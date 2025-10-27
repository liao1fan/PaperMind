/**
 * 前端登录逻辑
 */

// DOM 元素
const loginForm = document.getElementById('loginForm');
const registerForm = document.getElementById('registerForm');
const toggleLink = document.getElementById('toggleLink');
const toggleText = document.getElementById('toggleText');

const loginUsername = document.getElementById('loginUsername');
const loginPassword = document.getElementById('loginPassword');
const loginBtn = document.getElementById('loginBtn');
const loginError = document.getElementById('loginError');

const registerUsername = document.getElementById('registerUsername');
const registerPassword = document.getElementById('registerPassword');
const registerPasswordConfirm = document.getElementById('registerPasswordConfirm');
const registerBtn = document.getElementById('registerBtn');
const registerError = document.getElementById('registerError');
const registerSuccess = document.getElementById('registerSuccess');

// 当前显示的表单
let isLoginMode = true;

// ============= 表单切换 =============

toggleLink.addEventListener('click', () => {
    isLoginMode = !isLoginMode;

    if (isLoginMode) {
        loginForm.classList.remove('hidden');
        registerForm.classList.add('hidden');
        toggleText.textContent = '还没有账户？';
        toggleLink.textContent = '立即注册';
    } else {
        loginForm.classList.add('hidden');
        registerForm.classList.remove('hidden');
        toggleText.textContent = '已有账户？';
        toggleLink.textContent = '立即登录';
    }

    // 清空错误信息
    hideError(loginError);
    hideError(registerError);
    hideSuccess(registerSuccess);
});

// ============= 登录逻辑 =============

loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const username = loginUsername.value.trim();
    const password = loginPassword.value;

    if (!username || !password) {
        showError(loginError, '请输入用户名和密码');
        return;
    }

    // 禁用按钮
    loginBtn.disabled = true;
    const originalText = loginBtn.textContent;
    loginBtn.innerHTML = '<span class="loading"></span> 正在登录...';

    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                username: username,
                password: password,
            }),
        });

        const data = await response.json();

        if (response.ok && data.success) {
            // 保存 Token 到 localStorage
            localStorage.setItem('token', data.token);
            localStorage.setItem('username', data.username);
            localStorage.setItem('user_id', data.user_id);

            showSuccess(loginError, data.message);

            // 2秒后跳转到主页
            setTimeout(() => {
                window.location.href = '/';
            }, 1000);
        } else {
            showError(loginError, data.detail || '登录失败，请检查用户名和密码');
        }
    } catch (error) {
        console.error('登录错误:', error);
        showError(loginError, '网络错误，请重试');
    } finally {
        loginBtn.disabled = false;
        loginBtn.textContent = originalText;
    }
});

// ============= 注册逻辑 =============

registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const username = registerUsername.value.trim();
    const password = registerPassword.value;
    const passwordConfirm = registerPasswordConfirm.value;

    // 验证输入
    if (!username || !password || !passwordConfirm) {
        showError(registerError, '请填写所有字段');
        return;
    }

    if (username.length < 3 || username.length > 20) {
        showError(registerError, '用户名长度必须 3-20 位');
        return;
    }

    if (!/^[a-zA-Z0-9]+$/.test(username)) {
        showError(registerError, '用户名只能包含字母和数字');
        return;
    }

    if (password.length < 6) {
        showError(registerError, '密码长度至少 6 位');
        return;
    }

    if (password !== passwordConfirm) {
        showError(registerError, '两次输入的密码不一致');
        return;
    }

    // 禁用按钮
    registerBtn.disabled = true;
    const originalText = registerBtn.textContent;
    registerBtn.innerHTML = '<span class="loading"></span> 正在注册...';

    try {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                username: username,
                password: password,
            }),
        });

        const data = await response.json();

        if (response.ok && data.success) {
            // 保存 Token 到 localStorage
            localStorage.setItem('token', data.token);
            localStorage.setItem('username', data.username);
            localStorage.setItem('user_id', data.user_id);

            showSuccess(registerSuccess, '注册成功！正在跳转...');

            // 2秒后跳转到主页
            setTimeout(() => {
                window.location.href = '/';
            }, 1000);
        } else {
            showError(registerError, data.detail || '注册失败，请重试');
        }
    } catch (error) {
        console.error('注册错误:', error);
        showError(registerError, '网络错误，请重试');
    } finally {
        registerBtn.disabled = false;
        registerBtn.textContent = originalText;
    }
});

// ============= 辅助函数 =============

function showError(element, message) {
    element.textContent = message;
    element.classList.add('show');
}

function hideError(element) {
    element.classList.remove('show');
}

function showSuccess(element, message) {
    element.textContent = message;
    element.classList.add('show');
}

function hideSuccess(element) {
    element.classList.remove('show');
}

// ============= 页面加载时检查登录状态 =============

window.addEventListener('DOMContentLoaded', async () => {
    const token = localStorage.getItem('token');

    // 如果已登录，跳转到主页
    if (token) {
        try {
            const response = await fetch(`/api/auth/verify-token?token=${token}`);
            if (response.ok) {
                window.location.href = '/';
            } else {
                // Token 无效，删除
                localStorage.removeItem('token');
                localStorage.removeItem('username');
                localStorage.removeItem('user_id');
            }
        } catch (error) {
            console.error('验证 Token 错误:', error);
        }
    }
});
