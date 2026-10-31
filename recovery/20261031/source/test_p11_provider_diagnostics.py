import json
from probe_minute_history import safe_provider_error


def error(message):
    value = Exception('ARBITRARY_REPR_PRIVATE_VALUE')
    value.code = 403208
    value.message = message
    return value


def test_unknown_code_preserves_structured_diagnostic(monkeypatch):
    monkeypatch.setenv('LONGBRIDGE_ACCESS_TOKEN', 'private-123')
    exc = error('Access condition unmet request_id=abcd-1234; access_token=private-123\nhttps://user:password@host/path?secret=x')
    result = safe_provider_error(exc, stage='QuoteContext.quote')
    assert result['provider_error_code'] == 403208
    assert result['provider_identifiers']['request_id'] == 'abcd-1234'
    assert result['failure_stage'] == 'QuoteContext.quote'
    assert result['sdk_version'] == '4.4.1'
    text = json.dumps(result)
    assert all(value not in text for value in ('private-123', 'password@host', 'ARBITRARY_REPR', 'secret=x'))


def test_headers_and_embedded_secrets_are_removed_before_truncation(monkeypatch):
    monkeypatch.setenv('LONGBRIDGE_APP_SECRET', 'short secret')
    exc = error('short secret ' + 'a ' * 260 + '\nAuthorization: Bearer abc\nCookie: sess=xyz\npassword="private value"')
    result = safe_provider_error(exc)
    assert len(result['provider_message']) <= 512
    assert 'short secret' not in json.dumps(result)
    assert '\n' not in result['provider_message']


def test_unstructured_exception_and_oversize_fail_closed():
    assert safe_provider_error(Exception('secret'))['provider_message'] is None
    assert safe_provider_error(error('x'*17000))['provider_message'] == '[OVERSIZE_MESSAGE_OMITTED]'


def test_identifier_cannot_echo_known_credentials(monkeypatch):
    monkeypatch.setenv('LONGBRIDGE_APP_KEY', 'abcdefgh1234')
    exc = error('failed')
    exc.request_id = 'abcdefgh1234'
    assert safe_provider_error(exc)['provider_identifiers']['request_id'] is None
