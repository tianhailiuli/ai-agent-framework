# AI Agent 框架 V2 — Function Calling 架构改造方案

> 目标：从 ReAct 文本解析模式迁移到 OpenAI 标准 Function Calling 模式，实现真正的逐字流式输出和更低的延迟。
>
> 状态：设计文档，待评审。

---

## 一、现状痛点

| 痛点 | 根因 |
|------|------|
| 思考速度慢 | ReAct 需要 2+ 次完整 LLM 调用（Action → Observation → Final） |
| 无真流式 | 必须等 LLM 输出完整文本后，才能正则解析 Action |
| 解析不可靠 | 正则提取 Thought/Action/Action Input 容易受模型输出格式影响 |
| 工具容错差 | LLM 输出不规范 JSON 时，整个循环失败 |

---

## 二、新架构总览

```
用户输入
  │
  ▼
┌─────────────┐     tools[]      ┌─────────────┐
│ PromptBuilder │ ──────────────→ │  LLMClient  │
│  (Function    │    messages[]   │  (stream=   │
│   Calling)    │                 │   true)     │
└─────────────┘                 └──────┬──────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼
              content token    tool_calls start    tool_args chunk
                    │                  │                  │
                    ▼                  ▼                  ▼
              StreamManager    StreamManager      StreamManager
              push(thinking)   push(tool_start)   push(tool_args)
                    │                  │                  │
                    └──────────────────┘──────────────────┘
                                       │
                                       ▼
                              等完整响应后解析
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                                     │
                    ▼                                     ▼
              无 tool_calls                        有 tool_calls
                    │                                     │
                    ▼                                     ▼
              就是 Final Answer                 解析参数 → 执行工具
              逐字推送给前端                    push(tool_result)
                                              再次调用 LLM
                                              生成 Final Answer
                                              逐字推送给前端
```

---

## 三、核心变更模块

### 3.1 工具层 (`tools/`)

**新增方法**：每个工具类需要暴露 OpenAI 标准的 JSON Schema。

```python
class Tool(ABC):
    # ... 原有方法不变 ...

    @property
    @abstractmethod
    def schema(self) -> dict:
        """
        返回 OpenAI Function Calling 格式的工具定义。
        示例：
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "Perform mathematical calculations",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "Math expression like 2+2"
                        }
                    },
                    "required": ["expression"]
                }
            }
        }
        """
        pass
```

**ToolRegistry 新增**：
```python
def get_schemas(self) -> list[dict]:
    """生成给 LLM 的 tools 参数"""
    return [t.schema for t in self._tools.values()]
```

---

### 3.2 LLM 调用层 (`core/llm_client.py`)

**接口变更**：
```python
def chat(
    self,
    messages: list[dict],
    tools: list[dict] | None = None,
    stream: bool = False
) -> str | Iterator[str]:
    """
    新增 tools 参数。
    当 tools 不为空且 stream=True 时，返回的生成器需要能产出 tool_calls 相关的 chunk。
    """
```

**请求体变化**：
```json
// 旧 (ReAct)
{
  "model": "kimi-k2.6",
  "messages": [{"role": "user", "content": "...ReAct Prompt..."}],
  "stream": true
}

// 新 (Function Calling)
{
  "model": "kimi-k2.6",
  "messages": [{"role": "user", "content": "用户原始输入"}],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "calculator",
        "description": "...",
        "parameters": {...}
      }
    }
  ],
  "tool_choice": "auto",
  "stream": true
}
```

**流式响应解析要点**：

| chunk 类型 | 识别特征 | 处理方式 |
|-----------|---------|---------|
| 普通内容 | `delta.content` 存在 | yield {"type": "content", "text": "..."} |
| 工具名开始 | `delta.tool_calls[0].function.name` | yield {"type": "tool_name", "name": "..."} |
| 工具参数 | `delta.tool_calls[0].function.arguments` | yield {"type": "tool_args", "args": "..."} |
| 响应结束 | `[DONE]` | yield {"type": "done"} |

**注意**：`arguments` 是**流式拼接**的，可能分多个 chunk 到达：
```
chunk1: arguments='{"exp'
chunk2: arguments='ression": "2+2"}'
```

需要在 LLMClient 内部维护 buffer，等 `tool_calls` 完整后再统一 yield 一个结构化事件。

---

### 3.3 Prompt 工程层 (`core/prompt_builder.py`)

**System Prompt 变革**：

