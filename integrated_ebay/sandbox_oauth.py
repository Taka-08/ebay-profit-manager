"""Single-use Sandbox authorization-code grant. No persistence or database access."""

from dataclasses import dataclass, field
import hmac
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit

from .sandbox_http import REQUIRED_SCOPES, SandboxHTTP
from .sandbox_oauth_diagnostics import current_status, mark


class OAuthSetupError(ValueError):
    """Only fixed, credential-free messages may cross the UI boundary."""


def _text(value, limit):
    return (isinstance(value, str) and 0 < len(value) <= limit
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def validate_settings(settings):
    if (settings.environment != 'SANDBOX'
            or not all(_text(v, 4096) for v in
                       (settings.client_id, settings.client_secret, settings.redirect_name))
            or ':' in settings.client_id
            or set(settings.scopes) != set(REQUIRED_SCOPES)):
        raise OAuthSetupError('Sandbox credentials and both required scopes must be configured.')


def validate_code(code):
    if not _text(code, 32768):
        raise OAuthSetupError('The authorization response is invalid. Start a new consent flow.')


def authorization_request_diagnostics(url, settings):
    """Return fixed statuses only; never return request values or the URL."""
    result = {
        'environment': 'SANDBOX' if settings.environment == 'SANDBOX' else 'OTHER',
        'endpoint': 'OTHER',
        'scheme': 'OTHER', 'host': 'OTHER', 'path': 'OTHER',
        'parameter_count': 0, 'fragment': 'ABSENT',
        'client_id': 'MISSING', 'client_id_match': 'MISMATCH',
        'client_id_format': 'INVALID',
        'redirect_uri': 'MISSING', 'redirect_uri_type': 'UNKNOWN',
        'redirect_uri_match': 'MISMATCH',
        'scope': 'MISSING', 'scope_required': 'NO', 'scope_unexpected': 'NO',
        'scope_match': 'MISMATCH', 'semantic_roundtrip': 'NO',
        'response_type': 'OTHER', 'state': 'MISSING', 'prompt': 'ABSENT',
        'duplicate_parameters': 'NO', 'double_encoding': 'NO',
        'overall': 'INVALID',
    }
    if not isinstance(url, str) or len(url) > 65536:
        return result
    try:
        parsed = urlsplit(url)
        fields = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True,
                           errors='strict', max_num_fields=20)
    except (ValueError, UnicodeError):
        return result

    result['scheme'] = 'HTTPS' if parsed.scheme == 'https' else 'OTHER'
    result['host'] = 'EXPECTED_SANDBOX' if parsed.netloc == 'auth.sandbox.ebay.com' else 'OTHER'
    result['path'] = 'EXPECTED_AUTHORIZE_PATH' if parsed.path == '/oauth2/authorize' else 'OTHER'
    result['parameter_count'] = len(fields)
    result['fragment'] = 'PRESENT' if parsed.fragment else 'ABSENT'
    result['endpoint'] = ('SANDBOX' if parsed.scheme == 'https'
                          and parsed.netloc == 'auth.sandbox.ebay.com'
                          and parsed.path == '/oauth2/authorize' and not parsed.fragment
                          else 'OTHER')
    values = {}
    for key, value in fields:
        values.setdefault(key, []).append(value)
    result['duplicate_parameters'] = ('YES' if any(len(items) != 1 for items in values.values())
                                      else 'NO')
    result['double_encoding'] = ('YES' if any(re.search(r'%[0-9a-fA-F]{2}', value)
                                              for _, value in fields) else 'NO')

    def single(name):
        items = values.get(name, ())
        return items[0] if len(items) == 1 else ''

    client_id = single('client_id')
    redirect_uri = single('redirect_uri')
    scope = single('scope')
    state = single('state')
    prompt = single('prompt')
    scope_parts = scope.split()
    required = set(REQUIRED_SCOPES)
    result['client_id'] = 'PRESENT' if client_id else 'MISSING'
    result['client_id_match'] = 'MATCH' if client_id and client_id == settings.client_id else 'MISMATCH'
    result['client_id_format'] = ('VALID' if client_id and client_id == client_id.strip()
                                  and not any(char.isspace() for char in client_id)
                                  and ':' not in client_id else 'INVALID')
    result['redirect_uri'] = 'PRESENT' if redirect_uri else 'MISSING'
    if redirect_uri.startswith(('https://', 'http://')):
        result['redirect_uri_type'] = 'URL'
    elif re.fullmatch(r'[A-Za-z0-9_.~-]+', redirect_uri):
        result['redirect_uri_type'] = 'RUNAME'
    result['redirect_uri_match'] = ('MATCH' if redirect_uri and redirect_uri == settings.redirect_name
                                    else 'MISMATCH')
    result['scope'] = 'PRESENT' if scope else 'MISSING'
    result['scope_required'] = 'YES' if required.issubset(scope_parts) else 'NO'
    result['scope_unexpected'] = 'YES' if set(scope_parts) - required else 'NO'
    result['scope_match'] = ('MATCH' if len(scope_parts) == len(settings.scopes)
                             and set(scope_parts) == set(settings.scopes) else 'MISMATCH')
    result['response_type'] = 'CODE' if single('response_type') == 'code' else 'OTHER'
    result['state'] = 'PRESENT' if state else 'MISSING'
    result['prompt'] = 'LOGIN' if prompt == 'login' else 'OTHER' if prompt else 'ABSENT'
    valid_escapes = not re.search(r'%(?![0-9a-fA-F]{2})', parsed.query)
    if (valid_escapes and result['double_encoding'] == 'NO'
            and parse_qsl(urlencode(fields), keep_blank_values=True, strict_parsing=True) == fields):
        result['semantic_roundtrip'] = 'YES'
    expected_keys = {'client_id', 'redirect_uri', 'response_type', 'scope', 'state', 'prompt'}
    if (result['environment'] == result['endpoint'] == 'SANDBOX'
            and result['client_id_match'] == result['redirect_uri_match'] == result['scope_match'] == 'MATCH'
            and result['client_id_format'] == 'VALID'
            and result['redirect_uri_type'] == 'RUNAME'
            and result['scope_required'] == 'YES' and result['scope_unexpected'] == 'NO'
            and len(scope_parts) == len(settings.scopes) == len(REQUIRED_SCOPES)
            and set(settings.scopes) == required
            and result['response_type'] == 'CODE'
            and result['state'] == 'PRESENT' and len(state) <= 128
            and re.fullmatch(r'[A-Za-z0-9_-]+', state)
            and result['prompt'] in ('LOGIN', 'ABSENT')
            and result['duplicate_parameters'] == result['double_encoding'] == 'NO'
            and set(values).issubset(expected_keys)
            and valid_escapes):
        result['overall'] = 'VALID'
    return result


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int
    refresh_token_expires_in: int


