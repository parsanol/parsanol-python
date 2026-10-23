# 0003 — Bindings application and the flattening port

The v1 test runner skips `example` (bindings layer, 8 corpus cases) and
`shape` (whole-tree flattening, 9 cases). Closing this makes Python's
replay 125/125 with zero skips.

## Work

- [ ] Port the flatten laws V0–V4 from `docs/parg-semantics.md` (the
      sequence merge ⊕ table — note the map-beside-array FLAT append — and
      the named-context rule: a capture's direct value only). The archived
      B2 validator (`parsanol-rs/tools/spec-validator/validate.py`) is a
      working Python reference for exactly these laws — lift from there
      rather than translating the Rust.
- [ ] Port `apply_bindings` (types, cardinalities, `[]` paths one level,
      `preprocess: table_lookup` against the artifact's tables section).
- [ ] Enable `example` and `shape` phases in `run_tests`; drop the skip
      accounting and pin 125/125 with zero skips.
- [ ] Keep the slice-reduction discipline: reduce `{offset,length,line,
      column,value}` to text before flattening (terminals reduce to their
      text — the suite's canonical comparison form).

## Acceptance

`python3 -m pytest tests -q` green with `skipped == 0`; the corpus gate
asserts it.