```
旧 (ReAct):
你是自主决策AI Agent。可用工具：...
你必须严格遵循以下ReAct格式输出：
Thought: [...]
Action: [工具名称]
Action Input: [JSON]
Final Answer: [...]

新 (Function Calling):
你是自主决策AI Agent。当用户的问题需要外部工具时，
你会调用可用工具来获取信息；当不需要工具时，直接回答用户。

可用工具：
- calculator: 数学计算
- weather_query: 天气查询
...

注意：
1. 如果可以直接回答，不要调用工具。
2. 调用工具时，请确保参数准确。
3. 收到工具结果后，结合上下文给出最终回答。
```

**核心差异**：
- 不再要求 LLM 输出 `Thought/Action/Action Input` 文本结构
- 工具能力通过 `tools` API 参数告知 LLM，而非纯文本描述
- 保留少量文本描述是为了让 LLM 理解工具用途，辅助决策

**新增接口**：
```python
def build_messages(self, user_input: str, history: list[dict]) -> list[dict]:
    """构建标准 messages 列表，不含 ReAct 格式要求"""
    pass
```

---

### 3.4 核心循环层 — ToolLoop (`core/tool_loop.py` 替代 `react_loop.py`)

**新类设计**：
```python
class ToolLoop:
    def __init__(self, llm, tools: ToolRegistry, prompt_builder, memory, stream_manager):
        self.llm = llm
        self.tools = tools
        self.prompt_builder = prompt_builder
        self.memory = memory
        self.stream = stream_manager

    def run(self, user_input: str, session_id: str, max_iterations: int = 5) -> str:
        """
        执行流程：
        1. 添加用户输入到记忆
        2. 构建 messages（含历史）
        3. 调用 LLM（stream=True, tools=schemas）
        4. 流式收集响应：
           - 普通 token → push(type="thinking", content=token)
           - tool_calls → push(type="tool_start"), push(type="tool_args")
        5. 完整响应后：
           - 无 tool_calls → 内容即 Final Answer，结束
           - 有 tool_calls → 解析参数，执行工具
        6. 工具执行后：
           - push(type="tool_result", content=result)
           - 把 tool 结果加入 messages（role="tool"）
           - 再次调用 LLM（stream=True，不传 tools 或传空）
           - 这次返回的 content 就是 Final Answer，逐字 push(type="final")
        """
        pass
```

**关键状态机**：

```
状态：IDLE
  └─ 用户输入 → 调用 LLM(stream, tools)
      ├─ 收到 content token → 状态: THINKING → push(thinking)
      ├─ 收到 tool_calls.name → 状态: TOOL_CALL → push(tool_start)
      ├─ 收到 tool_calls.arguments → 状态: TOOL_CALL → push(tool_args)
      └─ [DONE]
          ├─ 无 tool_calls → 结束
          └─ 有 tool_calls → 解析 → 执行工具 → push(tool_result)
              └─ 再次调用 LLM(stream)
                  ├─ 收到 content token → 状态: FINAL_ANSWER → push(final)
                  └─ [DONE] → 结束
```

---

### 3.5 流式输出层 (`streaming/stream_manager.py`)

**新增 SSE 事件类型**：

```python
# 后端推送给前端的数据格式规范
{
    "type": "thinking",       # LLM 正在思考（逐字）
    "content": "我需要..."
}
{
    "type": "tool_start",     # 开始调用工具
    "name": "calculator",
    "timestamp": "..."
}
{
    "type": "tool_args",      # 工具参数（可能流式追加）
    "content": "{\"expression\": \"2+2\"}",
    "timestamp": "..."
}
{
    "type": "tool_result",    # 工具执行结果
    "content": "{\"result\": 4}",
    "timestamp": "..."
}
{
    "type": "final",          # 最终答案（逐字流式）
    "content": "2加2等于4"
}
```

**废弃类型**：`thought`, `action`, `action_input`, `observation`（被新类型替代）

---

### 3.6 前端层 (`web/static/js/app.js` + `style.css`)

**新的事件处理逻辑**：

```javascript
function handleStreamEvent(data) {
    switch(data.type) {
        case "thinking":
            // 实时追加到"思考中"区域，带打字机效果
            appendTypingText("thinking-area", data.content);
            break;

        case "tool_start":
            // 显示"正在使用工具：xxx"状态卡片
            showToolCard(data.name);
            break;

        case "tool_args":
            // 展开显示参数（可能逐字追加JSON）
            appendToolArgs(data.content);
            break;

        case "tool_result":
            // 显示工具执行结果
            showToolResult(data.content);
            break;

        case "final":
            // 最终答案，逐字追加到主消息气泡
            appendTypingText("main-answer", data.content);
            break;
    }
}
```

**UI 变化**：
- 移除黄色/蓝色/绿色的可折叠 ReAct 卡片
- 新增：
  - 顶部"思考中..."区域（灰色小字，实时打字）
  - 工具调用状态条（蓝色，显示工具名 + 参数 + 结果）
  - 最终答案区域（正常黑色文字，逐字出现）
