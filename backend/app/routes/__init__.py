"""Router aggregation.

Every feature router is collected here and mounted once in main.py. Adding a
new feature in a later phase is then a two-line change in this file, and
main.py never has to be touched again.
"""

from fastapi import APIRouter

from app.routes import ai, content, developer, documents, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(ai.router, prefix="/ai")
api_router.include_router(content.router, prefix="/content")
api_router.include_router(developer.router, prefix="/developer")
api_router.include_router(documents.router, prefix="/documents")

# Later phases will add:
#   api_router.include_router(auth.router, prefix="/auth")
#   api_router.include_router(documents.router, prefix="/documents")
#   api_router.include_router(conversations.router, prefix="/conversations")
