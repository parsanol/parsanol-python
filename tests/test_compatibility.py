"""Real native explicit policy ABI; matches upstream causal-lookahead fixture."""
import json
import os
from pathlib import Path
import pytest
from parsanol import PargArtifact, NativeContext, ParseFailed, ParsanolError
from parsanol.canonical import checksum_hex
from parsanol import _ffi


def envelope(prefix):
    value = {"shape":"parsanol-tree/v2", "grammar":"DiagnosticPolicy", "version":"1.0.0",
        "default_entry":"main", "entries":{"main":{"root":"main","grammar":{
        "root":6,"atoms":[{"Str":{"pattern":prefix+"b"}},{"Str":{"pattern":"c"}},
        {"Sequence":{"atoms":[0,1]}},{"Lookahead":{"atom":2,"positive":False}},
        {"Str":{"pattern":prefix}},{"Str":{"pattern":"!"}},
        {"Sequence":{"atoms":[3,4,5]}}]}}}}
    value['checksum'] = checksum_hex(value)
    return json.dumps(value,ensure_ascii=False)


@pytest.fixture
def library():
    path = os.environ.get('PARSANOL_COMPATIBILITY_TEST_LIBRARY')
    if not path: pytest.skip('explicit-policy native library required')
    return path


@pytest.mark.parametrize('prefix,input,causal',[('a','ab?',1),('α','αb?',2)])
def test_real_policy_preserves_default_and_causal_utf8(library,prefix,input,causal):
    initial = _ffi._lib
    artifact = PargArtifact(envelope(prefix),library_path=library)
    for mode,expected in [('strict',causal+1),('parslet',causal)]:
        with pytest.raises(ParseFailed) as error:
            artifact.parse_with_compatibility(input,compatibility=mode)
        assert error.value.wire['offset'] == expected
    with pytest.raises(ParseFailed) as error: artifact.parse(input)
    assert error.value.wire['offset'] == causal+1
    assert artifact.parse_with_compatibility(prefix+'!',compatibility='parslet') is not None
    assert _ffi._lib is initial


def test_input_validation_and_exclusive_context(library):
    artifact=PargArtifact(envelope('a'),native_context=NativeContext(library))
    with pytest.raises(ValueError): artifact.parse_with_compatibility('a!',compatibility='unknown')
    with pytest.raises(ValueError): artifact.parse_with_compatibility('a\0!',compatibility='parslet')
    with pytest.raises(UnicodeEncodeError): artifact.parse_with_compatibility('\ud800',compatibility='parslet')
    with pytest.raises(KeyError): artifact.parse_with_compatibility('a!',entry='missing',compatibility='parslet')


def test_old_engine_rejects_unsupported_policy_explicitly():
    path=os.environ.get('PARSANOL_COMPATIBILITY_OLD_LIBRARY')
    if not path: pytest.skip('old native library required')
    artifact=PargArtifact(envelope('a'),library_path=path)
    assert artifact.parse('a!') is not None
    with pytest.raises(ParsanolError,match='does not expose'):
        artifact.parse_with_compatibility('a!',compatibility='parslet')
