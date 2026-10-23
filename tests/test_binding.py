"""Binding smoke tests: engine load, shaped parse, failure wire, float form."""

from __future__ import annotations

import pytest

from parsanol import PargArtifact, ParseFailed, canonical_json, engine_version, ruby_json_float

GRAMMAR = '{"root": 0, "atoms": [{"Str": {"pattern": "ab"}}]}'


def test_engine_loads_and_reports_version() -> None:
    version = engine_version()
    assert version
    assert version.split(".")[0].isdigit()


def test_shaped_parse_success() -> None:
    from parsanol import _ffi

    shaped = _ffi.parse_shaped(GRAMMAR, "ab")
    assert shaped is not None
    assert '"value":"ab"' in canonical_json(shaped) or "ab" in str(shaped)


def test_failure_wire_carries_offset() -> None:
    from parsanol import _ffi

    wire = _ffi.failure_wire(GRAMMAR, "zz")
    assert "offset" in wire


def test_ruby_json_float_forms() -> None:
    # Ground truth ported from parsanol-rs float_tests (Ruby JSON gem
    # JSON.generate on ruby 3.4, JSON gem 2.x).
    cases = [
        (0.1, "0.1"),
        (1.5, "1.5"),
        (2.0, "2.0"),
        (100.0, "100.0"),
        (-2.5, "-2.5"),
        (-0.0, "-0.0"),
        (0.0, "0.0"),
        (0.0001, "0.0001"),
        (1e-5, "0.00001"),
        (1e-8, "0.00000001"),
        (1.5e-10, "1.5e-10"),
        (5e-324, "5e-324"),
        (12345.6789, "12345.6789"),
        (123456789012345.0, "123456789012345.0"),
        (999999999999999.9, "999999999999999.9"),
        (1e15, "1e+15"),
        (1e16, "1e+16"),
        (1e17, "1e+17"),
        (1e300, "1e+300"),
        (1.7976931348623157e308, "1.7976931348623157e+308"),
    ]
    for value, want in cases:
        assert ruby_json_float(value) == want, f"{value!r}: {ruby_json_float(value)!r} != {want!r}"


def test_canonical_json_key_order_and_escapes() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert canonical_json({"k": "a\"b\\c\n"}) == '{"k":"a\\"b\\\\c\\n"}'


def test_checksum_rejects_tampering(tmp_path) -> None:
    artifact = PargArtifact.from_path(
        _corpus() / "recovery_resync_declared.json"
    )
    tampered = dict(artifact.envelope)
    tampered["grammar"] = "Tampered"
    import json

    with pytest.raises(ValueError, match="checksum mismatch"):
        PargArtifact(json.dumps(tampered))


def test_parse_failure_raises_with_wire() -> None:
    artifact = PargArtifact.from_path(_corpus() / "recovery_resync_declared.json")
    with pytest.raises(ParseFailed) as excinfo:
        artifact.parse("a=1;b=2;@@junk@@;c=3;d=4;", "main")
    assert excinfo.value.wire.get("offset") == 8


def _corpus():
    import os
    from pathlib import Path

    return Path(
        os.environ.get("PARSANOL_CORPUS_DIR", "")
        or Path(__file__).resolve().parents[1] / "corpus" / "conformance"
    )
