# MoneyShift

A companion app for board games that involve money (Monopoly and similar). One person runs the
app on a laptop and becomes the **host and the bank**. Everyone else joins from their own phone
(Android or iOS) over the same Wi-Fi, and money moves between players and the bank in real time.

- `backend/`: Python (FastAPI + SQLite). The server and source of truth: ledger, bank rules, WebSocket sync.
- `frontend/`: Angular 22 mobile-first web app, built and served by the backend.
- `plans/`: local planning documents (git-ignored).

## Quick start

Prerequisites: Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Node 22.22+ / 24.15+ with npm.

```bash
make setup   # install dependencies (once)
make run     # build the app and start the host server
```

The terminal prints the address and a QR code. Open it on the laptop, choose **Start a game**, then
have players scan the QR code shown on the host screen (or open the address and enter the 4-letter
game code). The game is stored in `backend/data/moneyshift.db`, so restarting `make run` resumes it.

Everyone must be on the same Wi-Fi network as the laptop, and the laptop's firewall must allow the
port (default `8000`). The first version uses plain HTTP; see "HTTPS later" below.

## How it works

- The laptop is the server. Phones send *intents* ("pay Sam 200"); the server validates them and is the only place balances change.
- The host is the bank. Players can pay each other instantly, but can only *ask* the bank for money; the host approves or denies. The host can also pay or collect from any player and undo a transaction.
- Every change is an event with a sequence number. Phones reconnect automatically and catch up after a dropped connection.
- Game modes (classes in `backend/app/domain/modes.py`): **Monopoly** is the base game (default: $1,500, Pass GO and tax shortcuts, Jail and Dice). **UnoPoly** derives from it and swaps the Dice for physical Uno cards: the holder ends their turn, plays **Skip next player** or **Reverse**, and anyone can **Call Out!** a player who ended their turn without saying UNO (everyone else votes; if all agree, that player goes to Jail and a siren sounds). **Custom** is for any other game. In Jail a player gets one chance to pay the fine on their turn; if they miss the turn instead they also miss the next two, then are released automatically. The host can override the turn, Jail and call-outs from the bank dashboard, and can **Restart game** (same players, everyone back to the starting money, clean ledger).
- QR payments, UPI style: **Receive by QR** shows a QR code for you (with an optional amount); the host's bank dashboard has **Collect by QR** for fines and taxes. A payer taps **Scan QR code**, sees who they are paying and confirms. The QR only pre-fills the screen, and the server validates everything.
- Actions taken while a phone is offline are saved and sent on reconnect with an idempotency key, so a retry never charges twice.

### Scanning on plain HTTP

Browsers only allow the live camera viewfinder on HTTPS (or localhost). On plain HTTP the scanner
falls back to **Take a photo of the QR**, which works on Android and iOS. To try the live viewfinder
over HTTP on your own Android Chrome, open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`,
add the game address (for example `http://192.168.1.20:8000`) and relaunch. With HTTPS the live
viewfinder works for everyone.

## Development

```bash
make dev-backend    # http://localhost:8000 with auto-reload
make dev-frontend   # http://localhost:4200, proxies /api to the backend
make test           # backend (pytest) and frontend (vitest) tests
make lint           # ruff and eslint
```

Configuration is by environment variables or `backend/.env` (all prefixed `MONEYSHIFT_`): `PORT`,
`DATABASE_URL`, `STATIC_DIR`, `SSL_CERTFILE`, `SSL_KEYFILE`.

## HTTPS later

Plain HTTP works for the whole game. Browser features that need a secure context (installable PWA,
keeping the screen awake, in-app QR scanning) require HTTPS. The app is built so HTTPS is only
configuration: set `MONEYSHIFT_SSL_CERTFILE` and `MONEYSHIFT_SSL_KEYFILE`, and the server starts
with TLS (WebSockets switch to `wss` automatically). Planned route: a DuckDNS name with a Let's
Encrypt certificate. Never commit the certificate, key or any token.
