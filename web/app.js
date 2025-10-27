// 应用状态
const state = {
    processing: false,
    ws: null,
    messages: [],
    token: null
};

// ============= 认证函数 =============

function getAuthToken() {
    return localStorage.getItem('token');
}

function setAuthToken(token) {
    if (token) {
        localStorage.setItem('token', token);
        state.token = token;
    }
}

function clearAuthToken() {
    localStorage.removeItem('token');
    localStorage.removeItem('username');
    localStorage.removeItem('user_id');
    state.token = null;
}

function checkAuthentication() {
    const token = getAuthToken();
    if (!token) {
        // 没有 token，重定向到登录页面
        window.location.href = '/login';
        return;
    }
    state.token = token;
}

function logout() {
    console.log('执行登出操作');
    clearAuthToken();
    // 强制跳转到登录页
    window.location.replace('/login');
}

// 获取 API 请求头（包含 token）
function getApiHeaders() {
    const headers = {
        'Content-Type': 'application/json'
    };

    const token = getAuthToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    return headers;
}

// DOM 元素
const elements = {
    messagesContainer: document.getElementById('messages-container'),
    welcomeMessage: document.getElementById('welcome-message'),
    messageInput: document.getElementById('message-input'),
    sendBtn: document.getElementById('send-btn'),
    newChatBtn: document.getElementById('new-chat-btn'),
    chatHistory: document.getElementById('chat-history'),
    modelName: document.getElementById('model-name'),
    inputWrapper: document.querySelector('.input-wrapper')
};

// 初始化用户信息显示
function initUserInfo() {
    const username = localStorage.getItem('username');
    const usernameDisplay = document.getElementById('username-display');
    const logoutButton = document.getElementById('logout-button');

    console.log('初始化用户信息:', { username, usernameDisplay, logoutButton });

    if (usernameDisplay && username) {
        usernameDisplay.textContent = `你好, ${username}`;
        console.log('用户名已设置');
    } else {
        console.warn('未找到用户名显示元素或用户名为空');
    }

    if (logoutButton) {
        logoutButton.addEventListener('click', logout);
        console.log('登出按钮事件已绑定');
    } else {
        console.warn('未找到登出按钮元素');
    }
}

// 初始化
document.addEventListener('DOMContentLoaded', async () => {
    // 检查认证状态
    checkAuthentication();

    // 初始化用户信息
    initUserInfo();

    // 绑定事件
    elements.sendBtn.addEventListener('click', handleSend);
    elements.newChatBtn.addEventListener('click', newChat);

    // 点击输入框任何位置都能触发输入焦点
    if (elements.inputWrapper) {
        elements.inputWrapper.addEventListener('click', (e) => {
            // 如果不是点击发送按钮，就让输入框获得焦点
            if (e.target !== elements.sendBtn && !elements.sendBtn.contains(e.target)) {
                elements.messageInput.focus();
            }
        });
    }

    // 输入框事件
    elements.messageInput.addEventListener('input', handleInput);
    elements.messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !state.processing) {
            e.preventDefault();
            handleSend();
        }
    });

    // 自动调整输入框高度
    elements.messageInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = this.scrollHeight + 'px';
    });

    // 建立 WebSocket 连接
    await connectWebSocket();

    // 获取模型信息
    fetchModelInfo();
});

// 获取模型信息
async function fetchModelInfo() {
    try {
        const response = await fetch('/health');
        const data = await response.json();
        elements.modelName.textContent = data.model_provider === 'openai' ? 'GPT-5' : 'DeepSeek';
    } catch (error) {
        console.error('获取模型信息失败:', error);
    }
}

// WebSocket 连接
async function connectWebSocket() {
    return new Promise((resolve, reject) => {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        state.ws = new WebSocket(wsUrl);

        state.ws.onopen = () => {
            console.log('WebSocket 已连接');
            resolve();
        };

        state.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleWebSocketMessage(data);
            } catch (error) {
                console.error('解析消息失败:', error);
            }
        };

        state.ws.onerror = (error) => {
            console.error('WebSocket 错误:', error);
            reject(error);
        };

        state.ws.onclose = () => {
            console.log('WebSocket 已断开');
            // 尝试重连
            setTimeout(() => connectWebSocket(), 3000);
        };
    });
}

