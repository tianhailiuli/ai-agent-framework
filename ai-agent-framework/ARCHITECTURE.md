# 架构说明

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     主控循环 (Orchestrator)                    │
│         while True: 思考 → 行动 → 观察 → 更新状态              │
└─────────────────────────────────────────────────────────────┘
                              │
    ┌─────────┐    ┌──────────┼──────────┐    ┌─────────┐
    ▼         ▼    ▼          ▼          ▼    ▼         ▼
┌───────┐ ┌───────┐ ┌─────────┐ ┌──────────┐ ┌───────┐ ┌─────────┐
│Prompt │ │工具   │ │工具集   │ │结果处理  │ │记忆   │ │流式输出 │
│工程   │ │调度器 │ │(5个)   │ │模块     │ │模块   │ │模块     │
└───────┘ └───────┘ └─────────┘ └──────────┘ └───────┘ └─────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
              ┌─────────┐        ┌─────────┐
              │ Web界面 │        │多Agent  │
              │ (Flask) │        │协作模块  │
              └─────────┘        └─────────┘
```

## 模块说明

### core/agent_core.py — AgentCore
系统入口，负责：
- 初始化所有模块
- 根据请求复杂度选择单 Agent (ReAct) 或多 Agent (Planner + Executor) 路径
- 管理会话生命周期

### core/react_loop.py — ReActLoop
核心推理循环：
1. 构建包含历史记录和观察结果的 Prompt
2. 调用 LLM 获取结构化输出
3. 使用正则解析 Thought / Action / Action Input / Final Answer
4. 若存在 Action，调用对应工具并将结果作为 Observation 反馈给 LLM
5. 重复直到出现 Final Answer 或达到最大迭代次数

### core/llm_client.py — LLMClient
封装 LLM API 调用：
- 支持流式 (SSE chunks) 和非流式返回
- 自动重试机制 (默认 3 次)
- 兼容 OpenAI 及兼容 OpenAI 的 API

### core/prompt_builder.py — PromptBuilder
构造所有 LLM Prompt：
- System Prompt：包含工具描述和 ReAct 格式规范
- ReAct Prompt：包含对话历史和观察结果
- Planner Prompt：要求 LLM 输出子任务 JSON
- Executor Prompt：为单个子任务提供上下文

### core/multi_agent.py — PlannerAgent / ExecutorAgent
多 Agent 协作：
- **PlannerAgent**：将用户复杂请求分解为带依赖关系的子任务列表
- **ExecutorAgent**：按依赖拓扑排序逐个执行子任务，每个子任务内部复用 ReActLoop
- 最后由 LLM 汇总所有子任务结果生成最终回复

### tools/ — 工具集
所有工具继承自 `Tool` 抽象基类，通过 `ToolRegistry` 统一管理。

| 工具 | 说明 |
|------|------|
| calculator | 安全数学计算 (AST 解析，非 eval) |
| wikipedia_search | 维基百科词条搜索摘要 |
| file_read | 安全文件读取 (路径白名单) |
| file_write | 安全文件写入 (路径白名单) |
| weather_query | Open-Meteo 天气查询 |

### memory/memory_manager.py — MemoryManager
记忆管理：
- **短期记忆**：`collections.deque`，按会话隔离，默认保留最近 20 轮
- **长期记忆**：SQLite 持久化，支持按关键词检索
- 启动新会话时自动生成 UUID 作为 session_id

### streaming/stream_manager.py — StreamManager
SSE 流式推送：
- 为每个会话创建 `queue.Queue`
- ReActLoop / ExecutorAgent 在关键节点 push 事件
- Flask 路由通过 `stream_with_context` 返回 `text/event-stream`

### web/app.py — Flask Web
提供 RESTful API 和前端页面：
- `POST /api/chat` — 非流式对话
- `POST /api/chat/stream` — SSE 流式对话
- `GET /api/sessions` — 会话列表
- `GET/DELETE /api/sessions/<id>` — 查询/清空会话历史

## 数据流

### 单 Agent 请求
```
用户输入 → AgentCore.process()
  → MemoryManager.add_short_term()
  → ReActLoop.run()
    → PromptBuilder.build_react_prompt()
    → LLMClient.chat()
    → 解析 Action → ToolRegistry.get() → Tool.run()
    → Observation 加入历史
    → 循环直到 Final Answer
  → MemoryManager.add_short_term()
  → 返回结果
```

### 多 Agent 请求
```
用户输入 → AgentCore.process()
  → 触发多 Agent 条件
  → PlannerAgent.plan() → Task[]
  → ExecutorAgent.execute_plan()
    → 拓扑排序
    → 对每个 Task 调用 ExecutorAgent.execute()
      → 内部使用 ReActLoop
    → StreamManager.push() 进度
    → 全部完成后 LLM 汇总
  → 返回结果
```

## 安全设计

1. **文件工具路径限制**：使用 `os.path.abspath` 校验目标路径必须在 `SAFE_FILE_BASE_PATH` 之下
2. **计算器安全**：不使用 `eval`，而是解析 AST 并仅允许白名单运算符
3. **SQL 注入防护**：SQLite 参数化查询
4. **API Key 管理**：通过环境变量注入，禁止硬编码
