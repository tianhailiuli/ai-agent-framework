"""ReAct reasoning and acting loop."""

import json
import re
from typing import Callable

from ai_agent_framework import config


class ReActLoop:
    """Core think-act-observe loop."""

    def __init__(self, llm, tools, prompt_builder, memory=None, stream_manager=None):
        self.llm = llm
        self.tools = tools
        self.prompt_builder = prompt_builder
        self.memory = memory
        self.stream_manager = stream_manager

    def run(
        self,
        user_input: str,
        session_id: str,
        max_iterations: int = None,
        stream: bool = False,
        on_token: Callable = None,
    ) -> str:
        """
        Execute ReAct loop.

        Returns:
            Final answer string.
        """
        max_iterations = max_iterations or config.MAX_REACT_ITERATIONS
        observations = []

        if self.memory:
            self.memory.add_short_term({
                "role": "user",
                "content": user_input,
                "timestamp": __import__("time").time(),
                "metadata": {"session_id": session_id},
            })

        history = self.memory.get_short_term(session_id) if self.memory else []

        for iteration in range(max_iterations):
            prompt = self.prompt_builder.build_react_prompt(
                user_input, history, self.tools.list_tools(), observations
            )

            messages = [{"role": "user", "content": prompt}]

            if stream and on_token:
                # Stream not fully supported in loop context; collect first
                full_response = ""
                for token in self.llm.chat(messages, stream=True):
                    full_response += token
            else:
                full_response = self.llm.chat(messages, stream=False)

            thought, action, action_input, final_answer = self._parse_response(full_response)

            # Stream updates
            if self.stream_manager:
                if thought:
                    self.stream_manager.push(session_id, {
                        "type": "thought",
                        "content": thought,
                        "timestamp": __import__("datetime").datetime.now().isoformat(),
                    })
                if action:
                    self.stream_manager.push(session_id, {
                        "type": "action",
                        "content": action,
                        "timestamp": __import__("datetime").datetime.now().isoformat(),
                    })
                    self.stream_manager.push(session_id, {
                        "type": "action_input",
                        "content": action_input,
                        "timestamp": __import__("datetime").datetime.now().isoformat(),
                    })

            if final_answer is not None:
                if self.memory:
                    self.memory.add_short_term({
                        "role": "assistant",
                        "content": final_answer,
                        "timestamp": __import__("time").time(),
                        "metadata": {"session_id": session_id},
                    })
                if self.stream_manager:
                    self.stream_manager.push(session_id, {
                        "type": "final",
                        "content": final_answer,
                        "timestamp": __import__("datetime").datetime.now().isoformat(),
                    })
                return final_answer

            if action:
                tool = self.tools.get(action)
                if not tool:
                    obs = f"Error: Tool '{action}' not found."
                else:
                    try:
                        params = json.loads(action_input) if action_input else {}
                    except json.JSONDecodeError:
                        params = {}
                        obs = f"Error: Invalid JSON in Action Input: {action_input}"
                    else:
                        result = tool.run(params)
                        obs = json.dumps(result, ensure_ascii=False)

                observations.append(obs)

                if self.stream_manager:
                    self.stream_manager.push(session_id, {
                        "type": "observation",
                        "content": obs,
                        "timestamp": __import__("datetime").datetime.now().isoformat(),
                    })
            else:
                # No action and no final answer: treat response as final
                if self.memory:
                    self.memory.add_short_term({
                        "role": "assistant",
                        "content": full_response,
                        "timestamp": __import__("time").time(),
                        "metadata": {"session_id": session_id},
                    })
                if self.stream_manager:
                    self.stream_manager.push(session_id, {
                        "type": "final",
                        "content": full_response,
                        "timestamp": __import__("datetime").datetime.now().isoformat(),
                    })
                return full_response

        # Max iterations reached
        fallback = "I have reached the maximum number of thinking steps. Please try rephrasing your request."
        if self.memory:
            self.memory.add_short_term({
                "role": "assistant",
                "content": fallback,
                "timestamp": __import__("time").time(),
                "metadata": {"session_id": session_id},
            })
        if self.stream_manager:
            self.stream_manager.push(session_id, {
                "type": "final",
                "content": fallback,
                "timestamp": __import__("datetime").datetime.now().isoformat(),
            })
        return fallback

    def _parse_response(self, text: str):
        """
        Parse ReAct response.

        Returns:
            (thought, action, action_input, final_answer)
        """
        thought = None
        action = None
        action_input = None
        final_answer = None

        # Extract Thought
        thought_match = re.search(r'Thought:\s*(.*?)(?=\nAction:|\nFinal Answer:|$)', text, re.DOTALL | re.IGNORECASE)
        if thought_match:
            thought = thought_match.group(1).strip()

        # Extract Final Answer
        final_match = re.search(r'Final Answer:\s*(.*)', text, re.DOTALL | re.IGNORECASE)
        if final_match:
            final_answer = final_match.group(1).strip()

        # Extract Action
        action_match = re.search(r'Action:\s*(\S+)', text, re.IGNORECASE)
        if action_match:
            action = action_match.group(1).strip()

        # Extract Action Input
        action_input_match = re.search(r'Action Input:\s*(\{.*?\}|\S.*)', text, re.DOTALL | re.IGNORECASE)
        if action_input_match:
            action_input = action_input_match.group(1).strip()

        return thought, action, action_input, final_answer
