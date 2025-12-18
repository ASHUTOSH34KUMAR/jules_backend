# backend/core/config.py
import os
from dotenv import load_dotenv

load_dotenv()  # load from .env

class Settings:
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    GITHUB_OAUTH_CALLBACK_URL: str = os.getenv("GITHUB_OAUTH_CALLBACK_URL", "")
    GITHUB_OAUTH_SCOPES: str = os.getenv("GITHUB_OAUTH_SCOPES", "repo read:user")

settings = Settings()
