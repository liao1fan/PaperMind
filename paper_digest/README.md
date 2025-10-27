# Paper Digest - 论文深度整理系统

## 功能说明

完全独立于主流程 `chat.py` 的论文深度整理系统。

### 核心功能

1. **从小红书获取论文信息**
2. **Web 搜索查找论文 PDF**（使用 Exa AI MCP Server）
3. **下载 PDF 到本地**
4. **生成结构化论文整理**（按照学术标准模板）
5. **保存到 Notion**（properties + 正文内容）

### 论文整理模板

整理结构包含：
- 📋 基本信息
- 📝 摘要
- 🎯 研究背景与动机
- 🔍 现有方法及其局限
- 💡 本文方法
- ⚙️ 方法实现细节
- 📊 实验与结果
- ⚠️ 局限性
- 🔮 未来方向
- 💭 个人思考

详见：[digest_template.md](./digest_template.md)

---

## 安装配置

### 1. 安装 Exa MCP Server

Exa 提供强大的 AI 搜索能力，可以查找论文 PDF。

```bash
# 无需安装，使用 npx 即可
# 第一次运行会自动下载
```

### 2. 获取 Exa API Key

1. 访问 https://exa.ai/
2. 注册账号（免费 $10 额度）
3. 获取 API Key
4. 添加到 `.env` 文件：

```bash
# 在项目根目录的 .env 文件中添加
EXA_API_KEY=your_exa_api_key_here
```

### 3. 安装 Python 依赖

```bash
# 在项目根目录执行
pip install httpx
```

---

## 使用方法

### 自动处理多篇论文

```bash
cd paper_digest
python digest_agent.py
```

程序会自动处理三篇小红书帖子，生成深度整理并保存到 Notion。

### 输出文件

- **PDFs**: `paper_digest/pdfs/` - 下载的 PDF 文件
- **整理输出**: `paper_digest/outputs/` - Markdown 格式的论文整理

---

## 工作流程

```
小红书URL
    ↓
1. 获取帖子内容 (fetch_xiaohongshu_post)
    ↓
2. 提取论文标题 (extract_paper_basic_info)
    ↓
3. Web 搜索 PDF (Exa MCP Server: exa_search)
    ↓
4. 下载 PDF (download_pdf)
    ↓
5. 生成论文整理 (generate_paper_digest)
    ↓
6. 保存到 Notion (save_digest_to_notion)
    ↓
完成！
```

---

## Notion 数据结构

### Properties（属性）

- **Name**: 论文标题
- **Source URL**: 小红书链接
- **PDF Link**: PDF 下载链接
- **Tags**: 标签（论文整理、深度分析）
- **Summary**: 摘要（前200字）

### Page Content（正文）

完整的论文整理内容，按照学术模板结构化组织。

---

## 技术栈

- **OpenAI Agents SDK**: Agent 框架
- **Exa MCP Server**: AI 驱动的 Web 搜索
- **Notion API**: 知识库存储
- **Xiaohongshu Client**: 小红书内容获取
- **GPT-4**: 论文整理生成

---

## 与主流程的区别

| 维度 | 主流程 (chat.py) | 论文整理 (digest_agent.py) |
|------|------------------|----------------------------|
| **定位** | 快速整理 | 深度分析 |
| **信息来源** | 仅小红书 | 小红书 + PDF 全文 |
| **输出结构** | 简单 properties | Properties + 完整正文 |
| **整理深度** | 基础信息 | 学术标准模板 |
| **PDF处理** | 仅链接 | 下载并分析 |
| **Web搜索** | 无 | Exa AI搜索 |
| **适用场景** | 批量收集 | 精读整理 |

---

## 故障排查

### 1. Exa MCP Server 连接失败

检查：
- EXA_API_KEY 是否正确配置
- 网络代理是否正常
- npx 是否可用

### 2. PDF 下载失败

检查：
- 代理配置（http_proxy）
- PDF 链接是否有效
- 磁盘空间是否足够

### 3. Notion 保存失败

检查：
- NOTION_TOKEN 权限
- NOTION_DATABASE_ID 是否正确
- 数据库 schema 是否匹配

---

## 开发说明

### 文件结构

```
paper_digest/
├── digest_agent.py      # 主程序
├── digest_template.md   # 论文整理模板
├── README.md           # 本文件
├── pdfs/               # PDF 存储目录
└── outputs/            # 整理输出目录
```

### 扩展功能

可以添加：
- PDF 文本提取（PyPDF2, pdfplumber）
- 图表提取
- 引用分析
- 多语言支持
- 批量处理界面

---

## 许可证

与主项目保持一致
