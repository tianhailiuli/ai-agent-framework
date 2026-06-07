const API_BASE = '';
let currentSessionId = localStorage.getItem('currentSessionId') || null;
let isStreaming = false;
let abortController = null;

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// Track active AI message components during streaming
let activeAiMessage = null;
let activeThinkingText = null;
let activeToolContainer = null;
let activeFinalArea = null;
let activeCursor = null;

// Buffers for efficient rendering
let finalBuffer = '';
let scrollPending = false;
let thinkingVisible = true;

document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
    setupEventListeners();
    updateSendButton();
    if (currentSessionId) loadSessionHistory(currentSessionId);
});

/* ---------- Event Listeners ---------- */
function setupEventListeners() {
    $('#send-btn').addEventListener('click', sendMessage);
    $('#user-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    $('#user-input').addEventListener('input', () => {
        autoResizeTextarea();
        updateSendButton();
    });
    $('#new-chat-btn').addEventListener('click', createNewSession);
    $('#menu-toggle').addEventListener('click', toggleSidebar);
    $('#clear-chat').addEventListener('click', clearCurrentSession);

    $$('.chip').forEach(chip => {
        chip.addEventListener('click', () => {
            $('#user-input').value = chip.dataset.text;
            autoResizeTextarea();
            updateSendButton();
            $('#user-input').focus();
        });
    });

    document.addEventListener('click', (e) => {
        const sidebar = $('#sidebar');
        if (window.innerWidth <= 768 && !sidebar.contains(e.target) && !$('#menu-toggle').contains(e.target)) {
            sidebar.classList.add('collapsed');
        }
    });
}

function autoResizeTextarea() {
    const ta = $('#user-input');
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
}

function updateSendButton() {
    const btn = $('#send-btn');
    const text = $('#user-input').value.trim();
    btn.disabled = !text || isStreaming;
}

/* ---------- Session Management ---------- */
async function loadSessions() {
    try {
        const resp = await fetch(`${API_BASE}/api/sessions`);
        const data = await resp.json();
        renderSessionList(data.sessions || []);
    } catch (e) {
        console.error('Failed to load sessions', e);
    }
}

