"""Loopback-only, in-memory OAuth helper. Never deploy this script to Cloud."""

import ctypes
from ctypes import wintypes
import hmac
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrated_ebay.ebay_api import OAuthClient, OAuthSettings
from integrated_ebay.sandbox_http import REQUIRED_SCOPES


class PrivateClipboard:
    """Windows clipboard with history/cloud exclusion; never reads clipboard text."""
    def __init__(self):
        self.sequence = None
        self.deadline = 0

    def _api(self):
        if os.name != 'nt':
            raise RuntimeError('This helper requires Windows.')
        user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        user.OpenClipboard.argtypes = [wintypes.HWND]
        user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
            wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user.CreateWindowExW.restype = wintypes.HWND
        user.DestroyWindow.argtypes = [wintypes.HWND]
        user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user.SetClipboardData.restype = wintypes.HANDLE
        user.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
        user.GetClipboardSequenceNumber.restype = wintypes.DWORD
        kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel.GlobalLock.restype = ctypes.c_void_p
        kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]
        return user, kernel

    def copy(self, text):
        user, kernel = self._api()
        owner = user.CreateWindowExW(0, 'STATIC', '', 0, 0, 0, 0, 0, -3, None, None, None)
        if not owner:
            raise RuntimeError('Clipboard unavailable.')
        if not user.OpenClipboard(owner):
            user.DestroyWindow(owner)
            raise RuntimeError('Clipboard unavailable.')
        try:
            if not user.EmptyClipboard():
                raise RuntimeError('Clipboard unavailable.')
            formats = [user.RegisterClipboardFormatW(name) for name in
                       ('CanIncludeInClipboardHistory', 'CanUploadToCloudClipboard')]
            if not all(formats):
                raise RuntimeError('Clipboard privacy formats unavailable.')
            for fmt, data in [(fmt, b'\0\0\0\0') for fmt in formats] + [(13, (text + '\0').encode('utf-16-le'))]:
                handle = kernel.GlobalAlloc(0x0042, len(data))
                if not handle:
                    raise RuntimeError('Clipboard unavailable.')
                pointer = kernel.GlobalLock(handle)
                if not pointer:
                    kernel.GlobalFree(handle)
                    raise RuntimeError('Clipboard unavailable.')
                ctypes.memmove(pointer, data, len(data))
                kernel.GlobalUnlock(handle)
                if not user.SetClipboardData(fmt, handle):
                    kernel.GlobalFree(handle)
                    raise RuntimeError('Clipboard unavailable.')
        except Exception:
            user.EmptyClipboard()
            raise
        finally:
            user.CloseClipboard()
            user.DestroyWindow(owner)
        self.sequence = user.GetClipboardSequenceNumber()
        self.deadline = time.monotonic() + 90

    def clear(self, *, force=False):
        if self.sequence is None or (not force and time.monotonic() < self.deadline):
            return
        user, _ = self._api()
        if user.OpenClipboard(None):
            try:
                if user.GetClipboardSequenceNumber() == self.sequence:
                    user.EmptyClipboard()
                self.sequence = None
            finally:
                user.CloseClipboard()


class SetupServer(HTTPServer):
    def __init__(self, port=0):
        super().__init__(('127.0.0.1', port), SetupHandler)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)
        self.csrf = secrets.token_urlsafe(32)
        self.flow = None
        self.refresh = None
        self.message = ''
        self.clipboard = PrivateClipboard()
        self.deadline = time.monotonic() + 1800
        self.stopping = False
        self.timeout = 1

    def handle_error(self, request, client_address):
        # Base implementation prints tracebacks. Never print request contents.
        pass

    def wipe(self):
        self.flow = self.refresh = None
        self.csrf = secrets.token_urlsafe(32)
        self.clipboard.clear(force=True)


class SetupHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    def _headers(self, status, *, location=None):
        self.send_response(status)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        if location:
            self.send_header('Location', location)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()

    def _host_ok(self):
        return self.headers.get('Host') == self.server.origin.removeprefix('http://')

    def do_GET(self):
        if self.path != '/' or not self._host_ok():
            self._headers(404)
            return
        self._headers(200)
        self.wfile.write(self.page().encode('utf-8'))

    def page(self):
        s = self.server
        csrf = '<input type="hidden" name="csrf" value="' + s.csrf + '">'
        def form(action, content):
            return '<form method="post" action="' + action + '" autocomplete="off">' + csrf + content + '</form>'
        body = '<h1>Sandbox OAuth</h1><p>このPCのみ / Production通信・出品操作・DB接続なし</p>'
        body += '<p role="status">' + escape(s.message) + '</p>'
        if s.refresh:
            body += '<h2>Refresh Token取得済み</h2><p>実値は表示・保存しません。Secretsの対応欄へ貼り付けてください。コピーは90秒で消去します。</p>'
            body += form('/copy', '<label><input type="checkbox" name="private" required> クリップボード履歴・同期・第三者クリップボード管理を無効にしました</label><button>Refresh Tokenを非表示でコピー</button>')
        elif s.flow:
            body += '<h2>Sandboxユーザーの同意</h2><p><a target="_blank" rel="noopener noreferrer" href="' + escape(s.flow.authorization_url, quote=True) + '">eBay Sandboxでログイン・同意</a></p>'
            body += '<p>同意後、遷移先URL全体を下欄へ貼り付けます。コード・URLのスクリーンショットやチャット投稿はしないでください。コードは短時間で失効します。</p>'
            body += form('/exchange', '<label>同意後のURL（非表示）<input type="password" name="callback" autocomplete="off" required maxlength="65536"></label><label><input type="checkbox" name="confirmed" required> Sandboxの認可コードを1回だけ交換します</label><button>Access Token / Refresh Tokenを取得</button>')
        else:
            body += '<h2>Sandbox設定</h2><p>既存Cloud Secretsは変更不要です。ここへの入力はメモリ内だけで使用します。以前露出したAccess Tokenは入力しません。</p>'
            fields = ''.join('<label>' + label + '<input type="password" name="' + name + '" autocomplete="off" required maxlength="4096"></label>' for name, label in (
                ('client_id', 'Sandbox App ID / Client ID'), ('client_secret', 'Sandbox Cert ID / Client Secret'),
                ('redirect_name', 'Sandbox RuName')))
            fields += '<p>今回要求するscope（固定）</p><pre>' + escape('\n'.join(REQUIRED_SCOPES)) + '</pre>'
            fields += '<label><input type="checkbox" name="sandbox" required> Sandbox Keyset / Sandbox RuNameのみを入力しました</label><button>Sandbox同意リンクを準備</button>'
            body += form('/begin', fields)
        body += form('/reset', '<button>入力を破棄してやり直す</button>')
        body += form('/finish', '<button>メモリを破棄して終了</button>')
        return '<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sandbox OAuth</title><style>body{font:16px system-ui,sans-serif;max-width:680px;margin:24px auto;padding:0 16px;color:#202124;background:#fff}h1{font-size:28px}h2{font-size:20px}label{display:block;margin:16px 0}input[type=password]{display:block;box-sizing:border-box;width:100%;min-height:46px;margin-top:6px}button{min-height:46px;max-width:100%;padding:8px 16px;margin:8px 0;cursor:pointer}pre,p,a{white-space:pre-wrap;overflow-wrap:anywhere}form{margin:16px 0}</style><body>' + body + '</body></html>'

    def do_POST(self):
        s = self.server
        try:
            if not self._host_ok() or self.headers.get('Origin') != s.origin:
                raise ValueError()
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                raise ValueError()
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 200000:
                raise ValueError()
            data = parse_qs(self.rfile.read(size).decode('utf-8'), keep_blank_values=True, max_num_fields=10)
            if any(len(v) != 1 for v in data.values()) or not hmac.compare_digest(data.get('csrf', [''])[0], s.csrf):
                raise ValueError()
        except Exception:
            self._headers(403)
            return
        fields = {k: v[0] for k, v in data.items()}
        try:
            if self.path == '/begin' and fields.get('sandbox') == 'on' and not s.flow and not s.refresh:
                settings = OAuthSettings('SANDBOX', client_id=fields.get('client_id', ''),
                    client_secret=fields.get('client_secret', ''), redirect_name=fields.get('redirect_name', ''),
                    scopes=REQUIRED_SCOPES)
                s.flow = OAuthClient(settings).begin_sandbox_authorization()
                s.message = '同意リンクを準備しました。まだAPI通信は行っていません。'
            elif self.path == '/exchange' and s.flow and fields.get('confirmed') == 'on':
                flow, s.flow = s.flow, None
                result = flow.exchange(fields.get('callback', ''), confirmed=True)
                s.refresh = result.refresh_token  # Access token is deliberately discarded.
                s.message = '取得成功。トークンはこのプロセスのメモリ内にのみ保持しています。'
            elif self.path == '/copy' and s.refresh and fields.get('private') == 'on':
                s.clipboard.copy(s.refresh)
                s.message = 'コピーしました。EBAY_SANDBOX_REFRESH_TOKENの値欄に貼り付け、終了してください。'
            elif self.path in ('/reset', '/finish'):
                s.wipe()
                s.message = 'メモリ内の認証情報を破棄しました。'
                s.stopping = self.path == '/finish'
            else:
                raise ValueError()
        except Exception:
            s.message = '処理できませんでした。交換失敗・結果不明の場合は同じコードを再送せず、同意からやり直してください。詳細や秘密値は表示しません。'
        if s.stopping:
            self._headers(200)
            self.wfile.write('<!doctype html><meta charset="utf-8"><p>終了しました。このタブを閉じてください。</p>'.encode('utf-8'))
            return
        self._headers(303, location='/')


def main():
    if os.name != 'nt':
        print('This private clipboard helper requires Windows.')
        return
    with SetupServer() as server:
        print('Sandbox OAuth helper (local only): ' + server.origin, flush=True)
        try:
            while not server.stopping and time.monotonic() < server.deadline:
                server.handle_request()
                server.clipboard.clear()
        finally:
            server.wipe()


if __name__ == '__main__':
    main()
