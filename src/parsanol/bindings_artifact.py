"""The declared per-target binding artifact (parsanol-ruby#432).

From one compiled grammar the toolchain emits one checksummed bindings
artifact per target (ruby / rs / ts / python), each carrying the entry
binding records and pinned to its grammar by source hash. Declared and
diffable, not baked: consumers pin and verify what they load.

Boundary: the records carry AST construction only — the
production-to-binding mapping. Semantics live in the model layer (LML).
Execution resources (preprocess steps and their tables) resolve from the
PAIRED parse artifact's checksummed envelope, which is why
:meth:`BindingsArtifact.apply` takes the paired artifact envelope and
re-verifies the pairing.
"""

from __future__ import annotations

import json

from .canonical import checksum_hex
from .bindings import Bindings

BINDINGS_ARTIFACT_KIND = "parg-bindings"
SUPPORTED_BINDING_VERSION = 1
BINDING_TARGETS = ("ruby", "rs", "ts", "python")


class BindingsArtifactError(ValueError):
    """The bindings artifact payload failed verification or pairing."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BindingsArtifactError(message)


def bindings_envelope(envelope: dict, target: str) -> dict:
    """Emit the per-target bindings artifact from a compiled parse-artifact
    envelope. Checksummed with the artifact scheme (canonical JSON sha256
    over everything except the checksum itself), so every engine
    re-derives it identically."""
    _require(target in BINDING_TARGETS, f"unknown binding target {target!r}")
    payload = {
        "artifact_kind": BINDINGS_ARTIFACT_KIND,
        "target": target,
        "binding_version": SUPPORTED_BINDING_VERSION,
        "grammar": envelope.get("grammar"),
        "grammar_version": envelope.get("version"),
        "grammar_source_hash": envelope.get("source_hash"),
        "shape": envelope.get("shape"),
        "entries": {
            name: {"bindings": entry.get("bindings", [])}
            for name, entry in envelope.get("entries", {}).items()
        },
    }
    payload["checksum"] = checksum_hex(payload)
    return payload


class BindingsArtifact:
    """A verified declared bindings artifact. Never exists for a tampered
    payload: construction verifies kind, checksum, target and binding
    version."""

    def __init__(self, payload: dict, expected_target: str | None = None):
        _require(isinstance(payload, dict), "payload must be an object")
        self.payload = payload
        self.verify()
        if expected_target is not None:
            self.verify_target(expected_target)

    @classmethod
    def from_json(cls, text: str, expected_target: str | None = None):
        return cls(json.loads(text), expected_target)

    def verify(self) -> None:
        payload = self.payload
        _require(
            payload.get("artifact_kind") == BINDINGS_ARTIFACT_KIND,
            f"not a {BINDINGS_ARTIFACT_KIND} artifact "
            f"(artifact_kind {payload.get('artifact_kind')!r})",
        )
        target = payload.get("target")
        _require(
            target in BINDING_TARGETS, f"unknown binding target {target!r}"
        )
        version = payload.get("binding_version")
        _require(
            version == SUPPORTED_BINDING_VERSION,
            f"unsupported binding_version {version!r} "
            f"(supported: {SUPPORTED_BINDING_VERSION})",
        )
        _require(
            isinstance(payload.get("entries"), dict),
            "bindings artifact carries no entries map",
        )
        stored = payload.get("checksum")
        _require(isinstance(stored, str), "bindings artifact has no checksum")
        computed = checksum_hex(
            {k: v for k, v in payload.items() if k != "checksum"}
        )
        _require(
            stored == computed,
            f"bindings artifact checksum mismatch: stored {stored}, "
            f"computed {computed}",
        )

    def verify_target(self, expected: str) -> None:
        declared = self.payload.get("target")
        _require(
            declared == expected,
            f"bindings artifact targets {declared!r}, not {expected!r}",
        )

    @property
    def target(self) -> str:
        return self.payload["target"]

    @property
    def grammar_source_hash(self):
        return self.payload.get("grammar_source_hash")

    def bindings(self, entry: str) -> list:
        return self.payload["entries"].get(entry, {}).get("bindings", [])

    def _verify_pairing(self, parg_envelope: dict) -> None:
        mismatches = []
        if self.payload.get("grammar") != parg_envelope.get("grammar"):
            mismatches.append("grammar")
        if self.payload.get("grammar_version") != parg_envelope.get("version"):
            mismatches.append("version")
        if self.grammar_source_hash != parg_envelope.get("source_hash"):
            mismatches.append("source_hash")
        _require(
            not mismatches,
            "bindings artifact does not pair with the parse artifact: "
            + ", ".join(mismatches),
        )

    def apply(self, parg_envelope: dict, entry: str, shape) -> dict:
        """Materialize the bound map from a parse shape using the DECLARED
        records. The paired parse artifact envelope supplies entry context
        and preprocess resolution; the same Bindings runs as for the
        embedded records, so the declared artifact and the baked records
        produce identical bound maps."""
        self._verify_pairing(parg_envelope)
        crafted = dict(parg_envelope)
        entries = dict(crafted.get("entries", {}))
        entry_view = dict(entries.get(entry, {}))
        entry_view["bindings"] = self.bindings(entry)
        entries[entry] = entry_view
        crafted["entries"] = entries
        return Bindings(crafted, entry).apply(shape)


__all__ = [
    "BINDING_TARGETS",
    "BINDINGS_ARTIFACT_KIND",
    "BindingsArtifact",
    "BindingsArtifactError",
    "SUPPORTED_BINDING_VERSION",
    "bindings_envelope",
]
