# VaultSignalsAI Flask Project

## Project structure
- `app.py`: main Flask backend (routes, auth, billing, market APIs)
- `data/pricing_catalog.json`: pricing tiers, discount tags, promo plans
- `data/daily_signal_blueprints.json`: daily signal seed templates
- `sql/auth_schema.sql`: auth/account SQL reference schema
- `templates/`: HTML templates
- `static/style.css`: shared styling
- `static/script.js`: shared frontend logic
- `static/admin_signals.js`: admin signal panel logic
- `vaultsignals.db`: SQLite database (auto-created)

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

You can now run `python app.py` from either:
- the app folder: `vaultsignalsai_flask/vaultsignalsai_flask`
- the workspace root: `vaultsignalsai_flask`

The root-level `app.py` is a launcher that auto-loads the nested Flask app and keeps template/static resolution correct.

Open: `http://127.0.0.1:5000`

## Environment configuration
```text
APP_BASE_URL=http://127.0.0.1:5000
APP_SECRET_KEY=<long-random-session-secret>
APP_DATA_ENCRYPTION_KEY=<fernet-key>
TOKEN_PEPPER=<long-random-secret>

ADMIN_USERNAMES=admin

APP_DEFAULT_CURRENCY_CODE=GBP
APP_REMEMBER_COOKIE_NAME=vaultsignals_remember
APP_CURRENCY_COOKIE_NAME=vaultsignals_currency
APP_REMEMBER_ME_DAYS=30
APP_EXCHANGE_RATE_CACHE_TTL_SECONDS=1800
APP_EXCHANGE_RATE_BASE_URL=https://api.frankfurter.app
APP_VAT_RATE=0.21

EMAIL_FROM=no-reply@vaultsignalsai.com
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=false

FEEDBACK_EMAIL=VaultSignals@AI.com
FEEDBACK_EMAIL_FROM=no-reply@vaultsignalsai.com
FEEDBACK_CONTACT_EMAIL=VaultSignals@AI.com
FEEDBACK_PHONE_NUMBER=+31625317922
FEEDBACK_PHONE_DISPLAY=0625317922

REQUEST_TIMEOUT_SECONDS=5
REQUEST_RETRIES=2
AUTH_RATE_LIMIT_ATTEMPTS=10
AUTH_RATE_LIMIT_WINDOW_SECONDS=300
ALLOWED_CORS_ORIGINS=

PAYMENT_URL_CREDITCARD=https://www.visa.com/pay-with-visa/featured-technologies/click-to-pay.html
PAYMENT_URL_IDEAL=https://www.ideal.nl/en/consumers/
PAYMENT_URL_PAYPAL=https://www.paypal.com/signin

COINGECKO_BASE_URL=https://api.coingecko.com/api/v3
COINGECKO_API_KEY=
COINGECKO_API_KEY_HEADER=x-cg-demo-api-key
STREAM_CRYPTO_IDS=bitcoin,ethereum,cardano,solana,ripple
API_CRYPTO_IDS=bitcoin,ethereum
CANVAS_CRYPTO_IDS=bitcoin,ethereum,solana,ripple,cardano,binancecoin
MARKET_CACHE_TTL_SECONDS=30

FLASK_RUN_HOST=127.0.0.1
FLASK_RUN_PORT=5000
FLASK_DEBUG=false
```

Optional one-line JSON env:
```text
STATIC_STOCK_FEED=[{"symbol":"NASDAQ","name":"NASDAQ","price":19234.56,"change":2.41}]
```

## Current features
- Member auth with immediate login access and remember-me sessions
- Member-only Your Signals page with purchased tier filtering
- Admin Signals panel (`/admin/signals`) with create, edit, publish/unpublish, and delete controls
- Currency auto-suggestion + manual override with account/device persistence
- Real-time market feed and on-site signal alerts
- Data-driven pricing and signal seed catalogs (no large hardcoded blocks)

## Notes
- Passwords use Werkzeug hashing.
- Verification tokens and remember-me tokens are stored hashed.
- Sensitive account and billing fields are encrypted when `APP_DATA_ENCRYPTION_KEY` is set.
- Login/account endpoints include rate limiting.
- Security headers are added on responses.
