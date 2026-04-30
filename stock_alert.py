#!/usr/bin/env python3
"""Compliant stock alert monitor for Pokemon card product pages.

This tool is intentionally limited to stock notifications. It does not automate
checkout, solve challenges, rotate identities, or bypass retailer controls.
"""

from __future__ import annotations

import argparse
import json
import smtplib
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, Protocol


DEFAULT_USER_AGENT = "PokiHeavenStockAlert/1.0 (+contact: configure-owner-email)"
MIN_CHECK_INTERVAL_SECONDS = 60
ANTI_ABUSE_STATUS_CODES = {401, 403, 407, 429}
ANTI_ABUSE_MARKERS = (
    "captcha",
    "verify you are human",
    "access denied",
    "bot detection",
    "unusual traffic",
    "akamai",
    "cloudflare ray id",
)


class MonitorError(Exception):
    """Base exception for monitor failures."""


class ConfigurationError(MonitorError):
    """Raised when configuration is invalid."""


class AntiAbuseSignal(MonitorError):
    """Raised when a retailer indicates the monitor should stop."""


@dataclass(frozen=True)
class Product:
    name: str
    url: str
    in_stock_markers: tuple[str, ...]
    out_of_stock_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class EmailSettings:
    smtp_host: str
    smtp_port: int
    username: str | None
    password: str | None
    from_address: str
    to_addresses: tuple[str, ...]
    use_tls: bool = True


@dataclass(frozen=True)
class AppConfig:
    check_interval_seconds: int
    user_agent: str
    products: tuple[Product, ...]
    email: EmailSettings | None = None


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    body: str


class Notifier(Protocol):
    def send(self, product: Product, result: FetchResult) -> None:
        """Send a stock notification."""


class ConsoleNotifier:
    def send(self, product: Product, result: FetchResult) -> None:
        print(f"[IN STOCK] {product.name}: {result.url}")


class EmailNotifier:
    def __init__(self, settings: EmailSettings) -> None:
        self.settings = settings

    def send(self, product: Product, result: FetchResult) -> None:
        message = EmailMessage()
        message["Subject"] = f"Pokemon card stock alert: {product.name}"
        message["From"] = self.settings.from_address
        message["To"] = ", ".join(self.settings.to_addresses)
        message.set_content(
            f"{product.name} appears to be in stock.\n\n"
            f"Open the product page manually:\n{result.url}\n"
        )

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as smtp:
            if self.settings.use_tls:
                smtp.starttls()
            if self.settings.username:
                smtp.login(self.settings.username, self.settings.password or "")
            smtp.send_message(message)


def load_config(path: Path) -> AppConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON in {path}: {exc}") from exc

    interval = int(raw.get("check_interval_seconds", MIN_CHECK_INTERVAL_SECONDS))
    if interval < MIN_CHECK_INTERVAL_SECONDS:
        raise ConfigurationError(
            f"check_interval_seconds must be at least {MIN_CHECK_INTERVAL_SECONDS}"
        )

    products = tuple(_parse_product(item) for item in raw.get("products", []))
    if not products:
        raise ConfigurationError("At least one product is required")

    email = _parse_email(raw.get("email"))
    return AppConfig(
        check_interval_seconds=interval,
        user_agent=str(raw.get("user_agent") or DEFAULT_USER_AGENT),
        products=products,
        email=email,
    )


def _parse_product(raw: object) -> Product:
    if not isinstance(raw, dict):
        raise ConfigurationError("Each product must be an object")

    name = str(raw.get("name") or "").strip()
    url = str(raw.get("url") or "").strip()
    in_stock_markers = _parse_markers(raw.get("in_stock_markers"), "in_stock_markers")
    out_of_stock_markers = _parse_markers(
        raw.get("out_of_stock_markers", []),
        "out_of_stock_markers",
        required=False,
    )

    if not name:
        raise ConfigurationError("Product name is required")
    if not url.startswith(("https://", "http://")):
        raise ConfigurationError(f"Product URL must be http(s): {name}")

    return Product(
        name=name,
        url=url,
        in_stock_markers=in_stock_markers,
        out_of_stock_markers=out_of_stock_markers,
    )


