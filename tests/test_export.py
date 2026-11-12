"""Constrained-decoding export through the C ABI (parsanol >= 0.20.16).

Rust is the authoritative lowering; the Python runtime inherits it
through `parsanol_parg_export` and asserts the recorded oracle bytes —
the same sha-pinned corpus fixture parsanol-rs
`tests/export_parity.rs` replays (skip on re-bake drift, the
corpus-gate philosophy).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from parsanol import PargArtifact, export_available
from parsanol._ffi import ParsanolError

CORPUS_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "export_parity_corpus.json"


def corpus_dir() -> Path:
    return Path(
        os.environ.get("PARSANOL_CORPUS_DIR", "")
        or Path(__file__).resolve().parents[1] / "corpus" / "conformance"
    )


def require_export():
    if not export_available():
        pytest.skip("the loaded libparsanol lacks parsanol_parg_export (requires >= 0.20.16)")


@pytest.fixture(scope="module")
def fixture_cases() -> list[dict]:
    assert CORPUS_FIXTURE.is_file(), "the corpus export fixture must ship with the package"
    return json.loads(CORPUS_FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_corpus_export_bytes_match_the_ruby_oracle(fixture_cases) -> None:
    require_export()
    artifacts = corpus_dir()
    if not artifacts.is_dir():
        pytest.skip("no PARSANOL_CORPUS_DIR and no bundled corpus")
    checked = 0
    stale = 0
    for case in fixture_cases:
        path = artifacts / f"{case['artifact']}.json"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if hashlib.sha256(text.encode()).hexdigest() != case["artifact_sha256"]:
            stale += 1
            continue
        artifact = PargArtifact.from_path(path)
        if "export" in case:
            try:
                actual = artifact.export(case["target"], case["recovery"])
            except ParsanolError as error:
                pytest.fail(f"{case['artifact']}: unexpected rejection: {error}")
            assert actual == case["export"], (
                f"{case['artifact']} ({case['target']}"
                f"{' +recovery' if case['recovery'] else ''}): bytes diverge"
            )
        else:
            with pytest.raises(ParsanolError) as raised:
                artifact.export(case["target"], case["recovery"])
            assert str(raised.value) == case["error"], (
                f"{case['artifact']}: rejection message diverges: {raised.value}"
            )
        checked += 1
    assert checked >= 20, f"corpus export parity checked only {checked} artifacts"
    if stale:
        print(f"stale (re-baked since the fixture was recorded): {stale} cases skipped")


def test_unknown_target_names_itself() -> None:
    require_export()
    artifacts = sorted(corpus_dir().glob("*.json")) if corpus_dir().is_dir() else []
    if not artifacts:
        pytest.skip("no checksummed corpus artifact present (set PARSANOL_CORPUS_DIR)")
    artifact = PargArtifact.from_path(artifacts[0])
    with pytest.raises(ParsanolError) as raised:
        artifact.export("gbnf")
    assert "unknown export target" in str(raised.value)
