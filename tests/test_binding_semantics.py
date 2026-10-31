"""Bindings semantics mirrors: ts#34 null skips, ruby#381 instance
pairing, rs#370 zero-instance skip."""

from __future__ import annotations

from parsanol import Bindings, apply_bindings


def _envelope(bindings: list[dict]) -> dict:
    return {
        "entries": {
            "identifier": {"bindings": bindings},
        },
    }


def test_null_capture_binds_nothing() -> None:
    # ts#34: the absent-optional wire is null; the key is skipped,
    # never cast to "".
    bindings = Bindings(
        _envelope(
            [
                {"capture": "year", "path": "year", "type": "string"},
                {
                    "capture": "amd_reaffirmed",
                    "path": "amd_reaffirmed",
                    "type": "string",
                },
            ]
        ),
        "identifier",
    )
    shape = {"year": "1997", "amd_reaffirmed": None}
    assert bindings.apply(shape) == {"year": "1997"}


def test_zero_instance_array_binding_binds_nothing() -> None:
    # rs#370: the tree carries `parts: []` for the zero-iteration
    # repetition; the bound map omits the key.
    bindings = Bindings(
        _envelope(
            [
                {"capture": "tail", "path": "tail", "type": "string"},
                {"capture": "part_code", "path": "parts[].part_code", "type": "string"},
            ]
        ),
        "identifier",
    )
    shape = {
        "tail": "AB",
        "parts": [],
    }
    assert bindings.apply(shape) == {"tail": "AB"}


def test_instance_pairing_pairs_a_sparse_capture() -> None:
    # ruby#381: each instance's subtree owns its captures — the shape
    # nests the instances under the prefix key.
    bindings = Bindings(
        _envelope(
            [
                {"capture": "tail", "path": "tail", "type": "string"},
                {"capture": "part_code", "path": "parts[].part_code", "type": "string"},
            ]
        ),
        "identifier",
    )
    shape = {
        "tail": "EF",
        "parts": [
            {"part_code": "5AB"},
            {"part_code": "7CD"},
        ],
    }
    assert bindings.apply(shape) == {
        "tail": "EF",
        "parts": [{"part_code": "5AB"}, {"part_code": "7CD"}],
    }
