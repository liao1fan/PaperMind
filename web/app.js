// 生成唯一的 session ID
function generateSessionId() {
    return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

// 获取或创建当前 session ID
function getSessionId() {
    let sessionId = localStorage.getItem('current_session_id');
    if (!sessionId) {
        sessionId = generateSessionId();
        localStorage.setItem('current_session_id', sessionId);
    }
    return sessionId;
}

// 应用状态
const state = {
    processing: false,
    ws: null,
    messages: [],
    token: null,
    sessionId: getSessionId(),
    conversations: []  // 会话列表
};

// ============= 会话列表管理 =============

// 加载会话列表
function loadConversationList() {
    try {
        const data = localStorage.getItem('conversations');
        if (data) {
            state.conversations = JSON.parse(data);
        } else {
            state.conversations = [];
        }
        return state.conversations;
    } catch (error) {
        console.error('加载会话列表失败:', error);
        state.conversations = [];
        return [];
    }
}

// 保存会话列表
function saveConversationList() {
    try {
        localStorage.setItem('conversations', JSON.stringify(state.conversations));
    } catch (error) {
        console.error('保存会话列表失败:', error);
    }
}

// 生成会话标题（从第一条消息生成）
function generateConversationTitle(firstMessage) {
    if (!firstMessage) return '新对话';

    // 截取前30个字符作为标题
    const title = firstMessage.trim().substring(0, 30);
    return title + (firstMessage.length > 30 ? '...' : '');
}

// 添加会话到列表
function addConversationToList(sessionId, title = '新对话', preview = '') {
    const existingIndex = state.conversations.findIndex(c => c.id === sessionId);

    if (existingIndex === -1) {
        // 新会话
        const conversation = {
            id: sessionId,
            title: title,
            preview: preview,
            timestamp: Date.now(),
            lastMessageTime: Date.now()
        };

        // 添加到列表开头
        state.conversations.unshift(conversation);
    } else {
        // 更新现有会话
        state.conversations[existingIndex].title = title;
        state.conversations[existingIndex].preview = preview;
        state.conversations[existingIndex].lastMessageTime = Date.now();

        // 移到列表开头
        const conversation = state.conversations.splice(existingIndex, 1)[0];
        state.conversations.unshift(conversation);
    }

    saveConversationList();
    renderConversationList();
}

// 更新会话信息
function updateConversationInList(sessionId, updates) {
    const index = state.conversations.findIndex(c => c.id === sessionId);
    if (index !== -1) {
        Object.assign(state.conversations[index], updates);
        state.conversations[index].lastMessageTime = Date.now();
        saveConversationList();
        renderConversationList();
    }
}

// 删除会话
function deleteConversation(sessionId, event) {
    if (event) {
        event.stopPropagation();
    }

    // 确认删除
    if (!confirm('确定要删除这个会话吗？')) {
        return;
    }

    // 从列表中删除
    state.conversations = state.conversations.filter(c => c.id !== sessionId);
    saveConversationList();

    // 删除会话的消息
    localStorage.removeItem(`chat_messages_${sessionId}`);

    // 如果删除的是当前会话，创建新会话
    if (state.sessionId === sessionId) {
        newChat();
    } else {
        renderConversationList();
    }
}

// 编辑会话标题（内联编辑）
function editConversationTitle(sessionId, event) {
    if (event) {
        event.stopPropagation();
    }

    const conversation = state.conversations.find(c => c.id === sessionId);
    if (!conversation) return;

    // 找到标题元素
    const titleElement = event.target.closest('.chat-history-item').querySelector('.chat-history-item-title');
    if (!titleElement) return;

    // 保存原始标题
    const originalTitle = conversation.title;

    // 创建输入框
    const input = document.createElement('input');
    input.type = 'text';
    input.value = originalTitle;
    input.className = 'chat-history-item-title-input';

    // 替换标题为输入框
    titleElement.style.display = 'none';
    titleElement.parentElement.insertBefore(input, titleElement);

    // 聚焦并选中文本
    input.focus();
    input.select();

    // 保存编辑
    const saveEdit = () => {
        const newTitle = input.value.trim();

        if (newTitle && newTitle !== originalTitle) {
            conversation.title = newTitle;
            conversation.lastMessageTime = Date.now();
            saveConversationList();
        }

        // 恢复标题显示
        titleElement.textContent = conversation.title;
        titleElement.style.display = '';
        input.remove();
    };

    // 取消编辑
    const cancelEdit = () => {
        titleElement.style.display = '';
        input.remove();
    };

    // 监听事件
    input.addEventListener('blur', saveEdit);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            saveEdit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancelEdit();
        }
    });

    // 阻止点击输入框时触发会话切换
    input.addEventListener('click', (e) => {
        e.stopPropagation();
    });
}

