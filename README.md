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
npm run dev
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
| `JWT_SECRET` | Phase 8 | Signing key for auth tokens |
| `JWT_ALGORITHM` | Phase 8 | Token algorithm (HS256) |
| `JWT_EXPIRE_MINUTES` | Phase 8 | Token lifetime |
| `CORS_ORIGINS` | Phase 2 | Comma-separated allowed origins |
| `MAX_UPLOAD_MB` | Phase 7 | Upload size limit |

---

## Progress

- [x] **Phase 1** — Project setup
- [x] **Phase 2** — FastAPI backend foundation (config, CORS, error handling, health, tests)
- [x] **Phase 3** — MongoDB Atlas + PyMongo (pending real Atlas credentials)
- [x] **Phase 4** — Groq API integration (pending a real API key)
- [ ] Phase 5 — Content Agent
- [ ] Phase 6 — Developer Productivity Agent
- [ ] Phase 7 — Document upload and processing
- [ ] Phase 8 — Authentication
- [ ] Phase 9 — Frontend dashboard and agent interfaces
- [ ] Phase 10 — Frontend/backend integration
- [ ] Phase 11 — Conversation history
- [ ] Phase 12 — Testing and error handling
- [ ] Phase 13 — Deployment
- [ ] Phase 14 — Documentation
