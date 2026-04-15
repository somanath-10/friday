"""
Configuration — load environment variables and app-wide settings.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SERVER_NAME: str = os.getenv("SERVER_NAME", "Friday")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")


config = Config()
