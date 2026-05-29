# VaultSignalsAI Security Runbook

This runbook defines minimum operational controls for account data protection.

## 1) Secrets and Keys

Required environment variables in non-development environments:

- `APP_SECRET_KEY`
- `TOKEN_PEPPER`
- `APP_DATA_ENCRYPTION_KEY`
- `SESSION_COOKIE_SECURE=true`

Rules:

- Never commit secrets to git.
- Rotate all application secrets at least every 90 days.
- Store previous encryption keys in a secure vault only for controlled data migration windows.

## 2) Key Rotation Procedure

1. Generate a new Fernet key for `APP_DATA_ENCRYPTION_KEY`.
2. Deploy a maintenance window build that can read old encrypted values and rewrite with the new key.
3. Validate account profile reads and purchase/billing reads for a sample of users.
4. Revoke old key material from runtime environments.
5. Record rotation date, operator, and validation notes.

## 3) Backups

Backup policy for `vaultsignals.db`:

- Frequency: daily minimum, hourly preferred in production.
- Encryption: mandatory at rest and in transit.
- Retention: 30 days minimum.
- Storage separation: keep backups in a separate account/project from runtime infra.

Backup verification:

- Verify backup file integrity hash after each backup job.
- Alert on backup failures immediately.

## 4) Restore Testing

Run restore drills at least monthly:

1. Restore latest backup into an isolated environment.
2. Run application startup and DB migration (`init_db`) checks.
3. Verify account login, profile read, and purchase list endpoints.
4. Record RTO/RPO metrics and remediation actions.

## 5) Incident Response (Data Exposure)

1. Contain: rotate `APP_SECRET_KEY`, `TOKEN_PEPPER`, and `APP_DATA_ENCRYPTION_KEY`.
2. Disable public write endpoints if abuse is active.
3. Preserve evidence (logs, DB snapshots, request traces).
4. Assess impacted records and exposure scope.
5. Notify stakeholders and users according to legal and policy obligations.
6. Ship corrective patch and document postmortem.

## 6) Security Regression Checklist

Before every release:

- [ ] Auth routes do not accept account identity from client-controlled email when session exists.
- [ ] Password verification always uses `check_password_hash`.
- [ ] Remember tokens are stored hashed, never plaintext.
- [ ] Sensitive fields are encrypted in `*_enc` columns and plaintext columns are redacted/null.
- [ ] Production cookies are `Secure` and `HttpOnly` where appropriate.
- [ ] Rate limiting is active and persistent.
- [ ] Recovery test date is within the last 30 days.
