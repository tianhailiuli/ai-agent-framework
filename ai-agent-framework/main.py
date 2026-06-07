"""Entry point to start the AI Agent Framework web server."""

import sys
import os

# Add src/ to path for development mode (no pip install needed)
_project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_project_root, "src"))

from ai_agent_framework.main import main

if __name__ == "__main__":
    main()