def _parse_markers(raw: object, field_name: str, required: bool = True) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ConfigurationError(f"{field_name} must be a list")
    if not raw and not required:
        return ()
    if not raw:
        raise ConfigurationError(f"{field_name} must be a non-empty list")
    markers = tuple(str(item).strip().lower() for item in raw if str(item).strip())
    if not markers:
        raise ConfigurationError(f"{field_name} must contain text markers")
    return markers


def _parse_email(raw: object) -> EmailSettings | None:
    if raw in (None, {}, False):
        return None
    if not isinstance(raw, dict):
        raise ConfigurationError("email must be an object")

    host = str(raw.get("smtp_host") or "").strip()
    from_address = str(raw.get("from_address") or "").strip()
    to_addresses = tuple(str(item).strip() for item in raw.get("to_addresses", []) if str(item).strip())
    if not host or not from_address or not to_addresses:
        raise ConfigurationError("email requires smtp_host, from_address, and to_addresses")

    return EmailSettings(
        smtp_host=host,
        smtp_port=int(raw.get("smtp_port", 587)),
        username=str(raw["username"]) if raw.get("username") else None,
        password=str(raw["password"]) if raw.get("password") else None,
        from_address=from_address,
        to_addresses=to_addresses,
        use_tls=bool(raw.get("use_tls", True)),
    )


def fetch_product(product: Product, user_agent: str, timeout_seconds: int = 20) -> FetchResult:
    request = urllib.request.Request(
        product.url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": user_agent,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = response.status
            body = response.read(1_000_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in ANTI_ABUSE_STATUS_CODES:
            raise AntiAbuseSignal(
                f"{product.name} returned HTTP {exc.code}; stopping instead of bypassing"
            ) from exc
        body = exc.read(100_000).decode("utf-8", errors="replace")
        return FetchResult(product.url, exc.code, body)
    except urllib.error.URLError as exc:
        raise MonitorError(f"Failed to fetch {product.name}: {exc}") from exc

    result = FetchResult(product.url, status_code, body)
    ensure_no_anti_abuse_signal(product, result)
    return result


def ensure_no_anti_abuse_signal(product: Product, result: FetchResult) -> None:
    if result.status_code in ANTI_ABUSE_STATUS_CODES:
        raise AntiAbuseSignal(
            f"{product.name} returned HTTP {result.status_code}; stopping instead of bypassing"
        )

    normalized = result.body.lower()
    for marker in ANTI_ABUSE_MARKERS:
        if marker in normalized:
            raise AntiAbuseSignal(
                f"{product.name} showed an anti-abuse challenge marker: {marker!r}"
            )


def is_in_stock(product: Product, result: FetchResult) -> bool:
    normalized = result.body.lower()
    if any(marker in normalized for marker in product.out_of_stock_markers):
        return False
    return any(marker in normalized for marker in product.in_stock_markers)


def run_once(config: AppConfig, notifier: Notifier) -> int:
    notifications = 0
    for product in config.products:
        result = fetch_product(product, config.user_agent)
        if is_in_stock(product, result):
            notifier.send(product, result)
            notifications += 1
        else:
            print(f"[out of stock] {product.name}")
    return notifications


def run_forever(config: AppConfig, notifier: Notifier) -> None:
    while True:
        run_once(config, notifier)
        time.sleep(config.check_interval_seconds)


def build_notifier(config: AppConfig) -> Notifier:
    if config.email:
        return EmailNotifier(config.email)
    return ConsoleNotifier()


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pokemon card stock alert monitor")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("products.example.json"),
        help="Path to JSON config file",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one check and exit instead of polling continuously",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args.config)
        notifier = build_notifier(config)
        if args.once:
            run_once(config, notifier)
        else:
            run_forever(config, notifier)
        return 0
    except AntiAbuseSignal as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 2
    except MonitorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
