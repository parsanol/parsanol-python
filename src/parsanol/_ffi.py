"""ctypes binding for the parsanol C ABI (libparsanol cdylib).

The C surface is the same pure-portable ABI the Ruby ffi tier drives:
`parsanol_parg_parse` returns the shaped tree as JSON on success (null on
failure), `parsanol_parg_error` returns the failure wire as JSON, and
`parsanol_parg_free` releases both. Nothing here interprets trees — that is
`parsanol.artifact`'s job.
"""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path

_LIB_NAMES = (
    "libparsanol.dylib",
    "libparsanol.so",
    "parsanol.dll",  # cargo emits no lib prefix on windows
    "libparsanol.dll",
)


class ParsanolError(RuntimeError):
    """The engine reported a hard error (registration, loading, ABI)."""

class NativeResourceError(ParsanolError):
    """A structured native rule-recursion guard, never a syntax refusal."""
    def __init__(self, wire: dict):
        self.wire = wire
        self.category = wire["category"]
        self.depth = wire["depth"]
        self.max_depth = wire["max_depth"]
        super().__init__(f"native parser {self.category}: depth {self.depth}, limit {self.max_depth}")



def _candidate_paths(library_path: str | Path | None = None) -> list[str]:
    if library_path is not None:
        return [str(library_path)]
    candidates: list[str] = []
    env = os.environ.get("PARSANOL_CDYLIB")
    if env:
        candidates.append(env)
    packaged = Path(__file__).resolve().parent / "lib"
    for name in _LIB_NAMES:
        candidates.append(str(packaged / name))
    for name in _LIB_NAMES:
        candidates.append(name)  # system loader search
    return candidates


_lib: ctypes.CDLL | None = None
_version: str | None = None


def _load_library(library_path: str | Path | None = None) -> tuple[ctypes.CDLL, str]:
    """Load and bind one library without changing the default context."""

    errors: list[str] = []
    lib: ctypes.CDLL | None = None
    for candidate in _candidate_paths(library_path):
        try:
            lib = ctypes.CDLL(candidate)
            break
        except OSError as error:  # noqa: PERF203 - small fixed list
            errors.append(f"{candidate}: {error}")
    if lib is None:
        raise ParsanolError(
            "libparsanol not found (build it with `cargo build -p parsanol-ffi "
            "--release` and point PARSANOL_CDYLIB at the dylib, or install a "
            "wheel that vendors it). Tried:\n  " + "\n  ".join(errors)
        )

    lib.parsanol_parg_parse.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    lib.parsanol_parg_parse.restype = ctypes.c_void_p
    lib.parsanol_parg_error.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    lib.parsanol_parg_error.restype = ctypes.c_void_p
    lib.parsanol_parg_free.argtypes = [ctypes.c_void_p]
    lib.parsanol_parg_free.restype = None
    # parsanol >= 0.18.19: the recovery export. Optional so an older cdylib
    # still loads; parse_recovering reports availability instead.
    if hasattr(lib, "parsanol_parg_parse_recovering"):
        lib.parsanol_parg_parse_recovering.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
        ]
        lib.parsanol_parg_parse_recovering.restype = ctypes.c_void_p
    # STATIC string — must never be freed (restype c_char_p copies it).
    lib.parsanol_version.argtypes = []
    lib.parsanol_version.restype = ctypes.c_char_p
    lib.parsanol_c_last_error.argtypes = []
    # STATIC string — must never be freed.
    lib.parsanol_c_last_error.restype = ctypes.c_char_p

    version = (lib.parsanol_version() or b"").decode("utf-8", errors="replace")
    return lib, version


