"""Configuration for the AI Agent Framework.

Priority for .env loading:
1. Current working directory (CWD) — for user projects
2. Package directory — for development / fallback
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Try CWD first (backward compatible)
cwd_env = Path.cwd() / ".env"
if cwd_env.exists():
    load_dotenv(dotenv_path=cwd_env)
else:
    # Fallback to package directory
    pkg_env = Path(__file__).parent / ".env"
    if pkg_env.exists():
        load_dotenv(dotenv_path=pkg_env)

# LLM Configuration
API_KEY = os.getenv("LLM_API_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Memory Configuration
MEMORY_DB_PATH = os.getenv("MEMORY_DB_PATH", "memory.db")
SHORT_TERM_LIMIT = int(os.getenv("SHORT_TERM_LIMIT", "20"))

# File Tool Security
SAFE_FILE_BASE_PATH = os.getenv("SAFE_FILE_BASE_PATH", "./data")

# Web Server
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "8080"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

# Agent Behavior
MAX_REACT_ITERATIONS = int(os.getenv("MAX_REACT_ITERATIONS", "10"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))

# Agent Mode: "function_calling" (new) or "react" (legacy)
AGENT_MODE = os.getenv("AGENT_MODE", "function_calling")
