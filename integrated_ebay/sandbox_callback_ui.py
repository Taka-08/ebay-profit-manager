"""Sandbox-only OAuth pages; never import or initialize a listing database here."""

import hmac
import os
import time

import streamlit as st

from .ebay_api import MODES, OAuthSettings, execution_mode
from .sandbox_callback import sandbox_callback_registry
from .sandbox_http import REQUIRED_SCOPES, setting
from .sandbox_oauth import OAuthSetupError, authorization_request_diagnostics, validate_settings
from .sandbox_oauth_diagnostics import diagnostic_scope, mark, new_diagnostic, safe_lines


START_PATH = "ebay-sandbox-start"
ACCEPTED_PATH = "ebay-sandbox-accepted"
DECLINED_PATH = "ebay-sandbox-declined"
TOKEN_HANDOFF_SECONDS = 120


def _setup_key():
    key = setting("EBAY_SANDBOX_OAUTH_SETUP_KEY")
    try:
        mode = execution_mode()
    except ValueError:
        raise OAuthSetupError("Sandbox OAuth is not configured for this app.") from None
    if (len(key) < 32 or mode == "PRODUCTION"
            or setting("EBAY_ENABLE_PRODUCTION_WRITES").lower() not in ("", "false")):
        raise OAuthSetupError("Sandbox OAuth is not configured for this app.")
    return key


def _authorized(candidate):
    try:
        expected = _setup_key()
    except OAuthSetupError:
        return False
    return isinstance(candidate, str) and hmac.compare_digest(candidate, expected)


def _diagnostic_setting(name):
    value = os.environ.get(name)
    if value:
        return value, "environment"
    try:
        section = st.secrets.get("ebay", {})
        if hasattr(section, "get"):
            value = section.get(name)
            if value is not None:
                return str(value).strip(), "[ebay]"
        value = st.secrets.get(name)
        if value is not None:
            return str(value).strip(), "top-level"
    except Exception:
        pass
    return "", "missing"


def _text_problem(value):
    if not value:
        return "not loaded"
    if len(value) > 4096:
        return "exceeds 4096 characters"
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return "contains a control character"
    return ""


def _configuration_diagnostics():
    lines = []
    for name in ("CLIENT_ID", "CLIENT_SECRET", "REDIRECT_NAME"):
        key = f"EBAY_SANDBOX_{name}"
        value, source = _diagnostic_setting(key)
        reason = _text_problem(value)
        if name == "CLIENT_ID" and not reason and ":" in value:
            reason = "contains a colon"
        lines.append(f"{key}: loaded={'OK' if value else 'NG'}, "
                     f"format={'NG - ' + reason if reason else 'OK'}, source={source}")

    key = "EBAY_SANDBOX_SCOPES"
    value, source = _diagnostic_setting(key)
    configured = set(value.split())
    required = set(REQUIRED_SCOPES)
    missing = sorted(required - configured)
    reason = ("missing required scope: " + ", ".join(missing) if missing else
              "unexpected scope configured" if configured != required else "")
    lines.append(f"{key}: loaded={'OK' if value else 'NG'}, "
                 f"required scopes={'NG - ' + reason if reason else 'OK'}, source={source}")

    key = "EBAY_SANDBOX_OAUTH_SETUP_KEY"
    value, source = _diagnostic_setting(key)
    lines.append(f"{key}: loaded={'OK' if value else 'NG'}, "
                 f"minimum 32 characters={'OK' if len(value) >= 32 else 'NG - too short'}, "
                 f"source={source}")

    value, source = _diagnostic_setting("EBAY_EXECUTION_MODE")
    mode = (value or "mock").upper()
    reason = "unsupported mode" if mode not in MODES else "Production mode" if mode == "PRODUCTION" else ""
    lines.append(f"EXECUTION_MODE: {'NG - ' + reason if reason else 'OK - Sandbox OAuth allowed'}, "
                 f"source={source}")

    value, source = _diagnostic_setting("EBAY_ENABLE_PRODUCTION_WRITES")
    disabled = value.lower() in ("", "false")
    lines.append(f"PRODUCTION_WRITE_GUARD: {'OK - writes disabled' if disabled else 'NG - writes not disabled'}, "
                 f"source={source}")
    return lines


def _request_sources(settings):
    sources = {}
    expected = {
        'client_id': ('EBAY_SANDBOX_CLIENT_ID', settings.client_id),
        'redirect_uri': ('EBAY_SANDBOX_REDIRECT_NAME', settings.redirect_name),
        'scope': ('EBAY_SANDBOX_SCOPES', settings.scopes),
    }
    for label, (key, loaded) in expected.items():
        value, source = _diagnostic_setting(key)
        matches = tuple(value.split()) == loaded if label == 'scope' else value == loaded
        sources[label] = source if matches and source in ('environment', '[ebay]', 'top-level') else 'UNKNOWN'
    return sources


