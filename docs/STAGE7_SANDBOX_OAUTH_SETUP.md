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
