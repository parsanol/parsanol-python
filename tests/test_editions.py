"""Edition validation at load (ruby#357's contract, all loaders).

Every runtime accepts 1, 2, "1", "2", "v1", "v2", "classic" and
absent/null (absent = 1), and rejects unknown values at load. The
fixtures are compiled once and re-stamped per spelling with a valid
checksum (the edition is a checksummed field)."""

import json
from pathlib import Path

import pytest

from parsanol import PargArtifact
from parsanol.canonical import checksum_hex

FIXTURE = Path(__file__).parent / "fixtures" / "editions" / "base.json"

ACCEPT = {"num1": 1, "num2": 2, "s1": "1", "s2": "2", "v1": "v1", "v2": "v2",
          "classic": "classic", "null_ed": None, "absent": "absent"}
REJECT = {"v3": "v3", "num3": 3}


def stamped(tmp_path: Path, tag: str, edition) -> Path:
    envelope = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if tag == "absent":
        envelope.pop("edition", None)
    else:
        envelope["edition"] = edition
    envelope["checksum"] = checksum_hex(
        {k: v for k, v in envelope.items() if k != "checksum"}
    )
    out = tmp_path / f"ed_{tag}.json"
    out.write_text(json.dumps(envelope), encoding="utf-8")
    return out


@pytest.mark.parametrize("tag", sorted(ACCEPT))
def test_accepts_known_editions(tmp_path, tag):
    artifact = PargArtifact.from_path(stamped(tmp_path, tag, ACCEPT[tag]))
    assert artifact.edition == 1 if tag in ("num1", "s1", "v1", "classic", "null_ed", "absent") else artifact.edition == 2


@pytest.mark.parametrize("tag", sorted(REJECT))
def test_rejects_unknown_editions(tmp_path, tag):
    with pytest.raises(ValueError, match="edition this runtime does not know"):
        PargArtifact.from_path(stamped(tmp_path, tag, REJECT[tag]))


def test_readers():
    artifact = PargArtifact.from_path(FIXTURE)
    assert isinstance(artifact.edition, int)
    assert artifact.semantics_hash is None or isinstance(artifact.semantics_hash, str)
