"""Process-local, fail-closed state for a one-time Sandbox OAuth callback."""

from hashlib import sha256
import hmac
import threading
import time
from urllib.parse import parse_qs, urlsplit

from .sandbox_oauth import OAuthSetupError, SandboxConsent, validate_code
from .sandbox_oauth_diagnostics import mark


FLOW_LIFETIME_SECONDS = 600
MAX_PENDING_FLOWS = 8


class SandboxCallbackRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending = {}
        self._used_codes = {}

    def _expire(self, now):
        self._pending = {key: entry for key, entry in self._pending.items()
                         if now - entry[1] <= FLOW_LIFETIME_SECONDS}
        self._used_codes = {key: used_at for key, used_at in self._used_codes.items()
                            if now - used_at <= FLOW_LIFETIME_SECONDS}

    def begin(self, settings):
        flow = SandboxConsent(settings)
        url = flow.authorization_url
        state = parse_qs(urlsplit(url).query)['state'][0]
        with self._lock:
            now = time.monotonic()
            self._expire(now)
            if len(self._pending) >= MAX_PENDING_FLOWS:
                raise OAuthSetupError('Too many pending consent flows. Try again later.')
            self._pending[state] = (flow, now)
        return url

    def prepared_request_diagnostics(self, url):
        result = {'state_match': 'MISMATCH', 'generated_url_match': 'MISMATCH'}
        if not isinstance(url, str):
            return result
        try:
            states = parse_qs(urlsplit(url).query, strict_parsing=True).get('state', ())
        except ValueError:
            return result
        if len(states) != 1:
            return result
        state = states[0]
        with self._lock:
            entry = self._pending.get(state)
            if entry is None or time.monotonic() - entry[1] > FLOW_LIFETIME_SECONDS:
                return result
            flow = entry[0]
            if hmac.compare_digest(state, flow._state):
                result['state_match'] = 'MATCH'
                if hmac.compare_digest(url, flow.authorization_url):
                    result['generated_url_match'] = 'MATCH'
        return result

    def exchange(self, state, code):
        if not isinstance(state, str) or not 0 < len(state) <= 4096:
            raise OAuthSetupError('Consent response/state mismatch. Start a new consent flow.')
        validate_code(code)
        digest = sha256(code.encode('utf-8')).digest()
        with self._lock:
            now = time.monotonic()
            candidate = self._pending.get(state)
            if candidate is not None:
                mark('stored_state_found', 'YES')
                mark('same_cloud_process', 'SAME')
                mark('state_expired', 'YES' if now - candidate[1] > FLOW_LIFETIME_SECONDS else 'NO')
                mark('state_matched', 'YES' if hmac.compare_digest(state, candidate[0]._state) else 'NO')
            self._expire(now)
            entry = self._pending.get(state)
            if digest in self._used_codes:
                mark('callback_already_processed', 'YES')
                mark('same_cloud_process', 'SAME')
            if entry is None or not hmac.compare_digest(state, entry[0]._state):
                raise OAuthSetupError('Consent response/state mismatch. Start a new consent flow.')
            if digest in self._used_codes:
                raise OAuthSetupError('This authorization code was already used.')
            self._pending.pop(state)
            self._used_codes[digest] = now
        return entry[0].exchange_callback(state, code, confirmed=True)


sandbox_callback_registry = SandboxCallbackRegistry()
