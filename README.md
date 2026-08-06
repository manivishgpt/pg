# Telegram Account Automation System (Python & Web UI)

A modular, asynchronous Python framework for Telegram client account automation built using **Pyrogram**, **FastAPI Web Dashboard**, **Rich CLI**, and **AsyncIO**.

---

## Features

- 🌐 **Modern Web UI Dashboard**: Glassmorphic web interface running on FastAPI + WebSockets (`http://127.0.0.1:8000`).
- 👤 **Multi-Account Session Manager**: Manage and authenticate multiple `.session` files or string sessions simultaneously.
- 🔍 **Writable Groups Finder & Scraper**: Discover joined groups where your account has posting permissions, with 1-click CSV/JSON downloads.
- ⚡ **Auto-Responder Engine**: Automatic keyword/regex matching replies with customizable typing simulation and private/group scope control.
- 📢 **Broadcaster & Mass Messenger**: Send bulk text or photo campaigns to lists of users/chats with built-in queueing and human-like safety delays.
- 🔄 **Channel Mirror & Forwarder**: Real-time message auto-forwarding between channels with link stripping, header/footer additions, and keyword filtering.
- 🛡️ **Anti-Flood & Rate-Limit Shield**: Automatic `FloodWait` detection and exponential retry logic to keep accounts safe.
- 📜 **Live Terminal Log Streaming**: Real-time log streamer in the browser via WebSocket.

---

## Installation

### Prerequisites
- Python 3.9+
- Telegram API Credentials (`API_ID` & `API_HASH`) from [https://my.telegram.org](https://my.telegram.org).

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env`:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash_here
MIN_ACTION_DELAY=3.0
MAX_ACTION_DELAY=8.0
DEFAULT_PROXY=
```

---

## How to Run

### Option A: Launch Web UI Dashboard (Recommended)

```bash
python web_app.py
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

### Option B: Launch Terminal CLI Interface

```bash
python cli.py
```

---

## Project Structure

```
├── web_app.py            # FastAPI Web Server & REST/WebSocket Endpoints
├── config.py             # Settings loader and proxy parser
├── cli.py                # Rich interactive CLI dashboard
├── requirements.txt      # Python dependencies
├── templates/
│   └── index.html        # Glassmorphic single-page dashboard UI
├── static/
│   ├── css/style.css     # Theme & design system
│   └── js/app.js         # REST & WebSocket frontend logic
├── core/
│   ├── anti_flood.py     # FloodWait handlers & randomized delay utilities
│   └── session_manager.py # Multi-account Pyrogram client manager
└── modules/
    ├── auto_responder.py # Auto-reply listener engine
    ├── broadcaster.py    # Bulk campaign broadcaster
    ├── forwarder.py      # Real-time channel mirror/forwarder
    └── scraper.py        # Group member & writable groups extractor
```
