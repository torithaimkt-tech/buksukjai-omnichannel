# Central E-Commerce AI Chatbot Engine (Meta Messenger)

Brand-agnostic FastAPI backend for a Facebook Messenger AI chatbot. All brand
data — persona, catalog, pricing, shipping rules, FAQ, upsell strategy — lives
in `config.json`. Deploying a new brand = swapping one JSON file; the codebase
never changes.

## Architecture

```
Meta Messenger ──► POST /webhook ──► Session & State Tracker (SQLite)
                                        │
                                        ▼
config.json ──► Config Loader ──► Dynamic Prompting Engine ──► OpenAI API
                (startup)          (system prompt)              (gpt-4o-mini)
                                        │
                                        ▼
                              Send API reply + state update
                              (browsing / pending_payment / completed)
```

| Module | Responsibility |
|---|---|
| `app/config_loader.py` | Parses + validates `config.json` at startup (`CONFIG_PATH` overridable) |
| `app/prompt_engine.py` | Builds the LLM system prompt from config — zero hardcoded brand data |
| `app/llm.py` | OpenAI integration with Structured Outputs `{reply, state}`; mock mode when no API key |
| `app/database.py` | SQLAlchemy/SQLite: user sessions (PSID, order state, timestamps) + message log |
| `app/messenger.py` | Meta Send API client, 2000-char chunking, X-Hub-Signature-256 verification |
| `app/followup.py` | Background scheduler: follow-up for `pending_payment` sessions idle > X hours |
| `app/main.py` | FastAPI app: webhook GET (verification) + POST (events), health/debug endpoints |

## Quick start

```bash
cd messenger-engine
pip install -r requirements.txt
copy .env.example .env          # then fill in your keys
python -m uvicorn app.main:app --reload --port 8000
```

Without any keys the engine runs in **mock mode** — the full pipeline
(webhook → DB → prompt building → state machine → reply) works and replies are
logged to the console, so you can develop and test before connecting anything.

## Connecting to Facebook Messenger

1. Create a Meta App (type: Business) at https://developers.facebook.com and add the **Messenger** product.
2. Generate a **Page access token** for your page → put it in `.env` as `PAGE_ACCESS_TOKEN`.
3. Copy the **App secret** (App Settings → Basic) → `META_APP_SECRET`.
4. Choose any secret string as `META_VERIFY_TOKEN`.
5. Expose the server publicly (e.g. `ngrok http 8000` for dev, or deploy) and set the webhook
   callback URL to `https://<your-host>/webhook` with your verify token; subscribe to the
   `messages` field.
6. Set `OPENAI_API_KEY` to leave mock mode. Model used: `gpt-4o-mini` by default (override with `OPENAI_MODEL`, e.g. `gpt-4o`).

## Order state machine

The LLM returns structured JSON `{reply, state}` on every turn (enforced by
OpenAI Structured Outputs — never free text):

- `browsing` — asking questions, comparing sizes
- `pending_payment` — agreed to buy; order summarized, awaiting address/payment
- `completed` — payment confirmed

State is persisted per PSID in `user_sessions` and injected back into the
prompt each turn.

## Follow-up automation

Set `ENABLE_FOLLOWUP=true` to activate. Every `FOLLOWUP_CHECK_MINUTES` the
scheduler finds sessions stuck in `pending_payment` for more than
`FOLLOWUP_AFTER_HOURS` and sends one follow-up message (customizable via a
`followup_strategy.message` key in `config.json`). A `followup_sent_at` guard
ensures it fires at most once until the customer replies again.

## Dev endpoints (disabled when `DEBUG=false`)

- `GET /health` — status, active brand, mock mode
- `GET /debug/prompt` — the exact system prompt generated from config.json
- `GET /debug/sessions` — all tracked sessions and their states

## Deploying another brand

```bash
CONFIG_PATH=/path/to/other-brand.json python -m uvicorn app.main:app --port 8001
```

Run one process per brand/page — each with its own config, page token, and
`DATABASE_URL`.
