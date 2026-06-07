"""Unit tests for memory manager."""

import gc
import os
import sys
import tempfile
import unittest
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_agent_framework.memory.memory_manager import MemoryManager


class TestMemoryManager(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.memory = MemoryManager(db_path=self.db_path)
        self.session_id = "test-session-001"

    def tearDown(self):
        self.memory = None
        gc.collect()
        try:
            os.remove(self.db_path)
        except PermissionError:
            pass

    def test_add_and_get_short_term(self):
        self.memory.add_short_term({
            "role": "user",
            "content": "Hello",
            "timestamp": time.time(),
            "metadata": {"session_id": self.session_id},
        })
        entries = self.memory.get_short_term(self.session_id)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["content"], "Hello")

    def test_clear_short_term(self):
        self.memory.add_short_term({
            "role": "user",
            "content": "Hello",
            "timestamp": time.time(),
            "metadata": {"session_id": self.session_id},
        })
        self.memory.clear_short_term(self.session_id)
        entries = self.memory.get_short_term(self.session_id)
        self.assertEqual(len(entries), 0)

    def test_save_to_long_term(self):
        self.memory.add_short_term({
            "role": "user",
            "content": "Persist me",
            "timestamp": time.time(),
            "metadata": {"session_id": self.session_id},
        })
        self.memory.save_to_long_term(self.session_id)
        long = self.memory.query_long_term(self.session_id)
        self.assertEqual(len(long), 1)
        self.assertEqual(long[0]["content"], "Persist me")

    def test_query_long_term_with_keyword(self):
        self.memory.add_short_term({
            "role": "user",
            "content": "apple pie recipe",
            "timestamp": time.time(),
            "metadata": {"session_id": self.session_id},
        })
        self.memory.save_to_long_term(self.session_id)
        results = self.memory.query_long_term(self.session_id, keyword="apple")
        self.assertEqual(len(results), 1)

    def test_session_isolation(self):
        sid_a = "session-a"
        sid_b = "session-b"
        self.memory.add_short_term({
            "role": "user",
            "content": "A message",
            "timestamp": time.time(),
            "metadata": {"session_id": sid_a},
        })
        self.memory.add_short_term({
            "role": "user",
            "content": "B message",
            "timestamp": time.time(),
            "metadata": {"session_id": sid_b},
        })
        a_entries = self.memory.get_short_term(sid_a)
        b_entries = self.memory.get_short_term(sid_b)
        self.assertEqual(a_entries[0]["content"], "A message")
        self.assertEqual(b_entries[0]["content"], "B message")


if __name__ == "__main__":
    unittest.main()
