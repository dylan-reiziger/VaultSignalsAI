# Request Audit Tracker

This file tracks feature requests and quality-audit checkpoints.

## Cycle Rule
- Every 5 completed requests, run a full quality pass:
- Hardcoded-value review
- Organization/refactor review
- Runtime sanity check
- Error scan

## Current Cycle
- Cycle start: Request 6
- Current count: 5/5
- Next full audit at: completed in request 10

## Request Log
1. Workflow setup: created request audit tracker and enabled 5-request quality checkpoints.
2. Admin Signals panel: added admin page, create/publish workflow, and admin-only API routes.
3. Admin signal CRUD expansion: added edit and delete APIs/UI, plus reusable backend signal payload validation.
4. Signup reachability fix: verified backend health and improved auth error messaging for wrong-origin usage (Live Server/file preview vs Flask origin).
5. Signup schema migration fix: repaired legacy accounts-table migration, verified live account creation, and added local verification-link fallback when SMTP is unavailable.
6. Unverified-account recovery flow: added resend verification and change-unverified-email endpoints, plus login-modal actions for direct recovery.
7. Manual token verification UX: added verify-token API and auth-modal token input/button for local no-SMTP verification.
8. Removed email verification requirement: new accounts are active immediately and login no longer blocks on verified status.
9. Forced verified-state compatibility: backfilled existing accounts and enforced verified=1 at the database layer to neutralize stale verification gating.
10. Full repo audit and hardening: centralized SMTP and billing config, removed redundant transaction commits, standardized purchase timestamps, hardened payment/request validation, and reran runtime checks.

## Full Audit Result - Request 5
- Static error scan: clean for Python and frontend files touched in this cycle.
- Hardcoded-value review: no new duplicated constants introduced in this fix; migration logic centralized in app startup.
- Wiring check: signup endpoint, auth frontend parsing, and local verification flow verified.
- Runtime sanity check: Flask booted on 127.0.0.1:5000 and /api/session returned 200.
- Outcome: account creation now returns 201 successfully on the existing local database.

## Full Audit Result - Request 10
- Static error scan: clean for Python, JS, CSS, and template files after hardening changes.
- Hardcoded-value review: centralized SMTP, billing-cycle durations, loyalty thresholds, renewal lead days, and community rank mapping.
- Robustness review: removed redundant `conn.commit()` calls, replaced silent migration failure handling with logging, and hardened PayPal/request JSON validation.
- Timestamp review: standardized new purchase/reminder timestamps to database format while keeping ISO parsing backward compatible.
- Runtime sanity check: Flask `test_client()` returned `200` for `/`, `/price`, and `/api/session`; timestamp helpers and tier/rank config loaded correctly.

## Full Audit Template (every 5th request)
- [ ] Run static error scan for Python, JS, CSS, and templates.
- [ ] Search for duplicated hardcoded constants and consolidate where needed.
- [ ] Check route/template/script wiring after latest changes.
- [ ] Run app startup sanity check.
- [ ] Summarize issues fixed and any remaining risks.
