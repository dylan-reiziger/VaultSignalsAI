# VaultSignalsAI business review guide

## Purpose

VaultSignalsAI is an educational desktop application for viewing public crypto-market data, chart candles, relative volume, scenario ranges, and optional public sentiment input. It is not an automated trading tool, personal investment advice service, or profit-guarantee product.

## What a reviewer can do

1. Download the Windows package from a GitHub Release or workflow artifact.
2. Extract the ZIP archive.
3. Run `VaultSignalsAI.exe` from the extracted `VaultSignalsAI` folder.
4. Confirm the original gold VaultSignalsAI logo appears during startup and on the app window.
5. Review the **Scenario report**, **Learn & risk**, and **Release checklist** pages in the navigation menu.
6. Read `LEGAL-NOTICE.txt` before testing or distributing the package.

## Review focus

- **Educational positioning:** screens describe observable data and uncertainty; they do not promise returns or instruct users to buy, sell, or hold cryptoassets.
- **Market data:** check symbols, timestamps, public exchange data, refresh behaviour, and outage messages.
- **Scenario display:** the midpoint and bands are an illustrative historical-volatility range, not a predicted target.
- **Social sentiment:** the connector is optional, requires HTTPS, and should use a licensed provider with documented terms and limitations.
- **Branding:** logo, application name, public notice, support materials, and release archive are consistent.
- **Release controls:** use the in-app checklist and [TODO.md](TODO.md) to record operational progress. The checklist does not establish regulatory approval.

## GitHub review process

- Review source changes through GitHub commits and pull requests.
- Use **Actions** → **Build Windows download** → **Run workflow** to generate a private review artifact before publication.
- Create and push a version tag such as `v0.1.0` only after internal review. The workflow publishes the ZIP to the matching GitHub Release.
- Keep the repository private while business, legal, compliance, branding, and source-licensing reviews are incomplete.

## Required decisions before public release

The business must supply and approve its support contact, privacy notice, terms, data-source records, release version, and public marketing copy. Obtain qualified, current legal and compliance advice for every country where the product or promotions may be offered. Do not claim FCA approval, authorisation, endorsement, or financial return unless independently verified and accurate.