// 处理 WebSocket 消息
function handleWebSocketMessage(data) {
    const { type, message, level, tool_name, tool_args, result, error } = data;

    switch (type) {
        case 'log':
            // 显示日志信息
            addLogMessage(message, level || 'info');
            break;

        case 'assistant_message':
            addMessage('assistant', message);
            break;

        case 'tool_call':
            addToolCall(tool_name, tool_args, 'running');
            break;

        case 'tool_result':
            updateToolCall(tool_name, 'completed', result);
            break;

        case 'notion_link':
            addNotionLink(result.title, result.url);
            break;

        case 'error':
            addMessage('assistant', `错误: ${error}`);
            break;

        case 'done':
            state.processing = false;
            elements.sendBtn.disabled = false;
            elements.messageInput.disabled = false;
            elements.messageInput.focus();
            break;
    }

    // 滚动到底部
    scrollToBottom();
}

// 处理输入
function handleInput() {
    const value = elements.messageInput.value.trim();
    elements.sendBtn.disabled = !value || state.processing;
}

// 发送消息
async function handleSend() {
    const message = elements.messageInput.value.trim();

    if (!message || state.processing) return;

    // 隐藏欢迎消息
    if (elements.welcomeMessage) {
        elements.welcomeMessage.classList.add('hidden');
    }

    // 添加用户消息
    addMessage('user', message);

    // 清空输入框
    elements.messageInput.value = '';
    elements.messageInput.style.height = 'auto';
    elements.sendBtn.disabled = true;
    elements.messageInput.disabled = true;

    // 显示输入中状态
    state.processing = true;
    addTypingIndicator();

    try {
        // 发送请求到后端
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: getApiHeaders(),
            body: JSON.stringify({ message })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '请求失败');
        }

        // 后端通过 WebSocket 返回消息

    } catch (error) {
        console.error('发送消息失败:', error);
        removeTypingIndicator();
        addMessage('assistant', `抱歉，发生错误：${error.message}`);
        state.processing = false;
        elements.sendBtn.disabled = false;
        elements.messageInput.disabled = false;
    }
}

// 添加日志消息
function addLogMessage(message, level = 'info') {
    // 获取或创建最后一个 assistant 消息的日志容器
    let logContainer = document.getElementById('current-log-container');

    if (!logContainer) {
        // 如果没有日志容器，检查是否有 typing indicator
        const typingIndicator = document.getElementById('typing-indicator');
        if (typingIndicator) {
            const messageContent = typingIndicator.querySelector('.message-content');

            // 移除 typing indicator，添加日志容器
            const typingDiv = messageContent.querySelector('.typing-indicator');
            if (typingDiv) {
                typingDiv.remove();
            }

            logContainer = document.createElement('div');
            logContainer.id = 'current-log-container';
            logContainer.className = 'log-container';
            logContainer.dataset.persistent = 'true'; // 标记为持久化容器
            messageContent.appendChild(logContainer);
        }
    }

    if (logContainer) {
        const logEntry = document.createElement('div');
        logEntry.className = `log-entry log-${level}`;
        logEntry.textContent = message;
        logContainer.appendChild(logEntry);
        scrollToBottom();
    }
}

