# Sofia — AI-Powered Facebook Messenger Chatbot

> **SOFIA** — Sales-Oriented Fulfillment & Intelligent Automation
>
> A production-grade, hybrid AI sales assistant for Ace Apparel built on Facebook Messenger.
> Combines rule-based determinism with Gemini LLM and Pinecone RAG for reliable,
> cost-efficient, personality-driven customer interactions.

---

## Overview

Sofia is an intelligent Messenger bot that handles customer inquiries for a streetwear brand.
It uses a two-stage response architecture: a rule-based engine handles the majority of traffic
at zero API cost, while Gemini LLM with Retrieval-Augmented Generation (RAG) handles
complex or open-ended queries.

**What makes it production-grade:**

- HMAC-SHA256 webhook signature verification
- Atomic Redis deduplication (prevents duplicate processing under load)
- Per-user spam detection and message rate limiting
- Prompt injection detection
- Red team guardrail engine on all AI-generated responses
- Structured intent logging and monthly analytics
- Human handover protocol with admin email alerts

---

## Architecture

```
Facebook Messenger
        │
        ▼
┌─────────────────────┐
│   app/routes.py     │  HMAC verify → dedup → spam check
│   Webhook Handler   │  → injection check → intent classify
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  core/sofia_agent   │  Rule-based engine (zero API cost)
│    SofiaAgent       │  → RAG + Gemini fallback
│                     │  → Guardrail enforcement
└────────┬────────────┘
         │
    ┌────┴─────────────────────────────────┐
    │                                      │
    ▼                                      ▼
┌──────────────┐                  ┌──────────────────┐
│  Rule-Based  │                  │   AI Fallback    │
│   Engine     │                  │ Gemini + Pinecone│
│  (TiDB SQL)  │                  │      RAG         │
└──────┬───────┘                  └────────┬─────────┘
       │                                   │
       └──────────────┬────────────────────┘
                      │
                      ▼
            ┌─────────────────┐
            │   services/     │
            │  Messenger API  │
            │  SendGrid Email │
            │  Redis Session  │
            └─────────────────┘
                      │
                      ▼
            ┌─────────────────┐
            │   database/     │
            │  TiDB (MySQL)   │
            │  Intent Log     │
            │  Message Log    │
            └─────────────────┘
```

---

## Tech Stack

| Layer           | Technology                       |
| :-------------- | :------------------------------- |
| Backend         | Python 3.11, Flask 3.0           |
| WSGI Server     | Gunicorn                         |
| LLM             | Google Gemini 2.5 Flash Lite     |
| Vector Search   | Pinecone (RAG pipeline)          |
| Embeddings      | Gemini Embedding 001 (3072-dim)  |
| Database        | TiDB Cloud (MySQL-compatible)    |
| Cache / Session | Upstash Redis                    |
| Messaging       | Facebook Messenger Graph API v22 |
| Email Alerts    | SendGrid                         |
| Deployment      | Render                           |

---

## Features

### Intent Classification (2-Stage)

1. **Keyword matching** — instant, zero API cost, handles 90%+ of real traffic
2. **Gemini fallback** — only triggered when no keyword matches

### Rule-Based Engine

Deterministic responses for all high-confidence intents — no LLM needed:

| Intent            | Behavior                                             |
| :---------------- | :--------------------------------------------------- |
| `SMALL_TALK`      | Returns welcome menu                                 |
| `PRODUCT_INQUIRY` | SQL search → TiDB → formatted reply                  |
| `PRICE_QUERY`     | SQL search → TiDB → formatted reply                  |
| `PURCHASE`        | Guides to `buy` confirmation → admin email           |
| `WHOLESALE`       | Rule reply → human handover → admin email            |
| `SHIPPING_INFO`   | Rule reply → human handover → admin email            |
| `REFUND_REQUEST`  | Handover message → human handover → admin email      |
| `COMPLAINT`       | Handover message → human handover → admin email      |
| `BANTER`          | Sofia rides the joke, redirects to products          |
| `PLAYFUL`         | Falls through to Gemini for personality-driven reply |

### RAG Pipeline

Product catalog is embedded with Gemini and stored in Pinecone.
Semantic search retrieves relevant context before every AI response.

### Guardrail Engine

All AI responses are scanned before delivery:

- Fabricated product data (invented prices, SKUs)
- Hallucinated certainty ("I am 100% sure...")
- Sycophancy patterns
- Unsafe language

Any failure triggers immediate human handover and admin alert.

### Session Management

- Bot auto-pauses when admin replies in Page Inbox
- Bot reactivates when admin types `sofia` or `bot`
- 90-day session TTL with Redis persistence

### Rate Limiting & Spam Protection

- Per-user message gap enforcement (configurable)
- Sliding window spam detection (10 messages / 20 seconds)
- Per-user admin email rate limit (2 emails / 30 minutes)

---

## Project Structure