def render_start():
    st.title("eBay Sandbox OAuth")
    try:
        _setup_key()
        settings = OAuthSettings.load("SANDBOX")
        validate_settings(settings)
    except (OAuthSetupError, ValueError):
        st.session_state.pop("_sandbox_oauth_consent_url", None)
        st.warning("Sandbox OAuthの設定が完了していません。")
        for line in _configuration_diagnostics():
            st.caption(line)
        return

    supplied = st.text_input("セットアップキー", type="password", autocomplete="off")
    if st.button("Sandbox同意リンクを準備"):
        if not _authorized(supplied):
            st.error("確認できませんでした。")
            return
        try:
            st.session_state.pop("_sandbox_oauth_diagnostics", None)
            st.session_state["_sandbox_oauth_consent_url"] = sandbox_callback_registry.begin(settings)
        except OAuthSetupError:
            st.error("準備できませんでした。時間をおいてやり直してください。")
            return
    url = st.session_state.get("_sandbox_oauth_consent_url")
    if url:
        current_settings = OAuthSettings.load("SANDBOX")
        report = authorization_request_diagnostics(url, current_settings)
        sources = _request_sources(current_settings)
        st.caption("Authorization Request事前診断")
        for label, key in (
            ("Environment", "environment"),
            ("Authorization endpoint", "endpoint"),
            ("Client ID", "client_id"),
            ("Client ID match", "client_id_match"),
            ("Client ID format", "client_id_format"),
            ("redirect_uri", "redirect_uri"),
            ("redirect_uri type", "redirect_uri_type"),
            ("redirect_uri match", "redirect_uri_match"),
            ("scope required", "scope_required"),
            ("scope unexpected", "scope_unexpected"),
            ("scope match", "scope_match"),
            ("response_type", "response_type"),
            ("state", "state"),
            ("prompt", "prompt"),
            ("duplicate query parameters", "duplicate_parameters"),
            ("double encoding", "double_encoding"),
        ):
            st.caption(f"{label}: {report[key]}")
        st.caption(f"Client ID source: {sources['client_id']}")
        st.caption(f"redirect_uri source: {sources['redirect_uri']}")
        st.caption(f"scope source: {sources['scope']}")
        if 'UNKNOWN' in sources.values():
            report['overall'] = 'INVALID'
        st.caption(f"Authorization request overall: {report['overall']}")
        if report['overall'] == 'VALID':
            st.link_button("eBay Sandboxで同意する", url)
        else:
            st.session_state.pop("_sandbox_oauth_consent_url", None)
            st.warning("認可リクエストを確認できませんでした。リンクは使用できません。")


def _capture_callback():
    history = st.session_state.setdefault("_sandbox_oauth_diagnostics", [])
    diagnostic = new_diagnostic()
    if history:
        diagnostic["rerun_detected_after_callback"] = "YES"
    history.append(diagnostic)
    del history[:-2]
    with diagnostic_scope(diagnostic):
        mark("callback_reached", "YES")
        params = st.query_params
        states = params.get_all("state")
        codes = params.get_all("code")
        mark("state_received", "YES" if states else "NO")
        mark("code_received", "YES" if codes else "NO")
        has_error = bool(params.get_all("error"))
        _clear_sensitive_session()
        valid = not has_error and len(states) == 1 and len(codes) == 1
        if valid:
            state, code = states[0], codes[0]
            valid = bool(state and code and len(state) <= 4096 and len(code) <= 32768)
        params.clear()
        mark("query_cleared", "YES")
        if not valid:
            return False
        try:
            _setup_key()
            result = sandbox_callback_registry.exchange(state, code)
        except OAuthSetupError:
            return False
        st.session_state["_sandbox_oauth_refresh"] = (result.refresh_token, time.monotonic())
        return True


def _clear_sensitive_session():
    for key in ("_sandbox_oauth_callback", "_sandbox_oauth_refresh", "_sandbox_oauth_refresh_field"):
        st.session_state.pop(key, None)


def _show_callback_diagnostics():
    history = st.session_state.get("_sandbox_oauth_diagnostics", [])
    for index, diagnostic in enumerate(history):
        st.caption("Sandbox callback diagnostics: " + ("previous" if index < len(history) - 1 else "latest"))
        for line in safe_lines(diagnostic):
            st.caption(line)


def render_accepted():
    if st.query_params:
        if not _capture_callback():
            st.title("eBay Sandbox OAuth")
            st.error("同意結果を確認できませんでした。最初からやり直してください。")
            _show_callback_diagnostics()
            return
    else:
        history = st.session_state.get("_sandbox_oauth_diagnostics", [])
        if history:
            history[-1]["rerun_detected_after_callback"] = "YES"
        else:
            diagnostic = new_diagnostic()
            diagnostic["callback_reached"] = "YES"
            st.session_state["_sandbox_oauth_diagnostics"] = [diagnostic]
    st.title("eBay Sandbox OAuth")
    try:
        _setup_key()
    except OAuthSetupError:
        _clear_sensitive_session()
        st.warning("Sandbox OAuthの設定が完了していません。")
        _show_callback_diagnostics()
        return

    stored = st.session_state.get("_sandbox_oauth_refresh")
    if stored:
        token, issued_at = stored
        if time.monotonic() - issued_at > TOKEN_HANDOFF_SECONDS:
            _clear_sensitive_session()
            st.warning("受け渡し時間が終了しました。最初からやり直してください。")
            _show_callback_diagnostics()
            return
        st.success("Sandbox Refresh Tokenを取得しました。")
        st.text_input("Streamlit Secretsへ移すRefresh Token", value=token,
                      type="password", key="_sandbox_oauth_refresh_field", autocomplete="off")
        st.caption("この端末でコピーし、Secretsに保存したら直ちに終了してください。履歴・同期は無効にしてください。")
        st.button("受け渡しを終了", on_click=_clear_sensitive_session)
        _show_callback_diagnostics()
        return

    st.warning("有効な同意結果がありません。最初からやり直してください。")
    _show_callback_diagnostics()


def render_declined():
    if st.query_params:
        st.query_params.clear()
    _clear_sensitive_session()
    st.title("eBay Sandbox OAuth")
    st.info("Sandbox OAuthがキャンセルされました。")
