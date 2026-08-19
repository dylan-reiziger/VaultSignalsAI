# VaultSignalsAI

VaultSignalsAI is a Windows desktop learning tool for exploring public crypto-market data. It shows live market movement, one-hour candles, volume, a transparent observed-volatility scenario, and optional public sentiment input.

## What it does

- Displays public exchange market data, order-book snapshots, candles, volume, and recent price movement.
- Labels the current market reading from observable inputs. Indicator strength is not a probability of a future move.
- Draws a 12-hour scenario midpoint with upper and lower volatility bands from recent candle returns, realised volatility, relative volume, and an optional public sentiment source.
- Includes a timestamped scenario report and a **Learn & risk** page that explains the educational product boundaries.

## Important boundaries

VaultSignalsAI is for education and general market research. It does not provide personal investment advice, a recommendation to buy, sell, or hold an asset, or a promise of profit. Cryptoassets are high risk and users can lose all of the money they invest.

Read [LEGAL-NOTICE.txt](LEGAL-NOTICE.txt) before distributing the application.

## Run from source

Requirements: Windows, Python 3.13 or later, and the standard-library Tkinter package.

```powershell
.\.venv\Scripts\python.exe .\vaultsignals_desktop.py
```

## Build a Windows download

The repository contains a reproducible Windows packaging script. It includes the public release notice and business review guide in the build output.

```powershell
.\scripts\build-release.ps1 -Version "v0.1.0"
```

Upload the complete `release/VaultSignalsAI-windows-x64.zip` archive, not only the executable. Users should extract the archive and run `VaultSignalsAI.exe`. Before public distribution, test the extracted archive on a separate Windows device and sign the executable and installer with a code-signing certificate.

## GitHub downloads and business review

This repository includes a GitHub Actions workflow at [.github/workflows/windows-release.yml](.github/workflows/windows-release.yml).

1. Create a **private GitHub repository** for the business review and push this project to it.
2. Give the business holder repository access so they can review the source, TODO list, and release materials.
3. In GitHub **Actions**, run **Build Windows download** to create a downloadable review artifact.
4. After internal approval, create a version tag such as `v0.1.0` and push it. The workflow creates a GitHub Release containing the Windows ZIP.

See [BUSINESS-REVIEW.md](BUSINESS-REVIEW.md) for the reviewer steps and [TODO.md](TODO.md) for the outstanding release work.

## Logo and release checklist

Place the original owned PNG logo at `assets/VaultSignalsAI-logo.png`. VaultSignalsAI then shows it in the loading screen and application window. Add `assets/VaultSignalsAI-logo.ico` too when it is available so the Windows executable uses the same icon after rebuilding.

The app's **Release checklist** mirrors [TODO.md](TODO.md) and stores the checklist ticks locally. It is an operational tracker, not evidence of legal or FCA compliance.

## Optional public sentiment connector

In **Settings**, an optional HTTPS connector may provide a JSON object with a numeric `score` from `-100` to `100`, plus optional `source` and `updated_at` fields. Use a licensed public-data or social-listening provider. If it is blank, the scenario uses candles and volume only.

## UK public release and FCA status

The application is not FCA approved or FCA authorised merely because it has a disclaimer, downloadable package, or educational content. Do not make that claim unless the relevant status has been independently verified and applies to the product and promotion.

Before making a download, subscription, website, or marketing material available in the UK, obtain qualified, current legal and compliance advice. Confirm whether the product, audience, pricing, marketing, and cryptoasset financial promotions are regulated, then implement the required approval, authorisation, risk warnings, privacy, consumer-protection, and record-keeping processes. This is not legal advice.