// 切换会话
async function switchConversation(sessionId) {
    if (state.sessionId === sessionId) {
        return; // 已经是当前会话
    }

    // 保存当前会话的消息
    if (state.messages.length > 0) {
        saveMessagesToStorage();
    }

    // 切换到新会话
    state.sessionId = sessionId;
    localStorage.setItem('current_session_id', sessionId);

    // 清空当前消息显示
    state.messages = [];
    elements.messagesContainer.innerHTML = '';

    // 加载新会话的消息
    loadMessagesFromStorage();

    console.log(`[DEBUG] loadMessagesFromStorage 执行完毕`);
    console.log(`[DEBUG] state.messages:`, state.messages);
    console.log(`[DEBUG] localStorage 原始数据:`, localStorage.getItem(`chat_messages_${sessionId}`));

    // 如果没有消息，显示欢迎消息
    if (state.messages.length === 0) {
        showWelcomeMessage();
    }

    // 通知后端切换会话并恢复历史上下文
    console.log(`[DEBUG] 切换到会话: ${sessionId}`);
    console.log(`[DEBUG] 历史消息数量: ${state.messages.length}`);
    console.log(`[DEBUG] 历史消息内容:`, state.messages);

    try {
        const response = await fetch('/api/restore-session', {
            method: 'POST',
            headers: getApiHeaders(),
            body: JSON.stringify({
                session_id: sessionId,
                messages: state.messages  // 发送历史消息给后端
            })
        });

        const result = await response.json();
        console.log(`[DEBUG] 后端恢复会话响应:`, result);
    } catch (error) {
        console.error('切换会话失败:', error);
    }

    // 更新 UI
    renderConversationList();
    elements.messageInput.focus();
}

// 显示欢迎消息
function showWelcomeMessage() {
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
                    <span>arXiv 论文、PDF 直链、小红书笔记、学术期刊网站</span>
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
}

// 渲染会话列表
function renderConversationList() {
    if (!elements.chatHistory) return;

    // 清空现有列表
    elements.chatHistory.innerHTML = '';

    if (state.conversations.length === 0) {
        // 显示空状态
        const emptyDiv = document.createElement('div');
        emptyDiv.className = 'chat-history-empty';
        emptyDiv.textContent = '暂无会话历史';
        elements.chatHistory.appendChild(emptyDiv);
        return;
    }

    // 渲染每个会话
    state.conversations.forEach(conversation => {
        const itemDiv = document.createElement('div');
        itemDiv.className = 'chat-history-item';

        // 标记当前活动的会话
        if (conversation.id === state.sessionId) {
            itemDiv.classList.add('active');
        }

        // 格式化时间
        const date = new Date(conversation.lastMessageTime);
        const timeStr = formatTimestamp(date);

        itemDiv.innerHTML = `
            <div class="chat-history-item-content">
                <div class="chat-history-item-title">${conversation.title}</div>
                <div class="chat-history-item-time">${timeStr}</div>
            </div>
            <div class="chat-history-item-actions">
                <button class="chat-history-item-edit" title="重命名">
                    <svg width="16" height="16" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/>
                    </svg>
                </button>
                <button class="chat-history-item-delete" title="删除会话">
                    <svg width="16" height="16" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z"/>
                    </svg>
                </button>
            </div>
        `;

        // 点击会话项切换会话
        itemDiv.querySelector('.chat-history-item-content').addEventListener('click', () => {
            switchConversation(conversation.id);
        });

        // 点击编辑按钮
        itemDiv.querySelector('.chat-history-item-edit').addEventListener('click', (e) => {
            editConversationTitle(conversation.id, e);
        });

        // 点击删除按钮
        itemDiv.querySelector('.chat-history-item-delete').addEventListener('click', (e) => {
            deleteConversation(conversation.id, e);
        });

        elements.chatHistory.appendChild(itemDiv);
    });
}

