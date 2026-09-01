# VaultSignalsAI Flask v1.0.8

## Included changes

- Added a market-first dashboard at `/dashboard` with Yahoo Finance index data, movers, volume leaders, source timestamps, cache state, and clear unavailable-data handling.
- Sends successful web authentication to the market dashboard.
- Persists Normal, Compact, and Advanced interface modes per account.
- Enforces active Pro entitlement checks for the Pro signal desk.
- Removes unsupported performance fallback data and fabricated stock quote fallback behavior.
- Adds a signal provenance policy: static blueprints are disabled by default, optional development fixtures are draft-only, and member APIs serve only operator-approved signals.
- Shows signal provenance in the restricted administrator signal table.

## Run locally

1. Create and activate a Python virtual environment.
2. Install dependencies from `vaultsignalsai_flask/requirements.txt`.
3. Run `python app.py` from this package root.
4. Open `http://127.0.0.1:5000/dashboard`.

## Windows desktop companion

The GitHub Release includes a separate `VaultSignalsAI-windows-x64-<version>.zip` download. Extract it and run `VaultSignalsAI.exe`. The companion saves its preferences in `%LOCALAPPDATA%\VaultSignalsAI\client_config.json`.

The desktop workspace uses only a local profile and public market data; it does not require a website account. Select **Update** in the application header to check the latest GitHub Release and open its Windows download.

## Development-only sample signals

Static signal blueprints are disabled by default. To seed draft-only local fixtures, set:

```text
SEED_DEMO_SIGNAL_BLUEPRINTS=true
```

Published member signals require an administrator to explicitly publish or update the record.