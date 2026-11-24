# Apple Stock Monitor

A stupid Python monitor that tracks **Apple Store retail pickup availability** and sends instant **Telegram alerts** the moment your target product comes back in stock.


## Why This Exists

I built this script to track down an **iPhone Duo** for in store pickup at my local Apple Store in Italy (Apple Campania, Marcianise) without spending my days refreshing Apple's website.

## Features

- **Zero external dependencies:** built purely with the Python 3 standard library.
- **Fully configurable via `.env`:** change product, SKU, country endpoint, postal codes, and stores without editing `main.py`.
- **Smart Telegram alerts:** sends HTML formatted notifications only when a store transitions from unavailable to available (no duplicate spam).
- **Atomic state persistence:** saves the last known availability to a JSON file so restarts do not trigger duplicate alerts.
- **Multi-location polling:** queries multiple postal codes per cycle and deduplicates stores automatically (positive availability takes precedence).
- **Flexible store filtering:** filter specific Apple Stores by keyword with custom display names, or leave `ALLOWED_STORES` empty to watch every store Apple returns.
- **Built-in CLI utilities:** test Telegram connectivity, run a single check, or point to custom `.env` files.


## Quick Start

### 1. Prerequisites

- **Python 3.9+**
- A **Telegram Bot Token** (create one via [@BotFather](https://t.me/BotFather))
- Your **Telegram Chat ID** (via bot or the Telegram Bot API `getUpdates` endpoint)

### 2. Configure `.env`

Copy the example configuration file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` with your Telegram credentials, target product, Apple Store URL, postal codes, and optional store filter.

> **Note:** Never commit your `.env` file to version control, as it contains your Telegram bot token and chat ID.

### 3. Verify Telegram Alerts

```bash
python3 main.py --test-telegram
```

### 4. Run the Monitor

Run a single check (useful for testing or `cron`):

```bash
python3 main.py --once
```

Start continuous monitoring:

```bash
python3 main.py
```


## Configuration (`.env`)

All settings are loaded from `.env` (existing shell environment variables take precedence if already set).

| Variable | Required | Default | Description |
| :--- | :---: | :--- | :--- |
| `TG_TOKEN` | Yes | None | Telegram Bot API token from `@BotFather`. |
| `TG_CHAT_ID` | Yes | None | Target Telegram chat or channel ID. |
| `PRODUCT_NAME` | Yes | None | Human-readable product name shown in logs and Telegram alerts. |
| `PART_NUMBER` | Yes | None | Apple SKU / part number (e.g. `MK2D4QL/A`). |
| `APPLE_URL` | Yes | None | Regional Apple pickup endpoint (e.g. `https://www.apple.com/it/shop/retail/pickup-message` for Italy, or `https://www.apple.com/shop/retail/pickup-message` for the US). |
| `APPLE_REFERER` | No | Derived from `APPLE_URL` | `Referer` HTTP header sent to Apple (e.g. `https://www.apple.com/it/shop/`). |
| `ACCEPT_LANGUAGE` | No | `en-US,en;q=0.9` | `Accept-Language` HTTP header (e.g. `it-IT,it;q=0.9`). |
| `LOCATIONS` | Yes | None | Postal codes / areas to query. Supports `key:Label, ...`, bare postal codes, or a JSON object. |
| `ALLOWED_STORES` | No | *(all stores)* | Case-insensitive keyword filter mapping to official display names. Leave empty to monitor every store returned by Apple. |
| `INTERVAL` | No | `180` | Polling interval in seconds (minimum enforced: `30`). |
| `STATE_FILE` | No | `apple_stock_state.json` | Relative or absolute path to the JSON file used to persist store states. |
| `REQUEST_TIMEOUT` | No | `25` | HTTP timeout in seconds for Apple API requests. |
| `TELEGRAM_TIMEOUT` | No | `20` | HTTP timeout in seconds for Telegram API requests. |

### Supported Formats for `LOCATIONS` and `ALLOWED_STORES`

Both variables accept multiple convenient formats:

```env
# 1. Comma-separated key:label pairs
LOCATIONS="80121:Napoli centro, 80125:Napoli Fuorigrotta"
ALLOWED_STORES="campania:Apple Campania - Marcianise"

# 2. Semicolon-separated pairs (useful if labels contain commas)
ALLOWED_STORES="campania:Apple Campania, Marcianise; roma:Apple Via del Corso"

# 3. Bare entries without labels (uses the postcode or Apple's store name)
LOCATIONS="80121, 80125"
ALLOWED_STORES="campania"

# 4. JSON object
LOCATIONS='{"80121": "Napoli centro", "80125": "Napoli Fuorigrotta"}'
ALLOWED_STORES='{"campania": "Apple Campania - Marcianise"}'
```

### Finding Your `PART_NUMBER` and `APPLE_URL`

1. Open your regional Apple Store website and configure the exact model, color, and storage you want.
2. Open your browser's **DevTools → Network** tab, trigger the *"Check availability"* / *"In-store pickup"* lookup, and inspect the `pickup-message` request.
3. Copy the base URL into `APPLE_URL` and the `parts.0` query parameter into `PART_NUMBER`.

## CLI Options

```text
python3 main.py [options]
```

| Flag | Description |
| :--- | :--- |
| `--once` | Run a single availability check and exit. |
| `--test-telegram` | Send a test Telegram notification and exit. |
| `--env-file PATH` | Load configuration from a custom `.env` file (useful for monitoring multiple products in parallel). |


## How It Works

1. Loads and validates all settings from `.env`.
2. Queries Apple's retail pickup endpoint for each postal code listed in `LOCATIONS`.
3. Deduplicates stores across locations and filters them through `ALLOWED_STORES` (if configured).
4. Compares current availability against the previous state saved in `STATE_FILE`.
5. Sends a Telegram notification whenever a store switches to `available`, then atomically updates `STATE_FILE`.

## Plot Twist: It Actually Worked (and Now There's a Survival Log)

Because this script did its job, on **November 18, 2026** I finally retired my faithful six year old **iPhone 12 mini** and brought home the **iPhone Duo** from my Apple Store.

Of course, buying a foldable is only half the adventure. Spend five minutes doomscrolling `r/iPhoneDuo` and you'll be convinced every unit spontaneously grows a neon green line, a dead-pixel constellation, or a jammed hinge by Tuesday. Since nobody goes on Reddit just to post *"Day 47: opened my phone today, still works"*, I built a lighthearted counterbalance on my personal site:

👉 **[simonemargio.dev/duo/](https://simonemargio.dev/duo/)**: *iPhone Duo Survival Log. One fold at a time.*

![](https://github.com/user-attachments/assets/c5413818-d4b7-42c7-93d5-d3376d18eafd)


## Disclaimer

This project is an unofficial personal utility and is not affiliated with, endorsed by, or connected to Apple Inc. Please keep polling intervals reasonable (a 30-second minimum is enforced by default) to avoid sending excessive requests to Apple's servers.
