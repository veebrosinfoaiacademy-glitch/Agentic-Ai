"""MongoDB Atlas connection.

Placeholder for Phase 3. It exists now so the import path is stable and the
project structure is complete, but it deliberately holds no connection logic
yet — Phase 2 must start without a database.

Phase 3 will add:
    - a PyMongo MongoClient built from settings.MONGODB_URI
    - typed collection handles (users, conversations, documents, code_reviews)
    - index creation on startup
    - a ping() helper used by the /api/health endpoint
"""
