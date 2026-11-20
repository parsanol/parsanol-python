"""vLLM logits-processor integration for parsanol grammar masks (rs#530).

`ParsanolLogitsProcessor` implements the vLLM LogitsProcessor INTERFACE
— `__call__(self, input_ids, scores) -> scores` — by stepping the
engine's constrained-decoding oracle over the consumed token ids and
applying the returned bitmask: every token the grammar disallows goes
to -inf, so any sampler picks a grammar-valid token and the generated
text parses by construction.

No torch or vLLM dependency is required: the base class is vLLM's
LogitsProcessor when vLLM imports, else a torch.nn.Module when torch
imports, else a plain callable — the mask math runs on plain lists and
arrays either way. `input_ids` may be a list of ints or a torch tensor.
"""

from __future__ import annotations

from parsanol._ffi import (
    ParsanolError,
    mask_available,
    mask_free,
    mask_open,
    mask_step,
)

try:  # pragma: no cover - exercised only where torch is installed
    import torch
except ImportError:  # pragma: no cover
    torch = None  # type: ignore[assignment]

try:  # pragma: no cover - exercised only where vLLM is installed
    from vllm.model_executor.layers.logits_processor import (
        LogitsProcessor as _VllmLogitsProcessor,
    )
except Exception:  # pragma: no cover - vLLM absent or its layout moved
    _VllmLogitsProcessor = None


def _bits_of(wire: bytes) -> list[int]:
    """The packed little-endian u32 words of the llguidance wire."""
    return [int.from_bytes(wire[i : i + 4], "little")
            for i in range(0, len(wire), 4)]


def _is_allowed(words: list[int], token_id: int) -> bool:
    """Bit i of word i/32 = token i allowed (out-of-wire ids: masked)."""
    word = token_id // 32
    return word < len(words) and (words[word] >> (token_id % 32)) & 1 == 1


class _PurePythonLogitsProcessor:
    """The interface contract when neither vLLM nor torch is present."""

    def __call__(self, input_ids, scores):
        return self.apply_mask(input_ids, scores)

    # A vLLM-shaped repr so debuggers and wrappers see a processor.
    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"{type(self).__name__}()"


if _VllmLogitsProcessor is not None:  # pragma: no cover - needs vLLM
    _ProcessorBase = _VllmLogitsProcessor
elif torch is not None:  # pragma: no cover - needs torch

    class _ProcessorBase(torch.nn.Module):  # type: ignore[no-redef]
        """torch.Module base so the processor slots into Module machinery."""

        def __call__(self, input_ids, scores):
            return self.apply_mask(input_ids, scores)

else:
    _ProcessorBase = _PurePythonLogitsProcessor


class ParsanolLogitsProcessor(_ProcessorBase):
    """The grammar mask as a logits processor: input_ids + scores in,
    scores out with every grammar-invalid token at -inf.

    `artifact_json` is a checksum-verified parsanol-tree/v2 artifact's
    text; `vocab` is the tokenizer's decoded vocabulary as a list of
    (token id, decoded text) pairs (required: the prefix is reconstructed
    from the ids). `entry` selects the artifact entry (None = the
    default). `library_path`/`native_context` pin an engine like
    `PargArtifact` does. Raises ParsanolError when the loaded cdylib
    lacks the mask ABI or the engine rejects the artifact/vocabulary.
    """

    def __init__(self, artifact_json: str, vocab: list[tuple[int, str]],
                 entry: str | None = None, *, library_path=None,
                 native_context=None):
        if not mask_available(context=native_context):
            raise ParsanolError(
                "the loaded libparsanol lacks parsanol_mask_open (rs#530 mask ABI)"
            )
        if not vocab:
            raise ValueError("vocab must be a non-empty list of (id, text) pairs")
        self._context = native_context
        self._text_of = {}
        seen: set[int] = set()
        for token_id, text in vocab:
            token_id = int(token_id)
            if token_id in seen:
                raise ValueError(f"duplicate token id {token_id} in vocab")
            seen.add(token_id)
            self._text_of[token_id] = str(text)
        # mask_open re-validates and hands the wire to the engine.
        self._handle = mask_open(artifact_json, entry=entry,
                                 vocab=[(i, t) for i, t in self._text_of.items()],
                                 context=native_context)
        self.library_path = library_path

    # -- interface ---------------------------------------------------------

    def prefix_text(self, input_ids) -> str:
        """The consumed text: the ids' decoded texts, concatenated."""
        return "".join(self._token_text(token_id)
                       for token_id in self._as_id_list(input_ids))

    def mask_for(self, input_ids) -> bytes:
        """The next-step bitmask at the consumed prefix (the llguidance
        wire: bit i of word i/32, little-endian)."""
        return mask_step(self._handle, self.prefix_text(input_ids),
                         context=self._context)

    def apply_mask(self, input_ids, scores):
        """The logits pass: scores with every masked-out token at -inf."""
        return self.mask_scores(self.mask_for(input_ids), scores)

    @staticmethod
    def mask_scores(wire: bytes, scores):
        """The mask math itself: score[i] = -inf where bit i of word i/32
        is clear. Runs on plain lists always; torch tensors take the
        guarded tensor path when torch is present."""
        words = _bits_of(wire)
        if torch is not None and isinstance(scores, torch.Tensor):  # pragma: no cover - needs torch
            vocab_size = scores.shape[-1]
            blocked = torch.tensor(
                [not _is_allowed(words, i) for i in range(vocab_size)],
                device=scores.device,
            )
            return scores.masked_fill(blocked, float("-inf"))
        return [score if _is_allowed(words, i) else float("-inf")
                for i, score in enumerate(scores)]

    def __call__(self, input_ids, scores):
        return self.apply_mask(input_ids, scores)

    # -- plumbing ----------------------------------------------------------

    def close(self) -> None:
        """Release the native handle. Idempotent; a closed processor
        raises on further use."""
        handle, self._handle = getattr(self, "_handle", 0), 0
        if handle:
            mask_free(handle, context=getattr(self, "_context", None))

    def __enter__(self) -> "ParsanolLogitsProcessor":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _as_id_list(self, input_ids) -> list[int]:
        if torch is not None and isinstance(input_ids, torch.Tensor):  # pragma: no cover - needs torch
            return [int(v) for v in input_ids.reshape(-1).tolist()]
        return [int(token_id) for token_id in input_ids]

    def _token_text(self, token_id: int) -> str:
        try:
            return self._text_of[token_id]
        except KeyError:
            raise ValueError(
                f"input id {token_id} is not in the processor vocabulary"
            ) from None

    def __del__(self):  # pragma: no cover - best-effort cleanup
        try:
            self.close()
        except Exception:
            pass
