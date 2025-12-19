# backend/models/user.py
from sqlalchemy import Column, Integer, String
from backend.core.db import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    github_id = Column(Integer, unique=True, index=True)
    github_login = Column(String, unique=True, index=True)
    name = Column(String, nullable=True)
