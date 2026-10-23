"""Canonical JSON and artifact checksums — a faithful port of the Rust
reference (`parsanol::parg::canonical_json` / `checksum_hex`), so a Python
verification agrees byte-for-byte with the compiler's sha256.

Canonical form: object keys sorted, no whitespace, short escapes for
``\\b \\t \\n \\f \\r " \\``, lowercase ``\\u00xx`` for other control
characters, raw UTF-8 otherwise, and floats rendered with the B6 float form
(shortest round-trip digits, Ruby JSON gem notation).
"""

from __future__ import annotations

import hashlib
import json
import math


def ruby_json_float(value: float) -> str:
    """B6 float form: shortest round-trip digits, Ruby JSON notation."""
    if value == 0.0:
        return "-0.0" if math.copysign(1.0, value) < 0 else "0.0"
    sign = "-" if value < 0 else ""

    digits = exponent = None
    for precision in range(18):
        text = f"{value:.{precision}e}"
        if float(text) == value:
            mantissa, raw_exponent = text.split("e")
            stripped = "".join(c for c in mantissa if c.isdigit()).rstrip("0")
            digits = stripped or "0"
            exponent = int(raw_exponent)
            break
    assert digits is not None and exponent is not None, f"unformattable float {value!r}"

    if not (-9 <= exponent <= 14):
        head, tail = digits[:1], digits[1:]
        mantissa = head if not tail else f"{head}.{tail}"
        return f"{sign}{mantissa}e{exponent:+03d}"

    if exponent >= 0:
        point = exponent + 1
        if point >= len(digits):
            return f"{sign}{digits}{'0' * (point - len(digits))}.0"
        return f"{sign}{digits[:point]}.{digits[point:]}"
    zeros = "0" * (-exponent - 1)
    return f"{sign}0.{zeros}{digits}"


def _write_canonical(value, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, float):
        out.append(ruby_json_float(value))
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, str):
        _write_canonical_string(value, out)
    elif isinstance(value, list):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _write_canonical(item, out)
        out.append("]")
    elif isinstance(value, dict):
        out.append("{")
        for index, key in enumerate(sorted(value)):
            if index:
                out.append(",")
            _write_canonical_string(key, out)
            out.append(":")
            _write_canonical(value[key], out)
        out.append("}")
    else:  # pragma: no cover - envelopes are plain JSON by construction
        raise TypeError(f"non-JSON value in envelope: {type(value)!r}")


def _write_canonical_string(text: str, out: list[str]) -> None:
    out.append('"')
    for character in text:
        if character == '"':
            out.append('\\"')
        elif character == "\\":
            out.append("\\\\")
        elif character == "\b":
            out.append("\\b")
        elif character == "\f":
            out.append("\\f")
        elif character == "\n":
            out.append("\\n")
        elif character == "\r":
            out.append("\\r")
        elif character == "\t":
            out.append("\\t")
        elif ord(character) < 0x20:
            out.append(f"\\u{ord(character):04x}")
        else:
            out.append(character)
    out.append('"')


def canonical_json(value) -> str:
    out: list[str] = []
    _write_canonical(value, out)
    return "".join(out)


def canonical_from_json_text(text: str):
    """Parse JSON text the way the canonical form expects.

    `json.loads` already produces shortest-round-trip floats (repr-based),
    and `ruby_json_float` re-derives the digits, so plain parsing preserves
    the B6 form.
    """
    return json.loads(text)


def checksum_hex(payload) -> str:
    """`sha256:<hex>` over the canonical form of `payload`."""
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def verify_checksum(envelope: dict) -> None:
    """Raise ValueError when the envelope's checksum does not verify."""
    stored = envelope.get("checksum")
    if not isinstance(stored, str):
        raise ValueError("envelope has no checksum")
    payload = {key: value for key, value in envelope.items() if key != "checksum"}
    computed = checksum_hex(payload)
    if stored != computed:
        raise ValueError(f"checksum mismatch: stored {stored}, computed {computed}")
