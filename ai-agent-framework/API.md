# Web API 文档

## 页面路由

### GET /
返回前端单页面应用 (index.html)。

---

## API 路由

### POST /api/chat
非流式对话接口。

**请求体**:
```json
{
  "message": "用户输入",
  "session_id": "可选，不提供则创建新会话"
}
```

**响应**:
```json
{
  "response": "Agent 回复",
  "session_id": "会话 ID"
}
```

**错误响应**:
```json
{
  "error": "错误信息",
  "session_id": "会话 ID"
}
```

---

### POST /api/chat/stream
流式对话接口 (SSE)。

**请求体**:
```json
{
  "message": "用户输入",
  "session_id": "可选"
}
```

**响应**: `Content-Type: text/event-stream`

每条消息格式:
```json
{
  "type": "thought|action|action_input|observation|final|error",
  "content": "...",
  "timestamp": "2024-01-15T10:30:00"
}
```

前端接收示例:
```javascript
const resp = await fetch("/api/chat/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "计算 2+2" })
});
const reader = resp.body.getReader();
// 读取 SSE 数据
```

---

### GET /api/sessions
获取所有历史会话 ID。

**响应**:
```json
{
  "sessions": ["uuid-1", "uuid-2"]
}
```

---

### GET /api/sessions/<session_id>
获取指定会话的历史记录。

**响应**:
```json
{
  "session_id": "uuid",
  "history": [
    {
      "id": 1,
      "session_id": "uuid",
      "role": "user",
      "content": "...",
      "timestamp": 1705312200.0,
      "metadata": {}
    }
  ]
}
```

---

### DELETE /api/sessions/<session_id>
清空指定会话的短期记忆。

**响应**:
```json
{
  "message": "Session uuid short-term memory cleared."
}
```