// 格式化时间戳
function formatTimestamp(date) {
    const now = new Date();
    const diff = now - date;

    // 今天
    if (diff < 24 * 60 * 60 * 1000 && now.getDate() === date.getDate()) {
        return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    }

    // 昨天
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (date.getDate() === yesterday.getDate()) {
        return '昨天';
    }

    // 一周内
    if (diff < 7 * 24 * 60 * 60 * 1000) {
        const days = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
        return days[date.getDay()];
    }

    // 更早
    return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

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
    stopBtn: document.getElementById('stop-btn'),
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

// 保存消息到 localStorage（使用 session-specific key）
function saveMessagesToStorage() {
    try {
        // 保存完整的DOM内容
        const messagesHTML = elements.messagesContainer.innerHTML;

        const messagesData = {
            sessionId: state.sessionId,
            messages: state.messages,
            messagesHTML: messagesHTML,  // 保存完整的HTML内容
            timestamp: Date.now()
        };
        // 使用 session-specific key
        localStorage.setItem(`chat_messages_${state.sessionId}`, JSON.stringify(messagesData));
    } catch (error) {
        console.error('保存消息失败:', error);
    }
}

// 从 localStorage 恢复消息（使用 session-specific key）
function loadMessagesFromStorage() {
    try {
        // 使用 session-specific key
        const data = localStorage.getItem(`chat_messages_${state.sessionId}`);
        if (!data) {
            state.messages = [];
            return;
        }

        const messagesData = JSON.parse(data);

        // 恢复消息状态
        state.messages = messagesData.messages || [];

        // 恢复 DOM 显示 - 直接使用保存的HTML
        if (messagesData.messagesHTML) {
            // 隐藏欢迎消息
            if (elements.welcomeMessage) {
                elements.welcomeMessage.classList.add('hidden');
            }

            // 直接设置HTML内容,保留所有log、tool call、notion link等
            elements.messagesContainer.innerHTML = messagesData.messagesHTML;

            // 滚动到底部
            scrollToBottom();
        } else if (state.messages.length > 0) {
            // 兼容旧数据格式 - 只有纯文本消息
            if (elements.welcomeMessage) {
                elements.welcomeMessage.classList.add('hidden');
            }

            state.messages.forEach(msg => {
                renderMessage(msg.role, msg.content);
            });

            // 滚动到底部
            scrollToBottom();
        }
    } catch (error) {
        console.error('加载消息失败:', error);
        state.messages = [];
    }
}

// 渲染单条消息到 DOM（不保存到 state.messages）
function renderMessage(role, content) {
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
    scrollToBottom();

    return messageDiv;
}

// 初始化
document.addEventListener('DOMContentLoaded', async () => {
    const perfStart = performance.now();
    console.log('[性能] 页面DOM加载完成，开始初始化');

    // 检查认证状态
    checkAuthentication();
    console.log(`[性能] checkAuthentication 耗时: ${(performance.now() - perfStart).toFixed(2)}ms`);

    // 初始化用户信息
    const infoStart = performance.now();
    initUserInfo();
    console.log(`[性能] initUserInfo 耗时: ${(performance.now() - infoStart).toFixed(2)}ms`);

    // 加载会话列表
    const loadStart = performance.now();
    loadConversationList();
    console.log(`[性能] loadConversationList 耗时: ${(performance.now() - loadStart).toFixed(2)}ms`);

    // 渲染会话列表
    const renderStart = performance.now();
    renderConversationList();
    console.log(`[性能] renderConversationList 耗时: ${(performance.now() - renderStart).toFixed(2)}ms`);

    // 恢复之前的消息
    const msgStart = performance.now();
    loadMessagesFromStorage();
    console.log(`[性能] loadMessagesFromStorage 耗时: ${(performance.now() - msgStart).toFixed(2)}ms`);

    // 确保当前会话在列表中
    const currentConversation = state.conversations.find(c => c.id === state.sessionId);
    if (!currentConversation && state.messages.length === 0) {
        // 如果当前会话不在列表中，且没有消息，则添加到列表
        addConversationToList(state.sessionId, '新对话', '');
    }

    // 绑定事件
    elements.sendBtn.addEventListener('click', handleSend);
    elements.stopBtn.addEventListener('click', handleStop);
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
    const wsStart = performance.now();
    console.log('[性能] 开始建立WebSocket连接...');
    await connectWebSocket();
    console.log(`[性能] WebSocket连接耗时: ${(performance.now() - wsStart).toFixed(2)}ms`);

    // 获取模型信息
    const modelStart = performance.now();
    console.log('[性能] 开始获取模型信息...');
    await fetchModelInfo();
    console.log(`[性能] 获取模型信息耗时: ${(performance.now() - modelStart).toFixed(2)}ms`);

    const totalTime = performance.now() - perfStart;
    console.log(`[性能] ===== 页面初始化总耗时: ${totalTime.toFixed(2)}ms =====`);

    // 将性能数据发送到后端日志
    try {
        await fetch('/api/performance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                page: 'index',
                metrics: {
                    '检查认证耗时': `${(performance.now() - perfStart).toFixed(2)}ms`,
                    '初始化用户信息耗时': `${(performance.now() - infoStart).toFixed(2)}ms`,
                    '加载会话列表耗时': `${(performance.now() - loadStart).toFixed(2)}ms`,
                    '渲染会话列表耗时': `${(performance.now() - renderStart).toFixed(2)}ms`,
                    '恢复消息耗时': `${(performance.now() - msgStart).toFixed(2)}ms`,
                    'WebSocket连接耗时': `${(performance.now() - wsStart).toFixed(2)}ms`,
                    '获取模型信息耗时': `${(performance.now() - modelStart).toFixed(2)}ms`,
                    '总初始化耗时': `${totalTime.toFixed(2)}ms`
                }
            })
        });
    } catch (error) {
        console.error('发送性能日志失败:', error);
    }
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

            // 切换按钮显示：显示发送按钮，隐藏停止按钮
            elements.sendBtn.classList.remove('hidden');
            elements.stopBtn.classList.add('hidden');

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

