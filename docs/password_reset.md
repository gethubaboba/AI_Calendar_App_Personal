# Email password reset

Backend implementation was staged in `.calendar-dev/reset-backend/backend` against commit `8d39b7a`. On 23 November 2026 the coordinating agent reviewed and applied `.calendar-dev/reset-backend.patch`, rebuilt backend/public-api, and reported migration 0005 deployed. The nine backend files in the workspace match the final tested staging files. The live backend mounts the workspace and reloads source files, so future source updates require coordinated deployment.

The frontend Pages build passed. The owner supplied a Gmail app password privately in `backend/.env`, and the deployed API authenticated successfully to Gmail SMTP without sending a test message. Inbox delivery and the owner's password change remain pending. The disposable backend test database and network have been removed.

The frontend contract uses `POST /api/auth/password/forgot` with `{email}` and `POST /api/auth/password/reset` with `{token,new_password}`. Both return `{message:string}` on success. Reset returns no login tokens. Valid reset links have the fixed configured HTTPS frontend URL followed by `#token=...`. Read the fragment in the reset page and remove it from the address bar with `history.replaceState` before loading external resources. Send the token only in the reset request body.

New passwords must have at least 12 characters and at most 72 UTF-8 bytes. Whitespace-only, numeric-only, fewer than four distinct characters and a small list of obvious common passwords are rejected. This local list provides basic weak-password screening; it is not a comprehensive breached-password database. The API returns a sanitized 422 message without echoing tokens or passwords.

Forgot-password returns the same HTTP 200 body for existing accounts, unknown addresses, cooldowns and exhausted delivery capacity. Missing or invalid mail configuration returns the same 503 for every valid email address. SMTP delivery is asynchronous, so an acknowledgement does not establish delivery. Provider errors produce a generic backend log event without the address, token, password or provider response.

Each reset token contains 32 random bytes and expires after 15 minutes. PostgreSQL stores its SHA-256 digest, user, expiry and session version. A replacement request invalidates the previous token when its background job issues a new one. Redemption locks the user and token rows and consumes the token atomically. Expired, already-used, malformed and version-invalidated links return 400. Successful reset changes the bcrypt hash, increments `auth_version`, removes reset tokens and pending MFA login challenges, clears pending TOTP enrollment, and resets password retry counters. Enabled TOTP, accepted TOTP timecode, recovery hashes and MFA retry counters survive. Existing access and refresh tokens fail after completion; a new login still requires enabled MFA. Merely requesting a reset leaves the current password and sessions working.

Email addresses are trimmed and lowercased for lookup and throttling. Only their SHA-256 digests are stored in the rate table, including unknown addresses. Delivery uses the address already stored on the selected account. If legacy data contains multiple accounts differing only by email case, delivery is suppressed until that ambiguity is corrected.

The default limits are one admitted request per email per minute, five per email per hour, ten globally per minute and 100 globally per hour. Unknown addresses consume the same budgets. Fixed windows and counts live in PostgreSQL and survive restarts. A nonblocking transaction lock serializes admission across workers. Old email-rate rows are pruned on later admitted requests after a day of inactivity, bounding their growth under the global budget. Four database leases bound simultaneous background jobs across API workers; each lease expires after 60 seconds. Busy or exhausted requests retain the uniform response.

Account lookup and mail delivery start after the response body has been sent. SMTP runs in a short-lived subprocess with a 20-second hard deadline, including DNS/connect work, and five-second socket timeouts. Tokens and credentials pass through stdin, while subprocess stdout and stderr are discarded. Failed delivery removes only that attempt's token, so a delayed failure cannot delete a newer link. A process crash can lose an in-memory job; the user can retry after the cooldown. These controls reduce timing differences but do not guarantee constant-time behavior under database or system contention. A global abuse limit can temporarily suppress legitimate requests as well.

