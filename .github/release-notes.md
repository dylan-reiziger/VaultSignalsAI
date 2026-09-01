## Highlights

- Market-first dashboard with Yahoo Finance index data, movers, volume leaders, source timestamps, cache state, and an unavailable-data state.
- Successful sign-in and account creation now lead directly to the dashboard.
- Account-persisted Normal, Compact, and Advanced interface modes.
- Server-enforced Pro access to the protected signal desk.
- Source-aware signal publication: static blueprints are disabled by default and member APIs return only operator-approved signals.
- Removed fabricated stock-feed and performance fallback behavior.
- Restored the local-first desktop market workspace with no website-account requirement.
- Added an in-app Update button that checks the latest GitHub Release and opens its Windows download.

## Download contents

- `VaultSignalsAI-windows-x64-<version>.zip` contains the Windows desktop companion executable.
- The matching `.sha256` file lets you verify the Windows download before running it.
- The source archive excludes local SQLite data, Python environments, bytecode caches, build output, and Git metadata. Follow the included `RELEASE-NOTES.md` to run it locally.