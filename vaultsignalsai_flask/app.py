from __future__ import annotations

import logging
import sqlite3
import json
import time
import uuid
import re
import smtplib
import os
import base64
import hashlib
import secrets
from email.message import EmailMessage
import requests
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from datetime import UTC, datetime, timedelta
from cryptography.fernet import Fernet, InvalidToken

from flask import Flask, Response, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "vaultsignals.db"

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

VERIFICATION_TOKEN_MAX_AGE_HOURS = 24
AUTH_RATE_LIMIT_ATTEMPTS = int(os.getenv("AUTH_RATE_LIMIT_ATTEMPTS", "10"))
AUTH_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "300"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "5"))
REQUEST_RETRIES = int(os.getenv("REQUEST_RETRIES", "2"))
ENCRYPTION_KEY = os.getenv("APP_DATA_ENCRYPTION_KEY", "")
TOKEN_PEPPER = os.getenv("TOKEN_PEPPER", "change-this-token-pepper")
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", TOKEN_PEPPER)
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
APP_ENV = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "development")).strip().lower()
IS_DEV_ENV = APP_ENV in {"dev", "development", "local"} or os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes"}
BADGE_PREVIEW_ENABLED = os.getenv("BADGE_PREVIEW_ENABLED", "true" if IS_DEV_ENV else "false").lower() in {"1", "true", "yes"}

