#!/usr/bin/env python3

from __future__ import annotations

import argparse
import html
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

# ============================================================
# DEFAULTS
# ============================================================

DEFAULT_INTERVAL = 180
MIN_INTERVAL = 30
DEFAULT_REQUEST_TIMEOUT = 25
DEFAULT_TELEGRAM_TIMEOUT = 20
DEFAULT_ACCEPT_LANGUAGE = "en-US,en;q=0.9"
DEFAULT_STATE_FILE = "apple_stock_state.json"

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = BASE_DIR / ".env"


# ============================================================
# CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class Config:
    """Runtime configuration loaded from environment variables and .env."""

    tg_token: str
    tg_chat_id: str
    product_name: str
    part_number: str
    apple_url: str
    apple_referer: str
    accept_language: str
    locations: dict[str, str]
    allowed_stores: dict[str, str]
    interval: int
    state_file: Path
    request_timeout: int
    telegram_timeout: int


def normalize(value: str) -> str:
    """Normalize text for case-insensitive and whitespace-insensitive matching."""
    return " ".join(str(value).lower().strip().split())


def strip_matching_quotes(value: str) -> str:
    """Remove a single matching pair of outer single or double quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def load_env(env_file: Path = DEFAULT_ENV_FILE) -> None:
    """Load key-value pairs from the .env file without overriding existing env vars."""
    if not env_file.exists():
        raise FileNotFoundError(f".env file not found: {env_file}")

    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()

        value = strip_matching_quotes(value.strip())

        if key and key not in os.environ:
            os.environ[key] = value


def get_required_env(name: str) -> str:
    """Read a required non-empty environment variable."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required variable in .env: {name}")
    return value


def parse_positive_int(name: str, default: int, minimum: int = 1) -> int:
    """Parse an integer environment variable with fallback and lower bound."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return max(default, minimum)

    try:
        parsed = int(raw.strip())
    except ValueError:
        parsed = default

    return max(parsed, minimum)


def parse_mapping(
    raw_value: str,
    var_name: str,
    *,
    normalize_keys: bool = False,
    allow_empty: bool = False,
    default_value_to_key: bool = True,
) -> dict[str, str]:
    """
    Parse a dictionary-like environment variable.

    Supported formats:
      1. JSON object: {"10001": "New York Midtown", "94102": "San Francisco"}
      2. Delimited pairs: "10001:New York Midtown, 94102:San Francisco"
         (semicolons can be used instead of commas if labels contain commas)
      3. Bare entries without colon: "10001, 94102"
    """
    text = raw_value.strip()
    if not text:
        if allow_empty:
            return {}
        raise ValueError(f"{var_name} is missing or empty in .env")

    result: dict[str, str] = {}

    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{var_name} contains invalid JSON in .env: {exc}") from exc

        if not isinstance(parsed, dict):
            raise ValueError(f"{var_name} must be a JSON object in .env")

        for raw_key, raw_val in parsed.items():
            key = normalize(raw_key) if normalize_keys else str(raw_key).strip()
            val = "" if raw_val is None else str(raw_val).strip()
            if key:
                result[key] = val or (key if default_value_to_key else "")
    else:
        separator = ";" if ";" in text else ","
        for entry in text.split(separator):
            entry = entry.strip()
            if not entry:
                continue

            if ":" in entry:
                raw_key, raw_val = entry.split(":", 1)
                key = normalize(raw_key) if normalize_keys else raw_key.strip()
                val = raw_val.strip()
            else:
                key = normalize(entry) if normalize_keys else entry
                val = key if default_value_to_key else ""

            if key:
                result[key] = val

    if not result and not allow_empty:
        raise ValueError(f"{var_name} does not contain any valid entries in .env")

    return result


def derive_referer(apple_url: str) -> str:
    """Derive a default Apple Store Referer header from APPLE_URL."""
    parsed = urlsplit(apple_url)
    shop_marker = "/shop/"
    if shop_marker in parsed.path:
        shop_prefix = parsed.path.split(shop_marker, 1)[0] + shop_marker
        return f"{parsed.scheme}://{parsed.netloc}{shop_prefix}"
    return f"{parsed.scheme}://{parsed.netloc}/"


def get_config(env_file: Path = DEFAULT_ENV_FILE) -> Config:
    """Load, validate, and build the application Config object."""
    load_env(env_file)

    tg_token = get_required_env("TG_TOKEN")
    tg_chat_id = get_required_env("TG_CHAT_ID")
    product_name = get_required_env("PRODUCT_NAME")
    part_number = get_required_env("PART_NUMBER")
    apple_url = get_required_env("APPLE_URL")

    apple_referer = os.getenv("APPLE_REFERER", "").strip() or derive_referer(apple_url)
    accept_language = os.getenv("ACCEPT_LANGUAGE", "").strip() or DEFAULT_ACCEPT_LANGUAGE

    locations = parse_mapping(
        os.getenv("LOCATIONS", ""),
        "LOCATIONS",
        normalize_keys=False,
        allow_empty=False,
        default_value_to_key=True,
    )

    allowed_stores = parse_mapping(
        os.getenv("ALLOWED_STORES", ""),
        "ALLOWED_STORES",
        normalize_keys=True,
        allow_empty=True,
        default_value_to_key=False,
    )

    interval = parse_positive_int("INTERVAL", DEFAULT_INTERVAL, minimum=MIN_INTERVAL)
    request_timeout = parse_positive_int("REQUEST_TIMEOUT", DEFAULT_REQUEST_TIMEOUT, minimum=5)
    telegram_timeout = parse_positive_int("TELEGRAM_TIMEOUT", DEFAULT_TELEGRAM_TIMEOUT, minimum=5)

    raw_state_file = os.getenv("STATE_FILE", DEFAULT_STATE_FILE).strip() or DEFAULT_STATE_FILE
    state_file = Path(raw_state_file)
    if not state_file.is_absolute():
        state_file = BASE_DIR / state_file

    return Config(
        tg_token=tg_token,
        tg_chat_id=tg_chat_id,
        product_name=product_name,
        part_number=part_number,
        apple_url=apple_url,
        apple_referer=apple_referer,
        accept_language=accept_language,
        locations=locations,
        allowed_stores=allowed_stores,
        interval=interval,
        state_file=state_file,
        request_timeout=request_timeout,
        telegram_timeout=telegram_timeout,
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(config: Config, message: str) -> bool:
    """Send an HTML-formatted notification message via the Telegram Bot API."""
    url = f"https://api.telegram.org/bot{config.tg_token}/sendMessage"

    payload = json.dumps({
        "chat_id": config.tg_chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=config.telegram_timeout) as response:
            result = json.loads(response.read().decode("utf-8"))

        if not result.get("ok"):
            print(f"TELEGRAM ERROR: {result}")
            return False

        return True

    except Exception as exc:
        print(f"TELEGRAM ERROR: {exc}")
        return False


# ============================================================
# STATE PERSISTENCE
# ============================================================

def load_state(state_file: Path) -> dict[str, str]:
    """Load the previously recorded store availability state from disk."""
    if not state_file.exists():
        return {}

    try:
        with state_file.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except Exception as exc:
        raise RuntimeError(f"Unable to read state file: {exc}") from exc


def save_state(state_file: Path, state: dict[str, str]) -> None:
    """Atomically persist the store availability state to disk."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = state_file.with_suffix(".tmp")

    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, ensure_ascii=False)

    temp_file.replace(state_file)


