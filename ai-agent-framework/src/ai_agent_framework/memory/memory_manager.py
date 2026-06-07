"""Memory manager with short-term and long-term storage."""

import json
import sqlite3
import time
import uuid
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional

from ai_agent_framework import config


@dataclass
class MemoryEntry:
    role: str
    content: str
    timestamp: float
    metadata: dict


class MemoryManager:
    """Manages conversation memory."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.MEMORY_DB_PATH
        self.short_term: dict[str, deque] = {}  # session_id -> deque of MemoryEntry
        self.short_term_limit = config.SHORT_TERM_LIMIT
        self._init_db()

    def close(self):
        """Close any open connections (not needed with context managers, but for tests)."""
        pass

    def _ensure_table(self, conn):
        """Ensure the conversations table exists (for in-memory DBs where connections don't persist)."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL,
                metadata TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON conversations(session_id)")

    def _init_db(self):
        """Initialize SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    metadata TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session ON conversations(session_id)
            """)
            conn.commit()

    def create_session(self) -> str:
        """Generate a new session ID."""
        return str(uuid.uuid4())

    def add_short_term(self, entry: dict):
        """Add entry to short-term memory."""
        session_id = entry.get("metadata", {}).get("session_id", "default")
        if session_id not in self.short_term:
            self.short_term[session_id] = deque(maxlen=self.short_term_limit)
        self.short_term[session_id].append(MemoryEntry(
            role=entry.get("role", "user"),
            content=entry.get("content", ""),
            timestamp=entry.get("timestamp", time.time()),
            metadata=entry.get("metadata", {}),
        ))

    def get_short_term(self, session_id: str = "default", limit: int = 10) -> list[dict]:
        """Get recent short-term memory entries."""
        dq = self.short_term.get(session_id, deque())
        entries = list(dq)[-limit:]
        return [
            {
                "role": e.role,
                "content": e.content,
                "timestamp": e.timestamp,
                "metadata": e.metadata,
            }
            for e in entries
        ]

    def clear_short_term(self, session_id: str):
        """Clear short-term memory for a session."""
        if session_id in self.short_term:
            self.short_term[session_id].clear()

    def save_to_long_term(self, session_id: str):
        """Persist short-term memory to SQLite."""
        entries = list(self.short_term.get(session_id, []))
        if not entries:
            return
        with sqlite3.connect(self.db_path) as conn:
            for e in entries:
                conn.execute(
                    "INSERT INTO conversations (session_id, role, content, timestamp, metadata) VALUES (?, ?, ?, ?, ?)",
                    (session_id, e.role, e.content, e.timestamp, json.dumps(e.metadata)),
                )
            conn.commit()
        self.clear_short_term(session_id)

    def persist_without_clear(self, session_id: str):
        """Copy short-term entries to long-term WITHOUT clearing short-term."""
        entries = list(self.short_term.get(session_id, []))
        if not entries:
            return
        with sqlite3.connect(self.db_path) as conn:
            for e in entries:
                conn.execute(
                    "INSERT INTO conversations (session_id, role, content, timestamp, metadata) VALUES (?, ?, ?, ?, ?)",
                    (session_id, e.role, e.content, e.timestamp, json.dumps(e.metadata)),
                )
            conn.commit()

    def query_long_term(
        self, session_id: str, keyword: str = None, limit: int = 50
    ) -> list[dict]:
        """Query historical records from long-term memory."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if keyword:
                cursor = conn.execute(
                    "SELECT * FROM conversations WHERE session_id = ? AND content LIKE ? ORDER BY timestamp DESC LIMIT ?",
                    (session_id, f"%{keyword}%", limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM conversations WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (session_id, limit),
                )
            rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "role": r["role"],
                "content": r["content"],
                "timestamp": r["timestamp"],
                "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
            }
            for r in rows
        ]

    def get_related_memories(self, query: str, top_k: int = 3) -> list[dict]:
        """
        Retrieve related memories based on keyword matching.
        (Simple implementation; advanced: embedding similarity)
        """
        keywords = [w for w in query.split() if len(w) > 1]
        with sqlite3.connect(self.db_path) as conn:
            self._ensure_table(conn)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM conversations ORDER BY timestamp DESC LIMIT 200"
            )
            rows = cursor.fetchall()

        scored = []
        for r in rows:
            content = r["content"]
            score = sum(1 for kw in keywords if kw.lower() in content.lower())
            if score > 0:
                scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "role": r["role"],
                "content": r["content"],
                "timestamp": r["timestamp"],
                "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
            }
            for _, r in top
        ]

    def list_sessions(self) -> list[str]:
        """List all distinct session IDs."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT DISTINCT session_id FROM conversations ORDER BY session_id"
            )
            rows = cursor.fetchall()
        return [r[0] for r in rows]
