"""parsanol — Python runtime for PARG artifacts.

Loads checksummed parsanol-tree/v2 artifacts and parses through the parsanol
C ABI (the same engine the Ruby, Rust, wasm, and TypeScript runtimes use).
"""

from .artifact import ParseFailed, PargArtifact, TestRun, apply_bindings
from .bindings import Bindings, BindingsError, canonical as canonical_value, collect_captures
from .canonical import canonical_json, checksum_hex, ruby_json_float, verify_checksum
from ._ffi import ParsanolError, engine_version, load

try:
    # The installed distribution's version is authoritative: pyproject is
    # the single source, and a hardcoded literal here went stale (0.1.1
    # reported by 0.1.2 wheels, ruby#369's packaging twin).
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("parsanol")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0.dev0"

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
