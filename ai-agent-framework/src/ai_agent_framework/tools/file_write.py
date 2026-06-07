"""Safe file write tool."""

import os

from .base import Tool


class FileWriteTool(Tool):
    """Tool for writing files safely within a restricted directory."""

    def __init__(self, base_path: str = "./data"):
        self.base_path = os.path.abspath(base_path)
        os.makedirs(self.base_path, exist_ok=True)

    @property
    def name(self) -> str:
        return "file_write"

    @property
    def description(self) -> str:
        return (
            "Write content to a local file. "
            'Input: {"filepath": "relative/path/to/file.txt", "content": "text to write"}. '
            "Creates directories if needed. Only within allowed data directory."
        )

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Write text content to a local file within the safe data directory. Creates parent directories automatically.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "Relative path to the file, e.g. 'output.txt' or 'data/result.json'"
                        },
                        "content": {
                            "type": "string",
                            "description": "Text content to write into the file"
                        }
                    },
                    "required": ["filepath", "content"]
                }
            }
        }

    def run(self, params: dict) -> dict:
        filepath = params.get("filepath", "")
        content = params.get("content", "")
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
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(content)
            return {
                "status": "success",
                "result": filepath,
                "message": f"Successfully wrote to file '{filepath}'.",
            }
        except Exception as e:
            return {
                "status": "error",
                "result": None,
                "message": f"Write error: {str(e)}",
            }

    def _is_safe_path(self, filepath: str) -> bool:
        """Prevent directory traversal attacks."""
        target_path = os.path.abspath(os.path.join(self.base_path, filepath))
        return target_path.startswith(self.base_path)
