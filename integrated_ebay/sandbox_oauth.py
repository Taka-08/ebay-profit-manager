"""Single-use Sandbox authorization-code grant. No persistence or database access."""

from dataclasses import dataclass, field
import hmac
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from .sandbox_http import REQUIRED_SCOPES, SandboxHTTP


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
        if confirmed is not True:
            raise OAuthSetupError('Explicit Sandbox token exchange confirmation is required.')
        # Consume before dispatch: even a timeout must never cause an automatic retry.
        with self._lock:
            if self._used or time.monotonic() - self._started > 600:
                raise OAuthSetupError('This consent flow is used or expired. Start a new flow.')
            self._used = True
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
        try:
            result = SandboxHTTP().exchange_authorization_code(self._settings, code)
            if (not isinstance(result, dict)
                    or not _text(result.get('access_token'), 65536)
                    or not _text(result.get('refresh_token'), 65536)
                    or result.get('refresh_token') == 'N/A'
                    or any(type(result.get(k)) is not int or result[k] <= 0
                           for k in ('expires_in', 'refresh_token_expires_in'))):
                raise ValueError()
            return OAuthTokens(result['access_token'], result['refresh_token'],
                               result['expires_in'], result['refresh_token_expires_in'])
        except Exception:
            raise OAuthSetupError('Token exchange failed or its result is unknown. Do not resend; start a new consent flow.') from None
