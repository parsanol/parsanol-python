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


def _candidate_paths() -> list[str]:
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


def load() -> ctypes.CDLL:
    """dlopen the cdylib once and bind the entry points."""
    global _lib, _version
    if _lib is not None:
        return _lib

    errors: list[str] = []
    lib: ctypes.CDLL | None = None
    for candidate in _candidate_paths():
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

    _lib = lib
    _version = (lib.parsanol_version() or b"").decode("utf-8", errors="replace")
    return lib


def engine_version() -> str:
    """The parsanol crate version compiled into the loaded cdylib."""
    load()
    assert _version is not None
    return _version


def _last_error() -> str:
    assert _lib is not None
    pointer = _lib.parsanol_c_last_error()
    if not pointer:
        return ""
    return pointer.decode("utf-8", errors="replace")


def _take_owned(pointer: int | None):
    """Decode an OWNED C string (parse/error results) and free it."""
    assert _lib is not None
    if not pointer:
        raise ParsanolError(_last_error() or "null result with no error text")
    text = ctypes.string_at(pointer).decode("utf-8", errors="replace")
    _lib.parsanol_parg_free(ctypes.c_void_p(pointer))
    return text


def parse_shaped(grammar_json: str, input_text: str) -> dict | list | str | None:
    """Shaped (parsanol-shape) tree as Python objects; None on rejection."""
    lib = load()
    pointer = lib.parsanol_parg_parse(
        grammar_json.encode("utf-8"), input_text.encode("utf-8")
    )
    if not pointer:
        return None
    return json.loads(_take_owned(pointer))


def failure_wire(grammar_json: str, input_text: str) -> dict:
    """The failure wire (offset, expected, ...) for a rejected input."""
    lib = load()
    pointer = lib.parsanol_parg_error(
        grammar_json.encode("utf-8"), input_text.encode("utf-8")
    )
    if not pointer:
        raise ParsanolError(_last_error() or "failure wire unavailable")
    result = json.loads(_take_owned(pointer))
    return result if isinstance(result, dict) else {}


def recovery_available() -> bool:
    """Whether the loaded cdylib exports the recovery ABI (>= 0.18.19)."""
    return hasattr(load(), "parsanol_parg_parse_recovering")


def parse_recovering(
    envelope_json: str, entry: str | None, input_text: str
) -> dict:
    """The recovery envelope for an artifact envelope (checksum verified
    engine-side). Requires a cdylib with the recovery export."""
    lib = load()
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
        raise ParsanolError(_last_error() or "recovery envelope unavailable")
    result = json.loads(_take_owned(pointer))
    return result if isinstance(result, dict) else {}
