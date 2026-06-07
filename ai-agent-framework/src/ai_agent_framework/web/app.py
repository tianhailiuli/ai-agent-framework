"""Flask web application for AI Agent."""

import uuid

from pathlib import Path

from flask import Flask, request, jsonify, Response, render_template

from ai_agent_framework.core.agent_core import AgentCore
from ai_agent_framework.memory.memory_manager import MemoryManager

_pkg_dir = Path(__file__).parent
app = Flask(
    __name__,
    template_folder=str(_pkg_dir / "templates"),
    static_folder=str(_pkg_dir / "static"),
)
agent_core = AgentCore()
memory_manager = agent_core.memory


@app.route("/")
def index():
    """Render main page."""
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    """Non-streaming chat endpoint."""
    data = request.get_json(force=True)
    message = data.get("message", "")
    session_id = data.get("session_id")

    if not session_id:
        session_id = memory_manager.create_session()

    try:
        response = agent_core.process(message, session_id=session_id, stream=False)
        return jsonify({"response": response, "session_id": session_id})
    except Exception as e:
        return jsonify({"error": str(e), "session_id": session_id}), 500


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """Streaming chat endpoint (SSE)."""
    data = request.get_json(force=True)
    message = data.get("message", "")
    session_id = data.get("session_id")

    if not session_id:
        session_id = memory_manager.create_session()

    return agent_core.process(message, session_id=session_id, stream=True)


@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    """List all session IDs."""
    sessions = memory_manager.list_sessions()
    # Also include active in-memory sessions
    active = list(memory_manager.short_term.keys())
    all_sessions = sorted(set(sessions + active))
    return jsonify({"sessions": all_sessions})


@app.route("/api/sessions/<session_id>", methods=["GET"])
def get_session_history(session_id):
    """Get session history."""
    short = memory_manager.get_short_term(session_id, limit=50)
    long = memory_manager.query_long_term(session_id, limit=50)
    # Combine and sort by timestamp
    combined = short + long
    combined.sort(key=lambda x: x.get("timestamp", 0))
    return jsonify({"session_id": session_id, "history": combined})


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def clear_session(session_id):
    """Clear short-term memory for a session."""
    memory_manager.clear_short_term(session_id)
    return jsonify({"message": f"Session {session_id} short-term memory cleared."})
