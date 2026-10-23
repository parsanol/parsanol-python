# 0001 — Packaging: wheels on PyPI

**Owner decisions needed before this ships** (per the library-laws: names
and supported floors are never agent calls):

1. PyPI package name — the skeleton assumes `parsanol`; confirm or rename.
2. `requires-python` floor — the skeleton uses `>=3.9`; confirm.
3. Release cadence — own train, or ride the parsanol-rs release (a new rs
   release makes the vendored cdylib stale, exactly like the Ruby ext lock).

## Work

- [ ] Build script: `cargo build -p parsanol-ffi --release` per target and
      stage `libparsanol.{dylib,so,dll}` into `src/parsanol/lib/` before
      `pip wheel` (the sdist builds nothing; wheels vendored-binary only,
      mirroring the Ruby native-gem model).
- [ ] manylinux/macos/windows wheel matrix in CI (auditwheel or equivalent
      policy decision).
- [ ] `musllinux` + arm variants — same set as the Ruby gem platforms.
- [ ] Trusted publishing to PyPI (the npm model: OIDC, no long-lived
      token).
- [ ] Post-publish: a shipped-audit leg that `pip install`s the released
      wheel and replays the corpus through it (the audit is how every other
      runtime stays honest).

## Acceptance

`pip install parsanol` works on every supported platform; the audit leg
replays 125/125 corpus cases (17 documented skips) against the published
wheel.
