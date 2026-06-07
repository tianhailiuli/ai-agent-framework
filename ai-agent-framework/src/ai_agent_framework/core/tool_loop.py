"""Tool Calling loop with real-time streaming."""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from ai_agent_framework import config


class ToolLoop:
    """Core think-act-observe loop using Function Calling."""

    MAX_CHARS_PER_SECOND = 20
    BUILTIN_CALC_RE = re.compile(r'^(?:计算|算一下|求)\s*[:：]?\s*([0-9+\-*/().\s^%]+)$')
    # Simple in-memory cache for tool calls: {(tool_name, args_hash): (result, timestamp)}
    TOOL_CACHE_TTL = 60  # seconds

    def __init__(self, llm, tools, prompt_builder, memory=None, stream_manager=None):
        self.llm = llm
        self.tools = tools
        self.prompt_builder = prompt_builder
        self.memory = memory
        self.stream_manager = stream_manager
        self._tool_cache: dict = {}

    # ---------- Builtin tool detection ----------

    def _try_builtin(self, user_input: str) -> dict | None:
        """
        Try to match user input against builtin tools (no LLM function calling needed).
        Returns {"tool": name, "result": {...}, "expression": ...} or None.
        """
        # Calculator builtin patterns - strict matching to avoid false positives
        calc_patterns = [
            # Chinese explicit calculator requests
            r'(?:计算|算一下|求|算)\s*[:：]\s*(.+)',
            r'^(?:计算|算一下|求|算)\s*(.+)$',
            # Chinese result inquiries (must end with number-like expression)
            r'([\d\(\)\+\-\*\/\^\%\.\s]+?)\s*等于\s*多\s*少',
            r'([\d\(\)\+\-\*\/\^\%\.\s]+?)\s*是\s*多\s*少',
        ]
        for pattern in calc_patterns:
            match = re.search(pattern, user_input)
            if match:
                expr = match.group(1).strip()
                # Remove trailing punctuation and whitespace
                expr = re.sub(r'[。！？?.!\s]+$', '', expr)
                # Strict validation: expression must be mostly math characters
                # Allow only digits, operators, parentheses, dots, and small amounts of whitespace
                cleaned = expr.replace(' ', '').replace('**', '')
                if not cleaned or not re.match(r'^[\d\+\-\*\/\(\)\.\%\^]+$', cleaned):
                    continue
                # Must contain at least one operator or be a complex expression
                if not re.search(r'[\+\-\*\/\%\^\(\)]', cleaned):
                    # Single number, not a calculation
                    continue
                tool = self.tools.get("calculator")
                if tool:
                    result = tool.run({"expression": expr})
                    return {
                        "tool": "calculator",
                        "result": result,
                        "expression": expr,
                    }
        return None

    # ---------- Main run loop ----------

    def run(
        self,
        user_input: str,
        session_id: str,
        max_iterations: int = None,
    ) -> str:
        """
        Execute tool calling loop.

        Three paths:
        1. Builtin tool path: detect simple requests (calculator), execute directly,
           then stream final answer from LLM (no tool UI shown).
        2. Direct answer path: LLM answers without tools, stream as final.
        3. Function calling path: LLM calls tools, execute them, then stream final.
        """
        max_iterations = max_iterations or config.MAX_REACT_ITERATIONS

        # Try builtin tools first (e.g., calculator)
        builtin = self._try_builtin(user_input)
        if builtin:
            return self._run_builtin_path(user_input, builtin, session_id)

        # Add user input to memory only if not already present at the end
        if self.memory:
            history_check = self.memory.get_short_term(session_id)
            if not history_check or history_check[-1].get("content") != user_input or history_check[-1].get("role") != "user":
                self.memory.add_short_term({
                    "role": "user",
                    "content": user_input,
                    "timestamp": __import__("time").time(),
                    "metadata": {"session_id": session_id},
                })

        history = self.memory.get_short_term(session_id) if self.memory else []
        tool_results = []
        final_answer = ""

        for iteration in range(max_iterations):
            # Reset tool_results for each iteration
            tool_results = []

            # Force final answer on last iteration (no tools provided)
            force_final = (iteration >= max_iterations - 1)

            # Fetch related long-term memories for context enrichment
            related_memories = []
            if self.memory and user_input:
                related_memories = self.memory.get_related_memories(user_input, top_k=3)

            # Build messages for this turn
            messages = self.prompt_builder.build_fc_messages(
                user_input if iteration == 0 else "",
                history,
                self.tools.list_tools(),
                tool_results if tool_results else None,
                related_memories=related_memories,
                iteration=iteration,
                max_iterations=max_iterations,
                force_final=force_final,
            )

            # On follow-up turns, add user message if not already present
            if iteration > 0 and messages[-1]["role"] != "user":
                messages.append({"role": "user", "content": "请继续"})

            schemas = self.tools.get_schemas() if not force_final else None

            # Call LLM with streaming
            tool_calls = None
            thinking_buffer = ""
            reasoning_buffer = ""
            # For iteration 0, buffer content/reasoning instead of streaming immediately.
            # We'll flush as 'final' if no tool_calls, or as 'thinking' if tool_calls.
            first_turn_buffer = [] if iteration == 0 else None
            first_turn_reasoning_buffer = [] if iteration == 0 else None

            # Rate-limiting state (reset per run)
            last_push_time = 0
            min_interval = 1.0 / self.MAX_CHARS_PER_SECOND

            def _push_final(text_piece: str):
                """Push final text with rate limiting (max 7 chars/sec)."""
                nonlocal last_push_time
                if not self.stream_manager:
                    return
                now = time.time()
                needed_delay = max(0, len(text_piece) * min_interval - (now - last_push_time))
                if needed_delay > 0:
                    time.sleep(needed_delay)
                self.stream_manager.push(session_id, {
                    "type": "final",
                    "content": text_piece,
                    "timestamp": datetime.now().isoformat(),
                })
                last_push_time = time.time()

            def _push_thinking(text_piece: str):
                """Push thinking text (no rate limit, real-time)."""
                if not self.stream_manager:
                    return
                self.stream_manager.push(session_id, {
                    "type": "thinking",
                    "content": text_piece,
                    "timestamp": datetime.now().isoformat(),
                })

            for event in self.llm.chat(messages, tools=schemas, stream=True):
                if event["type"] == "reasoning":
                    text = event["text"]
                    reasoning_buffer += text
                    if iteration == 0:
                        # Real-time thinking stream so user isn't staring at a blank screen
                        _push_thinking(text)
                    # Buffer for memory / downstream use
                    if iteration == 0 and first_turn_reasoning_buffer is not None:
                        first_turn_reasoning_buffer.append(text)

                elif event["type"] == "content":
                    text = event["text"]
                    thinking_buffer += text
                    if iteration == 0 and first_turn_buffer is not None:
                        first_turn_buffer.append(text)
                    else:
                        # Iteration > 0: stream as 'final' with rate limit
                        _push_final(text)

                elif event["type"] == "tool_calls":
                    tool_calls = event["calls"]
                    reasoning_buffer = event.get("reasoning_content", reasoning_buffer)

                elif event["type"] == "done":
                    reasoning_buffer = event.get("reasoning_content", reasoning_buffer)
                    break

            # Case 1: No tool calls → direct answer
            if not tool_calls:
                # Kimi often puts the full answer in reasoning_content and leaves content empty/short
                # Use reasoning_buffer if thinking_buffer is very short compared to reasoning_buffer
                if thinking_buffer and len(thinking_buffer) >= max(10, len(reasoning_buffer) * 0.3):
                    final_answer = thinking_buffer
                else:
                    final_answer = reasoning_buffer or thinking_buffer
                if iteration == 0 and self.stream_manager:
                    # Flush any remaining content as final with rate limit
                    # (reasoning was already streamed as thinking in real-time)
                    for text in (first_turn_buffer or []):
                        _push_final(text)
                elif self.stream_manager and thinking_buffer and iteration > 0:
                    # Already streamed as final during the loop, nothing to do
                    pass
                # Save assistant message to memory
                if self.memory:
                    self.memory.add_short_term({
                        "role": "assistant",
                        "content": final_answer,
                        "timestamp": __import__("time").time(),
                        "metadata": {"session_id": session_id},
                    })
                break

            # Case 2: Has tool calls → execute them
            # Thinking was already streamed in real-time above.

            # Save assistant message with tool_calls to memory
            if self.memory:
                full_tool_calls = []
                for i, call in enumerate(tool_calls):
                    full_tool_calls.append({
                        "index": i,
                        "id": call.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": call.get("name", ""),
                            "arguments": call.get("arguments", ""),
                        },
                    })
                self.memory.add_short_term({
                    "role": "assistant",
                    "content": thinking_buffer,
                    "timestamp": __import__("time").time(),
                    "metadata": {
                        "session_id": session_id,
                        "tool_calls": full_tool_calls,
                        "reasoning_content": reasoning_buffer,
                    },
                })

            # Execute tool calls concurrently for speed
            def _execute_single(call: dict) -> dict:
                """Execute a single tool call, with caching support."""
                tool_name = call.get("name", "")
                tool_args_raw = call.get("arguments", "")

                # Check cache first
                cache_key = (tool_name, tool_args_raw)
                cached = self._tool_cache.get(cache_key)
                if cached:
                    result, cached_time = cached
                    if time.time() - cached_time < self.TOOL_CACHE_TTL:
                        return {
                            "call": call,
                            "result": result,
                            "result_text": json.dumps(result, ensure_ascii=False),
                            "cached": True,
                        }

                tool = self.tools.get(tool_name)
                if not tool:
                    result = {
                        "status": "error",
                        "result": None,
                        "message": f"Tool '{tool_name}' not found.",
                    }
                else:
                    try:
                        params = json.loads(tool_args_raw) if tool_args_raw else {}
                    except json.JSONDecodeError:
                        params = {}
                        result = {
                            "status": "error",
                            "result": None,
                            "message": f"Invalid JSON arguments: {tool_args_raw}",
                        }
                    else:
                        result = tool.run(params)

                # Store in cache
                self._tool_cache[cache_key] = (result, time.time())
                return {
                    "call": call,
                    "result": result,
                    "result_text": json.dumps(result, ensure_ascii=False),
                    "cached": False,
                }

            # Run all tool calls in parallel
            tool_outputs = []
            if len(tool_calls) == 1:
                tool_outputs = [_execute_single(tool_calls[0])]
            else:
                with ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as executor:
                    futures = {executor.submit(_execute_single, call): call for call in tool_calls}
                    for future in as_completed(futures):
                        try:
                            tool_outputs.append(future.result(timeout=30))
                        except Exception as e:
                            call = futures[future]
                            tool_outputs.append({
                                "call": call,
                                "result": {"status": "error", "result": None, "message": str(e)},
                                "result_text": json.dumps({"status": "error", "result": None, "message": str(e)}, ensure_ascii=False),
                                "cached": False,
                            })

            # Stream UI events and collect results
            for out in tool_outputs:
                call = out["call"]
                tool_name = call.get("name", "")
                tool_args_raw = call.get("arguments", "")
                result = out["result"]
                result_text = out["result_text"]
                is_cached = out.get("cached", False)

                tool = self.tools.get(tool_name)
                is_hidden = tool.hidden if tool else False

                # Push tool UI events only for visible tools
                if not is_hidden and self.stream_manager:
                    self.stream_manager.push(session_id, {
                        "type": "tool_start",
                        "name": tool_name,
                        "timestamp": datetime.now().isoformat(),
                    })
                    self.stream_manager.push(session_id, {
                        "type": "tool_args",
                        "content": tool_args_raw + (" [cached]" if is_cached else ""),
                        "timestamp": datetime.now().isoformat(),
                    })
                    self.stream_manager.push(session_id, {
                        "type": "tool_result",
                        "content": result_text,
                        "timestamp": datetime.now().isoformat(),
                    })

                # Store for next LLM call
                tool_call_id = call.get("id", "")
                if not tool_call_id:
                    tool_call_id = f"call_{tool_name}_{iteration}"
                tool_results.append({
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "content": result_text,
                })

                if self.memory:
                    self.memory.add_short_term({
                        "role": "tool",
                        "content": f"Tool {tool_name} result: {result_text}",
                        "timestamp": time.time(),
                        "metadata": {
                            "session_id": session_id,
                            "tool_name": tool_name,
                            "tool_call_id": tool_call_id,
                        },
                    })

            # Refresh history after adding assistant + tool messages
            history = self.memory.get_short_term(session_id) if self.memory else []

        # Save final answer to memory (if not already saved in Case 1)
        if final_answer and self.memory:
            history = self.memory.get_short_term(session_id)
            if not history or history[-1].get("role") != "assistant" or history[-1].get("content") != final_answer:
                self.memory.add_short_term({
                    "role": "assistant",
                    "content": final_answer,
                    "timestamp": __import__("time").time(),
                    "metadata": {"session_id": session_id},
                })

        if self.stream_manager and not final_answer:
            self.stream_manager.push(session_id, {
                "type": "error",
                "content": "未能生成有效回复",
                "timestamp": datetime.now().isoformat(),
            })

        if self.stream_manager:
            self.stream_manager.push(session_id, {
                "type": "done",
                "timestamp": datetime.now().isoformat(),
            })

        return final_answer

    # ---------- Builtin path handler ----------

    def _run_builtin_path(self, user_input: str, builtin: dict, session_id: str) -> str:
        """Handle builtin tool execution: no tool UI, stream final answer directly."""
        # Save user message to memory
        if self.memory:
            history_check = self.memory.get_short_term(session_id)
            if not history_check or history_check[-1].get("content") != user_input or history_check[-1].get("role") != "user":
                self.memory.add_short_term({
                    "role": "user",
                    "content": user_input,
                    "timestamp": __import__("time").time(),
                    "metadata": {"session_id": session_id},
                })

        # Build messages with builtin result injected
        messages = self.prompt_builder.build_builtin_messages(
            user_input, builtin, self.tools.list_tools()
        )

        # Call LLM for final answer (no tools, just stream as 'final')
        final_answer = ""
        last_push_time = 0
        min_interval = 1.0 / self.MAX_CHARS_PER_SECOND

        for event in self.llm.chat(messages, stream=True):
            if event["type"] == "content":
                text = event["text"]
                final_answer += text
                if self.stream_manager:
                    now = time.time()
                    needed_delay = max(0, len(text) * min_interval - (now - last_push_time))
                    if needed_delay > 0:
                        time.sleep(needed_delay)
                    self.stream_manager.push(session_id, {
                        "type": "final",
                        "content": text,
                        "timestamp": datetime.now().isoformat(),
                    })
                    last_push_time = time.time()
            elif event["type"] == "done":
                break

        # Save to memory
        if self.memory:
            self.memory.add_short_term({
                "role": "assistant",
                "content": final_answer,
                "timestamp": __import__("time").time(),
                "metadata": {"session_id": session_id},
            })

        if self.stream_manager:
            self.stream_manager.push(session_id, {
                "type": "done",
                "timestamp": datetime.now().isoformat(),
            })

        return final_answer
