# Paper Notion Agent - Web 应用

一个简洁美观的 Web 应用，可以自动整理小红书笔记和 PDF 论文到 Notion。

## 功能特点

- 📝 支持小红书链接和 PDF 链接
- 🤖 AI 自动提取和整理内容
- 📊 实时进度显示（WebSocket）
- 💾 自动保存到 Notion 数据库
- 🎨 现代化、简洁的用户界面

## 快速开始

### 1. 启动服务器

在项目根目录运行：

```bash
python web_server.py
```

服务器将在 `http://localhost:8000` 启动。

### 2. 打开浏览器

访问 `http://localhost:8000`，你将看到主界面。

### 3. 输入链接

在输入框中粘贴：
- 小红书链接（例如：`https://www.xiaohongshu.com/explore/...`）
- PDF 链接（例如：`https://arxiv.org/pdf/...`）
- arXiv 链接（例如：`https://arxiv.org/abs/...`）

### 4. 开始整理

点击"开始整理"按钮，系统将：
1. 识别链接类型
2. 提取内容
3. AI 整理
4. 保存到 Notion

整个过程会实时显示进度。

## 技术架构

### 前端
- **HTML5** - 语义化结构
- **CSS3** - 现代渐变设计
- **Vanilla JavaScript** - 无框架依赖
- **WebSocket** - 实时通信

### 后端
- **FastAPI** - 高性能 Web 框架
- **WebSocket** - 实时进度推送
- **OpenAI Agents SDK** - AI 能力
- **Notion API** - 数据库集成

## 项目结构

```
web/
├── index.html          # 主页面
├── style.css           # 样式文件
├── app.js              # 前端逻辑
└── README.md           # 本文档

web_server.py           # FastAPI 服务器
```

## API 端点

### POST /api/digest
提交整理任务

**请求体：**
```json
{
  "url": "https://..."
}
```

**响应：**
```json
{
  "success": true,
  "message": "任务已提交，正在处理...",
  "task_id": null
}
```

### WebSocket /ws
实时进度推送

**消息类型：**
- `step` - 步骤开始
- `step_complete` - 步骤完成
- `log` - 日志信息
- `success` - 处理成功
- `error` - 处理失败

### GET /health
健康检查

**响应：**
```json
{
  "status": "healthy",
  "model_provider": "openai",
  "connections": 1
}
```

## 环境变量

确保设置以下环境变量：

```bash
# OpenAI 配置
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.openai.com/v1

# 或者 DeepSeek 配置
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com

# Notion 配置
NOTION_TOKEN=your_notion_token
NOTION_DATABASE_ID=your_database_id
```

## 浏览器兼容性

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## 常见问题

### 连接失败怎么办？
确保服务器正在运行，并检查浏览器控制台的错误信息。

### 处理速度慢？
- 检查网络连接
- 确认 API 配额充足
- 考虑使用更快的模型（gpt-5-mini）

### WebSocket 断开？
自动重连机制会在页面恢复时重新建立连接。

## 许可证

MIT License