class SandboxConsent:
    def __init__(self, settings):
        validate_settings(settings)
        self._settings = settings
        self._state = secrets.token_urlsafe(32)
        self._started = time.monotonic()
        self._used = False
        self._lock = threading.Lock()

    @property
    def authorization_url(self):
        return 'https://auth.sandbox.ebay.com/oauth2/authorize?' + urlencode({
            'client_id': self._settings.client_id,
            'redirect_uri': self._settings.redirect_name,
            'response_type': 'code', 'scope': ' '.join(REQUIRED_SCOPES),
            'state': self._state, 'prompt': 'login',
        })

    def exchange(self, response_url, *, confirmed=False):
        self._consume(confirmed)
        try:
            if not _text(response_url, 65536):
                raise ValueError()
            parsed = urlsplit(response_url)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                    or parsed.password or parsed.fragment):
                raise ValueError()
            fields = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
            if ('error' in fields or len(fields.get('state', [])) != 1
                    or len(fields.get('code', [])) != 1
                    or not hmac.compare_digest(fields['state'][0], self._state)):
                raise ValueError()
            code = fields['code'][0]  # parse_qs decodes once; do not unquote again.
            validate_code(code)
        except Exception:
            raise OAuthSetupError('Consent response/state mismatch. Start a new consent flow.') from None
        return self._exchange_code(code)

    def exchange_callback(self, state, code, *, confirmed=False):
        """Accept already-decoded Streamlit query values without reconstructing a URL."""
        self._consume(confirmed)
        if not _text(state, 4096) or not hmac.compare_digest(state, self._state):
            mark('state_matched', 'NO')
            raise OAuthSetupError('Consent response/state mismatch. Start a new consent flow.')
        mark('state_matched', 'YES')
        try:
            validate_code(code)
        except OAuthSetupError:
            raise OAuthSetupError('Consent response/state mismatch. Start a new consent flow.') from None
        return self._exchange_code(code)

    def _consume(self, confirmed):
        if confirmed is not True:
            raise OAuthSetupError('Explicit Sandbox token exchange confirmation is required.')
        # Consume before dispatch: even a timeout must never cause an automatic retry.
        with self._lock:
            if self._used or time.monotonic() - self._started > 600:
                if self._used:
                    mark('callback_already_processed', 'YES')
                else:
                    mark('state_expired', 'YES')
                raise OAuthSetupError('This consent flow is used or expired. Start a new flow.')
            if current_status('state_expired') == 'NOT CHECKED':
                mark('state_expired', 'NO')
            self._used = True

    def _exchange_code(self, code):
        mark('token_exchange_attempted', 'YES')
        try:
            result = SandboxHTTP().exchange_authorization_code(self._settings, code)
            refresh = result.get('refresh_token') if isinstance(result, dict) else None
            mark('refresh_token_received', 'YES' if _text(refresh, 65536) and refresh != 'N/A' else 'NO')
            if (not isinstance(result, dict)
                    or not _text(result.get('access_token'), 65536)
                    or not _text(result.get('refresh_token'), 65536)
                    or result.get('refresh_token') == 'N/A'
                    or any(type(result.get(k)) is not int or result[k] <= 0
                           for k in ('expires_in', 'refresh_token_expires_in'))):
                raise ValueError()
            mark('token_exchange_succeeded', 'YES')
            return OAuthTokens(result['access_token'], result['refresh_token'],
                               result['expires_in'], result['refresh_token_expires_in'])
        except Exception as exc:
            if isinstance(exc, TimeoutError) and current_status('token_exchange_http_status') == 'NOT ATTEMPTED':
                mark('token_exchange_http_status', 'TIMEOUT')
            mark('token_exchange_succeeded', 'NO')
            raise OAuthSetupError('Token exchange failed or its result is unknown. Do not resend; start a new consent flow.') from None
