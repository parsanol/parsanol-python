"""Explicit native contexts use real libraries without touching default lookup."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from parsanol import NativeContext, PargArtifact, ParseFailed, ParsanolError
from parsanol import _ffi

FIXTURE = Path(__file__).parent / 'fixtures/editions/base.json'
GRAMMAR = '{"root":0,"atoms":[{"Str":{"pattern":"x"}}]}'


@pytest.fixture()
def contexts():
    paths = json.loads(os.environ.get('PARSANOL_CONTEXT_TEST_LIBRARIES', '[]'))
    if not paths and os.environ.get('PARSANOL_CDYLIB'):
        paths = [os.environ['PARSANOL_CDYLIB']]
    if not paths:
        pytest.skip('real C ABI library required')
    return [NativeContext(path) for path in paths]


def forbid_default():
    raise AssertionError('an explicit native context used the default loader')


def test_artifact_path_and_shared_context_do_not_use_or_change_default(contexts, monkeypatch):
    initial = _ffi._lib
    initial_env = os.environ.get('PARSANOL_CDYLIB')
    monkeypatch.setattr(_ffi, 'load', forbid_default)
    for context in contexts:
        artifact = PargArtifact.from_path(FIXTURE, native_context=context)
        assert artifact.native_context is context
        assert artifact.parse('x') is not None
        with pytest.raises(ParseFailed):
            artifact.parse('y')
        second = PargArtifact(FIXTURE.read_text(), native_context=context)
        assert second.native_context is artifact.native_context
        assert second.parse('x') == artifact.parse('x')
        assert context.engine_version()
    assert _ffi._lib is initial
    assert os.environ.get('PARSANOL_CDYLIB') == initial_env


def test_library_path_constructor_is_lazy_and_independent(contexts, monkeypatch):
    monkeypatch.setattr(_ffi, 'load', forbid_default)
    artifact = PargArtifact(FIXTURE.read_text(), library_path=contexts[0].library_path)
    assert artifact.native_context is not None
    assert artifact.native_context._lib is None
    assert artifact.parse('x') is not None
    assert artifact.native_context._lib is not None


def test_context_arguments_are_exclusive_and_checked(contexts):
    text = FIXTURE.read_text()
    with pytest.raises(ValueError, match='library_path or native_context'):
        PargArtifact(text, library_path=contexts[0].library_path, native_context=contexts[0])
    with pytest.raises(TypeError, match='NativeContext'):
        PargArtifact(text, native_context=object())


def test_bad_explicit_path_does_not_fall_back_to_environment(contexts, monkeypatch, tmp_path):
    monkeypatch.setenv('PARSANOL_CDYLIB', str(contexts[0].library_path))
    artifact = PargArtifact.from_path(FIXTURE, library_path=tmp_path / 'missing-library')
    with pytest.raises(ParsanolError, match='libparsanol not found'):
        artifact.parse('x')


def test_owned_results_are_freed_by_their_creating_context_even_on_read_error(contexts, monkeypatch):
    monkeypatch.setattr(_ffi, 'load', forbid_default)
    calls = []
    for number, context in enumerate(contexts):
        lib = context.load()
        free = lib.parsanol_parg_free
        def release(pointer, owner=number, native_free=free):
            calls.append((owner, pointer.value))
            native_free(pointer)
        monkeypatch.setattr(lib, 'parsanol_parg_free', release)
        assert context.parse_shaped(GRAMMAR, 'x') is not None
        assert calls[-1][0] == number
        with monkeypatch.context() as local:
            def fail_read(pointer):
                raise UnicodeError('injected read failure after a real native allocation')
            local.setattr(_ffi.ctypes, 'string_at', fail_read)
            with pytest.raises(UnicodeError):
                context.parse_shaped(GRAMMAR, 'x')
        assert calls[-1][0] == number
    assert len(calls) == 2 * len(contexts)
    assert all(pointer for _, pointer in calls)


def test_hard_errors_are_read_from_the_same_context(contexts, monkeypatch):
    monkeypatch.setattr(_ffi, 'load', forbid_default)
    for context in contexts:
        with pytest.raises(ParsanolError):
            context.failure_wire('{invalid grammar json', 'x')
        assert context.failure_wire(GRAMMAR, 'y')['offset'] == 0


def test_recovery_uses_the_artifact_context(contexts, monkeypatch):
    corpus = Path(os.environ.get('PARSANOL_CORPUS_DIR', ''))
    path = corpus / 'recovery_resync_declared.json'
    if not path.is_file():
        pytest.skip('the project recovery corpus is required')
    monkeypatch.setattr(_ffi, 'load', forbid_default)
    for context in contexts:
        artifact = PargArtifact.from_path(path, native_context=context)
        assert artifact.recovery_supported()
        result = artifact.parse_recovering('a=1;b=2;', 'main')
        assert result['ok'] is True
        assert result['shape'] == artifact.parse('a=1;b=2;', 'main')
        result = artifact.parse_recovering('a=1;b=2;@@junk@@;c=3;d=4;', 'main')
        assert result['ok'] is False
        assert result['error']['offset'] == 8
        assert result['resyncs'][0]['skipped'] == '@@junk@@;'
