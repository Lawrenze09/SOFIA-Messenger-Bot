<div align="center">

# Sofia — AI-Powered Facebook Messenger Chatbot

**SOFIA** — Sales-Oriented Fulfillment & Intelligent Automation

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Gemini](https://img.shields.io/badge/Gemini-2.5_Flash-4285F4?style=flat-square&logo=google&logoColor=white)](https://ai.google.dev)
[![Pinecone](https://img.shields.io/badge/Pinecone-RAG-00B388?style=flat-square)](https://pinecone.io)
[![Redis](https://img.shields.io/badge/Redis-Session-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io)
[![Render](https://img.shields.io/badge/Deployed-Render-46E3B7?style=flat-square&logo=render&logoColor=white)](https://render.com)
[![Tests](https://img.shields.io/badge/Tests-33%2F33_Passing-brightgreen?style=flat-square)](tests/)
[![Meta](https://img.shields.io/badge/Meta_App_Review-Approved-1877F2?style=flat-square&logo=meta&logoColor=white)](https://developers.facebook.com)

> **Live in Production** — Actively handling real customer inquiries for Ace Apparel on Facebook Messenger.
>
> **Meta App Review Approved** — Passed Facebook's official app review process, meeting all platform policies and data handling requirements.

</div>

---

## Executive Summary

Sofia is a hybrid conversational automation system built for Facebook Messenger commerce workflows. The core architectural decision — and the one that defines every other design choice in the system — is the **strict separation of deterministic and probabilistic reasoning domains**.

Most LLM-based chatbots make a critical mistake: they ask the language model to answer questions it cannot reliably answer. Product prices change. Stock levels fluctuate. SKUs are exact strings. When you route these queries through a language model, you get hallucinations — confidently wrong answers that erode customer trust and create support overhead.

Sofia's architecture is built around a different premise:

> **The rule engine owns facts. The LLM owns language. These domains never overlap.**

Product prices, stock availability, and order confirmations are handled exclusively by deterministic SQL queries against TiDB. Gemini is only invoked for what it actually does well — understanding natural language intent in ambiguous or open-ended messages, and generating personality-driven conversational responses for queries that have no factual answer to get wrong.

The result is a system that is simultaneously more reliable than a pure LLM approach and more capable than a pure rule-based approach. The rule engine handles approximately 90% of production traffic at zero API cost. Gemini handles the remaining 10% — the edge cases, playful banter, and unstructured queries that keyword matching genuinely cannot resolve.

---

## System Architecture

```mermaid
flowchart TD
    A[Facebook Messenger] -->|POST /webhook| B[HMAC Verification]
    B -->|Signature Valid| C[Deduplication Check\nRedis SETNX]
    B -->|Invalid| X1[401 Unauthorized]
    C -->|New Message| D[Echo Handler\nSynchronous]
    C -->|Duplicate| X2[Silent Drop]
    D -->|Admin Echo| E{Bot Reactivation?}
    E -->|sofia / bot| F[Set BOT_ACTIVE\nRedis]
    E -->|Other Text| G[Set HUMAN_ACTIVE\nRedis]
    D -->|Customer Message| H[Background Thread\nThreadPoolExecutor]
    H --> I[Silent Message Filter]
    I -->|Acknowledged| X3[Silent Drop]
    I -->|Proceed| J[Spam Detection\nSliding Window]
    J -->|Blocked| K[Set HUMAN_ACTIVE]
    J -->|Clear| L[Message Gap Enforcement\nSleep if needed]
    L --> M[Prompt Injection Scan]
    M -->|Injection Detected| N[Rejection Message]
    M -->|Clean| O{Intent Classification}
    O -->|Keyword Match\n90% of traffic| P[Rule-Based Engine\nZero API Cost]
    O -->|No Match\n10% of traffic| Q[Gemini Classifier\nFallback]
    P --> R{Intent Router}
    Q --> R
    R -->|REFUND / COMPLAINT| S[Handover Message\n+ HUMAN_ACTIVE\n+ SendGrid Alert]
    R -->|WHOLESALE / SHIPPING| T[Rule Reply\n+ HUMAN_ACTIVE\n+ SendGrid Alert]
    R -->|PURCHASE| U[Confirmation Reply\n+ SendGrid Alert\nBot Stays Active]
    R -->|PRODUCT / PRICE| V[TiDB SQL Search\nFormatted Reply]
    R -->|PLAYFUL / UNKNOWN| W[RAG Retrieval\nPinecone + Gemini]
    W --> X[Guardrail Scan\nPattern Matching]
    X -->|Pass| Y[Send Response\nMessenger API]
    X -->|Fail| Z[Guardrail Handover\n+ HUMAN_ACTIVE\n+ SendGrid Alert]
    V --> Y
    S --> Y
    T --> Y
    U --> Y
    Y --> AA[Log to TiDB\nmessages + intent_log]
```

---

## AI Workflow

The classification pipeline operates in two stages, ordered by cost and confidence:

**Stage 1 — Keyword Matching (O(n) substring scan)**

Every incoming message is scanned against a manually curated keyword dictionary organized by intent. This is deliberately simple — there is no ML, no embedding, no API call. A customer typing "magkano" matches `PRICE_QUERY` in microseconds at zero cost.

The keyword dictionary is ordered with intent priority in mind. `PURCHASE` keywords appear before `PRODUCT_INQUIRY` in the dictionary because `PRODUCT_INQUIRY` contains broad terms like "bili" that would incorrectly match "pabili" (a PURCHASE signal) if checked first. This ordering is a production bug that was caught in testing — the test `test_purchase_before_product_inquiry` exists specifically to guard against regression.

**Stage 2 — Gemini Fallback (invoked only on keyword miss)**

When no keyword matches, the raw message is sent to `gemini-2.5-flash-lite` with a classification prompt listing all valid intent labels. The model returns a single label. If the label is not in the known enum, the system defaults to `UNKNOWN` rather than crashing.

This two-stage design means the free tier limit of 20 Gemini requests per day covers real production traffic without upgrades, because keyword matching resolves the vast majority of messages before Gemini is ever called.

**RAG Context Injection**

For PRODUCT and PRICE queries that reach the AI fallback, Sofia does not ask Gemini to recall product information from training data — it retrieves it. Each product in the catalog is embedded as a structured natural language document using `gemini-embedding-001` (3072-dimensional vectors) and stored in Pinecone. At query time, the customer's message is embedded and the three closest product vectors are retrieved by cosine similarity. The retrieved text is injected into the Gemini prompt as a strict context block.

The prompt explicitly instructs the model that it may only use information from the provided context. If no context is found, Gemini is told to say so rather than generate an answer from its weights.

---

## Architectural Pillars

### 1. Hybrid Deterministic/Probabilistic Logic

The rule engine and the LLM operate in completely separate domains. The rule engine handles:

- Product lookup (SQL → TiDB)
- Purchase confirmation flow
- Wholesale and shipping inquiry routing
- Refund and complaint escalation

Gemini handles:

- Playful conversational banter
- Ambiguous queries with no keyword match
- Natural language generation for edge cases

This separation was a deliberate tradeoff. A pure LLM approach would be simpler to build but would require aggressive guardrails on every response and would generate hallucinated prices on a regular basis. A pure rule-based approach would be reliable but brittle — it cannot handle the natural variation in how Filipino customers type messages in Taglish. The hybrid approach captures the reliability of rules where reliability matters and the flexibility of LLMs where flexibility matters.

### 2. Guardrail Engine

All AI-generated responses pass through a pattern-matching guardrail layer before delivery. The guardrail checks for four failure categories:

- **FABRICATED_PRODUCT** — detects invented PHP prices, fabricated SKUs, and false stock claims
- **HALLUCINATION** — detects false certainty language ("I am 100% sure", "guaranteed")
- **SYCOPHANCY** — detects patterns where the model unconditionally agrees with the user
- **UNSAFE** — detects harmful language

Any guardrail failure triggers immediate human handover, pauses the bot, and sends a SendGrid admin alert. The guardrail never silently fails — it always escalates.

Rule-based responses bypass the guardrail entirely because they are deterministic — there is nothing for the guardrail to catch in a hardcoded string.

### 3. Session Memory and Human Handover

Session state is stored in Redis with a 90-day TTL. The two states are `BOT_ACTIVE` and `HUMAN_ACTIVE`.

The handover protocol is designed around a real operational constraint: the admin manages customer conversations directly in the Facebook Page Inbox. When the admin types a reply to a customer, Facebook sends an echo event to the webhook. Sofia intercepts this echo event and immediately sets the session to `HUMAN_ACTIVE` — pausing the bot so it does not interfere with the admin's conversation.

This echo handling was originally processed in a background thread, which introduced a race condition: a customer message could arrive before the state was written to Redis, causing the bot to respond after the admin had already taken over. The fix was to process echo events **synchronously in the webhook handler** before returning 200 to Meta — guaranteeing state is written before any customer message from the same payload can be dispatched to the thread pool.

Bot reactivation uses exact-match commands (`sofia` or `bot`) to prevent accidental reactivation from messages containing those words in passing.

### 4. Resilience and Rate Protection

Several layers of protection prevent the system from being overwhelmed or abused:

- **Atomic deduplication** — Redis SETNX prevents the same message ID from being processed twice, handling Meta's at-least-once delivery guarantee
- **Spam detection** — sliding window counter blocks users who send 10+ messages in 20 seconds, setting them to HUMAN_ACTIVE silently
- **Message gap enforcement** — minimum 5-second gap between messages from the same user, sleeping the thread if needed
- **Email rate limiting** — maximum 2 admin alert emails per user per 30 minutes, preventing SendGrid quota exhaustion during complaint floods
- **Prompt injection detection** — regex scan for known jailbreak patterns before any text reaches the LLM

---

## Feature Showcase

| Capability            | Implementation               | Design Reason                                       |
| :-------------------- | :--------------------------- | :-------------------------------------------------- |
| Intent Classification | 2-stage: keyword → Gemini    | Minimize API cost while handling language variation |
| Product Lookup        | Direct TiDB SQL query        | Prevent LLM from hallucinating product data         |
| RAG Pipeline          | Pinecone + Gemini embeddings | Semantic retrieval for unstructured product queries |
| Guardrail Engine      | Regex pattern matching       | Deterministic safety — no LLM can bypass a regex    |
| Human Handover        | Echo event interception      | Admin can take over any conversation in real time   |
| Session Persistence   | Redis 90-day TTL             | Maintain context across multi-day conversations     |
| Deduplication         | Redis SETNX                  | Handle Meta's at-least-once delivery                |
| Spam Protection       | Sliding window counter       | Prevent abuse and API cost explosion                |
| Webhook Security      | HMAC-SHA256                  | Verify all requests originate from Meta             |
| Injection Detection   | Regex pattern scan           | Block prompt injection before it reaches Gemini     |
| Admin Alerting        | SendGrid + rate limit        | Notify on escalations without flooding inbox        |
| Analytics             | TiDB intent_log table        | Track intent distribution for keyword gap analysis  |

---

## Technology Stack

| Layer           | Technology               | Version          | Reason for Choice                                             |
| :-------------- | :----------------------- | :--------------- | :------------------------------------------------------------ |
| Backend         | Python + Flask           | 3.11 / 3.0       | Lightweight, async-compatible via thread pool                 |
| WSGI Server     | Gunicorn                 | 21.2             | Production-grade, Render-compatible                           |
| LLM             | Google Gemini Flash Lite | 2.5              | Best cost/performance ratio for classification and generation |
| Embeddings      | Gemini Embedding         | 001 (3072-dim)   | Consistent embedding space with generation model              |
| Vector DB       | Pinecone                 | 3.x              | Managed, serverless, cosine similarity search                 |
| Database        | TiDB Cloud               | MySQL-compatible | Serverless MySQL with built-in horizontal scaling             |
| Cache / Session | Upstash Redis            | 5.x              | Serverless Redis, Singapore region, low latency               |
| Messaging       | Meta Graph API           | v22              | Facebook Messenger platform integration                       |
| Email           | SendGrid                 | REST v3          | Reliable transactional email with delivery tracking           |
| Deployment      | Render                   | —                | Git-based deploys, Singapore region, free SSL                 |
| Testing         | pytest + unittest.mock   | —                | Mock all external services, no API keys needed in CI          |

---

## Project Structure

```
sofia-bot/
│
├── app/
│   ├── __init__.py
│   ├── main.py              # Flask app factory, startup sequence, Gunicorn hook
│   └── routes.py            # Webhook handler, echo processing, message pipeline
│
├── core/
│   ├── __init__.py
│   ├── sofia_agent.py       # SofiaAgent class — rule engine, RAG injection, guardrails
│   ├── intent_classifier.py # 2-stage classification: keyword dict → Gemini fallback
│   └── guardrails.py        # Red team pattern matching, GuardrailFailure enum
│
├── services/
│   ├── __init__.py
│   ├── session_service.py   # Redis session state, spam detection, rate limiting
│   ├── messenger_service.py # Facebook Graph API send wrapper
│   ├── email_service.py     # SendGrid alert with per-user rate limiting
│   ├── llm_service.py       # Gemini client: classification, generation, embedding
│   └── rag_service.py       # Pinecone retrieval pipeline
│
├── database/
│   ├── __init__.py
│   ├── client.py            # pymysql connection factory, TiDB SSL parsing
│   ├── models.py            # DDL — sessions, messages, intent_log tables
│   └── repository.py        # All SQL operations (no SQL outside this file)
│
├── config/
│   ├── __init__.py
│   └── settings.py          # Typed Settings dataclass, validated at startup
│
├── utils/
│   ├── __init__.py
│   ├── security.py          # HMAC verification, injection detection, deduplication
│   └── logger.py            # Structured logging, consistent format across modules
│
├── tests/
│   ├── __init__.py
│   ├── test_intent.py       # Keyword priority, Gemini fallback mock
│   ├── test_guardrails.py   # Pattern matching for all failure categories
│   └── test_agent.py        # Rule engine, product formatting, AI fallback mock
│
├── scripts/
│   ├── sync_products.py     # TiDB → Pinecone sync (run on catalog changes)
│   └── reset_session.py     # Emergency Redis session reset
│
├── .env.example             # All required environment variables documented
├── requirements.txt
├── render.yaml              # Render Blueprint deployment config
└── gunicorn.conf.py         # Worker config, post_fork startup hook
```

---

## Engineering Challenges and Solutions

**Challenge: LLM Hallucination on Product Data**

The most critical reliability problem in LLM-based commerce bots is fabricated product information. In early prototyping, routing product queries directly to Gemini produced responses with invented prices and confident stock claims.

_Solution:_ Product and price queries never reach Gemini for answer generation. The rule engine intercepts these intents, queries TiDB directly, and formats a deterministic reply. Gemini only receives product queries when the rule engine returns no match — and in that case, it receives explicit TiDB context via RAG and is instructed to use only that context.

---

**Challenge: Race Condition in Human Handover**

The original implementation processed all webhook events — including admin echo events — in a background ThreadPoolExecutor. This introduced a race condition: a customer message and an admin echo could arrive in the same webhook payload, and if the customer message thread was dispatched before the echo thread wrote the `HUMAN_ACTIVE` state to Redis, the bot would respond after the admin had already taken over.

_Solution:_ Echo events are now processed synchronously in the webhook handler before any background threads are dispatched. State is written to Redis before the function returns 200, guaranteeing ordering regardless of thread scheduling.

---

**Challenge: Keyword Priority Ordering**

`PRODUCT_INQUIRY` keywords included "bili" (to buy) as a product-related term. This caused "pabili" (I want to buy) to match `PRODUCT_INQUIRY` instead of `PURCHASE`, returning a product list instead of the purchase confirmation flow.

_Solution:_ `PURCHASE` keywords are defined before `PRODUCT_INQUIRY` in the intent dictionary. Python dicts preserve insertion order — the first matching intent wins. A regression test (`test_purchase_before_product_inquiry`) guards this ordering permanently.

---

**Challenge: Silent Failures on Windows SSL**

The original `mysql-connector-python` library silently hung on Windows when SSL was configured, with no error, no timeout, and no log output. This took significant debugging time to identify.

_Solution:_ Migrated entirely to `pymysql`, which handles SSL via a dict parameter (`ssl={"ca": path}`) and does not exhibit the Windows hang behavior. The SSL cert path is parsed from the MYSQL_URI query string, keeping configuration in one place.

---

**Challenge: API Cost Control**

Gemini's free tier allows 20 classification requests per day. Without cost controls, a small burst of messages from customers using natural language variations not covered by keywords would exhaust the daily quota by midday.

_Solution:_ The two-stage classification architecture ensures Gemini is only called on a keyword miss. In production analytics, keyword matching resolves approximately 75–90% of traffic, keeping Gemini usage well within free tier limits for normal traffic volumes.

---

## Local Development

```bash
# 1. Clone the repository
git clone https://github.com/Lawrenze09/SOFIA-RAG-enabled-conversational-commerce-middleware.git
cd SOFIA-RAG-enabled-conversational-commerce-middleware

# 2. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 5. Start the development server
python -m app.main

# 6. Expose local server for Messenger webhook testing
ngrok http 5001
# Copy the ngrok HTTPS URL → Meta Developer Dashboard → Webhooks
```

**Environment Variables**

| Variable            | Required | Description                                |
| :------------------ | :------- | :----------------------------------------- |
| `GEMINI_API_KEY`    | ✅       | Google Gemini API key                      |
| `MYSQL_URI`         | ✅       | TiDB connection string with SSL cert path  |
| `REDIS_URL`         | ✅       | Upstash Redis connection URL               |
| `SENDGRID_API_KEY`  | ✅       | SendGrid API key for admin alerts          |
| `ADMIN_EMAIL`       | ✅       | Recipient address for alert emails         |
| `META_APP_SECRET`   | ✅       | Facebook App Secret for HMAC verification  |
| `PAGE_ACCESS_TOKEN` | ✅       | Facebook Page permanent access token       |
| `VERIFY_TOKEN`      | ✅       | Webhook verification token                 |
| `PINECONE_API_KEY`  | ⚪       | Pinecone API key — RAG disabled if missing |
| `PINECONE_INDEX`    | ⚪       | Pinecone index name                        |
| `FLASK_ENV`         | ⚪       | `development` uses in-memory rate limiter  |

---

## Deployment

### Render (Production)

```bash
# Option A — Render Blueprint (recommended)
# Push render.yaml to GitHub → Render Dashboard → New → Blueprint

# Option B — Manual
# Render Dashboard → New → Web Service → Connect GitHub repo
# Build Command:  pip install -r requirements.txt
# Start Command:  gunicorn "app.main:create_app()" --config gunicorn.conf.py
# Region:         Singapore
```

**Secret Files** (Render Dashboard → Environment → Secret Files)

| Path                          | Content                                         |
| :---------------------------- | :---------------------------------------------- |
| `/etc/secrets/isrgrootx1.pem` | TiDB SSL certificate (paste full file contents) |

Update `MYSQL_URI` to reference the secret file path:

```
MYSQL_URI=mysql+pymysql://user:pass@host:4000/db?ssl_ca=/etc/secrets/isrgrootx1.pem&ssl_verify_cert=true
```

**Post-Deployment**

```bash
# Update Facebook Webhook URL
# Meta Developer Dashboard → Webhooks → Edit
# Callback URL: https://sofia-rag-enabled-conversational.onrender.com/webhook

# Sync product catalog to Pinecone
python scripts/sync_products.py
```

**Health Check**

```
GET https://sofia-rag-enabled-conversational.onrender.com/health
# Returns: {"redis": "ok", "mysql": "ok", "status": "ok"}
```

**Analytics**

```
GET https://sofia-rag-enabled-conversational.onrender.com/analytics/monthly
# Returns: intent distribution with counts and percentages
```

---

## Testing

```bash
# Install test dependencies
pip install pytest

# Run full test suite
pytest tests/ -v
```

**Test Architecture**

All external services (Gemini, Pinecone, TiDB, Redis) are mocked using `unittest.mock.patch`. The test suite runs entirely offline with no API keys required. This design means tests can run in CI without secrets and validate logic independently of external service availability.

| Test File            | Coverage                                                       |
| :------------------- | :------------------------------------------------------------- |
| `test_intent.py`     | Keyword priority ordering, Gemini fallback, edge cases         |
| `test_guardrails.py` | All four failure categories, clean response passthrough        |
| `test_agent.py`      | Rule engine responses, product formatting, AI fallback routing |

---

## API Endpoints

| Method | Endpoint             | Auth         | Description                             |
| :----- | :------------------- | :----------- | :-------------------------------------- |
| `GET`  | `/webhook`           | VERIFY_TOKEN | Facebook webhook challenge verification |
| `POST` | `/webhook`           | HMAC-SHA256  | Receive and process Messenger events    |
| `GET`  | `/health`            | None         | Redis + MySQL connectivity check        |
| `POST` | `/reset/<psid>`      | None         | Emergency session reset for a user      |
| `GET`  | `/analytics/monthly` | None         | Intent distribution report              |

---

## Privacy Policy

This application is deployed on Facebook Messenger and complies with Meta's platform policies.
[View Privacy Policy](https://lawrenze09.github.io/Hybrid-AI-Messenger-Bot/privacy.html)

---

## Author

Built by **Nazh Lawrenze Romero**

- GitHub: [@Lawrenze09](https://github.com/Lawrenze09)
- LinkedIn: [Lawrenze Romero](https://www.linkedin.com/in/lawrenze-romero-6b6871378/)

---

## License

MIT License — see [LICENSE](LICENSE) for details.
