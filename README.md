# AI-Powered Content Creation and Developer Productivity Agents

Full-stack AI platform with two specialised agents: a **Content Creation Agent**
and a **Developer Productivity Agent**.

**Stack:** React + Tailwind CSS · FastAPI + Pydantic · Groq · MongoDB Atlas

---

## Setup

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env      # then fill in real values
uvicorn app.main:app --reload --port 8000
```

- API: http://localhost:8000/api/health
- Swagger docs: http://localhost:8000/docs
- OpenAPI schema: http://localhost:8000/openapi.json

Run the tests:

```bash
cd backend
source venv/bin/activate
pytest
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env    # VITE_API_BASE_URL only — never provider secrets
npm run dev
```

Run the frontend tests:

```bash
cd frontend
npm test
```

- App: http://localhost:5173

---

## API response format

Every endpoint returns one of two shapes.

**Success**

```json
{
  "success": true,
  "message": "Request successful",
  "data": {}
}
```

**Error**

```json
{
  "success": false,
  "message": "Internal server error",
  "error": { "code": "INTERNAL_SERVER_ERROR", "details": null }
}
```

---

## Environment variables

Declared in `.env.example`. The real `.env` lives in `backend/` and is
git-ignored — never commit it.

| Variable | Required from | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Phase 4 | Groq API authentication |
| `GROQ_MODEL` | Phase 4 | Which LLM to call |
| `MONGODB_URI` | Phase 3 | MongoDB Atlas connection string |
| `MONGODB_DB_NAME` | Phase 3 | Database name |
| `JWT_SECRET` | Phase 8 | Signing key for auth tokens (use 32+ bytes) |
| `JWT_ALGORITHM` | Phase 8 | Token algorithm (HS256) |
| `JWT_EXPIRE_MINUTES` | Phase 8 | Token lifetime |
| `CORS_ORIGINS` | Phase 2 | Comma-separated allowed origins |
| `MAX_UPLOAD_MB` | Phase 7 | Upload size limit |
| `DOCUMENT_MAX_EXTRACTED_CHARACTERS` | Phase 7 | Extracted text limit |

Frontend (`frontend/.env`) takes only `VITE_API_BASE_URL`. Provider secrets
must never appear there — the browser talks to FastAPI, and FastAPI talks to
Groq and MongoDB.

---

## Authentication

Every AI and document-processing endpoint requires a signed-in user. Identity
comes from the JWT and nothing else — a `user_id` in a request body is ignored,
and no request schema accepts one.

**Public** (no token):

| Endpoint | Why |
|---|---|
| `GET /api/health` | Liveness probe |
| `POST /api/auth/register` | Otherwise nobody could sign up |
| `POST /api/auth/login` | Otherwise nobody could sign in |
| `GET /api/documents/supported-types` | Global server configuration, no user data |

**Protected** (`Authorization: Bearer <token>`): `GET /api/auth/me`, all 7
`/api/content/*`, all 7 `/api/developer/*`, `POST /api/documents/upload`,
`POST /api/ai/test`, and all 6 `/api/conversations` routes.

Conversations are user-owned. Every query carries the owner as part of the
filter, so another account's conversation is indistinguishable from one
that never existed — both return 404.

Authentication is resolved **before** the request reaches Groq, the document
extractor or any user-owned database read, so an anonymous request can never
cause provider spend.

### Testing a protected endpoint

```bash
# 1. Get a token
curl -s -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"your-password"}'

# 2. Send it as a Bearer token
curl -s -X POST http://localhost:8000/api/content/summarize \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{"text":"Some source text.","summary_type":"short"}'
```

Or use Swagger at `/docs` → **Authorize** → paste the token → protected routes
become callable.

Tokens remain **stateless**: no refresh tokens, no blacklist, no session
storage. Signing out means the client discarding its token, and a token stops
working when it expires or its account is deleted.

---

## Production deployment

**Not yet deployed.** The configuration below is written and verified locally
in production mode; no hosted instance exists.

```
                Internet
                   │  HTTPS
        ┌──────────┴──────────┐
        │  Vercel (static)    │   React bundle, CDN-served
        └──────────┬──────────┘
                   │  fetch, CORS-restricted
        ┌──────────┴──────────┐
        │  Render (web svc)   │   FastAPI + uvicorn
        └──────────┬──────────┘
            ┌──────┴───────┐
        MongoDB Atlas    Groq API
```

**Why this shape.** Render runs FastAPI from `requirements.txt` with no
container to maintain, gives HTTPS and a health check on the free tier, and
deploys from GitHub. Vercel serves a Vite build as static files, so the
frontend has no server to run at all. Both keep secrets in their dashboard
rather than in git. Atlas and Groq are already in use and unchanged.

### Deploying the backend (Render)

`render.yaml` is a blueprint — point Render at the repository and it reads it.

- Root directory: `backend`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (never `--reload`)
- Health check path: `/api/health`

Set these in the dashboard (they are `sync: false` in the blueprint, so no
value is ever committed):

| Variable | Notes |
|---|---|
| `GROQ_API_KEY` | From console.groq.com |
| `MONGODB_URI` | Atlas connection string |
| `JWT_SECRET` | Render can generate it; 32+ bytes |
| `CORS_ORIGINS` | Exactly the deployed frontend origin, for example `https://agentic-ai-phi-two.vercel.app` |

### Deploying the frontend (Vercel)

- Root directory: `frontend`
- Build: `npm run build`, output `dist`
- Set `VITE_API_BASE_URL` to the Render URL plus `/api`, for example `https://agentic-ai-zhln.onrender.com/api`

The build **fails deliberately** if `VITE_API_BASE_URL` is missing, rather
than silently shipping a bundle pointed at localhost.

### CORS

Development allows `http://localhost:5173`. Production must be set to the
deployed frontend origin only. Never `*` — it is invalid alongside
credentials and would let any site call the API with a user's token.

### MongoDB Atlas

Render's free tier uses dynamic outbound IPs, so Atlas Network Access needs
`0.0.0.0/0`. That is a real trade-off: the cluster is reachable from any
address, and only the database credentials protect it. Mitigations are a
strong generated password, a least-privilege user scoped to this database,
and rotating the credential if it is ever exposed. A static outbound IP
(Render paid tier) or Atlas Private Endpoint removes the trade-off.

### After deploying

1. `GET /api/health` returns 200 with `database.connected: true`
2. Register, log in, and confirm `/api/auth/me`
3. Confirm the browser can reach the API (CORS) from the real frontend origin
4. Confirm `X-Request-ID` appears on responses

Free-tier Render sleeps after inactivity, so the first request after an idle
period takes several seconds. That affects the demo, not correctness.

### CI

`.github/workflows/ci.yml` runs on every push and PR: backend `pytest`,
frontend lint/test/build, and a secret scan. It needs no secrets — the test
suite fakes MongoDB and Groq, so CI never touches Atlas or spends quota.

---

## Progress

- [x] **Phase 1** — Project setup
- [x] **Phase 2** — FastAPI backend foundation (config, CORS, error handling, health, tests)
- [x] **Phase 3** — MongoDB Atlas + PyMongo — verified against a live cluster
- [x] **Phase 4** — Groq API integration — verified against the live API
- [x] **Phase 5** — Content Agent (7 tasks) — verified against the live API
- [x] **Phase 6** — Developer Agent (7 tasks) — verified against the live API
- [x] **Phase 7** — Document upload and extraction (txt, md, csv, pdf, docx)
- [x] **Phase 8** — Authentication (Argon2id + JWT), verified against live Atlas
- [x] **Phase 9** — React dashboard, agent interfaces, auth UI (45 frontend tests)
- [x] **Phase 10** — Protected AI/document APIs, JWT-derived identity
- [x] **Phase 11** — Conversation history and persistent AI sessions
- [ ] Phase 12 — Testing and error handling
- [x] **Phase 15** — Production deployment configuration (not yet deployed)
- [ ] Phase 14 — Documentation