class NativeContext:
    """An independent, lazily loaded C ABI library and its owned results.

    An explicit path is exclusive: failure never falls back to environment,
    packaged or system libraries. Sharing this object shares one native engine
    across artifacts without changing the module's default engine.
    """
    def __init__(self, library_path: str | Path | None = None):
        self.library_path = library_path
        self._lib: ctypes.CDLL | None = None
        self._version: str | None = None

    def load(self) -> ctypes.CDLL:
        if self._lib is None:
            self._lib, self._version = _load_library(self.library_path)
        return self._lib

    def engine_version(self) -> str:
        self.load()
        assert self._version is not None
        return self._version

    def parse_shaped(self, grammar_json: str, input_text: str):
        return parse_shaped(grammar_json, input_text, context=self)

    def parse_with_compatibility(self, envelope_json, entry, input_text, compatibility):
        return parse_with_compatibility(envelope_json, entry, input_text, compatibility, context=self)

    def failure_wire(self, grammar_json: str, input_text: str) -> dict:
        return failure_wire(grammar_json, input_text, context=self)

    def recovery_available(self) -> bool:
        return recovery_available(context=self)

    def parse_recovering(self, envelope_json: str, entry: str | None, input_text: str) -> dict:
        return parse_recovering(envelope_json, entry, input_text, context=self)

    def export_grammar(self, artifact_json: str, target: str, recovery: bool = False) -> str:
        return export_grammar(artifact_json, target, recovery, context=self)

    def generate_grammar(self, artifact_json: str, variant: str, model_json: str) -> str:
        return generate_grammar(artifact_json, variant, model_json, context=self)

    def mask_available(self) -> bool:
        return mask_available(context=self)

    def mask_open(self, artifact_json: str, entry: str | None = None,
                  vocab: list[tuple[int, str]] | None = None) -> int:
        return mask_open(artifact_json, entry, vocab, context=self)

    def mask_step(self, handle: int, prefix: str) -> bytes:
        return mask_step(handle, prefix, context=self)

    def mask_free(self, handle: int) -> None:
        mask_free(handle, context=self)


def load() -> ctypes.CDLL:
    """Load the default engine once, preserving existing lookup behavior."""
    global _lib, _version
    if _lib is None:
        _lib, _version = _load_library()
    return _lib


def engine_version() -> str:
    """The parsanol crate version compiled into the loaded cdylib."""
    load()
    assert _version is not None
    return _version


def _last_error(*, context: NativeContext | None = None) -> str:
    lib = context.load() if context is not None else load()
    pointer = lib.parsanol_c_last_error()
    if not pointer:
        return ""
    return pointer.decode("utf-8", errors="replace")


def _take_owned(pointer: int | None, *, context: NativeContext | None = None):
    """Read and free an owned result through the same library that created it."""
    lib = context.load() if context is not None else load()
    if not pointer:
        raise ParsanolError(_last_error(context=context) or "null result with no error text")
    try:
        return ctypes.string_at(pointer).decode("utf-8", errors="replace")
    finally:
        lib.parsanol_parg_free(ctypes.c_void_p(pointer))


def parse_shaped(grammar_json: str, input_text: str, *, context: NativeContext | None = None) -> dict | list | str | None:
    """Shaped (parsanol-shape) tree as Python objects; None on rejection."""
    lib = context.load() if context is not None else load()
    pointer = lib.parsanol_parg_parse(
        grammar_json.encode("utf-8"), input_text.encode("utf-8")
    )
    if not pointer:
        return None
    return json.loads(_take_owned(pointer, context=context))


def parse_with_compatibility(envelope_json: str, entry: str, input_text: str,
                             compatibility: str, *, context: NativeContext | None = None) -> dict:
    """Explicit strict/Parslet parsing; requires the additive native policy ABI.

    Unknown policies and unsupported engines fail rather than silently falling
    back to a different parsing or diagnostic contract.
    """
    if compatibility not in ("strict", "parslet"):
        raise ValueError("compatibility must be 'strict' or 'parslet'")
    for label, value in (("artifact", envelope_json), ("entry", entry), ("input", input_text)):
        if not isinstance(value, str):
            raise TypeError(f"{label} must be a str")
        if "\x00" in value:
            raise ValueError(f"{label} must not contain NUL")
    lib = context.load() if context is not None else load()
    if not hasattr(lib, "parsanol_parg_parse_with_compatibility"):
        raise ParsanolError("native engine does not expose explicit parsing compatibility")
    parse = lib.parsanol_parg_parse_with_compatibility
    parse.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    parse.restype = ctypes.c_void_p
    pointer = parse(envelope_json.encode("utf-8"), entry.encode("utf-8"),
                    input_text.encode("utf-8"), int(compatibility == "parslet"))
    result = json.loads(_take_owned(pointer, context=context))
    if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
        raise ParsanolError("invalid native compatibility result envelope")
    return result


