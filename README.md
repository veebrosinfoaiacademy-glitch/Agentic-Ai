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
- [ ] Phase 10 — Frontend/backend integration
- [ ] Phase 11 — Conversation history
- [ ] Phase 12 — Testing and error handling
- [ ] Phase 13 — Deployment
- [ ] Phase 14 — Documentation
