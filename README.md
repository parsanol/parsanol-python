# parsanol (Python)

Python runtime for **PARG artifacts** — checksummed `parsanol-tree/v2`
envelopes that Ruby, Rust, WebAssembly, TypeScript, and now Python all
parse identically.

The engine is the real one: this package drives `libparsanol` (the
pure-portable C ABI cdylib, the same binary the Ruby ffi tier ships) via
`ctypes`. No second parser, no reimplementation.

```python
from parsanol import PargArtifact

artifact = PargArtifact.from_path("demo.artifact.json")  # verifies sha256
tree = artifact.parse("iso 12345", "identifier")         # shaped tree
run = artifact.run_tests()                               # embedded tests replayed
```

On rejection, `parse` raises `ParseFailed` carrying the engine's failure
wire (`offset`, ranked positions, expected set).

## Status and honest boundaries (v0.1)

| Capability | State |
|---|---|
| Artifact load + sha256 verification | **works** — the canonical-form port is byte-exact against the reference compiler (all 32 corpus checksums verify) |
| Native parse (shaped tree, slice wire) | **works** |
| Failure wire | **works** |
| Embedded tests: accept / reject / capture | **works** — all 125 corpus cases replay with zero failures |
| Embedded tests: example / shape | skipped (17 cases) — needs the bindings + flattening port ([ticket 0003](docs/tickets/0003-bindings-and-flattening.md)) |
| `parse_recovering` | not yet — needs a C-ABI export ([ticket 0002](docs/tickets/0002-recovery-export.md)) |
| Dynamic / runtime-state artifacts | rejected upstream by contract (Ruby-tier) |
| Wheels on PyPI | not yet ([ticket 0001](docs/tickets/0001-packaging.md)) |

## Development

```sh
cargo build -p parsanol-ffi --release          # in parsanol-rs
export PARSANOL_CDYLIB=$RS/target/release/libparsanol.dylib
ln -s ../parsanol-rs/corpus corpus             # for the corpus gate
python3 -m pip install -e . pytest
python3 -m pytest tests -q
```

The corpus gate (`tests/test_corpus.py`) pins the sizes: 125 cases, 17
skips — when either moves, this repo moves with it deliberately.
