# RAPTOR Live Visualizer

Educational web app that builds a [RAPTOR](https://github.com/parthsarthi03/raptor) tree from
pasted text and renders the construction live, then lets you explore the tree and run
retrieval queries against it.

- **Backend**: FastAPI + RAPTOR, deployed on Render
- **Frontend**: Angular + D3, deployed on Vercel
- **DB**: MongoDB Atlas
- **Streaming**: Server-Sent Events

Build phases (see prompt for details): the repo is being built incrementally. Current
status: **Phase 1 — backend skeleton complete**.

## Repo layout

```
backend/
  app/
    main.py            FastAPI app, /health
    serialization.py   RAPTOR Tree → JSON
    settings.py        env config
  scripts/
    sample_build.py    end-to-end smoke test
  tests/               pytest unit tests
  requirements.txt
  .env.example
```

## Backend — local run

Requires Python 3.11+. A working OpenAI API key is needed for any real tree build
(RAPTOR uses OpenAI for both embeddings and summarization by default).

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then edit and paste your OPENAI_API_KEY
```

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
pytest
```

The serializer is duck-typed against `Node`/`Tree` so its tests run without RAPTOR
or an OpenAI key.

## Known caveats

- **RAPTOR pins old dependency versions** (`numpy==1.26.3`, `transformers==4.38.1`,
  `openai==1.3.3`). Install in an isolated venv. On Python 3.13 some of these are
  shaky — Python 3.11 is the safest target.
- **`RetrievalAugmentation.add_documents` calls `input()`** if a tree already exists,
  which will hang a server. We'll bypass it in phase 2 by calling
  `tree_builder.build_from_text` directly.
- **OpenAI key is the server's**, not the user's. Rate limits enforced server-side
  (phase 4): 5 builds/day per IP, ~40 KB max input.

## Deployment

Wired up in a later phase. Render for the FastAPI service, Vercel for Angular,
MongoDB Atlas free tier. Secrets needed:

- `OPENAI_API_KEY` (Render)
- `MONGODB_URI` (Render)
- `FRONTEND_ORIGIN` (Render, set to the Vercel URL)
