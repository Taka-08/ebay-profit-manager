# Stage 7: Sandbox Inventory adapter

## Status and release boundary

- This change implements real HTTP request construction, not a claim of successful live Sandbox operation.
- No Sandbox credentials or verified test listing were available during implementation. Live verification is SKIPPED.
- Production provider is unconditionally disabled, including when `EBAY_ENABLE_PRODUCTION_WRITES=true`.
- Default remains MOCK. Existing Cloud Secrets are unchanged; no new migration runs at startup.
- No production DB migration, eBay call, OAuth grant/refresh or normal listing registration was performed.

## Official contract (reviewed 2026-09-18)

Primary references:

- [Inventory OpenAPI](https://developer.ebay.com/api-docs/master/sell/inventory/openapi/3/sell_inventory_v1_oas3.json)
- [Bulk price and quantity updates](https://developer.ebay.com/api-docs/sell/static/inventory/bulk-updates.html)
- [Inventory overview and listing ownership](https://developer.ebay.com/api-docs/sell/inventory/static/overview.html)
- [Out-of-stock control](https://developer.ebay.com/api-docs/user-guides/static/trading-user-guide/out-of-stock-enable.html)
- [Seller identity](https://developer.ebay.com/api-docs/user-guides/static/trading-user-guide/user-mgmt-user-info.html)
- [Trading OAuth headers](https://developer.ebay.com/devzone/xml/docs/Concepts/MakingACall.html)
- [OAuth authorization](https://developer.ebay.com/develop/guides/sell/authorization)
- [Identity OpenAPI](https://developer.ebay.com/api-docs/master/commerce/identity/openapi/3/commerce_identity_v1_oas3.json)

Inventory Item is seller/SKU inventory; Offer binds it to marketplace, price and listing. Published Offer's
`listing.listingId` is the Item ID. Arbitrary Seller Hub/Trading listings cannot be assumed to have an Offer.
No automatic listing migration or Trading write fallback is implemented.

Supported subset: Inventory-managed, single variation, fixed price GTC, one Offer globally for the SKU,
no inventory groups, auction allocation, pickup or warehouse distributions. Other cases stop before writes.

- Price: `POST /sell/inventory/v1/bulk_update_price_quantity`, one offer price only.
- Quantity: same endpoint; set both Inventory Item availability and Offer allocation. Readback compares both,
  not just their minimum (effective availability). Single-offer restriction prevents intentionally sharing stock.
- Zero: quantity update, not withdrawal. Requires successful read of OutOfStockControlPreference=true.
- End: only explicit approved END_LISTING -> `POST /offer/{offerId}/withdraw`. Keeps the unpublished Offer.
- Readback: GET offer, GET offers by SKU, GET inventory item. HTTP success alone never confirms local success.
- Trading calls are strictly READ ONLY: GetUser identifies the token owner; GetUserPreferences reads OOS setting.
  Identity API is not used for this check because its Sandbox documentation says it returns mock data.
- Stable seller binding is SHA256 of GetUser's EIASToken (a seller identifier, not an authorization token).
  Both configured EIAS and UserID must match. Raw responses and personal account information are not saved.

## Reuse and storage

The existing ApprovalService retains proposal/edit/approval/cancel, immutable payload, Outbox, attempt history,
execution claim, audit and failure/reconciliation flow. Fixed table hooks route the Sandbox subclass only to:

- `sandbox_marketplace_listings`: explicit product link, Item/SKU/site, seller/Offer/API/environment binding,
  current remote snapshot and local revision. No normal listing_id may be assigned.
- `sandbox_approval_requests`: SANDBOX only, three allowed actions, unique idempotency key.
- `sandbox_approval_attempts`: attempts and sanitized errors.
- `sandbox_api_dispatches`: durable INTENT before network, then CONFIRMED, then PROJECTED in the same
  transaction as local snapshot/approval completion. Unique unresolved target and key prevent another send.

`0006_sandbox_inventory` is explicit, additive, local-only, and **not** in startup MIGRATIONS. Existing 0001-0005,
normal listings, products and shipping/profit snapshots are not rewritten. Shared Outbox and audit receive
Sandbox records only when explicitly approving/executing in the local test database.

## Execution and uncertainty

1. Explicitly bind an existing Sandbox test Offer to a test product after remote identity/target reads.
2. Propose and review target, current/new values, site, currency, seller fingerprint and Offer/Item IDs.
3. Human approval freezes the payload and queues a namespaced Outbox event atomically.
4. Claim execution atomically. Another unresolved request for that binding prevents execution.
5. Compare local product SKU and listing SKU independently with approval; read and compare remote before-values.
6. Provider independently rechecks approval/Outbox/target, then records INTENT before HTTP, outside any long DB transaction.
7. Send once, inspect all per-item API statuses, read back, then atomically project confirmed result.
8. Timeout, network loss, 5xx, partial success or post-send DB failure -> UNKNOWN, no blind resend.
9. Reconciliation reads remote values against stored intent; matching result repairs DB without dispatch.
   Mismatch/ambiguous read remains UNKNOWN and requires human investigation. It does not unlock a retry.

401/403/429 are sanitized. No automatic token refresh-and-resend after a failed write. Access token refresh
is allowed only before requests in explicitly enabled Sandbox, in memory only. Request bodies/tokens/raw exceptions
are not logged. Redirects, proxies, arbitrary routes and production hosts are disallowed in the transport.

## Local setup for a later live Sandbox session

Do not modify the existing Cloud app or production Secrets for this step. Create an isolated local DB with
the existing foundation, then explicitly call `initialize_sandbox_storage(factory)` from `sandbox_migration`.
This refuses a configured Turso connection. Use a verified Sandbox seller/test listing only.

Required environment variables or existing `[ebay]` secret keys (values deliberately omitted):

- `EBAY_EXECUTION_MODE=SANDBOX`, `EBAY_ENVIRONMENT=SANDBOX`, `EBAY_ENABLE_SANDBOX_API=true`.
- `EBAY_ENABLE_PRODUCTION_WRITES=false` (default false; true still cannot unlock Production).
- `EBAY_SANDBOX_USER_ACCESS_TOKEN` for a newly issued, short-lived Developer Portal Sandbox User token,
  or CLIENT_ID + CLIENT_SECRET + REFRESH_TOKEN under the same Sandbox prefix. The short-lived token
  takes precedence while present; the older `EBAY_SANDBOX_ACCESS_TOKEN` key is not read from Secrets.
  Do not reuse any token previously exposed in a screenshot. Never paste a token into source, tests, or logs.
- `EBAY_SANDBOX_SCOPES`: space-separated `https://api.ebay.com/oauth/api_scope` and
  `https://api.ebay.com/oauth/api_scope/sell.inventory`, actually granted via seller consent.
- `EBAY_SANDBOX_SELLER_EIAS`, `EBAY_SANDBOX_SELLER_USER_ID`: independently verified test account.
- `EBAY_SANDBOX_ALLOWED_OFFER_IDS`: comma-separated explicit test Offer IDs.
- Optional `EBAY_SANDBOX_REDIRECT_NAME`: Sandbox RuName for manual developer-portal consent.

For the Developer Portal short-token path, the existing `ebay-sandbox-start` page has a setup-key-
protected `Sandbox認証を確認（GETのみ）` button. It allows exactly one attempt per Streamlit session even
while the app remains in MOCK mode. It sends only one fixed GET to the Sandbox Inventory `getVersion`
endpoint, touches no DB, does not refresh a token, and displays only a fixed HTTP result category.
The regular Sandbox write guard remains unchanged. A missing/expired token fails closed; there is no
Production fallback. The separate Streamlit OAuth authorization error does not need to be retried.

Obtain Sandbox keyset, test seller and seller User OAuth grant in the eBay Developer portal. No interactive
authorization-code callback or new token storage is built into the public app. The existing OAuthClient's
authorize() remains disabled; refresh uses only the Sandbox token endpoint and never saves secrets.

Create/verify a Sandbox Inventory test listing manually outside this tool. Read its exact Item ID, Offer ID,
SKU, site, currency and seller; enable OOS control on the test account if testing zero (this app never changes it).
Only if no suitable published Inventory Offer exists, prepare Sandbox fulfillment/payment/return business
policies and an Inventory Location when creating that test listing. They are not additional inputs to this
adapter's change operations. Obtain the seller EIAS identifier with the read-only GetUser call in the developer
test tools and verify that it belongs to the intended Sandbox account before pinning it locally.
Use `SandboxApprovalService.bind_existing_test_offer(..., test_target_confirmed=True)` for explicit local binding.
Then the existing approval UI in SANDBOX mode supports the three actions and human confirmation.
Use separate test listings where necessary; test withdrawal last. Preserve request/result evidence without tokens.

## Known limitations and Production blockers

- Live Sandbox is unverified; fake HTTP proves application safety paths, not account entitlements/API acceptance.
- Scope configuration is an allowlist assertion; only real authorization/read calls can prove granted scopes.
- No conditional-write/ETag compare-and-swap exists in the selected endpoints. Local leases stop this app's
  competing executions, not sales/other tools between remote read and write. Production remains blocked.
- Multi-request reads are not an atomic remote snapshot. Changed or unsupported responses stop/reconcile.
- Post-timeout equality proves state convergence, not causal attribution to our request.
- Crash after INTENT but before dispatch remains UNKNOWN; no automatic inference that no request was sent.
- Partial remote updates are not automatically reversed. No compensation write, forced unlock or retry button.
- A remote price/quantity conflict requires cancelling the unexecuted proposal, explicitly refreshing the
  isolated snapshot, then proposing/approving again. Refresh refuses pending approval or unresolved dispatch
  and never changes identity or normal listing snapshots. It cannot bypass UNKNOWN.
- Actor name is the existing self-reported audit identifier, not authenticated role-based access control.
- No Production OAuth, account linking, production migration, worker, order/shipping or Stage 8 work.

## Verification

`tests/test_sandbox_inventory.py` uses fake HTTP and disposable SQLite/local libSQL; production and OAuth
endpoints are never called. An explicit skipped test records the missing live Sandbox verification.
`tests/manual/sandbox_preview.py` and `verify_sandbox_layout.cjs` are fake-HTTP local-only visual checks.
Do not present these screenshots as live Sandbox evidence.

Verified on 2026-09-18:

- Added 54 discovered tests: 53 passed, 0 failed/errors, 1 explicitly skipped live Sandbox check.
- Full working-tree regression: 428 tests, 427 passed, 0 failed/errors, 1 live Sandbox skip.
- Release candidate reconstructed from HEAD plus these 13 files (excluding unrelated FedEx work):
  416 tests, 415 passed, 0 failed/errors, 1 live Sandbox skip. All 12 code/test files match the tested candidate.
- Chrome and WebKit previews: 1440/390/414/360px, all eight cases passed. No horizontal overflow,
  title/header overlap or UI exceptions; visible action buttons are at least 46px high. Offer, seller
  fingerprint, marketplace, currency and Production-disabled labels remain readable.
- Production Turso was queried read-only: all 94 listing rows exactly match the pre-0005 backup,
  including shipping JSON; all 94 product_id values remain NULL. Migration 0006 is absent.
- Nine protected files, including the existing FedEx changes and Cloud Secrets, match saved hashes.
- No actual Sandbox, Production eBay or OAuth request was made. Do not count the skip as a pass.

Release scope (13 files; unrelated FedEx work and local verification artifacts are excluded):

- `integrated_ebay/approval_repository.py`
- `integrated_ebay/approval_service.py`
- `integrated_ebay/approval_ui.py`
- `integrated_ebay/change_safety.py`
- `integrated_ebay/ebay_api.py`
- `integrated_ebay/sandbox_http.py`
- `integrated_ebay/sandbox_inventory.py`
- `integrated_ebay/sandbox_migration.py`
- `integrated_ebay/sandbox_service.py`
- `tests/test_sandbox_inventory.py`
- `tests/manual/sandbox_preview.py`
- `tests/manual/verify_sandbox_layout.cjs`
- `docs/STAGE7_SANDBOX_API.md`