// 处理停止按钮
async function handleStop() {
    if (!state.processing) return;

    console.log('用户请求停止处理');

    // 立即更新UI状态
    state.processing = false;
    removeTypingIndicator();

    // 切换按钮显示
    elements.stopBtn.classList.add('hidden');
    elements.sendBtn.classList.remove('hidden');

    // 重新启用输入
    elements.sendBtn.disabled = false;
    elements.messageInput.disabled = false;
    elements.messageInput.focus();

    // 添加提示消息
    addMessage('assistant', '已停止处理。');

    // 通知后端取消任务（可选）
    try {
        await fetch('/api/cancel-chat', {
            method: 'POST',
            headers: getApiHeaders(),
            body: JSON.stringify({
                session_id: state.sessionId
            })
        });
    } catch (error) {
        console.error('通知后端取消任务失败:', error);
    }
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
    elements.messageInput.disabled = true;

    // 切换按钮显示：隐藏发送按钮，显示停止按钮
    elements.sendBtn.classList.add('hidden');
    elements.stopBtn.classList.remove('hidden');

    // 显示输入中状态
    state.processing = true;
    addTypingIndicator();

    try {
        // 获取用户配置的 Notion 环境变量（如果有）
        const notionIntegrationSecret = localStorage.getItem('user_notion_integration_secret');
        const notionDatabaseId = localStorage.getItem('user_notion_database_id');

        // 构建请求体
        const requestBody = {
            message,
            session_id: state.sessionId,  // 传递 session_id
            history: state.messages  // 传递完整的历史上下文，确保后端有最新的会话信息
        };
        if (notionIntegrationSecret) {
            requestBody.notion_integration_secret = notionIntegrationSecret;
        }
        if (notionDatabaseId) {
            requestBody.notion_database_id = notionDatabaseId;
        }

        // 发送请求到后端
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: getApiHeaders(),
            body: JSON.stringify(requestBody)
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

        // 切换按钮显示：显示发送按钮，隐藏停止按钮
        elements.sendBtn.classList.remove('hidden');
        elements.stopBtn.classList.add('hidden');

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

        // 保存消息状态（包含log信息）
        saveMessagesToStorage();
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
            saveMessagesToStorage();

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
    saveMessagesToStorage();

    // 如果是第一条用户消息，更新会话标题
    if (role === 'user' && state.messages.filter(m => m.role === 'user').length === 1) {
        const title = generateConversationTitle(content);
        const preview = content.substring(0, 50);
        addConversationToList(state.sessionId, title, preview);
    }

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

    // 保存消息状态（包含tool call信息）
    saveMessagesToStorage();
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

    // 保存消息状态（更新tool call状态）
    saveMessagesToStorage();
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

    // 保存消息状态（包含Notion link信息）
    saveMessagesToStorage();
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
async function newChat() {
    // 生成新的 session ID
    const newSessionId = generateSessionId();
    state.sessionId = newSessionId;
    localStorage.setItem('current_session_id', newSessionId);

    // 清空消息
    state.messages = [];
    elements.messagesContainer.innerHTML = '';

    // 添加新会话到列表
    addConversationToList(newSessionId, '新对话', '');

    // 通知后端重置会话
    try {
        await fetch('/api/reset-session', {
            method: 'POST',
            headers: getApiHeaders(),
            body: JSON.stringify({ session_id: newSessionId })
        });
    } catch (error) {
        console.error('重置会话失败:', error);
    }

    // 显示欢迎消息
    showWelcomeMessage();

    elements.messageInput.value = '';
    elements.messageInput.focus();
}