def failure_wire(grammar_json: str, input_text: str, *, context: NativeContext | None = None) -> dict:
    """The failure wire (offset, expected, ...) for a rejected input."""
    lib = context.load() if context is not None else load()
    pointer = lib.parsanol_parg_error(
        grammar_json.encode("utf-8"), input_text.encode("utf-8")
    )
    if not pointer:
        raise ParsanolError(_last_error(context=context) or "failure wire unavailable")
    result = json.loads(_take_owned(pointer, context=context))
    return result if isinstance(result, dict) else {}


def recovery_available(*, context: NativeContext | None = None) -> bool:
    """Whether the loaded cdylib exports the recovery ABI (>= 0.18.19)."""
    return hasattr(context.load() if context is not None else load(), "parsanol_parg_parse_recovering")


def parse_recovering(
    envelope_json: str, entry: str | None, input_text: str, *, context: NativeContext | None = None
) -> dict:
    """The recovery envelope for an artifact envelope (checksum verified
    engine-side). Requires a cdylib with the recovery export."""
    lib = context.load() if context is not None else load()
    if not hasattr(lib, "parsanol_parg_parse_recovering"):
        raise ParsanolError(
            "the loaded libparsanol lacks parsanol_parg_parse_recovering "
            "(requires parsanol >= 0.18.19)"
        )
    pointer = lib.parsanol_parg_parse_recovering(
        envelope_json.encode("utf-8"),
        (entry.encode("utf-8") if entry is not None else None),
        input_text.encode("utf-8"),
    )
    if not pointer:
        raise ParsanolError(_last_error(context=context) or "recovery envelope unavailable")
    result = json.loads(_take_owned(pointer, context=context))
    return result if isinstance(result, dict) else {}


def export_available(*, context: NativeContext | None = None) -> bool:
    """Whether the loaded cdylib exports the constrained-decoder export
    ABI (requires parsanol >= 0.20.16, the Rust-authoritative export)."""
    lib = context.load() if context is not None else load()
    return hasattr(lib, "parsanol_parg_export")


def export_grammar(artifact_json: str, target: str, recovery: bool = False,
                   *, context: NativeContext | None = None) -> str:
    """Lower a checksum-verified artifact to a constrained-decoder
    grammar form: target "xgrammar" (EBNF `name ::= body`) or
    "llguidance" (Lark `name: body`, `start:` prologue); `recovery`
    lowers each declared resync pattern as an escape alternative at the
    repetition spine. Rust is the authoritative lowering — the Python
    runtime inherits it through this C-ABI surface instead of a
    per-language port. An unsupported construct or a recursive grammar
    raises ParsanolError naming the construct.
    """
    lib = context.load() if context is not None else load()
    if not hasattr(lib, "parsanol_parg_export"):
        raise ParsanolError(
            "the loaded libparsanol lacks parsanol_parg_export "
            "(requires parsanol >= 0.20.16)"
        )
    export = lib.parsanol_parg_export
    export.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    export.restype = ctypes.c_void_p
    pointer = export(
        artifact_json.encode("utf-8"),
        target.encode("utf-8"),
        1 if recovery else 0,
    )
    if not pointer:
        raise ParsanolError(_last_error(context=context) or "export unavailable")
    return _take_owned(pointer, context=context)


def generate_available(*, context: NativeContext | None = None) -> bool:
    """Whether the loaded cdylib exports the generation ABI (requires
    parsanol >= 0.20.19, the graduated generation path)."""
    lib = context.load() if context is not None else load()
    return hasattr(lib, "parsanol_parg_generate")


def generate_grammar(artifact_json: str, variant: str, model_json: str,
                     *, context: NativeContext | None = None) -> str:
    """Emit a render variant against a bound attribute map (rs#459
    slice 2 — the graduated generation path). `model_json` is the bound
    map as JSON text (what parse produces). Rust is the authoritative
    lowering — the Python runtime inherits it through this C-ABI
    surface instead of a per-language renderer.
    """
    lib = context.load() if context is not None else load()
    if not hasattr(lib, "parsanol_parg_generate"):
        raise ParsanolError(
            "the loaded libparsanol lacks parsanol_parg_generate "
            "(requires parsanol >= 0.20.19)"
        )
    generate = lib.parsanol_parg_generate
    generate.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
    generate.restype = ctypes.c_void_p
    pointer = generate(
        artifact_json.encode("utf-8"),
        variant.encode("utf-8"),
        model_json.encode("utf-8"),
    )
    if not pointer:
        raise ParsanolError(_last_error(context=context) or "generate unavailable")
    return _take_owned(pointer, context=context)