function renderSessionList(sessions) {
    const list = $('#session-list');
    list.innerHTML = '';

    const allSessions = Array.from(new Set(
        currentSessionId ? [currentSessionId, ...sessions] : sessions
    ));

    if (allSessions.length === 0) {
        list.innerHTML = '<div class="session-item" style="cursor:default;opacity:0.5">暂无历史会话</div>';
        return;
    }

    allSessions.forEach(sid => {
        const item = document.createElement('div');
        item.className = 'session-item' + (sid === currentSessionId ? ' active' : '');

        const nameSpan = document.createElement('span');
        nameSpan.className = 'session-name';
        nameSpan.textContent = '会话 ' + sid.slice(0, 8);

        const actions = document.createElement('div');
        actions.className = 'session-actions';

        const delBtn = document.createElement('button');
        delBtn.className = 'icon-btn-small';
        delBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>`;
        delBtn.title = '删除会话';
        delBtn.onclick = (e) => { e.stopPropagation(); deleteSession(sid); };

        actions.appendChild(delBtn);
        item.appendChild(nameSpan);
        item.appendChild(actions);
        item.addEventListener('click', () => switchSession(sid));
        list.appendChild(item);
    });
}

function switchSession(sid) {
    if (sid === currentSessionId) return;
    currentSessionId = sid;
    localStorage.setItem('currentSessionId', sid);
    $('#chat-title').textContent = '会话 ' + sid.slice(0, 8);
    loadSessionHistory(sid);
    renderSessionList([]);
    loadSessions();
    if (window.innerWidth <= 768) $('#sidebar').classList.add('collapsed');
}

function createNewSession() {
    currentSessionId = null;
    localStorage.removeItem('currentSessionId');
    $('#chat-title').textContent = '新会话';
    $('#messages').innerHTML = '';
    $('#empty-state').style.display = 'flex';
    loadSessions();
    if (window.innerWidth <= 768) $('#sidebar').classList.add('collapsed');
}

async function deleteSession(sid) {
    try {
        await fetch(`${API_BASE}/api/sessions/${sid}`, { method: 'DELETE' });
        if (sid === currentSessionId) createNewSession();
        else loadSessions();
    } catch (e) {
        showToast('删除失败: ' + e.message);
    }
}

async function clearCurrentSession() {
    if (!currentSessionId) {
        $('#messages').innerHTML = '';
        $('#empty-state').style.display = 'flex';
        return;
    }
    try {
        await fetch(`${API_BASE}/api/sessions/${currentSessionId}`, { method: 'DELETE' });
        $('#messages').innerHTML = '';
        $('#empty-state').style.display = 'flex';
        showToast('会话已清空');
    } catch (e) {
        showToast('清空失败: ' + e.message);
    }
}

function toggleSidebar() {
    $('#sidebar').classList.toggle('collapsed');
}

/* ---------- History ---------- */
async function loadSessionHistory(sid) {
    $('#messages').innerHTML = '';
    $('#empty-state').style.display = 'none';

    try {
        const resp = await fetch(`${API_BASE}/api/sessions/${sid}`);
        if (!resp.ok) throw new Error('Failed to load');
        const data = await resp.json();

        const history = (data.history || []).sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
        if (history.length === 0) {
            $('#empty-state').style.display = 'flex';
            return;
        }

        history.forEach(entry => {
            if (entry.role === 'user') {
                appendMessage(entry.content, 'user');
            } else if (entry.role === 'assistant') {
                appendMessage(entry.content, 'ai');
            }
        });
        scrollToBottom();
    } catch (e) {
        console.error('Failed to load history', e);
        $('#empty-state').style.display = 'flex';
    }
}

/* ---------- Send Message ---------- */
async function sendMessage() {
    const input = $('#user-input');
    const text = input.value.trim();
    if (!text || isStreaming) return;

    input.value = '';
    input.style.height = 'auto';
    updateSendButton();
    $('#empty-state').style.display = 'none';

    if (!currentSessionId) {
        currentSessionId = generateUUID();
        localStorage.setItem('currentSessionId', currentSessionId);
        $('#chat-title').textContent = '会话 ' + currentSessionId.slice(0, 8);
        loadSessions();
    }

    appendMessage(text, 'user');

    isStreaming = true;
    updateSendButton();
    $('#typing-indicator').classList.add('visible');
    scrollToBottom();

    // Reset rendering state
    finalBuffer = '';
    thinkingVisible = true;

    const aiMsg = createAiMessageSkeleton();
    activeAiMessage = aiMsg;
    activeThinkingText = aiMsg.querySelector('.thinking-text');
    activeToolContainer = aiMsg.querySelector('.tool-container');
    activeFinalArea = aiMsg.querySelector('.final-area');
    activeCursor = aiMsg.querySelector('.typing-cursor');

    try {
        const resp = await fetch(`${API_BASE}/api/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, session_id: currentSessionId }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || resp.statusText);
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const dataStr = line.slice(6).trim();
                if (!dataStr || dataStr === '[DONE]') continue;

                try {
                    const data = JSON.parse(dataStr);
                    handleStreamEvent(data);
                } catch (e) {
                    // ignore malformed lines
                }
            }
        }

        if (buffer.startsWith('data: ')) {
            try {
                const data = JSON.parse(buffer.slice(6));
                handleStreamEvent(data);
            } catch (e) {}
        }
    } catch (e) {
        if (activeFinalArea) {
            activeFinalArea.innerHTML = `<span style="color:#dc2626">连接失败: ${escapeHtml(e.message)}</span>`;
        } else {
            appendMessage('连接失败: ' + e.message, 'ai');
        }
        console.error(e);
    } finally {
        isStreaming = false;
        updateSendButton();
        $('#typing-indicator').classList.remove('visible');
        if (activeCursor) activeCursor.style.display = 'none';

        // Ensure final buffer is fully rendered
        if (activeFinalArea && finalBuffer) {
            activeFinalArea.innerHTML = renderMarkdown(finalBuffer);
        }
        // Hide thinking area when done
        const thinkingArea = activeAiMessage?.querySelector('.thinking-area');
        if (thinkingArea) thinkingArea.style.display = 'none';

        activeAiMessage = null;
        activeThinkingText = null;
        activeToolContainer = null;
        activeFinalArea = null;
        activeCursor = null;
        finalBuffer = '';

        scrollToBottom();
        loadSessions();
    }
}

