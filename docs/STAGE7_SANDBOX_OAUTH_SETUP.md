# Sandbox Refresh Token setup

This is an OAuth-only local Windows helper, not a Cloud app or an Inventory test.
It does not read existing Secrets, initialize a database, run migrations, change
execution-mode settings, or call any listing API. Do not deploy the helper to Cloud.

## Start and consent

Run `python scripts/sandbox_oauth_setup.py` from the repository. Use the printed
`http://127.0.0.1:<port>` URL in a browser on this same Windows PC. The process exits
after 30 minutes or the Finish button. Python's standard library is sufficient.

1. Disable clipboard history, cloud clipboard sync and third-party clipboard
   managers. Use a private browser window without untrusted extensions. Never put
   credentials in Codex/chat, command arguments, screenshots or online decoders.
2. Enter the Sandbox Client ID, Client Secret and OAuth-enabled RuName into the
   masked local form. This input is memory-only; existing Cloud Secrets are untouched.
3. Open the helper's Sandbox consent link, not the Portal's short-token shortcut.
   The link requests exactly these two scopes, with a fresh random state:
   - `https://api.ebay.com/oauth/api_scope`
   - `https://api.ebay.com/oauth/api_scope/sell.inventory`
4. Sign in as the Sandbox test seller and consent. The RuName must have a working
   HTTPS Auth Accepted URL. Copy the resulting full URL into the helper's masked
   field promptly, then explicitly exchange it. The helper never fetches that URL;
   it validates state and decodes the code once. A missing/changed state stops the
   flow. Do not bypass this check; check the accepted URL configuration instead.
5. On success, only the Refresh Token is kept in process memory. The new Access
   Token is received but discarded, not displayed or saved. Copy the Refresh Token
   using the explicit button, paste into the intended Secrets editor, then Finish.
   Windows history/sync exclusion formats are set. The copied value is cleared
   after 90 seconds if the clipboard has not since changed. Other processes on the
   PC can still read a clipboard, so this is not a substitute for a trusted device.

OAuth necessarily returns the code in the browser's redirect URL. Never screenshot
or share that URL; close the private consent tab after exchange. Nothing in the
helper logs the URL, code, tokens, headers or raw API errors. HTTP caches and framing
are disabled. Lost results/timeouts consume the attempt: start a new consent flow,
never resend the same code. There is no token export file or download endpoint.
Python memory is released, not cryptographically zeroed; crash dumps/swap and
browser/OS extensions are outside this helper's guarantee.

## When to enter Streamlit Secrets

Before consent: no Cloud Secrets change is needed. The local masked form supplies
Client ID, Client Secret and RuName; scopes are fixed to the pair above.

After successful consent/exchange: the user can store the following names in
`[ebay]` using the intended Streamlit app's private Secrets editor. Confirm the
destination before consent and preserve all existing entries. Storing Sandbox
credentials does not authorize changing the app's existing MOCK execution mode.
A protected local Secrets file must be outside OneDrive/Git.

- `EBAY_SANDBOX_CLIENT_ID`
- `EBAY_SANDBOX_CLIENT_SECRET`
- `EBAY_SANDBOX_REDIRECT_NAME`
- `EBAY_SANDBOX_SCOPES`
- `EBAY_SANDBOX_REFRESH_TOKEN`

The SCOPES entry is a space-separated string of the two exact scope URLs above.
Leave `EBAY_SANDBOX_ACCESS_TOKEN` unset for refresh-based operation. Never reuse the
previously exposed token. RuName is required for the initial code exchange, not for
the refresh grant. This change does not implement timed Access Token renewal.

The helper never modifies Cloud Secrets or switches its MOCK mode. The current
Sandbox execution service deliberately refuses a Turso-configured runtime, even
if Sandbox credentials are stored. Obtaining a Refresh Token does not lift that
guard or prepare a test Offer. Future listing tests need separate authorization
and an isolated Sandbox execution environment; do not enable them in this task.

## Existing Cloud app callback (Sandbox only)

The listing manager registers three hidden, top-level pages before its normal
`main()` / `init_db()` path. Use the verified existing listing-manager subdomain,
not the profit calculator subdomain, for these URLs:

