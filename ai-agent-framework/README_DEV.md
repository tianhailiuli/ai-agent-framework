# 项目开发手册

这份文档是给组内成员看的，不是对外 README。讲清楚系统怎么设计的、哪里容易改坏、接手时要注意什么。

---

## 1. 系统总览

一个基于 LLM 的 Agent 框架，核心能力：
- 调用外部工具（天气、计算、文件读写、搜索）
- 流式 SSE 输出到前端
- 短期+长期记忆
- 单 Agent（FC/ReAct）和多 Agent（Planner+Executor）两种模式

技术栈：Python 3.10+、Flask、requests、sqlite3。零高层框架依赖。

---

## 2. 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| 入口 | `core/agent_core.py` | 判断走单 Agent 还是多 Agent，协调 memory/stream |
| FC 循环 | `core/tool_loop.py` | Function Calling 主循环，工具调用、并发、缓存 |
| ReAct 循环 | `core/react_loop.py` | 文本解析式推理循环（legacy，备用） |
| LLM 客户端 | `core/llm_client.py` | 封装 OpenAI-compatible API，流式+重试 |
| Prompt 构造 | `core/prompt_builder.py` | 所有 System Prompt / User Prompt 的生成 |
| 多 Agent | `core/multi_agent.py` | Planner 分解任务，Executor 按依赖执行 |
| 记忆 | `memory/memory_manager.py` | 短期 deque + 长期 SQLite，session 隔离 |
| 流管理 | `streaming/stream_manager.py` | SSE 事件队列，按 session 隔离 |
| 工具集 | `tools/*.py` | 各工具实现 + ToolRegistry |
| Web | `web/app.py` | Flask 路由 + SSE endpoint |

---

## 3. 数据流

### 3.1 单 Agent 流（function_calling 模式，默认）

```
用户输入 → AgentCore._execute()
  → ToolLoop.run()
    → 可选：内置工具快速路径（正则匹配直接执行，不走 LLM）
    → PromptBuilder.build_fc_messages()（注入 history + related_memories）
    → LLMClient.chat(stream=True, tools=...)
    → 解析 tool_calls
    → 缓存命中？→ 直接返回
    → ThreadPoolExecutor 并发执行工具
    → 结果写入 memory（assistant + tool）
    → 下一轮（最多 MAX_REACT_ITERATIONS 轮）
  → 最终答案
```

**关键规则：**
- 最后一轮不传给 LLM tools，强制它输出最终答案
- 每轮迭代先 push `thinking` 事件给前端，再 push `final`
- `MAX_CHARS_PER_SECOND = 20`，按字符数算延迟

### 3.2 多 Agent 流

```
用户输入 → AgentCore._execute()
  → 触发条件：含规划/计划/安排/分步/协作 或长度 > 60
  → PlannerAgent.plan() → JSON Task[]
  → ExecutorAgent.execute_plan()
    → 拓扑排序
    → 每个 Task 内部走 ReActLoop
    → StreamManager push 进度事件
  → LLM 汇总所有子任务结果
```

---

## 4. 配置

所有配置在 `.env` 里，通过 `config.py` 加载。优先读取 CWD 的 `.env`，fallback 到包目录。

```env
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-8k
AGENT_MODE=function_calling   # function_calling | react
FLASK_PORT=8080
MEMORY_DB_PATH=memory.db
SAFE_FILE_BASE_PATH=./data
```

**注意：**
- `.env` 绝不能进 git（已在 `.gitignore` 中）
- 根目录 `config.py` 是薄代理，新代码不要从根目录 import config

---

## 5. 记忆系统

### 5.1 短期记忆

```python
self.short_term: dict[str, deque]  # session_id -> deque(maxlen=20)
```

每次 `process()` 结束后，loop 会写入 user/assistant/tool 消息。`session_id` 必须传对，否则串会话。

### 5.2 长期记忆

SQLite 表 `long_term_memory`：
- `session_id`
- `role` (user/assistant)
- `content`
- `timestamp`
- `metadata`

自动归档：`persist_without_clear()` 在每次对话结束后调用，把短期记忆写入 SQLite，但不清空 deque。

相关记忆召回：用关键词分词匹配，取最近 5 条注入 Prompt。

---

## 6. 工具系统

### 6.1 注册

`AgentCore._register_default_tools()` 里注册。加新工具：
1. 写类继承 `Tool`
2. 实现 `run()` 和 `description`/`parameters`
3. 在 `AgentCore` 里 `self.tools.register(NewTool())`

