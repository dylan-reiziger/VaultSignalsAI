import ctypes
import json
import math
import os
import queue
import random
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from getpass import getuser
from pathlib import Path
from tkinter import (
    BOTH,
    BooleanVar,
    CENTER,
    Entry,
    LEFT,
    RIGHT,
    X,
    Y,
    Button,
    Canvas,
    Frame,
    Label,
    Listbox,
    PhotoImage,
    Scrollbar,
    StringVar,
    Tk,
    Toplevel,
    ttk,
)
from tkinter import messagebox

APP_TITLE = "VaultSignalsAI"
APP_VERSION = "v1.0.10"
WINDOWS_APP_ID = "VaultSignalsAI.Desktop"
REFRESH_INTERVAL_SECONDS = 1
CANDLE_REFRESH_SECONDS = 60
CANDLE_HISTORY_LIMIT = 500
DEFAULT_VISIBLE_CANDLES = 100
MIN_VISIBLE_CANDLES = 20
DEFAULT_SYMBOL = "BTCUSDT"
SYMBOL_OPTIONS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
ALERT_MIN_QUOTE_VOLUME = 50_000_000
ALERT_COOLDOWN_SECONDS = 30 * 60
MARKET_EVALUATION_SECONDS = 45
SCENARIO_LOOKBACK_CANDLES = 48
SCENARIO_HORIZON_HOURS = 12
SOCIAL_SENTIMENT_REFRESH_SECONDS = 5 * 60
SETTINGS_PATH = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VaultSignalsAI" / "settings.json"
LOGO_RELATIVE_PATH = Path("assets") / "VaultSignalsAI-logo.png"
VERSION_RELATIVE_PATH = Path("assets") / "VaultSignalsAI-version.txt"
GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/dylan-reiziger/VaultSignalsAI/releases/latest"
SPLASH_MESSAGES = [
    "Setting up the market...",
    "Building the signals...",
    "Remembering your name again?",
]

BACKGROUND = "#07090c"
PANEL = "#0d1015"
PANEL_HOVER = "#151a22"
BORDER = "#1c222b"
GRID = "#171c23"
TEXT = "#e4e9f0"
MUTED = "#8a95a3"
BLUE = "#5e8cff"
GREEN = "#17c784"
RED = "#f05b69"

RELEASE_TODO_GROUPS = (
    (
        "Brand and product",
        (
            ("logo_added", "Add the final owned VaultSignalsAI logo asset."),
            ("data_sources_reviewed", "Record source licences, refresh rates, and limitations."),
            ("claims_reviewed", "Remove profit claims, guarantees, and buy/sell/hold instructions."),
        ),
    ),
    (
        "UK compliance and customer protection",
        (
            ("legal_review", "Obtain qualified, current legal and compliance advice before UK release."),
            ("regulatory_scope", "Confirm the applicable product and financial-promotion requirements."),
            ("customer_documents", "Publish accurate risk warnings, terms, privacy, support, and data disclosures."),
        ),
    ),
    (
        "Build and publishing",
        (
            ("clean_device_test", "Test the extracted package on a clean Windows device."),
            ("code_signing", "Sign the executable and installer with an organisation-controlled certificate."),
            ("support_and_updates", "Publish support, update, security-reporting, and release-checksum processes."),
        ),
    ),
)
RELEASE_TODO_KEYS = tuple(key for _group, items in RELEASE_TODO_GROUPS for key, _label in items)


class MarketSignalApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1440x820")
        self.root.minsize(1040, 660)
        self.root.configure(bg=BACKGROUND)
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
        self.brand_images = []
        self.logo_image = None
        self.app_version = self.load_app_version()
        self.load_brand_assets()

        self.is_fullscreen = False
        self.running = True
        self.market_thread_started = False
        self.settings = self.load_local_settings()
        self.local_windows_user = self.get_local_user_name()
        self.user_name = self.settings["display_name"]
        self.follow_symbol = StringVar(value=self.settings["default_symbol"])
        self.welcome_text = StringVar(value=f"Welcome, {self.user_name}")
        self.last_update = StringVar(value="Connecting to live market data...")
        self.market_name = StringVar(value=self.display_symbol(self.follow_symbol.get()))
        self.price_text = StringVar(value="--")
        self.change_text = StringVar(value="--")
        self.signal_text = StringVar(value="ANALYSING")
        self.signal_detail = StringVar(value="Waiting for the first market update.")
        self.volume_text = StringVar(value="--")
        self.range_text = StringVar(value="--")
        self.momentum_text = StringVar(value="--")
        self.trend_text = StringVar(value="--")
        self.scenario_mid_text = StringVar(value="Waiting for candles")
        self.scenario_upper_text = StringVar(value="Waiting for candles")
        self.scenario_change_text = StringVar(value="Waiting for candles")
        self.social_sentiment_text = StringVar(value="CANDLE-ONLY")
        self.nav_expanded = False
        self.nav_close_job = None
        self.active_symbol = self.follow_symbol.get()
        self.candles = []
        self.latest_price = None
        self.scenario = None
        self.social_sentiment_score = None
        self.social_sentiment_source = "No social sentiment connector configured"
        self.social_sentiment_updated_at = ""
        self.visible_candle_count = DEFAULT_VISIBLE_CANDLES
        self.chart_view = None
        self.data_queue = queue.Queue()
        self.last_candle_symbol = ""
        self.last_candle_fetch = 0.0
        self.last_depth_fetch = 0.0
        self.depth_rows = []
        self.profile_name = StringVar(value=self.user_name)
        self.profile_market = StringVar(value=self.settings["default_symbol"])
        self.discord_contact = StringVar(value=self.settings.get("discord_contact", ""))
        self.discord_tier = StringVar(value=self.settings.get("discord_tier", "Unverified"))
        self.discord_market_updates_opt_in = BooleanVar(value=self.settings.get("discord_market_updates_opt_in", False))
        self.refresh_interval_choice = StringVar(value=str(self.settings["refresh_seconds"]))
        self.splash_enabled = BooleanVar(value=self.settings["show_splash"])
        self.start_fullscreen_enabled = BooleanVar(value=self.settings["start_fullscreen"])
        self.refresh_interval_seconds = self.settings["refresh_seconds"]
        self.page_overlay = None
        self.account_notice = StringVar(value="")
        self.settings_notice = StringVar(value="")
        self.alerts_enabled = BooleanVar(value=self.settings["alerts_enabled"])
        self.alert_threshold_choice = StringVar(value=str(self.settings["alert_threshold_percent"]))
        self.alert_threshold_percent = self.settings["alert_threshold_percent"]
        self.restrict_alerts_to_favorites = BooleanVar(value=self.settings.get("restrict_alerts_to_favorites", False))
        self.scenario_overlay_enabled = BooleanVar(value=self.settings["show_scenario_overlay"])
        self.social_sentiment_url = StringVar(value=self.settings["social_sentiment_url"])
        self.release_todo_status = {
            key: BooleanVar(value=self.settings["release_todo_status"][key])
            for key in RELEASE_TODO_KEYS
        }
        if self.logo_image and not self.release_todo_status["logo_added"].get():
            self.release_todo_status["logo_added"].set(True)
            self.settings["release_todo_status"]["logo_added"] = True
            self.persist_settings()
        self.release_todo_summary = StringVar()
        self.update_release_todo_summary()
        self.alert_cooldowns = {}
        self.alert_popup = None
        self.alert_symbol = ""
        self.favorite_symbols = set(self.settings["favorite_symbols"])
        self.favorite_market_summary = StringVar()
        self.restrict_alerts_to_favorites.trace_add("write", self.on_alert_scope_changed)
        self.update_favorite_market_summary()
        self.market_directory = self.fallback_markets()
        self.market_directory_loaded = False
        self.market_directory_loading = False
        self.market_evaluation_started = False
        self.social_sentiment_thread_started = False
        self.market_metrics = {}
        self.market_browser = None
        self.market_search = StringVar(value="")
        self.market_filter = StringVar(value="ALL")
        self.visible_market_symbols = []
        self.market_browser_status = StringVar(value="Loading live market directory...")

        self.configure_styles()
        self.build_layout()
        self.root.bind("<F11>", self.toggle_fullscreen)
        self.root.bind("<Escape>", self.exit_fullscreen)
        self.root.bind("<Control-minus>", lambda _event: self.zoom_out())
        self.root.bind("<Control-equal>", lambda _event: self.zoom_in())
        self.root.after(120, self.process_market_updates)
        if self.splash_enabled.get():
            self.show_startup_splash()
        else:
            self.finish_startup()

    def configure_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Vault.TCombobox",
            fieldbackground="#151a22",
            background="#151a22",
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=BORDER,
            lightcolor="#151a22",
            darkcolor="#151a22",
            padding=(10, 6),
        )
        style.map(
            "Vault.TCombobox",
            fieldbackground=[("readonly", "#151a22")],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", "#151a22")],
            selectforeground=[("readonly", TEXT)],
        )

    def build_layout(self):
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        self.build_top_bar()

        self.workspace = Frame(self.root, bg=BACKGROUND)
        self.workspace.grid(row=1, column=0, sticky="nsew")
        self.workspace.grid_rowconfigure(1, weight=1)
        self.workspace.grid_columnconfigure(0, minsize=205)
        self.workspace.grid_columnconfigure(1, weight=1)
        self.workspace.grid_columnconfigure(2, minsize=265)

        self.build_market_panel()
        self.build_chart_workspace()
        self.build_signal_panel()
        self.build_hover_navigation()

    def build_top_bar(self):
        top = Frame(self.root, bg="#090c10", height=62, highlightbackground=BORDER, highlightthickness=1)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)

        brand = Frame(top, bg="#090c10")
        brand.pack(side=LEFT, padx=(22, 26), pady=10)
        if logo := self.create_scaled_logo(38):
            Label(brand, image=logo, bg="#090c10").pack(side=LEFT, padx=(0, 9))
        brand_text = Frame(brand, bg="#090c10")
        brand_text.pack(side=LEFT)
        Label(brand_text, text="VaultSignalsAI", fg=TEXT, bg="#090c10", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        Label(brand_text, textvariable=self.welcome_text, fg=MUTED, bg="#090c10", font=("Segoe UI", 8)).pack(anchor="w")

        Label(top, text="FOLLOW MARKET", fg=MUTED, bg="#090c10", font=("Segoe UI", 8, "bold")).pack(side=LEFT, padx=(0, 8))
        self.symbol_combo = ttk.Combobox(
            top,
            textvariable=self.follow_symbol,
            values=SYMBOL_OPTIONS,
            state="readonly",
            width=12,
            justify=CENTER,
            style="Vault.TCombobox",
        )
        self.symbol_combo.pack(side=LEFT, pady=13)
        self.symbol_combo.bind("<<ComboboxSelected>>", self.select_followed_asset)
        self.create_button(top, "Browse", self.open_market_browser).pack(side=LEFT, padx=(8, 0), pady=12)
        self.create_button(top, "Open", self.open_followed_asset, primary=True).pack(side=LEFT, padx=(8, 0), pady=12)

        self.live_badge = Label(
            top,
            text="ÔùÅ LIVE",
            fg=GREEN,
            bg="#090c10",
            font=("Segoe UI", 9, "bold"),
        )
        self.live_badge.pack(side=LEFT, padx=18)

        top_actions = Frame(top, bg="#090c10")
        top_actions.pack(side=RIGHT, padx=16, pady=12)
        self.update_button = self.create_button(top_actions, "Update", self.check_for_update)
        self.update_button.pack(side=LEFT, padx=(0, 8))
        self.fullscreen_button = self.create_button(top_actions, "Full screen", self.toggle_fullscreen)
        self.fullscreen_button.pack(side=LEFT, padx=(0, 8))
        self.create_button(top_actions, "Minimize", self.minimize_window).pack(side=LEFT, padx=(0, 8))
        self.create_button(top_actions, "Close", self.close_window, danger=True).pack(side=LEFT)

    def build_market_panel(self):
        panel = Frame(self.workspace, bg=PANEL, width=205, highlightbackground=BORDER, highlightthickness=1)
        panel.grid(row=1, column=0, sticky="nsew")
        panel.grid_propagate(False)

        header = Frame(panel, bg=PANEL)
        header.pack(fill=X, padx=14, pady=(16, 10))
        Label(header, text="ORDER BOOK", fg=TEXT, bg=PANEL, font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        Label(header, text="LIVE", fg=GREEN, bg=PANEL, font=("Segoe UI", 8, "bold")).pack(side=RIGHT)

        labels = Frame(panel, bg=PANEL)
        labels.pack(fill=X, padx=14, pady=(0, 5))
        Label(labels, text="PRICE", fg=MUTED, bg=PANEL, font=("Segoe UI", 7, "bold"), width=10, anchor="w").pack(side=LEFT)
        Label(labels, text="AMOUNT", fg=MUTED, bg=PANEL, font=("Segoe UI", 7, "bold"), anchor="e").pack(side=RIGHT)

        self.depth_container = Frame(panel, bg=PANEL)
        self.depth_container.pack(fill=BOTH, expand=True, padx=14)
        for index in range(12):
            row = Frame(self.depth_container, bg=PANEL)
            row.pack(fill=X, pady=1)
            price = Label(row, text="--", fg=RED if index < 6 else GREEN, bg=PANEL, font=("Cascadia Mono", 8), anchor="w")
            price.pack(side=LEFT)
            amount = Label(row, text="--", fg="#b9c2cd", bg=PANEL, font=("Cascadia Mono", 8), anchor="e")
            amount.pack(side=RIGHT)
            self.depth_rows.append((price, amount))

        footer = Frame(panel, bg="#0a0d11", height=72)
        footer.pack(fill=X, side="bottom")
        footer.pack_propagate(False)
        Label(footer, text="DATA SOURCE", fg=MUTED, bg="#0a0d11", font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=14, pady=(13, 0))
        Label(footer, text="Public exchange market feed", fg="#c6d1dc", bg="#0a0d11", font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(2, 0))

    def build_chart_workspace(self):
        chart_area = Frame(self.workspace, bg=BACKGROUND)
        chart_area.grid(row=1, column=1, sticky="nsew")
        chart_area.grid_rowconfigure(1, weight=1)
        chart_area.grid_columnconfigure(0, weight=1)

        toolbar = Frame(chart_area, bg="#090c10", height=43, highlightbackground=BORDER, highlightthickness=1)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_propagate(False)
        Label(toolbar, textvariable=self.market_name, fg=TEXT, bg="#090c10", font=("Segoe UI", 10, "bold")).pack(side=LEFT, padx=15)
        Label(toolbar, text="1H", fg=BLUE, bg="#090c10", font=("Segoe UI", 9, "bold")).pack(side=LEFT, padx=(0, 16))
        Label(toolbar, text="Candles", fg=MUTED, bg="#090c10", font=("Segoe UI", 8)).pack(side=LEFT, padx=(0, 16))
        Label(toolbar, text="Volume", fg=MUTED, bg="#090c10", font=("Segoe UI", 8)).pack(side=LEFT, padx=(0, 16))
        Label(toolbar, text="Signals", fg=MUTED, bg="#090c10", font=("Segoe UI", 8)).pack(side=LEFT)
        self.zoom_label = Label(toolbar, text="", fg=MUTED, bg="#090c10", font=("Segoe UI", 8))
        self.zoom_label.pack(side=RIGHT, padx=(0, 14))
        self.create_chart_button(toolbar, "Reset", self.reset_chart_zoom).pack(side=RIGHT, padx=(0, 6), pady=7)
        self.create_chart_button(toolbar, "´╝ï", self.zoom_in).pack(side=RIGHT, padx=(0, 4), pady=7)
        self.create_chart_button(toolbar, "´╝ì", self.zoom_out).pack(side=RIGHT, padx=(0, 4), pady=7)
        self.chart_status = Label(toolbar, text="Loading candles...", fg=MUTED, bg="#090c10", font=("Segoe UI", 8))
        self.chart_status.pack(side=RIGHT, padx=(0, 14))

        self.chart_canvas = Canvas(chart_area, bg=BACKGROUND, highlightthickness=0)
        self.chart_canvas.grid(row=1, column=0, sticky="nsew")
        self.chart_canvas.bind("<Configure>", lambda _event: self.draw_chart())
        self.chart_canvas.bind("<MouseWheel>", self.on_chart_wheel)
        self.chart_canvas.bind("<Button-4>", lambda _event: self.zoom_in())
        self.chart_canvas.bind("<Button-5>", lambda _event: self.zoom_out())
        self.chart_canvas.bind("<Motion>", self.on_chart_motion)
        self.chart_canvas.bind("<Leave>", self.clear_chart_crosshair)

        status = Frame(chart_area, bg="#090c10", height=31, highlightbackground=BORDER, highlightthickness=1)
        status.grid(row=2, column=0, sticky="ew")
        status.grid_propagate(False)
        Label(status, textvariable=self.last_update, fg=MUTED, bg="#090c10", font=("Segoe UI", 8)).pack(side=LEFT, padx=15, pady=8)
        Label(status, text=f"Version {self.app_version}", fg="#68737f", bg="#090c10", font=("Segoe UI", 8)).pack(side=RIGHT, padx=(0, 15), pady=8)
        Label(status, text="Market data only ÔÇó Not investment advice", fg="#68737f", bg="#090c10", font=("Segoe UI", 8)).pack(side=RIGHT, padx=15, pady=8)

    def build_signal_panel(self):
        panel = Frame(self.workspace, bg=PANEL, width=265, highlightbackground=BORDER, highlightthickness=1)
        panel.grid(row=1, column=2, sticky="nsew")
        panel.grid_propagate(False)

        Label(panel, text="LIVE MARKET READING", fg=TEXT, bg=PANEL, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=16, pady=(17, 5))
        self.signal_value = Label(panel, textvariable=self.signal_text, fg=BLUE, bg=PANEL, font=("Segoe UI", 22, "bold"))
        self.signal_value.pack(anchor="w", padx=16)
        Label(panel, textvariable=self.signal_detail, fg="#bdc8d4", bg=PANEL, wraplength=225, justify=LEFT, font=("Segoe UI", 9)).pack(anchor="w", padx=16, pady=(7, 18))

        self.add_divider(panel)
        self.add_stat(panel, "LAST PRICE", self.price_text, TEXT)
        self.add_stat(panel, "24H OBSERVED CHANGE", self.change_text, GREEN)
        self.add_stat(panel, "24H RANGE", self.range_text, TEXT)
        self.add_stat(panel, "QUOTE VOLUME", self.volume_text, TEXT)
        self.add_stat(panel, "MOMENTUM", self.momentum_text, BLUE)
        self.add_stat(panel, "TREND", self.trend_text, TEXT)

        self.add_divider(panel)
        Label(panel, text="12H SCENARIO", fg=MUTED, bg=PANEL, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
        self.add_stat(panel, "SCENARIO MIDPOINT", self.scenario_mid_text, BLUE)
        self.add_stat(panel, "UPPER VOLATILITY BAND", self.scenario_upper_text, "#f5c95c")
        self.add_stat(panel, "12H SCENARIO CHANGE", self.scenario_change_text, BLUE)
        self.add_stat(panel, "SENTIMENT INPUT", self.social_sentiment_text, TEXT)

        self.add_divider(panel)
        Label(panel, text="HOW TO READ THIS", fg=MUTED, bg=PANEL, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
        Label(
            panel,
            text="Observed changes and the scenario use public market inputs. Indicator strength is not a probability, prediction, target, or trading instruction.",
            fg="#9ca8b6",
            bg=PANEL,
            wraplength=225,
            justify=LEFT,
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=16)

    def build_hover_navigation(self):
        self.nav = Frame(self.workspace, bg="#0d1117", width=228, highlightbackground="#29323e", highlightthickness=1)
        self.nav.place(x=-228, y=40, relheight=1, height=-40)
        self.nav.pack_propagate(False)

        nav_header = Frame(self.nav, bg="#0d1117", height=56)
        nav_header.pack(fill=X, padx=20, pady=(17, 10))
        nav_header.pack_propagate(False)
        Label(nav_header, text="NAVIGATION", fg=MUTED, bg="#0d1117", font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(6, 0))
        Label(nav_header, text="Workspace", fg=TEXT, bg="#0d1117", font=("Segoe UI", 14, "bold")).pack(anchor="w")

        self.add_nav_button("Crypto markets", self.show_crypto_markets)
        self.add_nav_button("Scenario report", self.show_scenario_report)
        self.add_nav_button("Learn & risk", self.show_learning_and_risk)
        self.add_nav_button("Release checklist", self.show_release_checklist)
        self.add_nav_button("Account", self.show_account)
        self.add_nav_button("Settings", self.show_settings)

        logo_footer = Frame(self.nav, bg="#090c10", height=84)
        logo_footer.pack(fill=X, side="bottom")
        logo_footer.pack_propagate(False)
        Label(logo_footer, text="V", fg=BLUE, bg="#090c10", font=("Segoe UI", 21, "bold")).pack(anchor="w", padx=20, pady=(12, 0))
        Label(logo_footer, text="VAULTSIGNALSAI", fg="#d6e0eb", bg="#090c10", font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=20)
        Label(logo_footer, text="LIVE MARKET WORKSPACE", fg="#64717f", bg="#090c10", font=("Segoe UI", 6, "bold")).pack(anchor="w", padx=20)

        self.nav_toggle = Button(
            self.workspace,
            text="ÔÇ║",
            command=self.toggle_navigation,
            fg="#e5edf6",
            bg="#161d26",
            activeforeground="#ffffff",
            activebackground="#26313f",
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=("Segoe UI", 16, "bold"),
            width=2,
            height=1,
            takefocus=True,
            highlightthickness=1,
            highlightbackground="#324052",
            highlightcolor="#8badff",
        )
        self.nav_toggle.place(x=14, y=40, width=34, height=34)
        self.nav_toggle.lift()

    def add_nav_button(self, label, command):
        button = Button(
            self.nav,
            text=label,
            command=command,
            fg="#cbd6e2",
            bg="#10151d",
            activeforeground="#ffffff",
            activebackground=PANEL_HOVER,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
            padx=20,
            pady=11,
            takefocus=True,
            highlightthickness=1,
            highlightbackground="#0d1117",
            highlightcolor="#8badff",
        )
        button.pack(fill=X, padx=10, pady=2)

    def create_button(self, parent, text, command, primary=False, danger=False):
        background = RED if danger else BLUE if primary else "#171d26"
        active = "#ff7180" if danger else "#7da3ff" if primary else "#252f3d"
        return Button(
            parent,
            text=text,
            command=command,
            fg="#ffffff" if primary or danger else "#d6e0eb",
            bg=background,
            activeforeground="#ffffff",
            activebackground=active,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=13,
            pady=7,
            takefocus=True,
            highlightthickness=1,
            highlightbackground="#2a3442",
            highlightcolor="#8badff",
        )

    @staticmethod
    def create_chart_button(parent, text, command):
        return Button(
            parent,
            text=text,
            command=command,
            fg="#cbd6e2",
            bg="#151a22",
            activeforeground="#ffffff",
            activebackground="#252f3d",
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=4,
            takefocus=True,
            highlightthickness=1,
            highlightbackground="#283341",
            highlightcolor="#8badff",
        )

    @staticmethod
    def load_local_settings():
        defaults = {
            "display_name": MarketSignalApp.get_local_user_name(),
            "default_symbol": DEFAULT_SYMBOL,
            "refresh_seconds": REFRESH_INTERVAL_SECONDS,
            "show_splash": True,
            "start_fullscreen": False,
            "alerts_enabled": True,
            "alert_threshold_percent": 8,
            "favorite_symbols": [],
            "show_scenario_overlay": True,
            "social_sentiment_url": "",
            "discord_contact": "",
            "discord_tier": "Unverified",
            "discord_market_updates_opt_in": False,
            "restrict_alerts_to_favorites": False,
            "release_todo_status": {},
        }
        try:
            saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = {}

        if isinstance(saved, dict):
            defaults.update({key: value for key, value in saved.items() if key in defaults})
        if not isinstance(defaults["default_symbol"], str) or not defaults["default_symbol"].isalpha():
            defaults["default_symbol"] = DEFAULT_SYMBOL
        if defaults["refresh_seconds"] not in (1, 2, 5):
            defaults["refresh_seconds"] = REFRESH_INTERVAL_SECONDS
        if defaults["alert_threshold_percent"] not in (5, 8, 10):
            defaults["alert_threshold_percent"] = 8
        defaults["display_name"] = str(defaults["display_name"]).strip() or MarketSignalApp.get_local_user_name()
        defaults["show_splash"] = bool(defaults["show_splash"])
        defaults["start_fullscreen"] = bool(defaults["start_fullscreen"])
        defaults["alerts_enabled"] = bool(defaults["alerts_enabled"])
        defaults["show_scenario_overlay"] = bool(defaults["show_scenario_overlay"])
        if not isinstance(defaults["favorite_symbols"], list):
            defaults["favorite_symbols"] = []
        defaults["favorite_symbols"] = sorted(
            {symbol.upper() for symbol in defaults["favorite_symbols"] if isinstance(symbol, str) and symbol.isalpha()}
        )
        if not isinstance(defaults["social_sentiment_url"], str) or not defaults["social_sentiment_url"].startswith("https://"):
            defaults["social_sentiment_url"] = ""
        if not isinstance(defaults["release_todo_status"], dict):
            defaults["release_todo_status"] = {}
        defaults["release_todo_status"] = {
            key: bool(defaults["release_todo_status"].get(key, False))
            for key in RELEASE_TODO_KEYS
        }
        defaults["discord_contact"] = str(defaults.get("discord_contact", "")).strip()[:80]
        defaults["discord_tier"] = str(defaults.get("discord_tier", "")).strip()[:40] or "Unverified"
        defaults["discord_market_updates_opt_in"] = bool(defaults.get("discord_market_updates_opt_in", False))
        defaults["restrict_alerts_to_favorites"] = bool(defaults.get("restrict_alerts_to_favorites", False))
        return defaults

    @staticmethod
    def resource_path(relative_path):
        base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        return base_path / relative_path

    def load_brand_assets(self):
        logo_path = self.resource_path(LOGO_RELATIVE_PATH)
        if not logo_path.is_file():
            return
        try:
            self.logo_image = PhotoImage(file=str(logo_path))
            self.root.iconphoto(True, self.logo_image)
        except Exception:
            self.logo_image = None

    def load_app_version(self):
        version_path = self.resource_path(VERSION_RELATIVE_PATH)
        try:
            version = version_path.read_text(encoding="utf-8").splitlines()[0].strip()
        except (OSError, IndexError):
            return APP_VERSION
        return version[:40] or APP_VERSION

    def create_scaled_logo(self, maximum_dimension):
        if not self.logo_image:
            return None
        scale = max(1, math.ceil(max(self.logo_image.width(), self.logo_image.height()) / maximum_dimension))
        scaled_logo = self.logo_image.subsample(scale, scale)
        self.brand_images.append(scaled_logo)
        return scaled_logo

    def persist_settings(self):
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_PATH.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError:
            self.last_update.set("Could not save local preferences on this device.")

    def show_startup_splash(self):
        self.splash = self.create_splash_window()
        self.splash.after(3000, self.finish_startup)

    def create_splash_window(self, preview=False):
        splash = Toplevel(self.root)
        splash.overrideredirect(True)
        splash.configure(bg="#050608")
        splash.attributes("-topmost", True)
        width, height = 620, 660
        x = (splash.winfo_screenwidth() - width) // 2
        y = (splash.winfo_screenheight() - height) // 2
        splash.geometry(f"{width}x{height}+{x}+{y}")

        canvas = Canvas(splash, width=width, height=height, bg="#050608", highlightthickness=0)
        canvas.pack(fill=BOTH, expand=True)
        if logo := self.create_scaled_logo(500):
            canvas.create_image(310, 280, image=logo)
        else:
            self.draw_splash_emblem(canvas)
        canvas.create_text(310, 577, text=random.choice(SPLASH_MESSAGES), fill="#d9e1ea", font=("Segoe UI", 12))
        canvas.create_line(200, 607, 420, 607, fill="#30291c", width=4)
        canvas.create_line(200, 607, 365, 607, fill="#e0a83d", width=4)
        canvas.create_text(310, 630, text="LOADING LIVE MARKET WORKSPACE", fill="#68737f", font=("Segoe UI", 7, "bold"))
        if preview:
            Button(
                splash,
                text="Close preview",
                command=splash.destroy,
                fg="#dce6f0",
                bg="#1b2430",
                activeforeground="#ffffff",
                activebackground="#2a394c",
                relief="flat",
                borderwidth=0,
                cursor="hand2",
                font=("Segoe UI", 8, "bold"),
                padx=12,
                pady=6,
            ).place(x=478, y=616)
        return splash

    def preview_startup_logo(self):
        preview = self.create_splash_window(preview=True)
        preview.lift()
        preview.focus_force()

    @staticmethod
    def draw_splash_emblem(canvas):
        """Draw a branded gold coin emblem inspired by the supplied VaultSignalsAI reference."""
        centre_x, centre_y = 310, 275
        canvas.create_oval(54, 19, 566, 531, fill="#06080a", outline="#2b1d09", width=2)
        canvas.create_oval(60, 25, 560, 525, outline="#8b5b16", width=8)
        canvas.create_oval(66, 31, 554, 519, outline="#f0bd4f", width=3)
        canvas.create_arc(67, 32, 553, 518, start=74, extent=108, style="arc", outline="#fff0a1", width=4)
        canvas.create_arc(67, 32, 553, 518, start=252, extent=68, style="arc", outline="#5d3a0d", width=3)
        canvas.create_oval(84, 49, 536, 501, outline="#182027", width=2)

        circuit_paths = [
            (122, 178, 184, 178, 204, 199, 248, 199),
            (116, 239, 171, 239, 192, 218, 236, 218),
            (118, 316, 177, 316, 200, 293, 240, 293),
            (498, 172, 435, 172, 414, 193, 369, 193),
            (505, 247, 449, 247, 428, 226, 383, 226),
            (500, 327, 445, 327, 423, 305, 380, 305),
        ]
        for path in circuit_paths:
            canvas.create_line(path, fill="#172027", width=2)
            for node_x, node_y in ((path[0], path[1]), (path[-2], path[-1])):
                canvas.create_oval(node_x - 5, node_y - 5, node_x + 5, node_y + 5, outline="#243038", width=2)
        for x, y in ((210, 158), (246, 138), (377, 139), (414, 163), (172, 355), (449, 360)):
            canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#172027", outline="#273139")

        canvas.create_polygon(145, 165, 284, 165, 310, 225, 336, 165, 475, 165, 310, 450, fill="#9b6118", outline="#ffdd79", width=2)
        canvas.create_polygon(154, 174, 268, 174, 244, 205, 202, 205, 273, 343, 306, 414, 225, 310, 177, 235, fill="#d3952d", outline="#f8ce69", width=1)
        canvas.create_polygon(273, 174, 300, 174, 326, 234, 307, 282, 273, 215, 246, 205, fill="#fff0a0", outline="#ffdc72", width=1)
        canvas.create_polygon(345, 205, 418, 205, 465, 174, 393, 309, 315, 441, 338, 370, 420, 230, fill="#d49329", outline="#f9cd62", width=1)
        canvas.create_polygon(314, 233, 344, 174, 456, 174, 425, 212, 348, 361, 315, 414, 290, 378, fill="#f4be4c", outline="#fff0a0", width=1)
        canvas.create_polygon(258, 289, 285, 345, 310, 411, 337, 364, 309, 316, 286, 273, fill="#70430f", outline="#f2be4a", width=1)
        canvas.create_line(310, 225, 310, 413, fill="#fff1a0", width=2)

        bars = ((385, 139, 401, 207), (414, 112, 430, 207), (443, 85, 459, 207))
        for index, (left, top, right, bottom) in enumerate(bars):
            fill = ("#d29129", "#edb849", "#ffe18a")[index]
            canvas.create_rectangle(left, top, right, bottom, fill=fill, outline="#fff0a0", width=1)

        canvas.create_text(centre_x, 449, text="V A U L T S I G N A L S  A I", fill="#e9bd61", font=("Segoe UI", 13, "bold"))
        canvas.create_text(centre_x, 476, text="MARKET INTELLIGENCE", fill="#79643d", font=("Segoe UI", 7, "bold"))

    def finish_startup(self):
        if getattr(self, "splash", None):
            self.splash.destroy()
            self.splash = None
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if self.start_fullscreen_enabled.get() and not self.is_fullscreen:
            self.root.after(50, self.toggle_fullscreen)
        if not self.market_thread_started:
            self.market_thread_started = True
            self.market_thread = threading.Thread(target=self.market_data_loop, daemon=True)
            self.market_thread.start()
        self.start_market_directory_load()
        if not self.market_evaluation_started:
            self.market_evaluation_started = True
            self.market_evaluation_thread = threading.Thread(target=self.market_evaluation_loop, daemon=True)
            self.market_evaluation_thread.start()
        if not self.social_sentiment_thread_started:
            self.social_sentiment_thread_started = True
            self.social_sentiment_thread = threading.Thread(target=self.social_sentiment_loop, daemon=True)
            self.social_sentiment_thread.start()

    def show_page(self, title, subtitle):
        if self.page_overlay:
            self.page_overlay.destroy()
        self.page_overlay = Frame(self.workspace, bg=BACKGROUND)
        self.page_overlay.place(x=0, y=0, relwidth=1, relheight=1)
        header = Frame(self.page_overlay, bg="#090c10", height=74, highlightbackground=BORDER, highlightthickness=1)
        header.pack(fill=X)
        header.pack_propagate(False)
        self.create_button(header, "ÔÇ╣  Crypto markets", self.show_crypto_markets).pack(side=LEFT, padx=(32, 18), pady=17)
        header_text = Frame(header, bg="#090c10")
        header_text.pack(side=LEFT, pady=12)
        Label(header_text, text=title, fg=TEXT, bg="#090c10", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        Label(header_text, text=subtitle, fg=MUTED, bg="#090c10", font=("Segoe UI", 8)).pack(anchor="w")
        self.nav.lift()
        self.nav_toggle.lift()
        return self.page_overlay

    def show_main_workspace(self):
        if self.page_overlay:
            self.page_overlay.destroy()
            self.page_overlay = None
        self.nav.lift()
        self.nav_toggle.lift()
        self.draw_chart()

    @staticmethod
    def fallback_markets():
        symbols = [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "BNBUSDT", "DOGEUSDT", "AVAXUSDT",
            "LINKUSDT", "DOTUSDT", "ATOMUSDT", "LTCUSDT", "TRXUSDT", "UNIUSDT", "AAVEUSDT", "NEARUSDT",
            "BTCUSDC", "ETHUSDC", "SOLUSDC", "XRPUSDC", "ADAUSDC", "BTCEUR", "ETHEUR", "SOLEUR", "XRPEUR",
        ]
        quote_assets = ("USDT", "USDC", "EUR")
        markets = []
        for symbol in symbols:
            quote = next(quote for quote in quote_assets if symbol.endswith(quote))
            markets.append({"symbol": symbol, "base": symbol[:-len(quote)], "quote": quote})
        return markets

    def start_market_directory_load(self):
        if self.market_directory_loading or self.market_directory_loaded:
            return
        self.market_directory_loading = True
        threading.Thread(target=self.fetch_market_directory, daemon=True).start()

    def fetch_market_directory(self):
        try:
            response = self.fetch_json("https://api.binance.com/api/v3/exchangeInfo")
            markets = [
                {
                    "symbol": item["symbol"],
                    "base": item["baseAsset"],
                    "quote": item["quoteAsset"],
                }
                for item in response.get("symbols", [])
                if item.get("status") == "TRADING"
                and item.get("isSpotTradingAllowed", True)
                and item.get("quoteAsset") in {"USDT", "USDC", "EUR"}
            ]
            if not markets:
                raise ValueError("No supported spot markets were returned.")
            self.data_queue.put(("markets", "", markets))
        except Exception as exc:
            self.data_queue.put(("market_directory_error", "", str(exc)))

    def market_evaluation_loop(self):
        while self.running:
            try:
                ticker_rows = self.fetch_json("https://api.binance.com/api/v3/ticker/24hr")
                metrics = {
                    row["symbol"]: {
                        "price": float(row.get("lastPrice", 0.0)),
                        "change": float(row.get("priceChangePercent", 0.0)),
                        "quote_volume": float(row.get("quoteVolume", 0.0)),
                    }
                    for row in ticker_rows
                    if isinstance(row, dict) and row.get("symbol")
                }
                self.data_queue.put(("market_metrics", "", metrics))
            except Exception as exc:
                self.data_queue.put(("market_metrics_error", "", str(exc)))
            time.sleep(MARKET_EVALUATION_SECONDS)

    def open_market_browser(self):
        if self.market_browser and self.market_browser.winfo_exists():
            self.market_browser.deiconify()
            self.market_browser.lift()
            self.market_search_entry.focus_set()
            return

        self.market_search.set("")
        self.market_filter.set("EVALUATED")
        browser = self.market_browser = Toplevel(self.root)
        browser.title("VaultSignalsAI ÔÇó Evaluated crypto markets")
        browser.configure(bg=BACKGROUND)
        browser.geometry("1020x680")
        browser.minsize(820, 560)
        browser.transient(self.root)
        browser.protocol("WM_DELETE_WINDOW", self.close_market_browser)

        header = Frame(browser, bg="#090c10", height=72, highlightbackground=BORDER, highlightthickness=1)
        header.pack(fill=X)
        header.pack_propagate(False)
        Label(header, text="Evaluated crypto markets", fg=TEXT, bg="#090c10", font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=22, pady=(13, 0))
        Label(header, text="Search live spot markets by quote currency, movement, volume, and favourites.", fg=MUTED, bg="#090c10", font=("Segoe UI", 8)).pack(anchor="w", padx=22)

        controls = Frame(browser, bg=BACKGROUND)
        controls.pack(fill=X, padx=22, pady=(18, 10))
        self.market_search_entry = Entry(
            controls,
            textvariable=self.market_search,
            bg="#151a22",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
            highlightthickness=1,
            highlightbackground="#2b3440",
            highlightcolor=BLUE,
        )
        self.market_search_entry.pack(fill=X, ipady=8)
        self.market_search_entry.bind("<KeyRelease>", lambda _event: self.render_market_results())

        filters = Frame(browser, bg=BACKGROUND)
        filters.pack(fill=X, padx=22, pady=(0, 10))
        for name in ("EVALUATED", "ALL", "USDT", "EUR", "USDC", "STARRED"):
            button = self.create_button(filters, name.title() if name == "STARRED" else name, lambda value=name: self.set_market_filter(value))
            button.pack(side=LEFT, padx=(0, 7))

        body = Frame(browser, bg=BACKGROUND)
        body.pack(fill=BOTH, expand=True, padx=22, pady=(0, 16))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        list_frame = Frame(body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        list_frame.grid(row=0, column=0, sticky="nsew")
        self.market_list = Listbox(
            list_frame,
            bg=PANEL,
            fg="#d8e2ed",
            selectbackground="#254262",
            selectforeground="#ffffff",
            activestyle="none",
            relief="flat",
            borderwidth=0,
            font=("Cascadia Mono", 10),
            highlightthickness=0,
            exportselection=False,
        )
        scrollbar = Scrollbar(list_frame, command=self.market_list.yview)
        self.market_list.configure(yscrollcommand=scrollbar.set)
        self.market_list.pack(side=LEFT, fill=BOTH, expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side=RIGHT, fill=Y, padx=(0, 10), pady=10)
        self.market_list.bind("<<ListboxSelect>>", self.preview_selected_market)
        self.market_list.bind("<Double-Button-1>", lambda _event: self.open_selected_market())

        details = Frame(body, bg=PANEL, width=270, highlightbackground=BORDER, highlightthickness=1)
        details.grid(row=0, column=1, sticky="nsew", padx=(14, 0))
        details.grid_propagate(False)
        Label(details, text="MARKET SELECTION", fg=MUTED, bg=PANEL, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=18, pady=(20, 5))
        self.market_preview = Label(details, text="Select a market", fg=TEXT, bg=PANEL, font=("Segoe UI", 14, "bold"), wraplength=195, justify=LEFT)
        self.market_preview.pack(anchor="w", padx=18)
        self.market_metric_preview = Label(details, text="", fg="#bdc8d4", bg=PANEL, wraplength=225, justify=LEFT, font=("Cascadia Mono", 8))
        self.market_metric_preview.pack(anchor="w", padx=18, pady=(8, 0))
        self.market_star_status = Label(details, text="", fg="#f5c95c", bg=PANEL, font=("Segoe UI", 9))
        self.market_star_status.pack(anchor="w", padx=18, pady=(6, 20))
        self.create_button(details, "Open market", self.open_selected_market, primary=True).pack(anchor="w", padx=18, pady=(0, 8))
        self.star_market_button = self.create_button(details, "Star selected", self.toggle_selected_favorite)
        self.star_market_button.pack(anchor="w", padx=18)
        Label(
            details,
            text="Starred markets are saved on this device and always appear first. Turn on selected-market alerts in Account to target notifications to this list.",
            fg=MUTED,
            bg=PANEL,
            wraplength=195,
            justify=LEFT,
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=18, pady=(24, 0))

        footer = Frame(browser, bg="#090c10", height=38, highlightbackground=BORDER, highlightthickness=1)
        footer.pack(fill=X)
        footer.pack_propagate(False)
        Label(footer, textvariable=self.market_browser_status, fg=MUTED, bg="#090c10", font=("Segoe UI", 8)).pack(anchor="w", padx=22, pady=11)

        self.render_market_results(preselect=self.follow_symbol.get())
        self.start_market_directory_load()
        browser.lift()
        browser.focus_force()
        self.market_search_entry.focus_set()

    def close_market_browser(self):
        if self.market_browser:
            self.market_browser.destroy()
            self.market_browser = None

    def set_market_filter(self, market_filter):
        self.market_filter.set(market_filter)
        self.render_market_results()

    def render_market_results(self, preselect=None):
        if not self.market_browser or not self.market_browser.winfo_exists():
            return
        search = self.market_search.get().strip().upper()
        selected_filter = self.market_filter.get()
        results = []
        for market in self.market_directory:
            if selected_filter == "STARRED" and market["symbol"] not in self.favorite_symbols:
                continue
            if selected_filter == "EVALUATED" and market["symbol"] not in self.market_metrics:
                continue
            if selected_filter not in ("ALL", "STARRED", "EVALUATED") and market["quote"] != selected_filter:
                continue
            searchable = f"{market['symbol']} {market['base']} {market['quote']}"
            if search and search not in searchable:
                continue
            results.append(market)

        if selected_filter == "EVALUATED":
            results.sort(
                key=lambda item: (
                    item["symbol"] not in self.favorite_symbols,
                    -self.market_score(item["symbol"]),
                    item["base"],
                )
            )
        else:
            results.sort(key=lambda item: (item["symbol"] not in self.favorite_symbols, item["base"], item["quote"]))
        self.visible_market_symbols = [item["symbol"] for item in results]
        self.market_list.delete(0, "end")
        selected_index = None
        for index, market in enumerate(results):
            star = "Ôÿà" if market["symbol"] in self.favorite_symbols else " "
            metrics = self.market_metrics.get(market["symbol"])
            if metrics:
                movement = metrics["change"]
                price = self.format_price(metrics["price"])
                volume = self.format_compact_number(metrics["quote_volume"])
                self.market_list.insert(
                    "end",
                    f"{star}  {market['base']:<10} / {market['quote']:<4}  {price:>14}  {movement:+7.2f}%  V {volume:>8}",
                )
            else:
                self.market_list.insert("end", f"{star}  {market['base']:<10} / {market['quote']:<4}  waiting for evaluation")
            if market["symbol"] == preselect:
                selected_index = index

        source = "live exchange directory" if self.market_directory_loaded else "fallback list while live directory loads"
        self.market_browser_status.set(f"{len(results)} markets shown ÔÇó {source} ÔÇó Ôÿà favourites are pinned first")
        if selected_index is not None:
            self.market_list.selection_set(selected_index)
            self.market_list.see(selected_index)
            self.preview_selected_market()
        else:
            self.market_preview.configure(text="Select a market")
            self.market_metric_preview.configure(text="")
            self.market_star_status.configure(text="")

    def selected_browser_symbol(self):
        if not hasattr(self, "market_list"):
            return ""
        selected = self.market_list.curselection()
        if not selected:
            return ""
        index = selected[0]
        return self.visible_market_symbols[index] if index < len(self.visible_market_symbols) else ""

    def preview_selected_market(self, _event=None):
        symbol = self.selected_browser_symbol()
        if not symbol:
            return
        self.market_preview.configure(text=self.display_symbol(symbol))
        metrics = self.market_metrics.get(symbol)
        quote = next((market["quote"] for market in self.market_directory if market["symbol"] == symbol), "")
        if metrics:
            self.market_metric_preview.configure(
                text=(
                    f"Price      {self.format_price(metrics['price'])}\n"
                    f"24H move   {metrics['change']:+.2f}%\n"
                    f"Volume     {self.format_compact_number(metrics['quote_volume'])} {quote}"
                )
            )
        else:
            self.market_metric_preview.configure(text="Waiting for a live evaluation snapshot.")
        starred = symbol in self.favorite_symbols
        self.market_star_status.configure(text="Ôÿà Starred and pinned" if starred else "Not starred")
        self.star_market_button.configure(text="Remove star" if starred else "Star selected")

    def market_score(self, symbol):
        metrics = self.market_metrics.get(symbol)
        if not metrics:
            return 0.0
        return abs(metrics["change"]) * (1 + min(metrics["quote_volume"] / ALERT_MIN_QUOTE_VOLUME, 10))

    def toggle_selected_favorite(self):
        symbol = self.selected_browser_symbol()
        if not symbol:
            self.market_browser_status.set("Select a market before changing its star status.")
            return
        if symbol in self.favorite_symbols:
            self.favorite_symbols.remove(symbol)
        else:
            self.favorite_symbols.add(symbol)
        self.settings["favorite_symbols"] = sorted(self.favorite_symbols)
        self.update_favorite_market_summary()
        self.persist_settings()
        self.update_quick_market_values()
        self.render_market_results(preselect=symbol)

    def open_selected_market(self):
        symbol = self.selected_browser_symbol()
        if not symbol:
            self.market_browser_status.set("Select a market to open it.")
            return
        self.follow_symbol.set(symbol)
        self.profile_market.set(symbol)
        self.open_followed_asset()
        self.close_market_browser()

    def update_quick_market_values(self):
        quick_symbols = list(sorted(self.favorite_symbols))
        for symbol in [self.active_symbol, self.follow_symbol.get(), *SYMBOL_OPTIONS]:
            if symbol not in quick_symbols:
                quick_symbols.append(symbol)
        self.symbol_combo.configure(values=quick_symbols)

    def update_favorite_market_summary(self):
        if not self.favorite_symbols:
            if self.restrict_alerts_to_favorites.get():
                self.favorite_market_summary.set("Selected-market alerts are on, but no markets are selected. Choose markets to receive alerts.")
            else:
                self.favorite_market_summary.set("No markets selected. Alerts currently scan all eligible markets.")
            return
        displayed_symbols = [self.display_symbol(symbol) for symbol in sorted(self.favorite_symbols)]
        summary = ", ".join(displayed_symbols)
        scope = "Only these markets can raise alerts." if self.restrict_alerts_to_favorites.get() else "Alerts still scan all eligible markets."
        self.favorite_market_summary.set(f"Selected markets: {summary[:180]}\n{scope}")

    def on_alert_scope_changed(self, *_args):
        self.update_favorite_market_summary()

    @staticmethod
    def create_page_card(parent, title, subtitle):
        card = Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        Label(card, text=title, fg=TEXT, bg=PANEL, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=22, pady=(18, 2))
        Label(card, text=subtitle, fg=MUTED, bg=PANEL, font=("Segoe UI", 8)).pack(anchor="w", padx=22, pady=(0, 16))
        return card

    def add_form_field(self, parent, label, variable):
        row = Frame(parent, bg=PANEL)
        row.pack(fill=X, pady=(0, 12))
        Label(row, text=label.upper(), fg=MUTED, bg=PANEL, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 5))
        entry = Entry(
            row,
            textvariable=variable,
            bg="#151a22",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
            highlightthickness=1,
            highlightbackground="#2b3440",
            highlightcolor=BLUE,
        )
        entry.pack(fill=X, ipady=8)

    def add_form_combo(self, parent, label, variable, values):
        row = Frame(parent, bg=PANEL)
        row.pack(fill=X, pady=(0, 12))
        Label(row, text=label.upper(), fg=MUTED, bg=PANEL, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 5))
        combo = ttk.Combobox(row, textvariable=variable, values=values, state="readonly", style="Vault.TCombobox")
        combo.pack(fill=X, ipady=4)

    def add_toggle_row(self, parent, label, variable):
        row = Frame(parent, bg=PANEL)
        row.pack(fill=X, padx=22, pady=(0, 10))
        ttk.Checkbutton(row, text=label, variable=variable, takefocus=True).pack(anchor="w")

    def save_account_profile(self):
        name = self.profile_name.get().strip() or self.local_windows_user
        market = self.profile_market.get()
        discord_contact = self.discord_contact.get().strip()
        discord_tier = self.discord_tier.get().strip() or "Unverified"
        if len(discord_contact) > 80:
            self.account_notice.set("Keep the Discord profile reference to 80 characters or fewer.")
            return
        if len(discord_tier) > 40:
            self.account_notice.set("Keep the locally recorded Discord tier to 40 characters or fewer.")
            return
        if self.discord_market_updates_opt_in.get() and not discord_contact:
            self.account_notice.set("Add a Discord username or user ID before opting in to future Discord updates.")
            return
        self.user_name = name
        self.welcome_text.set(f"Welcome, {name}")
        self.settings.update(
            {
                "display_name": name,
                "default_symbol": market,
                "discord_contact": discord_contact,
                "discord_tier": discord_tier,
                "discord_market_updates_opt_in": self.discord_market_updates_opt_in.get(),
                "restrict_alerts_to_favorites": self.restrict_alerts_to_favorites.get(),
            }
        )
        self.persist_settings()
        self.account_notice.set("Account and notification preferences saved locally. Discord delivery is not connected in this beta.")
        self.last_update.set("Local account and market preferences saved.")

    def reset_account_profile(self):
        self.profile_name.set(self.local_windows_user)
        self.profile_market.set(DEFAULT_SYMBOL)
        self.discord_contact.set("")
        self.discord_tier.set("Unverified")
        self.discord_market_updates_opt_in.set(False)
        self.restrict_alerts_to_favorites.set(False)
        self.account_notice.set("Account form reset. Your selected markets are unchanged until you edit them in Browse.")

    def save_settings(self):
        try:
            refresh_seconds = int(self.refresh_interval_choice.get())
        except ValueError:
            refresh_seconds = REFRESH_INTERVAL_SECONDS
        if refresh_seconds not in (1, 2, 5):
            refresh_seconds = REFRESH_INTERVAL_SECONDS
        try:
            alert_threshold = int(self.alert_threshold_choice.get())
        except ValueError:
            alert_threshold = 8
        if alert_threshold not in (5, 8, 10):
            alert_threshold = 8
        social_sentiment_url = self.social_sentiment_url.get().strip()
        if social_sentiment_url and not social_sentiment_url.startswith("https://"):
            self.settings_notice.set("The social sentiment connector must use a secure HTTPS URL.")
            return
        previous_social_sentiment_url = self.settings["social_sentiment_url"]
        self.refresh_interval_seconds = refresh_seconds
        self.alert_threshold_percent = alert_threshold
        self.settings.update(
            {
                "display_name": self.user_name,
                "default_symbol": self.profile_market.get(),
                "refresh_seconds": refresh_seconds,
                "show_splash": self.splash_enabled.get(),
                "start_fullscreen": self.start_fullscreen_enabled.get(),
                "alerts_enabled": self.alerts_enabled.get(),
                "alert_threshold_percent": alert_threshold,
                "show_scenario_overlay": self.scenario_overlay_enabled.get(),
                "social_sentiment_url": social_sentiment_url,
            }
        )
        self.persist_settings()
        if social_sentiment_url != previous_social_sentiment_url:
            self.social_sentiment_score = None
            self.social_sentiment_source = "Waiting for the configured public sentiment source"
            self.social_sentiment_updated_at = ""
            self.social_sentiment_text.set("WAITING")
            self.request_social_sentiment_refresh()
        self.recalculate_scenario()
        self.settings_notice.set("Settings saved. Startup options apply next time you open the app.")
        self.last_update.set("Settings saved. Live refresh update is active.")

    def reset_settings(self):
        self.refresh_interval_choice.set(str(REFRESH_INTERVAL_SECONDS))
        self.profile_market.set(DEFAULT_SYMBOL)
        self.splash_enabled.set(True)
        self.start_fullscreen_enabled.set(False)
        self.alerts_enabled.set(True)
        self.alert_threshold_choice.set("8")
        self.scenario_overlay_enabled.set(True)
        self.social_sentiment_url.set("")
        self.settings_notice.set("Settings reset in the form. Select Save settings to keep them.")

    @staticmethod
    def get_local_user_name():
        name = getuser().strip().replace(".", " ").replace("_", " ").replace("-", " ")
        return name.title() if name else "there"

    @staticmethod
    def display_symbol(symbol):
        if symbol.endswith("USDT"):
            return f"{symbol[:-4]} / USDT"
        return symbol

    def add_divider(self, parent):
        Frame(parent, bg=BORDER, height=1).pack(fill=X, padx=16, pady=(0, 2))

    def add_stat(self, parent, title, value, colour):
        row = Frame(parent, bg=PANEL)
        row.pack(fill=X, padx=16, pady=7)
        Label(row, text=title, fg=MUTED, bg=PANEL, font=("Segoe UI", 7, "bold")).pack(anchor="w")
        Label(row, textvariable=value, fg=colour, bg=PANEL, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(1, 0))

    def toggle_navigation(self):
        self.nav_expanded = not self.nav_expanded
        if self.nav_expanded:
            self.nav.place_configure(x=0)
            self.nav_toggle.place_configure(x=211)
            self.nav_toggle.configure(text="ÔÇ╣")
            self.nav.lift()
            self.nav_toggle.lift()
        else:
            self.nav.place_configure(x=-228)
            self.nav_toggle.place_configure(x=14)
            self.nav_toggle.configure(text="ÔÇ║")
            self.nav_toggle.lift()

    def show_crypto_markets(self):
        self.show_main_workspace()
        self.last_update.set("Opening evaluated crypto markets.")
        self.open_market_browser()

    def show_account(self):
        page = self.show_page("Account", "Manage local profile, market, and future notification preferences.")
        content = Frame(page, bg=BACKGROUND)
        content.pack(fill=BOTH, expand=True, padx=42, pady=(4, 30))

        identity = self.create_page_card(content, "Local profile", "Preferences stay on this device. This beta does not create an online account.")
        identity.pack(fill=X, pady=(0, 18))
        Label(identity, text=f"Windows user: {self.local_windows_user}", fg="#afbdca", bg=PANEL, font=("Segoe UI", 10)).pack(anchor="w", padx=22, pady=(2, 14))

        preferences = self.create_page_card(content, "Account and market preferences", "Choose a default market and target high-impact alerts to selected markets.")
        preferences.pack(fill=X)
        form = Frame(preferences, bg=PANEL)
        form.pack(fill=X, padx=22, pady=(0, 14))
        self.add_form_field(form, "Display name", self.profile_name)
        self.add_form_combo(form, "Default market", self.profile_market, SYMBOL_OPTIONS)
        self.add_form_field(form, "Discord username or user ID", self.discord_contact)
        self.add_form_field(form, "Discord tier (local note)", self.discord_tier)
        self.add_toggle_row(preferences, "Opt in to future Discord market updates", self.discord_market_updates_opt_in)
        Label(
            preferences,
            text="The Discord reference and tier note are saved only on this device. This beta does not log in to Discord, verify a tier, upload your identity, or send Discord messages. Only a separate server-side Discord OAuth and bot service can verify tiers or choose notification delivery.",
            fg=MUTED,
            bg=PANEL,
            wraplength=760,
            justify=LEFT,
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=22, pady=(0, 14))
        Label(preferences, text="PREFERRED NOTIFICATION MARKETS", fg=MUTED, bg=PANEL, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=22, pady=(0, 5))
        Label(preferences, textvariable=self.favorite_market_summary, fg="#bdc8d4", bg=PANEL, wraplength=760, justify=LEFT, font=("Segoe UI", 9)).pack(anchor="w", padx=22, pady=(0, 8))
        self.add_toggle_row(preferences, "Alert only on my selected markets", self.restrict_alerts_to_favorites)
        actions = Frame(preferences, bg=PANEL)
        actions.pack(fill=X, padx=22, pady=(0, 8))
        self.create_button(actions, "Choose notification markets", self.show_crypto_markets).pack(side=LEFT)
        self.create_button(actions, "Save profile", self.save_account_profile, primary=True).pack(side=LEFT, padx=(8, 0))
        self.create_button(actions, "Reset form", self.reset_account_profile).pack(side=LEFT, padx=(8, 0))
        Label(preferences, textvariable=self.account_notice, fg=GREEN, bg=PANEL, font=("Segoe UI", 9)).pack(anchor="w", padx=22, pady=(0, 18))

    def show_scenario_report(self):
        page = self.show_page(
            "Scenario report",
            "Candle analysis with an optional public sentiment input. This is not a future-price forecast or trading instruction.",
        )
        content = Frame(page, bg=BACKGROUND)
        content.pack(fill=BOTH, expand=True, padx=42, pady=(4, 30))

        current = self.create_page_card(
            content,
            "Current 12-hour observed-volatility scenario",
            "The chart's dotted path is a modelled range from recent one-hour candles, not a price target.",
        )
        current.pack(fill=X, pady=(0, 18))
        if self.scenario:
            as_of = self.scenario["as_of"].strftime("%A, %d %B %Y %H:%M:%S")
            source = self.social_sentiment_source
            if self.social_sentiment_updated_at:
                source = f"{source} ÔÇó updated {self.social_sentiment_updated_at}"
            detail = (
                f"Market                 {self.display_symbol(self.active_symbol)}\n"
                f"Calculated             {as_of}\n"
                f"Current reference      {self.format_price(self.scenario['reference_price'])}\n"
                f"12H scenario midpoint  {self.format_price(self.scenario['midpoint'])}\n"
                f"12H upper band         {self.format_price(self.scenario['upper'])}\n"
                f"12H lower band         {self.format_price(self.scenario['lower'])}\n"
                f"Candle volatility      {self.scenario['volatility'] * 100:.2f}% per hour\n"
                f"Sentiment input        {self.social_sentiment_text.get()}\n"
                f"Source                 {source}"
            )
        else:
            detail = "Waiting for at least 24 completed one-hour candles before a scenario can be shown."
        Label(
            current,
            text=detail,
            fg="#c6d1dc",
            bg=PANEL,
            justify=LEFT,
            font=("Cascadia Mono", 9),
        ).pack(anchor="w", padx=22, pady=(0, 20))

        method = self.create_page_card(content, "Method and limits", "Use the range for research, not as a buying, selling, or profit decision.")
        method.pack(fill=X)
        Label(
            method,
            text=(
                "The scenario measures recent candle returns, realised volatility, and relative volume. A configured public sentiment connector can make a small adjustment to the path. "
                "It cannot know future market moves, prices, social-media events, liquidity changes, or whether a trade will be profitable."
            ),
            fg=MUTED,
            bg=PANEL,
            wraplength=900,
            justify=LEFT,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=22, pady=(0, 18))
        self.create_button(method, "Open chart", self.show_main_workspace, primary=True).pack(anchor="w", padx=22, pady=(0, 20))

    def show_learning_and_risk(self):
        page = self.show_page(
            "Learn & risk",
            "Educational market-data explanations and release guardrails. This page does not provide legal or financial advice.",
        )
        content = Frame(page, bg=BACKGROUND)
        content.pack(fill=BOTH, expand=True, padx=42, pady=(4, 30))

        learning = self.create_page_card(
            content,
            "Learning-first market workspace",
            "Use charts, public-market movement, and scenario ranges to understand how crypto markets can move.",
        )
        learning.pack(fill=X, pady=(0, 18))
        Label(
            learning,
            text=(
                "The app displays observed market data, recent price change, volume, and an illustrative volatility range. "
                "The direction label describes current inputs only; its strength value is not the chance of a future move."
            ),
            fg="#c6d1dc",
            bg=PANEL,
            wraplength=900,
            justify=LEFT,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=22, pady=(0, 18))

        risk = self.create_page_card(
            content,
            "Risk and product boundaries",
            "Cryptoassets are high risk. Values can fall quickly and users can lose all of the money they invest.",
        )
        risk.pack(fill=X, pady=(0, 18))
        Label(
            risk,
            text=(
                "VaultSignalsAI must not promise returns, call a scenario a guaranteed outcome, or tell a user to buy, sell, or hold an asset. "
                "Keep the product educational and general: show data sources, assumptions, timestamps, and uncertainty alongside every market view."
            ),
            fg=MUTED,
            bg=PANEL,
            wraplength=900,
            justify=LEFT,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=22, pady=(0, 18))

        release = self.create_page_card(
            content,
            "UK public-release check",
            "This software is not FCA approved or FCA authorised simply because it includes this page or a disclaimer.",
        )
        release.pack(fill=X)
        Label(
            release,
            text=(
                "Before making the download or related promotions available in the UK, obtain qualified, current legal and compliance advice. "
                "Confirm whether the product, subscription, audience, marketing, and cryptoasset financial promotions are regulated; follow the applicable approval, authorisation, risk-warning, record-keeping, privacy, and consumer-protection requirements. "
                "Only state an FCA status after it has been independently verified."
            ),
            fg=MUTED,
            bg=PANEL,
            wraplength=900,
            justify=LEFT,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=22, pady=(0, 18))
        self.create_button(release, "Open chart", self.show_main_workspace, primary=True).pack(anchor="w", padx=22, pady=(0, 20))

    def update_release_todo_summary(self):
        completed = sum(variable.get() for variable in self.release_todo_status.values())
        self.release_todo_summary.set(f"{completed} of {len(RELEASE_TODO_KEYS)} items completed on this device")

    def save_release_todo_status(self):
        self.settings["release_todo_status"] = {
            key: variable.get()
            for key, variable in self.release_todo_status.items()
        }
        self.persist_settings()
        self.update_release_todo_summary()

    def show_release_checklist(self):
        page = self.show_page(
            "Release checklist",
            "Local progress tracker for the educational desktop release. Compliance items require independent professional confirmation.",
        )
        content = Frame(page, bg=BACKGROUND)
        content.pack(fill=BOTH, expand=True, padx=42, pady=(4, 30))

        summary = self.create_page_card(
            content,
            "Public-release readiness",
            "Tick an item only when it is actually complete. Completion status is stored locally on this device.",
        )
        summary.pack(fill=X, pady=(0, 18))
        Label(summary, textvariable=self.release_todo_summary, fg="#f5c95c", bg=PANEL, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=22, pady=(0, 8))
        logo_status = (
            "Owned logo loaded from assets/VaultSignalsAI-logo.png."
            if self.logo_image
            else "Logo asset pending: add the supplied PNG at assets/VaultSignalsAI-logo.png, then rebuild the Windows package."
        )
        Label(summary, text=logo_status, fg=MUTED, bg=PANEL, wraplength=900, justify=LEFT, font=("Segoe UI", 8)).pack(anchor="w", padx=22, pady=(0, 18))

        for group_title, items in RELEASE_TODO_GROUPS:
            card = self.create_page_card(content, group_title, "Review and evidence each item before marking it complete.")
            card.pack(fill=X, pady=(0, 14))
            for key, label in items:
                row = Frame(card, bg=PANEL)
                row.pack(fill=X, padx=22, pady=(0, 9))
                ttk.Checkbutton(
                    row,
                    text=label,
                    variable=self.release_todo_status[key],
                    command=self.save_release_todo_status,
                    takefocus=True,
                ).pack(anchor="w")

        Label(
            content,
            text="This checklist is operational guidance only. It does not establish FCA approval, FCA authorisation, or legal compliance.",
            fg="#68737f",
            bg=BACKGROUND,
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(2, 0))

    def show_settings(self):
        page = self.show_page("Settings", "Control the local market-monitor behaviour and startup experience.")
        content = Frame(page, bg=BACKGROUND)
        content.pack(fill=BOTH, expand=True, padx=42, pady=(4, 30))

        data = self.create_page_card(content, "Market data", "Changes apply immediately after saving.")
        data.pack(fill=X, pady=(0, 18))
        form = Frame(data, bg=PANEL)
        form.pack(fill=X, padx=22, pady=(0, 14))
        self.add_form_combo(form, "Price refresh", self.refresh_interval_choice, ["1", "2", "5"])
        self.add_form_combo(form, "Default market", self.profile_market, SYMBOL_OPTIONS)
        Label(data, text="Refresh values are in seconds. Candle history refreshes every minute.", fg=MUTED, bg=PANEL, font=("Segoe UI", 8)).pack(anchor="w", padx=22, pady=(0, 14))

        startup = self.create_page_card(content, "Startup", "Choose how VaultSignalsAI opens on this device.")
        startup.pack(fill=X, pady=(0, 18))
        self.add_toggle_row(startup, "Show the 3-second VaultSignalsAI loading screen", self.splash_enabled)
        self.add_toggle_row(startup, "Open in full screen after startup", self.start_fullscreen_enabled)

        alerts = self.create_page_card(content, "High-impact market alerts", "Alerts use public price and volume data. They flag volatility, not a guaranteed opportunity or return.")
        alerts.pack(fill=X, pady=(0, 18))
        self.add_toggle_row(alerts, "Scan eligible liquid crypto markets for high-impact movement alerts", self.alerts_enabled)
        alert_form = Frame(alerts, bg=PANEL)
        alert_form.pack(fill=X, padx=22, pady=(0, 8))
        self.add_form_combo(alert_form, "Minimum 24H movement", self.alert_threshold_choice, ["5", "8", "10"])
        Label(
            alerts,
            text="The scanner evaluates USDT, USDC, and EUR spot markets. Alerts require the selected 24H movement threshold and at least $50M equivalent quote volume. Each market direction is limited to one alert every 30 minutes.",
            fg=MUTED,
            bg=PANEL,
            wraplength=650,
            justify=LEFT,
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=22, pady=(0, 14))

        scenario = self.create_page_card(content, "Chart scenario and public sentiment", "The overlay estimates an observed-volatility range from candles and an optional sentiment input.")
        scenario.pack(fill=X, pady=(0, 18))
        self.add_toggle_row(scenario, "Show the 12-hour scenario overlay on the market chart", self.scenario_overlay_enabled)
        sentiment_form = Frame(scenario, bg=PANEL)
        sentiment_form.pack(fill=X, padx=22, pady=(0, 8))
        self.add_form_field(sentiment_form, "Optional HTTPS social sentiment connector", self.social_sentiment_url)
        Label(
            scenario,
            text='A connector must return JSON with a numeric "score" from -100 to 100, plus optional "source" and "updated_at" fields. It should be a licensed public-data or social-listening provider; no social data is collected when this field is blank.',
            fg=MUTED,
            bg=PANEL,
            wraplength=650,
            justify=LEFT,
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=22, pady=(0, 10))
        self.create_button(scenario, "Refresh public sentiment", self.request_social_sentiment_refresh).pack(anchor="w", padx=22, pady=(0, 16))

        actions = Frame(content, bg=BACKGROUND)
        actions.pack(fill=X, pady=(2, 0))
        self.create_button(actions, "Save settings", self.save_settings, primary=True).pack(side=LEFT)
        self.create_button(actions, "Reset settings", self.reset_settings).pack(side=LEFT, padx=(8, 0))
        self.create_button(actions, "Preview startup logo", self.preview_startup_logo).pack(side=LEFT, padx=(8, 0))
        Label(actions, textvariable=self.settings_notice, fg=GREEN, bg=BACKGROUND, font=("Segoe UI", 9)).pack(side=LEFT, padx=14)

    def select_followed_asset(self, _event=None):
        selected = self.follow_symbol.get()
        self.last_update.set(f"{self.display_symbol(selected)} selected. Select Open to start following it.")

    def open_followed_asset(self):
        self.active_symbol = self.follow_symbol.get()
        self.market_name.set(self.display_symbol(self.active_symbol))
        self.candles = []
        self.latest_price = None
        self.scenario = None
        self.scenario_mid_text.set("Waiting for candles")
        self.scenario_upper_text.set("Waiting for candles")
        self.scenario_change_text.set("Waiting for candles")
        self.visible_candle_count = DEFAULT_VISIBLE_CANDLES
        self.chart_view = None
        self.last_candle_symbol = ""
        self.signal_text.set("LOADING")
        self.signal_detail.set("Opening the live market monitor...")
        self.chart_status.configure(text="Loading candle history...")
        self.last_update.set(f"Opening {self.display_symbol(self.active_symbol)} live market monitor...")
        self.draw_chart()

    def social_sentiment_loop(self):
        while self.running:
            self.fetch_social_sentiment()
            for _ in range(SOCIAL_SENTIMENT_REFRESH_SECONDS):
                if not self.running:
                    return
                time.sleep(1)

    def request_social_sentiment_refresh(self):
        social_sentiment_url = self.social_sentiment_url.get().strip()
        if not social_sentiment_url:
            self.social_sentiment_score = None
            self.social_sentiment_source = "No social sentiment connector configured"
            self.social_sentiment_updated_at = ""
            self.social_sentiment_text.set("CANDLE-ONLY")
            self.recalculate_scenario()
            self.settings_notice.set("No connector is configured, so the scenario uses candles only.")
            return
        if not social_sentiment_url.startswith("https://"):
            self.settings_notice.set("The social sentiment connector must use a secure HTTPS URL.")
            return
        self.settings["social_sentiment_url"] = social_sentiment_url
        self.social_sentiment_text.set("REFRESHING")
        threading.Thread(target=self.fetch_social_sentiment, daemon=True).start()

    def fetch_social_sentiment(self):
        social_sentiment_url = self.settings["social_sentiment_url"]
        if not social_sentiment_url:
            self.data_queue.put(("social_sentiment_unavailable", "", "No social sentiment connector configured"))
            return
        try:
            payload = self.fetch_json(social_sentiment_url)
            self.data_queue.put(("social_sentiment", "", self.parse_social_sentiment(payload)))
        except Exception as exc:
            self.data_queue.put(("social_sentiment_error", "", str(exc)))

    @staticmethod
    def parse_social_sentiment(payload):
        candidates = [payload]
        if isinstance(payload, dict):
            for key in ("data", "result", "sentiment"):
                nested = payload.get(key)
                if isinstance(nested, list) and nested:
                    candidates.append(nested[0])
                elif isinstance(nested, dict):
                    candidates.append(nested)

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            raw_score = next(
                (candidate[key] for key in ("score", "sentiment_score", "value") if key in candidate),
                None,
            )
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                continue
            if -1 <= score <= 1:
                score *= 100
            elif 0 <= score <= 100:
                score = (score - 50) * 2
            if not -100 <= score <= 100:
                continue
            source = str(candidate.get("source") or candidate.get("provider") or "Configured public sentiment source").strip()
            updated_at = str(candidate.get("updated_at") or candidate.get("timestamp") or "").strip()
            return {"score": score, "source": source[:80], "updated_at": updated_at[:80]}
        raise ValueError("The sentiment connector did not return a supported numeric score.")

    def market_data_loop(self):
        while self.running:
            symbol = self.active_symbol
            try:
                ticker = self.fetch_json(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}")
                self.data_queue.put(("ticker", symbol, ticker))

                now = time.monotonic()
                if now - self.last_depth_fetch >= 2:
                    depth = self.fetch_json(f"https://api.binance.com/api/v3/depth?symbol={symbol}&limit=12")
                    self.data_queue.put(("depth", symbol, depth))
                    self.last_depth_fetch = now

                if symbol != self.last_candle_symbol or now - self.last_candle_fetch >= CANDLE_REFRESH_SECONDS:
                    candles = self.fetch_json(
                        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit={CANDLE_HISTORY_LIMIT}"
                    )
                    self.data_queue.put(("candles", symbol, candles))
                    self.last_candle_symbol = symbol
                    self.last_candle_fetch = now
            except Exception as exc:
                self.data_queue.put(("error", symbol, str(exc)))

            time.sleep(self.refresh_interval_seconds)

    @staticmethod
    def fetch_json(url):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"VaultSignalsAI/{APP_VERSION}",
            },
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def version_key(version):
        return tuple(
            int(part)
            for part in str(version).strip().lower().lstrip("v").split(".")
            if part.isdigit()
        )

    def check_for_update(self):
        self.update_button.configure(text="Checking...", state="disabled")
        threading.Thread(target=self.fetch_latest_release, daemon=True).start()

    def fetch_latest_release(self):
        try:
            release = self.fetch_json(GITHUB_LATEST_RELEASE_URL)
            version = str(release.get("tag_name") or "").strip()
            assets = release.get("assets") or []
            asset = next(
                (
                    item
                    for item in assets
                    if str(item.get("name") or "").startswith("VaultSignalsAI-windows-x64-")
                    and str(item.get("name") or "").endswith(".zip")
                ),
                None,
            )
            download_url = str(asset.get("browser_download_url") or "").strip() if isinstance(asset, dict) else ""
            if not version or not download_url:
                raise ValueError("No Windows desktop update is attached to the latest release.")
            self.data_queue.put(("app_update", "", {"version": version, "download_url": download_url}))
        except Exception as exc:
            self.data_queue.put(("app_update_error", "", str(exc)))

    def handle_update_result(self, release):
        self.update_button.configure(text="Update", state="normal")
        latest_version = str(release.get("version") or "")
        if self.version_key(latest_version) <= self.version_key(self.app_version):
            self.last_update.set(f"VaultSignalsAI {self.app_version} is up to date.")
            messagebox.showinfo("VaultSignalsAI update", f"You already have the latest version ({self.app_version}).")
            return

        if messagebox.askyesno(
            "VaultSignalsAI update",
            f"Version {latest_version} is available. Open the Windows download now?",
        ):
            webbrowser.open_new_tab(release["download_url"])
            self.last_update.set(f"Opened the {latest_version} Windows download.")
        else:
            self.last_update.set(f"Version {latest_version} is available from the Update button.")

    def handle_update_error(self, message):
        self.update_button.configure(text="Update", state="normal")
        self.last_update.set("Could not check for a desktop update. Try again later.")
        messagebox.showerror("VaultSignalsAI update", f"Could not check GitHub Releases.\n\n{message}")

    def process_market_updates(self):
        try:
            while True:
                message_type, symbol, data = self.data_queue.get_nowait()
                if message_type == "markets":
                    self.update_market_directory(data)
                    continue
                if message_type == "market_directory_error":
                    self.market_directory_loading = False
                    self.market_browser_status.set("Live market directory unavailable; showing the local fallback list.")
                    continue
                if message_type == "market_metrics":
                    self.update_market_metrics(data)
                    continue
                if message_type == "market_metrics_error":
                    self.market_browser_status.set("Market evaluation is temporarily unavailable; retrying automatically.")
                    continue
                if message_type == "social_sentiment":
                    self.update_social_sentiment(data)
                    continue
                if message_type == "social_sentiment_unavailable":
                    self.update_social_sentiment_unavailable(data)
                    continue
                if message_type == "social_sentiment_error":
                    self.update_social_sentiment_error(data)
                    continue
                if message_type == "app_update":
                    self.handle_update_result(data)
                    continue
                if message_type == "app_update_error":
                    self.handle_update_error(data)
                    continue
                if symbol != self.active_symbol:
                    continue
                if message_type == "ticker":
                    self.update_ticker(data)
                elif message_type == "depth":
                    self.update_depth(data)
                elif message_type == "candles":
                    self.update_candles(data)
                elif message_type == "error":
                    self.live_badge.configure(text="ÔùÅ RETRYING", fg="#f3b84b")
                    self.last_update.set("Market connection interrupted; retrying automatically.")
        except queue.Empty:
            pass

        if self.running:
            self.root.after(120, self.process_market_updates)

    def update_market_directory(self, markets):
        self.market_directory = markets
        self.market_directory_loaded = True
        self.market_directory_loading = False
        valid_symbols = {market["symbol"] for market in markets}
        self.favorite_symbols.intersection_update(valid_symbols)
        self.settings["favorite_symbols"] = sorted(self.favorite_symbols)
        self.update_favorite_market_summary()
        self.persist_settings()
        self.update_quick_market_values()
        self.render_market_results(preselect=self.follow_symbol.get())

    def update_market_metrics(self, metrics):
        self.market_metrics = metrics
        self.render_market_results(preselect=self.selected_browser_symbol())
        self.check_high_impact_market_alerts()

    def update_ticker(self, data):
        price = float(data.get("lastPrice", 0.0))
        change = float(data.get("priceChangePercent", 0.0))
        quote_volume = float(data.get("quoteVolume", 0.0))
        high = float(data.get("highPrice", 0.0))
        low = float(data.get("lowPrice", 0.0))
        volume_ratio = quote_volume / max(high * 1000.0, 1.0)
        direction, confidence, reason = self.compute_signal(change, volume_ratio)

        self.latest_price = price
        self.price_text.set(self.format_price(price))
        self.change_text.set(f"{change:+.2f}%")
        self.signal_text.set(direction.upper())
        self.signal_detail.set(f"Indicator strength: {confidence}/100 ÔÇó {reason}")
        self.volume_text.set(self.format_compact_number(quote_volume))
        self.range_text.set(f"{self.format_price(low)} ÔÇö {self.format_price(high)}")
        self.momentum_text.set(f"{volume_ratio:.2f}x")
        self.trend_text.set("UPWARD" if change >= 0 else "DOWNWARD")
        self.change_text_colour(change)
        self.live_badge.configure(text="ÔùÅ LIVE", fg=GREEN)
        self.last_update.set(f"Last price update: {datetime.now().strftime('%H:%M:%S')}  ÔÇó  refreshes every second")
        self.recalculate_scenario()
        self.draw_chart()

    def update_social_sentiment(self, data):
        self.social_sentiment_score = data["score"]
        self.social_sentiment_source = data["source"]
        self.social_sentiment_updated_at = data["updated_at"] or datetime.now().strftime("%d %b %Y %H:%M:%S")
        self.social_sentiment_text.set(f"{self.social_sentiment_score:+.0f} / 100")
        self.recalculate_scenario()
        self.last_update.set("Public sentiment input refreshed; chart scenario recalculated.")

    def update_social_sentiment_unavailable(self, message):
        if self.social_sentiment_score is None:
            self.social_sentiment_source = message
            self.social_sentiment_updated_at = ""
            self.social_sentiment_text.set("CANDLE-ONLY")
            self.recalculate_scenario()

    def update_social_sentiment_error(self, message):
        if self.social_sentiment_score is None:
            self.social_sentiment_source = f"Sentiment unavailable: {message}"
            self.social_sentiment_updated_at = ""
            self.social_sentiment_text.set("CANDLE-ONLY")
            self.recalculate_scenario()

    def check_high_impact_market_alerts(self):
        """Alert on a single large, liquid public-market moveÔÇönever an asserted profit opportunity."""
        if not self.alerts_enabled.get() or self.alert_popup:
            return

        candidates = []
        allowed_symbols = {market["symbol"] for market in self.market_directory}
        if self.restrict_alerts_to_favorites.get():
            allowed_symbols.intersection_update(self.favorite_symbols)
        for symbol, metrics in self.market_metrics.items():
            if symbol not in allowed_symbols:
                continue
            if abs(metrics["change"]) < self.alert_threshold_percent:
                continue
            if metrics["quote_volume"] < ALERT_MIN_QUOTE_VOLUME:
                continue
            direction = "upward" if metrics["change"] > 0 else "downward"
            alert_key = (symbol, direction)
            if time.monotonic() - self.alert_cooldowns.get(alert_key, 0.0) < ALERT_COOLDOWN_SECONDS:
                continue
            candidates.append((self.market_score(symbol), symbol, metrics, direction))

        if not candidates:
            return
        _score, symbol, metrics, direction = max(candidates, key=lambda item: item[0])
        self.alert_cooldowns[(symbol, direction)] = time.monotonic()
        self.show_high_impact_alert(symbol, metrics["change"], metrics["quote_volume"], direction)

    def show_high_impact_alert(self, symbol, percent_change, quote_volume, direction):
        self.alert_symbol = symbol
        alert = self.alert_popup = Toplevel(self.root)
        alert.title("VaultSignalsAI ÔÇó High-impact movement")
        alert.configure(bg="#0d1117")
        alert.resizable(False, False)
        alert.transient(self.root)
        alert.attributes("-topmost", True)
        alert.protocol("WM_DELETE_WINDOW", self.dismiss_alert)

        width, height = 440, 275
        x = self.root.winfo_screenwidth() - width - 34
        y = 70
        alert.geometry(f"{width}x{height}+{x}+{y}")

        Label(alert, text="HIGH-IMPACT MARKET MOVEMENT", fg="#f5c95c", bg="#0d1117", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=22, pady=(20, 4))
        Label(alert, text=self.display_symbol(symbol), fg=TEXT, bg="#0d1117", font=("Segoe UI", 19, "bold")).pack(anchor="w", padx=22)
        colour = GREEN if percent_change > 0 else RED
        Label(
            alert,
            text=f"24H movement: {percent_change:+.2f}%  ÔÇó  {direction.title()} move",
            fg=colour,
            bg="#0d1117",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=22, pady=(6, 4))
        Label(
            alert,
            text=f"Detected: {datetime.now().strftime('%d %b %Y  ÔÇó  %H:%M:%S')}",
            fg="#8f9dab",
            bg="#0d1117",
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=22, pady=(0, 5))
        Label(
            alert,
            text=f"Quote volume: {self.format_compact_number(quote_volume)} USDT\n"
                 "This is a volatility alert based on public market data, not a profit guarantee or investment instruction.",
            fg="#b8c3cf",
            bg="#0d1117",
            justify=LEFT,
            wraplength=390,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=22, pady=(3, 15))

        actions = Frame(alert, bg="#0d1117")
        actions.pack(fill=X, padx=22, pady=(0, 18))
        self.create_button(actions, "Open market", self.open_alert_market, primary=True).pack(side=LEFT)
        self.create_button(actions, "Dismiss", self.dismiss_alert).pack(side=LEFT, padx=(8, 0))
        self.root.bell()

    def open_alert_market(self):
        self.dismiss_alert()
        self.show_main_workspace()
        self.follow_symbol.set(self.alert_symbol)
        self.profile_market.set(self.alert_symbol)
        self.open_followed_asset()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.last_update.set(f"Opened {self.display_symbol(self.alert_symbol)} after a high-impact movement alert.")

    def dismiss_alert(self):
        if self.alert_popup:
            self.alert_popup.destroy()
            self.alert_popup = None
        self.alert_symbol = ""

    def update_depth(self, data):
        asks = list(reversed(data.get("asks", [])[:6]))
        bids = data.get("bids", [])[:6]
        entries = asks + bids
        for index, (price_label, amount_label) in enumerate(self.depth_rows):
            if index < len(entries):
                price, amount = entries[index]
                price_label.configure(text=self.format_price(float(price)), fg=RED if index < len(asks) else GREEN)
                amount_label.configure(text=f"{float(amount):.4f}")
            else:
                price_label.configure(text="--")
                amount_label.configure(text="--")

    def update_candles(self, data):
        self.candles = [
            {
                "time": float(row[0]) / 1000,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
            for row in data
        ]
        self.visible_candle_count = min(self.visible_candle_count, len(self.candles))
        self.recalculate_scenario()
        self.update_chart_status()
        self.draw_chart()

    def zoom_in(self, _event=None):
        if not self.candles:
            return "break"
        self.visible_candle_count = max(MIN_VISIBLE_CANDLES, int(self.visible_candle_count / 1.35))
        self.update_chart_status()
        self.draw_chart()
        return "break"

    def zoom_out(self, _event=None):
        if not self.candles:
            return "break"
        self.visible_candle_count = min(len(self.candles), int(self.visible_candle_count * 1.35) + 1)
        self.update_chart_status()
        self.draw_chart()
        return "break"

    def reset_chart_zoom(self):
        if not self.candles:
            return
        self.visible_candle_count = min(DEFAULT_VISIBLE_CANDLES, len(self.candles))
        self.update_chart_status()
        self.draw_chart()

    def on_chart_wheel(self, event):
        return self.zoom_in() if event.delta > 0 else self.zoom_out()

    def update_chart_status(self):
        total = len(self.candles)
        visible = min(self.visible_candle_count, total)
        self.chart_status.configure(text=f"1H candles ÔÇó {visible} of {total} ÔÇó mouse wheel to zoom")
        self.zoom_label.configure(text=f"ZOOM: {visible} candles")

    @staticmethod
    def compute_signal(percent_change, volume_ratio):
        if percent_change > 1.2 and volume_ratio > 1.0:
            return "Bullish", 82, "Recent price strength is supported by active volume."
        if percent_change < -1.2 and volume_ratio < 1.0:
            return "Bearish", 78, "Recent weakness continues with softer participation."
        if abs(percent_change) < 0.6:
            return "Neutral", 58, "Price is contained and short-term direction is mixed."
        return "Watch", 66, "Momentum is present, but follow-through needs confirmation."

    def recalculate_scenario(self):
        if len(self.candles) < 24:
            self.scenario = None
            self.scenario_mid_text.set("Waiting for 24 candles")
            self.scenario_upper_text.set("Waiting for 24 candles")
            self.scenario_change_text.set("Waiting for 24 candles")
            return

        candles = self.candles[-min(SCENARIO_LOOKBACK_CANDLES, len(self.candles)):]
        closes = [candle["close"] for candle in candles]
        returns = [
            current / previous - 1
            for previous, current in zip(closes, closes[1:])
            if previous > 0
        ]
        if len(returns) < 12:
            self.scenario = None
            self.scenario_change_text.set("Waiting for candle history")
            return

        recent_returns = returns[-12:]
        drift = sum(recent_returns) / len(recent_returns)
        mean_return = sum(returns) / len(returns)
        volatility = math.sqrt(sum((value - mean_return) ** 2 for value in returns) / len(returns))
        volatility = max(volatility, 0.0025)

        recent_volume = sum(candle["volume"] for candle in candles[-12:]) / 12
        earlier_volume = sum(candle["volume"] for candle in candles[:-12]) / max(len(candles) - 12, 1)
        relative_volume = recent_volume / max(earlier_volume, 1.0)
        volume_adjustment = max(-1.0, min(relative_volume - 1.0, 1.0)) * 0.00035
        sentiment_adjustment = (self.social_sentiment_score or 0.0) / 100 * 0.00020
        hourly_drift = max(-0.004, min(drift + volume_adjustment + sentiment_adjustment, 0.004))
        reference_price = self.latest_price or closes[-1]

        points = [{"hour": 0, "midpoint": reference_price, "lower": reference_price, "upper": reference_price}]
        for hour in range(1, SCENARIO_HORIZON_HOURS + 1):
            midpoint = reference_price * (1 + hourly_drift * hour)
            spread = reference_price * volatility * math.sqrt(hour) * 1.15
            points.append(
                {
                    "hour": hour,
                    "midpoint": midpoint,
                    "lower": max(0.0, midpoint - spread),
                    "upper": midpoint + spread,
                }
            )

        final_point = points[-1]
        self.scenario = {
            "as_of": datetime.now(),
            "reference_price": reference_price,
            "points": points,
            "midpoint": final_point["midpoint"],
            "lower": final_point["lower"],
            "upper": final_point["upper"],
            "volatility": volatility,
        }
        self.scenario_mid_text.set(f"{self.format_price(final_point['midpoint'])} ÔÇó 12H")
        self.scenario_upper_text.set(f"{self.format_price(final_point['upper'])} ÔÇó 12H")
        midpoint_change = (final_point["midpoint"] / reference_price - 1) * 100
        upper_change = (final_point["upper"] / reference_price - 1) * 100
        self.scenario_change_text.set(f"Mid {midpoint_change:+.2f}% ÔÇó upper {upper_change:+.2f}%")

    def change_text_colour(self, percent_change):
        colour = GREEN if percent_change >= 0 else RED
        self.signal_value.configure(fg=colour if self.signal_text.get() != "WATCH" else BLUE)
        for child in self.workspace.grid_slaves(row=1, column=2):
            self.update_named_value_colour(child, self.change_text, colour)

    def update_named_value_colour(self, widget, value, colour):
        if isinstance(widget, Label) and str(widget.cget("textvariable")) == str(value):
            widget.configure(fg=colour)
        for child in widget.winfo_children():
            self.update_named_value_colour(child, value, colour)

    def draw_chart(self):
        canvas = self.chart_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 300)
        height = max(canvas.winfo_height(), 260)
        canvas.create_rectangle(0, 0, width, height, fill=BACKGROUND, outline="")

        chart_left = 16
        chart_right = width - 72
        chart_top = 18
        volume_height = max(58, int(height * 0.18))
        chart_bottom = height - volume_height - 22
        if chart_right <= chart_left or chart_bottom <= chart_top:
            return

        for index in range(6):
            y = chart_top + index * (chart_bottom - chart_top) / 5
            canvas.create_line(chart_left, y, chart_right, y, fill=GRID, width=1)
        for index in range(7):
            x = chart_left + index * (chart_right - chart_left) / 6
            canvas.create_line(x, chart_top, x, chart_bottom, fill="#11161d", width=1)

        if not self.candles:
            self.chart_view = None
            canvas.create_text(width / 2, height / 2, text="Loading live candle history...", fill=MUTED, font=("Segoe UI", 11))
            return

        visible = self.candles[-min(self.visible_candle_count, len(self.candles)):]
        scenario = self.scenario if self.scenario_overlay_enabled.get() and self.scenario else None
        forecast_width = min(170, (chart_right - chart_left) * 0.24) if scenario else 0
        history_right = chart_right - forecast_width
        lows = [item["low"] for item in visible]
        highs = [item["high"] for item in visible]
        if scenario:
            lows.extend(point["lower"] for point in scenario["points"])
            highs.extend(point["upper"] for point in scenario["points"])
        low_value = min(lows)
        high_value = max(highs)
        price_range = max(high_value - low_value, max(high_value * 0.002, 0.01))
        padding = price_range * 0.05
        low_value -= padding
        high_value += padding
        price_range = high_value - low_value
        max_volume = max(item["volume"] for item in visible) or 1.0
        step = (history_right - chart_left) / len(visible)
        body_width = max(1, min(8, step * 0.62))
        self.chart_view = {
            "candles": visible,
            "chart_left": chart_left,
            "chart_right": history_right,
            "chart_top": chart_top,
            "chart_bottom": chart_bottom,
            "low_value": low_value,
            "price_range": price_range,
            "step": step,
        }

        for index, candle in enumerate(visible):
            x = chart_left + (index + 0.5) * step
            y_high = self.price_to_y(candle["high"], low_value, price_range, chart_top, chart_bottom)
            y_low = self.price_to_y(candle["low"], low_value, price_range, chart_top, chart_bottom)
            y_open = self.price_to_y(candle["open"], low_value, price_range, chart_top, chart_bottom)
            y_close = self.price_to_y(candle["close"], low_value, price_range, chart_top, chart_bottom)
            colour = GREEN if candle["close"] >= candle["open"] else RED
            canvas.create_line(x, y_high, x, y_low, fill=colour, width=1)
            canvas.create_rectangle(x - body_width / 2, min(y_open, y_close), x + body_width / 2, max(y_open, y_close, min(y_open, y_close) + 1), fill=colour, outline=colour)

            volume_top = chart_bottom + 9
            volume_bottom = height - 16
            volume_bar_height = (candle["volume"] / max_volume) * (volume_bottom - volume_top)
            canvas.create_rectangle(x - body_width / 2, volume_bottom - volume_bar_height, x + body_width / 2, volume_bottom, fill=colour, outline="")

        if scenario:
            self.draw_scenario_overlay(
                canvas,
                scenario,
                history_right,
                chart_right,
                chart_top,
                chart_bottom,
                low_value,
                price_range,
            )

        for index in range(6):
            value = high_value - index * price_range / 5
            y = chart_top + index * (chart_bottom - chart_top) / 5
            canvas.create_text(chart_right + 8, y, text=self.format_price(value), fill=MUTED, anchor="w", font=("Cascadia Mono", 8))

        for index in range(5):
            candle = visible[round(index * (len(visible) - 1) / 4)]
            date_label = datetime.fromtimestamp(candle["time"]).strftime("%d %b")
            x = chart_left + index * (history_right - chart_left) / 4
            canvas.create_text(x, height - 5, text=date_label, fill="#64707d", anchor="s", font=("Segoe UI", 8))

        if self.latest_price is not None:
            y = self.price_to_y(self.latest_price, low_value, price_range, chart_top, chart_bottom)
            if chart_top <= y <= chart_bottom:
                canvas.create_line(chart_left, y, history_right, y, fill="#367560", dash=(3, 4))
                canvas.create_text(chart_right + 8, y, text=self.format_price(self.latest_price), fill="#9cf0cc", anchor="w", font=("Cascadia Mono", 8, "bold"))

    def draw_scenario_overlay(self, canvas, scenario, start_x, end_x, chart_top, chart_bottom, low_value, price_range):
        points = scenario["points"]
        width = end_x - start_x
        colour = GREEN if scenario["midpoint"] >= scenario["reference_price"] else RED
        fill = "#102b23" if colour == GREEN else "#2a151b"
        coordinates = []
        for point in points:
            x = start_x + width * point["hour"] / SCENARIO_HORIZON_HOURS
            y = self.price_to_y(point["upper"], low_value, price_range, chart_top, chart_bottom)
            coordinates.extend((x, y))
        for point in reversed(points):
            x = start_x + width * point["hour"] / SCENARIO_HORIZON_HOURS
            y = self.price_to_y(point["lower"], low_value, price_range, chart_top, chart_bottom)
            coordinates.extend((x, y))
        canvas.create_polygon(*coordinates, fill=fill, outline="", stipple="gray25")
        canvas.create_line(start_x, chart_top, start_x, chart_bottom, fill="#526171", dash=(3, 3))

        midpoint_coordinates = []
        for point in points:
            x = start_x + width * point["hour"] / SCENARIO_HORIZON_HOURS
            y = self.price_to_y(point["midpoint"], low_value, price_range, chart_top, chart_bottom)
            midpoint_coordinates.extend((x, y))
        canvas.create_line(*midpoint_coordinates, fill=colour, width=2, dash=(5, 3))
        canvas.create_text(
            start_x + 6,
            chart_top + 10,
            text="12H SCENARIO",
            fill="#b9c6d2",
            anchor="w",
            font=("Segoe UI", 7, "bold"),
        )

    def on_chart_motion(self, event):
        if not self.chart_view:
            return

        view = self.chart_view
        if not (view["chart_left"] <= event.x <= view["chart_right"] and view["chart_top"] <= event.y <= view["chart_bottom"]):
            self.clear_chart_crosshair()
            return

        index = min(int((event.x - view["chart_left"]) / view["step"]), len(view["candles"]) - 1)
        candle = view["candles"][index]
        x = view["chart_left"] + (index + 0.5) * view["step"]
        price = view["low_value"] + ((view["chart_bottom"] - event.y) / (view["chart_bottom"] - view["chart_top"])) * view["price_range"]
        detail = (
            f"{datetime.fromtimestamp(candle['time']).strftime('%d %b %Y %H:%M')}   "
            f"O {self.format_price(candle['open'])}   H {self.format_price(candle['high'])}   "
            f"L {self.format_price(candle['low'])}   C {self.format_price(candle['close'])}"
        )

        self.chart_canvas.delete("crosshair")
        self.chart_canvas.create_line(x, view["chart_top"], x, view["chart_bottom"], fill="#56616f", dash=(3, 3), tags="crosshair")
        self.chart_canvas.create_line(view["chart_left"], event.y, view["chart_right"], event.y, fill="#56616f", dash=(3, 3), tags="crosshair")
        self.chart_canvas.create_rectangle(
            view["chart_left"] + 7,
            view["chart_top"] + 7,
            view["chart_left"] + 370,
            view["chart_top"] + 29,
            fill="#10151d",
            outline="#2a3442",
            tags="crosshair",
        )
        self.chart_canvas.create_text(
            view["chart_left"] + 13,
            view["chart_top"] + 18,
            text=detail,
            fill="#d7e0eb",
            anchor="w",
            font=("Cascadia Mono", 7),
            tags="crosshair",
        )
        self.chart_canvas.create_text(
            view["chart_right"] + 8,
            event.y,
            text=self.format_price(price),
            fill="#d7e0eb",
            anchor="w",
            font=("Cascadia Mono", 8, "bold"),
            tags="crosshair",
        )

    def clear_chart_crosshair(self, _event=None):
        self.chart_canvas.delete("crosshair")

    @staticmethod
    def price_to_y(value, low_value, price_range, chart_top, chart_bottom):
        return chart_bottom - ((value - low_value) / price_range) * (chart_bottom - chart_top)

    @staticmethod
    def format_price(value):
        if value >= 1000:
            return f"${value:,.2f}"
        if value >= 1:
            return f"${value:,.4f}"
        return f"${value:.6f}"

    @staticmethod
    def format_compact_number(value):
        if value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.2f}B"
        if value >= 1_000_000:
            return f"{value / 1_000_000:.2f}M"
        if value >= 1_000:
            return f"{value / 1_000:.2f}K"
        return f"{value:.0f}"

    def toggle_fullscreen(self, _event=None):
        self.is_fullscreen = not self.is_fullscreen
        self.root.attributes("-fullscreen", self.is_fullscreen)
        self.fullscreen_button.configure(text="Exit full screen" if self.is_fullscreen else "Full screen")

    def exit_fullscreen(self, _event=None):
        if self.is_fullscreen:
            self.toggle_fullscreen()

    def minimize_window(self):
        self.exit_fullscreen()
        self.root.iconify()

    def close_window(self):
        self.running = False
        self.root.destroy()


def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
        except AttributeError:
            pass

    root = Tk()
    root.withdraw()
    MarketSignalApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
