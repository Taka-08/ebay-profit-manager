"""Sandbox-only OAuth pages; never import or initialize a listing database here."""

import hmac
import time

import streamlit as st

from .ebay_api import OAuthSettings, execution_mode
from .sandbox_callback import sandbox_callback_registry
from .sandbox_http import setting
from .sandbox_oauth import OAuthSetupError, validate_settings


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


def render_start():
    st.title("eBay Sandbox OAuth")
    try:
        _setup_key()
        validate_settings(OAuthSettings.load("SANDBOX"))
    except (OAuthSetupError, ValueError):
        st.warning("Sandbox OAuthの設定が完了していません。")
        return

    supplied = st.text_input("セットアップキー", type="password", autocomplete="off")
    if st.button("Sandbox同意リンクを準備"):
        if not _authorized(supplied):
            st.error("確認できませんでした。")
            return
        try:
            st.session_state["_sandbox_oauth_consent_url"] = sandbox_callback_registry.begin(
                OAuthSettings.load("SANDBOX")
            )
        except OAuthSetupError:
            st.error("準備できませんでした。時間をおいてやり直してください。")
            return
    url = st.session_state.get("_sandbox_oauth_consent_url")
    if url:
        st.link_button("eBay Sandboxで同意する", url)


def _capture_callback():
    params = st.query_params
    states = params.get_all("state")
    codes = params.get_all("code")
    has_error = bool(params.get_all("error"))
    _clear_sensitive_session()
    valid = not has_error and len(states) == 1 and len(codes) == 1
    if valid:
        state, code = states[0], codes[0]
        valid = bool(state and code and len(state) <= 4096 and len(code) <= 32768)
    params.clear()
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


def render_accepted():
    if st.query_params:
        if not _capture_callback():
            st.title("eBay Sandbox OAuth")
            st.error("同意結果を確認できませんでした。最初からやり直してください。")
            return
    st.title("eBay Sandbox OAuth")
    try:
        _setup_key()
    except OAuthSetupError:
        _clear_sensitive_session()
        st.warning("Sandbox OAuthの設定が完了していません。")
        return

    stored = st.session_state.get("_sandbox_oauth_refresh")
    if stored:
        token, issued_at = stored
        if time.monotonic() - issued_at > TOKEN_HANDOFF_SECONDS:
            _clear_sensitive_session()
            st.warning("受け渡し時間が終了しました。最初からやり直してください。")
            return
        st.success("Sandbox Refresh Tokenを取得しました。")
        st.text_input("Streamlit Secretsへ移すRefresh Token", value=token,
                      type="password", key="_sandbox_oauth_refresh_field", autocomplete="off")
        st.caption("この端末でコピーし、Secretsに保存したら直ちに終了してください。履歴・同期は無効にしてください。")
        st.button("受け渡しを終了", on_click=_clear_sensitive_session)
        return

    st.warning("有効な同意結果がありません。最初からやり直してください。")


def render_declined():
    if st.query_params:
        st.query_params.clear()
    _clear_sensitive_session()
    st.title("eBay Sandbox OAuth")
    st.info("Sandbox OAuthがキャンセルされました。")