/* ---------- Stream Event Handler ---------- */
function handleStreamEvent(data) {
    const type = data.type;
    const content = data.content || '';

    switch (type) {
        case 'thinking':
            // Don't show full reasoning text — just keep a "thinking..." hint alive
            // so the user knows the system is working instead of staring at a blank screen.
            if (activeAiMessage) {
                const prefix = activeAiMessage.querySelector('.thinking-prefix');
                if (prefix) {
                    const dots = ['.', '..', '...'];
                    const idx = Math.floor(Date.now() / 500) % 3;
                    prefix.textContent = '思考中' + dots[idx];
                }
                requestScroll();
            }
            break;

        case 'tool_start':
            if (activeToolContainer) {
                const toolCard = document.createElement('div');
                toolCard.className = 'tool-status';
                toolCard.dataset.toolName = content || data.name || 'unknown';
                toolCard.innerHTML = `
                    <div class="tool-header">
                        <span class="tool-icon">🔧</span>
                        <span>使用工具: ${escapeHtml(data.name || content)}</span>
                    </div>
                    <div class="tool-body">
                        <div class="tool-args"></div>
                        <div class="tool-result"></div>
                    </div>
                `;
                activeToolContainer.appendChild(toolCard);
                requestScroll();
            }
            break;

        case 'tool_args':
            if (activeToolContainer) {
                const lastCard = activeToolContainer.lastElementChild;
                if (lastCard) {
                    const argsDiv = lastCard.querySelector('.tool-args');
                    if (argsDiv) {
                        argsDiv.textContent = '参数: ' + content;
                        requestScroll();
                    }
                }
            }
            break;

        case 'tool_result':
            if (activeToolContainer) {
                const lastCard = activeToolContainer.lastElementChild;
                if (lastCard) {
                    const resultDiv = lastCard.querySelector('.tool-result');
                    if (resultDiv) {
                        resultDiv.textContent = '结果: ' + content;
                        requestScroll();
                    }
                }
            }
            break;

        case 'final':
            if (activeFinalArea) {
                // Hide thinking area when final content starts
                if (thinkingVisible) {
                    const thinkingArea = activeAiMessage?.querySelector('.thinking-area');
                    if (thinkingArea) {
                        thinkingArea.style.display = 'none';
                        thinkingVisible = false;
                    }
                }
                if (activeCursor) activeCursor.style.display = 'none';
                finalBuffer += content;
                activeFinalArea.innerHTML = renderMarkdown(finalBuffer);
                requestScroll();
            }
            break;

        case 'error':
            if (activeFinalArea) {
                activeFinalArea.innerHTML = `<span style="color:#dc2626">错误: ${escapeHtml(content)}</span>`;
            }
            if (activeCursor) activeCursor.style.display = 'none';
            break;
    }
}

/* ---------- Markdown Renderer ---------- */
function renderMarkdown(text) {
    if (!text) return '';
    
    // Escape HTML entities first
    let html = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    
    // Code blocks: ```lang\ncode\n```
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>');
    
    // Inline code: `code`
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Bold: **text**
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    
    // Italic: *text* (but not inside code)
    html = html.replace(/(?<!<code[^>]*>)\*(?!\*)(.+?)\*(?!<\/code>)/g, '<em>$1</em>');
    
    // Headers: ### text
    html = html.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^##\s+(.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^#\s+(.+)$/gm, '<h1>$1</h1>');
    
    // Unordered lists: - item
    html = html.replace(/^(\s*)-\s+(.+)$/gm, '<li>$2</li>');
    
    // Ordered lists: 1. item
    html = html.replace(/^(\s*)\d+\.\s+(.+)$/gm, '<li>$2</li>');
    
    // Links: [text](url)
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    
    // Line breaks
    html = html.replace(/\n/g, '<br>');
    
    return html;
}

/* ---------- Throttled Scroll ---------- */
function requestScroll() {
    if (scrollPending) return;
    scrollPending = true;
    requestAnimationFrame(() => {
        scrollToBottom();
        scrollPending = false;
    });
}

/* ---------- UI Helpers ---------- */
function appendMessage(content, role) {
    const container = $('#messages');
    const msg = document.createElement('div');
    msg.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'user' ? '我' : 'AI';

    const body = document.createElement('div');
    body.className = 'message-content';

    if (role === 'user') {
        body.textContent = content;
    } else {
        body.innerHTML = renderMarkdown(content);
    }

    msg.appendChild(avatar);
    msg.appendChild(body);
    container.appendChild(msg);
    scrollToBottom();
    return msg;
}

function createAiMessageSkeleton() {
    const container = $('#messages');
    const msg = document.createElement('div');
    msg.className = 'message ai';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = 'AI';

    const body = document.createElement('div');
    body.className = 'message-content';
    body.innerHTML = `
        <div class="thinking-area">
            <span class="thinking-prefix">思考中</span>
            <span class="thinking-text"></span>
            <span class="typing-cursor"></span>
        </div>
        <div class="tool-container"></div>
        <div class="final-area"></div>
    `;

    msg.appendChild(avatar);
    msg.appendChild(body);
    container.appendChild(msg);
    scrollToBottom();
    return msg;
}

function scrollToBottom() {
    const container = $('#messages-container');
    container.scrollTop = container.scrollHeight;
}

function showToast(text) {
    const toast = $('#toast');
    toast.textContent = text;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2500);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}
