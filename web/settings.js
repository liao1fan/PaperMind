// 设置页面的 JavaScript

// 认证检查
function getAuthToken() {
    return localStorage.getItem('token');
}

function checkAuthentication() {
    const token = getAuthToken();
    if (!token) {
        window.location.href = '/login';
        return false;
    }
    return true;
}

// 获取 API 请求头
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

// LocalStorage 键名
const STORAGE_KEYS = {
    NOTION_INTEGRATION_SECRET: 'user_notion_integration_secret',
    NOTION_DATABASE_ID: 'user_notion_database_id'
};

// 页面元素
const elements = {
    form: document.getElementById('settings-form'),
    notionIntegrationSecret: document.getElementById('notion-integration-secret'),
    notionDatabaseId: document.getElementById('notion-database-id'),
    saveButton: document.getElementById('save-button'),
    testButton: document.getElementById('test-button'),
    statusMessage: document.getElementById('status-message'),
    secretSource: document.getElementById('secret-source'),
    databaseSource: document.getElementById('database-source'),
    databaseFields: document.getElementById('database-fields'),
    fieldsGrid: document.getElementById('fields-grid')
};

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    // 检查认证
    if (!checkAuthentication()) {
        return;
    }

    // 加载已保存的设置
    loadSettings();

    // 绑定事件
    elements.form.addEventListener('submit', handleSave);
    elements.testButton.addEventListener('click', handleTest);
});

// 加载设置
function loadSettings() {
    const savedSecret = localStorage.getItem(STORAGE_KEYS.NOTION_INTEGRATION_SECRET);
    const savedDatabaseId = localStorage.getItem(STORAGE_KEYS.NOTION_DATABASE_ID);

    if (savedSecret) {
        elements.notionIntegrationSecret.value = savedSecret;
        showSourceBadge(elements.secretSource, 'user');
    } else {
        showSourceBadge(elements.secretSource, 'env');
    }

    if (savedDatabaseId) {
        elements.notionDatabaseId.value = savedDatabaseId;
        showSourceBadge(elements.databaseSource, 'user');
    } else {
        showSourceBadge(elements.databaseSource, 'env');
    }
}

// 显示来源标签
function showSourceBadge(element, source) {
    element.style.display = 'inline-block';
    if (source === 'user') {
        element.textContent = '用户配置';
        element.className = 'env-source from-user';
    } else {
        element.textContent = '默认配置';
        element.className = 'env-source from-env';
    }
}

// 保存设置
async function handleSave(e) {
    e.preventDefault();

    const notionIntegrationSecret = elements.notionIntegrationSecret.value.trim();
    const notionDatabaseId = elements.notionDatabaseId.value.trim();

    // 简单验证
    if (notionIntegrationSecret && !notionIntegrationSecret.startsWith('ntn_')) {
        showStatus('error', 'Notion Integration Secret 格式不正确，应以 "ntn_" 开头');
        return;
    }

    if (notionDatabaseId && notionDatabaseId.length !== 32) {
        showStatus('error', 'Database ID 格式不正确，应为 32 位字符串');
        return;
    }

    // 保存到 localStorage
    if (notionIntegrationSecret) {
        localStorage.setItem(STORAGE_KEYS.NOTION_INTEGRATION_SECRET, notionIntegrationSecret);
        showSourceBadge(elements.secretSource, 'user');
    } else {
        localStorage.removeItem(STORAGE_KEYS.NOTION_INTEGRATION_SECRET);
        showSourceBadge(elements.secretSource, 'env');
    }

    if (notionDatabaseId) {
        localStorage.setItem(STORAGE_KEYS.NOTION_DATABASE_ID, notionDatabaseId);
        showSourceBadge(elements.databaseSource, 'user');
    } else {
        localStorage.removeItem(STORAGE_KEYS.NOTION_DATABASE_ID);
        showSourceBadge(elements.databaseSource, 'env');
    }

    showStatus('success', '设置已保存！下次处理论文时将使用新的配置。');
}