# ============================================================
# ALLOWED STORES FILTER
# ============================================================

def identify_allowed_store(store_name: str, allowed_stores: dict[str, str]) -> str | None:
    """
    Return the display name for an allowed store, or None if it should be ignored.

    If allowed_stores is empty, all stores are accepted using Apple's store name.
    """
    if not allowed_stores:
        return store_name

    name = normalize(store_name)

    for keyword, official_name in allowed_stores.items():
        if keyword in name:
            return official_name or store_name

    return None


# ============================================================
# APPLE RESPONSE PARSING
# ============================================================

def get_store_id(store: dict) -> str | None:
    """Extract the unique store identifier from an Apple store payload."""
    return (
        store.get("storeNumber")
        or store.get("storeId")
        or store.get("storeID")
    )


def get_store_name(store: dict) -> str:
    """Extract the store name from an Apple store payload."""
    return (
        store.get("storeName")
        or store.get("name")
        or "Unknown store"
    )


def find_stores(data: object) -> list[dict]:
    """Recursively locate and deduplicate store entries in the Apple JSON response."""
    found: list[dict] = []

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if (
                    key.lower() == "stores"
                    and isinstance(value, list)
                    and all(isinstance(x, dict) for x in value)
                ):
                    found.extend(value)

                walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    unique: dict[str, dict] = {}

    for store in found:
        store_id = get_store_id(store)

        if store_id:
            unique[str(store_id)] = store

    return list(unique.values())


def get_pickup_status(store: dict, part_number: str) -> str | None:
    """Extract pickup availability ('available' or 'unavailable') for a part number."""
    availability = store.get("partsAvailability")

    if not isinstance(availability, dict):
        return None

    product = availability.get(part_number)

    if not isinstance(product, dict):
        return None

    display = product.get("pickupDisplay")

    if display == "available":
        return "available"

    if display == "unavailable":
        return "unavailable"

    return None


# ============================================================
# APPLE API CLIENT
# ============================================================

def query_apple(postcode: str, config: Config) -> list[dict]:
    """Query Apple's retail pickup endpoint for a given postal code."""
    params = {
        "pl": "true",
        "location": postcode,
        "parts.0": config.part_number,
        "mts.0": "regular",
    }

    url = config.apple_url + "?" + urlencode(params)

    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": config.accept_language,
            "Referer": config.apple_referer,
        },
    )

    with urlopen(request, timeout=config.request_timeout) as response:
        raw = response.read().decode("utf-8")

    data = json.loads(raw)

    stores = find_stores(data)

    if not stores:
        raise ValueError("Apple did not return a valid store list.")

    return stores