- 增加光标闪烁动画 `▋` 在文字末尾

---

## 四、数据流对比

### 旧流程（ReAct）
```
用户: 计算 2+2

[等待 3 秒]
AI: （突然显示完整内容）
    Thought: 这是数学问题
    Action: calculator
    Action Input: {"expression": "2+2"}
    Observation: {"result": 4}
    Final Answer: 2+2=4
```

### 新流程（Function Calling + 流式）
```
用户: 计算 2+2

[0.1s] 思考中... Th
[0.2s] 思考中... Thou
[0.3s] 思考中... Thought
[0.5s] 【调用工具】calculator
[0.6s] 参数: {"expression": "2+2"}
[0.7s] 结果: 4
[0.8s] 最终答案: 2
[0.9s] 最终答案: 2+
[1.0s] 最终答案: 2+2
[1.1s] 最终答案: 2+2=
[1.2s] 最终答案: 2+2=4
```

---

## 五、实施里程碑

### Milestone 1：后端工具层（半天）
- [ ] 所有工具类新增 `schema` 属性
- [ ] ToolRegistry 新增 `get_schemas()`
- [ ] 单元测试验证 schema 格式正确

### Milestone 2：LLMClient 改造（半天）
- [ ] `chat()` 支持 `tools` 参数
- [ ] `_chat_stream()` 正确解析流式 tool_calls
- [ ] 内部维护 buffer 拼接 arguments
- [ ] 测试：验证流式 chunk 解析正确

### Milestone 3：ToolLoop 核心（1天）
- [ ] 新建 `core/tool_loop.py`
- [ ] 实现 IDLE → THINKING → TOOL_CALL → FINAL_ANSWER 状态机
- [ ] 集成 memory、stream_manager
- [ ] 测试：单工具调用、多轮对话、无工具直接回答

### Milestone 4：PromptBuilder 精简（半天）
- [ ] 移除 ReAct 格式要求
- [ ] 新增 Function Calling 兼容的 System Prompt
- [ ] 测试：验证 LLM 输出格式正确

### Milestone 5：前端改造（1天）
- [ ] 重写 `handleStreamEvent`，支持新事件类型
- [ ] 实现打字机效果（逐字追加 + 光标闪烁）
- [ ] 新增工具状态条 UI
- [ ] 移除旧的 reasoning-block 折叠卡片

### Milestone 6：集成联调（1天）
- [ ] 端到端测试所有工具
- [ ] 流式体验优化（延迟、滚动、卡顿）
- [ ] 错误边界处理（tool 参数解析失败、LLM 不输出 tool_calls 等）

---

## 六、风险与回退方案

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| Kimi 不完全支持 Function Calling | 中 | 高 | 先用 `test_api.py` 验证 `tools` 参数是否可用；如不支持，回退到方案 A（轻量级优化） |
| 流式 tool_calls 解析复杂 | 中 | 中 | 增加详细的 debug 日志；arguments 用 JSON buffer 拼接，失败时 fallback 到非流式 |
| 多工具并发调用 | 低 | 中 | 当前设计支持单工具链；如 LLM 一次返回多个 tool_calls，需扩展 loop 逻辑 |
| 改造期间项目不可用 | 低 | 高 | 使用 git 分支开发；保留 react_loop.py 作为备份 |

---

## 七、保留兼容性的设计决策

1. **文件级保留**：不删除 `react_loop.py`，重命名为 `react_loop_legacy.py`，便于对比和回退。
2. **配置级切换**：`config.py` 增加 `AGENT_MODE = os.getenv("AGENT_MODE", "function_calling")`，支持 `"react"` 回退。
3. **接口兼容**：`AgentCore.__init__` 中根据配置实例化 `ToolLoop` 或 `ReActLoop`，上层调用不变。

---

## 八、需要用户确认的问题

1. **Kimi Function Calling 支持验证**：
   请执行以下 curl，确认 Kimi 支持 `tools` 参数：
   ```bash
   curl https://api.moonshot.cn/v1/chat/completions \
     -H "Authorization: Bearer $LLM_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
       "model": "kimi-k2.6",
       "messages": [{"role": "user", "content": "北京天气"}],
       "tools": [{
         "type": "function",
         "function": {
           "name": "weather_query",
           "description": "查询天气",
           "parameters": {
             "type": "object",
             "properties": {
               "city": {"type": "string"}
             },
             "required": ["city"]
           }
         }
       }]
     }'
   ```
   如果返回中包含 `tool_calls`，则支持。

2. **是否保留 ReAct 作为 fallback？**
   建议保留，万一 Function Calling 不稳定可一键切换。

---

**方案完成。请确认是否按此执行，或有调整意见？**
