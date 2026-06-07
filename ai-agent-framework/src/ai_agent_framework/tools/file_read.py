"""Safe file read tool."""

import os

from .base import Tool


class FileReadTool(Tool):
    """Tool for reading files safely within a restricted directory."""

    def __init__(self, base_path: str = "./data"):
        self.base_path = os.path.abspath(base_path)
        os.makedirs(self.base_path, exist_ok=True)

    @property
    def name(self) -> str:
        return "file_read"

    @property
    def description(self) -> str:
        return (
            "Read a local file. "
            'Input: {"filepath": "relative/path/to/file.txt"}. '
            "Only files within the allowed data directory can be accessed."
        )

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Read content from a local file within the safe data directory. Cannot access paths outside the allowed directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "Relative path to the file, e.g. 'notes.txt' or 'docs/report.md'"
                        }
                    },
                    "required": ["filepath"]
                }
            }
        }

    def run(self, params: dict) -> dict:
        filepath = params.get("filepath", "")
        if not filepath:
            return {
                "status": "error",
                "result": None,
                "message": "No filepath provided.",
            }

        if not self._is_safe_path(filepath):
            return {
                "status": "error",
                "result": None,
                "message": "Access denied: path is outside allowed directory.",
            }

        target_path = os.path.abspath(os.path.join(self.base_path, filepath))
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
            return {
                "status": "success",
                "result": content,
                "message": f"Successfully read file '{filepath}'.",
            }
        except FileNotFoundError:
            return {
                "status": "error",
                "result": None,
                "message": f"File not found: '{filepath}'.",
            }
        except Exception as e:
            return {
                "status": "error",
                "result": None,
                "message": f"Read error: {str(e)}",
            }

    def _is_safe_path(self, filepath: str) -> bool:
        """Prevent directory traversal attacks."""
        target_path = os.path.abspath(os.path.join(self.base_path, filepath))
        return target_path.startswith(self.base_path)
