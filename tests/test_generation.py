"""Generation through the C ABI (parsanol >= 0.20.19, rs#459 slice 2).

Rust is the authoritative lowering; the Python runtime inherits it
through `parsanol_parg_generate` / `PargArtifact.generate`. The sealed
synthetic artifact (compiled by the Ruby compiler, checksummed, RAW
JSON so the load-time byte checksum verifies) carries a render spec
with a conditional face; the gate is the round-trip property — a
generated string re-parses to the same bound map — plus the pinned
oracle strings from the rs generate_parity receipt.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parsanol import PargArtifact, generate_available
from parsanol._ffi import ParsanolError
from parsanol.artifact import apply_bindings, reduce_slices

SEALED_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "generate_sealed.json"


def require_generate():
    if not generate_available():
        pytest.skip("the loaded libparsanol lacks parsanol_parg_generate (requires >= 0.20.19)")


@pytest.fixture(scope="module")
def artifact() -> PargArtifact:
    assert SEALED_FIXTURE.is_file(), "the sealed generate fixture must ship with the package"
    return PargArtifact(SEALED_FIXTURE.read_text(encoding="utf-8"))


def bound_of(artifact: PargArtifact, input_text: str) -> dict:
    shape = reduce_slices(artifact.parse(input_text))
    return apply_bindings(artifact, artifact.default_entry, shape)


def test_generate_round_trips_the_bound_map(artifact) -> None:
    require_generate()
    checked = 0
    for input_text in ["42", "42:1999"]:
        bound = bound_of(artifact, input_text)
        generated = artifact.generate("default", bound)
        re_bound = bound_of(artifact, generated)
        assert re_bound == bound, (
            f"{input_text!r} generated {generated!r} which re-binds differently"
        )
        checked += 1
    assert checked == 2


def test_generate_matches_the_interpreter_byte_for_byte(artifact) -> None:
    require_generate()
    # The interpreter and the lowered generator walk the same spec; the
    # engine-level parity gate proves byte-identity (rs#490). Here the
    # pinned strings anchor the wire shape across re-bakes.
    assert artifact.generate("default", {"number": "42"}) == "42"
    assert artifact.generate("default", {"number": "42", "year": "1999"}) == "42:1999"
    assert artifact.generate("default", {}) == ""


def test_generate_requires_the_generation_abi() -> None:
    # generate_available mirrors export_available: an old engine skips.
    assert isinstance(generate_available(), bool)


def test_generate_rejects_unknown_variants(artifact) -> None:
    require_generate()
    with pytest.raises(ParsanolError):
        artifact.generate("mystery", {"number": "1"})
