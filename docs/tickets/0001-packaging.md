# 0001 — Packaging: wheels on PyPI

**Owner decisions needed before this ships** (per the library-laws: names
and supported floors are never agent calls):

1. PyPI package name — the skeleton assumes `parsanol`; confirm or rename.
2. `requires-python` floor — the skeleton uses `>=3.9`; confirm.
3. Release cadence — own train, or ride the parsanol-rs release (a new rs
   release makes the vendored cdylib stale, exactly like the Ruby ext lock).

**Owner decisions taken:** the name `parsanol` and trusted publishing
(project `parsanol`, owner `parsanol`, repo `parsanol-python`, workflow
`publish.yml`) are registered on PyPI. 0.1.0 was published first.

## Work

- [x] Build script: `cargo build -p parsanol-ffi --release` per target and
      stage `libparsanol.{dylib,so,dll}` into `src/parsanol/lib/` before
      `pip wheel` (the sdist builds nothing; wheels vendored-binary only,
      mirroring the Ruby native-gem model).
- [x] manylinux/macos/windows wheel matrix in CI. Policy: the wheel is
      pure Python plus a vendored binary, so setuptools tags it
      `py3-none-any`; every wheel is **retagged** with its real platform
      (`manylinux_2_35_x86_64`, `macosx_11_0_arm64`, `win_amd64`) before it
      is smoke-tested or uploaded. Without the retag the three OS builds
      collide as identically named `py3-none-any` files.
- [ ] `musllinux` + arm variants — same set as the Ruby gem platforms.
- [x] Trusted publishing to PyPI (the npm model: OIDC, no long-lived
      token).
- [x] Post-publish: a shipped-audit leg that `pip install`s the released
      wheel and replays the corpus through it (the audit is how every other
      runtime stays honest).

## 0.1.0 defect and the 0.1.1 remedy

0.1.0 (built by `python -m build` on the publish runner) shipped a
`py3-none-any` wheel with **no vendored cdylib**: `engine_version()` raised
`libparsanol not found`, so the artifact API could not parse anything. The
publish workflow did not stage the engine — only the wheels workflow did.

0.1.1 fixes the pipeline rather than the artifact: publishing now calls the
wheels workflow (which builds from the pinned parsanol-rs submodule, stages
the cdylib, retags the wheel, and smoke-tests it), publishes wheels only,
and audits the published release from PyPI on all three platforms. The
submodule is pinned to the current engine release (v0.19.7) so the vendored
binary understands the `edition` envelope field.

## Acceptance

`pip install parsanol` works on every supported platform; the audit leg
replays the full conformance corpus (155 cases, zero skips against the
rs 0.19.7 corpus) through the published wheel.
