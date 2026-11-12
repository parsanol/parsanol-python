"""Constrained-decoding export through the C ABI (parsanol >= 0.20.16).

Rust is the authoritative lowering; the Python runtime inherits it
through `parsanol_parg_export` and asserts the Ruby oracle's recorded
bytes over SEALED synthetic artifacts — real .parg sources compiled by
the oracle compiler (checksummed, so the C ABI's verification accepts
them), self-contained in the fixture: escapes, folds, bounded
repetitions on both targets, the expansion cap, the lookahead and
recursive-grammar rejections, and the recovery spine wrap.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from parsanol import PargArtifact, export_available
from parsanol._ffi import ParsanolError

SEALED_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "export_parity_sealed.json"


def require_export():
    if not export_available():
        pytest.skip("the loaded libparsanol lacks parsanol_parg_export (requires >= 0.20.16)")


@pytest.fixture(scope="module")
def sealed_cases() -> list[dict]:
    assert SEALED_FIXTURE.is_file(), "the sealed export fixture must ship with the package"
    return json.loads(SEALED_FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_sealed_artifacts_match_the_ruby_oracle_byte_for_byte(sealed_cases) -> None:
    require_export()
    checked = 0
    for case in sealed_cases:
        artifact = PargArtifact(case["artifact_text"])
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
    assert checked >= 16, f"the sealed fixture shrank: {checked} cases"


def test_unknown_target_names_itself(sealed_cases) -> None:
    require_export()
    artifact = PargArtifact(sealed_cases[0]["artifact_text"])
    with pytest.raises(ParsanolError) as raised:
        artifact.export("gbnf")
    assert "unknown export target" in str(raised.value)
