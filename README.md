# RAPTOR Live Visualizer

Educational web app that builds a [RAPTOR](https://github.com/parthsarthi03/raptor) tree from
pasted text and renders the construction live, then lets you explore the tree and run
retrieval queries against it.

- **Backend**: FastAPI + RAPTOR, deployed on Render
- **Frontend**: Angular + D3, deployed on Vercel
- **DB**: MongoDB Atlas
- **Streaming**: Server-Sent Events

Build phases: **Phases 1–7 complete** (everything except the final design polish pass).
What works today:

- Live build view streams chunk → embed → cluster → summarize → layer-complete events
  via SSE and animates each node as it arrives.
- Explore view re-renders the finished tree with click-to-inspect side panel.
- Query mode hits `/api/builds/{id}/query` with collapsed-tree or tree-traversal
  retrieval and glows the retrieved nodes.
- **$ caps, not build counts.** Global $1/day and per-IP $0.10/day OpenAI spend
  caps, refused at 90 % of each (so a $1 cap actually refuses at $0.90 to leave
  headroom for in-flight requests). 20,000-char input cap. 24 h TTL on trees.
- **gpt-4o-mini + text-embedding-3-small** for all OpenAI calls — RAPTOR's
  default `gpt-3.5-turbo` + `text-embedding-ada-002` were 5–10× pricier.
- **Out-of-funds UX.** If the OpenAI account itself runs dry mid-build, the
  partial tree is preserved and the visitor sees a friendly "piggy bank ran
  dry" message instead of a stack trace.

## Repo layout

```
backend/
  app/
    main.py            FastAPI app + lifespan hooks
    api.py             /api/builds + SSE stream + query
    builder.py         EventEmittingBuilder (subclasses ClusterTreeBuilder)
    build_session.py   per-build asyncio.Queue + thread-safe emit
    events.py          BuildEvent shape (chunked, embedded, …)
    db.py              Motor (MongoDB) + per-IP daily quota + TTL
    serialization.py   RAPTOR Tree → JSON
    settings.py        env config
  scripts/sample_build.py
  tests/               22 pytest tests, all OpenAI/Mongo-free
  vendor/raptor/       upstream RAPTOR as a git submodule
frontend/
  src/app/
    app.component.ts, app.config.ts, app.routes.ts
    pages/home, pages/build, pages/explore
    components/tree-view.component.ts   (D3 layout + animation)
    services/api.service.ts, services/sse.service.ts
```

## Backend — local run

Requires Python 3.11+. A working OpenAI API key is needed for any real tree build
(RAPTOR uses OpenAI for both embeddings and summarization by default).

```bash
git submodule update --init   # fetch the vendored RAPTOR source (one-time)
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit and paste your OPENAI_API_KEY
```

RAPTOR is vendored as a git submodule at `backend/vendor/raptor` because the
upstream repo has no `setup.py`/`pyproject.toml` and can't be `pip install`-ed
directly. `backend/app/__init__.py` adds it to `sys.path`.

### Health check

```bash
uvicorn app.main:app --reload
curl http://localhost:8000/health
# {"status":"ok","openai_key_configured":true}
```

### Phase 1 smoke test — build a tree from a hardcoded paragraph

```bash
python -m scripts.sample_build
```

This calls OpenAI (embeddings + summarization). With the small sample paragraph the
cost is a fraction of a cent. Output is the serialized tree as JSON — the same shape
the frontend will consume.

### Tests

```bash
pytest          # backend — 22 tests, no OpenAI/Mongo needed
```

All backend tests run without RAPTOR, OpenAI, or Mongo: the serializer is duck-typed,
the API tests stub `BuildSession.run`, the DB tests stub the Motor collection.

## Frontend — local run

```bash
cd frontend
npm install
npm start                 # serves on http://localhost:4200
```

The frontend defaults its API base to `http://localhost:8000`. To override at runtime,
set `window.RAPTOR_API_BASE` in `src/index.html` before bootstrap.

```bash
npm test                  # karma + jasmine
```

## Spend tracking & caps

All OpenAI usage flows through `app/raptor_models.py` (subclasses of RAPTOR's
`BaseEmbeddingModel` / `BaseSummarizationModel` / `BaseQAModel`). Every call's
`usage.prompt_tokens` + `completion_tokens` is converted to USD via the price
table in `app/cost_tracker.py` and `$inc`'d atomically into Mongo:

```
spend_log         { _id: "YYYY-MM-DD", cost_usd, prompt_tokens, ... }
spend_log_ip      { _id: "YYYY-MM-DD::<ip>", cost_usd, ... }
```

Two env-tunable caps (`.env`):

| | default | env var |
|---|---|---|
| Global daily | $1.00 | `DAILY_USD_CAP` |
| Per-IP daily | $0.10 | `PER_IP_USD_CAP` |
| Safety margin | 90 % | `SAFETY_MARGIN` |
| Concurrency cap | 8 in-flight | `OPENAI_MAX_CONCURRENCY` |
| Max input chars | 20,000 | `MAX_INPUT_CHARS` |

**Price table drifts** when OpenAI changes prices — update the `PRICE_TABLE` dict
in `app/cost_tracker.py` if you notice over- or under-billing.

**Mongo is the source of truth.** If it's unreachable the API refuses all new
builds with HTTP 503; better to be down briefly than blow through the budget.

## Known caveats

- **RAPTOR's upstream requirements pin very old versions** (`numpy==1.26.3`,
  `transformers==4.38.1`, `openai==1.3.3`) that no longer have wheels for newer
  Pythons. We've bumped them to mid-2024 versions in `requirements.txt`; if RAPTOR
  internals break on a bumped lib, fall back to upstream pins on Python 3.11.
- **`RetrievalAugmentation.add_documents` calls `input()`** if a tree already exists,
  which will hang a server. We'll bypass it in phase 2 by calling
  `tree_builder.build_from_text` directly.
- **OpenAI key is the server's**, not the user's. Rate limits enforced server-side
  (phase 4): 5 builds/day per IP, ~40 KB max input.

## Deployment

Wired up in a later phase. Render for the FastAPI service and for Angular,
MongoDB Atlas free tier. Secrets needed:

- `OPENAI_API_KEY` (Render)
- `MONGODB_URI` (Render)
