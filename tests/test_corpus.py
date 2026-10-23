"""Corpus gate: every conformance artifact verifies and replays natively.

Mirrors parsanol-rs `tests/conformance.rs` and the shipped-artifact audits:
checksum verification must agree byte-for-byte with the reference compiler,
and every embedded accept/reject/capture case must replay identically.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from parsanol import PargArtifact

CORPUS_DIR = Path(
    os.environ.get("PARSANOL_CORPUS_DIR", "")
    or Path(__file__).resolve().parents[1] / "corpus" / "conformance"
)


def corpus_artifacts() -> list[Path]:
    if not CORPUS_DIR.is_dir():
        pytest.skip("corpus/conformance not present (set PARSANOL_CORPUS_DIR)")
    paths = sorted(CORPUS_DIR.glob("*.json"))
    assert paths, "corpus directory is empty"
    return paths


def test_every_artifact_checksum_verifies() -> None:
    """The Python canonical form agrees with the reference compiler's
    sha256 over every corpus artifact — the B6 float form included."""
    verified = 0
    for path in corpus_artifacts():
        artifact = PargArtifact.from_path(path)
        assert artifact.checksum and artifact.checksum.startswith("sha256:")
        verified += 1
    assert verified >= 30, f"unexpectedly small corpus: {verified}"


def test_every_embedded_case_replays() -> None:
    total = 0
    skipped = 0
    for path in corpus_artifacts():
        artifact = PargArtifact.from_path(path)
        for entry in artifact.entry_names():
            run = artifact.run_tests(entry)
            total += run.total
            skipped += len(run.skipped)
            assert not run.failures, f"{path.name}: {run.failures}"
    # The full corpus is 125 cases, all five test phases now evaluated.
    assert total == 125, f"corpus size moved: {total}"
    assert skipped == 0, f"unexpected skips: {skipped}"