PAYPAL_API_BASE_URL = os.getenv("PAYPAL_API_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "").strip()
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID", "").strip()
PAYPAL_ALLOW_UNVERIFIED_WEBHOOKS = os.getenv("PAYPAL_ALLOW_UNVERIFIED_WEBHOOKS", "true" if IS_DEV_ENV else "false").lower() in {"1", "true", "yes"}

app.config.update(
    SECRET_KEY=APP_SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
    SEND_FILE_MAX_AGE_DEFAULT=0,
    TEMPLATES_AUTO_RELOAD=True,
)

COMMUNITY_DEFAULT_BALANCE = float(os.getenv("COMMUNITY_DEFAULT_BALANCE", "10000"))
COMMUNITY_MAX_CHAT_LENGTH = int(os.getenv("COMMUNITY_MAX_CHAT_LENGTH", "600"))
COMMUNITY_MAX_POST_LENGTH = int(os.getenv("COMMUNITY_MAX_POST_LENGTH", "1200"))
COMMUNITY_DEFAULT_AVATAR = os.getenv("COMMUNITY_DEFAULT_AVATAR", "/static/vaultsignals-logo.png")
COMMUNITY_CHAT_POLL_MS = int(os.getenv("COMMUNITY_CHAT_POLL_MS", "8000"))
BITVAVO_URL = os.getenv("BITVAVO_URL", "https://bitvavo.com/en").strip()


def validate_security_configuration() -> None:
    if IS_DEV_ENV:
        return

    if TOKEN_PEPPER == "change-this-token-pepper":
        raise RuntimeError("TOKEN_PEPPER must be set in non-development environments.")
    if not APP_SECRET_KEY or APP_SECRET_KEY == TOKEN_PEPPER:
        raise RuntimeError("APP_SECRET_KEY must be explicitly set and differ from TOKEN_PEPPER in non-development environments.")


def _csv_env(env_name: str, default_csv: str) -> list[str]:
    return [item.strip() for item in os.getenv(env_name, default_csv).split(",") if item.strip()]


def _json_env(env_name: str, default_value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return default_value
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    return default_value


def _float_env(env_name: str, default_value: float) -> float:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return default_value
    try:
        return float(raw)
    except ValueError:
        return default_value


def _load_json_file(path: Path, fallback: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def normalize_signal_time_utc(raw_value: str | None, session_label: str | None = None, tier_number: int | None = None) -> str:
    candidate = str(raw_value or "").strip()
    if candidate and re.match(r"^\d{2}:\d{2}$", candidate):
        try:
            hour, minute = [int(part) for part in candidate.split(":", 1)]
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
        except ValueError:
            pass

    session_key = str(session_label or "").strip()
    if session_key in DEFAULT_SIGNAL_TIME_BY_SESSION:
        return DEFAULT_SIGNAL_TIME_BY_SESSION[session_key]

    if tier_number in DEFAULT_SIGNAL_TIME_BY_TIER:
        return DEFAULT_SIGNAL_TIME_BY_TIER[int(tier_number)]

    return DEFAULT_SIGNAL_TIME_BY_SESSION["Session"]


def normalize_signal_timer_minutes(raw_value: Any) -> int:
    try:
        candidate = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_SIGNAL_TIMER_MINUTES
    return min(720, max(15, candidate))


def build_signal_window_utc(signal_day: str | None, signal_time_utc: str | None, timer_minutes: int | None) -> tuple[str | None, str | None]:
    resolved_day = str(signal_day or "").strip()
    resolved_time = normalize_signal_time_utc(signal_time_utc)
    resolved_minutes = normalize_signal_timer_minutes(timer_minutes)
    if not resolved_day or not re.match(r"^\d{4}-\d{2}-\d{2}$", resolved_day):
        return None, None

    try:
        starts_at = datetime.strptime(f"{resolved_day} {resolved_time}", "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
    except ValueError:
        return None, None

    ends_at = starts_at + timedelta(minutes=resolved_minutes)
    return starts_at.isoformat().replace("+00:00", "Z"), ends_at.isoformat().replace("+00:00", "Z")


COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "").strip()
COINGECKO_API_KEY_HEADER = os.getenv("COINGECKO_API_KEY_HEADER", "x-cg-demo-api-key").strip() or "x-cg-demo-api-key"
BITVAVO_BASE_URL = os.getenv("BITVAVO_BASE_URL", "https://api.bitvavo.com/v2").rstrip("/")
STREAM_CRYPTO_IDS = _csv_env("STREAM_CRYPTO_IDS", "bitcoin,ethereum,cardano,solana,ripple")
API_CRYPTO_IDS = _csv_env("API_CRYPTO_IDS", "bitcoin,ethereum")
CANVAS_CRYPTO_IDS = _csv_env("CANVAS_CRYPTO_IDS", "bitcoin,ethereum,solana,ripple,cardano,binancecoin")
LIVE_DESK_CRYPTO_IDS = _csv_env(
    "LIVE_DESK_CRYPTO_IDS",
    "bitcoin,ethereum,binancecoin,solana,ripple,dogecoin,cardano,sui,chainlink,avalanche-2",
)
LIVE_DESK_DEFAULT_COIN = os.getenv("LIVE_DESK_DEFAULT_COIN", "bitcoin").strip().lower() or "bitcoin"
LIVE_DESK_CHART_POINT_LIMIT = int(os.getenv("LIVE_DESK_CHART_POINT_LIMIT", "40"))
BITVAVO_ASSET_CATALOG: dict[str, dict[str, Any]] = {
    "bitcoin": {"market": "BTC-EUR", "symbol": "BTC", "name": "Bitcoin", "rank": 1, "circulating_supply": 19_850_000},
    "ethereum": {"market": "ETH-EUR", "symbol": "ETH", "name": "Ethereum", "rank": 2, "circulating_supply": 120_700_000},
    "ripple": {"market": "XRP-EUR", "symbol": "XRP", "name": "XRP", "rank": 4, "circulating_supply": 58_500_000_000},
    "binancecoin": {"market": "BNB-EUR", "symbol": "BNB", "name": "BNB", "rank": 5, "circulating_supply": 145_887_575},
    "solana": {"market": "SOL-EUR", "symbol": "SOL", "name": "Solana", "rank": 6, "circulating_supply": 516_000_000},
    "dogecoin": {"market": "DOGE-EUR", "symbol": "DOGE", "name": "Dogecoin", "rank": 8, "circulating_supply": 148_600_000_000},
    "cardano": {"market": "ADA-EUR", "symbol": "ADA", "name": "Cardano", "rank": 9, "circulating_supply": 35_300_000_000},
    "sui": {"market": "SUI-EUR", "symbol": "SUI", "name": "Sui", "rank": 13, "circulating_supply": 3_190_000_000},
    "chainlink": {"market": "LINK-EUR", "symbol": "LINK", "name": "Chainlink", "rank": 14, "circulating_supply": 657_100_000},
    "avalanche-2": {"market": "AVAX-EUR", "symbol": "AVAX", "name": "Avalanche", "rank": 15, "circulating_supply": 416_000_000},
}
MARKET_CACHE_TTL_SECONDS = int(os.getenv("MARKET_CACHE_TTL_SECONDS", "30"))
DEFAULT_CURRENCY_CODE = os.getenv("APP_DEFAULT_CURRENCY_CODE", "GBP").strip().upper() or "GBP"
CHECKOUT_VAT_RATE = _float_env("APP_VAT_RATE", 0.21)
EMAIL_FROM = os.getenv("EMAIL_FROM", "no-reply@vaultsignalsai.com").strip() or "no-reply@vaultsignalsai.com"
SMTP_HOST = os.getenv("SMTP_HOST", os.getenv("SMTP_SERVER", "localhost")).strip() or "localhost"
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", os.getenv("SMTP_USER", "")).strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "false").lower() in {"1", "true", "yes"}
RENEWAL_REMINDER_LEAD_DAYS = int(os.getenv("RENEWAL_REMINDER_LEAD_DAYS", "7"))
FEEDBACK_PHONE_NUMBER = os.getenv("FEEDBACK_PHONE_NUMBER", "+31625317922")
FEEDBACK_PHONE_DISPLAY = os.getenv("FEEDBACK_PHONE_DISPLAY", "0625317922")
FEEDBACK_CONTACT_EMAIL = os.getenv("FEEDBACK_CONTACT_EMAIL", "VaultSignals@AI.com")
FEEDBACK_EMAIL = os.getenv("FEEDBACK_EMAIL", FEEDBACK_CONTACT_EMAIL)
FEEDBACK_EMAIL_FROM = os.getenv("FEEDBACK_EMAIL_FROM", EMAIL_FROM)
REMEMBER_COOKIE_NAME = os.getenv("APP_REMEMBER_COOKIE_NAME", "vaultsignals_remember")
PREFERRED_CURRENCY_COOKIE_NAME = os.getenv("APP_CURRENCY_COOKIE_NAME", "vaultsignals_currency")
REMEMBER_ME_DAYS = int(os.getenv("APP_REMEMBER_ME_DAYS", "30"))
EXCHANGE_RATE_CACHE_TTL_SECONDS = int(os.getenv("APP_EXCHANGE_RATE_CACHE_TTL_SECONDS", "1800"))
EXCHANGE_RATE_BASE_URL = os.getenv("APP_EXCHANGE_RATE_BASE_URL", "https://api.frankfurter.app")
PAYMENT_LINKS = {
    "creditcard": os.getenv("PAYMENT_URL_CREDITCARD", "https://www.visa.com/pay-with-visa/featured-technologies/click-to-pay.html"),
    "ideal": os.getenv("PAYMENT_URL_IDEAL", "https://www.ideal.nl/en/consumers/"),
    "paypal": os.getenv("PAYMENT_URL_PAYPAL", "https://www.paypal.com/signin"),
}
DEFAULT_STOCK_FEED = [
    {"symbol": "NASDAQ", "name": "NASDAQ", "price": 19234.56, "change": 2.41},
    {"symbol": "S&P 500", "name": "S&P 500", "price": 5981.44, "change": 1.18},
    {"symbol": "NVDA", "name": "NVIDIA", "price": 924.15, "change": 4.76},
    {"symbol": "TSLA", "name": "Tesla", "price": 171.20, "change": -1.12},
    {"symbol": "AAPL", "name": "Apple", "price": 235.32, "change": 0.84},
    {"symbol": "MSFT", "name": "Microsoft", "price": 429.80, "change": 1.64},
    {"symbol": "AMZN", "name": "Amazon", "price": 156.92, "change": -0.92},
]
STATIC_STOCK_FEED = _json_env("STATIC_STOCK_FEED", DEFAULT_STOCK_FEED)
STOCK_SIGNAL_SYMBOLS = [
    symbol.upper()
    for symbol in _csv_env("STOCK_SIGNAL_SYMBOLS", "AAPL,MSFT,NVDA,TSLA,AMZN,META,SPY,QQQ")
    if re.match(r"^[A-Z0-9.\-^=]{1,12}$", symbol.upper())
]
if not STOCK_SIGNAL_SYMBOLS:
    STOCK_SIGNAL_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "SPY", "QQQ"]
STOCK_SIGNAL_DEFAULT_LIMIT = int(os.getenv("STOCK_SIGNAL_DEFAULT_LIMIT", "6"))
STOCK_SIGNAL_MIN_CONFIDENCE = int(os.getenv("STOCK_SIGNAL_MIN_CONFIDENCE", "60"))
STOCK_SIGNAL_CACHE_TTL_SECONDS = int(os.getenv("STOCK_SIGNAL_CACHE_TTL_SECONDS", "12"))
YAHOO_FINANCE_CHART_BASE_URL = os.getenv("YAHOO_FINANCE_CHART_BASE_URL", "https://query1.finance.yahoo.com/v8/finance/chart").rstrip("/")
YAHOO_FINANCE_USER_AGENT = os.getenv("YAHOO_FINANCE_USER_AGENT", "Mozilla/5.0")
ALLOWED_CORS_ORIGINS = set(_csv_env("ALLOWED_CORS_ORIGINS", ""))
ADMIN_USERNAMES = {username.lower() for username in _csv_env("ADMIN_USERNAMES", "admin")}
AUTO_ADMIN_EMAILS = {email.strip().lower() for email in _csv_env("AUTO_ADMIN_EMAILS", "dylan.reiziger@hotmail.com") if email.strip()}
_AUTH_REQUEST_LOG: dict[str, list[float]] = {}
_MARKET_CACHE: dict[str, Any] = {"payload": None, "updated_at": 0.0}
_LIVE_DESK_CACHE: dict[str, dict[str, Any]] = {}
_STOCK_SIGNAL_CACHE: dict[str, dict[str, Any]] = {}
_FX_CACHE: dict[str, Any] = {"payload": None, "updated_at": 0.0}
MAX_LENGTHS = {
    "username": 50,
    "full_name": 120,
    "email": 254,
    "phone_number": 30,
    "zipcode": 20,
    "address": 200,
    "discord_username": 50,
    "discord_tag": 30,
    "billing_name": 120,
    "billing_company": 120,
    "billing_address": 200,
    "billing_zip": 20,
    "billing_country": 80,
}
PRICING_CATALOG = _load_json_file(BASE_DIR / "data" / "pricing_catalog.json", {})
TIERS = PRICING_CATALOG.get("tiers", [])
DISCORD_TAG_LEVELS = PRICING_CATALOG.get("discordTagLevels", ["final"])
BILLING_CYCLES = PRICING_CATALOG.get("billingCycles", ["monthly"])
DISCORD_TAG_LABELS = PRICING_CATALOG.get("discordTagLabels", {"final": "Final"})
PRICING_MATRIX_GBP = {int(tier): plans for tier, plans in (PRICING_CATALOG.get("pricingMatrixGbp", {}) or {}).items()}
TIER_NUMBER_MIN = min(PRICING_MATRIX_GBP) if PRICING_MATRIX_GBP else 1
TIER_NUMBER_MAX = max(PRICING_MATRIX_GBP) if PRICING_MATRIX_GBP else max(len(TIERS), 1)
DEFAULT_BILLING_CYCLE = "monthly" if "monthly" in BILLING_CYCLES else (BILLING_CYCLES[0] if BILLING_CYCLES else "monthly")
VALID_BILLING_CYCLES = set(BILLING_CYCLES or ["weekly", "monthly", "quarterly", "annual", "lifetime"]) or {"weekly", "monthly", "quarterly", "annual", "lifetime"}
VALID_BILLING_CYCLES.add("lifetime")
BILLING_CYCLE_DAYS = {
    "weekly": int(os.getenv("BILLING_CYCLE_DAYS_WEEKLY", "7")),
    "monthly": int(os.getenv("BILLING_CYCLE_DAYS_MONTHLY", "30")),
    "quarterly": int(os.getenv("BILLING_CYCLE_DAYS_QUARTERLY", "90")),
    "annual": int(os.getenv("BILLING_CYCLE_DAYS_ANNUAL", "365")),
}
COMMUNITY_RANK_NAMES = _csv_env("COMMUNITY_RANK_NAMES", "Starter,Trader,Pro,Expert,Elite,Vault Elite")
COMMUNITY_RANK_BY_TIER = {
    0: "",
    **{index: label for index, label in enumerate(COMMUNITY_RANK_NAMES[:TIER_NUMBER_MAX], start=1)},
}
LOYALTY_MEMBER_BADGE_MONTHS = int(os.getenv("LOYALTY_MEMBER_BADGE_MONTHS", "1"))
LOYALTY_TRUSTED_BADGE_MONTHS = int(os.getenv("LOYALTY_TRUSTED_BADGE_MONTHS", "6"))
LOYALTY_VETERAN_BADGE_MONTHS = int(os.getenv("LOYALTY_VETERAN_BADGE_MONTHS", "12"))
LOYALTY_SUPPORTER_SPEND_GBP = _float_env("LOYALTY_SUPPORTER_SPEND_GBP", 100.0)
LOYALTY_LEVEL_SILVER_MONTHS = int(os.getenv("LOYALTY_LEVEL_SILVER_MONTHS", "3"))
LOYALTY_LEVEL_GOLD_MONTHS = int(os.getenv("LOYALTY_LEVEL_GOLD_MONTHS", str(LOYALTY_TRUSTED_BADGE_MONTHS)))
LOYALTY_LEVEL_DIAMOND_MONTHS = int(os.getenv("LOYALTY_LEVEL_DIAMOND_MONTHS", str(LOYALTY_VETERAN_BADGE_MONTHS)))
DISPLAY_NAME_CHANGE_COOLDOWN_DAYS = int(os.getenv("DISPLAY_NAME_CHANGE_COOLDOWN_DAYS", "30"))
DISCORD_VERIFICATION_PENDING = "pending"
DISCORD_VERIFICATION_VERIFIED = "verified"
DISCORD_VERIFICATION_NOT_CONNECTED = "not_connected"

SUPPORTED_CURRENCIES = {
    "GBP": {"label": "British Pound", "symbol": "£", "locale": "en-GB", "fallback_rate": 1.0},
    "USD": {"label": "US Dollar", "symbol": "$", "locale": "en-US", "fallback_rate": 1.27},
    "EUR": {"label": "Euro", "symbol": "€", "locale": "en-IE", "fallback_rate": 1.17},
    "CAD": {"label": "Canadian Dollar", "symbol": "CA$", "locale": "en-CA", "fallback_rate": 1.72},
    "AUD": {"label": "Australian Dollar", "symbol": "A$", "locale": "en-AU", "fallback_rate": 1.94},
    "NZD": {"label": "New Zealand Dollar", "symbol": "NZ$", "locale": "en-NZ", "fallback_rate": 2.08},
    "CHF": {"label": "Swiss Franc", "symbol": "CHF", "locale": "de-CH", "fallback_rate": 1.12},
    "JPY": {"label": "Japanese Yen", "symbol": "¥", "locale": "ja-JP", "fallback_rate": 191.5},
    "INR": {"label": "Indian Rupee", "symbol": "₹", "locale": "en-IN", "fallback_rate": 105.0},
    "AED": {"label": "UAE Dirham", "symbol": "AED", "locale": "en-AE", "fallback_rate": 4.66},
}

COUNTRY_CURRENCY_MAP = {
    "GB": "GBP",
    "US": "USD",
    "CA": "CAD",
    "AU": "AUD",
    "NZ": "NZD",
    "IE": "EUR",
    "NL": "EUR",
    "BE": "EUR",
    "DE": "EUR",
    "FR": "EUR",
    "ES": "EUR",
    "IT": "EUR",
    "PT": "EUR",
    "AT": "EUR",
    "FI": "EUR",
    "JP": "JPY",
    "CH": "CHF",
    "IN": "INR",
    "AE": "AED",
}

PROMO_PLANS_GBP = PRICING_CATALOG.get("promoPlansGbp", {})
DAILY_SIGNAL_BLUEPRINTS = _load_json_file(BASE_DIR / "data" / "daily_signal_blueprints.json", [])
DEFAULT_SIGNAL_TIME_BY_SESSION = {
    "London Open": "07:15",
    "Europe Midday": "10:30",
    "US Pre-Market": "12:45",
    "US Open": "14:30",
    "US Midday": "17:00",
    "US Close": "20:00",
    "Session": "12:00",
}
DEFAULT_SIGNAL_TIME_BY_TIER = {
    1: "07:15",
    2: "10:30",
    3: "12:45",
    4: "14:30",
    5: "17:00",
    6: "20:00",
}
DEFAULT_SIGNAL_TIMER_MINUTES = 90
DEFAULT_PERFORMANCE_TIMELINE = [
    {
        "month": "January",
        "value": "+12.4% Net",
        "note": "Trend continuation month with controlled drawdowns and disciplined exits.",
        "status": "positive",
    },
    {
        "month": "February",
        "value": "+8.1% Net",
        "note": "Selective participation in lower-volatility sessions preserved quality.",
        "status": "positive",
    },
    {
        "month": "March",
        "value": "+1.7% Net",
        "note": "Defensive risk posture reduced exposure during mixed market structure.",
        "status": "flat",
    },
    {
        "month": "April",
        "value": "+9.6% Net",
        "note": "Momentum re-expansion supported cleaner target progression on majors.",
        "status": "positive",
    },
]
PERFORMANCE_TIMELINE = _load_json_file(BASE_DIR / "data" / "performance_timeline.json", DEFAULT_PERFORMANCE_TIMELINE)

DEFAULT_CURRENCY_SYMBOL = SUPPORTED_CURRENCIES.get(DEFAULT_CURRENCY_CODE, SUPPORTED_CURRENCIES["GBP"])["symbol"]


def get_performance_timeline() -> list[dict[str, str]]:
    rows = PERFORMANCE_TIMELINE if isinstance(PERFORMANCE_TIMELINE, list) else []
    prepared_rows: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        month = str(row.get("month", "")).strip()
        value = str(row.get("value", "")).strip()
        note = str(row.get("note", "")).strip()
        status = str(row.get("status", "flat")).strip().lower()
        if status not in {"positive", "flat", "negative"}:
            status = "flat"
        if not month or not value or not note:
            continue
        prepared_rows.append(
            {
                "month": month,
                "value": value,
                "note": note,
                "status_class": f"is-{status}",
            }
        )

    if prepared_rows:
        return prepared_rows

    return [
        {
            "month": "January",
            "value": "+0.0% Net",
            "note": "Add your verified monthly metrics in data/performance_timeline.json.",
            "status_class": "is-flat",
        }
    ]


def get_cipher() -> Fernet | None:
    if not ENCRYPTION_KEY:
        return None
    try:
        return Fernet(ENCRYPTION_KEY.encode("utf-8"))
    except Exception:
        return None


CIPHER = get_cipher()


def encrypt_value(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value:
        return None
    if CIPHER is None:
        return value
    return CIPHER.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value:
        return None
    if CIPHER is None:
        return value
    try:
        return CIPHER.decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(f"{TOKEN_PEPPER}:{raw_token}".encode("utf-8")).hexdigest()


def normalize_currency_code(raw_value: str | None) -> str:
    candidate = (raw_value or "").strip().upper()
    if candidate in SUPPORTED_CURRENCIES:
        return candidate
    return DEFAULT_CURRENCY_CODE if DEFAULT_CURRENCY_CODE in SUPPORTED_CURRENCIES else "GBP"


def parse_db_timestamp(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw_value, fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw_value)
        return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    return None


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def format_db_timestamp(raw_value: datetime | None) -> str | None:
    if raw_value is None:
        return None
    return raw_value.strftime("%Y-%m-%d %H:%M:%S")


def send_smtp_message(message: EmailMessage) -> bool:
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USERNAME and SMTP_PASSWORD:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
        return True
    except Exception as exc:
        logger.warning("Could not send email via SMTP (%s:%s): %s", SMTP_HOST, SMTP_PORT, exc)
        return False


def build_exchange_rate_url() -> str:
    return f"{EXCHANGE_RATE_BASE_URL.rstrip('/')}/latest"


def get_exchange_rates() -> dict[str, float]:
    cached_payload = _FX_CACHE.get("payload")
    cached_at = float(_FX_CACHE.get("updated_at", 0) or 0)
    if cached_payload and (time.time() - cached_at) < EXCHANGE_RATE_CACHE_TTL_SECONDS:
        return cached_payload

    fallback_rates = {code: float(details["fallback_rate"]) for code, details in SUPPORTED_CURRENCIES.items()}
    fallback_rates["GBP"] = 1.0
    try:
        response = requests.get(
            build_exchange_rate_url(),
            params={"from": "GBP", "to": ",".join(code for code in SUPPORTED_CURRENCIES if code != "GBP")},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            payload = response.json()
            parsed_rates = {"GBP": 1.0, **{key.upper(): float(value) for key, value in (payload.get("rates") or {}).items() if key.upper() in SUPPORTED_CURRENCIES}}
            _FX_CACHE["payload"] = parsed_rates
            _FX_CACHE["updated_at"] = time.time()
            return parsed_rates
    except requests.RequestException:
        pass

    if cached_payload:
        return cached_payload
    return fallback_rates


def convert_currency_amount(amount: float | None, from_currency: str, to_currency: str) -> float | None:
    if amount is None:
        return None
    normalized_from = normalize_currency_code(from_currency)
    normalized_to = normalize_currency_code(to_currency)
    rates = get_exchange_rates()
    from_rate = rates.get(normalized_from)
    to_rate = rates.get(normalized_to)
    if from_rate is None or to_rate is None or from_rate == 0:
        return None
    gbp_amount = float(amount) / float(from_rate)
    return round(gbp_amount * float(to_rate), 2)


def build_currency_choice_payload(code: str, source: str) -> dict[str, Any]:
    normalized_code = normalize_currency_code(code)
    details = SUPPORTED_CURRENCIES[normalized_code]
    return {
        "code": normalized_code,
        "symbol": details["symbol"],
        "label": details["label"],
        "locale": details["locale"],
        "source": source,
        "privacyNote": "Regional currency suggestions use coarse country hints or browser locale. Raw IP addresses are not stored for this feature.",
    }


def build_currency_catalog() -> list[dict[str, Any]]:
    return [
        {
            "code": code,
            "symbol": details["symbol"],
            "label": details["label"],
            "locale": details["locale"],
        }
        for code, details in SUPPORTED_CURRENCIES.items()
    ]


def currency_code_from_country(country_code: str | None) -> str | None:
    if not country_code:
        return None
    return COUNTRY_CURRENCY_MAP.get(country_code.strip().upper())


def extract_country_from_request() -> str | None:
    header_candidates = [
        request.headers.get("CF-IPCountry"),
        request.headers.get("X-Vercel-IP-Country"),
        request.headers.get("X-Appengine-Country"),
        request.headers.get("CloudFront-Viewer-Country"),
    ]
    for candidate in header_candidates:
        if candidate and candidate.strip() and candidate.strip().upper() != "XX":
            return candidate.strip().upper()

    accept_language = request.headers.get("Accept-Language", "")
    for chunk in accept_language.split(","):
        language_part = chunk.split(";")[0].strip()
        if "-" in language_part:
            region = language_part.split("-")[-1].upper()
            if len(region) == 2:
                return region
    return None


def resolve_currency_preference(account_row: sqlite3.Row | None) -> dict[str, Any]:
    account_currency = normalize_currency_code(account_row["preferred_currency_code"]) if account_row and account_row["preferred_currency_code"] else None
    if account_currency:
        return build_currency_choice_payload(account_currency, "account")

    cookie_currency = normalize_currency_code(request.cookies.get(PREFERRED_CURRENCY_COOKIE_NAME)) if request.cookies.get(PREFERRED_CURRENCY_COOKIE_NAME) else None
    if cookie_currency:
        return build_currency_choice_payload(cookie_currency, "device")

    hinted_currency = currency_code_from_country(extract_country_from_request())
    if hinted_currency:
        return build_currency_choice_payload(hinted_currency, "region")

    return build_currency_choice_payload(DEFAULT_CURRENCY_CODE, "default")


def serialize_account(user: sqlite3.Row | None) -> dict[str, Any] | None:
    if user is None:
        return None
    resolved_full_name = decrypt_value(user["full_name_enc"]) or user["full_name"]
    resolved_discord_username = decrypt_value(user["discord_username_enc"]) or user["discord_username"]
    verification_status = user["discord_verification_status"] if "discord_verification_status" in user.keys() else DISCORD_VERIFICATION_NOT_CONNECTED
    verified_tag = user["discord_verified_tag"] if "discord_verified_tag" in user.keys() else user["discord_tag"]
    return {
        "id": user["id"],
        "username": user["username"],
        "isAdmin": is_admin_account(user),
        "isVerified": bool(user["verified"]),
        "fullName": resolved_full_name,
        "email": user["email"],
        "discordUsername": resolved_discord_username,
        "discordTag": verified_tag,
        "discordVerificationStatus": verification_status,
        "discordCheckedAt": user["discord_checked_at"] if "discord_checked_at" in user.keys() else None,
        "preferredCurrencyCode": normalize_currency_code(user["preferred_currency_code"]) if user["preferred_currency_code"] else None,
    }


def normalize_phone_number(raw_value: str) -> str:
    normalized = re.sub(r"\s+", " ", str(raw_value or "").strip())
    normalized = re.sub(r"[^0-9+()\-\s]", "", normalized)
    return normalized[:MAX_LENGTHS["phone_number"]]


def is_admin_username(username: str | None) -> bool:
    candidate = (username or "").strip().lower()
    if not candidate:
        return False
    return candidate in ADMIN_USERNAMES


def is_auto_admin_email(email: str | None) -> bool:
    candidate = (email or "").strip().lower()
    if not candidate:
        return False
    return candidate in AUTO_ADMIN_EMAILS


def is_admin_account(account: sqlite3.Row | None) -> bool:
    if account is None:
        return False
    if "is_admin" in account.keys():
        return bool(account["is_admin"])
    return is_admin_username(account["username"] if "username" in account.keys() else None)


def require_admin_api() -> tuple[sqlite3.Row | None, tuple[Any, int] | None]:
    if g.current_account is None:
        return None, (jsonify({"ok": False, "message": "Login required."}), 401)
    if not is_admin_account(g.current_account):
        return None, (jsonify({"ok": False, "message": "Admin access required."}), 403)
    return g.current_account, None


def fetch_account_by_id(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
            a.id,
            a.username,
            a.full_name,
            a.full_name_enc,
            a.email,
            a.discord_username,
            a.discord_username_enc,
            a.discord_tag,
            a.is_admin,
            a.verified,
            a.preferred_currency_code,
            dv.verification_status AS discord_verification_status,
            dv.verified_tag AS discord_verified_tag,
            dv.checked_at AS discord_checked_at
        FROM accounts a
        LEFT JOIN account_discord_verifications dv ON dv.account_id = a.id
        WHERE a.id = ?
        """,
        (account_id,),
    ).fetchone()


def fetch_account_profile_by_id(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
            a.id,
            a.username,
            a.full_name,
            a.full_name_enc,
            a.email,
            a.phone_number,
            a.phone_number_enc,
            a.zipcode,
            a.zipcode_enc,
            a.address,
            a.address_enc,
            a.discord_tag,
            a.is_admin,
            a.preferred_currency_code,
            a.verified,
            cp.display_name,
            cp.avatar_url,
            dv.verification_status AS discord_verification_status,
            dv.verified_tag AS discord_verified_tag
        FROM accounts a
        LEFT JOIN community_profiles cp ON cp.account_id = a.id
        LEFT JOIN account_discord_verifications dv ON dv.account_id = a.id
        WHERE a.id = ?
        """,
        (account_id,),
    ).fetchone()


def serialize_account_profile(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    full_name = decrypt_value(row["full_name_enc"]) or row["full_name"] or ""
    phone_number = decrypt_value(row["phone_number_enc"]) or row["phone_number"] or ""
    zipcode = decrypt_value(row["zipcode_enc"]) or row["zipcode"] or ""
    address = decrypt_value(row["address_enc"]) or row["address"] or ""
    address_summary = ", ".join(part for part in [address, zipcode] if part)

    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row["display_name"] or row["username"],
        "fullName": full_name,
        "email": row["email"],
        "phoneNumber": phone_number,
        "zipcode": zipcode,
        "address": address,
        "addressSummary": address_summary,
        "avatarUrl": row["avatar_url"] or COMMUNITY_DEFAULT_AVATAR,
        "isVerified": bool(row["verified"]),
        "isAdmin": is_admin_account(row),
        "preferredCurrencyCode": normalize_currency_code(row["preferred_currency_code"]) if row["preferred_currency_code"] else "GBP",
        "discordVerificationStatus": row["discord_verification_status"] or DISCORD_VERIFICATION_NOT_CONNECTED,
        "discordTag": row["discord_verified_tag"] or row["discord_tag"] or "",
    }


def normalize_discord_username(raw_value: str) -> str:
    normalized = raw_value.strip().lstrip("@").lower()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[^a-z0-9._-]", "", normalized)
    return normalized[:MAX_LENGTHS["discord_username"]]


def sync_discord_verification_for_account(conn: sqlite3.Connection, account_id: int, raw_discord_username: str | None) -> tuple[str, str | None]:
    normalized_username = normalize_discord_username(raw_discord_username or "")
    if not normalized_username:
        conn.execute("UPDATE accounts SET discord_tag = NULL WHERE id = ?", (account_id,))
        conn.execute(
            """
            INSERT INTO account_discord_verifications (account_id, discord_username, verification_status, verified_tag, checked_at, source)
            VALUES (?, ?, ?, NULL, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(account_id) DO UPDATE SET
              discord_username = excluded.discord_username,
              verification_status = excluded.verification_status,
              verified_tag = NULL,
              checked_at = CURRENT_TIMESTAMP,
              source = excluded.source
            """,
            (account_id, None, DISCORD_VERIFICATION_NOT_CONNECTED, "system_registry"),
        )
        return DISCORD_VERIFICATION_NOT_CONNECTED, None

    registry_row = conn.execute(
        "SELECT discord_tag FROM discord_member_registry WHERE lower(discord_username) = ? AND is_active = 1 LIMIT 1",
        (normalized_username,),
    ).fetchone()

    if registry_row and normalize_discord_tag(registry_row["discord_tag"] or "") in DISCORD_TAG_LEVELS:
        verified_tag = normalize_discord_tag(registry_row["discord_tag"])
        verification_status = DISCORD_VERIFICATION_VERIFIED
    else:
        verified_tag = None
        verification_status = DISCORD_VERIFICATION_PENDING

    conn.execute(
        "UPDATE accounts SET discord_username = ?, discord_username_enc = ?, discord_tag = ? WHERE id = ?",
        (normalized_username, encrypt_value(normalized_username), verified_tag, account_id),
    )
    conn.execute(
        """
        INSERT INTO account_discord_verifications (account_id, discord_username, verification_status, verified_tag, checked_at, source)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(account_id) DO UPDATE SET
          discord_username = excluded.discord_username,
          verification_status = excluded.verification_status,
          verified_tag = excluded.verified_tag,
          checked_at = CURRENT_TIMESTAMP,
          source = excluded.source
        """,
        (account_id, normalized_username, verification_status, verified_tag, "system_registry"),
    )
    return verification_status, verified_tag


def set_currency_cookie(response: Response, currency_code: str) -> None:
    response.set_cookie(
        PREFERRED_CURRENCY_COOKIE_NAME,
        normalize_currency_code(currency_code),
        max_age=60 * 60 * 24 * 365,
        httponly=False,
        samesite="Lax",
        secure=request.is_secure,
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(REMEMBER_COOKIE_NAME, samesite="Lax")


def create_remember_token(conn: sqlite3.Connection, account_id: int) -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    expires_at = (utc_now() + timedelta(days=REMEMBER_ME_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO auth_tokens (account_id, token_hash, user_agent, expires_at, last_used_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (account_id, token_hash, (request.headers.get("User-Agent", "") or "")[:255], expires_at),
    )
    return raw_token, expires_at


def attach_auth_state(response: Response, account_id: int, remember_me: bool) -> Response:
    session["account_id"] = account_id
    session.permanent = remember_me
    if not remember_me:
        clear_auth_cookie(response)
        return response

    with get_db() as conn:
        raw_token, expires_at = create_remember_token(conn, account_id)
    max_age = int((parse_db_timestamp(expires_at) - utc_now()).total_seconds()) if parse_db_timestamp(expires_at) else REMEMBER_ME_DAYS * 24 * 60 * 60
    response.set_cookie(
        REMEMBER_COOKIE_NAME,
        raw_token,
        max_age=max_age,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure,
    )
    return response


def clear_auth_state(response: Response) -> Response:
    session.clear()
    clear_auth_cookie(response)
    return response


def load_account_from_remember_cookie(conn: sqlite3.Connection, raw_token: str) -> sqlite3.Row | None:
    token_hash = hash_token(raw_token)
    auth_row = conn.execute(
        "SELECT account_id FROM auth_tokens WHERE token_hash = ? AND expires_at > CURRENT_TIMESTAMP",
        (token_hash,),
    ).fetchone()
    if auth_row is None:
        conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))
        return None
    conn.execute("UPDATE auth_tokens SET last_used_at = CURRENT_TIMESTAMP WHERE token_hash = ?", (token_hash,))
    return fetch_account_by_id(conn, int(auth_row["account_id"]))


def ensure_daily_signals(conn: sqlite3.Connection, signal_day: str | None = None) -> str:
    resolved_day = signal_day or utc_now().strftime("%Y-%m-%d")
    existing = conn.execute("SELECT COUNT(*) AS count FROM daily_signals WHERE signal_day = ?", (resolved_day,)).fetchone()
    if existing and int(existing["count"] or 0) > 0:
        return resolved_day

    for signal in DAILY_SIGNAL_BLUEPRINTS:
        # Mark tier 1 signals as free for all logged-in users
        is_free = 1 if signal.get("tier_number") == 1 else 0
        signal_time_utc = normalize_signal_time_utc(signal.get("signal_time_utc"), signal.get("session_label"), int(signal.get("tier_number", 0) or 0))
        timer_minutes = normalize_signal_timer_minutes(signal.get("timer_minutes"))
        conn.execute(
            "INSERT INTO daily_signals (signal_day, tier_number, asset_symbol, market, direction, entry_price, target_price, stop_price, confidence_label, session_label, thesis, signal_time_utc, timer_minutes, base_currency_code, status, is_free) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                resolved_day,
                signal["tier_number"],
                signal["asset_symbol"],
                signal["market"],
                signal["direction"],
                signal["entry_price"],
                signal["target_price"],
                signal["stop_price"],
                signal["confidence_label"],
                signal["session_label"],
                signal["thesis"],
                signal_time_utc,
                timer_minutes,
                "USD",
                "published",
                is_free,
            ),
        )
    return resolved_day


def serialize_signal_row(signal_row: sqlite3.Row, selected_currency_code: str) -> dict[str, Any]:
    base_currency = normalize_currency_code(signal_row["base_currency_code"] or "USD")
    signal_time_utc = normalize_signal_time_utc(
        signal_row["signal_time_utc"] if "signal_time_utc" in signal_row.keys() else None,
        signal_row["session_label"],
        int(signal_row["tier_number"] or 0),
    )
    timer_minutes = normalize_signal_timer_minutes(signal_row["timer_minutes"] if "timer_minutes" in signal_row.keys() else DEFAULT_SIGNAL_TIMER_MINUTES)
    starts_at_utc, ends_at_utc = build_signal_window_utc(signal_row["signal_day"], signal_time_utc, timer_minutes)
    return {
        "id": signal_row["id"],
        "tierNumber": signal_row["tier_number"],
        "assetSymbol": signal_row["asset_symbol"],
        "market": signal_row["market"],
        "direction": signal_row["direction"],
        "entryPrice": convert_currency_amount(signal_row["entry_price"], base_currency, selected_currency_code),
        "targetPrice": convert_currency_amount(signal_row["target_price"], base_currency, selected_currency_code),
        "stopPrice": convert_currency_amount(signal_row["stop_price"], base_currency, selected_currency_code),
        "baseCurrencyCode": base_currency,
        "displayCurrencyCode": selected_currency_code,
        "confidenceLabel": signal_row["confidence_label"],
        "sessionLabel": signal_row["session_label"],
        "thesis": signal_row["thesis"],
        "status": signal_row["status"],
        "signalDay": signal_row["signal_day"],
        "signalTimeUtc": signal_time_utc,
        "timerMinutes": timer_minutes,
        "signalStartsAtUtc": starts_at_utc,
        "signalEndsAtUtc": ends_at_utc,
    }


def ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def build_legacy_username(email: str | None, account_id: int, existing_usernames: set[str]) -> str:
    email_local = (email or "").split("@", 1)[0].strip().lower()
    base_username = re.sub(r"[^a-z0-9_]", "", email_local.replace(".", "_"))[:40] or f"user{account_id}"
    candidate = base_username
    suffix = 1
    while candidate in existing_usernames:
        candidate = f"{base_username[:36]}_{suffix}"
        suffix += 1
    existing_usernames.add(candidate)
    return candidate


def build_pricing_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tier_id, plans in PRICING_MATRIX_GBP.items():
        for tag_key in DISCORD_TAG_LEVELS:
            plan_prices = plans[tag_key]
            rows.append(
                {
                    "tier": tier_id,
                    "signals": tier_id,
                    "tag_key": tag_key,
                    "tag_label": DISCORD_TAG_LABELS[tag_key],
                    "weekly": plan_prices["weekly"],
                    "monthly": plan_prices["monthly"],
                    "quarterly": plan_prices["quarterly"],
                    "annual": plan_prices["annual"],
                    "lifetime": plan_prices["lifetime"],
                }
            )
    return rows


def get_price_for_selection(tier: int, tag_key: str, billing_cycle: str) -> float | None:
    if tier not in PRICING_MATRIX_GBP:
        return None
    if tag_key not in DISCORD_TAG_LEVELS:
        return None
    if billing_cycle not in BILLING_CYCLES:
        return None

    return PRICING_MATRIX_GBP[tier][tag_key][billing_cycle]


def get_payment_forward_url(method: str) -> str:
    method_key = (method or "").strip().lower()
    return PAYMENT_LINKS.get(method_key, PAYMENT_LINKS["creditcard"])


def ensure_community_profile(conn: sqlite3.Connection, account_id: int, username: str) -> None:
    conn.execute(
        """
        INSERT INTO community_profiles (account_id, display_name, avatar_url, privacy_mode, layout_preset, show_on_leaderboard, user_rank, ignore_whisper, updated_at)
        VALUES (?, ?, ?, 'public', 'default', 1, '', 0, CURRENT_TIMESTAMP)
        ON CONFLICT(account_id) DO NOTHING
        """,
        (account_id, username, COMMUNITY_DEFAULT_AVATAR),
    )
    conn.execute(
        """
        INSERT INTO account_balances (account_id, balance_amount, total_invested, total_profit, updated_at)
        VALUES (?, ?, 0, 0, CURRENT_TIMESTAMP)
        ON CONFLICT(account_id) DO NOTHING
        """,
        (account_id, COMMUNITY_DEFAULT_BALANCE),
    )


def get_active_tier_number(conn: sqlite3.Connection, account_id: int) -> int:
    row = conn.execute(
        "SELECT MAX(COALESCE(tier_number, 0)) AS tier_max FROM purchases WHERE account_id = ? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)",
        (account_id,),
    ).fetchone()
    return int((row["tier_max"] if row else 0) or 0)


def get_chat_suspension(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, reason, suspended_until FROM chat_suspensions WHERE account_id = ? AND suspended_until > CURRENT_TIMESTAMP ORDER BY suspended_until DESC LIMIT 1",
        (account_id,),
    ).fetchone()


def can_account_chat(conn: sqlite3.Connection, account_id: int) -> tuple[bool, str | None, int]:
    suspension = get_chat_suspension(conn, account_id)
    if suspension is not None:
        return False, f"Chat suspended until {suspension['suspended_until']}", 0

    active_tier = get_active_tier_number(conn, account_id)
    if active_tier < 1:
        return False, "A paid tier is required to use chat.", active_tier
    return True, None, active_tier


def resolve_loyalty_level(months_active: int) -> str:
    if months_active >= LOYALTY_LEVEL_DIAMOND_MONTHS:
        return "diamond"
    if months_active >= LOYALTY_LEVEL_GOLD_MONTHS:
        return "gold"
    if months_active >= LOYALTY_LEVEL_SILVER_MONTHS:
        return "silver"
    return "bronze"


def get_loyalty_snapshot(conn: sqlite3.Connection, account_id: int) -> dict[str, Any]:
    loyalty = conn.execute(
        "SELECT customer_since, months_active, total_spent_gbp FROM customer_loyalty WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    months_active = int((loyalty["months_active"] if loyalty else 0) or 0)
    total_spent = float((loyalty["total_spent_gbp"] if loyalty else 0) or 0)
    return {
        "customerSince": loyalty["customer_since"] if loyalty else None,
        "monthsActive": months_active,
        "totalSpent": total_spent,
        "loyaltyLevel": resolve_loyalty_level(months_active),
    }


def get_account_performance_summary(conn: sqlite3.Connection, account_id: int) -> dict[str, dict[str, float]]:
    now = utc_now()
    today = now.strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_start = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    daily = conn.execute(
        "SELECT COALESCE(SUM(invested_amount),0) AS invested, COALESCE(SUM(profit_amount),0) AS profit FROM account_performance_snapshots WHERE account_id = ? AND period_day = ?",
        (account_id, today),
    ).fetchone()
    weekly = conn.execute(
        "SELECT COALESCE(SUM(invested_amount),0) AS invested, COALESCE(SUM(profit_amount),0) AS profit FROM account_performance_snapshots WHERE account_id = ? AND period_day >= ?",
        (account_id, week_start),
    ).fetchone()
    monthly = conn.execute(
        "SELECT COALESCE(SUM(invested_amount),0) AS invested, COALESCE(SUM(profit_amount),0) AS profit FROM account_performance_snapshots WHERE account_id = ? AND period_day >= ?",
        (account_id, month_start),
    ).fetchone()
    lifetime = conn.execute(
        "SELECT COALESCE(SUM(invested_amount),0) AS invested, COALESCE(SUM(profit_amount),0) AS profit FROM account_performance_snapshots WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    return {
        "daily": {"invested": float(daily["invested"] or 0), "profit": float(daily["profit"] or 0)},
        "weekly": {"invested": float(weekly["invested"] or 0), "profit": float(weekly["profit"] or 0)},
        "monthly": {"invested": float(monthly["invested"] or 0), "profit": float(monthly["profit"] or 0)},
        "lifetime": {"invested": float(lifetime["invested"] or 0), "profit": float(lifetime["profit"] or 0)},
    }


def build_display_name_policy(profile_row: sqlite3.Row | None) -> dict[str, Any]:
    changed_at_raw = None
    if profile_row is not None and "display_name_changed_at" in profile_row.keys():
        changed_at_raw = profile_row["display_name_changed_at"]
    changed_at = parse_db_timestamp(changed_at_raw)
    available_at = changed_at + timedelta(days=DISPLAY_NAME_CHANGE_COOLDOWN_DAYS) if changed_at else None
    return {
        "canChange": available_at is None or utc_now() >= available_at,
        "availableAt": format_db_timestamp(available_at),
        "cooldownDays": DISPLAY_NAME_CHANGE_COOLDOWN_DAYS,
    }


def are_accounts_connected(conn: sqlite3.Connection, left_account_id: int, right_account_id: int) -> bool:
    if left_account_id <= 0 or right_account_id <= 0:
        return False
    row = conn.execute(
        """
        SELECT 1
        FROM community_network
        WHERE (account_id = ? AND target_account_id = ?) OR (account_id = ? AND target_account_id = ?)
        LIMIT 1
        """,
        (left_account_id, right_account_id, right_account_id, left_account_id),
    ).fetchone()
    return row is not None


def get_connection_state(conn: sqlite3.Connection, viewer_account_id: int | None, target_account_id: int) -> str:
    if viewer_account_id is None:
        return "guest"
    if viewer_account_id == target_account_id:
        return "self"
    if are_accounts_connected(conn, viewer_account_id, target_account_id):
        return "connected"
    incoming = conn.execute(
        "SELECT 1 FROM community_connection_requests WHERE requester_account_id = ? AND recipient_account_id = ? AND status = 'pending' LIMIT 1",
        (target_account_id, viewer_account_id),
    ).fetchone()
    if incoming is not None:
        return "incoming"
    outgoing = conn.execute(
        "SELECT 1 FROM community_connection_requests WHERE requester_account_id = ? AND recipient_account_id = ? AND status = 'pending' LIMIT 1",
        (viewer_account_id, target_account_id),
    ).fetchone()
    if outgoing is not None:
        return "outgoing"
    return "none"


def get_connection_counts(conn: sqlite3.Connection, account_id: int) -> dict[str, int]:
    connections = conn.execute(
        "SELECT COUNT(*) AS count FROM community_network WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    incoming = conn.execute(
        "SELECT COUNT(*) AS count FROM community_connection_requests WHERE recipient_account_id = ? AND status = 'pending'",
        (account_id,),
    ).fetchone()
    outgoing = conn.execute(
        "SELECT COUNT(*) AS count FROM community_connection_requests WHERE requester_account_id = ? AND status = 'pending'",
        (account_id,),
    ).fetchone()
    return {
        "connections": int((connections["count"] if connections else 0) or 0),
        "incoming": int((incoming["count"] if incoming else 0) or 0),
        "outgoing": int((outgoing["count"] if outgoing else 0) or 0),
    }


def accept_connection_request(conn: sqlite3.Connection, requester_account_id: int, recipient_account_id: int) -> None:
    conn.execute(
        "UPDATE community_connection_requests SET status = 'accepted', responded_at = CURRENT_TIMESTAMP WHERE requester_account_id = ? AND recipient_account_id = ? AND status = 'pending'",
        (requester_account_id, recipient_account_id),
    )
    conn.execute(
        "INSERT OR IGNORE INTO community_network (account_id, target_account_id) VALUES (?, ?)",
        (requester_account_id, recipient_account_id),
    )
    conn.execute(
        "INSERT OR IGNORE INTO community_network (account_id, target_account_id) VALUES (?, ?)",
        (recipient_account_id, requester_account_id),
    )


def get_last_whisper_previews(conn: sqlite3.Connection, account_id: int) -> dict[int, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT m.message_body, m.created_at,
               CASE WHEN m.sender_account_id = ? THEN m.recipient_account_id ELSE m.sender_account_id END AS counterpart_id,
               CASE WHEN m.sender_account_id = ? THEN 1 ELSE 0 END AS is_mine
        FROM chat_messages m
        WHERE m.channel_type = 'whisper'
          AND m.is_deleted = 0
          AND (m.sender_account_id = ? OR m.recipient_account_id = ?)
        ORDER BY m.id DESC
        LIMIT 400
        """,
        (account_id, account_id, account_id, account_id),
    ).fetchall()
    previews: dict[int, dict[str, Any]] = {}
    for row in rows:
        counterpart_id = int(row["counterpart_id"] or 0)
        if counterpart_id <= 0 or counterpart_id in previews:
            continue
        previews[counterpart_id] = {
            "text": row["message_body"],
            "createdAt": row["created_at"],
            "isMine": bool(row["is_mine"]),
        }
    return previews


def get_community_member_snapshot(
    conn: sqlite3.Connection,
    target_account_id: int,
    viewer_account_id: int | None = None,
    viewer_is_admin: bool = False,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT a.id, a.username,
               cp.display_name, cp.avatar_url, cp.bio, cp.privacy_mode, cp.show_on_leaderboard, cp.user_rank, cp.ignore_whisper,
               ab.balance_amount, ab.total_invested, ab.total_profit, ab.updated_at
        FROM accounts a
        LEFT JOIN community_profiles cp ON cp.account_id = a.id
        LEFT JOIN account_balances ab ON ab.account_id = a.id
        WHERE a.id = ?
        """,
        (target_account_id,),
    ).fetchone()
    if row is None:
        return None

    is_owner = viewer_account_id is not None and int(viewer_account_id) == target_account_id
    can_view_stats = (row["privacy_mode"] or "public") != "private" or is_owner or viewer_is_admin
    connection_counts = get_connection_counts(conn, target_account_id)
    performance = get_account_performance_summary(conn, target_account_id) if can_view_stats else None
    top_tier = get_active_tier_number(conn, target_account_id)
    network_state = get_connection_state(conn, viewer_account_id, target_account_id)
    can_whisper = (
        viewer_account_id is not None
        and viewer_account_id != target_account_id
        and (network_state == "connected" or int(row["ignore_whisper"] or 0) == 0)
    )

    payload: dict[str, Any] = {
        "profile": {
            "id": target_account_id,
            "username": row["username"],
            "displayName": row["display_name"] or row["username"],
            "avatarUrl": row["avatar_url"] or COMMUNITY_DEFAULT_AVATAR,
            "bio": row["bio"] or "",
            "privacyMode": row["privacy_mode"] or "public",
            "showOnLeaderboard": bool(row["show_on_leaderboard"]) if row["show_on_leaderboard"] is not None else True,
            "userRank": row["user_rank"] or "",
            "tierBadge": f"Tier {top_tier}" if top_tier > 0 else "No Tier",
            "connectionsCount": connection_counts["connections"],
        },
        "badges": build_badges_for_account(conn, target_account_id, include_preview=BADGE_PREVIEW_ENABLED and is_owner),
        "networkState": network_state,
        "canWhisper": can_whisper,
        "visibility": "public" if can_view_stats else "private",
    }
    if can_view_stats:
        payload["balance"] = {
            "current": float((row["balance_amount"] if row else COMMUNITY_DEFAULT_BALANCE) or 0),
            "invested": float((row["total_invested"] if row else 0) or 0),
            "profit": float((row["total_profit"] if row else 0) or 0),
            "updatedAt": row["updated_at"],
        }
        payload["performance"] = performance
    return payload


def build_preview_badges_for_account(conn: sqlite3.Connection, account_id: int) -> list[dict[str, Any]]:
    account_row = conn.execute("SELECT verified FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if account_row is None:
        return []

    preview_badges: list[dict[str, Any]] = [
        {
            "code": "preview_bronze_member",
            "label": "Bronze Member",
            "shortLabel": "BRZ",
            "icon": "B",
            "tone": "bronze",
            "achievement": "Preview badge design enabled on your account.",
            "group": "preview",
        }
    ]

    if bool(account_row["verified"]):
        preview_badges.append(
            {
                "code": "verified_account",
                "label": "Verified Account",
                "shortLabel": "VER",
                "icon": "V",
                "tone": "verified",
                "achievement": "Confirmed account identity with trusted access.",
                "group": "trust",
            }
        )

    return preview_badges


def get_custom_badges_for_account(conn: sqlite3.Connection, account_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT code, label, short_label, icon, tone, achievement, badge_group
        FROM account_custom_badges
        WHERE account_id = ?
        ORDER BY display_order ASC, id ASC
        """,
        (account_id,),
    ).fetchall()
    return [
        {
            "code": row["code"],
            "label": row["label"],
            "shortLabel": row["short_label"],
            "icon": row["icon"],
            "tone": row["tone"],
            "achievement": row["achievement"],
            "group": row["badge_group"],
        }
        for row in rows
    ]


def build_badges_for_account(conn: sqlite3.Connection, account_id: int, include_preview: bool = False) -> list[dict[str, Any]]:
    custom_badges = get_custom_badges_for_account(conn, account_id)
    badges: list[dict[str, Any]] = list(custom_badges)
    active_tier = get_active_tier_number(conn, account_id)
    loyalty = get_loyalty_snapshot(conn, account_id)
    months_active = int(loyalty["monthsActive"] or 0)
    total_spent = float(loyalty["totalSpent"] or 0)
    loyalty_level = str(loyalty["loyaltyLevel"] or "bronze")

    if months_active >= LOYALTY_MEMBER_BADGE_MONTHS:
        badges.append(
            {
                "code": f"loyalty_{loyalty_level}",
                "label": f"{loyalty_level.title()} Loyalty",
                "shortLabel": loyalty_level.title(),
                "icon": "L",
                "tone": loyalty_level,
                "achievement": f"{months_active} active month{'s' if months_active != 1 else ''}",
                "group": "loyalty",
            }
        )
    if active_tier >= 1:
        badges.append(
            {
                "code": f"tier_{active_tier}",
                "label": f"Tier {active_tier} Member",
                "shortLabel": f"T{active_tier}",
                "icon": "T",
                "tone": "tier",
                "achievement": f"Unlocked tier {active_tier} member access",
                "group": "membership",
            }
        )
    if months_active >= LOYALTY_TRUSTED_BADGE_MONTHS:
        badges.append(
            {
                "code": "trusted_6m",
                "label": "Trusted 6 Months",
                "shortLabel": "6M",
                "icon": "6",
                "tone": "emerald",
                "achievement": "Stayed active for 6 months",
                "group": "milestone",
            }
        )
    if months_active >= LOYALTY_VETERAN_BADGE_MONTHS:
        badges.append(
            {
                "code": "veteran_12m",
                "label": "Veteran 12 Months",
                "shortLabel": "1Y",
                "icon": "1Y",
                "tone": "royal",
                "achievement": "Held membership for 12 months",
                "group": "milestone",
            }
        )
    if total_spent >= LOYALTY_SUPPORTER_SPEND_GBP:
        badges.append(
            {
                "code": "supporter_100",
                "label": "Top Supporter",
                "shortLabel": "GBP",
                "icon": "GBP",
                "tone": "gold",
                "achievement": f"Invested GBP {total_spent:.2f} into the platform",
                "group": "support",
            }
        )

    if include_preview:
        existing_codes = {str(badge.get("code") or "") for badge in badges}
        existing_tones = {str(badge.get("tone") or "") for badge in badges}
        preview_badges: list[dict[str, Any]] = []
        for badge in build_preview_badges_for_account(conn, account_id):
            if badge["code"] in existing_codes:
                continue
            if badge["tone"] == "bronze" and "bronze" in existing_tones:
                continue
            preview_badges.append(badge)
        badges = custom_badges + preview_badges + badges[len(custom_badges):]

    return badges


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA secure_delete = ON")
    return conn


def normalize_discord_tag(raw_value: str) -> str:
    cleaned = re.sub(r"\s+", "_", raw_value.strip().lower())
    cleaned = re.sub(r"[^a-z0-9_]", "", cleaned)
    return cleaned[:MAX_LENGTHS["discord_tag"]]


def validate_field_lengths(fields: dict[str, str]) -> str | None:
    for field_name, field_value in fields.items():
        max_len = MAX_LENGTHS.get(field_name)
        if max_len and len(field_value) > max_len:
            return f"{field_name.replace('_', ' ').title()} exceeds the maximum length ({max_len})."
    return None


def _is_same_origin(target_url: str, host_url: str) -> bool:
    target = urlparse(target_url)
    host = urlparse(host_url)
    return target.scheme == host.scheme and target.netloc == host.netloc


def is_verification_token_expired(created_at: str | None) -> bool:
    if not created_at:
        return True

    try:
        created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True

    return utc_now() - created_dt > timedelta(hours=VERIFICATION_TOKEN_MAX_AGE_HOURS)


def market_api_headers() -> dict[str, str]:
    if not COINGECKO_API_KEY:
        return {}
    return {COINGECKO_API_KEY_HEADER: COINGECKO_API_KEY}


def request_json_with_retry(
    url: str,
    params: dict[str, str],
    timeout: int = 5,
    retries: int = 2,
    headers: dict[str, str] | None = None,
) -> Any | None:
    for _ in range(retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout, headers=headers)
            if response.status_code == 200:
                return response.json()
        except requests.RequestException:
            continue
    return None


def clamp_int_value(raw_value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def resolve_stock_signal_symbols(raw_value: str | None) -> list[str]:
    if not raw_value:
        return STOCK_SIGNAL_SYMBOLS

    parsed_symbols: list[str] = []
    for chunk in str(raw_value).split(","):
        symbol = chunk.strip().upper()
        if not symbol:
            continue
        if not re.match(r"^[A-Z0-9.\-^=]{1,12}$", symbol):
            continue
        parsed_symbols.append(symbol)

    return parsed_symbols or STOCK_SIGNAL_SYMBOLS


def calculate_ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []

    smooth_period = max(1, period)
    multiplier = 2 / (smooth_period + 1)
    ema_values = [float(values[0])]
    for raw_value in values[1:]:
        current_value = float(raw_value)
        ema_values.append((current_value - ema_values[-1]) * multiplier + ema_values[-1])
    return ema_values


def calculate_rsi_value(values: list[float], period: int = 14) -> float:
    if len(values) < period + 1:
        return 50.0

    gains = 0.0
    losses = 0.0
    for index in range(len(values) - period, len(values)):
        delta = float(values[index]) - float(values[index - 1])
        if delta > 0:
            gains += delta
        else:
            losses += abs(delta)

    if losses == 0:
        return 100.0 if gains > 0 else 50.0

    average_gain = gains / period
    average_loss = losses / period
    if average_loss == 0:
        return 100.0

    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def stock_confidence_label(score: int) -> str:
    if score >= 90:
        return "Elite"
    if score >= 84:
        return "Pro"
    if score >= 78:
        return "Premium"
    if score >= 72:
        return "Core+"
    return "Core"


def fetch_yahoo_stock_snapshot(symbol: str) -> dict[str, Any] | None:
    payload = request_json_with_retry(
        f"{YAHOO_FINANCE_CHART_BASE_URL}/{symbol}",
        {
            "interval": "1m",
            "range": "1d",
            "includePrePost": "false",
            "events": "div,splits",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
        retries=REQUEST_RETRIES,
        headers={"User-Agent": YAHOO_FINANCE_USER_AGENT},
    )
    if not isinstance(payload, dict):
        return None

    result_rows = ((payload.get("chart") or {}).get("result") or [])
    if not result_rows or not isinstance(result_rows, list):
        return None

    result = result_rows[0]
    timestamps = result.get("timestamp") or []
    quote_rows = ((result.get("indicators") or {}).get("quote") or [{}])
    quote = quote_rows[0] if quote_rows and isinstance(quote_rows[0], dict) else {}
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    if not isinstance(timestamps, list) or not isinstance(closes, list):
        return None

    clean_rows: list[tuple[int, float, float]] = []
    for index, raw_timestamp in enumerate(timestamps):
        if index >= len(closes):
            break
        raw_close = closes[index]
        if raw_close is None:
            continue

        try:
            timestamp = int(raw_timestamp)
            close_price = float(raw_close)
        except (TypeError, ValueError):
            continue

        raw_volume = volumes[index] if index < len(volumes) and volumes[index] is not None else 0
        try:
            volume = max(0.0, float(raw_volume))
        except (TypeError, ValueError):
            volume = 0.0

        clean_rows.append((timestamp, close_price, volume))

    if len(clean_rows) < 30:
        return None

    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    return {
        "symbol": symbol.upper(),
        "name": str(meta.get("shortName") or meta.get("symbol") or symbol.upper()),
        "exchange": str(meta.get("exchangeName") or "US Equities"),
        "rows": clean_rows,
    }


def build_ai_stock_signal(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    rows = snapshot.get("rows")
    if not isinstance(rows, list) or len(rows) < 30:
        return None

    closes = [float(row[1]) for row in rows][-180:]
    volumes = [float(row[2]) for row in rows][-180:]
    if len(closes) < 30:
        return None

    ema_short = calculate_ema_series(closes, period=6)
    ema_long = calculate_ema_series(closes, period=21)
    if len(ema_short) < 2 or len(ema_long) < 2:
        return None

    latest_price = closes[-1]
    momentum_anchor = closes[-8] if len(closes) >= 8 else closes[0]
    momentum_pct = ((latest_price - momentum_anchor) / momentum_anchor * 100) if momentum_anchor > 0 else 0.0
    rsi_value = calculate_rsi_value(closes, period=14)
    recent_high = max(closes[-20:])
    trend_up = ema_short[-1] > ema_long[-1]
    fresh_cross = ema_short[-2] <= ema_long[-2] and trend_up
    breakout = latest_price >= (recent_high * 0.997)

    recent_volumes = volumes[-20:]
    avg_volume = sum(recent_volumes) / max(1, len(recent_volumes))
    latest_volume = recent_volumes[-1] if recent_volumes else 0.0
    volume_ratio = (latest_volume / avg_volume) if avg_volume > 0 else 1.0

    score = 35
    if trend_up:
        score += 16
    if fresh_cross:
        score += 18
    if momentum_pct >= 0.40:
        score += 16
    elif momentum_pct >= 0.10:
        score += 10
    elif momentum_pct < -0.20:
        score -= 10
    if 50 <= rsi_value <= 72:
        score += 12
    elif rsi_value < 40:
        score -= 8
    elif rsi_value > 80:
        score -= 6
    if volume_ratio >= 1.2:
        score += 10
    elif volume_ratio < 0.75:
        score -= 5
    if breakout:
        score += 8

    confidence = max(1, min(99, int(round(score))))
    if not trend_up or confidence < STOCK_SIGNAL_MIN_CONFIDENCE:
        return None

    target_move_pct = min(2.10, max(0.35, abs(momentum_pct) * 1.25 + 0.50))
    stop_move_pct = min(1.20, max(0.25, target_move_pct / 2.25))

    target_price = latest_price * (1 + target_move_pct / 100)
    stop_price = latest_price * (1 - stop_move_pct / 100)
    risk = max(0.0001, latest_price - stop_price)
    reward = max(0.0001, target_price - latest_price)
    risk_reward = round(reward / risk, 2)

    signal_timestamp = int(rows[-1][0])
    signal_dt = datetime.fromtimestamp(signal_timestamp, UTC)
    signal_day = signal_dt.strftime("%Y-%m-%d")
    signal_time = signal_dt.strftime("%H:%M")

    symbol = str(snapshot.get("symbol") or "").upper() or "UNKNOWN"
    insight = (
        f"{symbol} momentum engine detected a bullish setup: "
        f"short EMA is above long EMA, RSI {rsi_value:.1f}, "
        f"{momentum_pct:+.2f}% move over recent bars, volume ratio {volume_ratio:.2f}."
    )

    return {
        "id": f"stock-ai-{symbol}-{signal_day}-{signal_time}-BUY",
        "assetSymbol": symbol,
        "market": str(snapshot.get("exchange") or "US Equities"),
        "direction": "Long",
        "aiAction": "BUY",
        "aiConfidence": confidence,
        "confidenceLabel": stock_confidence_label(confidence),
        "aiInsight": insight,
        "entryPrice": round(latest_price, 4),
        "targetPrice": round(target_price, 4),
        "stopPrice": round(stop_price, 4),
        "riskReward": risk_reward,
        "momentumPct": round(momentum_pct, 3),
        "signalTimeUtc": signal_time,
        "signalDay": signal_day,
        "status": "published",
        "timerMinutes": 45,
        "source": "ai_stock_engine",
    }


def generate_live_stock_signals(symbols: list[str], limit: int) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for symbol in symbols:
        snapshot = fetch_yahoo_stock_snapshot(symbol)
        if snapshot is None:
            continue

        signal = build_ai_stock_signal(snapshot)
        if signal is None:
            continue
        signals.append(signal)

    signals.sort(
        key=lambda row: (
            -int(row.get("aiConfidence") or 0),
            -float(row.get("momentumPct") or 0.0),
            str(row.get("assetSymbol") or ""),
        )
    )
    return signals[: max(1, limit)]


def convert_market_quote_amount(amount: Any, from_currency: str = "EUR", to_currency: str = "USD") -> float:
    try:
        numeric_amount = float(amount or 0)
    except (TypeError, ValueError):
        return 0.0

    normalized_from = normalize_currency_code(from_currency)
    normalized_to = normalize_currency_code(to_currency)
    if normalized_from == normalized_to:
        return numeric_amount

    rates = get_exchange_rates()
    from_rate = rates.get(normalized_from)
    to_rate = rates.get(normalized_to)
    if from_rate is None or to_rate is None or from_rate == 0:
        return numeric_amount
    return numeric_amount / float(from_rate) * float(to_rate)


def get_bitvavo_assets(tracked_ids: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    resolved_ids = tracked_ids or list(BITVAVO_ASSET_CATALOG.keys())
    assets: list[dict[str, Any]] = []
    for raw_coin_id in resolved_ids:
        coin_id = str(raw_coin_id or "").strip().lower()
        asset = BITVAVO_ASSET_CATALOG.get(coin_id)
        if asset is None:
            continue
        assets.append({"id": coin_id, **asset})
    return assets


def fetch_bitvavo_ticker_rows(markets: list[str] | None = None) -> list[dict[str, Any]]:
    raw_payload = request_json_with_retry(
        f"{BITVAVO_BASE_URL}/ticker/24h",
        {},
        timeout=REQUEST_TIMEOUT_SECONDS,
        retries=REQUEST_RETRIES,
    )
    if not isinstance(raw_payload, list):
        return []

    if not markets:
        return [row for row in raw_payload if isinstance(row, dict)]

    market_set = {str(market or "").strip().upper() for market in markets}
    return [
        row
        for row in raw_payload
        if isinstance(row, dict) and str(row.get("market", "")).strip().upper() in market_set
    ]


def build_bitvavo_market_coin(asset: dict[str, Any], ticker_row: dict[str, Any]) -> dict[str, Any]:
    try:
        last_price_eur = float(ticker_row.get("last") or 0)
    except (TypeError, ValueError):
        last_price_eur = 0.0
    try:
        open_price_eur = float(ticker_row.get("open") or last_price_eur or 0)
    except (TypeError, ValueError):
        open_price_eur = last_price_eur
    try:
        high_price_eur = float(ticker_row.get("high") or last_price_eur or 0)
    except (TypeError, ValueError):
        high_price_eur = last_price_eur
    try:
        low_price_eur = float(ticker_row.get("low") or last_price_eur or 0)
    except (TypeError, ValueError):
        low_price_eur = last_price_eur
    try:
        volume_quote_eur = float(ticker_row.get("volumeQuote") or 0)
    except (TypeError, ValueError):
        volume_quote_eur = 0.0

    change_pct = ((last_price_eur - open_price_eur) / open_price_eur * 100) if open_price_eur > 0 else 0.0
    price_usd = convert_market_quote_amount(last_price_eur, "EUR", "USD")
    high_usd = convert_market_quote_amount(high_price_eur, "EUR", "USD")
    low_usd = convert_market_quote_amount(low_price_eur, "EUR", "USD")
    volume_usd = convert_market_quote_amount(volume_quote_eur, "EUR", "USD")
    circulating_supply = float(asset.get("circulating_supply") or 0)
    market_cap_usd = price_usd * circulating_supply if circulating_supply > 0 else 0.0

    return format_live_desk_coin(
        {
            "id": asset.get("id", ""),
            "symbol": asset.get("symbol", ""),
            "pair": f"{asset.get('symbol', '')}/USD",
            "name": asset.get("name", ""),
            "price": price_usd,
            "change": change_pct,
            "market_cap": market_cap_usd,
            "volume": volume_usd,
            "rank": int(asset.get("rank") or 0),
            "high_24h": high_usd,
            "low_24h": low_usd,
            "market_cap_change_24h": change_pct,
        }
    )


def build_bitvavo_market_rows(tracked_ids: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    assets = get_bitvavo_assets(tracked_ids)
    if not assets:
        return []

    ticker_rows = fetch_bitvavo_ticker_rows([str(asset.get("market", "")) for asset in assets])
    ticker_by_market = {
        str(row.get("market", "")).strip().upper(): row
        for row in ticker_rows
        if isinstance(row, dict)
    }

    rows: list[dict[str, Any]] = []
    for asset in assets:
        market = str(asset.get("market", "")).strip().upper()
        ticker_row = ticker_by_market.get(market)
        if ticker_row is None:
            continue
        rows.append(build_bitvavo_market_coin(asset, ticker_row))

    rows.sort(key=lambda coin: (int(coin.get("rank") or 9999), -float(coin.get("market_cap") or 0)))
    return rows


def build_bitvavo_chart_points(coin_id: str, limit: int = LIVE_DESK_CHART_POINT_LIMIT) -> list[dict[str, Any]]:
    asset = BITVAVO_ASSET_CATALOG.get(str(coin_id or "").strip().lower())
    if asset is None:
        return []

    raw_candles = request_json_with_retry(
        f"{BITVAVO_BASE_URL}/{asset['market']}/candles",
        {"interval": "1h", "limit": str(max(24, limit))},
        timeout=REQUEST_TIMEOUT_SECONDS,
        retries=REQUEST_RETRIES,
    )
    if not isinstance(raw_candles, list):
        return []

    candle_points: list[list[float]] = []
    for candle in raw_candles:
        if not isinstance(candle, list) or len(candle) < 5:
            continue
        try:
            timestamp = int(candle[0])
            close_price_eur = float(candle[4])
        except (TypeError, ValueError):
            continue
        candle_points.append([timestamp, convert_market_quote_amount(close_price_eur, "EUR", "USD")])

    candle_points.sort(key=lambda point: point[0])
    return build_chart_points(candle_points, limit=max(24, limit))


def build_bitvavo_live_desk_payload(tracked_ids: list[str] | tuple[str, ...], requested_coin_id: str) -> dict[str, Any]:
    top_coins = build_bitvavo_market_rows(tracked_ids)
    selected_coin = next((coin for coin in top_coins if str(coin.get("id", "")).lower() == requested_coin_id), None) or (top_coins[0] if top_coins else None)
    chart_points = build_bitvavo_chart_points(str(selected_coin.get("id", ""))) if selected_coin else []
    if selected_coin and not chart_points:
        chart_points = build_intraday_fallback_chart(selected_coin.get("price"), selected_coin.get("change"))

    return {
        "ok": True,
        "message": "Using Bitvavo live feed.",
        "topCoins": top_coins,
        "selectedCoin": selected_coin,
        "selectedCoinId": str(selected_coin.get("id", "")) if selected_coin else "",
        "chart": chart_points,
        "source": {
            "provider": "Bitvavo",
            "apiKeyConfigured": False,
            "fallback": True,
            "windowHours": 24,
            "quoteCurrency": "USD",
            "estimatedMarketCap": True,
        },
    }


def format_market_coin(coin: dict[str, Any]) -> dict[str, Any]:
    symbol = str(coin.get("symbol", "")).upper()
    return {
        "id": coin.get("id", ""),
        "symbol": symbol,
        "pair": f"{symbol}/USD" if symbol else "",
        "name": coin.get("name", ""),
        "price": coin.get("current_price", 0),
        "change": coin.get("price_change_percentage_24h", 0),
        "market_cap": coin.get("market_cap", 0),
        "volume": coin.get("total_volume", 0),
        "rank": coin.get("market_cap_rank", 0),
    }


def format_live_desk_coin(coin: dict[str, Any]) -> dict[str, Any]:
    if "current_price" in coin or "price_change_percentage_24h" in coin:
        market_coin = format_market_coin(coin)
    else:
        symbol = str(coin.get("symbol", "")).upper()
        market_coin = {
            "id": coin.get("id", ""),
            "symbol": symbol,
            "pair": coin.get("pair", f"{symbol}/USD" if symbol else ""),
            "name": coin.get("name", ""),
            "price": float(coin.get("price", 0) or 0),
            "change": float(coin.get("change", 0) or 0),
            "market_cap": float(coin.get("market_cap", 0) or 0),
            "volume": float(coin.get("volume", 0) or 0),
            "rank": int(coin.get("rank", 0) or 0),
        }
    market_coin.update(
        {
            "image": coin.get("image", ""),
            "high_24h": float(coin.get("high_24h") or coin.get("price") or coin.get("current_price") or 0),
            "low_24h": float(coin.get("low_24h") or coin.get("price") or coin.get("current_price") or 0),
            "ath": float(coin.get("ath") or 0),
            "market_cap_change_24h": float(coin.get("market_cap_change_percentage_24h") or coin.get("market_cap_change_24h") or 0),
        }
    )
    return market_coin


def build_chart_points(raw_points: Any, limit: int = LIVE_DESK_CHART_POINT_LIMIT) -> list[dict[str, Any]]:
    if not isinstance(raw_points, list):
        return []

    sanitized_points: list[tuple[int, float]] = []
    for point in raw_points:
        if not isinstance(point, list) or len(point) < 2:
            continue
        try:
            timestamp = int(point[0])
            price = float(point[1])
        except (TypeError, ValueError):
            continue
        sanitized_points.append((timestamp, price))

    if not sanitized_points:
        return []

    step = max(1, len(sanitized_points) // max(1, limit))
    sampled_points = sanitized_points[::step]
    if sampled_points[-1] != sanitized_points[-1]:
        sampled_points.append(sanitized_points[-1])

    return [{"timestamp": timestamp, "price": price} for timestamp, price in sampled_points[-limit:]]


def build_sparkline_points(
    raw_prices: Any,
    limit: int = LIVE_DESK_CHART_POINT_LIMIT,
    hours: int = 24,
    source_hours: int = 7 * 24,
) -> list[dict[str, Any]]:
    if not isinstance(raw_prices, list):
        return []

    prices: list[float] = []
    for point in raw_prices:
        try:
            prices.append(float(point))
        except (TypeError, ValueError):
            continue

    if not prices:
        return []

    source_hours = max(1, source_hours)
    window_points = max(2, int(len(prices) * (hours / source_hours)))
    recent_prices = prices[-max(limit, window_points):]
    step = max(1, len(recent_prices) // max(1, limit))
    sampled_prices = recent_prices[::step]
    if sampled_prices[-1] != recent_prices[-1]:
        sampled_prices.append(recent_prices[-1])

    now = utc_now()
    total_points = len(sampled_prices)
    step_minutes = max(5, int((hours * 60) / max(1, total_points - 1)))
    chart_points: list[dict[str, Any]] = []
    for index, price in enumerate(sampled_prices):
        offset = step_minutes * (total_points - index - 1)
        timestamp = int((now - timedelta(minutes=offset)).timestamp() * 1000)
        chart_points.append({"timestamp": timestamp, "price": price})
    return chart_points


def build_intraday_fallback_chart(current_price: float | int | None, change_pct: float | int | None, points: int = 24) -> list[dict[str, Any]]:
    try:
        resolved_price = float(current_price or 0)
    except (TypeError, ValueError):
        return []

    if resolved_price <= 0:
        return []

    try:
        resolved_change = float(change_pct or 0)
    except (TypeError, ValueError):
        resolved_change = 0.0

    denominator = 1 + (resolved_change / 100)
    starting_price = resolved_price / denominator if abs(denominator) > 1e-6 else resolved_price
    now = utc_now()
    chart_points: list[dict[str, Any]] = []

    for index in range(max(2, points)):
        progress = index / max(1, points - 1)
        timestamp = int((now - timedelta(hours=24 * (1 - progress))).timestamp() * 1000)
        price = starting_price + ((resolved_price - starting_price) * progress)
        chart_points.append({"timestamp": timestamp, "price": price})

    return chart_points


def build_market_summary(global_data: dict[str, Any] | None, crypto_rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload = global_data.get("data", {}) if isinstance(global_data, dict) else {}
    total_market_cap = (payload.get("total_market_cap") or {}).get("usd", 0)
    total_volume = (payload.get("total_volume") or {}).get("usd", 0)
    btc_dominance = (payload.get("market_cap_percentage") or {}).get("btc", 0)
    positive_count = sum(1 for coin in crypto_rows if (coin.get("change") or 0) >= 0)
    return {
        "market_cap": total_market_cap,
        "volume_24h": total_volume,
        "btc_dominance": btc_dominance,
        "positive_count": positive_count,
        "tracked_assets": len(crypto_rows),
        "updated_at": int(time.time()),
    }


def _client_key() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded_for or (request.remote_addr or "unknown")


def hash_ip(ip_value: str) -> str:
    return hashlib.sha256(f"ip:{TOKEN_PEPPER}:{ip_value}".encode("utf-8")).hexdigest()


def log_security_event(account_id: int | None, event_type: str, event_status: str) -> None:
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO account_security_events (account_id, event_type, event_status, ip_hash, user_agent) VALUES (?, ?, ?, ?, ?)",
                (
                    account_id,
                    event_type,
                    event_status,
                    hash_ip(_client_key()),
                    (request.headers.get("User-Agent", "") or "")[:255],
                ),
            )
    except Exception:
        # Security logging should never break the main request flow.
        pass


def is_rate_limited(client_key: str) -> bool:
    if IS_DEV_ENV and client_key in {"127.0.0.1", "::1", "localhost"}:
        return False

    now = time.time()
    request_times = _AUTH_REQUEST_LOG.get(client_key, [])
    valid_times = [t for t in request_times if now - t <= AUTH_RATE_LIMIT_WINDOW_SECONDS]
    limited = len(valid_times) >= AUTH_RATE_LIMIT_ATTEMPTS
    if not limited:
        valid_times.append(now)
    _AUTH_REQUEST_LOG[client_key] = valid_times
    return limited


@app.before_request
def validate_origin_for_state_changes() -> tuple[Any, int] | None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None

    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")

    if origin and not _is_same_origin(origin, request.host_url):
        return jsonify({"ok": False, "message": "Cross-origin request blocked."}), 403

    if not origin and referer and not _is_same_origin(referer, request.host_url):
        return jsonify({"ok": False, "message": "Cross-origin request blocked."}), 403

    # Optional stricter origin allow-list for deployments behind fixed domains.
    if ALLOWED_CORS_ORIGINS and origin and origin not in ALLOWED_CORS_ORIGINS:
        return jsonify({"ok": False, "message": "Origin is not allowed."}), 403

    return None


@app.before_request
def load_current_account() -> None:
    g.current_account = None
    g.clear_remember_cookie = False

    account_id = session.get("account_id")
    raw_remember_token = request.cookies.get(REMEMBER_COOKIE_NAME)

    with get_db() as conn:
        if account_id:
            account = fetch_account_by_id(conn, int(account_id))
            if account is not None:
                g.current_account = account
                return None
            session.pop("account_id", None)

        if raw_remember_token:
            account = load_account_from_remember_cookie(conn, raw_remember_token)
            if account is not None:
                session["account_id"] = int(account["id"])
                g.current_account = account
                return None
            g.clear_remember_cookie = True
    return None


@app.after_request
def apply_security_headers(response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if getattr(g, "clear_remember_cookie", False):
        clear_auth_cookie(response)
    return response


def init_db() -> None:
    with get_db() as conn:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                zipcode TEXT NOT NULL,
                address TEXT NOT NULL,
                phone_number TEXT,
                discord_username TEXT,
                discord_tag TEXT,
                verified INTEGER NOT NULL DEFAULT 1,
                is_admin INTEGER NOT NULL DEFAULT 0,
                data_consent_accepted INTEGER NOT NULL DEFAULT 0,
                data_consent_accepted_at TIMESTAMP,
                verification_token TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                event_type TEXT NOT NULL,
                event_status TEXT NOT NULL,
                ip_hash TEXT,
                user_agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS billing_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL UNIQUE,
                billing_name_enc TEXT,
                billing_company_enc TEXT,
                billing_address_enc TEXT,
                billing_zip_enc TEXT,
                billing_country_enc TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS billing_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                purchase_id INTEGER,
                tier_number INTEGER,
                plan_name TEXT,
                billing_cycle TEXT,
                billing_method TEXT,
                price_gbp REAL,
                payment_url TEXT,
                payment_status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id),
                FOREIGN KEY (purchase_id) REFERENCES purchases(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                tier_name TEXT NOT NULL,
                tier_number INTEGER,
                plan_name TEXT,
                billing_cycle TEXT,
                billing_method TEXT,
                price_gbp REAL,
                signals_per_day INTEGER,
                billing_name TEXT,
                billing_company TEXT,
                billing_address TEXT,
                billing_zip TEXT,
                billing_country TEXT,
                discord_username TEXT,
                discord_tag TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                months_active INTEGER DEFAULT 0,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                user_agent TEXT,
                expires_at TIMESTAMP NOT NULL,
                last_used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_day TEXT NOT NULL,
                tier_number INTEGER NOT NULL,
                asset_symbol TEXT NOT NULL,
                market TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                target_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                confidence_label TEXT NOT NULL,
                session_label TEXT NOT NULL,
                thesis TEXT NOT NULL,
                signal_time_utc TEXT NOT NULL DEFAULT '12:00',
                timer_minutes INTEGER NOT NULL DEFAULT 90,
                base_currency_code TEXT NOT NULL DEFAULT 'USD',
                status TEXT NOT NULL DEFAULT 'open',
                is_free INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discord_member_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_username TEXT NOT NULL UNIQUE,
                discord_tag TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_discord_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL UNIQUE,
                discord_username TEXT,
                verification_status TEXT NOT NULL DEFAULT 'pending',
                verified_tag TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source TEXT NOT NULL DEFAULT 'system_registry',
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )

        # Loyalty and transaction tracking
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_loyalty (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL UNIQUE,
                customer_since TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                months_active INTEGER DEFAULT 0,
                total_spent_gbp REAL DEFAULT 0,
                loyalty_level TEXT DEFAULT 'bronze',
                last_purchase_at TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )
        
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                purchase_id INTEGER,
                transaction_type TEXT NOT NULL,
                amount_gbp REAL NOT NULL,
                currency_code TEXT DEFAULT 'GBP',
                status TEXT NOT NULL DEFAULT 'completed',
                payment_method TEXT,
                description TEXT,
                invoice_number TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id),
                FOREIGN KEY (purchase_id) REFERENCES purchases(id)
            )
            """
        )
        
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS email_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                email_type TEXT NOT NULL,
                recipient_email TEXT NOT NULL,
                subject TEXT,
                body TEXT,
                sent_at TIMESTAMP,
                scheduled_for TIMESTAMP,
                status TEXT DEFAULT 'pending',
                retry_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS community_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL UNIQUE,
                display_name TEXT,
                display_name_changed_at TIMESTAMP,
                avatar_url TEXT,
                bio TEXT,
                privacy_mode TEXT NOT NULL DEFAULT 'public',
                layout_preset TEXT NOT NULL DEFAULT 'default',
                show_on_leaderboard INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL UNIQUE,
                balance_amount REAL NOT NULL DEFAULT 0,
                total_invested REAL NOT NULL DEFAULT 0,
                total_profit REAL NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_performance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                period_day TEXT NOT NULL,
                invested_amount REAL NOT NULL DEFAULT 0,
                profit_amount REAL NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS community_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_account_id INTEGER NOT NULL,
                recipient_account_id INTEGER,
                channel_type TEXT NOT NULL,
                message_body TEXT NOT NULL,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_account_id) REFERENCES accounts(id),
                FOREIGN KEY (recipient_account_id) REFERENCES accounts(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_suspensions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                reason TEXT,
                suspended_until TIMESTAMP NOT NULL,
                created_by_account_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id),
                FOREIGN KEY (created_by_account_id) REFERENCES accounts(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS community_network (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                target_account_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, target_account_id),
                FOREIGN KEY (account_id) REFERENCES accounts(id),
                FOREIGN KEY (target_account_id) REFERENCES accounts(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS community_connection_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requester_account_id INTEGER NOT NULL,
                recipient_account_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                responded_at TIMESTAMP,
                UNIQUE(requester_account_id, recipient_account_id),
                FOREIGN KEY (requester_account_id) REFERENCES accounts(id),
                FOREIGN KEY (recipient_account_id) REFERENCES accounts(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_custom_badges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                label TEXT NOT NULL,
                short_label TEXT NOT NULL,
                icon TEXT,
                tone TEXT NOT NULL DEFAULT 'royal',
                achievement TEXT,
                badge_group TEXT NOT NULL DEFAULT 'custom',
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, code),
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )

        ensure_column(conn, "accounts", "zipcode", "TEXT")
        ensure_column(conn, "accounts", "address", "TEXT")
        ensure_column(conn, "accounts", "phone_number", "TEXT")
        ensure_column(conn, "accounts", "username", "TEXT")
        ensure_column(conn, "accounts", "discord_username", "TEXT")
        ensure_column(conn, "accounts", "discord_tag", "TEXT")
        ensure_column(conn, "accounts", "verified", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "accounts", "is_admin", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "accounts", "data_consent_accepted", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "accounts", "data_consent_accepted_at", "TIMESTAMP")
        ensure_column(conn, "accounts", "verification_token", "TEXT")
        ensure_column(conn, "accounts", "verification_token_created_at", "TIMESTAMP")
        ensure_column(conn, "accounts", "verification_token_hash", "TEXT")
        ensure_column(conn, "accounts", "full_name_enc", "TEXT")
        ensure_column(conn, "accounts", "phone_number_enc", "TEXT")
        ensure_column(conn, "accounts", "zipcode_enc", "TEXT")
        ensure_column(conn, "accounts", "address_enc", "TEXT")
        ensure_column(conn, "accounts", "discord_username_enc", "TEXT")
        ensure_column(conn, "accounts", "preferred_currency_code", "TEXT")

        ensure_column(conn, "purchases", "tier_number", "INTEGER")
        ensure_column(conn, "purchases", "plan_name", "TEXT")
        ensure_column(conn, "purchases", "billing_cycle", "TEXT")
        ensure_column(conn, "purchases", "billing_method", "TEXT")
        ensure_column(conn, "purchases", "price_gbp", "REAL")
        ensure_column(conn, "purchases", "signals_per_day", "INTEGER")
        ensure_column(conn, "purchases", "billing_name", "TEXT")
        ensure_column(conn, "purchases", "billing_company", "TEXT")
        ensure_column(conn, "purchases", "billing_address", "TEXT")
        ensure_column(conn, "purchases", "billing_zip", "TEXT")
        ensure_column(conn, "purchases", "billing_country", "TEXT")
        ensure_column(conn, "purchases", "discord_username", "TEXT")
        ensure_column(conn, "purchases", "discord_tag", "TEXT")
        ensure_column(conn, "purchases", "billing_name_enc", "TEXT")
        ensure_column(conn, "purchases", "billing_company_enc", "TEXT")
        ensure_column(conn, "purchases", "billing_address_enc", "TEXT")
        ensure_column(conn, "purchases", "billing_zip_enc", "TEXT")
        ensure_column(conn, "purchases", "billing_country_enc", "TEXT")
        ensure_column(conn, "purchases", "expires_at", "TIMESTAMP")
        ensure_column(conn, "purchases", "months_active", "INTEGER DEFAULT 0")
        ensure_column(conn, "purchases", "auto_renew", "INTEGER DEFAULT 1")
        ensure_column(conn, "purchases", "next_renewal_date", "TIMESTAMP")
        ensure_column(conn, "purchases", "renewal_reminder_sent", "INTEGER DEFAULT 0")
        ensure_column(conn, "purchases", "last_renewed_at", "TIMESTAMP")
        ensure_column(conn, "daily_signals", "is_free", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "daily_signals", "signal_time_utc", "TEXT NOT NULL DEFAULT '12:00'")
        ensure_column(conn, "daily_signals", "timer_minutes", "INTEGER NOT NULL DEFAULT 90")

        ensure_column(conn, "community_profiles", "display_name", "TEXT")
        ensure_column(conn, "community_profiles", "display_name_changed_at", "TIMESTAMP")
        ensure_column(conn, "community_profiles", "avatar_url", "TEXT")
        ensure_column(conn, "community_profiles", "bio", "TEXT")
        ensure_column(conn, "community_profiles", "privacy_mode", "TEXT NOT NULL DEFAULT 'public'")
        ensure_column(conn, "community_profiles", "layout_preset", "TEXT NOT NULL DEFAULT 'default'")
        ensure_column(conn, "community_profiles", "show_on_leaderboard", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "community_profiles", "user_rank", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "community_profiles", "ignore_whisper", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "community_profiles", "email_alerts", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "community_profiles", "market_alerts", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "community_profiles", "renewal_reminders", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "community_profiles", "preferred_billing_method", "TEXT NOT NULL DEFAULT 'paypal'")
        ensure_column(conn, "account_balances", "balance_amount", "REAL NOT NULL DEFAULT 0")
        ensure_column(conn, "account_balances", "total_invested", "REAL NOT NULL DEFAULT 0")
        ensure_column(conn, "account_balances", "total_profit", "REAL NOT NULL DEFAULT 0")

        conn.execute("DROP TRIGGER IF EXISTS trg_accounts_force_verified_after_insert")
        conn.execute("DROP TRIGGER IF EXISTS trg_accounts_force_verified_after_update")

        existing_usernames = {
            str(row["username"]).strip().lower()
            for row in conn.execute("SELECT username FROM accounts WHERE username IS NOT NULL AND trim(username) != ''").fetchall()
        }
        legacy_account_rows = conn.execute("SELECT id, email, username, verified, is_admin FROM accounts").fetchall()
        for row in legacy_account_rows:
            username_value = str(row["username"] or "").strip().lower()
            if not username_value:
                username_value = build_legacy_username(row["email"], int(row["id"]), existing_usernames)
            is_admin = 1 if bool(row["is_admin"]) or is_auto_admin_email(row["email"]) or is_admin_username(username_value) else 0
            verified_value = 1
            conn.execute(
                "UPDATE accounts SET username = ?, verified = ?, is_admin = ?, verification_token = NULL, verification_token_hash = NULL, verification_token_created_at = NULL WHERE id = ?",
                (username_value, verified_value, is_admin, int(row["id"])),
            )

            conn.execute(
                "INSERT INTO community_profiles (account_id, display_name, avatar_url, privacy_mode, layout_preset, show_on_leaderboard) VALUES (?, ?, ?, 'public', 'default', 1) ON CONFLICT(account_id) DO NOTHING",
                (int(row["id"]), username_value, COMMUNITY_DEFAULT_AVATAR),
            )
            conn.execute(
                "INSERT INTO account_balances (account_id, balance_amount, total_invested, total_profit) VALUES (?, ?, 0, 0) ON CONFLICT(account_id) DO NOTHING",
                (int(row["id"]), COMMUNITY_DEFAULT_BALANCE),
            )

        founder_rows = conn.execute(
            """
            SELECT id
            FROM accounts
            WHERE lower(email) LIKE 'dylan.reiziger%'
               OR lower(full_name) LIKE 'dylan reizig%'
               OR lower(username) IN ('krok', 'krokonl')
            """
        ).fetchall()
        for row in founder_rows:
            conn.execute(
                """
                INSERT INTO account_custom_badges (
                    account_id,
                    code,
                    label,
                    short_label,
                    icon,
                    tone,
                    achievement,
                    badge_group,
                    display_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, code) DO UPDATE SET
                    label = excluded.label,
                    short_label = excluded.short_label,
                    icon = excluded.icon,
                    tone = excluded.tone,
                    achievement = excluded.achievement,
                    badge_group = excluded.badge_group,
                    display_order = excluded.display_order
                """,
                (
                    int(row["id"]),
                    "vault_founder",
                    "Vault Founder",
                    "FND",
                    "F",
                    "royal",
                    "Builder account with direct VaultSignals ownership and design authority.",
                    "founder",
                    -100,
                ),
            )

        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_username ON accounts(username)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_token_hash ON accounts(verification_token_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_purchases_account_id ON purchases(account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_billing_transactions_account_id ON billing_transactions(account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_security_events_account_id ON account_security_events(account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_account_id ON auth_tokens(account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires_at ON auth_tokens(expires_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_signals_day_tier ON daily_signals(signal_day, tier_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_discord_registry_username ON discord_member_registry(discord_username)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_discord_verifications_account ON account_discord_verifications(account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_profiles_account ON community_profiles(account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_profiles_privacy ON community_profiles(privacy_mode, show_on_leaderboard)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_balances_account ON account_balances(account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_account_day ON account_performance_snapshots(account_id, period_day)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_global_time ON chat_messages(channel_type, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_whisper_time ON chat_messages(sender_account_id, recipient_account_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_suspensions_account ON chat_suspensions(account_id, suspended_until)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_network_account_target ON community_network(account_id, target_account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_connection_requests_requester ON community_connection_requests(requester_account_id, status, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_connection_requests_recipient ON community_connection_requests(recipient_account_id, status, created_at)")

        # Backfill secure columns for existing rows.
        account_rows = conn.execute(
            "SELECT id, full_name, full_name_enc, zipcode, zipcode_enc, address, address_enc, discord_username, discord_username_enc, verification_token, verification_token_hash FROM accounts"
        ).fetchall()
        for row in account_rows:
            conn.execute(
                "UPDATE accounts SET full_name_enc = COALESCE(?, full_name_enc), zipcode_enc = COALESCE(?, zipcode_enc), address_enc = COALESCE(?, address_enc), discord_username_enc = COALESCE(?, discord_username_enc), verification_token_hash = COALESCE(?, verification_token_hash) WHERE id = ?",
                (
                    encrypt_value(row["full_name"]) if row["full_name"] and not row["full_name_enc"] else row["full_name_enc"],
                    encrypt_value(row["zipcode"]) if row["zipcode"] and not row["zipcode_enc"] else row["zipcode_enc"],
                    encrypt_value(row["address"]) if row["address"] and not row["address_enc"] else row["address_enc"],
                    encrypt_value(row["discord_username"]) if row["discord_username"] and not row["discord_username_enc"] else row["discord_username_enc"],
                    hash_token(row["verification_token"]) if row["verification_token"] and not row["verification_token_hash"] else row["verification_token_hash"],
                    row["id"],
                ),
            )
            sync_discord_verification_for_account(conn, int(row["id"]), decrypt_value(row["discord_username_enc"]) or row["discord_username"])

        purchase_rows = conn.execute(
            "SELECT id, billing_name, billing_name_enc, billing_company, billing_company_enc, billing_address, billing_address_enc, billing_zip, billing_zip_enc, billing_country, billing_country_enc FROM purchases"
        ).fetchall()
        for row in purchase_rows:
            conn.execute(
                "UPDATE purchases SET billing_name_enc = COALESCE(?, billing_name_enc), billing_company_enc = COALESCE(?, billing_company_enc), billing_address_enc = COALESCE(?, billing_address_enc), billing_zip_enc = COALESCE(?, billing_zip_enc), billing_country_enc = COALESCE(?, billing_country_enc) WHERE id = ?",
                (
                    encrypt_value(row["billing_name"]) if row["billing_name"] and not row["billing_name_enc"] else row["billing_name_enc"],
                    encrypt_value(row["billing_company"]) if row["billing_company"] and not row["billing_company_enc"] else row["billing_company_enc"],
                    encrypt_value(row["billing_address"]) if row["billing_address"] and not row["billing_address_enc"] else row["billing_address_enc"],
                    encrypt_value(row["billing_zip"]) if row["billing_zip"] and not row["billing_zip_enc"] else row["billing_zip_enc"],
                    encrypt_value(row["billing_country"]) if row["billing_country"] and not row["billing_country_enc"] else row["billing_country_enc"],
                    row["id"],
                ),
            )

        conn.execute("DELETE FROM auth_tokens WHERE expires_at <= CURRENT_TIMESTAMP")
        conn.execute("DELETE FROM chat_messages WHERE channel_type = 'global'")
        
        # Backfill is_free for existing signals - mark tier 1 signals as free
        try:
            conn.execute("UPDATE daily_signals SET is_free = 1 WHERE tier_number = ? AND is_free = 0", (TIER_NUMBER_MIN,))
        except Exception as exc:
            logger.warning("Skipping daily_signals is_free backfill during migration: %s", exc)

        try:
            blueprint_by_key = {
                (
                    int(signal.get("tier_number", 0) or 0),
                    str(signal.get("asset_symbol", "") or "").strip().upper(),
                    str(signal.get("session_label", "") or "").strip(),
                ): signal
                for signal in DAILY_SIGNAL_BLUEPRINTS
            }
            signal_rows = conn.execute(
                "SELECT id, tier_number, asset_symbol, session_label, signal_time_utc, timer_minutes FROM daily_signals"
            ).fetchall()
            for row in signal_rows:
                blueprint_signal = blueprint_by_key.get(
                    (
                        int(row["tier_number"] or 0),
                        str(row["asset_symbol"] or "").strip().upper(),
                        str(row["session_label"] or "").strip(),
                    )
                )
                mapped_time = DEFAULT_SIGNAL_TIME_BY_SESSION.get(
                    str(row["session_label"] or "").strip(),
                    DEFAULT_SIGNAL_TIME_BY_TIER.get(int(row["tier_number"] or 0), DEFAULT_SIGNAL_TIME_BY_SESSION["Session"]),
                )
                if blueprint_signal:
                    mapped_time = normalize_signal_time_utc(
                        blueprint_signal.get("signal_time_utc"),
                        blueprint_signal.get("session_label"),
                        int(blueprint_signal.get("tier_number", 0) or 0),
                    )
                current_time = str(row["signal_time_utc"] or "").strip()
                resolved_time = normalize_signal_time_utc(current_time, row["session_label"], int(row["tier_number"] or 0))
                if current_time == DEFAULT_SIGNAL_TIME_BY_SESSION["Session"] and mapped_time != DEFAULT_SIGNAL_TIME_BY_SESSION["Session"]:
                    resolved_time = mapped_time
                mapped_timer = normalize_signal_timer_minutes(
                    blueprint_signal.get("timer_minutes") if blueprint_signal else row["timer_minutes"]
                )
                current_timer = int(row["timer_minutes"] or DEFAULT_SIGNAL_TIMER_MINUTES)
                resolved_timer = normalize_signal_timer_minutes(current_timer)
                if current_timer == DEFAULT_SIGNAL_TIMER_MINUTES and mapped_timer != DEFAULT_SIGNAL_TIMER_MINUTES:
                    resolved_timer = mapped_timer
                if resolved_time != current_time or resolved_timer != int(row["timer_minutes"] or DEFAULT_SIGNAL_TIMER_MINUTES):
                    conn.execute(
                        "UPDATE daily_signals SET signal_time_utc = ?, timer_minutes = ? WHERE id = ?",
                        (resolved_time, resolved_timer, int(row["id"])),
                    )
        except Exception as exc:
            logger.warning("Skipping daily_signals timing backfill during migration: %s", exc)
        
        ensure_daily_signals(conn)


@app.context_processor
def inject_ui_config() -> dict[str, dict[str, Any]]:
    return {
        "ui_config": {
            "vat_rate": CHECKOUT_VAT_RATE,
            "default_currency_code": DEFAULT_CURRENCY_CODE,
            "currency_symbol": DEFAULT_CURRENCY_SYMBOL,
            "community_chat_poll_ms": COMMUNITY_CHAT_POLL_MS,
            "bitvavo_url": BITVAVO_URL,
            "feedback_phone_number": FEEDBACK_PHONE_NUMBER,
            "feedback_phone_display": FEEDBACK_PHONE_DISPLAY,
            "feedback_contact_email": FEEDBACK_CONTACT_EMAIL,
        }
    }


@app.after_request
def disable_static_cache(response: Response) -> Response:
    if request.path.startswith("/static/") or request.path.startswith("/api/") or request.path == "/stream":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/")
def index() -> str:
    return render_template(
        "index.html",
        tiers=TIERS,
        is_logged_in=(g.current_account is not None),
        performance_timeline=get_performance_timeline(),
    )


@app.route("/price")
def price() -> str:
    return render_template("price.html", tiers=TIERS, pricing_rows=build_pricing_rows(), discord_tag_labels=DISCORD_TAG_LABELS)


@app.route("/about-us")
def about_us() -> str:
    return render_template("about_us.html")


@app.route("/terms-and-conditions")
def terms_and_conditions() -> str:
    return render_template("terms_and_conditions.html")


@app.route("/your-signals")
def your_signals() -> str:
    if g.current_account is None:
        return render_template("your_signals.html", requires_login=True)
    return render_template("your_signals.html", requires_login=False)


@app.route("/settings")
def settings_page() -> str:
    if g.current_account is None:
        return redirect("/?login=1")
    return render_template("settings.html", tiers=TIERS)


@app.route("/account/profile")
def account_profile_page() -> str:
    if g.current_account is None:
        return redirect("/?login=1")
    return render_template("account_profile.html", tiers=TIERS)


@app.route("/account/dashboard")
def account_dashboard() -> str:
    if g.current_account is None:
        return redirect("/")
    return render_template("account_dashboard.html", requires_login=False)


@app.route("/community/account/<username>")
def community_account_page(username: str) -> str:
    if not username:
        return redirect("/")
    return render_template("community_account.html", target_username=username)


@app.route("/pro")
def pro_mode_alias() -> str:
    return redirect("/pro-mode")


@app.route("/pro-mode")
def pro_mode_page() -> str:
    return render_template("pro.html", requires_login=(g.current_account is None))


@app.get("/api/pro/signals")
def pro_signals() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    account_id = int(g.current_account["id"])
    today = utc_now().strftime("%Y-%m-%d")

    # Resolve display currency from account preference / cookie / region
    with get_db() as conn:
        account_row = fetch_account_by_id(conn, account_id)
        currency_pref = resolve_currency_preference(account_row)
        selected_currency = currency_pref["code"]

        ensure_daily_signals(conn, today)
        rows = conn.execute(
            "SELECT * FROM daily_signals WHERE signal_day = ? ORDER BY tier_number ASC",
            (today,),
        ).fetchall()

    _CONF_SCORE = {"Core": 72, "Core+": 81, "Active": 68, "Premium": 85, "Pro": 78, "Elite": 92}
    result = []
    for s in rows:
        entry = float(s["entry_price"] or 0)
        target = float(s["target_price"] or 0)
        stop = float(s["stop_price"] or 0)
        reward = abs(target - entry)
        risk = abs(entry - stop)
        rr = round(reward / risk, 2) if risk > 0 else 0
        pct_gain = round(((target - entry) / entry) * 100, 2) if entry > 0 else 0
        direction = (s["direction"] or "").lower()
        ai_action = "BUY" if direction == "long" else "SELL"
        ai_conf = _CONF_SCORE.get(s["confidence_label"] or "", 70)
        thesis = s["thesis"] or ""
        ai_insight = (
            f"Bullish structure detected on {s['asset_symbol']}. "
            f"Entry at {entry:,.2f} targets {target:,.2f} — {rr}:1 reward/risk. {thesis[:90]}{'…' if len(thesis) > 90 else ''}"
            if direction == "long"
            else
            f"Bearish signal on {s['asset_symbol']}. "
            f"Short from {entry:,.2f} targets {target:,.2f} — {rr}:1 reward/risk. {thesis[:90]}{'…' if len(thesis) > 90 else ''}"
        )
        serialized = serialize_signal_row(s, selected_currency)
        serialized.update({
            "riskReward": rr,
            "pctGain": round(abs(pct_gain), 2),
            "aiAction": ai_action,
            "aiConfidence": ai_conf,
            "aiInsight": ai_insight,
        })
        result.append(serialized)

    buys = [s for s in result if s["aiAction"] == "BUY"]
    sells = [s for s in result if s["aiAction"] == "SELL"]
    sentiment = "Bullish" if len(buys) >= len(result) / 2 else "Bearish"
    top_pick = max(result, key=lambda x: x["aiConfidence"]) if result else None
    avg_rr = round(sum(s["riskReward"] for s in result) / len(result), 2) if result else 0

    return jsonify({
        "ok": True,
        "signals": result,
        "market": {
            "sentiment": sentiment,
            "topPickSymbol": top_pick["assetSymbol"] if top_pick else None,
            "topPickAction": top_pick["aiAction"] if top_pick else None,
            "topPickConfidence": top_pick["aiConfidence"] if top_pick else None,
            "avgRiskReward": avg_rr,
            "buyCount": len(buys),
            "sellCount": len(sells),
            "totalSignals": len(result),
        },
        "displayCurrency": selected_currency,
    }), 200


@app.get("/api/ai/stock-signals")
def ai_stock_signals() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    symbols = resolve_stock_signal_symbols(str(request.args.get("symbols", "")).strip() or None)
    default_limit = max(1, min(20, STOCK_SIGNAL_DEFAULT_LIMIT))
    limit = clamp_int_value(request.args.get("limit"), 1, 20, default_limit)

    cache_key = f"{','.join(symbols)}:{limit}"
    cached_entry = _STOCK_SIGNAL_CACHE.get(cache_key)
    if cached_entry and (time.time() - float(cached_entry.get("updated_at", 0) or 0)) < STOCK_SIGNAL_CACHE_TTL_SECONDS:
        return jsonify(cached_entry.get("payload", {})), 200

    signals = generate_live_stock_signals(symbols, limit)
    payload = {
        "ok": True,
        "signals": signals,
        "meta": {
            "provider": "Yahoo Finance",
            "engine": "Momentum RSI signal engine",
            "trackedSymbols": symbols,
            "generatedAtUtc": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cacheTtlSeconds": STOCK_SIGNAL_CACHE_TTL_SECONDS,
            "minimumConfidence": STOCK_SIGNAL_MIN_CONFIDENCE,
        },
    }

    if not signals and cached_entry and cached_entry.get("payload"):
        return jsonify(cached_entry["payload"]), 200

    _STOCK_SIGNAL_CACHE[cache_key] = {"payload": payload, "updated_at": time.time()}
    return jsonify(payload), 200


@app.route("/admin/signals")
def admin_signals_page() -> str:
    if g.current_account is None:
        return render_template("admin_signals.html", access_denied=True, denied_reason="login", selected_day=utc_now().strftime("%Y-%m-%d"))
    if not is_admin_account(g.current_account):
        return render_template("admin_signals.html", access_denied=True, denied_reason="role", selected_day=utc_now().strftime("%Y-%m-%d"))
    return render_template("admin_signals.html", access_denied=False, denied_reason="", selected_day=utc_now().strftime("%Y-%m-%d"))


@app.get("/api/admin/signals")
def admin_list_signals() -> tuple[Any, int]:
    _, error_response = require_admin_api()
    if error_response is not None:
        return error_response

    signal_day = str(request.args.get("day", "")).strip() or utc_now().strftime("%Y-%m-%d")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", signal_day):
        return jsonify({"ok": False, "message": "Use day format YYYY-MM-DD."}), 400

    with get_db() as conn:
        ensure_daily_signals(conn, signal_day)
        rows = conn.execute(
            "SELECT id, signal_day, tier_number, asset_symbol, market, direction, entry_price, target_price, stop_price, confidence_label, session_label, thesis, signal_time_utc, timer_minutes, status, created_at FROM daily_signals WHERE signal_day = ? ORDER BY tier_number ASC, id ASC",
            (signal_day,),
        ).fetchall()

    return jsonify(
        {
            "ok": True,
            "day": signal_day,
            "signals": [
                {
                    "id": row["id"],
                    "signalDay": row["signal_day"],
                    "tierNumber": row["tier_number"],
                    "assetSymbol": row["asset_symbol"],
                    "market": row["market"],
                    "direction": row["direction"],
                    "entryPrice": row["entry_price"],
                    "targetPrice": row["target_price"],
                    "stopPrice": row["stop_price"],
                    "confidenceLabel": row["confidence_label"],
                    "sessionLabel": row["session_label"],
                    "thesis": row["thesis"],
                    "signalTimeUtc": normalize_signal_time_utc(row["signal_time_utc"], row["session_label"], int(row["tier_number"] or 0)),
                    "timerMinutes": normalize_signal_timer_minutes(row["timer_minutes"]),
                    "status": row["status"],
                    "createdAt": row["created_at"],
                }
                for row in rows
            ],
        }
    ), 200


def parse_admin_signal_payload(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    signal_day = str(payload.get("signalDay", "")).strip() or utc_now().strftime("%Y-%m-%d")
    asset_symbol = str(payload.get("assetSymbol", "")).strip().upper()
    market = str(payload.get("market", "")).strip()
    direction = str(payload.get("direction", "")).strip().capitalize()
    confidence_label = str(payload.get("confidenceLabel", "")).strip() or "Core"
    session_label = str(payload.get("sessionLabel", "")).strip() or "Session"
    thesis = str(payload.get("thesis", "")).strip()
    status = str(payload.get("status", "published")).strip().lower()

    try:
        tier_number = int(payload.get("tierNumber", 0))
        entry_price = float(payload.get("entryPrice", 0))
        target_price = float(payload.get("targetPrice", 0))
        stop_price = float(payload.get("stopPrice", 0))
        timer_minutes = normalize_signal_timer_minutes(payload.get("timerMinutes", DEFAULT_SIGNAL_TIMER_MINUTES))
    except (TypeError, ValueError):
        return None, (jsonify({"ok": False, "message": "Tier and prices must be valid numbers."}), 400)

    signal_time_utc = normalize_signal_time_utc(payload.get("signalTimeUtc"), session_label, tier_number)

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", signal_day):
        return None, (jsonify({"ok": False, "message": "Use day format YYYY-MM-DD."}), 400)
    if tier_number < TIER_NUMBER_MIN or tier_number > TIER_NUMBER_MAX:
        return None, (jsonify({"ok": False, "message": f"Tier number must be between {TIER_NUMBER_MIN} and {TIER_NUMBER_MAX}."}), 400)
    if direction not in {"Long", "Short"}:
        return None, (jsonify({"ok": False, "message": "Direction must be Long or Short."}), 400)
    if status not in {"draft", "published", "open", "archived", "cancelled"}:
        return None, (jsonify({"ok": False, "message": "Unsupported signal status."}), 400)
    if not asset_symbol or not market or not thesis:
        return None, (jsonify({"ok": False, "message": "Asset, market and thesis are required."}), 400)

    return {
        "signal_day": signal_day,
        "tier_number": tier_number,
        "asset_symbol": asset_symbol,
        "market": market,
        "direction": direction,
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_price": stop_price,
        "confidence_label": confidence_label,
        "session_label": session_label,
        "thesis": thesis,
        "signal_time_utc": signal_time_utc,
        "timer_minutes": timer_minutes,
        "status": status,
    }, None


@app.post("/api/admin/signals")
def admin_create_signal() -> tuple[Any, int]:
    _, error_response = require_admin_api()
    if error_response is not None:
        return error_response

    payload = request.get_json(silent=True) or {}
    parsed_payload, payload_error = parse_admin_signal_payload(payload)
    if payload_error is not None:
        return payload_error

    is_free = 1 if parsed_payload.get("tier_number") == 1 else int(payload.get("isFree", 0))

    with get_db() as conn:
        conn.execute(
            "INSERT INTO daily_signals (signal_day, tier_number, asset_symbol, market, direction, entry_price, target_price, stop_price, confidence_label, session_label, thesis, signal_time_utc, timer_minutes, base_currency_code, status, is_free) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                parsed_payload["signal_day"],
                parsed_payload["tier_number"],
                parsed_payload["asset_symbol"],
                parsed_payload["market"],
                parsed_payload["direction"],
                parsed_payload["entry_price"],
                parsed_payload["target_price"],
                parsed_payload["stop_price"],
                parsed_payload["confidence_label"],
                parsed_payload["session_label"],
                parsed_payload["thesis"],
                parsed_payload["signal_time_utc"],
                parsed_payload["timer_minutes"],
                "USD",
                parsed_payload["status"],
                is_free,
            ),
        )

    return jsonify({"ok": True, "message": "Signal created."}), 201


@app.put("/api/admin/signals/<int:signal_id>")
def admin_update_signal(signal_id: int) -> tuple[Any, int]:
    _, error_response = require_admin_api()
    if error_response is not None:
        return error_response

    payload = request.get_json(silent=True) or {}
    parsed_payload, payload_error = parse_admin_signal_payload(payload)
    if payload_error is not None:
        return payload_error

    with get_db() as conn:
        row = conn.execute("SELECT id FROM daily_signals WHERE id = ?", (signal_id,)).fetchone()
        if row is None:
            return jsonify({"ok": False, "message": "Signal not found."}), 404

        conn.execute(
            """
            UPDATE daily_signals
            SET signal_day = ?, tier_number = ?, asset_symbol = ?, market = ?, direction = ?,
                entry_price = ?, target_price = ?, stop_price = ?, confidence_label = ?,
                session_label = ?, thesis = ?, signal_time_utc = ?, timer_minutes = ?, status = ?
            WHERE id = ?
            """,
            (
                parsed_payload["signal_day"],
                parsed_payload["tier_number"],
                parsed_payload["asset_symbol"],
                parsed_payload["market"],
                parsed_payload["direction"],
                parsed_payload["entry_price"],
                parsed_payload["target_price"],
                parsed_payload["stop_price"],
                parsed_payload["confidence_label"],
                parsed_payload["session_label"],
                parsed_payload["thesis"],
                parsed_payload["signal_time_utc"],
                parsed_payload["timer_minutes"],
                parsed_payload["status"],
                signal_id,
            ),
        )

    return jsonify({"ok": True, "message": "Signal updated."}), 200


@app.patch("/api/admin/signals/<int:signal_id>/status")
def admin_update_signal_status(signal_id: int) -> tuple[Any, int]:
    _, error_response = require_admin_api()
    if error_response is not None:
        return error_response

    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status", "")).strip().lower()
    if status not in {"draft", "published", "open", "archived", "cancelled"}:
        return jsonify({"ok": False, "message": "Unsupported signal status."}), 400

    with get_db() as conn:
        row = conn.execute("SELECT id FROM daily_signals WHERE id = ?", (signal_id,)).fetchone()
        if row is None:
            return jsonify({"ok": False, "message": "Signal not found."}), 404
        conn.execute("UPDATE daily_signals SET status = ? WHERE id = ?", (status, signal_id))

    return jsonify({"ok": True, "message": "Signal status updated."}), 200


@app.delete("/api/admin/signals/<int:signal_id>")
def admin_delete_signal(signal_id: int) -> tuple[Any, int]:
    _, error_response = require_admin_api()
    if error_response is not None:
        return error_response

    with get_db() as conn:
        row = conn.execute("SELECT id FROM daily_signals WHERE id = ?", (signal_id,)).fetchone()
        if row is None:
            return jsonify({"ok": False, "message": "Signal not found."}), 404
        conn.execute("DELETE FROM daily_signals WHERE id = ?", (signal_id,))

    return jsonify({"ok": True, "message": "Signal deleted."}), 200


@app.get("/api/session")
def get_session_state() -> tuple[Any, int]:
    current_user = g.current_account
    if current_user is not None:
        with get_db() as conn:
            sync_discord_verification_for_account(
                conn,
                int(current_user["id"]),
                decrypt_value(current_user["discord_username_enc"]) or current_user["discord_username"],
            )
            current_user = fetch_account_by_id(conn, int(current_user["id"]))

    currency_choice = resolve_currency_preference(current_user)
    return jsonify(
        {
            "ok": True,
            "user": serialize_account(current_user),
            "currency": currency_choice,
            "currencies": build_currency_catalog(),
            "exchangeRates": get_exchange_rates(),
            "pricingMatrixGbp": PRICING_MATRIX_GBP,
            "promoPlansGbp": PROMO_PLANS_GBP,
            "discordTagLabels": DISCORD_TAG_LABELS,
            "vatRate": CHECKOUT_VAT_RATE,
        }
    ), 200


@app.post("/api/accounts")
def create_account() -> tuple[Any, int]:
    if is_rate_limited(_client_key()):
        log_security_event(None, "account_create", "rate_limited")
        return jsonify({"ok": False, "message": "Too many account attempts. Please wait a few minutes."}), 429

    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip().lower()
    full_name = str(payload.get("fullName", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    remember_me = bool(payload.get("rememberMe", False))
    zipcode = str(payload.get("zipcode", "")).strip()
    address = str(payload.get("address", "")).strip()
    discord_username = normalize_discord_username(str(payload.get("discordUsername", "")))
    consent_to_data_storage = bool(payload.get("consentToDataStorage", False))

    if not username or not full_name or not email or not password or not zipcode or not address:
        log_security_event(None, "account_create", "validation_failed")
        return jsonify({"ok": False, "message": "All fields are required."}), 400

    if not consent_to_data_storage:
        log_security_event(None, "account_create", "consent_missing")
        return jsonify({"ok": False, "message": "You must consent to Vault Signals storing your submitted account data before creating an account."}), 400

    if len(password) < 8:
        log_security_event(None, "account_create", "validation_failed")
        return jsonify({"ok": False, "message": "Password must be at least 8 characters."}), 400

    length_error = validate_field_lengths(
        {
            "username": username,
            "full_name": full_name,
            "email": email,
            "zipcode": zipcode,
            "address": address,
            "discord_username": discord_username,
        }
    )
    if length_error:
        log_security_event(None, "account_create", "validation_failed")
        return jsonify({"ok": False, "message": length_error}), 400

    email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    if not re.match(email_regex, email):
        log_security_event(None, "account_create", "validation_failed")
        return jsonify({"ok": False, "message": "Enter a valid email address."}), 400

    password_hash = generate_password_hash(password)
    is_admin = 1 if is_auto_admin_email(email) else 0
    verified = 1

    try:
        with get_db() as conn:
            existing = conn.execute("SELECT id FROM accounts WHERE username = ? OR email = ?", (username, email)).fetchone()
            if existing:
                log_security_event(existing["id"], "account_create", "conflict")
                return jsonify({"ok": False, "message": "Username or email already in use."}), 409

            conn.execute(
                "INSERT INTO accounts (username, full_name, full_name_enc, email, password_hash, zipcode, zipcode_enc, address, address_enc, discord_username, discord_username_enc, discord_tag, verified, is_admin, data_consent_accepted, data_consent_accepted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (
                    username,
                    full_name,
                    encrypt_value(full_name),
                    email,
                    password_hash,
                    zipcode,
                    encrypt_value(zipcode),
                    address,
                    encrypt_value(address),
                    discord_username or None,
                    encrypt_value(discord_username) if discord_username else None,
                    None,
                    verified,
                    is_admin,
                    1,
                ),
            )

            created_account = conn.execute("SELECT id FROM accounts WHERE email = ?", (email,)).fetchone()
            created_account_id: int | None = None
            if created_account:
                created_account_id = int(created_account["id"])
                sync_discord_verification_for_account(conn, created_account_id, discord_username)
                ensure_community_profile(conn, created_account_id, username)
                conn.execute(
                    "INSERT INTO billing_profiles (account_id, updated_at) VALUES (?, CURRENT_TIMESTAMP) ON CONFLICT(account_id) DO NOTHING",
                    (created_account_id,),
                )
                log_security_event(created_account_id, "account_create", "success")

    except sqlite3.IntegrityError:
        log_security_event(None, "account_create", "conflict")
        return jsonify({"ok": False, "message": "Username or email already in use."}), 409

    if created_account_id is None:
        return jsonify({"ok": False, "message": "Account was created but could not be loaded. Please log in."}), 500

    with get_db() as conn:
        created_user = fetch_account_by_id(conn, created_account_id)

    if created_user is None:
        return jsonify({"ok": False, "message": "Account was created but could not be loaded. Please log in."}), 500

    message = "Admin account created. You are now logged in." if is_admin else "Account created. You are now logged in and can buy signal tiers when you are ready."
    response = jsonify(
        {
            "ok": True,
            "message": message,
            "user": serialize_account(created_user),
            "currency": resolve_currency_preference(created_user),
        }
    )
    return attach_auth_state(response, created_account_id, remember_me), 201


@app.post("/api/login")
def login() -> tuple[Any, int]:
    if is_rate_limited(_client_key()):
        log_security_event(None, "login", "rate_limited")
        return jsonify({"ok": False, "message": "Too many login attempts. Please wait a few minutes."}), 429

    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    remember_me = bool(payload.get("rememberMe", False))

    if not email or not password:
        log_security_event(None, "login", "validation_failed")
        return jsonify({"ok": False, "message": "Email and password are required."}), 400

    with get_db() as conn:
        auth_row = conn.execute("SELECT id, password_hash FROM accounts WHERE email = ?", (email,)).fetchone()

        if auth_row is None or not check_password_hash(auth_row["password_hash"], password):
            log_security_event(auth_row["id"] if auth_row else None, "login", "failed")
            return jsonify({"ok": False, "message": "Invalid email or password."}), 401

        user = fetch_account_by_id(conn, int(auth_row["id"]))
        if user is not None:
            sync_discord_verification_for_account(
                conn,
                int(user["id"]),
                decrypt_value(user["discord_username_enc"]) or user["discord_username"],
            )
            user = fetch_account_by_id(conn, int(user["id"]))

    if user is None:
        return jsonify({"ok": False, "message": "Invalid email or password."}), 401

    log_security_event(user["id"], "login", "success")

    response = jsonify(
        {
            "ok": True,
            "message": "Login successful.",
            "user": serialize_account(user),
            "currency": resolve_currency_preference(user),
        }
    )
    return attach_auth_state(response, int(user["id"]), remember_me), 200


@app.post("/api/client-login")
def client_login() -> tuple[Any, int]:
    if is_rate_limited(_client_key()):
        log_security_event(None, "client_login", "rate_limited")
        return jsonify({"ok": False, "allowed": False, "message": "Too many login attempts. Please wait a few minutes."}), 429

    payload = request.get_json(silent=True) or {}
    username_or_email = str(payload.get("username", "")).strip().lower()
    password = str(payload.get("password", ""))
    remember_me = bool(payload.get("rememberMe", True))

    if not username_or_email or not password:
        log_security_event(None, "client_login", "validation_failed")
        return jsonify({"ok": False, "allowed": False, "message": "Username and password are required."}), 400

    with get_db() as conn:
        auth_row = conn.execute(
            "SELECT id, password_hash FROM accounts WHERE lower(username) = ? OR lower(email) = ? LIMIT 1",
            (username_or_email, username_or_email),
        ).fetchone()

        if auth_row is None or not check_password_hash(auth_row["password_hash"], password):
            log_security_event(auth_row["id"] if auth_row else None, "client_login", "failed")
            return jsonify({"ok": False, "allowed": False, "message": "Invalid username/email or password."}), 401

        user = fetch_account_by_id(conn, int(auth_row["id"]))
        if user is not None:
            sync_discord_verification_for_account(
                conn,
                int(user["id"]),
                decrypt_value(user["discord_username_enc"]) or user["discord_username"],
            )
            user = fetch_account_by_id(conn, int(user["id"]))

    if user is None:
        return jsonify({"ok": False, "allowed": False, "message": "Login failed."}), 401

    log_security_event(user["id"], "client_login", "success")
    response = jsonify(
        {
            "ok": True,
            "allowed": True,
            "message": "Client login successful.",
            "user": serialize_account(user),
            "currency": resolve_currency_preference(user),
        }
    )
    return attach_auth_state(response, int(user["id"]), remember_me), 200


@app.post("/api/auth/resend-verification")
def resend_verification_email() -> tuple[Any, int]:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    if not email:
        return jsonify({"ok": False, "message": "Email is required."}), 400

    email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    if not re.match(email_regex, email):
        return jsonify({"ok": False, "message": "Enter a valid email address."}), 400

    with get_db() as conn:
        account = conn.execute("SELECT id FROM accounts WHERE email = ?", (email,)).fetchone()
        if account is None:
            return jsonify({"ok": False, "message": "Account not found for this email."}), 404

    return jsonify({"ok": True, "message": "Account access is already enabled. Sign in with your email and password to continue."}), 200


@app.post("/api/auth/change-unverified-email")
def change_unverified_email() -> tuple[Any, int]:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    new_email = str(payload.get("newEmail", "")).strip().lower()

    if not email or not password or not new_email:
        return jsonify({"ok": False, "message": "Email, password and new email are required."}), 400

    email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    if not re.match(email_regex, new_email):
        return jsonify({"ok": False, "message": "Enter a valid new email address."}), 400

    with get_db() as conn:
        account = conn.execute("SELECT id, password_hash FROM accounts WHERE email = ?", (email,)).fetchone()
        if account is None or not check_password_hash(account["password_hash"], password):
            return jsonify({"ok": False, "message": "Invalid email or password."}), 401

        email_conflict = conn.execute("SELECT id FROM accounts WHERE email = ? AND id != ?", (new_email, int(account["id"]))).fetchone()
        if email_conflict is not None:
            return jsonify({"ok": False, "message": "New email is already in use."}), 409

        conn.execute(
            """
            UPDATE accounts
            SET email = ?, verified = 1, verification_token = NULL, verification_token_hash = NULL, verification_token_created_at = NULL
            WHERE id = ?
            """,
            (new_email, int(account["id"])),
        )

    return jsonify({
        "ok": True,
        "message": "Email updated. You can now sign in with the new email address.",
        "newEmail": new_email,
    }), 200


@app.post("/api/logout")
def logout() -> tuple[Any, int]:
    raw_remember_token = request.cookies.get(REMEMBER_COOKIE_NAME)
    if raw_remember_token:
        with get_db() as conn:
            conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (hash_token(raw_remember_token),))
    response = jsonify({"ok": True, "message": "You have been logged out."})
    return clear_auth_state(response), 200


@app.post("/api/preferences/currency")
def update_currency_preference() -> tuple[Any, int]:
    payload = request.get_json(silent=True) or {}
    currency_code = normalize_currency_code(str(payload.get("currencyCode", "")))

    if currency_code not in SUPPORTED_CURRENCIES:
        return jsonify({"ok": False, "message": "Unsupported currency."}), 400

    response = jsonify(
        {
            "ok": True,
            "message": "Currency preference updated.",
            "currency": build_currency_choice_payload(currency_code, "account" if g.current_account else "device"),
            "exchangeRates": get_exchange_rates(),
        }
    )
    set_currency_cookie(response, currency_code)

    if g.current_account is not None:
        with get_db() as conn:
            conn.execute("UPDATE accounts SET preferred_currency_code = ? WHERE id = ?", (currency_code, int(g.current_account["id"])))

    return response, 200


@app.post("/api/account/security")
def update_account_security() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    payload = request.get_json(silent=True) or {}
    current_password = str(payload.get("currentPassword", ""))
    new_password = str(payload.get("newPassword", ""))
    new_email = str(payload.get("newEmail", "")).strip().lower()

    if not current_password:
        return jsonify({"ok": False, "message": "Current password is required."}), 400

    account_id = int(g.current_account["id"])

    with get_db() as conn:
        account = conn.execute("SELECT id, email, password_hash FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if account is None or not check_password_hash(account["password_hash"], current_password):
            log_security_event(account_id, "account_security_update", "invalid_password")
            return jsonify({"ok": False, "message": "Current password is incorrect."}), 401

        updates: list[str] = []
        params: list[Any] = []

        if new_email and new_email != str(account["email"]).strip().lower():
            email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
            if not re.match(email_regex, new_email):
                return jsonify({"ok": False, "message": "Enter a valid email address."}), 400
            email_conflict = conn.execute("SELECT id FROM accounts WHERE email = ? AND id != ?", (new_email, account_id)).fetchone()
            if email_conflict is not None:
                return jsonify({"ok": False, "message": "Email is already in use."}), 409
            updates.append("email = ?")
            params.append(new_email)

        if new_password:
            if len(new_password) < 8:
                return jsonify({"ok": False, "message": "New password must be at least 8 characters."}), 400
            updates.append("password_hash = ?")
            params.append(generate_password_hash(new_password))

        if not updates:
            return jsonify({"ok": False, "message": "No account changes were provided."}), 400

        params.append(account_id)
        conn.execute(f"UPDATE accounts SET {', '.join(updates)} WHERE id = ?", tuple(params))
        log_security_event(account_id, "account_security_update", "success")

    return jsonify({"ok": True, "message": "Account security settings updated."}), 200


@app.get("/api/account/profile")
def get_account_profile() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    account_id = int(g.current_account["id"])
    with get_db() as conn:
        ensure_community_profile(conn, account_id, str(g.current_account["username"] or "member"))
        row = fetch_account_profile_by_id(conn, account_id)
        badges = build_badges_for_account(conn, account_id, include_preview=BADGE_PREVIEW_ENABLED)

    return jsonify({"ok": True, "profile": serialize_account_profile(row), "badges": badges}), 200


@app.patch("/api/account/profile")
def update_account_profile() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    payload = request.get_json(silent=True) or {}
    full_name = str(payload.get("fullName", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    phone_number = normalize_phone_number(str(payload.get("phoneNumber", "")))
    zipcode = str(payload.get("zipcode", "")).strip()
    address = str(payload.get("address", "")).strip()
    avatar_url = str(payload.get("avatarUrl", "")).strip()
    current_password = str(payload.get("currentPassword", ""))
    new_password = str(payload.get("newPassword", ""))

    if not full_name or not email or not zipcode or not address:
        return jsonify({"ok": False, "message": "Name, email, postcode, and address are required."}), 400
    if len(full_name) > MAX_LENGTHS["full_name"]:
        return jsonify({"ok": False, "message": "Full name is too long."}), 400
    if len(email) > MAX_LENGTHS["email"]:
        return jsonify({"ok": False, "message": "Email is too long."}), 400
    if len(zipcode) > MAX_LENGTHS["zipcode"]:
        return jsonify({"ok": False, "message": "Postcode is too long."}), 400
    if len(address) > MAX_LENGTHS["address"]:
        return jsonify({"ok": False, "message": "Address is too long."}), 400
    if avatar_url and len(avatar_url) > 500:
        return jsonify({"ok": False, "message": "Avatar image link is too long."}), 400
    if avatar_url and not (avatar_url.startswith("/") or re.match(r"^https?://", avatar_url, re.IGNORECASE)):
        return jsonify({"ok": False, "message": "Avatar image link must start with https://, http://, or /."}), 400

    email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    if not re.match(email_regex, email):
        return jsonify({"ok": False, "message": "Enter a valid email address."}), 400
    if new_password and len(new_password) < 8:
        return jsonify({"ok": False, "message": "New password must be at least 8 characters."}), 400

    account_id = int(g.current_account["id"])
    with get_db() as conn:
        ensure_community_profile(conn, account_id, str(g.current_account["username"] or "member"))
        existing_profile = fetch_account_profile_by_id(conn, account_id)
        if existing_profile is None:
            return jsonify({"ok": False, "message": "Account not found."}), 404

        current_email = str(existing_profile["email"] or "").strip().lower()
        email_changed = email != current_email
        password_changed = bool(new_password)

        if email_changed or password_changed:
            account_security = conn.execute("SELECT password_hash FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if not current_password:
                return jsonify({"ok": False, "message": "Current password is required to change email or password."}), 400
            if account_security is None or not check_password_hash(account_security["password_hash"], current_password):
                log_security_event(account_id, "account_profile_update", "invalid_password")
                return jsonify({"ok": False, "message": "Current password is incorrect."}), 401

        if email_changed:
            email_conflict = conn.execute("SELECT id FROM accounts WHERE email = ? AND id != ?", (email, account_id)).fetchone()
            if email_conflict is not None:
                return jsonify({"ok": False, "message": "Email is already in use."}), 409

        next_password_hash = generate_password_hash(new_password) if password_changed else None
        next_avatar_url = avatar_url or COMMUNITY_DEFAULT_AVATAR

        conn.execute(
            """
            UPDATE accounts
            SET full_name = ?,
                full_name_enc = ?,
                email = ?,
                phone_number = ?,
                phone_number_enc = ?,
                zipcode = ?,
                zipcode_enc = ?,
                address = ?,
                address_enc = ?,
                password_hash = COALESCE(?, password_hash)
            WHERE id = ?
            """,
            (
                full_name,
                encrypt_value(full_name),
                email,
                phone_number or None,
                encrypt_value(phone_number) if phone_number else None,
                zipcode,
                encrypt_value(zipcode),
                address,
                encrypt_value(address),
                next_password_hash,
                account_id,
            ),
        )
        conn.execute(
            "UPDATE community_profiles SET avatar_url = ?, updated_at = CURRENT_TIMESTAMP WHERE account_id = ?",
            (next_avatar_url, account_id),
        )

        if email_changed or password_changed:
            log_security_event(account_id, "account_profile_update", "success")

        updated_profile = fetch_account_profile_by_id(conn, account_id)
        badges = build_badges_for_account(conn, account_id, include_preview=BADGE_PREVIEW_ENABLED)

    return jsonify({"ok": True, "message": "Account details updated.", "profile": serialize_account_profile(updated_profile), "badges": badges}), 200


@app.post("/api/account/discord")
def update_account_discord() -> tuple[Any, int]:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    discord_username = normalize_discord_username(str(payload.get("discordUsername", "")))

    if not email or not discord_username:
        log_security_event(None, "discord_update", "validation_failed")
        return jsonify({"ok": False, "message": "Email and Discord username are required."}), 400

    with get_db() as conn:
        user = conn.execute("SELECT id FROM accounts WHERE email = ?", (email,)).fetchone()
        if user is None:
            log_security_event(None, "discord_update", "not_found")
            return jsonify({"ok": False, "message": "Account not found."}), 404

        verification_status, verified_tag = sync_discord_verification_for_account(conn, int(user["id"]), discord_username)

    log_security_event(user["id"], "discord_update", "success")

    return jsonify(
        {
            "ok": True,
            "message": "Discord username saved. Tag level is assigned only after system verification.",
            "discordUsername": discord_username,
            "discordTag": verified_tag,
            "discordVerificationStatus": verification_status,
        }
    ), 200


def build_verification_url(token: str) -> str:
    return f"{APP_BASE_URL}/api/verify/{token}"


def get_paypal_access_token() -> str | None:
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        return None

    try:
        response = requests.post(
            f"{PAYPAL_API_BASE_URL}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
            headers={"Accept": "application/json", "Accept-Language": "en_US"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            return None
        return (response.json() or {}).get("access_token")
    except requests.RequestException:
        return None


def verify_paypal_webhook_signature(event_body: dict[str, Any]) -> bool:
    if PAYPAL_ALLOW_UNVERIFIED_WEBHOOKS and IS_DEV_ENV:
        return True

    if not PAYPAL_WEBHOOK_ID:
        logger.warning("PAYPAL_WEBHOOK_ID is not configured; rejecting webhook in non-dev mode.")
        return False

    transmission_id = request.headers.get("PAYPAL-TRANSMISSION-ID", "")
    transmission_time = request.headers.get("PAYPAL-TRANSMISSION-TIME", "")
    cert_url = request.headers.get("PAYPAL-CERT-URL", "")
    auth_algo = request.headers.get("PAYPAL-AUTH-ALGO", "")
    transmission_sig = request.headers.get("PAYPAL-TRANSMISSION-SIG", "")

    if not all([transmission_id, transmission_time, cert_url, auth_algo, transmission_sig]):
        return False

    access_token = get_paypal_access_token()
    if not access_token:
        return False

    payload = {
        "transmission_id": transmission_id,
        "transmission_time": transmission_time,
        "cert_url": cert_url,
        "auth_algo": auth_algo,
        "transmission_sig": transmission_sig,
        "webhook_id": PAYPAL_WEBHOOK_ID,
        "webhook_event": event_body,
    }
    try:
        verify_response = requests.post(
            f"{PAYPAL_API_BASE_URL}/v1/notifications/verify-webhook-signature",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if verify_response.status_code != 200:
            return False
        verification_status = (verify_response.json() or {}).get("verification_status", "")
        return verification_status == "SUCCESS"
    except requests.RequestException:
        return False


def send_verification_email(email: str, token: str) -> bool:
    confirm_url = build_verification_url(token)
    subject = "VaultSignalsAI account verification"
    body = f"Please verify your account by visiting: {confirm_url}\n\nIf this was not you, ignore this message."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = email
    msg.set_content(body)
    return send_smtp_message(msg)


def verify_email_token(token: str) -> tuple[dict[str, Any], int]:
    token_hash = hash_token(token)
    with get_db() as conn:
        account = conn.execute("SELECT id, verified, verification_token_created_at FROM accounts WHERE verification_token_hash = ?", (token_hash,)).fetchone()
        if not account:
            log_security_event(None, "verify_email", "invalid_token")
            return {"ok": False, "message": "Invalid or expired verification link."}, 404

        if is_verification_token_expired(account["verification_token_created_at"]):
            conn.execute("UPDATE accounts SET verification_token = NULL, verification_token_hash = NULL, verification_token_created_at = NULL WHERE id = ?", (account["id"],))
            log_security_event(account["id"], "verify_email", "expired")
            return {"ok": False, "message": "Verification link expired. Please sign up again."}, 410

        if account["verified"]:
            log_security_event(account["id"], "verify_email", "already_verified")
            return {"ok": True, "message": "Account is already verified."}, 200

        conn.execute("UPDATE accounts SET verified = 1, verification_token = NULL, verification_token_hash = NULL, verification_token_created_at = NULL WHERE id = ?", (account["id"],))
        log_security_event(account["id"], "verify_email", "success")

    return {"ok": True, "message": "Email verified successfully."}, 200


@app.get("/api/verify/<token>")
def verify_email(token: str) -> tuple[Any, int]:
    result, status_code = verify_email_token(token)
    return jsonify(result), status_code


@app.post("/api/auth/verify-token")
def verify_email_by_token_input() -> tuple[Any, int]:
    payload = request.get_json(silent=True) or {}
    raw_token = str(payload.get("token", "")).strip()
    if not raw_token:
        return jsonify({"ok": False, "message": "Verification token is required."}), 400

    if "/api/verify/" in raw_token:
        raw_token = raw_token.rsplit("/api/verify/", 1)[-1]
    parsed_token = raw_token.split("?", 1)[0].split("#", 1)[0].strip()
    if not re.fullmatch(r"[a-fA-F0-9]{32}", parsed_token):
        return jsonify({"ok": False, "message": "Token format is invalid. Paste only the token or full verify link."}), 400

    result, status_code = verify_email_token(parsed_token)
    return jsonify(result), status_code


@app.post("/api/purchase")
def purchase() -> tuple[Any, int]:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    tier_name = str(payload.get("tierName", "")).strip()
    tier_number_raw = payload.get("tierNumber")
    tag_key = normalize_discord_tag(str(payload.get("discordTag", "")))
    billing_cycle = str(payload.get("billingCycle", "")).strip().lower()
    billing_method = str(payload.get("billingMethod", "")).strip().lower()
    discord_username = str(payload.get("discordUsername", "")).strip()
    billing_name = str(payload.get("billingName", "")).strip()
    billing_company = str(payload.get("billingCompany", "")).strip()
    billing_address = str(payload.get("billingAddress", "")).strip()
    billing_zip = str(payload.get("billingZip", "")).strip()
    billing_country = str(payload.get("billingCountry", "")).strip()
    terms_agreed = bool(payload.get("termsAgree", False))

    length_error = validate_field_lengths(
        {
            "email": email,
            "discord_username": discord_username,
            "discord_tag": tag_key,
            "billing_name": billing_name,
            "billing_company": billing_company,
            "billing_address": billing_address,
            "billing_zip": billing_zip,
            "billing_country": billing_country,
        }
    )
    if length_error:
        log_security_event(None, "purchase", "validation_failed")
        return jsonify({"ok": False, "message": length_error}), 400

    if not email:
        log_security_event(None, "purchase", "validation_failed")
        return jsonify({"ok": False, "message": "Email and tier name are required."}), 400

    if tier_number_raw in (None, ""):
        tier_number = None
    else:
        try:
            tier_number = int(tier_number_raw)
        except (TypeError, ValueError):
            log_security_event(None, "purchase", "validation_failed")
            return jsonify({"ok": False, "message": "Tier must be a number from 1 to 6."}), 400

    with get_db() as conn:
        user = fetch_account_by_id(conn, int(g.current_account["id"])) if g.current_account is not None else None
        if user is None and email:
            user = conn.execute(
                "SELECT id, username, full_name, full_name_enc, email, discord_username, discord_username_enc, discord_tag, verified, preferred_currency_code FROM accounts WHERE email = ?",
                (email,),
            ).fetchone()
        if user is None:
            log_security_event(None, "purchase", "account_missing")
            return jsonify({"ok": False, "message": "You must create an account before buying a tier."}), 403

        ensure_community_profile(conn, int(user["id"]), str(user["username"] or "member"))
        resolved_discord_username = discord_username or user["discord_username"]
        # If no Discord tag is present we apply standard pricing (Final tag = no discount).
        resolved_tag = tag_key or user["discord_tag"] or "final"

        if not tier_number and tier_name:
            tier_match = re.search(r"(\d+)", tier_name)
            if tier_match:
                tier_number = int(tier_match.group(1))

        if tier_number and billing_cycle:
            if resolved_tag not in DISCORD_TAG_LEVELS:
                log_security_event(user["id"], "purchase", "validation_failed")
                return jsonify({"ok": False, "message": "Discord tag is invalid for billing."}), 400

            price = get_price_for_selection(tier_number, resolved_tag, billing_cycle)
            if price is None:
                log_security_event(user["id"], "purchase", "validation_failed")
                return jsonify({"ok": False, "message": "Selected pricing combination is not available."}), 400

            if billing_cycle == "lifetime" and tier_number < 4:
                log_security_event(user["id"], "purchase", "validation_failed")
                return jsonify({"ok": False, "message": "Lifetime is available only from Tier 4 upward."}), 400

            if billing_method not in {"creditcard", "ideal", "paypal"}:
                log_security_event(user["id"], "purchase", "validation_failed")
                return jsonify({"ok": False, "message": "Select a valid payment method."}), 400

            if not terms_agreed:
                log_security_event(user["id"], "purchase", "validation_failed")
                return jsonify({"ok": False, "message": "You must agree to the terms and conditions."}), 400

            if not billing_name or not billing_address or not billing_zip or not billing_country:
                log_security_event(user["id"], "purchase", "validation_failed")
                return jsonify({"ok": False, "message": "Billing name and full address are required."}), 400

            resolved_tier_name = f"Tier {tier_number}"
            plan_name = DISCORD_TAG_LABELS[resolved_tag]
            signals_per_day = tier_number

            conn.execute(
                "INSERT INTO purchases (account_id, tier_name, tier_number, plan_name, billing_cycle, billing_method, price_gbp, signals_per_day, billing_name, billing_company, billing_address, billing_zip, billing_country, billing_name_enc, billing_company_enc, billing_address_enc, billing_zip_enc, billing_country_enc, discord_username, discord_tag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user["id"],
                    resolved_tier_name,
                    tier_number,
                    plan_name,
                    billing_cycle,
                    billing_method,
                    price,
                    signals_per_day,
                    billing_name,
                    billing_company or None,
                    billing_address,
                    billing_zip,
                    billing_country,
                    encrypt_value(billing_name),
                    encrypt_value(billing_company) if billing_company else None,
                    encrypt_value(billing_address),
                    encrypt_value(billing_zip),
                    encrypt_value(billing_country),
                    resolved_discord_username,
                    resolved_tag,
                ),
            )

            purchase_row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
            purchase_id = int(purchase_row["id"]) if purchase_row else None
            payment_url = get_payment_forward_url(billing_method)

            conn.execute(
                "INSERT INTO billing_profiles (account_id, billing_name_enc, billing_company_enc, billing_address_enc, billing_zip_enc, billing_country_enc, updated_at) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(account_id) DO UPDATE SET billing_name_enc = excluded.billing_name_enc, billing_company_enc = excluded.billing_company_enc, billing_address_enc = excluded.billing_address_enc, billing_zip_enc = excluded.billing_zip_enc, billing_country_enc = excluded.billing_country_enc, updated_at = CURRENT_TIMESTAMP",
                (
                    user["id"],
                    encrypt_value(billing_name),
                    encrypt_value(billing_company) if billing_company else None,
                    encrypt_value(billing_address),
                    encrypt_value(billing_zip),
                    encrypt_value(billing_country),
                ),
            )

            conn.execute(
                "INSERT INTO billing_transactions (account_id, purchase_id, tier_number, plan_name, billing_cycle, billing_method, price_gbp, payment_url, payment_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user["id"],
                    purchase_id,
                    tier_number,
                    plan_name,
                    billing_cycle,
                    billing_method,
                    price,
                    payment_url,
                    "pending",
                ),
            )
            conn.execute(
                "UPDATE account_balances SET total_invested = total_invested + ?, updated_at = CURRENT_TIMESTAMP WHERE account_id = ?",
                (price, user["id"]),
            )
            conn.execute(
                "INSERT INTO account_performance_snapshots (account_id, period_day, invested_amount, profit_amount) VALUES (?, ?, ?, 0)",
                (user["id"], utc_now().strftime("%Y-%m-%d"), price),
            )
            log_security_event(user["id"], "purchase", "success")

            currency_choice = resolve_currency_preference(user)
            converted_price = convert_currency_amount(price, "GBP", currency_choice["code"])

            return jsonify(
                {
                    "ok": True,
                    "message": f"{resolved_tier_name} ({signals_per_day} signal/day) confirmed at {currency_choice['code']} {converted_price} on {billing_cycle} billing.",
                    "summary": {
                        "tier": tier_number,
                        "signalsPerDay": signals_per_day,
                        "discordTag": plan_name,
                        "billingCycle": billing_cycle,
                        "billingMethod": billing_method,
                        "priceGbp": price,
                        "displayPrice": converted_price,
                        "displayCurrency": currency_choice,
                    },
                    "paymentUrl": payment_url,
                }
            ), 201

        if not tier_name:
            log_security_event(user["id"], "purchase", "validation_failed")
            return jsonify({"ok": False, "message": "Tier name is required for this purchase action."}), 400

        conn.execute(
            "INSERT INTO purchases (account_id, tier_name, discord_username, discord_tag) VALUES (?, ?, ?, ?)",
            (user["id"], tier_name, user["discord_username"], user["discord_tag"]),
        )

    log_security_event(user["id"], "purchase", "success")

    return jsonify({"ok": True, "message": f"{tier_name} has been added to your account."}), 201


@app.get("/api/member/signals")
def member_signals() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Log in to view your purchased signals."}), 401

    currency_choice = resolve_currency_preference(g.current_account)
    with get_db() as conn:
        ensure_daily_signals(conn)
        purchases = conn.execute(
            "SELECT id, tier_name, tier_number, plan_name, billing_cycle, billing_method, price_gbp, signals_per_day, created_at, expires_at, months_active FROM purchases WHERE account_id = ? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) ORDER BY created_at DESC",
            (int(g.current_account["id"]),),
        ).fetchall()

        max_signals = max([int(row["signals_per_day"] or 0) for row in purchases], default=0)
        today = utc_now().strftime("%Y-%m-%d")
        
        # Get FREE signals (available to all logged-in users)
        free_signals = conn.execute(
            "SELECT id, signal_day, tier_number, asset_symbol, market, direction, entry_price, target_price, stop_price, confidence_label, session_label, thesis, signal_time_utc, timer_minutes, base_currency_code, status FROM daily_signals WHERE signal_day = ? AND is_free = 1 AND status IN ('open', 'published') ORDER BY tier_number ASC",
            (today,),
        ).fetchall()
        
        # Get PAID signals (based on user's purchases)
        paid_signal_rows = []
        if max_signals > 0:
            paid_signal_rows = conn.execute(
                "SELECT id, signal_day, tier_number, asset_symbol, market, direction, entry_price, target_price, stop_price, confidence_label, session_label, thesis, signal_time_utc, timer_minutes, base_currency_code, status FROM daily_signals WHERE signal_day = ? AND tier_number <= ? AND is_free = 0 AND status IN ('open', 'published') ORDER BY tier_number ASC",
                (today, max_signals),
            ).fetchall()

    purchase_payload = [
        {
            "id": row["id"],
            "tierName": row["tier_name"],
            "tierNumber": row["tier_number"],
            "planName": row["plan_name"],
            "billingCycle": row["billing_cycle"],
            "billingMethod": row["billing_method"],
            "priceGbp": row["price_gbp"],
            "displayPrice": convert_currency_amount(row["price_gbp"], "GBP", currency_choice["code"]),
            "signalsPerDay": row["signals_per_day"],
            "createdAt": row["created_at"],
            "expiresAt": row["expires_at"],
            "monthsActive": row["months_active"],
        }
        for row in purchases
    ]
    
    # Combine free + paid signals
    all_signal_rows = list(free_signals) + list(paid_signal_rows)
    signal_payload = [serialize_signal_row(row, currency_choice["code"]) for row in all_signal_rows]

    return jsonify(
        {
            "ok": True,
            "currency": currency_choice,
            "member": serialize_account(g.current_account),
            "portfolio": {
                "purchases": purchase_payload,
                "signalsPerDay": max([int(row["signals_per_day"] or 0) for row in purchases], default=0),
                "activeTiers": len(purchases),
            },
            "signals": signal_payload,
            "hasFreeSIgnals": len(free_signals) > 0,
        }
    ), 200


@app.post("/api/member/purchases")
def create_purchase() -> tuple[Any, int]:
    """Create a new signal purchase/subscription."""
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Log in to purchase signals."}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "message": "Provide a valid JSON body."}), 400

    try:
        tier_number = int(data.get("tierNumber", TIER_NUMBER_MIN))
        price_gbp = float(data.get("priceGbp", 0))
        signals_per_day = int(data.get("signalsPerDay", 1))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Tier, price and signals per day must be valid numbers."}), 400

    tier_name = str(data.get("tierName", f"Tier {tier_number}")).strip() or f"Tier {tier_number}"
    plan_name = str(data.get("planName", DEFAULT_BILLING_CYCLE.title())).strip() or DEFAULT_BILLING_CYCLE.title()
    billing_cycle = str(data.get("billingCycle", DEFAULT_BILLING_CYCLE)).strip().lower() or DEFAULT_BILLING_CYCLE
    billing_method = str(data.get("billingMethod", "paypal")).strip().lower() or "paypal"

    if tier_number < TIER_NUMBER_MIN or tier_number > TIER_NUMBER_MAX:
        return jsonify({"ok": False, "message": f"Tier number must be between {TIER_NUMBER_MIN} and {TIER_NUMBER_MAX}."}), 400
    if price_gbp <= 0:
        return jsonify({"ok": False, "message": "Invalid price."}), 400
    if signals_per_day <= 0:
        return jsonify({"ok": False, "message": "Signals per day must be greater than zero."}), 400
    if billing_cycle not in VALID_BILLING_CYCLES:
        return jsonify({"ok": False, "message": "Unsupported billing cycle."}), 400
    if billing_method not in PAYMENT_LINKS:
        return jsonify({"ok": False, "message": "Unsupported billing method."}), 400

    expiry_date = None if billing_cycle == "lifetime" else utc_now() + timedelta(days=BILLING_CYCLE_DAYS.get(billing_cycle, BILLING_CYCLE_DAYS.get(DEFAULT_BILLING_CYCLE, 30)))
    next_renewal = expiry_date

    account_id = int(g.current_account["id"])
    with get_db() as conn:
        ensure_community_profile(conn, account_id, str(g.current_account["username"] or "member"))

        # Insert purchase
        conn.execute(
            """
            INSERT INTO purchases (account_id, tier_name, tier_number, plan_name, billing_cycle, billing_method, price_gbp, signals_per_day, created_at, expires_at, months_active, auto_renew, next_renewal_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, 1, 1, ?)
            """,
            (account_id, tier_name, tier_number, plan_name, billing_cycle, billing_method, price_gbp, signals_per_day, format_db_timestamp(expiry_date), format_db_timestamp(next_renewal))
        )
        purchase_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
        
        # Create transaction record
        invoice_number = f"INV-{purchase_id}-{utc_now().strftime('%Y%m%d')}"
        conn.execute(
            """
            INSERT INTO transactions (account_id, purchase_id, transaction_type, amount_gbp, currency_code, status, payment_method, invoice_number, description)
            VALUES (?, ?, 'purchase', ?, 'GBP', 'pending', ?, ?, ?)
            """,
            (account_id, purchase_id, price_gbp, billing_method, invoice_number, f"Purchase {tier_name} - {signals_per_day} signals/day")
        )
        
        # Update or create loyalty record
        loyalty = conn.execute("SELECT * FROM customer_loyalty WHERE account_id = ?", (account_id,)).fetchone()
        if loyalty:
            conn.execute(
                "UPDATE customer_loyalty SET months_active = months_active + 1, total_spent_gbp = total_spent_gbp + ?, last_purchase_at = CURRENT_TIMESTAMP WHERE account_id = ?",
                (price_gbp, account_id)
            )
        else:
            conn.execute(
                "INSERT INTO customer_loyalty (account_id, customer_since, months_active, total_spent_gbp, last_purchase_at) VALUES (?, CURRENT_TIMESTAMP, 1, ?, CURRENT_TIMESTAMP)",
                (account_id, price_gbp)
            )
        
        if expiry_date is not None:
            reminder_date = expiry_date - timedelta(days=RENEWAL_REMINDER_LEAD_DAYS)
            conn.execute(
                """
                INSERT INTO email_queue (account_id, email_type, recipient_email, scheduled_for, status)
                VALUES (?, 'renewal_reminder', ?, ?, 'pending')
                """,
                (account_id, g.current_account["email"], format_db_timestamp(reminder_date))
            )

        conn.execute(
            "UPDATE account_balances SET total_invested = total_invested + ?, updated_at = CURRENT_TIMESTAMP WHERE account_id = ?",
            (price_gbp, account_id),
        )
        conn.execute(
            "INSERT INTO account_performance_snapshots (account_id, period_day, invested_amount, profit_amount) VALUES (?, ?, ?, 0)",
            (account_id, utc_now().strftime("%Y-%m-%d"), price_gbp),
        )
    
    return jsonify({
        "ok": True,
        "message": f"Purchase created! You now have access to {signals_per_day} signal(s) per day.",
        "purchaseId": purchase_id,
        "invoiceNumber": invoice_number,
    }), 201


@app.get("/api/member/purchase-tiers")
def get_purchase_tiers() -> tuple[Any, int]:
    """Get available purchase tiers."""
    tiers = [
        {
            "tierNumber": 1,
            "tierName": "Tier 1",
            "signalsPerDay": 1,
            "priceGbp": 9.99,
            "description": "1 signal per day",
        },
        {
            "tierNumber": 2,
            "tierName": "Tier 2",
            "signalsPerDay": 3,
            "priceGbp": 24.99,
            "description": "3 signals per day",
        },
        {
            "tierNumber": 3,
            "tierName": "Tier 3",
            "signalsPerDay": 5,
            "priceGbp": 49.99,
            "description": "5 signals per day",
        },
    ]
    
    currency_choice = resolve_currency_preference(g.current_account) if g.current_account else {"code": DEFAULT_CURRENCY_CODE, "symbol": "£"}
    
    for tier in tiers:
        tier["displayPrice"] = convert_currency_amount(tier["priceGbp"], "GBP", currency_choice["code"])
    
    return jsonify({
        "ok": True,
        "currency": currency_choice,
        "tiers": tiers,
    }), 200


@app.get("/api/member/dashboard")
def member_dashboard() -> tuple[Any, int]:
    """Get member account dashboard with loyalty info."""
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Log in to view dashboard."}), 401
    
    account_id = int(g.current_account["id"])
    with get_db() as conn:
        loyalty = conn.execute("SELECT * FROM customer_loyalty WHERE account_id = ?", (account_id,)).fetchone()
        badges = build_badges_for_account(conn, account_id, include_preview=BADGE_PREVIEW_ENABLED)
        purchases = conn.execute(
            "SELECT id, tier_name, expires_at, created_at FROM purchases WHERE account_id = ? ORDER BY created_at DESC LIMIT 5",
            (account_id,)
        ).fetchall()
        transactions = conn.execute(
            "SELECT id, amount_gbp, transaction_type, status, created_at, invoice_number FROM transactions WHERE account_id = ? ORDER BY created_at DESC LIMIT 10",
            (account_id,)
        ).fetchall()
    
    # Calculate loyalty level and badges
    months_active = loyalty["months_active"] if loyalty else 0
    total_spent = loyalty["total_spent_gbp"] if loyalty else 0
    
    loyalty_level = "bronze"
    if months_active >= LOYALTY_LEVEL_DIAMOND_MONTHS:
        loyalty_level = "diamond"
    elif months_active >= LOYALTY_LEVEL_GOLD_MONTHS:
        loyalty_level = "gold"
    elif months_active >= LOYALTY_LEVEL_SILVER_MONTHS:
        loyalty_level = "silver"
    
    return jsonify({
        "ok": True,
        "member": serialize_account(g.current_account),
        "loyalty": {
            "monthsActive": months_active,
            "totalSpent": total_spent,
            "loyaltyLevel": loyalty_level,
            "badges": badges,
            "customerSince": loyalty["customer_since"] if loyalty else None,
        },
        "recentPurchases": [
            {
                "id": row["id"],
                "tierName": row["tier_name"],
                "expiresAt": row["expires_at"],
                "createdAt": row["created_at"],
            }
            for row in purchases
        ],
        "transactionHistory": [
            {
                "id": row["id"],
                "amount": row["amount_gbp"],
                "type": row["transaction_type"],
                "status": row["status"],
                "invoiceNumber": row["invoice_number"],
                "createdAt": row["created_at"],
            }
            for row in transactions
        ],
    }), 200


@app.get("/api/community/summary")
def community_summary() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    account_id = int(g.current_account["id"])

    with get_db() as conn:
        ensure_community_profile(conn, account_id, str(g.current_account["username"] or "member"))
        profile = conn.execute(
            "SELECT display_name, display_name_changed_at, avatar_url, bio, privacy_mode, layout_preset, show_on_leaderboard, user_rank, ignore_whisper, email_alerts, market_alerts, renewal_reminders, preferred_billing_method FROM community_profiles WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        balances = conn.execute(
            "SELECT balance_amount, total_invested, total_profit, updated_at FROM account_balances WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        performance = get_account_performance_summary(conn, account_id)
        top_tier = get_active_tier_number(conn, account_id)
        badges = build_badges_for_account(conn, account_id, include_preview=BADGE_PREVIEW_ENABLED)
        connection_counts = get_connection_counts(conn, account_id)
        display_name_policy = build_display_name_policy(profile)
        loyalty = get_loyalty_snapshot(conn, account_id)

    return jsonify(
        {
            "ok": True,
            "account": {
                "username": g.current_account["username"],
                "displayName": profile["display_name"] if profile and profile["display_name"] else g.current_account["username"],
                "avatarUrl": profile["avatar_url"] if profile and profile["avatar_url"] else COMMUNITY_DEFAULT_AVATAR,
                "bio": profile["bio"] if profile else "",
                "privacyMode": profile["privacy_mode"] if profile else "public",
                "layoutPreset": profile["layout_preset"] if profile else "default",
                "showOnLeaderboard": bool(profile["show_on_leaderboard"]) if profile else True,
                "userRank": profile["user_rank"] if profile else "",
                "ignoreWhisper": bool(profile["ignore_whisper"]) if profile else False,
                "emailAlerts": bool(profile["email_alerts"]) if profile else True,
                "marketAlerts": bool(profile["market_alerts"]) if profile else True,
                "renewalReminders": bool(profile["renewal_reminders"]) if profile else True,
                "preferredBillingMethod": profile["preferred_billing_method"] if profile else "paypal",
                "tierBadge": f"Tier {top_tier}" if top_tier > 0 else "No Tier",
                "displayNameCanChange": display_name_policy["canChange"],
                "displayNameChangeAvailableAt": display_name_policy["availableAt"],
                "displayNameCooldownDays": display_name_policy["cooldownDays"],
                "connectionCounts": connection_counts,
                "loyaltyLevel": loyalty["loyaltyLevel"],
            },
            "balance": {
                "current": float((balances["balance_amount"] if balances else COMMUNITY_DEFAULT_BALANCE) or 0),
                "totalInvested": float((balances["total_invested"] if balances else 0) or 0),
                "totalProfit": float((balances["total_profit"] if balances else 0) or 0),
                "updatedAt": balances["updated_at"] if balances else None,
            },
            "summary": performance,
            "badges": badges,
        }
    ), 200


@app.patch("/api/community/settings")
def community_settings_update() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    payload = request.get_json(silent=True) or {}
    display_name = str(payload.get("displayName", "")).strip()
    bio = str(payload.get("bio", "")).strip()
    avatar_url = str(payload.get("avatarUrl", "")).strip() if "avatarUrl" in payload else None
    privacy_mode = str(payload.get("privacyMode", "public")).strip().lower()
    layout_preset = str(payload.get("layoutPreset", "default")).strip().lower()
    show_on_leaderboard = 1 if bool(payload.get("showOnLeaderboard", True)) else 0
    ignore_whisper = 1 if bool(payload.get("ignoreWhisper", False)) else 0
    email_alerts = 1 if bool(payload.get("emailAlerts", True)) else 0
    market_alerts = 1 if bool(payload.get("marketAlerts", True)) else 0
    renewal_reminders = 1 if bool(payload.get("renewalReminders", True)) else 0
    preferred_billing_method = str(payload.get("preferredBillingMethod", "paypal")).strip().lower()

    if privacy_mode not in {"public", "private"}:
        return jsonify({"ok": False, "message": "Invalid privacy mode."}), 400
    if layout_preset not in {"default", "compact", "cards"}:
        return jsonify({"ok": False, "message": "Invalid layout preset."}), 400
    if preferred_billing_method not in {"paypal", "ideal", "creditcard"}:
        return jsonify({"ok": False, "message": "Invalid billing preference."}), 400
    if len(display_name) > MAX_LENGTHS["username"]:
        return jsonify({"ok": False, "message": "Display name is too long."}), 400
    if len(bio) > 400:
        return jsonify({"ok": False, "message": "Bio is too long."}), 400

    # Auto-compute rank from active tier — no manual entry
    account_id = int(g.current_account["id"])
    with get_db() as conn:
        tier_row = conn.execute(
            "SELECT MAX(tier_number) AS top FROM purchases WHERE account_id = ? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)",
            (account_id,),
        ).fetchone()
        top_tier = int(tier_row["top"] or 0) if tier_row and tier_row["top"] else 0
        user_rank = COMMUNITY_RANK_BY_TIER.get(top_tier, f"Tier {top_tier}" if top_tier else "")

        ensure_community_profile(conn, account_id, str(g.current_account["username"] or "member"))
        existing_profile = conn.execute(
            "SELECT display_name, display_name_changed_at, avatar_url FROM community_profiles WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        current_display_name = existing_profile["display_name"] if existing_profile and existing_profile["display_name"] else g.current_account["username"]
        next_display_name = current_display_name
        next_display_name_changed_at = existing_profile["display_name_changed_at"] if existing_profile else None
        if "displayName" in payload:
            requested_display_name = display_name or g.current_account["username"]
            if requested_display_name != current_display_name:
                display_name_policy = build_display_name_policy(existing_profile)
                if not display_name_policy["canChange"]:
                    next_change = display_name_policy["availableAt"] or "later"
                    return jsonify(
                        {
                            "ok": False,
                            "message": f"Display name can be changed once every {DISPLAY_NAME_CHANGE_COOLDOWN_DAYS} days. Next change available after {next_change}.",
                        }
                    ), 429
                next_display_name = requested_display_name
                next_display_name_changed_at = utc_now().strftime("%Y-%m-%d %H:%M:%S")
        next_avatar_url = avatar_url if avatar_url is not None else (existing_profile["avatar_url"] if existing_profile and existing_profile["avatar_url"] else COMMUNITY_DEFAULT_AVATAR)
        conn.execute(
            """
            UPDATE community_profiles
            SET display_name = ?, display_name_changed_at = ?, avatar_url = ?, bio = ?, privacy_mode = ?, layout_preset = ?, show_on_leaderboard = ?, user_rank = ?, ignore_whisper = ?, email_alerts = ?, market_alerts = ?, renewal_reminders = ?, preferred_billing_method = ?, updated_at = CURRENT_TIMESTAMP
            WHERE account_id = ?
            """,
            (
                next_display_name,
                next_display_name_changed_at,
                next_avatar_url,
                bio,
                privacy_mode,
                layout_preset,
                show_on_leaderboard,
                user_rank,
                ignore_whisper,
                email_alerts,
                market_alerts,
                renewal_reminders,
                preferred_billing_method,
                account_id,
            ),
        )

    return jsonify({"ok": True, "message": "Community settings updated."}), 200


@app.get("/api/community/leaderboard")
def community_leaderboard() -> tuple[Any, int]:
    scope = str(request.args.get("scope", "weekly")).strip().lower()
    limit_raw = request.args.get("limit", "20")
    try:
        limit = max(1, min(100, int(limit_raw)))
    except ValueError:
        limit = 20

    with get_db() as conn:
        if scope == "lifetime":
            rows = conn.execute(
                """
                SELECT a.id AS account_id, a.username, cp.display_name, cp.avatar_url, cp.user_rank,
                       ab.total_profit AS score, ab.balance_amount AS balance
                FROM accounts a
                JOIN community_profiles cp ON cp.account_id = a.id
                JOIN account_balances ab ON ab.account_id = a.id
                WHERE cp.privacy_mode = 'public' AND cp.show_on_leaderboard = 1
                ORDER BY score DESC, balance DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            week_start = (utc_now() - timedelta(days=7)).strftime("%Y-%m-%d")
            rows = conn.execute(
                """
                SELECT a.id AS account_id, a.username, cp.display_name, cp.avatar_url, cp.user_rank,
                       COALESCE(SUM(aps.profit_amount), 0) AS score,
                       ab.balance_amount AS balance
                FROM accounts a
                JOIN community_profiles cp ON cp.account_id = a.id
                JOIN account_balances ab ON ab.account_id = a.id
                LEFT JOIN account_performance_snapshots aps ON aps.account_id = a.id AND aps.period_day >= ?
                WHERE cp.privacy_mode = 'public' AND cp.show_on_leaderboard = 1
                GROUP BY a.id, a.username, cp.display_name, cp.avatar_url, cp.user_rank, ab.balance_amount
                ORDER BY score DESC, balance DESC
                LIMIT ?
                """,
                (week_start, limit),
            ).fetchall()

        payload = []
        for idx, row in enumerate(rows, start=1):
            top_tier = get_active_tier_number(conn, int(row["account_id"]))
            payload.append(
                {
                    "rank": idx,
                    "username": row["username"],
                    "displayName": row["display_name"] or row["username"],
                    "avatarUrl": row["avatar_url"] or COMMUNITY_DEFAULT_AVATAR,
                    "userRank": row["user_rank"] or "",
                    "tierBadge": f"Tier {top_tier}" if top_tier > 0 else "No Tier",
                    "score": float(row["score"] or 0),
                    "balance": float(row["balance"] or 0),
                }
            )

    return jsonify({"ok": True, "scope": scope, "leaders": payload}), 200


@app.get("/api/community/account/<username>")
def community_open_account(username: str) -> tuple[Any, int]:
    target_username = str(username or "").strip().lower()
    if not target_username:
        return jsonify({"ok": False, "message": "Username is required."}), 400

    with get_db() as conn:
        target = conn.execute("SELECT id, username FROM accounts WHERE lower(username) = ?", (target_username,)).fetchone()
        if target is None:
            return jsonify({"ok": False, "message": "Account not found."}), 404

        target_id = int(target["id"])
        viewer_id = int(g.current_account["id"]) if g.current_account is not None else None
        viewer_is_admin = g.current_account is not None and is_admin_account(g.current_account)
        snapshot = get_community_member_snapshot(conn, target_id, viewer_id, viewer_is_admin)
        if snapshot is None:
            return jsonify({"ok": False, "message": "Account not found."}), 404

    return jsonify({"ok": True, **snapshot}), 200


@app.get("/api/community/network")
def community_network_list() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    account_id = int(g.current_account["id"])
    viewer_is_admin = is_admin_account(g.current_account)
    with get_db() as conn:
        ensure_community_profile(conn, account_id, str(g.current_account["username"] or "member"))
        latest_previews = get_last_whisper_previews(conn, account_id)
        connection_rows = conn.execute(
            "SELECT target_account_id, created_at FROM community_network WHERE account_id = ? ORDER BY created_at DESC",
            (account_id,),
        ).fetchall()
        incoming_rows = conn.execute(
            "SELECT requester_account_id, created_at FROM community_connection_requests WHERE recipient_account_id = ? AND status = 'pending' ORDER BY created_at DESC",
            (account_id,),
        ).fetchall()
        outgoing_rows = conn.execute(
            "SELECT recipient_account_id, created_at FROM community_connection_requests WHERE requester_account_id = ? AND status = 'pending' ORDER BY created_at DESC",
            (account_id,),
        ).fetchall()
        counts = get_connection_counts(conn, account_id)

        def build_card(target_id: int, created_at: str | None, time_key: str) -> dict[str, Any] | None:
            snapshot = get_community_member_snapshot(conn, int(target_id), account_id, viewer_is_admin)
            if snapshot is None:
                return None
            profile = snapshot["profile"]
            performance = snapshot.get("performance") or {}
            balance = snapshot.get("balance") or {}
            latest_message = latest_previews.get(int(target_id))
            card: dict[str, Any] = {
                "username": profile["username"],
                "displayName": profile["displayName"],
                "avatarUrl": profile["avatarUrl"],
                "bio": profile["bio"],
                "tierBadge": profile["tierBadge"],
                "userRank": profile["userRank"],
                "connectionsCount": profile["connectionsCount"],
                "networkState": snapshot["networkState"],
                "canWhisper": snapshot["canWhisper"],
                "visibility": snapshot["visibility"],
                "badges": snapshot["badges"][:4],
                "balance": balance.get("current"),
                "weeklyProfit": (performance.get("weekly") or {}).get("profit") if performance else None,
                "lifetimeProfit": (performance.get("lifetime") or {}).get("profit") if performance else None,
                "lastMessage": latest_message,
            }
            if created_at:
                card[time_key] = created_at
            return card

        connections: list[dict[str, Any]] = []
        for row in connection_rows:
            card = build_card(int(row["target_account_id"] or 0), row["created_at"], "connectedAt")
            if card is not None:
                connections.append(card)

        incoming_requests: list[dict[str, Any]] = []
        for row in incoming_rows:
            card = build_card(int(row["requester_account_id"] or 0), row["created_at"], "requestedAt")
            if card is not None:
                incoming_requests.append(card)

        outgoing_requests: list[dict[str, Any]] = []
        for row in outgoing_rows:
            card = build_card(int(row["recipient_account_id"] or 0), row["created_at"], "requestedAt")
            if card is not None:
                outgoing_requests.append(card)

    return jsonify(
        {
            "ok": True,
            "counts": counts,
            "connections": connections,
            "incomingRequests": incoming_requests,
            "outgoingRequests": outgoing_requests,
        }
    ), 200


@app.post("/api/community/network/add")
def community_network_add() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    payload = request.get_json(silent=True) or {}
    target_username = str(payload.get("targetUsername", "")).strip().lower()
    if not target_username:
        return jsonify({"ok": False, "message": "Target username is required."}), 400

    account_id = int(g.current_account["id"])
    with get_db() as conn:
        target = conn.execute("SELECT id, username FROM accounts WHERE lower(username) = ?", (target_username,)).fetchone()
        if target is None:
            return jsonify({"ok": False, "message": "User not found."}), 404

        target_id = int(target["id"])
        if target_id == account_id:
            return jsonify({"ok": False, "message": "You cannot add yourself to your network."}), 400

        if are_accounts_connected(conn, account_id, target_id):
            return jsonify({"ok": True, "message": "Already connected.", "state": "connected"}), 200

        reverse_request = conn.execute(
            "SELECT id FROM community_connection_requests WHERE requester_account_id = ? AND recipient_account_id = ? AND status = 'pending'",
            (target_id, account_id),
        ).fetchone()
        if reverse_request is not None:
            accept_connection_request(conn, target_id, account_id)
            return jsonify({"ok": True, "message": "Connection accepted. You can message each other now.", "state": "connected"}), 200

        existing_request = conn.execute(
            "SELECT status FROM community_connection_requests WHERE requester_account_id = ? AND recipient_account_id = ?",
            (account_id, target_id),
        ).fetchone()
        if existing_request is not None and str(existing_request["status"] or "").lower() == "pending":
            return jsonify({"ok": True, "message": "Connection request already sent.", "state": "outgoing"}), 200

        conn.execute(
            """
            INSERT INTO community_connection_requests (requester_account_id, recipient_account_id, status, created_at, responded_at)
            VALUES (?, ?, 'pending', CURRENT_TIMESTAMP, NULL)
            ON CONFLICT(requester_account_id, recipient_account_id) DO UPDATE SET
              status = 'pending',
              created_at = CURRENT_TIMESTAMP,
              responded_at = NULL
            """,
            (account_id, target_id),
        )

    return jsonify({"ok": True, "message": "Connection request sent.", "state": "outgoing"}), 201


@app.post("/api/community/network/respond")
def community_network_respond() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    payload = request.get_json(silent=True) or {}
    target_username = str(payload.get("targetUsername", "")).strip().lower()
    action = str(payload.get("action", "accept")).strip().lower()
    if not target_username:
        return jsonify({"ok": False, "message": "Target username is required."}), 400
    if action not in {"accept", "decline"}:
        return jsonify({"ok": False, "message": "Invalid action."}), 400

    account_id = int(g.current_account["id"])
    with get_db() as conn:
        requester = conn.execute("SELECT id FROM accounts WHERE lower(username) = ?", (target_username,)).fetchone()
        if requester is None:
            return jsonify({"ok": False, "message": "User not found."}), 404

        requester_id = int(requester["id"])
        request_row = conn.execute(
            "SELECT id FROM community_connection_requests WHERE requester_account_id = ? AND recipient_account_id = ? AND status = 'pending'",
            (requester_id, account_id),
        ).fetchone()
        if request_row is None:
            return jsonify({"ok": False, "message": "No pending request from this user."}), 404

        if action == "accept":
            accept_connection_request(conn, requester_id, account_id)
            return jsonify({"ok": True, "message": "Connection accepted.", "state": "connected"}), 200

        conn.execute(
            "UPDATE community_connection_requests SET status = 'declined', responded_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(request_row["id"]),),
        )

    return jsonify({"ok": True, "message": "Connection request declined.", "state": "none"}), 200


@app.get("/api/community/chat/inbox")
def community_chat_inbox() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    account_id = int(g.current_account["id"])
    viewer_is_admin = is_admin_account(g.current_account)
    with get_db() as conn:
        previews = get_last_whisper_previews(conn, account_id)
        connection_ids = [
            int(row["target_account_id"] or 0)
            for row in conn.execute(
                "SELECT target_account_id FROM community_network WHERE account_id = ? ORDER BY created_at DESC",
                (account_id,),
            ).fetchall()
        ]

        ordered_ids: list[int] = []
        seen_ids: set[int] = set()
        for target_id in list(previews.keys()) + connection_ids:
            if target_id <= 0 or target_id in seen_ids:
                continue
            seen_ids.add(target_id)
            ordered_ids.append(target_id)

        threads: list[dict[str, Any]] = []
        for target_id in ordered_ids:
            snapshot = get_community_member_snapshot(conn, target_id, account_id, viewer_is_admin)
            if snapshot is None:
                continue
            profile = snapshot["profile"]
            latest = previews.get(target_id) or {}
            threads.append(
                {
                    "username": profile["username"],
                    "displayName": profile["displayName"],
                    "avatarUrl": profile["avatarUrl"],
                    "userRank": profile["userRank"],
                    "tierBadge": profile["tierBadge"],
                    "networkState": snapshot["networkState"],
                    "canWhisper": snapshot["canWhisper"],
                    "badges": snapshot["badges"][:3],
                    "lastMessagePreview": latest.get("text"),
                    "lastMessageAt": latest.get("createdAt"),
                    "lastMessageIsMine": bool(latest.get("isMine")),
                }
            )

    threads.sort(key=lambda item: parse_db_timestamp(item.get("lastMessageAt")) or datetime.min, reverse=True)
    return jsonify({"ok": True, "threads": threads}), 200


@app.get("/api/community/posts")
def community_posts_list() -> tuple[Any, int]:
    limit_raw = request.args.get("limit", "25")
    try:
        limit = max(1, min(100, int(limit_raw)))
    except ValueError:
        limit = 25

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.body, p.created_at, a.username, cp.display_name
            FROM community_posts p
            JOIN accounts a ON a.id = p.account_id
            LEFT JOIN community_profiles cp ON cp.account_id = a.id
            ORDER BY p.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return jsonify(
        {
            "ok": True,
            "posts": [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "body": row["body"],
                    "createdAt": row["created_at"],
                    "username": row["username"],
                    "displayName": row["display_name"] or row["username"],
                }
                for row in rows
            ],
        }
    ), 200


@app.post("/api/community/posts")
def community_posts_create() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip()
    body = str(payload.get("body", "")).strip()

    if not title or not body:
        return jsonify({"ok": False, "message": "Title and body are required."}), 400
    if len(title) > 180 or len(body) > COMMUNITY_MAX_POST_LENGTH:
        return jsonify({"ok": False, "message": "Post is too long."}), 400

    account_id = int(g.current_account["id"])
    with get_db() as conn:
        conn.execute(
            "INSERT INTO community_posts (account_id, title, body) VALUES (?, ?, ?)",
            (account_id, title, body),
        )
        post_row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()

    return jsonify({"ok": True, "postId": int(post_row["id"]) if post_row else None}), 201


@app.get("/api/community/chat/global")
def community_chat_global_list() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    requester_id = int(g.current_account["id"])
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT m.id, m.message_body, m.created_at,
                   a.username,
                   cp.display_name,
                   cp.avatar_url,
                     cp.user_rank,
                   COALESCE((
                       SELECT MAX(COALESCE(p.tier_number, 0))
                       FROM purchases p
                       WHERE p.account_id = a.id
                         AND (p.expires_at IS NULL OR p.expires_at > CURRENT_TIMESTAMP)
                   ), 0) AS sender_tier
            FROM chat_messages m
            JOIN accounts a ON a.id = m.sender_account_id
            LEFT JOIN community_profiles cp ON cp.account_id = a.id
            WHERE m.channel_type = 'global' AND m.is_deleted = 0
            ORDER BY m.id DESC
            LIMIT 100
            """
        ).fetchall()

    ordered = list(reversed(rows))
    return jsonify(
        {
            "ok": True,
            "messages": [
                {
                    "id": row["id"],
                    "text": row["message_body"],
                    "createdAt": row["created_at"],
                    "isMine": row["username"] == g.current_account["username"] and int(requester_id) > 0,
                    "username": row["username"],
                    "displayName": row["display_name"] or row["username"],
                    "avatarUrl": row["avatar_url"] or COMMUNITY_DEFAULT_AVATAR,
                    "userRank": row["user_rank"] or "",
                    "tierBadge": f"Tier {int(row['sender_tier'])}" if int(row["sender_tier"] or 0) > 0 else "No Tier",
                }
                for row in ordered
            ],
        }
    ), 200


@app.post("/api/community/chat/global")
def community_chat_global_send() -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"ok": False, "message": "Message is required."}), 400
    if len(text) > COMMUNITY_MAX_CHAT_LENGTH:
        return jsonify({"ok": False, "message": "Message is too long."}), 400

    account_id = int(g.current_account["id"])
    with get_db() as conn:
        allowed, reason, _tier = can_account_chat(conn, account_id)
        if not allowed:
            return jsonify({"ok": False, "message": reason}), 403

        conn.execute(
            "INSERT INTO chat_messages (sender_account_id, recipient_account_id, channel_type, message_body) VALUES (?, NULL, 'global', ?)",
            (account_id, text),
        )

    return jsonify({"ok": True, "message": "Message sent."}), 201


@app.get("/api/community/chat/whisper/<username>")
def community_chat_whisper_list(username: str) -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    requester_id = int(g.current_account["id"])
    target_username = str(username or "").strip().lower()
    with get_db() as conn:
        target = conn.execute("SELECT id, username FROM accounts WHERE lower(username) = ?", (target_username,)).fetchone()
        if target is None:
            return jsonify({"ok": False, "message": "Target account not found."}), 404

        target_id = int(target["id"])
        rows = conn.execute(
            """
            SELECT m.id, m.message_body, m.created_at, m.sender_account_id,
                                         a.username, cp.display_name, cp.avatar_url, cp.user_rank,
                                         COALESCE((
                                                 SELECT MAX(COALESCE(p.tier_number, 0))
                                                 FROM purchases p
                                                 WHERE p.account_id = a.id
                                                     AND (p.expires_at IS NULL OR p.expires_at > CURRENT_TIMESTAMP)
                                         ), 0) AS sender_tier
            FROM chat_messages m
            JOIN accounts a ON a.id = m.sender_account_id
            LEFT JOIN community_profiles cp ON cp.account_id = a.id
            WHERE m.channel_type = 'whisper'
              AND m.is_deleted = 0
              AND ((m.sender_account_id = ? AND m.recipient_account_id = ?) OR (m.sender_account_id = ? AND m.recipient_account_id = ?))
            ORDER BY m.id DESC
            LIMIT 100
            """,
            (requester_id, target_id, target_id, requester_id),
        ).fetchall()

    ordered = list(reversed(rows))
    return jsonify(
        {
            "ok": True,
            "target": {"username": target["username"]},
            "messages": [
                {
                    "id": row["id"],
                    "text": row["message_body"],
                    "createdAt": row["created_at"],
                    "isMine": int(row["sender_account_id"]) == requester_id,
                    "username": row["username"],
                    "displayName": row["display_name"] or row["username"],
                    "avatarUrl": row["avatar_url"] or COMMUNITY_DEFAULT_AVATAR,
                    "userRank": row["user_rank"] or "",
                    "tierBadge": f"Tier {int(row['sender_tier'])}" if int(row["sender_tier"] or 0) > 0 else "No Tier",
                }
                for row in ordered
            ],
        }
    ), 200


@app.post("/api/community/chat/whisper/<username>")
def community_chat_whisper_send(username: str) -> tuple[Any, int]:
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"ok": False, "message": "Message is required."}), 400
    if len(text) > COMMUNITY_MAX_CHAT_LENGTH:
        return jsonify({"ok": False, "message": "Message is too long."}), 400

    requester_id = int(g.current_account["id"])
    target_username = str(username or "").strip().lower()
    with get_db() as conn:
        allowed, reason, _tier = can_account_chat(conn, requester_id)
        if not allowed:
            return jsonify({"ok": False, "message": reason}), 403

        target = conn.execute("SELECT id FROM accounts WHERE lower(username) = ?", (target_username,)).fetchone()
        if target is None:
            return jsonify({"ok": False, "message": "Target account not found."}), 404

        target_id = int(target["id"])
        if target_id == requester_id:
            return jsonify({"ok": False, "message": "Choose another member for a private chat."}), 400
        target_profile = conn.execute(
            "SELECT ignore_whisper FROM community_profiles WHERE account_id = ?",
            (target_id,),
        ).fetchone()
        if target_profile is not None and int(target_profile["ignore_whisper"] or 0) == 1 and not are_accounts_connected(conn, requester_id, target_id):
            return jsonify({"ok": False, "message": "This user is not accepting whispers right now."}), 403

        conn.execute(
            "INSERT INTO chat_messages (sender_account_id, recipient_account_id, channel_type, message_body) VALUES (?, ?, 'whisper', ?)",
            (requester_id, target_id, text),
        )

    return jsonify({"ok": True, "message": "Whisper sent."}), 201


@app.get("/api/admin/chat/messages")
def admin_chat_messages() -> tuple[Any, int]:
    _, error_response = require_admin_api()
    if error_response is not None:
        return error_response

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT m.id, m.channel_type, m.message_body, m.created_at,
                   s.username AS sender_username,
                   r.username AS recipient_username
            FROM chat_messages m
            JOIN accounts s ON s.id = m.sender_account_id
            LEFT JOIN accounts r ON r.id = m.recipient_account_id
            WHERE m.is_deleted = 0
            ORDER BY m.id DESC
            LIMIT 300
            """
        ).fetchall()

    return jsonify(
        {
            "ok": True,
            "messages": [
                {
                    "id": row["id"],
                    "channel": row["channel_type"],
                    "text": row["message_body"],
                    "createdAt": row["created_at"],
                    "sender": row["sender_username"],
                    "recipient": row["recipient_username"],
                }
                for row in rows
            ],
        }
    ), 200


@app.post("/api/admin/chat/suspend/<int:account_id>")
def admin_chat_suspend(account_id: int) -> tuple[Any, int]:
    admin_user, error_response = require_admin_api()
    if error_response is not None:
        return error_response

    payload = request.get_json(silent=True) or {}
    days_raw = payload.get("days", 7)
    reason = str(payload.get("reason", "Sharing paid signals to unauthorized tiers")).strip()
    try:
        days = max(1, min(30, int(days_raw)))
    except (TypeError, ValueError):
        days = 7

    suspended_until = (utc_now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        target = conn.execute("SELECT id FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if target is None:
            return jsonify({"ok": False, "message": "Account not found."}), 404
        conn.execute(
            "INSERT INTO chat_suspensions (account_id, reason, suspended_until, created_by_account_id) VALUES (?, ?, ?, ?)",
            (account_id, reason, suspended_until, int(admin_user["id"])),
        )

    return jsonify({"ok": True, "message": f"Account suspended from chat for {days} day(s).", "suspendedUntil": suspended_until}), 200


@app.post("/api/payment/paypal/checkout")
def paypal_checkout() -> tuple[Any, int]:
    """Initialize PayPal payment checkout."""
    if g.current_account is None:
        return jsonify({"ok": False, "message": "Log in to checkout."}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "message": "Provide a valid JSON body."}), 400
    try:
        purchase_id = int(data.get("purchaseId", 0))
    except (TypeError, ValueError):
        purchase_id = 0

    if purchase_id <= 0:
        return jsonify({"ok": False, "message": "Invalid purchase ID."}), 400
    
    with get_db() as conn:
        purchase = conn.execute(
            "SELECT * FROM purchases WHERE id = ? AND account_id = ?",
            (purchase_id, int(g.current_account["id"]))
        ).fetchone()
        
        if not purchase:
            return jsonify({"ok": False, "message": "Purchase not found."}), 404
        
        # Create checkout session (placeholder - waiting for PayPal credentials)
        checkout_session_id = f"CHECKOUT-{purchase_id}-{utc_now().strftime('%Y%m%d%H%M%S')}"
        
        # Update transaction status to pending_payment
        conn.execute(
            "UPDATE transactions SET status = 'pending_payment' WHERE purchase_id = ?",
            (purchase_id,)
        )
    
    return jsonify({
        "ok": True,
        "message": "Checkout session created. Ready for PayPal payment.",
        "checkoutSessionId": checkout_session_id,
        "purchaseId": purchase_id,
        "amount": purchase["price_gbp"],
        "paymentUrl": f"https://paypal.com/checkout?session={checkout_session_id}",  # Placeholder
    }), 200


@app.post("/api/payment/webhook/paypal")
def paypal_webhook() -> tuple[Any, int]:
    """PayPal webhook for payment confirmations."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "message": "Invalid webhook payload."}), 400
    if not verify_paypal_webhook_signature(data):
        logger.warning("Rejected PayPal webhook: signature verification failed.")
        return jsonify({"ok": False, "message": "Invalid webhook signature."}), 400

    event_type = data.get("event_type", "")
    
    if event_type == "CHECKOUT.ORDER.APPROVED":
        try:
            purchase_id = int(data.get("resource", {}).get("purchase_id", 0))
        except (TypeError, ValueError):
            purchase_id = 0
        
        if purchase_id > 0:
            with get_db() as conn:
                # Update transaction and purchase to completed
                conn.execute(
                    "UPDATE transactions SET status = 'completed' WHERE purchase_id = ?",
                    (purchase_id,)
                )
                conn.execute(
                    "UPDATE purchases SET last_renewed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (purchase_id,)
                )
                
                # Queue thank you email
                purchase = conn.execute("SELECT account_id FROM purchases WHERE id = ?", (purchase_id,)).fetchone()
                if purchase:
                    account = conn.execute("SELECT email FROM accounts WHERE id = ?", (purchase["account_id"],)).fetchone()
                    if account:
                        conn.execute(
                            "INSERT INTO email_queue (account_id, email_type, recipient_email, status) VALUES (?, 'purchase_confirmation', ?, 'pending')",
                            (purchase["account_id"], account["email"])
                        )
    
    return jsonify({"ok": True}), 200


@app.get("/api/admin/transactions")
def admin_transactions() -> tuple[Any, int]:
    """Get all transactions for business owner."""
    _, error_response = require_admin_api()
    if error_response is not None:
        return error_response
    
    with get_db() as conn:
        transactions = conn.execute("""
            SELECT t.id, t.account_id, a.email, t.purchase_id, t.amount_gbp, 
                   t.status, t.invoice_number, t.created_at
            FROM transactions t
            JOIN accounts a ON t.account_id = a.id
            ORDER BY t.created_at DESC LIMIT 100
        """).fetchall()
    
    return jsonify({
        "ok": True,
        "transactions": [
            {
                "id": row["id"],
                "accountId": row["account_id"],
                "email": row["email"],
                "purchaseId": row["purchase_id"],
                "amount": row["amount_gbp"],
                "status": row["status"],
                "invoiceNumber": row["invoice_number"],
                "createdAt": row["created_at"],
            }
            for row in transactions
        ],
    }), 200


@app.post("/api/admin/send-renewal-reminders")
def admin_send_renewal_reminders() -> tuple[Any, int]:
    """Send renewal reminder emails to customers."""
    _, error_response = require_admin_api()
    if error_response is not None:
        return error_response
    
    today = utc_now()
    with get_db() as conn:
        # Find purchases expiring in 7 days that haven't had reminder sent
        purchases = conn.execute("""
            SELECT p.id, p.account_id, p.expires_at, a.email, p.renewal_reminder_sent
            FROM purchases p
            JOIN accounts a ON p.account_id = a.id
            WHERE p.renewal_reminder_sent = 0 AND p.auto_renew = 1
        """).fetchall()
        
        sent_count = 0
        for purchase in purchases:
            expires_at = parse_db_timestamp(purchase["expires_at"])
            if expires_at is None:
                logger.warning("Skipping renewal reminder for purchase %s with invalid expires_at value %r", purchase["id"], purchase["expires_at"])
                continue
            days_until = (expires_at - today).days
            
            # Send reminder if within configured lead window.
            if 0 <= days_until <= RENEWAL_REMINDER_LEAD_DAYS:
                conn.execute(
                    "INSERT INTO email_queue (account_id, email_type, recipient_email, status) VALUES (?, 'renewal_reminder', ?, 'pending')",
                    (purchase["account_id"], purchase["email"])
                )
                conn.execute(
                    "UPDATE purchases SET renewal_reminder_sent = 1 WHERE id = ?",
                    (purchase["id"],)
                )
                sent_count += 1
    
    return jsonify({
        "ok": True,
        "message": f"Sent {sent_count} renewal reminders.",
        "remindersSent": sent_count,
    }), 200


def send_renewal_reminder_email(email: str, account_name: str, expires_at: str, signals_per_day: int) -> bool:
    """Send renewal reminder email to customer."""
    try:
        expires_dt = parse_db_timestamp(expires_at)
        if expires_dt is None:
            logger.warning("Could not send renewal email to %s because expires_at is invalid: %r", email, expires_at)
            return False

        expires_date = expires_dt.strftime("%B %d, %Y")

        subject = "Your VaultSignalsAI subscription expires soon!"
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <h2>Hi {account_name},</h2>
                <p>Your VaultSignalsAI subscription expires on <strong>{expires_date}</strong>.</p>
                <p>You currently have access to <strong>{signals_per_day} signal(s) per day</strong>.</p>
                <p>To keep enjoying premium signals without interruption, please renew your subscription:</p>
                <p><a href="{APP_BASE_URL}/your-signals" style="background: #f2c14e; color: #111; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">Renew Now</a></p>
                <p>Questions? <a href="{APP_BASE_URL}/">Contact us</a></p>
                <p>Best regards,<br/>VaultSignalsAI Team</p>
            </body>
        </html>
        """

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = email
        msg.set_content(f"Your VaultSignalsAI subscription expires on {expires_date}.")
        msg.add_alternative(html_body, subtype="html")

        return send_smtp_message(msg)
    except Exception as e:
        logger.warning("Failed to send renewal email to %s: %s", email, e)
        return False


def send_purchase_confirmation_email(email: str, account_name: str, tier_name: str, amount: float, invoice_number: str) -> bool:
    """Send purchase confirmation email."""
    try:
        subject = "Purchase Confirmed - VaultSignalsAI"
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <h2>Purchase Confirmed!</h2>
                <p>Hi {account_name},</p>
                <p>Thank you for your purchase! Your subscription is now active.</p>
                <h3>Order Details</h3>
                <ul>
                    <li><strong>Plan:</strong> {tier_name}</li>
                    <li><strong>Amount:</strong> £{amount:.2f}</li>
                    <li><strong>Invoice:</strong> {invoice_number}</li>
                </ul>
                <p><a href="{APP_BASE_URL}/your-signals" style="background: #f2c14e; color: #111; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">View Signals</a></p>
                <p>Questions? <a href="{APP_BASE_URL}/">Contact Support</a></p>
                <p>Best regards,<br/>VaultSignalsAI Team</p>
            </body>
        </html>
        """

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = email
        msg.set_content(f"Purchase confirmed for {tier_name}. Invoice: {invoice_number}.")
        msg.add_alternative(html_body, subtype="html")

        return send_smtp_message(msg)
    except Exception as e:
        logger.warning("Failed to send confirmation email to %s: %s", email, e)
        return False


@app.route("/stream")
def stream():
    requested_ids_raw = str(request.args.get("ids", "")).strip().lower()
    requested_ids = [item.strip() for item in requested_ids_raw.split(",") if re.match(r"^[a-z0-9-]{2,40}$", item.strip())]
    resolved_ids = requested_ids or STREAM_CRYPTO_IDS or LIVE_DESK_CRYPTO_IDS

    def generate():
        crypto_ids = resolved_ids
        last_update = 0
        last_heartbeat = 0
        
        while True:
            try:
                # Fetch crypto prices from CoinGecko API every 5 seconds
                if time.time() - last_update > 5:
                    url = f"{COINGECKO_BASE_URL}/simple/price"
                    params = {
                        "ids": ",".join(crypto_ids),
                        "vs_currencies": "usd",
                        "include_24hr_change": "true",
                        "include_market_cap": "true"
                    }
                    prices = request_json_with_retry(
                        url,
                        params,
                        timeout=REQUEST_TIMEOUT_SECONDS,
                        retries=REQUEST_RETRIES,
                        headers=market_api_headers(),
                    )

                    emitted_rows: list[dict[str, Any]] = []
                    if isinstance(prices, dict) and prices:
                        for crypto_id in crypto_ids:
                            if crypto_id in prices:
                                emitted_rows.append(
                                    {
                                        "id": crypto_id,
                                        "symbol": crypto_id.upper(),
                                        "price": prices[crypto_id].get("usd", 0),
                                        "change_24h": prices[crypto_id].get("usd_24h_change", 0),
                                        "market_cap": prices[crypto_id].get("usd_market_cap", 0),
                                    }
                                )
                    else:
                        fallback_rows = build_bitvavo_market_rows(crypto_ids)
                        emitted_rows.extend(
                            {
                                "id": str(coin.get("id", "")).lower(),
                                "symbol": str(coin.get("symbol", "")).upper(),
                                "price": coin.get("price", 0),
                                "change_24h": coin.get("change", 0),
                                "market_cap": coin.get("market_cap", 0),
                            }
                            for coin in fallback_rows
                        )

                    for data in emitted_rows:
                        yield f"data: {json.dumps(data)}\n\n"
                    last_update = time.time()

                if time.time() - last_heartbeat > 15:
                    yield ": keepalive\n\n"
                    last_heartbeat = time.time()
                
                time.sleep(1)
            except Exception as e:
                logger.warning("SSE stream error: %s", e)
                time.sleep(2)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/crypto-data")
def crypto_data():
    cached_payload = _MARKET_CACHE.get("payload")
    cached_at = float(_MARKET_CACHE.get("updated_at", 0) or 0)
    if cached_payload and (time.time() - cached_at) < MARKET_CACHE_TTL_SECONDS:
        return jsonify(cached_payload), 200

    try:
        tracked_ids = CANVAS_CRYPTO_IDS or API_CRYPTO_IDS
        crypto_url = f"{COINGECKO_BASE_URL}/coins/markets"
        crypto_params = {
            "vs_currency": "usd",
            "ids": ",".join(tracked_ids),
            "order": "market_cap_desc",
            "per_page": str(max(1, len(tracked_ids))),
            "page": "1",
            "sparkline": "false",
            "price_change_percentage": "24h",
        }
        global_url = f"{COINGECKO_BASE_URL}/global"
        headers = market_api_headers()
        crypto_json = request_json_with_retry(
            crypto_url,
            crypto_params,
            timeout=REQUEST_TIMEOUT_SECONDS,
            retries=REQUEST_RETRIES,
            headers=headers,
        )
        global_json = request_json_with_retry(
            global_url,
            {},
            timeout=REQUEST_TIMEOUT_SECONDS,
            retries=REQUEST_RETRIES,
            headers=headers,
        )

        market_data = {
            "stocks": STATIC_STOCK_FEED,
            "crypto": [],
            "summary": {
                "market_cap": 0,
                "volume_24h": 0,
                "btc_dominance": 0,
                "positive_count": 0,
                "tracked_assets": 0,
                "updated_at": int(time.time()),
            },
        }

        if isinstance(crypto_json, list):
            market_data["crypto"] = [format_market_coin(coin) for coin in crypto_json]
        if not market_data["crypto"]:
            market_data["crypto"] = build_bitvavo_market_rows(tracked_ids)

        market_data["summary"] = build_market_summary(global_json, market_data["crypto"])
        if not market_data["crypto"] and cached_payload:
            return jsonify(cached_payload), 200
        _MARKET_CACHE["payload"] = market_data
        _MARKET_CACHE["updated_at"] = time.time()

        return jsonify(market_data), 200
    except Exception as e:
        logger.warning("Market data fetch error: %s", e)

    if cached_payload:
        return jsonify(cached_payload), 200

    return jsonify({"error": "Could not fetch market data"}), 500


@app.get("/api/live-desk")
def live_desk_data() -> tuple[Any, int]:
    requested_coin_id = str(request.args.get("coin_id", "")).strip().lower()
    cache_key = requested_coin_id or LIVE_DESK_DEFAULT_COIN
    cached_entry = _LIVE_DESK_CACHE.get(cache_key)
    if cached_entry and (time.time() - float(cached_entry.get("updated_at", 0) or 0)) < MARKET_CACHE_TTL_SECONDS:
        return jsonify(cached_entry.get("payload", {})), 200

    tracked_ids = LIVE_DESK_CRYPTO_IDS or CANVAS_CRYPTO_IDS or API_CRYPTO_IDS
    headers = market_api_headers()

    try:
        crypto_url = f"{COINGECKO_BASE_URL}/coins/markets"
        crypto_params = {
            "vs_currency": "usd",
            "ids": ",".join(tracked_ids),
            "order": "market_cap_desc",
            "per_page": str(max(1, len(tracked_ids))),
            "page": "1",
            "sparkline": "true",
            "price_change_percentage": "24h,7d",
        }
        crypto_json = request_json_with_retry(
            crypto_url,
            crypto_params,
            timeout=REQUEST_TIMEOUT_SECONDS,
            retries=REQUEST_RETRIES,
            headers=headers,
        )

        market_rows = crypto_json if isinstance(crypto_json, list) else []
        if not market_rows:
            payload = build_bitvavo_live_desk_payload(tracked_ids, requested_coin_id)
            if payload.get("topCoins"):
                _LIVE_DESK_CACHE[cache_key] = {"payload": payload, "updated_at": time.time()}
                return jsonify(payload), 200
        top_coins = [format_live_desk_coin(coin) for coin in market_rows]
        selected_raw_coin = next((coin for coin in market_rows if str(coin.get("id", "")).lower() == requested_coin_id), None)
        if selected_raw_coin is None and market_rows:
            selected_raw_coin = market_rows[0]

        if selected_raw_coin is None:
            payload = build_bitvavo_live_desk_payload(tracked_ids, requested_coin_id)
            if payload.get("topCoins"):
                _LIVE_DESK_CACHE[cache_key] = {"payload": payload, "updated_at": time.time()}
                return jsonify(payload), 200

        selected_coin_id = str(selected_raw_coin.get("id", LIVE_DESK_DEFAULT_COIN)).strip().lower()
        chart_points = build_sparkline_points(
            ((selected_raw_coin.get("sparkline_in_7d") or {}).get("price")),
            hours=24,
        )
        if not chart_points:
            chart_points = build_intraday_fallback_chart(
                selected_raw_coin.get("current_price"),
                selected_raw_coin.get("price_change_percentage_24h"),
            )

        selected_coin = next((coin for coin in top_coins if coin.get("id") == selected_coin_id), format_live_desk_coin(selected_raw_coin))
        payload = {
            "ok": True,
            "topCoins": top_coins,
            "selectedCoin": selected_coin,
            "selectedCoinId": selected_coin_id,
            "chart": chart_points,
            "source": {
                "provider": "CoinGecko",
                "apiKeyConfigured": bool(COINGECKO_API_KEY),
                "fallback": False,
                "windowHours": 24,
            },
        }
        _LIVE_DESK_CACHE[cache_key] = {"payload": payload, "updated_at": time.time()}
        return jsonify(payload), 200
    except Exception as exc:
        logger.warning("Live desk fetch error: %s", exc)

    if cached_entry and cached_entry.get("payload"):
        return jsonify(cached_entry["payload"]), 200

    bitvavo_payload = build_bitvavo_live_desk_payload(tracked_ids, requested_coin_id)
    if bitvavo_payload.get("topCoins"):
        _LIVE_DESK_CACHE[cache_key] = {"payload": bitvavo_payload, "updated_at": time.time()}
        return jsonify(bitvavo_payload), 200

    cached_market_payload = _MARKET_CACHE.get("payload") if isinstance(_MARKET_CACHE.get("payload"), dict) else None
    cached_market_rows = (cached_market_payload or {}).get("crypto") if cached_market_payload else []
    if isinstance(cached_market_rows, list) and cached_market_rows:
        top_coins = [format_live_desk_coin(coin) for coin in cached_market_rows]
        selected_coin = next((coin for coin in top_coins if str(coin.get("id", "")).lower() == requested_coin_id), None) or top_coins[0]
        payload = {
            "ok": True,
            "message": "Using cached market feed.",
            "topCoins": top_coins,
            "selectedCoin": selected_coin,
            "selectedCoinId": str(selected_coin.get("id", "")).lower(),
            "chart": build_intraday_fallback_chart(selected_coin.get("price"), selected_coin.get("change")),
            "source": {
                "provider": "CoinGecko cache",
                "apiKeyConfigured": bool(COINGECKO_API_KEY),
                "fallback": True,
                "windowHours": 24,
            },
        }
        _LIVE_DESK_CACHE[cache_key] = {"payload": payload, "updated_at": time.time()}
        return jsonify(payload), 200

    return jsonify(
        {
            "ok": True,
            "message": "Live desk temporarily unavailable.",
            "topCoins": [],
            "selectedCoin": None,
            "selectedCoinId": "",
            "chart": [],
            "source": {
                "provider": "CoinGecko",
                "apiKeyConfigured": bool(COINGECKO_API_KEY),
                "fallback": True,
                "windowHours": 24,
            },
        }
    ), 200


MAX_FEEDBACK_LENGTH = 1000


@app.post("/api/feedback")
def submit_feedback() -> tuple[Any, int]:
    if is_rate_limited(_client_key()):
        return jsonify({"ok": False, "message": "Too many feedback submissions. Please wait a few minutes."}), 429

    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    topic = str(payload.get("topic", "")).strip()
    question = str(payload.get("question", "")).strip()

    if not email or not topic or not question:
        return jsonify({"ok": False, "message": "Email, topic and question are all required."}), 400

    email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    if not re.match(email_regex, email):
        return jsonify({"ok": False, "message": "Enter a valid email address."}), 400

    if len(question) > MAX_FEEDBACK_LENGTH:
        return jsonify({"ok": False, "message": f"Question must not exceed {MAX_FEEDBACK_LENGTH} characters."}), 400

    subject = f"[VaultSignalsAI Feedback] {topic[:80]}"
    body = f"From: {email}\nTopic: {topic}\n\n{question}"

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = FEEDBACK_EMAIL_FROM
        msg["To"] = FEEDBACK_EMAIL
        msg["Reply-To"] = email
        msg.set_content(body)
        send_smtp_message(msg)
    except Exception as e:
        logger.warning("Could not send feedback email: %s", e)
        # Feedback receipt is still acknowledged even if SMTP is not configured locally.

    return jsonify({"ok": True, "message": "Thank you! Your feedback has been received."}), 200


if __name__ == "__main__":
    validate_security_configuration()
    init_db()
    app.run(
        host=os.getenv("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_RUN_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes"},
    )