# ============================================================
# AVAILABILITY CHECK
# ============================================================

def check_availability(
    config: Config,
) -> tuple[dict[str, str], dict[str, str], int, list[str]]:
    """Query all configured locations and aggregate status for allowed stores."""
    current_status: dict[str, str] = {}
    store_names: dict[str, str] = {}

    successful_locations = 0
    errors: list[str] = []

    for postcode, location_name in config.locations.items():
        try:
            stores = query_apple(postcode, config)
            successful_locations += 1

            for store in stores:
                store_id = get_store_id(store)
                raw_name = get_store_name(store)

                # Filter: skip stores that do not match ALLOWED_STORES.
                official_name = identify_allowed_store(raw_name, config.allowed_stores)

                if not official_name:
                    continue

                status = get_pickup_status(store, config.part_number)

                if status is None:
                    continue

                store_id = str(store_id)
                store_names[store_id] = official_name

                # If a store appears across multiple location queries,
                # positive availability takes precedence.
                previous = current_status.get(store_id)

                if previous == "available":
                    continue

                if status == "available" or previous is None:
                    current_status[store_id] = status

        except Exception as exc:
            errors.append(location_name)
            print(f"ERROR ({location_name}): {exc}")

    return current_status, store_names, successful_locations, errors


# ============================================================
# MONITORING & NOTIFICATIONS
# ============================================================

def check_once(config: Config) -> None:
    """Run a single availability check, update persisted state, and notify on changes."""
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    print()
    print("=" * 65)
    print(f"[{now}] AVAILABILITY CHECK")
    print("=" * 65)

    current_status, store_names, successful, errors = check_availability(config)

    print(f"Locations queried successfully: {successful}/{len(config.locations)}")
    print(f"Matching stores found: {len(current_status)}")

    if errors:
        print("Failed locations: " + ", ".join(errors))

    if successful == 0:
        print("No valid response from Apple. State unchanged.")
        return

    print()
    print("MONITORED STORES STATUS:")

    for store_id, status in sorted(current_status.items()):
        name = store_names.get(store_id, "Unknown store")
        print(f"  - {name} ({store_id}): {status}")

    available = [
        store_id
        for store_id, status in current_status.items()
        if status == "available"
    ]

    print()
    print(f"Currently available: {len(available)}")

    previous_state = load_state(config.state_file)
    new_state = dict(previous_state)

    new_availability: list[str] = []

    for store_id, status in current_status.items():
        previous_status = previous_state.get(store_id)

        if status == "available" and previous_status != "available":
            new_availability.append(store_id)

        new_state[store_id] = status

    save_state(config.state_file, new_state)

    if not new_availability:
        print("No new availability detected.")
        return

    print()
    print("NEW AVAILABILITY! Sending Telegram alert...")

    for store_id in new_availability:
        name = store_names.get(store_id, "Apple Store")

        message = (
            "🍎 <b>PRODUCT AVAILABLE!</b>\n\n"
            f"<b>Product:</b> {html.escape(config.product_name)}\n"
            f"<b>Part Number:</b> {html.escape(config.part_number)}\n"
            f"<b>Store:</b> {html.escape(name)}\n"
            f"<b>Store ID:</b> {html.escape(store_id)}\n\n"
            "Check pickup availability on the Apple website now."
        )

        if send_telegram(config, message):
            print(f"Telegram sent: {name} ({store_id})")
        else:
            print(f"Telegram FAILED: {name} ({store_id})")


# ============================================================
# ENTRYPOINT
# ============================================================

def main() -> None:
    """Parse CLI arguments, load configuration, and start the monitoring loop."""
    parser = argparse.ArgumentParser(
        description="Monitor Apple Store retail pickup availability and send Telegram alerts."
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single availability check and exit",
    )

    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Send a test Telegram message and exit",
    )

    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="Path to the .env configuration file",
    )

    args = parser.parse_args()

    config = get_config(args.env_file)

    if args.test_telegram:
        ok = send_telegram(
            config,
            "✅ Apple Stock Monitor: Telegram is configured and working.",
        )

        if ok:
            print("Test message sent.")
        else:
            print("Telegram test failed.")

        return

    print()
    print("Apple Stock Monitor started.")
    print(f"Product: {config.product_name} ({config.part_number})")
    print(f"Checking every {config.interval} seconds.")

    if config.allowed_stores:
        print("MONITORED STORES:")
        for keyword, name in config.allowed_stores.items():
            print(f"  - {name or keyword}")
        print()
        print("All other Apple Stores are ignored.")
    else:
        print("MONITORED STORES: all Apple Stores returned by Apple.")

    print("Press CTRL+C to stop.")

    if args.once:
        check_once(config)
        return

    while True:
        try:
            check_once(config)

        except KeyboardInterrupt:
            raise

        except Exception as exc:
            print(f"ERROR: {exc}")

        print()
        print(f"Next check in {config.interval} seconds.")

        try:
            time.sleep(config.interval)

        except KeyboardInterrupt:
            raise


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
