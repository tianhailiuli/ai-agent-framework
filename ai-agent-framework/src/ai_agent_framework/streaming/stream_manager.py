"""Stream manager for SSE-based real-time output."""

import json
import queue
import threading
import time

from flask import Response


class StreamManager:
    """Manages SSE streams for sessions."""

    def __init__(self):
        self._active_streams: dict[str, queue.Queue] = {}
        self._lock = threading.Lock()

    def create_stream(self, session_id: str) -> queue.Queue:
        """Create a message queue for a session."""
        with self._lock:
            q = queue.Queue()
            self._active_streams[session_id] = q
            return q

    def push(self, session_id: str, data: dict):
        """Push data to a session's stream queue."""
        with self._lock:
            q = self._active_streams.get(session_id)
        if q:
            q.put(data)

    def generate_sse(self, session_id: str) -> Response:
        """Generate Flask SSE response."""
        with self._lock:
            q = self._active_streams.get(session_id)
            if q is None:
                q = self.create_stream(session_id)

        def event_stream():
            try:
                while True:
                    try:
                        data = q.get(timeout=120)
                    except queue.Empty:
                        yield f"data: {json.dumps({'type': 'error', 'content': 'Stream timeout'})}\n\n"
                        break

                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    if data.get("type") in ("done", "error"):
                        break
            finally:
                with self._lock:
                    self._active_streams.pop(session_id, None)

        return Response(
            event_stream(),
            mimetype="text/event-stream",
        )
