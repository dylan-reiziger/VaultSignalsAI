from __future__ import annotations

import json
import os
import queue
import secrets
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener

import tkinter as tk
from tkinter import messagebox, ttk

try:
    import ctypes
except Exception:
    ctypes = None

try:
    from plyer import notification as plyer_notification
except Exception:
    plyer_notification = None

APP_NAME = "VaultSignalsAI"
APP_DIR = Path(__file__).resolve().parent
LEGACY_CONFIG_PATH = APP_DIR / "client_config.json"
CONFIG_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / APP_NAME / "client_config.json"

MARKETS = ("NASDAQ", "NYSE", "SP500", "CRYPTO")
SYMBOLS_BY_MARKET = {
    "NASDAQ": ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META"],
    "NYSE": ["JPM", "KO", "DIS", "BA", "WMT", "NKE"],
    "SP500": ["SPY", "QQQ", "IWM", "DIA", "VOO", "VTI"],
    "CRYPTO": ["BTCUSD", "ETHUSD", "SOLUSD", "ADAUSD", "XRPUSD"],
}
RNG = secrets.SystemRandom()

FULL_WINDOW_GEOMETRY = "1020x620"
FULL_WINDOW_MINSIZE = (680, 420)
COMPACT_WINDOW_GEOMETRY = "720x340"
COMPACT_WINDOW_MINSIZE = (600, 300)
TASKBAR_SAFE_MODE = True
VIEW_MODES = ("Feed", "Account", "Settings")


@dataclass
class ClientConfig:
    website_url: str = "http://127.0.0.1:5000"
    username: str = ""
    discord_webhook: str = ""
    market: str = "NASDAQ"
    sync_seconds: int = 5
    compact_mode: bool = False
    windows_notifications: bool = True
    in_app_notifications: bool = True


def load_config() -> ClientConfig:
    source_path = CONFIG_PATH if CONFIG_PATH.exists() else LEGACY_CONFIG_PATH
    if not source_path.exists():
        return ClientConfig()

    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ClientConfig()

    if not isinstance(payload, dict):
        return ClientConfig()

    config = ClientConfig()
    config.website_url = str(payload.get("website_url") or config.website_url)
    config.username = str(payload.get("username") or config.username)
    config.discord_webhook = str(payload.get("discord_webhook") or config.discord_webhook)

    market = str(payload.get("market") or config.market).upper()
    config.market = market if market in MARKETS else config.market

    sync_seconds = payload.get("sync_seconds")
    if isinstance(sync_seconds, int) and 5 <= sync_seconds <= 3600:
        config.sync_seconds = sync_seconds

    config.compact_mode = bool(payload.get("compact_mode", config.compact_mode))
    config.windows_notifications = bool(
        payload.get("windows_notifications", config.windows_notifications)
    )
    config.in_app_notifications = bool(
        payload.get("in_app_notifications", config.in_app_notifications)
    )
    return config


