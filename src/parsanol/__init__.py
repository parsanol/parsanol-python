"""parsanol — Python runtime for PARG artifacts.

Loads checksummed parsanol-tree/v2 artifacts and parses through the parsanol
C ABI (the same engine the Ruby, Rust, wasm, and TypeScript runtimes use).
"""

from .artifact import ParseFailed, PargArtifact, TestRun, apply_bindings
from .bindings import Bindings, BindingsError, canonical as canonical_value, collect_captures
from .canonical import canonical_json, checksum_hex, ruby_json_float, verify_checksum
from ._ffi import ParsanolError, engine_version, load

__version__ = "0.1.1"

__all__ = [
    "Bindings",
    "BindingsError",
    "PargArtifact",
    "ParseFailed",
    "ParsanolError",
    "TestRun",
    "apply_bindings",
    "canonical_json",
    "canonical_value",
    "checksum_hex",
    "collect_captures",
    "engine_version",
    "load",
    "ruby_json_float",
    "verify_checksum",
    "__version__",
]
