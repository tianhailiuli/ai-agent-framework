"""
Unified launcher for AI Agent Framework.

Usage:
    python launch.py              # Start server on default port (auto-cleanup)
    python launch.py --port 8080  # Start on specific port
    python launch.py --foreground # Run in foreground (Ctrl+C to stop cleanly)
    python launch.py --killall    # Kill ALL python processes and exit
"""

import sys
import os

# Add src/ to path for development mode
_project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_project_root, "src"))

from ai_agent_framework.launch import main

if __name__ == "__main__":
    main()
