"""Recovery through the C ABI: the envelope must equal the wasm wire,
declared resync spans included (parsanol >= 0.18.19)."""

from __future__ import annotations

import pytest

from parsanol import PargArtifact


@pytest.fixture()
def artifact() -> PargArtifact:
    path = _corpus() / "recovery_resync_declared.json"
    if not path.is_file():
        pytest.skip("corpus not present")
    return PargArtifact.from_path(path)


def _corpus():
    import os
    from pathlib import Path

    return Path(
        os.environ.get("PARSANOL_CORPUS_DIR", "")
        or Path(__file__).resolve().parents[1] / "corpus" / "conformance"
    )


def test_recovery_supported(artifact: PargArtifact) -> None:
    if not artifact.recovery_supported():
        pytest.skip("loaded libparsanol predates the recovery export (0.18.19)")


def _require_recovery(artifact: PargArtifact) -> None:
    if not artifact.recovery_supported():
        pytest.skip("loaded libparsanol predates the recovery export (0.18.19)")


def test_failure_envelope_with_declared_resync(artifact: PargArtifact) -> None:
    _require_recovery(artifact)
    env = artifact.parse_recovering("a=1;b=2;@@junk@@;c=3;d=4;", "main")
    assert env["ok"] is False
    items = env["partial"]["document"]
    assert len(items) == 4, f"expected all four pairs, got {len(items)}"
    third = env["partial"]["document"][2]
    assert third["k"]["value"] == "c" and third["v"]["value"] == "3"
    assert env["error"]["offset"] == 8
    assert len(env["resyncs"]) == 1
    span = env["resyncs"][0]
    assert span["skipped"] == "@@junk@@;"
    assert span["offset"] == 8
    assert span["resumed_at"] == 17


def test_success_envelope_is_the_shape(artifact: PargArtifact) -> None:
    _require_recovery(artifact)
    env = artifact.parse_recovering("a=1;b=2;", "main")
    assert env["ok"] is True
    assert env["shape"] == artifact.parse("a=1;b=2;", "main")


def test_null_entry_selects_the_default(artifact: PargArtifact) -> None:
    _require_recovery(artifact)
    from parsanol import _ffi

    env = _ffi.parse_recovering(artifact.envelope_text, None, "a=1;b=2;")
    assert env["ok"] is True