Configure the following in the backend's private environment. Keep credentials out of source control, chat, screenshots and command output. The frontend receives none of these SMTP values.

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USERNAME=your-sender-address@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your-sender-address@gmail.com
SMTP_TLS_MODE=ssl
PASSWORD_RESET_URL=https://gethubaboba.github.io/AI_Calendar_App_Personal/reset-password/
```

For a provider using STARTTLS, set `SMTP_TLS_MODE=starttls` and its documented port, commonly 587. The implementation uses `SMTP_SSL` or requires successful STARTTLS before authentication. Both modes use `ssl.create_default_context()` for certificate and hostname verification. An unavailable STARTTLS upgrade fails delivery. The URL must be a configured HTTPS address without credentials, query parameters or a fragment. Request Host headers never choose the destination. [Python SMTP documentation](https://docs.python.org/3/library/smtplib.html) [Python TLS documentation](https://docs.python.org/3/library/ssl.html#ssl.create_default_context)

For Gmail, use a dedicated sender account where practical. The account owner must enable Google's 2-Step Verification and create an app password for this application, then save it privately as `SMTP_PASSWORD`. Some organization policies and Advanced Protection accounts do not offer app passwords. Changing the Google account password revokes its app passwords. Gmail supports implicit TLS on `smtp.gmail.com:465` and STARTTLS on port 587. The Gmail account's security configuration is separate from optional TOTP inside Smart Calendar. [Google app-password instructions](https://support.google.com/accounts/answer/185833) [Google SMTP settings](https://developers.google.com/workspace/gmail/imap/imap-smtp)

For initial installation, deployment and delivery verification follow this order. The current deployment has completed the source and migration steps; SMTP configuration and real delivery verification remain.

1. Review the patch and frontend handling of the fragment, generic acknowledgement, password policy and error states. Back up PostgreSQL.
2. Pause the live reload backend through the deployment procedure before applying `.calendar-dev/reset-backend.patch` from the repository root. Provision the SMTP settings privately. No new Python dependencies are required.
3. Rebuild the backend image and apply `alembic upgrade head` with its deployment database configuration before starting the reviewed service. Migration 0005 adds the reset-token/rate/lease tables and seeds the global limits and four delivery slots. Existing users and MFA secrets are untouched by the migration.
4. After the frontend reset page is deployed, use a dedicated test account with a mailbox you control. Submit forgot-password once, check the inbox and spam folder, and open the HTTPS link. Confirm the fragment is removed from the address bar, choose a new password, and verify the old link fails on reuse. Confirm old sessions fail and enabled MFA is still required on login.
5. Check backend logs for the generic `password_reset_delivery_failed` event if delivery does not arrive. Check credentials, sender permissions, port/TLS mode and outbound connectivity privately. A 503 before delivery indicates missing/invalid configuration or database admission failure. Provider authentication failures occur after the uniform acknowledgement.

Verification used the existing Python 3.12 test image with the staged backend mounted read-only, plus an isolated PostgreSQL 16 container with an in-memory data directory. All 50 tests passed across `test_password_reset`, `test_mfa`, `test_calendar`, `test_mcp_calendar`, `test_ai`, `test_metrics` and `test_public_proxy`. The 19 reset/mail tests cover expiry, reissue, concurrent single use, session revocation, MFA preservation, response privacy, admission limits, background ordering, TLS requirements, mail timeout and delayed-failure cleanup. SMTP was mocked throughout; real delivery awaits sender configuration and the coordinated integration check.

Migration 0005 was downgraded to 0004 and upgraded with a synthetic MFA-enabled account. Its MFA secret, recovery hashes, existing sessions and login flow survived. `alembic check` reported no model drift. Existing python-jose UTC deprecation and AnyIO test-client resource warnings remain.

For regression tests, set `DATABASE_URL`, `RESET_TEST_DATABASE_URL`, `MFA_TEST_DATABASE_URL` and `AGENT_TEST_DATABASE_URL` to the same disposable migrated PostgreSQL database inside the test container, then run the following. The reset test suite clears only its test database's reset throttles and leases while preparing each case.

```sh
alembic upgrade head
alembic check
python -m unittest -v test_password_reset test_mfa test_calendar test_mcp_calendar test_ai test_metrics test_public_proxy
```
