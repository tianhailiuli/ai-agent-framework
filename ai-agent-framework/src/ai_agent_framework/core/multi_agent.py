"""Multi-agent collaboration: Planner + Executor."""

import json
import uuid
from dataclasses import dataclass, field


@dataclass
class Task:
    task_id: str
    description: str
    required_tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    status: str = "pending"
    result: str = ""


class PlannerAgent:
    """Agent that decomposes user requests into subtasks."""

    def __init__(self, llm_client, prompt_builder):
        self.llm = llm_client
        self.prompt_builder = prompt_builder

    def plan(self, user_input: str, history: list[dict]) -> list[Task]:
        """
        Decompose user request into subtasks.

        Returns:
            List of Task objects.
        """
        prompt = self.prompt_builder.build_planner_prompt(user_input, history)
        messages = [{"role": "user", "content": prompt}]
        raw = self.llm.chat(messages, stream=False)
        response_text = raw["choices"][0]["message"]["content"] if isinstance(raw, dict) else raw

        # Try to extract JSON array
        tasks = []
        try:
            # Find JSON array in response
            start = response_text.find("[")
            end = response_text.rfind("]")
            if start != -1 and end != -1:
                json_str = response_text[start:end + 1]
                data = json.loads(json_str)
            else:
                data = json.loads(response_text)

            if isinstance(data, list):
                for item in data:
                    tasks.append(Task(
                        task_id=str(item.get("task_id", uuid.uuid4())),
                        description=item.get("description", ""),
                        required_tools=item.get("required_tools", []),
                        dependencies=item.get("dependencies", []),
                    ))
            elif isinstance(data, dict):
                # Single task
                tasks.append(Task(
                    task_id=str(data.get("task_id", uuid.uuid4())),
                    description=data.get("description", ""),
                    required_tools=data.get("required_tools", []),
                    dependencies=data.get("dependencies", []),
                ))
        except json.JSONDecodeError:
            # Fallback: treat entire response as one task
            tasks.append(Task(
                task_id="1",
                description=user_input,
                required_tools=[],
                dependencies=[],
            ))

        return tasks


class ExecutorAgent:
    """Agent that executes subtasks using ReAct loop."""

    def __init__(self, llm_client, tool_registry, prompt_builder, react_loop):
        self.llm = llm_client
        self.tools = tool_registry
        self.prompt_builder = prompt_builder
        self.react_loop = react_loop

    def execute(self, task: Task, history: list[dict]) -> str:
        """Execute a single subtask using ReAct loop."""
        task.status = "in_progress"
        prompt = self.prompt_builder.build_executor_prompt(
            {"description": task.description},
            self.tools.list_tools(),
            history,
        )
        messages = [{"role": "user", "content": prompt}]
        raw = self.llm.chat(messages, stream=False)
        response_text = raw["choices"][0]["message"]["content"] if isinstance(raw, dict) else raw

        # Parse and execute tool calls manually for subtask
        thought, action, action_input, final_answer = self._parse_response(response_text)

        if final_answer is not None:
            task.status = "completed"
            task.result = final_answer
            return final_answer

        if action:
            tool = self.tools.get(action)
            if tool:
                try:
                    params = json.loads(action_input) if action_input else {}
                except json.JSONDecodeError:
                    params = {}
                result = tool.run(params)
                obs = json.dumps(result, ensure_ascii=False)
                # Follow-up with observation
                follow_prompt = (
                    f"{prompt}\n\n"
                    f"Thought: {thought}\n"
                    f"Action: {action}\n"
                    f"Action Input: {action_input}\n"
                    f"Observation: {obs}\n\n"
                    "Continue with Thought and Final Answer."
                )
                follow_messages = [{"role": "user", "content": follow_prompt}]
                follow_raw = self.llm.chat(follow_messages, stream=False)
                follow_text = follow_raw["choices"][0]["message"]["content"] if isinstance(follow_raw, dict) else follow_raw
                _, _, _, final_answer2 = self._parse_response(follow_text)
                if final_answer2 is not None:
                    task.status = "completed"
                    task.result = final_answer2
                    return final_answer2
                task.status = "completed"
                task.result = follow_text
                return follow_text
            else:
                task.status = "failed"
                task.result = f"Tool '{action}' not found."
                return task.result

        task.status = "completed"
        task.result = response
        return response

    def execute_plan(
        self, tasks: list[Task], memory, stream_manager, session_id: str
    ) -> str:
        """
        Execute all tasks respecting dependencies.

        Returns:
            Final aggregated result.
        """
        completed_ids = set()
        pending = {t.task_id: t for t in tasks}

        while pending:
            # Find ready tasks (all dependencies completed)
            ready = [
                t for t in pending.values()
                if all(dep in completed_ids for dep in t.dependencies)
            ]
            if not ready:
                # Circular dependency or missing dependency
                break

            for task in ready:
                if stream_manager:
                    stream_manager.push(session_id, {
                        "type": "tool_start",
                        "name": "subtask",
                        "timestamp": __import__("datetime").datetime.now().isoformat(),
                    })
                    stream_manager.push(session_id, {
                        "type": "tool_args",
                        "content": task.description,
                        "timestamp": __import__("datetime").datetime.now().isoformat(),
                    })

                history = memory.get_short_term(session_id) if memory else []
                result = self.execute(task, history)

                if memory:
                    memory.add_short_term({
                        "role": "tool",
                        "content": f"Task {task.task_id} result: {result}",
                        "timestamp": __import__("time").time(),
                        "metadata": {"session_id": session_id, "task_id": task.task_id},
                    })

                if stream_manager:
                    stream_manager.push(session_id, {
                        "type": "tool_result",
                        "content": result,
                        "timestamp": __import__("datetime").datetime.now().isoformat(),
                    })

                completed_ids.add(task.task_id)
                del pending[task.task_id]

        # Aggregate results
        results_text = "\n".join([f"- {t.description}: {t.result}" for t in tasks])

        # Use LLM to synthesize final answer
        synthesis_prompt = (
            "You are a helpful assistant. Based on the completed subtasks below, "
            "provide a concise and helpful final answer to the user.\n\n"
            f"Subtask Results:\n{results_text}\n\n"
            "Final Answer:"
        )
        messages = [{"role": "user", "content": synthesis_prompt}]
        raw = self.llm.chat(messages, stream=False)
        result = raw["choices"][0]["message"]["content"] if isinstance(raw, dict) else raw

        if stream_manager:
            stream_manager.push(session_id, {
                "type": "done",
                "timestamp": __import__("datetime").datetime.now().isoformat(),
            })

        return result

    def _parse_response(self, text: str):
        """Parse ReAct response."""
        import re
        thought = None
        action = None
        action_input = None
        final_answer = None

        thought_match = re.search(
            r'Thought:\s*(.*?)(?=\nAction:|\nFinal Answer:|$)', text, re.DOTALL | re.IGNORECASE
        )
        if thought_match:
            thought = thought_match.group(1).strip()

        final_match = re.search(r'Final Answer:\s*(.*)', text, re.DOTALL | re.IGNORECASE)
        if final_match:
            final_answer = final_match.group(1).strip()

        action_match = re.search(r'Action:\s*(\S+)', text, re.IGNORECASE)
        if action_match:
            action = action_match.group(1).strip()

        action_input_match = re.search(
            r'Action Input:\s*(\{.*?\}|\S.*)', text, re.DOTALL | re.IGNORECASE
        )
        if action_input_match:
            action_input = action_input_match.group(1).strip()

        return thought, action, action_input, final_answer
