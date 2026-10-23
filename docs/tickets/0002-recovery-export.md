# 0002 — Recovery: needs a C-ABI export

`parse_recovering` (partial trees + declared resync spans) is not reachable
from Python: the C ABI exposes `parsanol_parg_parse` (strict, null on
failure) and `parsanol_parg_error` (failure wire) only. The recovery
envelope lives behind `PargArtifact::parse_shape_recovering` in
`parsanol::parg::suite`, which the cdylib never calls.

## Work

- [ ] parsanol-rs: add `parsanol_parg_parse_recovering(grammar_json, input)
      -> *mut c_char` next to `parsanol_parg_parse` in `parsanol::ffi::c`,
      returning the recovery envelope JSON
      (`{ok, partial, error, resyncs, captures, consumed_upto}`); owned,
      freed via `parsanol_parg_free`. Must appear in `parsanol-ffi`'s
      force-link list (the crate exists to publish those symbols).
- [ ] Wire-contract test in rs (the cdylib round-trips the same envelope
      the wasm `parseShapeRecovering` returns).
- [ ] Python: `PargArtifact.parse_recovering(input, entry)` returning the
      envelope as a dict; corpus differential vs the wasm wire (identical
      spans, e.g. `@@junk@@;` 8→17 on `recovery_resync_declared`).
- [ ] Release train: the export rides the next rs minor; the Python repo
      re-vendors the cdylib the same way the Ruby ext lock does.

## Acceptance

Python's recovery envelope equals the shipped wasm envelope for every
corpus case with a declared resync policy.