### 6.2 安全

- **calculator**：AST 遍历，只允 `ast.Constant` + `ast.BinOp` + `ast.UnaryOp`，拒绝 `ast.Call`/`ast.Name`
- **file_read/file_write**：`Path.resolve()` 后检查是否以 `SAFE_FILE_BASE_PATH` 开头

### 6.3 内置工具路径

`ToolLoop._try_builtin(user_input)` 用正则匹配计算请求。命中后直接本地执行，不走 LLM，隐藏工具 UI。

### 6.4 缓存

`{(tool_name, args_json): (result, timestamp)}`，TTL 60s。命中时前端显示 `[cached]`。

---

## 7. 流式 SSE

### 7.1 事件类型

| type | 说明 |
|------|------|
| `thinking` | 正在思考，前端只显示前缀动画 |
| `tool_start` | 开始调用工具，展开卡片 |
| `tool_args` | 显示参数 |
| `tool_result` | 显示结果 |
| `final` | 最终答案片段，前端逐字追加 |
| `done` | 结束，前端关闭连接 |
| `error` | 异常 |

### 7.2 断开条件

前端收到 `type in ("done", "error")` 时关闭 EventSource。后端 generator 结束时必须 push `done`。

### 7.3 速率限制

按字符数算：`delay = len(text) * (1 / MAX_CHARS_PER_SECOND)`。不是固定间隔，长文本延迟大，短文本延迟小。

---

## 8. 容易改坏的地方

### 8.1 session_id 传错

`memory.get_short_term(session_id)` 必须传 `session_id`。漏传就读到 `default`，所有用户共享历史。

**涉及位置：**
- `react_loop.py:45`（已修复）
- `tool_loop.py` 多处
- `multi_agent.py` 的 `execute_plan()`

### 8.2 重复写 memory

`agent_core.py` 的 `_execute()` 曾经和 `ToolLoop.run()` 都写 user/assistant，导致重复条目。

**现状：** `_execute()` 不再写 memory，全权委托 loop。loop 内部有去重检查（检查最后一条的 role + content）。

### 8.3 并发工具的执行顺序

`ThreadPoolExecutor` 并发执行多个 `tool_calls`，但结果必须按原顺序返回 LLM（因为 `tool_call_id` 要对应）。

`ToolLoop` 里用 `list(ex.map(...))` 保持顺序。

### 8.4 Flask 的 template/static 路径

`web/app.py` 的 `template_folder` 和 `static_folder` 用的是包内路径：
```python
_pkg_dir = Path(__file__).parent
app = Flask(__name__, template_folder=str(_pkg_dir / "templates"), ...)
```

不要改成相对路径 `"templates"`，否则 `pip install` 后找不到文件。

---

## 9. 测试

```bash
pytest tests/ -v
```

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_tools.py` | 所有工具的正确性、安全性 |
| `test_memory.py` | 短期/长期记忆、session 隔离 |
| `test_react_loop.py` | ReAct 循环的解析、终止 |
| `test_integration_fc.py` | FC 完整链路（builtin、单工具、无工具） |
| `test_multi_agent.py` | Planner JSON 解析、Executor 任务执行 |

**加新工具必须补测试。**

---

## 10. 打包与发布

```bash
pip install -e ".[dev]"   # 开发模式安装
```

`pyproject.toml` 定义了包元数据。发布时：
```bash
python -m build
 twine upload dist/*
```

**不要提交：** `.env`、`.db`、`*`.log`、`__pycache__`。已写在 `.gitignore` 里。

---

## 11. 已知限制

1. **LLM 强绑定**：目前使用 OpenAI-compatible 协议（/v1/chat/completions），因此天然支持所有提供该协议的 Provider（OpenAI、Kimi、DeepSeek、通义千问、智谱等）。不支持非兼容协议的 Provider（如 Claude 原生 API、Gemini 原生 API）
2. **记忆召回简单**：关键词匹配，不是向量检索。长文档相关度低
3. **前端原生 JS**：没有框架，维护成本随复杂度上升
4. **killall 太暴力**：`launch.py --killall` 杀所有 python.exe，生产环境禁用——因为经常会在多次使用/测试后进程卡死，还没优化先用killall凑合hhh
5. **Windows 为主**：`port_guard.py` 的 `taskkill` 和 `CREATE_NEW_PROCESS_GROUP` 是 Windows 逻辑，Linux/Mac 需要适配