- Accepted: `https://ebay-profit-manager-9nrrrcznpgcesspgdjcssj.streamlit.app/ebay-sandbox-accepted`
- Declined: `https://ebay-profit-manager-9nrrrcznpgcesspgdjcssj.streamlit.app/ebay-sandbox-declined`
- Initiation: `https://ebay-profit-manager-9nrrrcznpgcesspgdjcssj.streamlit.app/ebay-sandbox-start`

Do not add `code`, `state`, credentials, or other query values to the registered
URLs. Keep `EBAY_SANDBOX_REDIRECT_NAME` set to the Sandbox RuName, not the URL.
Never use Streamlit's reserved `/oauth2callback` OIDC route for eBay OAuth.

The Cloud flow remains disabled until the owner configures the four pre-consent
Sandbox settings above (Client ID, Client Secret, RuName, scopes) and a random,
at least 32-character
`EBAY_SANDBOX_OAUTH_SETUP_KEY` in the listing-manager app's private `[ebay]`
Secrets section. Keep the app in MOCK mode and Production writes disabled.
The key protects initiation even if the app is public; the one-time random
state protects the callback exchange. Hidden navigation alone is not
authentication. Do not put the key in a URL,
source file, chat, log, or screenshot. No settings are changed by the callback.

The owner starts on the initiation page, enters the setup key, and follows the
Sandbox consent link. The server holds the random state and a copy of the
Sandbox credentials in process memory for ten minutes; the configured values
remain in private Cloud Secrets. Callback navigation creates a new
Streamlit session, so the server checks the process-local state rather than
relying on `st.session_state`. A restart or process mismatch loses the flow and
fails closed. The accepted page clears app query parameters and immediately
checks the Sandbox-only configuration and the one-time state before making one
request to the fixed Sandbox token endpoint. No second user action delays the
code exchange. A lost/unknown result is never resent. Declined callbacks
never exchange. Neither callback calls the listing database or migrations.

On successful exchange, the access token is discarded; the refresh token is
placed in a masked password input for the owner to copy into the intended
private Streamlit Secrets editor. Server-side session state clears after two
minutes on the next rerun, but an already-rendered browser field may remain
until the page is refreshed or closed. The token is not printed, logged by
application code, or stored in a file or database. The owner must use a
trusted browser with clipboard history/sync and untrusted extensions disabled,
then select "受け渡しを終了" and close the tab. Masking does not keep a token
out of the owner's browser memory, WebSocket traffic, clipboard, or browser
developer tools. The existing PC-only helper remains available and avoids
sending the refresh token through Cloud UI at all.

An OAuth authorization code necessarily appears in the redirected browser URL.
`st.query_params.clear()` clears the inner app URL, but the outer Community Cloud
browser URL may retain `code` and `state` even after exchange. App code does not
log them, but Community Cloud ingress/access-log behavior is not controlled or
guaranteed by this repository. After a successful one-time exchange the code
cannot be reused. Do not share the callback URL; close the consent tab after
the refresh-token handoff. Verify the app's public/private redirect behavior
and callback routing before registering these URLs or starting live consent.
The Streamlit page cannot guarantee callback-specific `Cache-Control` or
`Referrer-Policy` response headers on Community Cloud; use a private browser
session without untrusted extensions for this Sandbox-only handoff.
If no approved secure destination is ready, do not start consent yet: memory-only
results will be lost on helper shutdown and must be obtained again.

## Safety and sources

- Consent host: `auth.sandbox.ebay.com`; token host: `api.sandbox.ebay.com`.
- Only `POST /identity/v1/oauth2/token` with `grant_type=authorization_code`.
- No redirects, proxy inheritance, automatic retries, production fallback or writes.
- Existing refresh, Mock, approval and Production-provider guards are preserved.
- Offline tests use fixtures and mocked HTTP/clipboard; they are not live OAuth evidence.

Official references:
- https://developer.ebay.com/support/knowledge-base/5075
- https://developer.ebay.com/develop/guides/sell/authorization
- https://learn.microsoft.com/en-us/windows/win32/dataxchg/clipboard-formats
