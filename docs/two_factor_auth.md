# Optional TOTP two-factor authentication

The implementation adds optional authenticator-based two-factor authentication. Existing accounts remain password-only until their owner enables it. Backend migration 0004 was applied on 23 November 2026 after an isolated test run and local database backup. The live backend mounts the workspace with automatic reload, so coordinated updates should pause it before changing dependencies or models.

In the web app, open **Безопасность**, enter the current password, scan the locally generated QR code (or enter the key manually), and confirm a six-digit authenticator code. Save the ten recovery codes shown once after confirmation. Future logins require the password followed by an authenticator or recovery code. To turn MFA off, enter the password and a fresh authenticator or unused recovery code on the same page. Android clients need to implement the second login step before an MFA-enabled account can use them.

All routes below are relative to `/api/auth`. Auth responses, including handled errors and validation errors, carry `Cache-Control: no-store` and `Pragma: no-cache`. The existing public proxy preserves these headers.

| Method and route | Input | Success response |
| --- | --- | --- |
| POST /login | `{email,password}` | Existing token pair for accounts without MFA, or `{mfa_required:true,challenge_token}` |
| POST /mfa/verify | `{challenge_token,code}` | `{access_token,refresh_token,token_type:"bearer"}` |
| GET /mfa/status | Bearer access token | `{enabled:boolean,recovery_codes_remaining:number}` |
| POST /mfa/setup | Bearer token and `{password}` | `{secret,otpauth_uri}` |
| POST /mfa/enable | Bearer token and `{code}` | Token pair plus `recovery_codes:string[]` |
| POST /mfa/disable | Bearer token and `{password,code}` | Fresh token pair |

Setup requires password reauthentication and creates a pending secret valid for ten minutes. A later setup replaces that secret. The pending secret becomes active only after a correct first TOTP code. Enabling increments the account's `auth_version`, revokes previous access and refresh tokens, and returns the current browser's replacement tokens. Disabling requires the password and a fresh TOTP or unused recovery code, deletes the secrets and recovery hashes, increments the version again, and returns replacement tokens. Frontend callers must store those replacement tokens immediately.

MFA login first checks the password and returns a random challenge valid for five minutes. Its SHA-256 digest is persisted. Only one challenge per account is active; repeating password login replaces the earlier challenge. A challenge cannot authenticate an API request or refresh a session. Successful verification consumes it. Refresh accepts only a current session version, and enabled accounts additionally require a token that records successful MFA verification. Tokens issued before this change continue to work for accounts at version zero without MFA. Requests already authorized before revocation can finish.

TOTP uses six digits, 30-second intervals and a one-interval clock tolerance in either direction. The last accepted interval is saved on the user. Reuse of that interval or an older interval fails, including across simultaneous requests. The first enrollment code is consumed too, so wait for the authenticator to display its next code before using TOTP again. PostgreSQL row locks serialize enrollment, verification, recovery consumption, disable and refresh with session-version changes.

There are ten recovery codes, each generated from 128 random bits. The API returns the plaintext set once during enrollment; the database stores SHA-256 hashes. Hyphens, spaces and letter case are normalized when entering recovery codes. Every accepted code is consumed once. Store the set securely outside the account's browser. If the authenticator is lost, use one code to sign in and another unused code plus the password to disable MFA, then enroll a replacement authenticator. The last remaining code can restore login, but a further disable operation still requires a separate unused code or working authenticator. There is no automated support reset or recovery-code regeneration endpoint in this change.

Incorrect password attempts for an existing account and incorrect second-factor attempts use separate persisted counters. Five failures lock that credential category for five minutes and return HTTP 429 with `Retry-After`. A successful check resets its category. A new login challenge or repeated setup cannot reset the MFA failure counter. A challenge with five failed attempts is permanently exhausted, and a new password login is required after the account's lock expires. Invalid credentials normally return 401, expired setup or incompatible enrollment state returns 409, and an unavailable encryption key returns 503. These account limits survive worker and container restarts. They do not provide a network-wide request limit for unknown usernames.

Secrets are encrypted with Fernet using a dedicated `MFA_ENCRYPTION_KEY`. Generate it once with `cryptography.fernet.Fernet.generate_key()` and store the returned URL-safe Base64 value in the backend's private environment or secret manager. Keep it separate from `SECRET_KEY`. Use the same key on every API worker and retain it across rebuilds. Back up the key securely alongside a documented association with the database backup, while keeping the key's access restricted separately from database access. An arbitrary replacement key makes stored TOTP secrets unreadable. Rotation requires decrypting and re-encrypting both active and pending secrets with the old and new keys. The implementation supports one active key.

If the key is absent or invalid, accounts without MFA can still log in, while setup and TOTP verification return 503. Recovery codes still work with an unavailable TOTP key because they use independent hashes. Losing both the authenticator and recovery codes requires a separately reviewed recovery process. Keep the host clock synchronized and serve these endpoints through HTTPS.

PyOTP 2.12.1 handles TOTP generation and verification, including the matched interval used for replay prevention. Cryptography 50.0.2 provides authenticated encryption. The implementation follows the libraries' primary documentation. [PyOTP documentation](https://pyauth.github.io/pyotp/) [Fernet documentation](https://cryptography.io/en/latest/fernet/)

Deployment on a new installation should proceed in this order.

1. Back up the database and provision the persistent encryption key. Confirm the frontend handles the login union and saves replacement tokens after enable and disable.
2. Pause the backend through the existing deployment procedure before updating its source, since the current service reloads changed workspace files.
3. Rebuild the backend image so the new requirements are installed. Apply `alembic upgrade head` using that image and the production database configuration. Revision 0004 adds defaults for existing accounts and the challenge table. The existing Compose startup command already runs migrations before Uvicorn.
4. Start the reviewed backend and deploy the coordinated frontend. Check ordinary login, enrollment, TOTP login, recovery login, refresh and disable through the public HTTPS route with a dedicated test account.

Downgrading 0004 removes MFA state and session-version checks. After any users have enrolled, rollback needs a reviewed security plan rather than an unattended schema downgrade.

Verification used a dedicated Docker network and disposable PostgreSQL 16 container with an in-memory data directory. The source mount was the isolated staging backend. All 31 tests passed across `test_mfa`, `test_calendar`, `test_mcp_calendar`, `test_ai`, `test_metrics` and `test_public_proxy`. The 15 MFA tests cover legacy tokens, password reauthentication, encryption, pending setup, expiry, replacement secrets, session revocation, refresh restrictions, recovery consumption, persisted throttling, unavailable keys and simultaneous requests. Concurrent enrollment, challenge reuse, and TOTP/recovery reuse across distinct challenges each admitted only one request.

The migration was also downgraded to 0003 and upgraded with an existing account in the disposable test database. That account retained working legacy access/refresh tokens and password login. `alembic check` reported no model drift. The suite emitted a python-jose UTC deprecation warning and AnyIO test-client resource warnings. After the live upgrade, all 16 existing backend regression tests passed again. The Next.js Pages export, including `/security/`, and TypeScript checks passed.

To rerun tests, use an isolated migrated PostgreSQL database and the rebuilt backend image. Set `DATABASE_URL`, `MFA_TEST_DATABASE_URL` and `AGENT_TEST_DATABASE_URL` to that same disposable database before running the following commands inside the test container. MFA tests create and remove their own users and require PostgreSQL for locking checks.

```sh
alembic upgrade head
alembic check
python -m unittest -v test_mfa test_calendar test_mcp_calendar test_ai test_metrics test_public_proxy
```
