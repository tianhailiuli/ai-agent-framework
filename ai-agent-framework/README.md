# AI Agent Framework

一个轻量级的 AI Agent 框架，使 LLM 具备自主工具调用与决策能力。

> **零外部框架依赖**：仅使用 Flask、requests、sqlite3 等基础库，从零构建完整的 Agent 能力。

## ✨ 特性

- **Function Calling 工具调用**：原生支持多工具并行调用、结果缓存、速率限制
- **ReAct 推理循环**：思考-行动-观察核心循环，支持流式输出
- **内置工具集**：计算器、文件读写、天气查询、网页搜索
- **长短期记忆**：内存级短期缓存 + SQLite 长期持久化，自动归档与上下文召回
- **流式 SSE 推送**：基于 Server-Sent Events 的实时打字机效果
- **多 Agent 协作**：Planner + Executor 协作处理复杂规划任务
- **Web 交互界面**：基于 Flask 的聊天界面，支持工具卡片渲染
- **端口守护**：自动清理僵尸进程，防止端口占用

## 📦 安装

### 从源码安装

```bash
git clone <repo-url>
cd ai-agent-framework
pip install -e ".[dev]"
```

### 依赖

- Python >= 3.10
- Flask >= 2.0
- requests >= 2.28
- python-dotenv >= 1.0
- psutil >= 5.9

## 🚀 快速开始

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 LLM API Key
```

示例 `.env`：

```env
LLM_API_KEY=sk-your-api-key-here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

> 支持任意 OpenAI-compatible API，包括 Kimi、DeepSeek、通义千问等。

### 2. 纯代码调用（最小示例）

```python
from ai_agent_framework import AgentCore

agent = AgentCore()
result = agent.process("北京今天天气怎么样？", stream=False)
print(result)
```

### 3. 启动 Web 服务

```bash
python main.py
# 或
python launch.py --foreground
```

访问 http://localhost:5000 打开交互界面。

### 4. 命令行入口（安装后）

```bash
ai-agent
```

## 🏗 架构

```
ai-agent-framework/
├── src/ai_agent_framework/
│   ├── core/           # 主控编排、LLM 客户端、ReAct/FC 循环、多 Agent
│   ├── memory/         # 短期记忆 (deque) + 长期记忆 (SQLite)
│   ├── tools/          # 工具注册表与内置工具实现
│   ├── streaming/      # SSE 流管理
│   ├── utils/          # 端口守护等工具
│   └── web/            # Flask Web 应用（含静态资源）
├── tests/              # pytest 测试套件
├── main.py             # 开发模式入口
└── launch.py           # 统一启动器（支持后台/前台）
```

### 核心流程

```
用户输入
    → AgentCore.process()
        → 简单任务 → ToolLoop (Function Calling)
        → 复杂任务 → PlannerAgent.plan() → ExecutorAgent.execute_plan()
    → 自动归档记忆 → 返回结果 / SSE 流
```

## 🔧 配置项

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `LLM_API_KEY` | *(必填)* | LLM API 密钥 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | API 基础地址 |
| `LLM_MODEL` | `gpt-4o-mini` | 模型名称 |
| `AGENT_MODE` | `function_calling` | `function_calling` 或 `react` |
| `MEMORY_DB_PATH` | `memory.db` | SQLite 数据库路径 |
| `SAFE_FILE_BASE_PATH` | `./data` | 文件工具允许的最高目录 |
| `FLASK_PORT` | `5000` | Web 服务端口 |
| `MAX_REACT_ITERATIONS` | `10` | 最大推理轮数 |

## 🧪 测试

```bash
pytest tests/ -v
```

## 📄 License

[MIT](LICENSE)
