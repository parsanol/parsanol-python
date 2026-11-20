"""The vLLM logits-processor integration (rs#530's runtime slice).

The mask math runs on plain lists ALWAYS — no torch, no vLLM. The torch
tensor path skips without torch. The validity loop drives the processor
over the isbn and json acceptance artifacts sampling through the mask
exactly like the rust receipt (the lowest allowed id), asserting 100%
grammar-valid output — the scorer is the artifact oracle itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parsanol import PargArtifact
from parsanol._ffi import ParsanolError, mask_available, mask_free, mask_open, mask_step
from parsanol.contrib.vllm import ParsanolLogitsProcessor

# The acceptance artifacts, byte-identical to the engine's
# parsanol/tests/constrain_fixtures at the pinned engine revision (the
# same bytes the mask receipt and the rust mask-ffi suite run on).
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ISBN = FIXTURES / "constrain_isbn.json"
JSON = FIXTURES / "constrain_json.json"

ISBN_ENTRY = "identifier"
JSON_ENTRY = "main"

# The receipt's vocabularies: the tokens of an ISBN- / json-shaped
# generation, ids mirroring the rust-level constrain fixtures.
ISBN_VOCAB = [(1, "ISBN"), (2, " "), (3, ":"), (4, "0"), (5, "9"), (6, "7"),
              (7, "8"), (8, "-"), (9, "X"), (10, "978"), (11, "-0")]
JSON_VOCAB = [(1, "{"), (2, "}"), (3, '"'), (4, "a"), (5, ":"), (6, ","),
              (7, "1"), (8, " "), (9, "["), (10, "]")]


def require_mask():
    if not mask_available():
        pytest.skip("the loaded libparsanol lacks the rs#530 mask exports")


def isbn_processor() -> ParsanolLogitsProcessor:
    return ParsanolLogitsProcessor(ISBN.read_text(encoding="utf-8"), ISBN_VOCAB,
                                   entry=ISBN_ENTRY)


def json_processor() -> ParsanolLogitsProcessor:
    return ParsanolLogitsProcessor(JSON.read_text(encoding="utf-8"), JSON_VOCAB,
                                   entry=JSON_ENTRY)


def test_processor_masks_invalid_tokens_on_plain_lists() -> None:
    require_mask()
    processor = isbn_processor()
    try:
        # At the empty prefix the hyphen cannot start; "ISBN" can.
        masked = processor([], [0.0] * 12)
        assert masked[8] == float("-inf"), "the hyphen must be masked out"
        assert masked[1] == 0.0, "ISBN stays at its score"
        assert masked[4] == 0.0, "a digit stays at its score"

        # After "978" (id 10) the hyphen continues; the prefix cannot reopen.
        masked = processor([10], [0.0] * 12)
        assert masked[8] == 0.0
        assert masked[1] == float("-inf")

        # After "978-" (ids [10, 8]) the demanded group continues: a digit
        # or the X check-digit class, never the "ISBN" literal.
        masked = processor([10, 8], [0.0] * 12)
        assert masked[9] == 0.0, "X continues the demanded group"
        assert masked[4] == 0.0, "a digit continues the demanded group"
        assert masked[1] == float("-inf")
    finally:
        processor.close()


def test_mask_scores_beyond_the_wire_are_masked() -> None:
    require_mask()
    processor = isbn_processor()
    try:
        wire = processor.mask_for([])
        # An 11-token vocab tops out inside word 1; scores[12] is out of
        # the wire and must be masked conservatively.
        scores = [1.0] * 40
        masked = processor.mask_scores(wire, scores)
        assert masked[12] == float("-inf")
        assert masked[1] == 1.0
        assert len(masked) == 40
    finally:
        processor.close()


def test_unknown_input_id_raises_a_clear_error() -> None:
    require_mask()
    processor = isbn_processor()
    try:
        with pytest.raises(ValueError, match="not in the processor vocabulary"):
            processor([999], [0.0])
    finally:
        processor.close()


def test_processor_rejects_bad_vocab_and_bad_artifacts() -> None:
    require_mask()
    with pytest.raises(ValueError, match="non-empty"):
        ParsanolLogitsProcessor(ISBN.read_text(encoding="utf-8"), [])
    with pytest.raises(ValueError, match="duplicate"):
        ParsanolLogitsProcessor(ISBN.read_text(encoding="utf-8"), [(1, "a"), (1, "b")])
    with pytest.raises((ParsanolError, ValueError)):
        ParsanolLogitsProcessor("not an artifact", ISBN_VOCAB)
    with pytest.raises((ParsanolError, ValueError)):
        ParsanolLogitsProcessor(ISBN.read_text(encoding="utf-8"), ISBN_VOCAB,
                                entry="no-such-entry")


def test_native_context_isolation() -> None:
    from parsanol import NativeContext

    require_mask()
    context = NativeContext()
    handle = context.mask_open(ISBN.read_text(encoding="utf-8"), ISBN_ENTRY, ISBN_VOCAB)
    wire = context.mask_step(handle, "978")
    assert wire and not all(b == 0 for b in wire), "the hyphen continues 978"
    assert context.mask_available()
    context.mask_free(handle)


def test_ffi_level_terminal_vocabulary_open() -> None:
    require_mask()
    handle = mask_open(ISBN.read_text(encoding="utf-8"))
    try:
        wire = mask_step(handle, "")
        assert len(wire) % 4 == 0
        assert any(b != 0 for b in wire), "the ISBN terminal starts the identifier"
    finally:
        mask_free(handle)


def test_torch_tensor_path() -> None:
    torch = pytest.importorskip("torch")
    require_mask()
    processor = isbn_processor()
    try:
        scores = torch.zeros(12)
        masked = processor([], scores)
        assert masked[8].item() == float("-inf")
        assert masked[1].item() == 0.0
        assert isinstance(masked, torch.Tensor)

        ids = torch.tensor([10])
        masked = processor(ids, scores)
        assert masked[8].item() == 0.0
    finally:
        processor.close()


def _generate_valid(processor: ParsanolLogitsProcessor, artifact: PargArtifact,
                    entry: str, generations: int, cap: int = 40) -> tuple[int, int]:
    """The receipt's deterministic loop through the processor: per step
    apply the processor's mask, sample the lowest allowed id, continue
    until the artifact parses. Returns (valid, tokens)."""
    valid = 0
    tokens = 0
    for _ in range(generations):
        ids: list[int] = []
        picked: list[int] = []
        for _ in range(cap):
            wire = processor.mask_for(ids)
            bit = next((i for i in range(len(wire) * 8)
                        if (wire[i // 8] >> (i % 8)) & 1), None)
            assert bit is not None, "the mask drained: no valid continuation"
            ids.append(bit)
            picked.append(bit)
            text = processor.prefix_text(ids)
            try:
                artifact.parse(text, entry)
                break
            except Exception:
                continue
        text = processor.prefix_text(ids)
        artifact.parse(text, entry)  # ParseFailed on any invalid output
        replay = "".join(processor._text_of[i] for i in picked)
        assert replay == text, "the picks concatenate to the output"
        valid += 1
        tokens += len(picked)
    return valid, tokens


def test_validity_loop_isbn_is_100_percent_grammar_valid() -> None:
    require_mask()
    processor = isbn_processor()
    artifact = PargArtifact.from_path(ISBN)
    try:
        valid, tokens = _generate_valid(processor, artifact, ISBN_ENTRY, 200)
    finally:
        processor.close()
    assert valid == 200, "validity must be 100%"
    print(f"isbn: validity {valid}/200 ({tokens} tokens)")


def test_validity_loop_json_is_100_percent_grammar_valid() -> None:
    require_mask()
    processor = json_processor()
    artifact = PargArtifact.from_path(JSON)
    try:
        valid, tokens = _generate_valid(processor, artifact, JSON_ENTRY, 200)
    finally:
        processor.close()
    assert valid == 200, "validity must be 100%"
    print(f"json: validity {valid}/200 ({tokens} tokens)")


def test_every_masked_survivor_is_grammar_safe() -> None:
    """The processor's core promise: after masking, EVERY surviving token
    either completes the grammar or consumes past the boundary — the
    recovering envelope's oracle, exactly the rust-side acceptance rule.
    No sampler choice among survivors can dead-end the generation."""
    require_mask()
    processor = isbn_processor()
    artifact = PargArtifact.from_path(ISBN)
    try:
        def parses(text: str) -> bool:
            try:
                artifact.parse(text, ISBN_ENTRY)
                return True
            except Exception:
                return False

        ids: list[int] = []
        completed = False
        for _ in range(40):
            if parses(processor.prefix_text(ids)):
                completed = True
                break
            text = processor.prefix_text(ids)
            boundary = len(text.encode("utf-8"))
            masked = processor(ids, [0.0] * 12)
            survivors = [i for i, s in enumerate(masked) if s != float("-inf")]
            assert survivors, "the mask must leave a continuation"
            for token_id in survivors:
                candidate = text + processor._text_of[token_id]
                envelope = artifact.parse_recovering(candidate, ISBN_ENTRY)
                assert envelope.get("ok") is True \
                    or envelope.get("consumed_upto", 0) > boundary, (
                    f"{processor._text_of[token_id]!r} survived the mask "
                    f"but dead-ends at {text!r}")
            ids.append(survivors[0])
        assert completed, "the masked walk must reach a full parse"
    finally:
        processor.close()