// 添加消息
function addMessage(role, content) {
    // 移除输入中指示器
    if (role === 'assistant') {
        const typingIndicator = document.getElementById('typing-indicator');
        if (typingIndicator) {
            // 获取 typing indicator 中的所有内容（包括日志）
            const messageContent = typingIndicator.querySelector('.message-content');
            const logContainer = messageContent.querySelector('#current-log-container');

            // 创建新的 assistant 消息
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${role}`;

            const avatar = document.createElement('div');
            avatar.className = 'message-avatar';
            avatar.textContent = 'AI';

            const newMessageContent = document.createElement('div');
            newMessageContent.className = 'message-content';

            // 如果有日志容器，先添加日志（显示在上面）
            if (logContainer) {
                logContainer.removeAttribute('id'); // 移除临时 ID
                newMessageContent.appendChild(logContainer);
            }

            const messageText = document.createElement('div');
            messageText.className = 'message-text';
            messageText.textContent = content;

            newMessageContent.appendChild(messageText);

            messageDiv.appendChild(avatar);
            messageDiv.appendChild(newMessageContent);

            // 替换 typing indicator
            typingIndicator.replaceWith(messageDiv);

            // 保存消息
            state.messages.push({ role, content });

            scrollToBottom();
            return messageDiv;
        }
    }

    // 普通消息（用户消息或没有 typing indicator 的情况）
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'user' ? 'U' : 'AI';

    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';

    const messageText = document.createElement('div');
    messageText.className = 'message-text';
    messageText.textContent = content;

    messageContent.appendChild(messageText);
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(messageContent);

    elements.messagesContainer.appendChild(messageDiv);

    // 保存消息
    state.messages.push({ role, content });

    scrollToBottom();

    return messageDiv;
}

// 添加输入中指示器
function addTypingIndicator() {
    const existingIndicator = document.getElementById('typing-indicator');
    if (existingIndicator) return;

    const messageDiv = document.createElement('div');
    messageDiv.id = 'typing-indicator';
    messageDiv.className = 'message assistant';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = 'AI';

    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';

    const typingDiv = document.createElement('div');
    typingDiv.className = 'typing-indicator';
    typingDiv.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';

    messageContent.appendChild(typingDiv);
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(messageContent);

    elements.messagesContainer.appendChild(messageDiv);
    scrollToBottom();
}

// 移除输入中指示器
function removeTypingIndicator() {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) {
        indicator.remove();
    }
}

// 添加工具调用显示
function addToolCall(toolName, toolArgs, status = 'running') {
    const lastMessage = elements.messagesContainer.lastElementChild;
    if (!lastMessage || !lastMessage.classList.contains('assistant')) return;

    const toolCallDiv = document.createElement('div');
    toolCallDiv.className = 'tool-call';
    toolCallDiv.dataset.toolName = toolName;

    const header = document.createElement('div');
    header.className = 'tool-call-header';
    header.innerHTML = `
        <svg width="16" height="16" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M6 2a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2V7.414A2 2 0 0015.414 6L12 2.586A2 2 0 0010.586 2H6zm5 6a1 1 0 10-2 0v3.586l-1.293-1.293a1 1 0 10-1.414 1.414l3 3a1 1 0 001.414 0l3-3a1 1 0 00-1.414-1.414L11 11.586V8z"/>
        </svg>
        ${getToolDisplayName(toolName)}
        <span class="tool-call-status ${status}">${status === 'running' ? '运行中...' : '已完成'}</span>
    `;

    toolCallDiv.appendChild(header);

    if (toolArgs) {
        const details = document.createElement('div');
        details.className = 'tool-call-details';
        details.textContent = formatToolArgs(toolName, toolArgs);
        toolCallDiv.appendChild(details);
    }

    lastMessage.querySelector('.message-content').appendChild(toolCallDiv);
    scrollToBottom();
}

// 更新工具调用状态
function updateToolCall(toolName, status, result) {
    const toolCalls = document.querySelectorAll('.tool-call');
    for (const toolCall of toolCalls) {
        if (toolCall.dataset.toolName === toolName) {
            const statusEl = toolCall.querySelector('.tool-call-status');
            if (statusEl) {
                statusEl.textContent = '已完成';
                statusEl.className = 'tool-call-status completed';
            }
            break;
        }
    }
}

// 添加 Notion 链接展示
function addNotionLink(title, url) {
    const lastMessage = elements.messagesContainer.lastElementChild;
    if (!lastMessage || !lastMessage.classList.contains('assistant')) return;

    const linkDiv = document.createElement('div');
    linkDiv.className = 'notion-link-display';
    linkDiv.innerHTML = `
        <div class="notion-link-header">
            <svg width="20" height="20" fill="currentColor" viewBox="0 0 20 20">
                <path d="M9 4.804A7.968 7.968 0 005.5 4c-1.255 0-2.443.29-3.5.804v10A7.969 7.969 0 015.5 14c1.669 0 3.218.51 4.5 1.385A7.962 7.962 0 0114.5 14c1.255 0 2.443.29 3.5.804v-10A7.968 7.968 0 0014.5 4c-1.255 0-2.443.29-3.5.804V12a1 1 0 11-2 0V4.804z"/>
            </svg>
            已保存到 Notion
        </div>
        <div class="notion-link-title">${title}</div>
        <a href="${url}" target="_blank" class="notion-link-btn">
            <svg width="16" height="16" fill="currentColor" viewBox="0 0 20 20">
                <path d="M11 3a1 1 0 100 2h2.586l-6.293 6.293a1 1 0 101.414 1.414L15 6.414V9a1 1 0 102 0V4a1 1 0 00-1-1h-5z"/>
                <path d="M5 5a2 2 0 00-2 2v8a2 2 0 002 2h8a2 2 0 002-2v-3a1 1 0 10-2 0v3H5V7h3a1 1 0 000-2H5z"/>
            </svg>
            在 Notion 中打开
        </a>
    `;

    lastMessage.querySelector('.message-content').appendChild(linkDiv);
    scrollToBottom();
}

// 工具名称显示
function getToolDisplayName(toolName) {
    const names = {
        'search_arxiv_pdf': '搜索 arXiv 论文',
        'download_pdf': '下载 PDF',
        'extract_pdf_text': '提取 PDF 文本',
        'extract_images': '提取图片',
        'fetch_xiaohongshu_post': '获取小红书内容',
        'create_notion_page': '创建 Notion 页面',
        'extract_paper_info': '提取论文信息'
    };
    return names[toolName] || toolName;
}

// 格式化工具参数
function formatToolArgs(toolName, args) {
    if (typeof args === 'string') return args;
    if (args.url) return `URL: ${args.url}`;
    if (args.query) return `查询: ${args.query}`;
    return JSON.stringify(args);
}

// 滚动到底部
function scrollToBottom() {
    setTimeout(() => {
        elements.messagesContainer.scrollTop = elements.messagesContainer.scrollHeight;
    }, 100);
}

// 新对话
function newChat() {
    state.messages = [];
    elements.messagesContainer.innerHTML = '';

    // 重新添加欢迎消息
    const welcomeDiv = document.createElement('div');
    welcomeDiv.id = 'welcome-message';
    welcomeDiv.className = 'welcome-message';
    welcomeDiv.innerHTML = `
        <div class="welcome-icon">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                <rect width="48" height="48" rx="8" fill="url(#gradient2)"/>
                <path d="M12 10h24v5h-24zm0 10h24v5h-24zm0 10h16v5h-16z" fill="white"/>
                <defs>
                    <linearGradient id="gradient2" x1="0" y1="0" x2="48" y2="48">
                        <stop offset="0%" stop-color="#667eea"/>
                        <stop offset="100%" stop-color="#764ba2"/>
                    </linearGradient>
                </defs>
            </svg>
        </div>
        <h2>开始使用 Paper Digest</h2>
        <p>我可以帮你整理论文和小红书笔记，并自动保存到 Notion</p>

        <div class="usage-tips">
            <div class="tip-item">
                <svg width="20" height="20" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"/>
                </svg>
                <div class="tip-content">
                    <strong>支持多种链接</strong>
                    <span>arXiv 论文、PDF 直链、小红书笔记</span>
                </div>
            </div>
            <div class="tip-item">
                <svg width="20" height="20" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M7 3a1 1 0 000 2h6a1 1 0 100-2H7zM4 7a1 1 0 011-1h10a1 1 0 110 2H5a1 1 0 01-1-1zM2 11a2 2 0 012-2h12a2 2 0 012 2v4a2 2 0 01-2 2H4a2 2 0 01-2-2v-4z"/>
                </svg>
                <div class="tip-content">
                    <strong>批量处理</strong>
                    <span>一次可以输入多个链接，用换行或空格分隔</span>
                </div>
            </div>
            <div class="tip-item">
                <svg width="20" height="20" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M9 4.804A7.968 7.968 0 005.5 4c-1.255 0-2.443.29-3.5.804v10A7.969 7.969 0 015.5 14c1.669 0 3.218.51 4.5 1.385A7.962 7.962 0 0114.5 14c1.255 0 2.443.29 3.5.804v-10A7.968 7.968 0 0014.5 4c-1.255 0-2.443.29-3.5.804V12a1 1 0 11-2 0V4.804z"/>
                </svg>
                <div class="tip-content">
                    <strong>自动保存</strong>
                    <span>整理完成后自动保存到你的 Notion 数据库</span>
                </div>
            </div>
        </div>
    `;

    elements.messagesContainer.appendChild(welcomeDiv);
    elements.welcomeMessage = welcomeDiv;

    elements.messageInput.value = '';
    elements.messageInput.focus();
}
