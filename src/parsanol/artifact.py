"""PargArtifact: checksum-verified artifact load and native parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import _ffi
from .bindings import Bindings, canonical
from .canonical import verify_checksum


def apply_bindings(artifact: "PargArtifact", entry: str, shape) -> dict:
    """Apply an entry's bindings to a shaped tree (the `example` layer)."""
    return Bindings(artifact.envelope, entry).apply(shape)


class ParseFailed(Exception):
    """The input was rejected; `wire` carries the failure wire."""

    def __init__(self, wire: dict):
        self.wire = wire
        offset = wire.get("offset")
        expected = wire.get("expected") or []
        what = ", ".join(expected[:4]) if expected else "no further input"
        super().__init__(f"Failed to match at offset {offset}: expected {what}")


@dataclass
class TestRun:
    """Result of replaying an artifact's embedded tests."""

    total: int
    failures: list[str]
    skipped: list[str]

    @property
    def ok(self) -> bool:
        return not self.failures


class PargArtifact:
    """A loaded parsanol-tree/v2 artifact.

    Load verifies the sha256 checksum over the canonicalized envelope and
    fails loudly on mismatch — never silently mis-parses.
    """

    def __init__(self, envelope_text: str):
        self.envelope_text = envelope_text
        envelope = json.loads(envelope_text)
        verify_checksum(envelope)
        self.envelope = envelope
        entries = envelope.get("entries") or {}
        default = envelope.get("default_entry")
        if default is None and entries:
            default = sorted(entries)[0]
        self.default_entry: str | None = default

    @classmethod
    def from_path(cls, path: str | Path) -> "PargArtifact":
        return cls(Path(path).read_text(encoding="utf-8"))

    # -- structure ---------------------------------------------------------

    @property
    def checksum(self) -> str | None:
        return self.envelope.get("checksum")

    def entry_names(self) -> list[str]:
        return sorted(self.envelope.get("entries") or {})

    def _entry(self, entry: str | None) -> tuple[str, dict]:
        entries = self.envelope.get("entries") or {}
        name = entry or self.default_entry
        if name is None or name not in entries:
            raise KeyError(f"unknown entry {name!r}")
        return name, entries[name]

    def _grammar_json(self, entry: str | None) -> str:
        _, resolved = self._entry(entry)
        grammar = resolved.get("grammar")
        if grammar is None:
            raise KeyError(f"entry {entry!r} has no portable grammar")
        return json.dumps(grammar, separators=(",", ":"), sort_keys=True)

    # -- parsing -----------------------------------------------------------

    def parse(self, input_text: str, entry: str | None = None):
        """Shaped tree (Python objects) or raises ParseFailed."""
        grammar_json = self._grammar_json(entry)
        shaped = _ffi.parse_shaped(grammar_json, input_text)
        if shaped is None:
            raise ParseFailed(_ffi.failure_wire(grammar_json, input_text))
        return shaped

    def parse_wire(self, input_text: str, entry: str | None = None) -> dict:
        """The failure wire for a rejected input (no exception)."""
        return _ffi.failure_wire(self._grammar_json(entry), input_text)

    # -- embedded tests ------------------------------------------------------

    def run_tests(self, entry: str | None = None) -> TestRun:
        """Replay the artifact's embedded tests through the native engine.

        Phases: accept / reject / capture (grammar layer) / example
        (bindings layer) / shape (whole-tree layer) — the same five the
        Ruby and Rust runners evaluate.
        """
        name, _resolved = self._entry(entry)
        failures: list[str] = []
        skipped: list[str] = []
        total = 0
        for test in self.envelope.get("tests") or []:
            test_entry = test.get("entry") or name
            if test_entry != name:
                continue
            total += 1
            kind = test.get("kind")
            text = test.get("input") or ""
            label = f"{kind} {text!r}"
            if kind not in ("accept", "reject", "capture", "example", "shape"):
                skipped.append(f"{label}: {kind} not in the Python scope")
                continue
            try:
                tree = self.parse(text, name)
            except ParseFailed:
                if kind != "reject":
                    failures.append(f"{label}: expected a match, engine rejected")
                continue
            if kind == "reject":
                failures.append(f"{label}: expected rejection, engine matched")
                continue

            reduced = reduce_slices(tree)
            if kind == "capture":
                problems = _check_capture(reduced, test.get("expect") or {})
                failures.extend(f"{label}: {problem}" for problem in problems)
            elif kind == "example":
                problems = _check_example(self, name, reduced, test.get("expect") or {})
                failures.extend(f"{label}: {problem}" for problem in problems)
            elif kind == "shape":
                if canonical(reduced) != canonical(test.get("expect")):
                    failures.append(
                        f"{label}: shape mismatch: expected {test.get('expect')!r}, "
                        f"got {reduced!r}"
                    )
        return TestRun(total=total, failures=failures, skipped=skipped)


def _check_example(artifact: "PargArtifact", entry: str, reduced, expect: dict) -> list[str]:
    if not isinstance(expect, dict):
        return [f"example expectations must be an object, got {expect!r}"]
    try:
        bound = apply_bindings(artifact, entry, reduced)
    except Exception as error:  # bindings errors are test failures
        return [f"bindings failed: {error}"]
    problems: list[str] = []
    for key, want in expect.items():
        got = bound.get(key)
        if canonical(got) != canonical(want):
            problems.append(f"bound {key!r}: expected {want!r}, got {got!r}")
    return problems


_SLICE_KEYS = {"offset", "length", "line", "column", "value"}


def reduce_slices(tree):
    """Reduce slice wire objects ({offset, length, line, column, value}) to
    their text — the comparison form the capture-test semantics expect.
    Other dicts pass through untouched."""
    if isinstance(tree, dict):
        if set(tree) == _SLICE_KEYS:
            return tree["value"]
        return {key: reduce_slices(value) for key, value in tree.items()}
    if isinstance(tree, list):
        return [reduce_slices(item) for item in tree]
    return tree


def _check_capture(tree, expect: dict) -> list[str]:
    """Corpus capture semantics: collect named captures from anywhere in
    the flattened tree (first value wins) and compare presence + value."""
    problems: list[str] = []
    captures: dict = {}

    def walk(value) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                captures.setdefault(key, item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(tree)
    for key, want in expect.items():
        if key not in captures:
            problems.append(f"capture {key!r} missing from tree")
        elif captures[key] != want:
            problems.append(f"capture {key!r}: expected {want!r}, got {captures[key]!r}")
    return problems
