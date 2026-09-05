# MenuChecker

A daily menu digest for **Rangsit University** students — so you don't have to
check five different restaurants' Facebook pages and Line groups just to find
out what's for lunch.

Every morning, MenuChecker checks the restaurants around campus that post
their daily menu — some on Facebook, some directly in a Line group — reads
the post (Burmese text or a photo of a handwritten board), and posts one
digest to a shared Line group: a card per restaurant, with an **Order**
button that DMs you the menu and walks you through picking items.

## Why

Students following Myanmar restaurants near Rangsit end up with the same
routine every morning: open Facebook, open two or three Line groups, scroll
each one looking for today's post, decide what to eat. MenuChecker collapses
that into one message in one place, at the same time every day.

## What it does

- **Watches restaurants automatically.** Facebook pages are scraped on a
  schedule; restaurants that only post inside a Line group are picked up
  from that group directly — no manual copying either way.
- **Reads the menu, in Burmese or English, text or photo.** Gemini extracts
  the dish list (and prices, when posted) from whatever format the
  restaurant used that day.
- **Posts one digest, every morning at 8:00 (Thailand time).** All of today's
  menus land in the shared Line group as Flex cards, so there's one place to
  check instead of several.
- **Lets you order without leaving Line.** Tap **Order** on a restaurant's
  card, pick items and quantities in a DM, and get a summary you can send
  straight to the restaurant.

## How it works

```
Facebook pages ──(scheduled scrape)──┐
                                     ├─→ Gemini extraction ─→ menu_store.json
Line source groups ──(webhook)───────┘                             │
                                                                   ▼
                                          Flex menu card → Line group → Order button
                                                                   │
                                                          DM order flow → summary
```

- `scheduler.py` runs the Facebook pipeline once a day, at `SCHEDULE_HOUR`:`SCHEDULE_MINUTE` in `TIMEZONE` (defaults to 08:00 `Asia/Bangkok`).
- `fetcher/line_reader.py` serves the Line webhook. Extraction runs on worker
  threads so the webhook answers immediately; Line redeliveries are deduplicated
  by `webhookEventId`.
- `utils/menu_store.py` persists the day's menu so the Order button can resolve
  items later. Writes are atomic.
- `utils/order_session.py` holds each user's in-progress order **in memory**.

## Setup

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env                             # then fill it in
cp restaurants.example.json restaurants.json     # then add your restaurants
python save_session.py                           # log in once, stores fb_session.json
```

## Running

Production (waitress WSGI server + daily scheduler):

```bash
python main.py
```

One-off pipeline run, no server:

```bash
python main.py --run-now
```

Development server (Werkzeug, do not use in production):

```bash
python main.py --dev
```

Point your reverse proxy or ngrok at `PORT` and set the Line webhook URL to
`https://<your-host>/webhook`. `GET /health` is the liveness probe.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Operational notes

- **Local config.** `restaurants.json` is gitignored because Line group IDs
  identify your private groups. Start from `restaurants.example.json`; override
  the path with `RESTAURANTS_FILE` if you keep it elsewhere.
- **Secrets.** `.env` and `fb_session.json` hold live credentials and are
  gitignored. If they were ever committed or shared, rotate the Line channel
  access token, the Gemini key, and the Facebook token.
- **Facebook token** expires every 60 days; refresh it before day 50.
- **Session state is per-process.** `order_session` lives in memory, so a
  restart drops in-flight orders and running more than one worker process would
  split sessions across them. Run a single instance, or move sessions to Redis
  before scaling out.
- **Logs** rotate at 5 MB, 5 files kept. Override the path with `LOG_FILE`.
- **`menu_store.json` is runtime state**, not config — it is gitignored and is
  rebuilt every morning.
