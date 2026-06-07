"""Prompt engineering module for constructing LLM prompts."""

from ai_agent_framework.tools import Tool


class PromptBuilder:
    """Builds prompts for different agent modes."""

    # ==================== Legacy ReAct (保留兼容) ====================

    def build_system_prompt(self, tools: list[Tool]) -> str:
        """Build system prompt with tool descriptions."""
        tool_desc = "\n".join([f"- {t.name}: {t.description}" for t in tools])
        return (
            "You are an autonomous decision-making AI Agent. Your task is to help users complete various requests.\n\n"
            f"Available tools:\n{tool_desc}\n\n"
            "You MUST strictly follow the ReAct format below:\n"
            "Thought: [your reasoning process]\n"
            "Action: [tool name]\n"
            "Action Input: [JSON string of tool parameters]\n\n"
            "When the task is complete, output:\n"
            "Thought: [summary]\n"
            "Final Answer: [final response to the user]\n\n"
            "Important rules:\n"
            "1. Always output 'Thought' before Action or Final Answer.\n"
            "2. Action Input must be a valid JSON object.\n"
            "3. If no tool is needed, directly output Final Answer.\n"
            "4. Do not output anything outside the specified format.\n\n"
            "Examples:\n"
            "User: What is 3 squared?\n"
            "Thought: This is a math calculation, I should use the calculator.\n"
            "Action: calculator\n"
            "Action Input: {\"expression\": \"3**2\"}\n"
            "Observation: Result of '3**2' is 9\n"
            "Thought: The calculation is complete.\n"
            "Final Answer: 3 squared is 9.\n\n"
            "User: What is the capital of France?\n"
            "Thought: I know the capital of France is Paris, no tool needed.\n"
            "Final Answer: The capital of France is Paris."
        )

    def build_react_prompt(
        self,
        user_input: str,
        history: list[dict],
        tools: list[Tool],
        observations: list[str] | None = None,
    ) -> str:
        """Build prompt for ReAct loop."""
        lines = []
        lines.append(self.build_system_prompt(tools))
        lines.append("\n--- Conversation History ---")
        for entry in history[-10:]:
            role = entry.get("role", "user")
            content = entry.get("content", "")
            lines.append(f"{role.capitalize()}: {content}")

        if observations:
            lines.append("\n--- Previous Observations ---")
            for obs in observations:
                lines.append(f"Observation: {obs}")

        lines.append(f"\nUser: {user_input}")
        lines.append("Assistant:")
        return "\n".join(lines)

    def build_planner_prompt(self, user_input: str, history: list[dict]) -> str:
        """Build prompt for planner agent to decompose tasks."""
        history_text = "\n".join(
            [f"{e.get('role', 'user').capitalize()}: {e.get('content', '')}" for e in history[-5:]]
        )
        return (
            "You are a Task Planner AI. Your job is to break down a user request into subtasks.\n\n"
            "Output a JSON array of subtasks with this exact format:\n"
            '[{"task_id": "1", "description": "...", "required_tools": ["tool_name"], "dependencies": []}]\n\n'
            "Rules:\n"
            "1. task_id must be a unique string.\n"
            "2. dependencies is a list of task_ids that must complete before this task.\n"
            "3. required_tools is a list of suggested tool names (can be empty).\n"
            "4. Keep descriptions specific and actionable.\n\n"
            f"Conversation History:\n{history_text}\n\n"
            f"User Request: {user_input}\n\n"
            "Output JSON only, no extra text."
        )

    def build_executor_prompt(
        self, subtask: dict, tools: list[Tool], history: list[dict]
    ) -> str:
        """Build prompt for executor agent to run a subtask."""
        tool_desc = "\n".join([f"- {t.name}: {t.description}" for t in tools])
        history_text = "\n".join(
            [f"{e.get('role', 'user').capitalize()}: {e.get('content', '')}" for e in history[-5:]]
        )
        return (
            "You are an Execution AI. Your job is to complete a specific subtask.\n\n"
            f"Available tools:\n{tool_desc}\n\n"
            "You MUST follow the ReAct format:\n"
            "Thought: [your reasoning]\n"
            "Action: [tool name]\n"
            "Action Input: [JSON parameters]\n\n"
            "When done, output:\n"
            "Thought: [summary]\n"
            "Final Answer: [result of this subtask]\n\n"
            f"Conversation History:\n{history_text}\n\n"
            f"Current Subtask: {subtask.get('description', '')}\n\n"
            "Begin:"
        )

    # ==================== Function Calling (新) ====================

    def build_fc_system_prompt(self, tools: list[Tool], iteration: int = 0, max_iterations: int = 10, force_final: bool = False) -> str:
        """Build system prompt for Function Calling mode."""
        tool_names = ", ".join([t.name for t in tools])
        iteration_hint = ""
        if iteration > 0:
            remaining = max_iterations - iteration
            iteration_hint = f"\n[Round {iteration + 1}/{max_iterations}] You have already received tool results. Synthesize them and answer. {remaining} round(s) remaining.\n"
        if force_final:
            iteration_hint += "\n[CRITICAL] This is your LAST chance to respond. Do NOT call any more tools. Answer directly based on the information you already have.\n"
        return (
            "You are an autonomous decision-making AI Agent. Your task is to help users complete various requests.\n\n"
            f"You have access to the following tools: {tool_names}.\n"
            "When a user request requires external information or computation, you should call the appropriate tool.\n"
            "When you can answer directly without tools, just respond naturally.\n\n"
            "Tool selection guide:\n"
            "- calculator: for math calculations only\n"
            "- web_search: for real-time info, news, facts, weather, current events, encyclopedia knowledge, or anything not in your training data\n"
            "- weather_query: for weather information (alternative to web_search for weather)\n"
            "- file_read/file_write: for reading/writing local files\n\n"
            "Important rules:\n"
            "1. Only call tools when necessary.\n"
            "2. For real-time or recent information, use web_search.\n"
            "3. Ensure tool parameters are accurate and complete.\n"
            "4. After receiving tool results, synthesize them into a helpful final answer.\n"
            "5. DO NOT make more than 2-3 tool calls total. If you already have useful information, answer directly.\n"
            "6. Respond in the same language as the user's query."
            f"{iteration_hint}"
        )

    def build_fc_messages(
        self,
        user_input: str,
        history: list[dict],
        tools: list[Tool],
        tool_results: list[dict] | None = None,
        related_memories: list[dict] | None = None,
        iteration: int = 0,
        max_iterations: int = 10,
        force_final: bool = False,
    ) -> list[dict]:
        """
        Build messages list for Function Calling.

        Args:
            user_input: Current user input.
            history: Conversation history.
            tools: Available tools (for system prompt context).
            tool_results: Previous tool execution results to include (role="tool" messages).
            related_memories: Related long-term memories to inject.
            iteration: Current iteration number.
            max_iterations: Max allowed iterations.
            force_final: If True, force LLM to answer without tools.

        Returns:
            List of message dicts ready for LLM API.
        """
        system_content = self.build_fc_system_prompt(tools, iteration, max_iterations, force_final)

        # Inject related long-term memories into system prompt
        if related_memories:
            memory_text = "\n\n[Related memories from past conversations]:\n"
            for i, mem in enumerate(related_memories[:3], 1):
                memory_text += f"{i}. {mem.get('role', 'user')}: {mem.get('content', '')[:200]}\n"
            system_content += memory_text

        messages = [
            {"role": "system", "content": system_content}
        ]

        # Add history (including tool messages with tool_call_id from metadata)
        for entry in history[-10:]:
            role = entry.get("role", "user")
            if role == "tool":
                metadata = entry.get("metadata", {})
                messages.append({
                    "role": "tool",
                    "tool_call_id": metadata.get("tool_call_id", ""),
                    "content": entry.get("content", ""),
                })
            elif role in ("user", "assistant", "system"):
                msg = {
                    "role": role,
                    "content": entry.get("content", ""),
                }
                # Preserve Kimi thinking mode fields for assistant messages
                # These are stored in metadata by ToolLoop
                if role == "assistant":
                    metadata = entry.get("metadata", {})
                    if metadata.get("tool_calls"):
                        msg["tool_calls"] = metadata["tool_calls"]
                    if metadata.get("reasoning_content") is not None:
                        msg["reasoning_content"] = metadata["reasoning_content"]
                messages.append(msg)

        # Add explicit tool results if any (for first-turn or non-memory paths)
        if tool_results:
            for result in tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": result.get("tool_call_id", ""),
                    "content": result.get("content", ""),
                })

        # Add current user input (avoid duplicate if already in history, skip if empty)
        if user_input and (not history or history[-1].get("content") != user_input or history[-1].get("role") != "user"):
            messages.append({"role": "user", "content": user_input})
        return messages

    def build_builtin_messages(
        self,
        user_input: str,
        builtin_result: dict,
        tools: list[Tool],
    ) -> list[dict]:
        """
        Build messages when a builtin tool was executed directly.
        The tool result is injected into the user context so LLM can
        generate a friendly final answer without function calling.
        """
        tool_name = builtin_result.get("tool", "")
        result = builtin_result.get("result", {})
        expression = builtin_result.get("expression", "")

        if result.get("status") == "success":
            result_value = result.get("result")
            context = (
                f"用户请求: {user_input}\n\n"
                f"我已经使用 {tool_name} 完成了计算，"
                f"表达式 '{expression}' 的结果是: {result_value}\n\n"
                f"请直接回答用户，简要说明计算过程和结果。"
            )
        else:
            error_msg = result.get("message", "计算出错")
            context = (
                f"用户请求: {user_input}\n\n"
                f"我尝试使用 {tool_name} 计算，但遇到了问题: {error_msg}\n\n"
                f"请友好地告知用户计算出错，并询问是否需要帮助。"
            )

        return [
            {"role": "system", "content": self.build_fc_system_prompt(tools)},
            {"role": "user", "content": context},
        ]