def save_config(config: ClientConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")


class VaultSignalsApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = load_config()

        self.logged_in = False
        self.sync_running = False
        self.stop_event = threading.Event()
        self.sync_thread: threading.Thread | None = None
        self.event_queue: queue.Queue[dict] = queue.Queue()

        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.appwindow_style_ready = False

        self.preview_mode_login = False
        self.website_cookie_jar = CookieJar()
        self.website_opener = build_opener(HTTPCookieProcessor(self.website_cookie_jar))
        self.known_signal_keys: set[str] = set()
        self.known_signal_order: list[str] = []

        self.sync_market = self.config.market
        self.sync_seconds = self.config.sync_seconds
        self.sync_discord_webhook = self.config.discord_webhook
        self.sync_windows_notifications = self.config.windows_notifications
        self.sync_in_app_notifications = self.config.in_app_notifications

        self.root.title(APP_NAME)
        self.root.geometry(FULL_WINDOW_GEOMETRY)
        self.root.minsize(*FULL_WINDOW_MINSIZE)
        self.root.configure(bg="#0a0d14")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        if not TASKBAR_SAFE_MODE:
            self.root.overrideredirect(True)
            self.root.bind("<Map>", self.on_map_event)

        self.setup_styles()
        self.build_layout()
        self.restore_state_from_config()
        self.root.after(120, self.enable_alt_tab_visibility)

        self.root.after(220, self.drain_event_queue)

    def setup_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(
            "Signals.Treeview",
            background="#121824",
            fieldbackground="#121824",
            foreground="#dfe8ff",
            borderwidth=0,
            rowheight=24,
        )
        style.map("Signals.Treeview", background=[("selected", "#1f2a44")])

        style.configure(
            "Signals.Treeview.Heading",
            background="#0f1520",
            foreground="#9fb4db",
            relief="flat",
            borderwidth=0,
            font=("Segoe UI Semibold", 10),
        )

        style.configure(
            "Signals.TCombobox",
            fieldbackground="#1a2233",
            background="#1a2233",
            foreground="#f0f4ff",
            arrowcolor="#f0f4ff",
            borderwidth=0,
        )

    def build_layout(self) -> None:
        self.shell = tk.Frame(
            self.root,
            bg="#0b1019",
            highlightthickness=1,
            highlightbackground="#1f2a3c",
        )
        self.shell.pack(fill="both", expand=True, padx=10, pady=10)

        self.build_title_bar()

        self.content = tk.Frame(self.shell, bg="#0d131f")
        self.content.pack(fill="both", expand=True, padx=12, pady=(10, 12))
        self.content.grid_columnconfigure(0, weight=0, minsize=280)
        self.content.grid_columnconfigure(1, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.left_panel = tk.Frame(self.content, bg="#0f1625")
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        self.right_panel = tk.Frame(self.content, bg="#111a2a")
        self.right_panel.grid(row=0, column=1, sticky="nsew")

        self.build_notifications_panel()
        self.build_account_panel()
        self.build_sync_panel()
        self.build_signal_panel()
        self.build_compact_settings_panel()

    def build_title_bar(self) -> None:
        self.title_bar = tk.Frame(self.shell, bg="#111722", height=48)
        self.title_bar.pack(fill="x", padx=1, pady=1)
        self.title_bar.pack_propagate(False)
        self.title_bar.grid_columnconfigure(1, weight=1)

        self.left_header_controls = tk.Frame(self.title_bar, bg="#111722")
        self.left_header_controls.grid(row=0, column=0, sticky="w", padx=8)

        self.view_mode_var = tk.StringVar(value="Feed")

        self.settings_button = self.make_header_button(
            self.left_header_controls,
            text="Settings",
            command=self.focus_settings,
        )
        self.settings_button.pack(side="left", padx=(0, 6), pady=8)

        self.account_button = self.make_header_button(
            self.left_header_controls,
            text="Account",
            command=self.focus_account,
        )
        self.account_button.pack(side="left", padx=(0, 6), pady=8)

        self.compact_button = self.make_header_button(
            self.left_header_controls,
            text="Compact",
            command=self.toggle_compact_mode,
            width=10,
        )
        self.compact_button.pack(side="left", pady=8)

        self.title_label = tk.Label(
            self.title_bar,
            text=APP_NAME,
            bg="#111722",
            fg="#f2f5ff",
            font=("Bahnschrift SemiBold", 15),
        )
        self.title_label.grid(row=0, column=1, sticky="nsew")

        self.right_header_controls = tk.Frame(self.title_bar, bg="#111722")
        self.right_header_controls.grid(row=0, column=2, sticky="e", padx=8)

        self.pin_button = self.make_header_button(
            self.right_header_controls,
            text="Pin",
            command=self.toggle_pin,
            width=5,
        )
        self.pin_button.pack(side="left", padx=(0, 6), pady=8)

        self.minimize_button = self.make_header_button(
            self.right_header_controls,
            text="-",
            command=self.minimize_window,
            width=4,
        )
        self.minimize_button.pack(side="left", padx=(0, 6), pady=8)

        self.close_button = tk.Button(
            self.right_header_controls,
            text="X",
            width=4,
            command=self.on_close,
            bg="#312029",
            activebackground="#b73755",
            fg="#ffdce6",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("Segoe UI Semibold", 10),
            cursor="hand2",
        )
        self.close_button.pack(side="left", pady=8)

        for drag_widget in (self.title_bar, self.title_label):
            drag_widget.bind("<ButtonPress-1>", self.start_drag)
            drag_widget.bind("<B1-Motion>", self.drag_window)

    def make_header_button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        width: int = 8,
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            width=width,
            command=command,
            bg="#1b2434",
            activebackground="#2c3a54",
            fg="#dbe7ff",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        )

    def build_notifications_panel(self) -> None:
        self.notifications_card = tk.Frame(
            self.left_panel,
            bg="#111a2b",
            highlightthickness=1,
            highlightbackground="#263350",
        )
        self.notifications_card.pack(fill="x", padx=12, pady=(12, 8))

        header = tk.Frame(self.notifications_card, bg="#111a2b")
        header.pack(fill="x", padx=12, pady=(12, 8))

        tk.Label(
            header,
            text="Website Notifications",
            bg="#111a2b",
            fg="#f2f5ff",
            font=("Segoe UI Semibold", 13),
        ).pack(side="left")

        tk.Button(
            header,
            text="Clear",
            command=self.clear_notifications,
            bg="#2f3240",
            activebackground="#50576d",
            fg="#d7dded",
            relief="flat",
            bd=0,
            padx=10,
            pady=5,
            font=("Segoe UI Semibold", 8),
            cursor="hand2",
        ).pack(side="right")

        list_wrap = tk.Frame(self.notifications_card, bg="#111a2b")
        list_wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.notification_list = tk.Listbox(
            list_wrap,
            bg="#0f1521",
            fg="#dbe7ff",
            selectbackground="#1f2a44",
            selectforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#2e3d5c",
            font=("Consolas", 9),
            activestyle="none",
            exportselection=False,
            height=10,
        )
        self.notification_list.pack(side="left", fill="both", expand=True)
        self.notification_list.insert(
            "end",
            "Waiting for website signals. Start sync after account login.",
        )

    def clear_notifications(self) -> None:
        self.notification_list.delete(0, "end")

    def apply_navigation_view(self, view_name: str | None = None, announce: bool = False) -> None:
        selected_view = str(view_name or "Feed").strip().title()
        if selected_view not in VIEW_MODES:
            selected_view = "Feed"

        if self.view_mode_var.get() != selected_view:
            self.view_mode_var.set(selected_view)

        if self.config.compact_mode:
            return

        if selected_view == "Feed":
            self.right_panel.grid(row=0, column=1, sticky="nsew")
            self.left_panel.grid(row=0, column=0, columnspan=1, sticky="nsew", padx=(0, 12))
            self.content.grid_columnconfigure(0, weight=0, minsize=280)
            self.content.grid_columnconfigure(1, weight=1, minsize=0)
            self.notifications_card.pack_forget()
            self.account_card.pack_forget()
            self.settings_card.pack_forget()
            self.notifications_card.pack(fill="x", padx=12, pady=(12, 8))
            self.settings_card.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        elif selected_view == "Account":
            self.right_panel.grid_remove()
            self.left_panel.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=0)
            self.content.grid_columnconfigure(0, weight=1, minsize=0)
            self.content.grid_columnconfigure(1, weight=0, minsize=0)
            self.notifications_card.pack_forget()
            self.account_card.pack_forget()
            self.settings_card.pack_forget()
            self.account_card.pack(fill="both", expand=True, padx=12, pady=12)
        else:
            self.right_panel.grid_remove()
            self.left_panel.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=0)
            self.content.grid_columnconfigure(0, weight=1, minsize=0)
            self.content.grid_columnconfigure(1, weight=0, minsize=0)
            self.notifications_card.pack_forget()
            self.account_card.pack_forget()
            self.settings_card.pack_forget()
            self.settings_card.pack(fill="both", expand=True, padx=12, pady=12)

        if announce:
            self.status_var.set(f"{selected_view} view enabled.")

    def build_account_panel(self) -> None:
        self.account_card = tk.Frame(
            self.left_panel,
            bg="#111a2b",
            highlightthickness=1,
            highlightbackground="#263350",
        )
        self.account_card.pack(fill="x", padx=12, pady=(12, 8))

        tk.Label(
            self.account_card,
            text="Client Account",
            bg="#111a2b",
            fg="#f2f5ff",
            font=("Segoe UI Semibold", 13),
        ).pack(anchor="w", padx=12, pady=(12, 2))

        tk.Label(
            self.account_card,
            text="Login is required before auto-sync can run.",
            bg="#111a2b",
            fg="#8fa4cb",
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=12, pady=(0, 10))

        self.website_url_var = tk.StringVar(value=self.config.website_url)
        self.username_var = tk.StringVar(value=self.config.username)
        self.password_var = tk.StringVar(value="")
        self.account_status_var = tk.StringVar(value="Not logged in")

        self.website_entry = self.add_labeled_entry(
            self.account_card,
            "Website URL",
            self.website_url_var,
        )
        self.username_entry = self.add_labeled_entry(
            self.account_card,
            "Client Username",
            self.username_var,
        )
        self.password_entry = self.add_labeled_entry(
            self.account_card,
            "Password",
            self.password_var,
            show="*",
        )

        button_row = tk.Frame(self.account_card, bg="#111a2b")
        button_row.pack(fill="x", padx=12, pady=(10, 4))

        self.login_button = tk.Button(
            button_row,
            text="Login",
            command=self.login_to_website,
            bg="#204c78",
            activebackground="#2a659c",
            fg="#eaf3ff",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        )
        self.login_button.pack(side="left", padx=(0, 8))

        self.logout_button = tk.Button(
            button_row,
            text="Logout",
            command=self.logout_client,
            bg="#2f3240",
            activebackground="#50576d",
            fg="#d7dded",
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        )
        self.logout_button.pack(side="left")

        tk.Label(
            self.account_card,
            textvariable=self.account_status_var,
            bg="#111a2b",
            fg="#9fd4aa",
            font=("Segoe UI", 9),
            wraplength=300,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(6, 12))

    def build_sync_panel(self) -> None:
        self.settings_card = tk.Frame(
            self.left_panel,
            bg="#111a2b",
            highlightthickness=1,
            highlightbackground="#263350",
        )
        self.settings_card.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        tk.Label(
            self.settings_card,
            text="Signal Sync Settings",
            bg="#111a2b",
            fg="#f2f5ff",
            font=("Segoe UI Semibold", 13),
        ).pack(anchor="w", padx=12, pady=(12, 8))

        self.discord_webhook_var = tk.StringVar(value=self.config.discord_webhook)
        self.discord_entry = self.add_labeled_entry(
            self.settings_card,
            "Discord Webhook URL",
            self.discord_webhook_var,
        )

        market_row = tk.Frame(self.settings_card, bg="#111a2b")
        market_row.pack(fill="x", padx=12, pady=(8, 0))

        tk.Label(
            market_row,
            text="Market",
            bg="#111a2b",
            fg="#9fb4db",
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        self.market_var = tk.StringVar(value=self.config.market)
        self.market_combo = ttk.Combobox(
            market_row,
            textvariable=self.market_var,
            values=MARKETS,
            state="readonly",
            style="Signals.TCombobox",
        )
        self.market_combo.pack(fill="x", pady=(4, 0))

        self.sync_seconds_var = tk.StringVar(value=str(self.config.sync_seconds))
        self.add_labeled_entry(
            self.settings_card,
            "Auto Sync Interval (seconds)",
            self.sync_seconds_var,
        )

        self.in_app_notify_var = tk.BooleanVar(value=self.config.in_app_notifications)
        self.windows_notify_var = tk.BooleanVar(value=self.config.windows_notifications)

        check_row = tk.Frame(self.settings_card, bg="#111a2b")
        check_row.pack(fill="x", padx=12, pady=(10, 0))

        in_app_check = tk.Checkbutton(
            check_row,
            text="In-app notifications",
            variable=self.in_app_notify_var,
            bg="#111a2b",
            fg="#dbe7ff",
            activebackground="#111a2b",
            activeforeground="#dbe7ff",
            selectcolor="#1f2a40",
            font=("Segoe UI", 9),
        )
        in_app_check.pack(anchor="w")

        windows_check = tk.Checkbutton(
            check_row,
            text="Windows notifications",
            variable=self.windows_notify_var,
            bg="#111a2b",
            fg="#dbe7ff",
            activebackground="#111a2b",
            activeforeground="#dbe7ff",
            selectcolor="#1f2a40",
            font=("Segoe UI", 9),
        )
        windows_check.pack(anchor="w", pady=(2, 0))

        controls = tk.Frame(self.settings_card, bg="#111a2b")
        controls.pack(fill="x", padx=12, pady=(12, 4))

        self.start_button = tk.Button(
            controls,
            text="Start Auto Sync",
            command=self.start_auto_sync,
            bg="#1f7a48",
            activebackground="#299f5d",
            fg="#f0fff7",
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        )
        self.start_button.pack(side="left", padx=(0, 8))

        self.stop_button = tk.Button(
            controls,
            text="Stop",
            command=self.stop_auto_sync,
            state="disabled",
            bg="#4a2d34",
            activebackground="#6f404b",
            fg="#ffe7ed",
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        )
        self.stop_button.pack(side="left")

    def build_signal_panel(self) -> None:
        top_row = tk.Frame(self.right_panel, bg="#111a2a")
        top_row.pack(fill="x", padx=14, pady=(14, 10))

        tk.Label(
            top_row,
            text="Live Signal Feed",
            bg="#111a2a",
            fg="#f2f5ff",
            font=("Segoe UI Semibold", 14),
        ).pack(side="left")

        tk.Button(
            top_row,
            text="Send Test Signal",
            command=self.send_test_signal,
            bg="#2b436f",
            activebackground="#3a5a8f",
            fg="#eff4ff",
            relief="flat",
            bd=0,
            padx=11,
            pady=6,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        ).pack(side="right")

        table_wrap = tk.Frame(self.right_panel, bg="#111a2a")
        table_wrap.pack(fill="both", expand=True, padx=14)

        columns = ("time", "market", "symbol", "signal", "price", "delivery")
        self.signal_tree = ttk.Treeview(
            table_wrap,
            columns=columns,
            show="headings",
            style="Signals.Treeview",
        )

        headings = {
            "time": "Time",
            "market": "Market",
            "symbol": "Symbol",
            "signal": "Signal",
            "price": "Price",
            "delivery": "Delivery",
        }
        widths = {
            "time": 108,
            "market": 92,
            "symbol": 92,
            "signal": 88,
            "price": 100,
            "delivery": 180,
        }

        for key in columns:
            self.signal_tree.heading(key, text=headings[key])
            self.signal_tree.column(key, width=widths[key], anchor="center")

        scrollbar = ttk.Scrollbar(table_wrap, orient="vertical", command=self.signal_tree.yview)
        self.signal_tree.configure(yscrollcommand=scrollbar.set)

        self.signal_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.signal_tree.bind("<MouseWheel>", self.on_signal_mousewheel)
        self.signal_tree.bind("<Button-4>", self.on_signal_scroll_up)
        self.signal_tree.bind("<Button-5>", self.on_signal_scroll_down)

        self.status_var = tk.StringVar(value="Ready. Login to start auto-sync.")
        status_bar = tk.Label(
            self.right_panel,
            textvariable=self.status_var,
            bg="#0f1624",
            fg="#90a8d4",
            anchor="w",
            padx=12,
            pady=8,
            font=("Segoe UI", 9),
        )
        status_bar.pack(fill="x", padx=14, pady=(10, 14))

    def build_compact_settings_panel(self) -> None:
        self.compact_settings_panel = tk.Frame(
            self.content,
            bg="#111a2a",
            highlightthickness=1,
            highlightbackground="#253554",
        )
        self.compact_settings_panel.grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="nsew",
        )
        self.compact_settings_panel.grid_remove()

        header = tk.Frame(self.compact_settings_panel, bg="#111a2a")
        header.pack(fill="x", padx=16, pady=(14, 10))

        tk.Label(
            header,
            text="Compact Settings",
            bg="#111a2a",
            fg="#f2f5ff",
            font=("Segoe UI Semibold", 14),
        ).pack(anchor="w")

        tk.Label(
            header,
            text="Quick account + sync controls in a tighter layout.",
            bg="#111a2a",
            fg="#8fa6d2",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))

        account_row = tk.Frame(self.compact_settings_panel, bg="#111a2a")
        account_row.pack(fill="x", padx=16, pady=(0, 8))
        account_row.grid_columnconfigure(0, weight=2)
        account_row.grid_columnconfigure(1, weight=1)
        account_row.grid_columnconfigure(2, weight=1)

        self.compact_website_entry = self.make_compact_entry(
            account_row,
            "Website",
            self.website_url_var,
            row=0,
            column=0,
            sticky="ew",
            padx=(0, 8),
        )
        self.compact_username_entry = self.make_compact_entry(
            account_row,
            "Username",
            self.username_var,
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
        )
        self.compact_password_entry = self.make_compact_entry(
            account_row,
            "Password",
            self.password_var,
            row=0,
            column=2,
            sticky="ew",
            show="*",
        )

        account_actions = tk.Frame(self.compact_settings_panel, bg="#111a2a")
        account_actions.pack(fill="x", padx=16, pady=(0, 8))

        tk.Button(
            account_actions,
            text="Login",
            command=self.login_to_website,
            bg="#204c78",
            activebackground="#2a659c",
            fg="#eaf3ff",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            account_actions,
            text="Logout",
            command=self.logout_client,
            bg="#2f3240",
            activebackground="#50576d",
            fg="#d7dded",
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        ).pack(side="left")

        sync_row = tk.Frame(self.compact_settings_panel, bg="#111a2a")
        sync_row.pack(fill="x", padx=16, pady=(0, 8))
        sync_row.grid_columnconfigure(0, weight=2)
        sync_row.grid_columnconfigure(1, weight=0)
        sync_row.grid_columnconfigure(2, weight=0)

        self.compact_discord_entry = self.make_compact_entry(
            sync_row,
            "Discord Webhook",
            self.discord_webhook_var,
            row=0,
            column=0,
            sticky="ew",
            padx=(0, 8),
        )

        market_wrap = tk.Frame(sync_row, bg="#111a2a")
        market_wrap.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        tk.Label(
            market_wrap,
            text="Market",
            bg="#111a2a",
            fg="#8ea6d3",
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        self.compact_market_combo = ttk.Combobox(
            market_wrap,
            textvariable=self.market_var,
            values=MARKETS,
            state="readonly",
            style="Signals.TCombobox",
            width=12,
        )
        self.compact_market_combo.pack(fill="x", pady=(3, 0))

        self.compact_seconds_entry = self.make_compact_entry(
            sync_row,
            "Second",
            self.sync_seconds_var,
            row=0,
            column=2,
            width=9,
        )

        sync_actions = tk.Frame(self.compact_settings_panel, bg="#111a2a")
        sync_actions.pack(fill="x", padx=16, pady=(0, 8))

        self.compact_toggle_button = tk.Button(
            sync_actions,
            text="Start Sync",
            command=self.toggle_sync_from_compact,
            bg="#1f7a48",
            activebackground="#299f5d",
            fg="#f0fff7",
            relief="flat",
            bd=0,
            padx=14,
            pady=8,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        )
        self.compact_toggle_button.pack(side="left", padx=(0, 8))

        tk.Button(
            sync_actions,
            text="Send Test Signal",
            command=self.send_test_signal,
            bg="#2b436f",
            activebackground="#3a5a8f",
            fg="#eff4ff",
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        ).pack(side="left")

        notify_row = tk.Frame(self.compact_settings_panel, bg="#111a2a")
        notify_row.pack(fill="x", padx=16, pady=(0, 8))

        tk.Checkbutton(
            notify_row,
            text="In-app notifications",
            variable=self.in_app_notify_var,
            bg="#111a2a",
            fg="#dbe7ff",
            activebackground="#111a2a",
            activeforeground="#dbe7ff",
            selectcolor="#1f2a40",
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 12))

        tk.Checkbutton(
            notify_row,
            text="Windows notifications",
            variable=self.windows_notify_var,
            bg="#111a2a",
            fg="#dbe7ff",
            activebackground="#111a2a",
            activeforeground="#dbe7ff",
            selectcolor="#1f2a40",
            font=("Segoe UI", 9),
        ).pack(side="left")

        status_wrap = tk.Frame(self.compact_settings_panel, bg="#111a2a")
        status_wrap.pack(fill="x", padx=16, pady=(0, 14))

        tk.Label(
            status_wrap,
            textvariable=self.account_status_var,
            bg="#111a2a",
            fg="#9fd4aa",
            anchor="w",
            font=("Segoe UI", 9),
        ).pack(fill="x")

        tk.Label(
            status_wrap,
            textvariable=self.status_var,
            bg="#111a2a",
            fg="#90a8d4",
            anchor="w",
            font=("Segoe UI", 9),
        ).pack(fill="x", pady=(2, 0))

    def make_compact_entry(
        self,
        parent: tk.Widget,
        label_text: str,
        text_var: tk.StringVar,
        row: int,
        column: int,
        sticky: str = "w",
        padx: tuple[int, int] | int = (0, 0),
        width: int = 16,
        show: str | None = None,
    ) -> tk.Entry:
        wrap = tk.Frame(parent, bg="#111a2a")
        wrap.grid(row=row, column=column, sticky=sticky, padx=padx)

        tk.Label(
            wrap,
            text=label_text,
            bg="#111a2a",
            fg="#8ea6d3",
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        entry = tk.Entry(
            wrap,
            textvariable=text_var,
            show=show,
            width=width,
            bg="#1a2233",
            fg="#f4f7ff",
            insertbackground="#f4f7ff",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#2e3d5c",
            highlightcolor="#4a6faa",
            font=("Segoe UI", 10),
        )
        entry.pack(fill="x", pady=(3, 0), ipady=6)
        return entry

    def add_labeled_entry(
        self,
        parent: tk.Widget,
        label_text: str,
        text_var: tk.StringVar,
        show: str | None = None,
    ) -> tk.Entry:
        wrapper = tk.Frame(parent, bg="#111a2b")
        wrapper.pack(fill="x", padx=12, pady=(8, 0))

        tk.Label(
            wrapper,
            text=label_text,
            bg="#111a2b",
            fg="#9fb4db",
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        entry = tk.Entry(
            wrapper,
            textvariable=text_var,
            show=show,
            bg="#1a2233",
            fg="#f4f7ff",
            insertbackground="#f4f7ff",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#2e3d5c",
            highlightcolor="#4a6faa",
            font=("Segoe UI", 10),
        )
        entry.pack(fill="x", pady=(4, 0), ipady=7)
        return entry

    def restore_state_from_config(self) -> None:
        if self.config.compact_mode:
            self.set_compact_mode(True)
        else:
            self.apply_navigation_view("Feed")

    def start_drag(self, event: tk.Event) -> None:
        self.drag_offset_x = event.x
        self.drag_offset_y = event.y

    def drag_window(self, _event: tk.Event) -> None:
        x = self.root.winfo_pointerx() - self.drag_offset_x
        y = self.root.winfo_pointery() - self.drag_offset_y
        self.root.geometry(f"+{x}+{y}")

    def on_map_event(self, _event: tk.Event) -> None:
        if TASKBAR_SAFE_MODE:
            return
        if self.root.state() == "normal":
            self.root.overrideredirect(True)
            self.enable_alt_tab_visibility()

    def enable_alt_tab_visibility(self) -> None:
        if TASKBAR_SAFE_MODE:
            return
        if ctypes is None:
            return

        try:
            user32 = ctypes.windll.user32
            hwnd = self.root.winfo_id()

            gwl_exstyle = -20
            ws_ex_appwindow = 0x00040000
            ws_ex_toolwindow = 0x00000080

            ex_style = user32.GetWindowLongW(hwnd, gwl_exstyle)
            updated_style = (ex_style & ~ws_ex_toolwindow) | ws_ex_appwindow

            if updated_style != ex_style:
                user32.SetWindowLongW(hwnd, gwl_exstyle, updated_style)

            if not self.appwindow_style_ready:
                self.appwindow_style_ready = True
                self.root.withdraw()
                self.root.after(25, self.root.deiconify)
        except Exception:
            return

    def minimize_window(self) -> None:
        if not TASKBAR_SAFE_MODE:
            self.root.overrideredirect(False)
        self.root.iconify()

    def toggle_pin(self) -> None:
        is_pinned = bool(self.root.attributes("-topmost"))
        next_value = not is_pinned
        self.root.attributes("-topmost", next_value)
        self.pin_button.configure(text="Unpin" if next_value else "Pin")

    def toggle_compact_mode(self) -> None:
        self.set_compact_mode(not self.config.compact_mode)

    def toggle_sync_from_compact(self) -> None:
        if self.sync_running:
            self.stop_auto_sync()
        else:
            self.start_auto_sync()

    def set_compact_mode(self, compact_mode: bool) -> None:
        self.config.compact_mode = compact_mode
        if compact_mode:
            self.left_panel.grid_remove()
            self.right_panel.grid_remove()
            self.compact_settings_panel.grid()
            self.compact_button.configure(text="Expanded")
            self.root.minsize(*COMPACT_WINDOW_MINSIZE)
            self.root.geometry(COMPACT_WINDOW_GEOMETRY)
            self.status_var.set("Compact settings mode enabled.")
        else:
            self.compact_settings_panel.grid_remove()
            self.compact_button.configure(text="Compact")
            self.apply_navigation_view(self.view_mode_var.get())
            self.root.minsize(*FULL_WINDOW_MINSIZE)
            self.root.geometry(FULL_WINDOW_GEOMETRY)
            self.status_var.set("Full mode enabled.")
        save_config(self.collect_config())

    def focus_settings(self) -> None:
        if self.config.compact_mode:
            self.compact_discord_entry.focus_set()
        else:
            next_view = "Feed" if self.view_mode_var.get() == "Settings" else "Settings"
            self.view_mode_var.set(next_view)
            self.apply_navigation_view(next_view, announce=True)
            self.discord_entry.focus_set()
        if self.view_mode_var.get() == "Feed":
            self.status_var.set("Feed view enabled.")
        else:
            self.status_var.set("Settings focused.")

    def focus_account(self) -> None:
        if self.config.compact_mode:
            self.compact_username_entry.focus_set()
        else:
            next_view = "Feed" if self.view_mode_var.get() == "Account" else "Account"
            self.view_mode_var.set(next_view)
            self.apply_navigation_view(next_view, announce=True)
            self.username_entry.focus_set()
        if self.view_mode_var.get() == "Feed":
            self.status_var.set("Feed view enabled.")
        else:
            self.status_var.set("Account focused.")

    def set_sync_button_states(self, is_running: bool) -> None:
        self.start_button.configure(state="disabled" if is_running else "normal")
        self.stop_button.configure(state="normal" if is_running else "disabled")

        if hasattr(self, "compact_toggle_button"):
            if is_running:
                self.compact_toggle_button.configure(
                    text="Stop Sync",
                    bg="#4a2d34",
                    activebackground="#6f404b",
                    fg="#ffe7ed",
                )
            else:
                self.compact_toggle_button.configure(
                    text="Start Sync",
                    bg="#1f7a48",
                    activebackground="#299f5d",
                    fg="#f0fff7",
                )

    def collect_config(self) -> ClientConfig:
        config = ClientConfig(
            website_url=self.website_url_var.get().strip() or "http://127.0.0.1:5000",
            username=self.username_var.get().strip(),
            discord_webhook=self.discord_webhook_var.get().strip(),
            market=self.market_var.get().strip().upper() if self.market_var.get() else "NASDAQ",
            sync_seconds=self.read_sync_seconds(default_value=self.config.sync_seconds),
            compact_mode=self.config.compact_mode,
            windows_notifications=bool(self.windows_notify_var.get()),
            in_app_notifications=bool(self.in_app_notify_var.get()),
        )
        if config.market not in MARKETS:
            config.market = "NASDAQ"
        return config

    def read_sync_seconds(self, default_value: int = 30) -> int:
        raw = self.sync_seconds_var.get().strip()
        try:
            value = int(raw)
        except ValueError:
            return default_value
        if value < 2:
            return 2
        if value > 600:
            return 600
        return value

    def login_to_website(self) -> None:
        website_url = self.website_url_var.get().strip().rstrip("/")
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()

        if not website_url or not username or not password:
            messagebox.showerror("Missing info", "Website URL, username, and password are required.")
            return

        login_attempts = (
            ("api/client-login", {"username": username, "password": password}),
            ("api/login", {"email": username, "password": password, "rememberMe": True}),
        )

        login_error: Exception | None = None
        self.logged_in = False
        self.website_cookie_jar.clear()

        for endpoint_path, payload in login_attempts:
            endpoint = urljoin(f"{website_url}/", endpoint_path)
            try:
                response = self.post_json(endpoint, payload, use_session=True)
                accepted = bool(response.get("ok", response.get("allowed", True)))
                if not accepted:
                    reason = str(response.get("message") or "Login rejected by website.")
                    raise ValueError(reason)

                self.logged_in = True
                self.preview_mode_login = False
                self.account_status_var.set("Connected to website account.")
                self.status_var.set("Login complete. Auto-sync can now run.")
                break
            except Exception as error:
                login_error = error

        if not self.logged_in:
            use_preview = messagebox.askyesno(
                "Website Login Unavailable",
                (
                    "Could not verify login with the website endpoint.\n\n"
                    f"Reason: {login_error}\n\n"
                    "Use preview mode login so you can test the app design now?"
                ),
            )
            if use_preview:
                self.logged_in = True
                self.preview_mode_login = True
                self.account_status_var.set("Preview mode login active.")
                self.status_var.set("Preview mode enabled. Replace with website API later.")
            else:
                self.logged_in = False
                self.preview_mode_login = False
                self.account_status_var.set("Login failed.")
                self.status_var.set("Login failed.")
                return

        self.config = self.collect_config()
        save_config(self.config)

    def logout_client(self) -> None:
        if self.sync_running:
            self.stop_auto_sync()
        self.logged_in = False
        self.preview_mode_login = False
        self.website_cookie_jar.clear()
        self.password_var.set("")
        self.account_status_var.set("Logged out.")
        self.status_var.set("Account logged out.")

    def start_auto_sync(self) -> None:
        if not self.logged_in:
            messagebox.showwarning("Login required", "Login to the client account first.")
            return

        self.sync_market = self.market_var.get().strip().upper()
        if self.sync_market not in MARKETS:
            self.sync_market = "NASDAQ"

        self.sync_seconds = self.read_sync_seconds(default_value=self.config.sync_seconds)
        self.sync_discord_webhook = self.discord_webhook_var.get().strip()
        self.sync_windows_notifications = bool(self.windows_notify_var.get())
        self.sync_in_app_notifications = bool(self.in_app_notify_var.get())

        self.config = self.collect_config()
        save_config(self.config)

        self.stop_event.clear()
        self.sync_thread = threading.Thread(target=self.sync_worker, daemon=True)
        self.sync_thread.start()
        self.sync_running = True

        self.set_sync_button_states(True)
        self.status_var.set(
            f"Auto-sync running every {self.sync_seconds}s for {self.sync_market}."
        )

    def stop_auto_sync(self) -> None:
        self.stop_event.set()
        self.sync_running = False
        self.set_sync_button_states(False)
        self.status_var.set("Auto-sync stopped.")

    def send_test_signal(self) -> None:
        signal = self.build_signal_snapshot()
        delivery = self.deliver_signal(signal)
        self.enqueue_signal_event(signal, delivery)

    def sync_worker(self) -> None:
        while not self.stop_event.is_set():
            if self.preview_mode_login:
                signal = self.build_signal_snapshot()
                delivery = self.deliver_signal(signal)
                self.enqueue_signal_event(signal, delivery, source="preview")
            else:
                website_signals = self.fetch_website_signals()
                for signal in website_signals:
                    delivery = self.deliver_signal(signal)
                    self.enqueue_signal_event(signal, delivery, source="website")

            if self.stop_event.wait(self.sync_seconds):
                break

    def enqueue_signal_event(self, signal: dict, delivery: str, source: str = "app") -> None:
        self.event_queue.put(
            {
                "kind": "signal",
                "signal": signal,
                "delivery": delivery,
                "show_in_app": self.sync_in_app_notifications,
                "source": source,
            }
        )

    def fetch_website_signals(self) -> list[dict]:
        website_url = self.website_url_var.get().strip().rstrip("/")
        if not website_url:
            return []

        candidate_endpoints = (
            "api/ai/stock-signals?limit=6",
            "api/member/signals",
            "api/pro/signals",
        )
        normalized_signals: list[dict] = []

        for endpoint_path in candidate_endpoints:
            endpoint = urljoin(f"{website_url}/", endpoint_path)
            payload = None
            try:
                payload = self.get_json(endpoint, use_session=True)
            except Exception:
                payload = None

            if payload is None:
                continue

            normalized_signals = self.parse_signal_payload(payload)
            if normalized_signals:
                break

        if not normalized_signals:
            return []

        fresh_signals: list[dict] = []
        for signal in normalized_signals:
            key = signal.get("key")
            if not key or key in self.known_signal_keys:
                continue
            self.known_signal_keys.add(key)
            self.known_signal_order.append(key)
            fresh_signals.append(signal)

        if len(self.known_signal_order) > 2000:
            stale_keys = self.known_signal_order[:-1000]
            self.known_signal_order = self.known_signal_order[-1000:]
            for stale_key in stale_keys:
                self.known_signal_keys.discard(stale_key)

        return fresh_signals

    def parse_signal_payload(self, payload: object) -> list[dict]:
        rows: list[dict] = []

        if isinstance(payload, list):
            rows = [row for row in payload if isinstance(row, dict)]
        elif isinstance(payload, dict):
            if payload.get("ok") is False and not payload.get("signals"):
                return []
            direct_rows = payload.get("signals")
            if isinstance(direct_rows, list):
                rows = [row for row in direct_rows if isinstance(row, dict)]
            nested_result = payload.get("result")
            if not rows and isinstance(nested_result, dict):
                nested_rows = nested_result.get("signals")
                if isinstance(nested_rows, list):
                    rows = [row for row in nested_rows if isinstance(row, dict)]

        normalized: list[dict] = []
        for row in rows:
            parsed = self.normalize_website_signal(row)
            if parsed is not None:
                normalized.append(parsed)
        return normalized

    def normalize_website_signal(self, row: dict) -> dict | None:
        raw_symbol = row.get("assetSymbol") or row.get("symbol") or row.get("asset_symbol") or ""
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            return None

        raw_action = row.get("aiAction") or row.get("direction") or row.get("signal") or ""
        action = str(raw_action).strip().upper()
        if action in {"LONG", "BUY"}:
            signal_side = "BUY"
        elif action in {"SHORT", "SELL"}:
            signal_side = "SELL"
        else:
            signal_side = "INFO"

        raw_market = row.get("market") or row.get("sessionLabel") or row.get("session_label") or self.sync_market
        market = str(raw_market).strip().upper() or self.sync_market

        raw_price = row.get("entryPrice")
        if raw_price is None:
            raw_price = row.get("price")
        if raw_price is None:
            raw_price = row.get("entry_price")

        currency = str(
            row.get("displayCurrencyCode")
            or row.get("baseCurrencyCode")
            or row.get("currencyCode")
            or "USD"
        ).strip().upper()

        price_text = "N/A"
        try:
            numeric_price = float(raw_price)
            if currency == "USD":
                price_text = f"${numeric_price:,.2f}"
            else:
                price_text = f"{currency} {numeric_price:,.2f}"
        except (TypeError, ValueError):
            if raw_price is not None:
                price_text = str(raw_price)

        time_value = str(
            row.get("signalTimeUtc")
            or row.get("time")
            or row.get("signal_starts_at_utc")
            or ""
        ).strip()
        formatted_time = self.format_signal_time(time_value)

        unique_key = str(
            row.get("id")
            or f"{symbol}:{signal_side}:{row.get('signalDay') or row.get('signal_day') or ''}:{formatted_time}:{price_text}"
        )

        return {
            "key": unique_key,
            "time": formatted_time,
            "market": market,
            "symbol": symbol,
            "signal": signal_side,
            "price": price_text,
        }

    def format_signal_time(self, raw_value: str) -> str:
        candidate = raw_value.strip()
        if not candidate:
            return datetime.now().strftime("%H:%M:%S")

        if len(candidate) >= 8 and candidate[2] == ":" and candidate[5] == ":":
            return candidate[:8]

        if len(candidate) >= 5 and candidate[2] == ":":
            return f"{candidate[:5]}:00"

        if "T" in candidate:
            try:
                parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
                return parsed.strftime("%H:%M:%S")
            except ValueError:
                pass

        return datetime.now().strftime("%H:%M:%S")

    def build_signal_snapshot(self) -> dict:
        symbols = SYMBOLS_BY_MARKET.get(self.sync_market, SYMBOLS_BY_MARKET["NASDAQ"])
        symbol = RNG.choice(symbols)
        side = RNG.choice(["BUY", "SELL"])

        base_price = RNG.uniform(18, 750)
        variance = RNG.uniform(-3.2, 3.2)
        price = max(1.0, base_price + variance)

        return {
            "time": datetime.now().strftime("%H:%M:%S"),
            "market": self.sync_market,
            "symbol": symbol,
            "signal": side,
            "price": f"${price:,.2f}",
        }

    def deliver_signal(self, signal: dict) -> str:
        message = (
            f"{APP_NAME} {signal['signal']} {signal['symbol']} @ {signal['price']} "
            f"[{signal['market']}]"
        )

        delivery = "App"

        if self.sync_discord_webhook:
            ok, detail = self.send_discord_message(self.sync_discord_webhook, message)
            if ok:
                delivery = "Discord + App"
            else:
                delivery = f"Discord error: {detail}"

        if self.sync_windows_notifications:
            self.send_windows_notification("New Trading Signal", message)

        return delivery

    def send_discord_message(self, webhook_url: str, message: str) -> tuple[bool, str]:
        body = json.dumps({"content": message}).encode("utf-8")
        request_obj = Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": APP_NAME},
            method="POST",
        )

        try:
            with build_opener().open(request_obj, timeout=10):
                return True, "sent"
        except HTTPError as error:
            return False, f"HTTP {error.code}"
        except URLError as error:
            return False, str(error.reason)
        except ValueError:
            return False, "invalid webhook url"

    def send_windows_notification(self, title: str, message: str) -> None:
        if plyer_notification is not None:
            try:
                plyer_notification.notify(title=title, message=message, timeout=4)
                return
            except Exception:
                return

    def post_json(self, url: str, payload: dict, use_session: bool = False) -> dict:
        body = json.dumps(payload).encode("utf-8")
        request_obj = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )

        raw = self.open_request(request_obj, use_session=use_session)

        parsed = json.loads(raw) if raw else {}
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("Invalid JSON response from website.")

    def get_json(self, url: str, use_session: bool = False) -> object:
        request_obj = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": APP_NAME},
            method="GET",
        )
        raw = self.open_request(request_obj, use_session=use_session)
        return json.loads(raw) if raw else {}

    def open_request(self, request_obj: Request, use_session: bool = False) -> str:
        if use_session:
            with self.website_opener.open(request_obj, timeout=10) as response:
                return response.read().decode("utf-8")
        with build_opener().open(request_obj, timeout=10) as response:
            return response.read().decode("utf-8")

    def drain_event_queue(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break

            if event.get("kind") == "signal":
                signal = event["signal"]
                delivery = str(event.get("delivery") or "App")
                source = str(event.get("source") or "app")
                if bool(event.get("show_in_app", True)):
                    self.add_signal_to_table(signal, delivery)
                self.add_signal_notification(signal, source)
                self.status_var.set(
                    f"Signal {signal['signal']} {signal['symbol']} sent via {delivery}."
                )

        self.root.after(220, self.drain_event_queue)

    def add_signal_to_table(self, signal: dict, delivery: str) -> None:
        item_id = self.signal_tree.insert(
            "",
            0,
            values=(
                signal["time"],
                signal["market"],
                signal["symbol"],
                signal["signal"],
                signal["price"],
                delivery,
            ),
        )
        self.signal_tree.selection_set(item_id)

        children = self.signal_tree.get_children()
        if len(children) > 250:
            for stale_id in children[250:]:
                self.signal_tree.delete(stale_id)

    def add_signal_notification(self, signal: dict, source: str) -> None:
        source_label = "WEB" if source == "website" else source.upper()
        message = (
            f"[{source_label}] {signal['time']} | {signal['signal']} {signal['symbol']} "
            f"@ {signal['price']} [{signal['market']}]"
        )
        self.notification_list.insert(0, message)
        if self.notification_list.size() > 400:
            self.notification_list.delete(400, "end")

    def on_signal_mousewheel(self, event: tk.Event) -> str:
        if getattr(event, "delta", 0) == 0:
            return "break"
        self.signal_tree.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def on_signal_scroll_up(self, _event: tk.Event) -> str:
        self.signal_tree.yview_scroll(-1, "units")
        return "break"

    def on_signal_scroll_down(self, _event: tk.Event) -> str:
        self.signal_tree.yview_scroll(1, "units")
        return "break"

    def on_close(self) -> None:
        self.stop_event.set()
        self.sync_running = False

        self.config = self.collect_config()
        save_config(self.config)

        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    VaultSignalsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
