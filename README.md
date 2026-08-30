# 🩺 Guttify AI Assistant

A conversational product-recommendation chatbot for **Guttify**, a gut-health/wellness supplement line. It asks a few natural clarifying questions, understands the user's symptoms in plain language, and recommends a product **only** from Guttify's own product database — the underlying LLM is used purely to phrase replies, never to decide what to recommend.

Built with **FastAPI**, a small **Groq**-hosted LLM for conversational phrasing, and a fully deterministic, dependency-light Python recommendation engine.

---

## Table of Contents

- [Why it's built this way](#why-its-built-this-way)
- [Features](#features)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [Running Locally](#running-locally)
- [API Endpoints](#api-endpoints)
- [Example Conversations](#example-conversations)
- [Testing](#testing)
- [Product Data](#product-data)
- [Deployment](#deployment)
- [Safety Notes](#safety-notes)
- [Contributing](#contributing)

---

## Why it's built this way

Letting an LLM freely choose which product to recommend risks hallucinated products, invented ingredients, or unsafe suggestions. Guttify instead uses the LLM only to *understand and phrase* — a deterministic Python engine makes the actual product decision from `products.json`, so:

- A product can **never** appear in a response unless it was actually loaded from `products.json`.
- A product **never** scores above zero without an explicit primary-symptom match — "somewhat related to digestion" is never enough on its own.
- The conversation never asks more than **3** clarifying questions, and never re-asks something the user already said.
- Anything that looks like a serious/red-flag symptom short-circuits straight to "seek medical care," before any product logic runs.

## Features

- 🗣️ **Natural language understanding** — synonym/intent mapping turns phrases like *"my stomach gets swollen"* or *"burning in my chest after meals"* into the right canonical symptom, without needing an embedding model.
- 🎯 **Deterministic recommendation engine** — explicit, auditable scoring rules instead of vague semantic similarity; ties are never guessed — the assistant asks up to 2 targeted questions to try to break the tie, and if it's still unresolved, presents every tied product side by side with the symptoms and support that make each one distinct.
- 🛡️ **Two-tier safety layer** — red-flag detection (e.g. vomiting blood, black stool, jaundice, fainting) stops the flow and tells the user to seek care; softer caution rules (pregnancy, existing conditions, medication) recommend checking with a doctor first.
- 💬 **Bounded, adaptive conversation** — up to 3 follow-up questions, skipped entirely when the user already gave enough detail in one message.
- 👋 **Greeting handling** — a plain "hi" / "hey" / "yo" / "what's up" gets a friendly reply instead of being treated as gibberish or off-topic.
- 🔍 **Named-product lookup** — "what are the ingredients in Piloease?" is answered directly, no symptom description required.
- 🚫 **Gibberish & off-topic filtering** — keyboard-mash input and unrelated questions ("who is the president?") are rejected cleanly.
- 💾 **Session-based conversations** — structured symptom state and chat history are tracked per session in memory.
- 👋 **Graceful session close** — after a recommendation, a "thanks, that's all!" style remark ends the session (`SESSION_ENDED`) instead of leaving it open indefinitely; a genuine follow-up question is never mistaken for a closing remark.
- 🎯 **Hallucination guard on the LLM reply** — the LLM only ever phrases an already-approved product; every reply is checked to make sure it doesn't name a different Guttify product, regenerated once if it does, and if it still fails, a fully template-based reply (no LLM involved) is used instead.
- ✅ **Automated test suite** — 29 tests covering matching, safety, conversation flow, and edge cases, with no network or model dependency required to run them.

## Architecture

```
User message
    │
    ▼
Greeting check ───────────► "Hi! What can I help you with?"
    │
    ▼
Gibberish check ──────────► Light "try again?" response
    │
    ▼
Safety check (red flags) ─► "Please seek medical care" (stops here)
    │
    ▼
Named-product lookup ─────► Direct product-info answer (skips Q&A)
    │
    ▼
Intent parser
(free text → structured
 symptom state)
    │
    ▼
Deterministic recommendation engine
    │
    ├─ Confident match ──────► Recommendation (LLM phrases the reply)
    ├─ Ambiguous match ──────► Ask up to 2 targeted tie-break questions,
    │                          then show every tied product side by side
    │                          with what makes each one distinct
    └─ Not enough info ──────► Ask a clarifying question (max 3 total)
                               or return "no close match"
```

The LLM (`guttify_chatbot.py`, via Groq) only ever sees an **already-approved** product dict and turns it into a natural-sounding reply — it cannot introduce a different product, ingredient, or claim.

## Project Structure

```
guttify-chatbot/
│
├── app.py                        # FastAPI entrypoint — HTTP, sessions, static files only
├── guttify_agent.py               # Conversation manager: question cap, flow control
├── intent_parser.py                # Free text → structured symptom state (rule-based, no ML)
├── recommendation_engine.py       # Deterministic product scoring & matching
├── safety_checker.py              # Red-flag + caution safety rules
├── gibberish_checker.py           # Keyboard-mash / nonsense input filter
├── greeting_checker.py            # Greeting detection ("hi", "yo", "what's up", ...)
├── satisfaction_checker.py        # Closing-remark detection ("thanks!", "got it", ...)
├── guttify_chatbot.py              # LLM-backed reply phrasing (Groq)
├── products.json                  # Product database — single source of truth
│
├── create_memory_for_llm.py       # (optional) builds a FAISS store from PDFs for RAG
├── connect_memory_with_llm.py     # (optional) one-shot RAG CLI using that FAISS store
│
├── tests/
│   └── test_recommendation.py     # Automated test suite (stdlib unittest)
│
├── static/
│   ├── index.html
│   ├── app.js
│   └── style.css
│
├── requirements.txt
├── Pipfile
├── Dockerfile
└── .gitignore
```

> `create_memory_for_llm.py` and `connect_memory_with_llm.py` are optional offline CLI scripts for an alternative RAG-based approach. They are **not** imported by the live web app and pull in heavier dependencies (FAISS, sentence-transformers) on their own.

## Requirements

- Python 3.10+
- A [Groq](https://console.groq.com) API key (free tier available) — powers the live chatbot's reply phrasing
- Git

The live recommendation path (`recommendation_engine.py`, `intent_parser.py`, `safety_checker.py`, `guttify_agent.py`) has **no ML/embedding dependency** — it's plain Python, which keeps it cheap to run in a small container.

## Installation

1. **Clone the repository**

   ```bash
   git clone <YOUR_GITHUB_REPOSITORY_URL>
   cd <YOUR_REPOSITORY_FOLDER>
   ```

2. **Create and activate a virtual environment**

   macOS / Linux:
   ```bash
   python -m venv env
   source env/bin/activate
   ```

   Windows PowerShell:
   ```powershell
   python -m venv env
   .\env\Scripts\Activate.ps1
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

## Environment Variables

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_groq_api_key
```

> ⚠️ Never commit `.env` to version control. `.gitignore` already excludes it, along with `env/`, `.venv/`, `__pycache__/`, and `*.pyc`.

If you also plan to use the optional RAG CLI scripts (`create_memory_for_llm.py` / `connect_memory_with_llm.py`), add:

```
HF_TOKEN=your_huggingface_token
```

## Running Locally

Start the FastAPI server:

```bash
uvicorn app:app --reload
```

Then open:

```
http://127.0.0.1:8000
```

## API Endpoints

### Create a session

```
POST /api/session
```

Creates a fresh chat session (and resets any prior conversation state for it).

**Response**
```json
{ "session_id": "..." }
```

### Chat

```
POST /api/chat
```

**Request**
```json
{
  "session_id": "your-session-id",
  "message": "I have bloating after eating dairy"
}
```

**Response**
```json
{
  "reply": "...",
  "status": "RECOMMENDATION_FOUND"
}
```

`status` is one of: `GREETING`, `GIBBERISH`, `IRRELEVANT`, `SAFETY_REVIEW`, `ASK`, `AMBIGUOUS`, `NO_MATCH`, `PRODUCT_INFO_FOUND`, `RECOMMENDATION_FOUND`, `SESSION_ENDED`.

Once a `RECOMMENDATION_FOUND` or `PRODUCT_INFO_FOUND` reply has been sent, the session starts watching for a closing remark ("thanks!", "great, that's all I needed", "got it", ...). The next such remark ends the session with `SESSION_ENDED`; any further message on that same `session_id` gets a polite "start a new chat" reply instead of being processed. A message that isn't purely a closing remark (e.g. it asks a further question) is unaffected and flows through normally.

## Example Conversations

**Greeting**
> **User:** yo
> **Assistant:** Hey! I'm here to help with Guttify products — what's bothering you?

**Multi-turn symptom flow**
> **User:** liver issue
> **Assistant:** Got it. What are you experiencing most — bloating, acidity, pain, constipation, or something else?
> **User:** bloating, happens a few times a week and it's related to food
> **Assistant:** Which food seems to trigger it most — dairy, spicy/oily food, wheat, beans/lentils, or not sure?
> **User:** dairy
> **Assistant:** *(recommends the best-matching product)*

**One-shot, fully-specified message**
> **User:** I get bloating every day after eating paneer.
> **Assistant:** *(already has enough info — recommends directly, no extra questions)*

**Named product**
> **User:** What are the ingredients of Piloease?
> **Assistant:** *(answers directly from product data, no symptom Q&A)*

**Closing out after a recommendation**
> **Assistant:** *(recommends Digest Boost)*
> **User:** Thanks, that's helpful!
> **Assistant:** Glad that helped! This chat will close out now — feel free to start a new one anytime you have another gut-health question. *(session ends — `SESSION_ENDED`)*

**Red-flag safety**
> **User:** I have severe abdominal pain and I'm vomiting blood.
> **Assistant:** Please seek medical care promptly — I'm not able to recommend a supplement for this.

**Off-topic**
> **User:** Who is the president of the United States?
> **Assistant:** That's not something I can help with — I'm here for Guttify product questions.

## Testing

The test suite uses only the Python standard library (`unittest`) — no network or model calls required:

```bash
python -m unittest discover -s tests -v
```

Covers: exact & synonym symptom matching, food-trigger extraction, the "no primary-symptom match = zero score" rule, red-flag detection, greeting handling, the 3-question conversation cap, named-product bypass, ambiguous-match handling, and malformed/missing-data edge cases.

## Product Data

All product information — symptoms, intended support, ingredients, usage, warnings, flavors — lives in [`products.json`](./products.json). It is the **only** source of truth for recommendations; nothing is invented at request time.

## Deployment

**Build command**
```bash
pip install -r requirements.txt
```

**Start command**
```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Set `GROQ_API_KEY` (and `HF_TOKEN` if using the optional RAG scripts) as environment variables on your hosting platform — never in the repository itself.

A `Dockerfile` is included for container-based deployment.

## Safety Notes

- Guttify AI Assistant is a **wellness/product assistant, not a doctor**. It does not diagnose medical conditions.
- Symptoms consistent with a medical emergency (e.g. vomiting blood, black stool, jaundice, fainting, difficulty breathing) are detected and routed to a "seek medical care" response instead of a product recommendation.
- Product information always comes from `products.json` — the LLM cannot invent ingredients, dosages, prices, or claims.
- Conversation history and structured symptom state currently exist only in process memory and reset when the server restarts (see the notes in `app.py` for scaling this to multiple workers).

## Contributing

```bash
git status
git add .
git commit -m "Update Guttify chatbot"
git push
```

Please run the test suite before opening a PR:

```bash
python -m unittest discover -s tests -v
```
