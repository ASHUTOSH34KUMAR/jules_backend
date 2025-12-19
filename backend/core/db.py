# backend/core/db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from backend.core.config import settings

# SQLAlchemy Base class (for our models)
Base = declarative_base()

# Engine (PostgreSQL)
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


# Dependency for FastAPI routes (when we start using it there)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