// 测试连接
async function handleTest(e) {
    e.preventDefault();

    const notionIntegrationSecret = elements.notionIntegrationSecret.value.trim() || localStorage.getItem(STORAGE_KEYS.NOTION_INTEGRATION_SECRET);
    const notionDatabaseId = elements.notionDatabaseId.value.trim() || localStorage.getItem(STORAGE_KEYS.NOTION_DATABASE_ID);

    if (!notionIntegrationSecret || !notionDatabaseId) {
        showStatus('error', '请填写 Integration Secret 和 Database ID，或使用默认配置');
        return;
    }

    // 禁用按钮，显示加载状态
    elements.testButton.disabled = true;
    elements.testButton.innerHTML = `
        <div class="loading-spinner"></div>
        测试中...
    `;

    try {
        const response = await fetch('/api/test-notion-connection', {
            method: 'POST',
            headers: getApiHeaders(),
            body: JSON.stringify({
                notion_integration_secret: notionIntegrationSecret,
                notion_database_id: notionDatabaseId
            })
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showStatus('success', `连接成功！Database: ${result.database_title || '未命名'}`);

            // 显示数据库字段
            if (result.fields && result.fields.length > 0) {
                displayDatabaseFields(result.fields);
            }

            // 自动初始化数据库字段（添加缺失的字段）
            await initializeDatabaseFields(notionIntegrationSecret, notionDatabaseId);
        } else {
            showStatus('error', `连接失败: ${result.error || '未知错误'}`);
            // 隐藏字段列表
            elements.databaseFields.style.display = 'none';
        }
    } catch (error) {
        showStatus('error', `测试失败: ${error.message}`);
    } finally {
        // 恢复按钮
        elements.testButton.disabled = false;
        elements.testButton.innerHTML = `
            <svg width="16" height="16" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"/>
            </svg>
            测试连接
        `;
    }
}

// 显示状态消息
function showStatus(type, message) {
    elements.statusMessage.className = `status-message ${type}`;
    elements.statusMessage.textContent = message;
    elements.statusMessage.style.display = 'block';

    // 3秒后自动隐藏（成功消息）
    if (type === 'success') {
        setTimeout(() => {
            elements.statusMessage.style.display = 'none';
        }, 3000);
    }
}

// 初始化数据库字段（添加缺失的字段）
async function initializeDatabaseFields(notionIntegrationSecret, notionDatabaseId) {
    try {
        showStatus('info', '正在初始化数据库字段...');

        const response = await fetch('/api/initialize-notion-database', {
            method: 'POST',
            headers: getApiHeaders(),
            body: JSON.stringify({
                notion_integration_secret: notionIntegrationSecret,
                notion_database_id: notionDatabaseId
            })
        });

        const result = await response.json();

        if (response.ok && result.success) {
            if (result.added_fields && result.added_fields.length > 0) {
                showStatus('success', `✅ 成功添加 ${result.added_fields.length} 个字段: ${result.added_fields.join(', ')}`);

                // 重新获取字段列表并显示
                const testResponse = await fetch('/api/test-notion-connection', {
                    method: 'POST',
                    headers: getApiHeaders(),
                    body: JSON.stringify({
                        notion_integration_secret: notionIntegrationSecret,
                        notion_database_id: notionDatabaseId
                    })
                });

                const testResult = await testResponse.json();
                if (testResult.success && testResult.fields) {
                    displayDatabaseFields(testResult.fields);
                }
            } else {
                showStatus('info', '所有必需字段已存在，无需添加');
            }
        } else {
            showStatus('error', `字段初始化失败: ${result.error || '未知错误'}`);
        }
    } catch (error) {
        showStatus('error', `初始化失败: ${error.message}`);
    }
}

// 显示数据库字段
function displayDatabaseFields(fields) {
    // 清空现有内容
    elements.fieldsGrid.innerHTML = '';

    // 字段类型的中文映射和图标
    const fieldTypeMap = {
        'title': { name: '标题', icon: '📝' },
        'rich_text': { name: '富文本', icon: '📄' },
        'number': { name: '数字', icon: '🔢' },
        'select': { name: '单选', icon: '🎯' },
        'multi_select': { name: '多选', icon: '🏷️' },
        'date': { name: '日期', icon: '📅' },
        'people': { name: '人员', icon: '👤' },
        'files': { name: '文件', icon: '📎' },
        'checkbox': { name: '复选框', icon: '☑️' },
        'url': { name: 'URL', icon: '🔗' },
        'email': { name: '邮箱', icon: '📧' },
        'phone_number': { name: '电话', icon: '📞' },
        'formula': { name: '公式', icon: '🧮' },
        'relation': { name: '关联', icon: '🔗' },
        'rollup': { name: '汇总', icon: '📊' },
        'created_time': { name: '创建时间', icon: '🕐' },
        'created_by': { name: '创建者', icon: '👤' },
        'last_edited_time': { name: '编辑时间', icon: '🕐' },
        'last_edited_by': { name: '编辑者', icon: '👤' }
    };

    // 为每个字段创建卡片
    fields.forEach(field => {
        const fieldInfo = fieldTypeMap[field.type] || { name: field.type, icon: '❓' };

        const fieldCard = document.createElement('div');
        fieldCard.className = 'field-card';
        fieldCard.innerHTML = `
            <div class="field-icon">${fieldInfo.icon}</div>
            <div class="field-info">
                <div class="field-name">${field.name}</div>
                <div class="field-type">${fieldInfo.name}</div>
            </div>
        `;

        elements.fieldsGrid.appendChild(fieldCard);
    });

    // 显示字段区域
    elements.databaseFields.style.display = 'block';
}

// 导出函数供其他页面使用
window.NotionSettings = {
    getIntegrationSecret: () => localStorage.getItem(STORAGE_KEYS.NOTION_INTEGRATION_SECRET),
    getDatabaseId: () => localStorage.getItem(STORAGE_KEYS.NOTION_DATABASE_ID),
    hasUserSettings: () => {
        return !!(localStorage.getItem(STORAGE_KEYS.NOTION_INTEGRATION_SECRET) ||
                  localStorage.getItem(STORAGE_KEYS.NOTION_DATABASE_ID));
    }
};
