"""LLM API client with streaming and retry support."""

import json
import os
import time
from typing import Iterator

import requests

from ai_agent_framework import config


class LLMClient:
    """Client for LLM API calls."""

    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or config.API_KEY
        self.base_url = (base_url or config.BASE_URL).rstrip("/")
        self.model = model or config.MODEL
        self.max_retries = config.MAX_RETRIES
        self.timeout = config.REQUEST_TIMEOUT

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> str | Iterator[dict]:
        """
        Call LLM API.

        Args:
            messages: List of message dicts with "role" and "content".
            tools: OpenAI Function Calling tool schemas.
            stream: Whether to stream the response.

        Returns:
            - stream=False: Full response dict (contains choices, usage, etc.)
            - stream=True: Iterator of structured event dicts:
                {"type": "content", "text": "..."}
                {"type": "tool_calls", "calls": [{"name": "...", "arguments": "..."}]}
                {"type": "done"}
        """
        if stream:
            return self._chat_stream(messages, tools)
        return self._chat_sync(messages, tools)

    def _chat_sync(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Non-streaming chat. Returns full response dict."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if "moonshot" in self.base_url.lower():
            headers["User-Agent"] = "AI-Agent-Framework/1.0"

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        print(f"[LLM] Sync payload: {json.dumps(payload, ensure_ascii=False)[:800]}")

        last_exception = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(
                    url, headers=headers, json=payload, timeout=self.timeout,
                    proxies=self._get_proxies()
                )
                print(f"[LLM] Sync status: {resp.status_code}")
                if resp.status_code != 200:
                    print(f"[LLM] Sync response: {resp.text[:1000]}")
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.ConnectionError as e:
                last_exception = e
                if attempt == self.max_retries - 1:
                    raise self._build_error(e, url)
                time.sleep(2 ** attempt)
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    time.sleep(1 * (attempt + 1))

        raise Exception(f"LLM API failed after {self.max_retries} retries: {last_exception}")

    def _chat_stream(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> Iterator[dict]:
        """
        Streaming chat. Falls back to non-streaming if streaming + tools returns 400.

        Yields structured events:
            {"type": "content", "text": "..."}   - Normal text token
            {"type": "tool_calls", "calls": [...]} - Complete tool calls detected
            {"type": "done"}                       - Stream finished
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if "moonshot" in self.base_url.lower():
            headers["User-Agent"] = "AI-Agent-Framework/1.0"

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        print(f"[LLM] Stream payload: {json.dumps(payload, ensure_ascii=False)[:800]}")

        last_exception = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(
                    url, headers=headers, json=payload, timeout=self.timeout, stream=True,
                    proxies=self._get_proxies()
                )
                print(f"[LLM] Stream status: {resp.status_code}")

                if resp.status_code == 400 and tools:
                    print("[LLM] 400 with tools, falling back to non-streaming...")
                    # Fallback: use non-streaming + tools, then simulate stream
                    resp.close()
                    data = self._chat_sync(messages, tools)
                    choice = data.get("choices", [{}])[0]
                    msg = choice.get("message", {})

                    # Simulate streaming content
                    content = msg.get("content", "")
                    if content:
                        for ch in content:
                            yield {"type": "content", "text": ch}

                    # Simulate tool_calls (include real tool_call_id and reasoning_content)
                    reasoning_content = msg.get("reasoning_content", "")
                    tool_calls = msg.get("tool_calls", [])
                    if tool_calls:
                        calls = []
                        for tc in tool_calls:
                            func = tc.get("function", {})
                            calls.append({
                                "id": tc.get("id", ""),
                                "name": func.get("name", ""),
                                "arguments": func.get("arguments", ""),
                            })
                        yield {"type": "tool_calls", "calls": calls, "reasoning_content": reasoning_content}

                    yield {"type": "done", "reasoning_content": reasoning_content}
                    return

                resp.raise_for_status()

                # Buffers for accumulating across chunks
                tool_calls_buffer = {}  # index -> {"id": str, "name": str, "arguments": str}
                reasoning_content = ""

                for line in resp.iter_lines():
                    if not line:
                        continue
                    line_str = line.decode("utf-8")
                    if not line_str.startswith("data: "):
                        continue

                    data_str = line_str[6:]
                    if data_str == "[DONE]":
                        # Yield accumulated tool calls if any
                        if tool_calls_buffer:
                            calls = []
                            for idx in sorted(tool_calls_buffer.keys()):
                                tc = tool_calls_buffer[idx]
                                calls.append({
                                    "id": tc.get("id", ""),
                                    "name": tc.get("name", ""),
                                    "arguments": tc.get("arguments", ""),
                                })
                            yield {"type": "tool_calls", "calls": calls, "reasoning_content": reasoning_content}
                        yield {"type": "done", "reasoning_content": reasoning_content}
                        return

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {})

                    # Handle tool_calls
                    tc_list = delta.get("tool_calls")
                    if tc_list:
                        for tc in tc_list:
                            idx = tc.get("index", 0)
                            if idx not in tool_calls_buffer:
                                tool_calls_buffer[idx] = {"id": "", "name": "", "arguments": ""}

                            func = tc.get("function", {})
                            if tc.get("id"):
                                tool_calls_buffer[idx]["id"] = tc["id"]
                            if func.get("name"):
                                tool_calls_buffer[idx]["name"] = func["name"]
                            if func.get("arguments"):
                                tool_calls_buffer[idx]["arguments"] += func["arguments"]
                        continue  # Don't yield content when processing tool_calls

                    # Handle reasoning content (Kimi thinking mode)
                    rc = delta.get("reasoning_content", "")
                    if rc:
                        reasoning_content += rc
                        yield {"type": "reasoning", "text": rc}

                    # Handle normal content
                    content = delta.get("content", "")
                    if content:
                        yield {"type": "content", "text": content}

                # Stream ended without [DONE]
                if tool_calls_buffer:
                    calls = []
                    for idx in sorted(tool_calls_buffer.keys()):
                        tc = tool_calls_buffer[idx]
                        calls.append({
                            "id": tc.get("id", ""),
                            "name": tc.get("name", ""),
                            "arguments": tc.get("arguments", ""),
                        })
                    yield {"type": "tool_calls", "calls": calls, "reasoning_content": reasoning_content}
                yield {"type": "done", "reasoning_content": reasoning_content}
                return

            except requests.exceptions.HTTPError as e:
                last_exception = e
                print(f"[LLM] HTTP error: {e}")
                if e.response is not None:
                    print(f"[LLM] Response body: {e.response.text[:1000]}")
                if attempt == self.max_retries - 1:
                    raise self._build_error(e, url)
                time.sleep(2 ** attempt)
            except requests.exceptions.ConnectionError as e:
                last_exception = e
                if attempt == self.max_retries - 1:
                    raise self._build_error(e, url)
                time.sleep(2 ** attempt)
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    time.sleep(1 * (attempt + 1))

        raise Exception(f"LLM API streaming failed after {self.max_retries} retries: {last_exception}")

    def _get_proxies(self):
        """Auto-detect system proxy if set."""
        http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
        https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        if http_proxy or https_proxy:
            return {"http": http_proxy, "https": https_proxy}
        return None

    def _build_error(self, exc, url: str) -> Exception:
        """Build a user-friendly error message."""
        msg = (
            f"无法连接到 LLM 服务 ({url})。\n"
            "可能原因：\n"
            "1. API Key 无效或已过期\n"
            "2. BASE_URL 配置错误（Kimi 应为 https://api.moonshot.cn/v1）\n"
            "3. 网络问题（国内访问 OpenAI 需要代理）\n"
            "4. 模型名称不存在\n"
            "5. 如果开了 Clash/VPN，尝试关闭或设置直连\n"
            f"原始错误: {exc}"
        )
        return Exception(msg)