```
sofia-bot/
├── app/
│   ├── main.py              # Flask app factory + startup
│   └── routes.py            # Webhook routes + message pipeline
│
├── core/
│   ├── sofia_agent.py       # SofiaAgent class — response logic
│   ├── intent_classifier.py # 2-stage intent classification
│   └── guardrails.py        # Red team pattern matching
│
├── services/
│   ├── session_service.py   # Redis session, spam, rate limiting
│   ├── messenger_service.py # Facebook Graph API
│   ├── email_service.py     # SendGrid alerts
│   ├── llm_service.py       # Gemini client wrapper
│   └── rag_service.py       # Pinecone retrieval
│
├── database/
│   ├── client.py            # pymysql connection factory
│   ├── models.py            # Table creation (DDL)
│   └── repository.py        # All SQL operations
│
├── config/
│   └── settings.py          # Typed env var validation
│
├── utils/
│   ├── security.py          # HMAC, injection, dedup
│   └── logger.py            # Structured logging
│
├── tests/
│   ├── test_intent.py
│   ├── test_guardrails.py
│   └── test_agent.py
│
├── scripts/
│   ├── sync_products.py     # TiDB → Pinecone sync
│   └── reset_session.py     # Emergency session reset
│
├── .env.example
├── requirements.txt
├── render.yaml
└── gunicorn.conf.py
```

---

## Deployment (Render)

### 1. Fork and clone the repository

```bash
git clone https://github.com/Lawrenze09/SOFIA-Messenger-Bot.git
cd sofia-bot
```

### 2. Create a new Web Service on Render

- Connect your GitHub repository
- Set **Build Command**: `pip install -r requirements.txt`
- Set **Start Command**: `gunicorn "app.main:create_app()" --config gunicorn.conf.py`
- Set **Region**: Singapore (closest to Philippines)

Or deploy directly with `render.yaml` via Render Blueprint.

### 3. Set environment variables

Add all variables from `.env.example` in Render Dashboard → Environment.

### 4. Set Facebook Webhook URL

In Meta Developer Dashboard → Webhooks:

```
https://your-app.onrender.com/webhook
```

### 5. Sync product catalog to Pinecone

```bash
python scripts/sync_products.py
```

---

## Local Development

```bash
# Clone
git clone https://github.com/Lawrenze09/SOFIA-Messenger-Bot.git
cd sofia-bot

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Fill in your values in .env

# Run locally
python app/main.py

# Expose local server for Messenger webhook testing
ngrok http 5001
```

---

## Environment Variables

| Variable            | Required | Description                                          |
| :------------------ | :------- | :--------------------------------------------------- |
| `GEMINI_API_KEY`    | ✅       | Google Gemini API key                                |
| `MYSQL_URI`         | ✅       | TiDB connection string with SSL                      |
| `REDIS_URL`         | ✅       | Upstash Redis URL                                    |
| `SENDGRID_API_KEY`  | ✅       | SendGrid API key                                     |
| `ADMIN_EMAIL`       | ✅       | Email address for admin alerts                       |
| `META_APP_SECRET`   | ✅       | Facebook App Secret for HMAC                         |
| `PAGE_ACCESS_TOKEN` | ✅       | Facebook Page permanent token                        |
| `VERIFY_TOKEN`      | ✅       | Webhook verification token                           |
| `PINECONE_API_KEY`  | ⚪       | Pinecone API key (optional, disables RAG if missing) |
| `PINECONE_INDEX`    | ⚪       | Pinecone index name                                  |
| `RATE_LIMIT`        | ⚪       | Default: `30 per minute`                             |
| `SPAM_MAX_MSGS`     | ⚪       | Default: `10`                                        |
| `SPAM_WINDOW_SECS`  | ⚪       | Default: `20`                                        |
| `EMAIL_MAX`         | ⚪       | Default: `2`                                         |
| `EMAIL_WINDOW_SECS` | ⚪       | Default: `1800`                                      |

---

## API Endpoints

| Method | Endpoint             | Description                   |
| :----- | :------------------- | :---------------------------- |
| `GET`  | `/webhook`           | Facebook webhook verification |
| `POST` | `/webhook`           | Receive Messenger events      |
| `GET`  | `/health`            | Redis + MySQL health check    |
| `POST` | `/reset/<psid>`      | Emergency session reset       |
| `GET`  | `/analytics/monthly` | Intent distribution report    |

---

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

---

## Message Flow Example

```
Customer: "may hoodie ba kayo?"

1. HMAC verified ✓
2. Dedup check — new message ✓
3. Spam check — under limit ✓
4. Injection scan — clean ✓
5. Intent: PRODUCT_INQUIRY (keyword: "hoodie")
6. Rule engine: SQL search → TiDB
7. Product found → formatted reply sent

Customer: "pabili"

5. Intent: PURCHASE (keyword: "pabili")
6. Rule reply: "i-type ang 'buy' para ma-confirm..."

Customer: "buy"

5. Intent: PURCHASE (exact match: "buy")
6. Rule reply: "Ina-alert ko na si Bigboss..."
7. Admin email sent via SendGrid

Customer: "may puso ka ba?"

5. Intent: PLAYFUL (keyword: "may puso ka ba")
6. Rule engine → no match → AI fallback
7. Gemini generates Sofia-style reply
8. Guardrails pass → reply sent
```

---

## Author

Built by Nazh Lawrenze Romero

- GitHub: [Lawrenze09](https://github.com/Lawrenze09)
- LinkedIn: [Lawrenze Romero](https://www.linkedin.com/in/lawrenze-romero-6b6871378/)

## Privacy Policy

This application is deployed on Facebook Messenger and complies with Meta's platform policies.
[View Privacy Policy](https://lawrenze09.github.io/Hybrid-AI-Messenger-Bot/privacy.html)

---

## License

MIT License — see [LICENSE](LICENSE) for details.