def mask_available(*, context: NativeContext | None = None) -> bool:
    """Whether the loaded cdylib exports the constrained-decoding mask
    ABI (rs#530: parsanol_mask_open/step/free)."""
    lib = context.load() if context is not None else load()
    return hasattr(lib, "parsanol_mask_open")


def mask_open(artifact_json: str, entry: str | None = None,
              vocab: list[tuple[int, str]] | None = None,
              *, context: NativeContext | None = None) -> int:
    """Open a constrained-decoding mask handle over a checksum-verified
    artifact entry and a tokenizer vocabulary (rs#530). `entry` may be
    None for the artifact's default entry; `vocab` is a list of
    (token id, decoded text) pairs and may be None to derive the
    vocabulary from the artifact's terminals (ids 1..n). Returns an
    opaque handle (free with mask_free); raises ParsanolError naming the
    failure (bad checksum, unknown entry, bad vocabulary).
    """
    lib = context.load() if context is not None else load()
    if not hasattr(lib, "parsanol_mask_open"):
        raise ParsanolError(
            "the loaded libparsanol lacks parsanol_mask_open (rs#530 mask ABI)"
        )
    if vocab is not None:
        if not vocab:
            raise ValueError("vocab must be a non-empty list of (id, text) pairs")
        seen: set[int] = set()
        for token_id, _text in vocab:
            if not isinstance(token_id, int) or isinstance(token_id, bool):
                raise TypeError("vocab ids must be ints")
            if token_id in seen:
                raise ValueError(f"duplicate token id {token_id} in vocab")
            seen.add(token_id)
        vocab_wire = json.dumps(
            [{"id": token_id, "text": text} for token_id, text in vocab],
            ensure_ascii=False,
        ).encode("utf-8")
    else:
        vocab_wire = None
    open_fn = lib.parsanol_mask_open
    open_fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
    open_fn.restype = ctypes.c_void_p
    handle = open_fn(
        artifact_json.encode("utf-8"),
        (entry.encode("utf-8") if entry is not None else None),
        vocab_wire,
    )
    if not handle:
        raise ParsanolError(_last_error(context=context) or "mask handle unavailable")
    return handle


def mask_step(handle: int, prefix: str, *, context: NativeContext | None = None) -> bytes:
    """The next-step token bitmask at `prefix` (the consumed text so
    far), in the llguidance wire format: bit i of word i/32 (packed
    little-endian u32 words) = token i allowed. The bytes legitimately
    contain interior NULs — this returns the exact wire length, never
    stopping at a NUL. The buffer is freed engine-side before returning.
    """
    lib = context.load() if context is not None else load()
    if not hasattr(lib, "parsanol_mask_step"):
        raise ParsanolError(
            "the loaded libparsanol lacks parsanol_mask_step (rs#530 mask ABI)"
        )
    step = lib.parsanol_mask_step
    step.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    step.restype = ctypes.c_int
    data = prefix.encode("utf-8")
    out = ctypes.c_void_p()
    out_len = ctypes.c_size_t()
    rc = step(ctypes.c_void_p(handle), data, len(data),
              ctypes.byref(out), ctypes.byref(out_len))
    if rc != 0:
        raise ParsanolError(_last_error(context=context)
                            or f"mask step failed (rc={rc})")
    try:
        return ctypes.string_at(out, out_len.value)
    finally:
        lib.parsanol_parg_free(ctypes.c_void_p(out.value))


def mask_free(handle: int, *, context: NativeContext | None = None) -> None:
    """Release a mask handle from mask_open. A freed handle must never
    be stepped again."""
    lib = context.load() if context is not None else load()
    if not hasattr(lib, "parsanol_mask_free"):
        raise ParsanolError(
            "the loaded libparsanol lacks parsanol_mask_free (rs#530 mask ABI)"
        )
    free = lib.parsanol_mask_free
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    free(ctypes.c_void_p(handle))
