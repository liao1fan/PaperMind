"""
Web 服务器 - 为论文整理 Agent 提供 Web 界面
支持小红书和 PDF 链接的自动整理和 Notion 保存
"""

import asyncio
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional
import logging
from pathlib import Path

# 导入现有的 Agent 系统
from src.services.paper_digest import digest_agent, _init_digest_globals
from paper_agents import paper_agent, init_paper_agents
from agents import Runner
from init_model import init_models

# 导入认证路由和工具
from src.auth.routes import router as auth_router
from src.auth.conversation_routes import router as conversation_router
from src.auth.utils import TokenManager

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# URL 类型检测函数
def check_url_type(url: str) -> str:
    """检测 URL 类型"""
    url_lower = url.lower()

    if 'xiaohongshu.com' in url_lower or 'xhslink.com' in url_lower:
        return "xiaohongshu"
    elif 'arxiv.org' in url_lower:
        return "arxiv"
    elif url_lower.endswith('.pdf') or 'pdf' in url_lower:
        return "pdf"
    else:
        return "unknown"

# 初始化 FastAPI
app = FastAPI(title="Paper Notion Agent", description="自动整理论文和小红书笔记到 Notion")

# 包含认证和对话路由
app.include_router(auth_router)
app.include_router(conversation_router)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="web"), name="static")

# 初始化模型
logger.info("初始化模型...")
factory = init_models()
openai_client = factory.get_client()
logger.info(f"使用模型提供商: {factory.provider}")

# 初始化 agents
logger.info("初始化 Paper Agents...")
init_paper_agents(openai_client)
_init_digest_globals(openai_client)
logger.info("✅ Agents 初始化完成")

# 全局日志广播函数（用于 structlog processor）
_global_log_broadcast_func = None

def set_log_broadcast_func(func):
    global _global_log_broadcast_func
    _global_log_broadcast_func = func

def get_log_broadcast_func():
    return _global_log_broadcast_func

# Structlog processor for broadcasting logs
def websocket_broadcast_processor(logger, method_name, event_dict):
    """
    Structlog processor that broadcasts log messages to WebSocket clients.
    This processor runs before the final renderer, capturing the formatted message.
    """
    broadcast_func = get_log_broadcast_func()

    if broadcast_func is None:
        return event_dict

    # Extract log level and message
    log_level = event_dict.get('level', 'info')
    event_msg = event_dict.get('event', '')

    # Extract additional context fields (除了 structlog 的内部字段)
    excluded_keys = {'event', 'level', 'timestamp', 'logger', 'exc_info', 'stack_info'}
    extra_fields = {k: v for k, v in event_dict.items() if k not in excluded_keys}

    # Format extra fields as key=value pairs
    extra_str = ''
    if extra_fields:
        extra_parts = []
        for k, v in extra_fields.items():
            # 格式化值：字符串加引号，其他类型直接转字符串
            if isinstance(v, str):
                extra_parts.append(f"{k}='{v}'")
            else:
                extra_parts.append(f"{k}={v}")
        extra_str = ' ' + ' '.join(extra_parts)

    # Format the log message with timestamp
    timestamp = event_dict.get('timestamp', '')
    if timestamp:
        # Format timestamp nicely
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            timestamp_str = dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            timestamp_str = timestamp[:19]

        formatted_msg = f"{timestamp_str} [{log_level:5}] {event_msg}{extra_str}"
    else:
        formatted_msg = f"[{log_level:5}] {event_msg}{extra_str}"

    # Determine log type for frontend
    if log_level in ('error', 'critical'):
        log_type = 'error'
    elif log_level == 'warning':
        log_type = 'warning'
    else:
        log_type = 'info'

    # Schedule broadcast in the event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(broadcast_func({
                "type": "log",
                "level": log_type,
                "message": formatted_msg
            }))
    except RuntimeError:
        pass

    return event_dict

# 配置 structlog 添加 WebSocket 广播处理器
import structlog
from structlog.types import Processor

# 获取当前的 structlog 配置
current_config = structlog.get_config()

# 在现有 processors 中插入我们的 WebSocket 广播 processor
# 插入位置：在最终渲染器（JSONRenderer/ConsoleRenderer）之前
existing_processors = list(current_config.get('processors', []))

# 找到渲染器的位置并在其前面插入我们的 processor
insert_index = len(existing_processors) - 1 if existing_processors else 0
existing_processors.insert(insert_index, websocket_broadcast_processor)

# 重新配置 structlog
structlog.configure(
    processors=existing_processors,
    wrapper_class=current_config.get('wrapper_class', structlog.stdlib.BoundLogger),
    context_class=current_config.get('context_class', dict),
    logger_factory=current_config.get('logger_factory', structlog.stdlib.LoggerFactory()),
    cache_logger_on_first_use=current_config.get('cache_logger_on_first_use', True),
)

logger.info("✅ Structlog WebSocket 广播配置完成")

# ============= 认证辅助函数 =============

def verify_token_from_query(token: Optional[str] = Query(None)) -> Optional[dict]:
    """从查询参数验证 token"""
    if not token:
        return None

    payload = TokenManager.verify_token(token)
    return payload


# 对话上下文管理
class ConversationManager:
    def __init__(self):
        self.sessions = {}  # session_id -> {"agent": agent, "input_items": []}

    def get_session(self, session_id: str = "default"):
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "agent": paper_agent,
                "input_items": []
            }
        return self.sessions[session_id]

    def reset_session(self, session_id: str = "default"):
        if session_id in self.sessions:
            del self.sessions[session_id]

conversation_manager = ConversationManager()

# WebSocket 连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket 连接建立，当前连接数: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket 连接断开，当前连接数: {len(self.active_connections)}")

    async def send_message(self, message: dict, websocket: WebSocket):
        """发送消息到指定连接"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            self.disconnect(websocket)

    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        for connection in self.active_connections[:]:
            await self.send_message(message, connection)

manager = ConnectionManager()

# 请求模型
class DigestRequest(BaseModel):
    url: str

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"
    history: Optional[list] = None  # 前端发送的完整历史上下文
    notion_integration_secret: Optional[str] = None
    notion_database_id: Optional[str] = None

class ResetSessionRequest(BaseModel):
    session_id: str

class RestoreSessionRequest(BaseModel):
    session_id: str
    messages: list

class CancelChatRequest(BaseModel):
    session_id: str

class DigestResponse(BaseModel):
    success: bool
    message: str
    task_id: Optional[str] = None

class NotionTestRequest(BaseModel):
    notion_integration_secret: str
    notion_database_id: str

# 自定义日志处理器，用于将日志发送到 WebSocket
class WebSocketLogHandler(logging.Handler):
    def __init__(self, websocket: WebSocket):
        super().__init__()
        self.websocket = websocket
        self.manager = manager

    def emit(self, record):
        try:
            log_entry = self.format(record)
            # 异步发送日志
            asyncio.create_task(self.manager.send_message({
                "type": "log",
                "message": log_entry
            }, self.websocket))
        except Exception:
            pass

@app.get("/")
async def root():
    """返回主页面 - 认证由前端 JavaScript 处理"""
    # 直接返回主页面，由前端 app.js 检查 localStorage 中的 token
    # 如果没有有效 token，前端会自动重定向到登录页面
    return FileResponse("web/index.html")

@app.get("/login")
async def login_page():
    """返回登录页面"""
    return FileResponse("web/login.html")

@app.get("/login.js")
async def login_js():
    """返回登录 JavaScript 文件"""
    return FileResponse("web/login.js", media_type="application/javascript")

@app.get("/settings")
async def settings_page():
    """返回设置页面"""
    return FileResponse("web/settings.html")

@app.get("/settings.js")
async def settings_js():
    """返回设置 JavaScript 文件"""
    return FileResponse("web/settings.js", media_type="application/javascript")

@app.get("/style.css")
async def get_css():
    """返回 CSS 文件"""
    return FileResponse("web/style.css", media_type="text/css")

@app.get("/app.js")
async def get_js():
    """返回 JavaScript 文件"""
    return FileResponse("web/app.js", media_type="application/javascript")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接端点"""
    await manager.connect(websocket)
    try:
        # 保持连接，接收心跳
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("客户端断开连接")

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    聊天接口 - 接收用户消息并通过 WebSocket 返回 Agent 响应
    支持从前端传递 Notion 配置、session_id 和历史上下文
    """
    message = request.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    session_id = request.session_id or "default"

    logger.info(f"收到聊天消息: {message}, session_id: {session_id}")

    # 在后台启动处理任务，传递 Notion 配置、session_id 和历史上下文
    asyncio.create_task(process_chat(
        message,
        session_id=session_id,
        history=request.history,  # 传递前端发送的历史上下文
        notion_integration_secret=request.notion_integration_secret,
        notion_database_id=request.notion_database_id
    ))

    return {"success": True, "message": "消息已提交"}

@app.post("/api/digest")
async def create_digest(request: DigestRequest):
    """
    创建整理任务

    接收 URL（小红书或 PDF），启动 Agent 进行整理，并通过 WebSocket 返回进度
    """
    url = request.url.strip()

    if not url:
        raise HTTPException(status_code=400, detail="URL 不能为空")

    logger.info(f"收到整理请求: {url}")

    # 验证 URL 类型
    try:
        url_type = check_url_type(url)
        logger.info(f"URL 类型: {url_type}")
    except Exception as e:
        logger.error(f"URL 验证失败: {e}")
        raise HTTPException(status_code=400, detail=f"无效的 URL: {str(e)}")

    # 在后台启动处理任务
    asyncio.create_task(process_digest(url))

    return DigestResponse(
        success=True,
        message="任务已提交，正在处理...",
        task_id=None  # 可以后续添加任务 ID 跟踪
    )

class WebSocketLogCapture(logging.Handler):
    """捕获日志并发送到 WebSocket"""

    def __init__(self, broadcast_func):
        super().__init__()
        self.broadcast_func = broadcast_func
        # 设置格式化器
        formatter = logging.Formatter('%(message)s')
        self.setFormatter(formatter)

    def emit(self, record):
        try:
            # 格式化日志消息
            msg = self.format(record)

            # 过滤掉不需要的日志
            if 'HTTP Request:' in msg or 'traces/ingest' in msg:
                return

            # 提取有用的信息
            log_type = 'info'
            if record.levelname == 'ERROR':
                log_type = 'error'
            elif record.levelname == 'WARNING':
                log_type = 'warning'

            # 异步发送到前端 - 正确获取事件循环
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.broadcast_func({
                        "type": "log",
                        "level": log_type,
                        "message": msg
                    }))
            except RuntimeError:
                # 没有运行中的事件循环
                pass
        except Exception as e:
            # 调试：打印错误
            print(f"日志发送失败: {e}")

async def process_chat(
    message: str,
    session_id: str = "default",
    history: Optional[list] = None,
    notion_integration_secret: Optional[str] = None,
    notion_database_id: Optional[str] = None
):
    """
    处理聊天消息的后台函数 - 使用 Runner.run() 维护对话上下文

    Args:
        message: 用户消息
        session_id: 会话ID（从前端传递）
        history: 前端发送的完整历史上下文（优先于后端内存中的历史）
        notion_integration_secret: Notion Integration Secret (可选，优先使用用户配置)
        notion_database_id: Notion Database ID (可选，优先使用用户配置)

    注意：日志已通过 structlog 的 websocket_broadcast_processor 处理，
    无需再添加额外的 logging handler，以避免日志重复显示。
    """
    # 设置全局广播函数，供 structlog processor 使用
    set_log_broadcast_func(manager.broadcast)

    # 设置环境变量（临时覆盖，仅在当前请求中生效）
    original_env = {}
    try:
        if notion_integration_secret:
            original_env['NOTION_INTEGRATION_SECRET'] = os.environ.get('NOTION_INTEGRATION_SECRET')
            os.environ['NOTION_INTEGRATION_SECRET'] = notion_integration_secret
            logger.info("使用用户配置的 Notion Integration Secret")

        if notion_database_id:
            original_env['NOTION_DATABASE_ID'] = os.environ.get('NOTION_DATABASE_ID')
            os.environ['NOTION_DATABASE_ID'] = notion_database_id
            logger.info("使用用户配置的 Notion Database ID")

    except Exception as e:
        logger.warning(f"设置环境变量失败: {e}")

    try:
        # 获取会话上下文
        session = conversation_manager.get_session(session_id)
        current_agent = session["agent"]

        # 使用前端发送的历史上下文（如果有），优先级高于后端内存中的历史
        if history is not None and isinstance(history, list) and len(history) > 0:
            # 前端已经发送了完整的历史上下文，使用前端的数据
            input_items = []
            for msg in history:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    input_items.append({
                        "role": msg.get("role"),
                        "content": msg.get("content")
                    })
            logger.info(f"[DEBUG] 使用前端发送的历史上下文 - session_id: {session_id}")
            logger.info(f"[DEBUG] 前端历史消息数: {len(input_items)}")
        else:
            # 使用后端内存中的历史
            input_items = session["input_items"]
            logger.info(f"[DEBUG] 使用后端内存的历史上下文 - session_id: {session_id}")
            logger.info(f"[DEBUG] 后端历史消息数: {len(input_items)}")

        logger.info(f"[DEBUG] 历史消息内容: {input_items}")

        # 添加用户消息到上下文
        # 重要: 确保输入消息格式正确 - {"role": "user", "content": message}
        input_items.append({"role": "user", "content": message})
        logger.info(f"[DEBUG] 添加新消息后，总消息数: {len(input_items)}")

        # 使用 Runner.run() 执行，传入完整上下文
        # max_turns: 增加到 100 以支持更复杂的任务
        # 每个"turn"是一次 Agent-LLM 交互，论文处理通常需要多个步骤
        # (搜索 -> 下载 -> 提取文本 -> 提取图片 -> 创建 Notion 页面等)
        result = await Runner.run(
            starting_agent=current_agent,
            input=input_items,
            max_turns=50
        )

        # 更新会话状态
        session["agent"] = result.last_agent
        session["input_items"] = result.to_input_list()

        # 提取响应
        response_text = result.final_output if hasattr(result, 'final_output') else str(result)

        # 发送 assistant 消息
        await manager.broadcast({
            "type": "assistant_message",
            "message": response_text
        })

        # 尝试提取 Notion 链接
        notion_url = extract_notion_url(response_text)
        title = extract_title(response_text)

        if notion_url and title:
            # 发送 Notion 链接
            await manager.broadcast({
                "type": "notion_link",
                "result": {
                    "title": title,
                    "url": notion_url
                }
            })

        # 发送完成信号
        await manager.broadcast({
            "type": "done"
        })

        logger.info(f"聊天处理完成: {message[:50]}...")

    except Exception as e:
        logger.error(f"聊天处理失败: {e}", exc_info=True)
        await manager.broadcast({
            "type": "error",
            "error": str(e)
        })
        await manager.broadcast({
            "type": "done"
        })
    finally:
        # 恢复原始环境变量
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        # 清除全局广播函数
        set_log_broadcast_func(None)

async def process_digest(url: str):
    """
    处理整理任务的后台函数
    """
    try:
        # 步骤 1: 链接识别
        await manager.broadcast({
            "type": "step",
            "step": 1,
            "message": "正在识别链接类型..."
        })

        url_type = check_url_type(url)

        await manager.broadcast({
            "type": "step_complete",
            "step": 1,
            "message": f"链接类型识别完成: {url_type}"
        })

        # 步骤 2: 内容提取
        await manager.broadcast({
            "type": "step",
            "step": 2,
            "message": "正在提取内容..."
        })

        # 根据不同类型构建提示
        if url_type == "xiaohongshu":
            prompt = f"整理这篇小红书笔记并保存到 Notion：{url}"
        else:
            prompt = f"整理这篇论文并保存到 Notion：{url}"

        await manager.broadcast({
            "type": "step_complete",
            "step": 2,
            "message": "内容提取完成"
        })

        # 步骤 3: AI 整理
        await manager.broadcast({
            "type": "step",
            "step": 3,
            "message": "正在使用 AI 整理内容..."
        })

        # 调用 digest_agent（使用同步方式，因为 agents SDK 不是原生 async）
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: digest_agent.run(prompt)
        )

        # 提取最终消息
        final_message = response.messages[-1].content if response.messages else ""

        await manager.broadcast({
            "type": "step_complete",
            "step": 3,
            "message": "AI 整理完成"
        })

        # 步骤 4: 保存到 Notion
        await manager.broadcast({
            "type": "step",
            "step": 4,
            "message": "正在保存到 Notion..."
        })

        # 从响应中提取 Notion 链接和标题
        # 假设 agent 返回的消息中包含这些信息
        notion_url = extract_notion_url(final_message)
        title = extract_title(final_message)

        if not notion_url:
            raise Exception("未能获取 Notion 链接")

        await manager.broadcast({
            "type": "step_complete",
            "step": 4,
            "message": "已保存到 Notion"
        })

        # 发送成功消息
        await manager.broadcast({
            "type": "success",
            "message": "处理完成！",
            "result": {
                "title": title or "未命名笔记",
                "notion_url": notion_url
            }
        })

        logger.info(f"处理完成: {url}")

    except Exception as e:
        logger.error(f"处理失败: {e}", exc_info=True)
        await manager.broadcast({
            "type": "error",
            "message": "处理失败",
            "error": str(e)
        })

def extract_notion_url(message: str) -> Optional[str]:
    """从 Agent 响应中提取 Notion URL"""
    import re

    # 查找 Notion URL
    patterns = [
        r'https://www\.notion\.so/[^\s\)]+',
        r'Notion 链接[：:]\s*(https://[^\s]+)',
        r'保存到[：:]\s*(https://www\.notion\.so/[^\s]+)'
    ]

    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            if match.groups():
                return match.group(1)
            return match.group(0)

    return None

def extract_title(message: str) -> Optional[str]:
    """从 Agent 响应中提取标题"""
    import re

    # 查找标题
    patterns = [
        r'标题[：:]\s*(.+?)[\n\r]',
        r'论文标题[：:]\s*(.+?)[\n\r]',
        r'笔记标题[：:]\s*(.+?)[\n\r]',
        r'已保存.*?[「『""](.+?)[」』""]',
    ]

    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            return match.group(1).strip()

    # 如果找不到，尝试从第一行获取
    lines = message.strip().split('\n')
    if lines and len(lines[0]) < 100:
        return lines[0].strip()

    return None

@app.post("/api/test-notion-connection")
async def test_notion_connection(request: NotionTestRequest):
    """
    测试 Notion 连接
    """
    try:
        from notion_client import AsyncClient

        # 验证参数
        if not request.notion_integration_secret or not request.notion_database_id:
            raise HTTPException(status_code=400, detail="Integration Secret 和 Database ID 不能为空")

        # 创建客户端并测试连接
        client = AsyncClient(auth=request.notion_integration_secret)

        # 尝试查询数据库信息
        database = await client.databases.retrieve(database_id=request.notion_database_id)

        await client.aclose()

        # 提取数据库标题
        database_title = "未命名"
        if database.get("title"):
            title_parts = database["title"]
            if title_parts and len(title_parts) > 0:
                database_title = title_parts[0].get("plain_text", "未命名")

        # 提取数据库字段信息
        properties = database.get("properties", {})
        fields = []
        for field_name, field_data in properties.items():
            field_type = field_data.get("type", "unknown")
            fields.append({
                "name": field_name,
                "type": field_type
            })

        logger.info(f"Notion 连接测试成功: {database_title}, 字段数量: {len(fields)}")

        return {
            "success": True,
            "database_title": database_title,
            "fields": fields,
            "message": "连接成功"
        }

    except Exception as e:
        logger.error(f"Notion 连接测试失败: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/reset-session")
async def reset_session(request: ResetSessionRequest):
    """
    重置会话 - 清除指定会话的上下文
    """
    try:
        session_id = request.session_id
        conversation_manager.reset_session(session_id)
        logger.info(f"会话已重置: {session_id}")
        return {"success": True, "message": f"会话 {session_id} 已重置"}
    except Exception as e:
        logger.error(f"重置会话失败: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/cancel-chat")
async def cancel_chat(request: CancelChatRequest):
    """
    取消正在进行的聊天处理
    """
    try:
        session_id = request.session_id
        logger.info(f"收到取消请求: session_id={session_id}")

        # 发送取消信号到前端
        await manager.broadcast({
            "type": "done"
        })

        return {"success": True, "message": "处理已取消"}
    except Exception as e:
        logger.error(f"取消聊天失败: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/restore-session")
async def restore_session(request: RestoreSessionRequest):
    """
    恢复会话 - 从前端消息重建会话上下文
    """
    try:
        session_id = request.session_id
        messages = request.messages

        logger.info(f"[DEBUG] 收到恢复会话请求: session_id={session_id}")
        logger.info(f"[DEBUG] 收到的消息数量: {len(messages)}")
        logger.info(f"[DEBUG] 消息内容: {messages}")

        # 将前端消息转换为 input_items 格式
        input_items = []
        for msg in messages:
            # 只提取 role 和 content 字段
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                input_items.append({
                    "role": msg.get("role"),
                    "content": msg.get("content")
                })

        logger.info(f"[DEBUG] 转换后的 input_items 数量: {len(input_items)}")
        logger.info(f"[DEBUG] input_items 内容: {input_items}")

        # 获取或创建会话
        session = conversation_manager.get_session(session_id)
        session["input_items"] = input_items
        session["agent"] = paper_agent

        logger.info(f"✅ 会话已恢复: {session_id}, 消息数: {len(input_items)}")
        return {
            "success": True,
            "message": f"会话 {session_id} 已恢复",
            "message_count": len(input_items)
        }
    except Exception as e:
        logger.error(f"恢复会话失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

@app.post("/api/initialize-notion-database")
async def initialize_notion_database(request: NotionTestRequest):
    """
    自动为 Notion Database 添加所需字段（如果不存在）
    """
    try:
        from notion_client import AsyncClient

        # 验证参数
        if not request.notion_integration_secret or not request.notion_database_id:
            raise HTTPException(status_code=400, detail="Integration Secret 和 Database ID 不能为空")

        logger.info("开始初始化 Notion Database 字段...")

        # 创建客户端
        client = AsyncClient(auth=request.notion_integration_secret)

        # 获取当前数据库的字段
        database = await client.databases.retrieve(database_id=request.notion_database_id)
        existing_properties = database.get("properties", {})

        # 定义需要的字段（基于 paper_digest.py 中的字段）
        required_fields = {
            "Name": {"title": {}},  # 标题字段（必须存在）
            "Authors": {"rich_text": {}},
            "Affiliations": {"rich_text": {}},
            "Venue": {"rich_text": {}},
            "Abstract": {"rich_text": {}},
            "Keywords": {"multi_select": {"options": []}},
            "ArXiv ID": {"rich_text": {}},
            "Publication Date": {"date": {}},
            "Other Resources": {"rich_text": {}},
            "PDF Link": {"url": {}},
            "Source URL": {"url": {}}
        }

        # 检查缺失的字段
        missing_fields = {}
        for field_name, field_config in required_fields.items():
            if field_name not in existing_properties:
                missing_fields[field_name] = field_config
                logger.info(f"发现缺失字段: {field_name}")

        if not missing_fields:
            logger.info("所有必需字段已存在，无需初始化")
            await client.aclose()
            return {
                "success": True,
                "message": "所有必需字段已存在",
                "added_fields": [],
                "existing_fields": list(existing_properties.keys())
            }

        # 添加缺失的字段
        logger.info(f"准备添加 {len(missing_fields)} 个缺失字段...")

        # 构建更新请求 - 只添加新字段，不修改现有字段
        update_properties = dict(existing_properties)  # 保留现有字段
        update_properties.update(missing_fields)  # 添加缺失字段

        # 更新数据库 schema
        await client.databases.update(
            database_id=request.notion_database_id,
            properties=update_properties
        )

        await client.aclose()

        logger.info(f"✅ 成功添加 {len(missing_fields)} 个字段到 Notion Database")

        return {
            "success": True,
            "message": f"成功添加 {len(missing_fields)} 个字段",
            "added_fields": list(missing_fields.keys()),
            "existing_fields": list(existing_properties.keys())
        }

    except Exception as e:
        logger.error(f"初始化 Notion Database 失败: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "model_provider": factory.provider,
        "connections": len(manager.active_connections)
    }

if __name__ == "__main__":
    import uvicorn

    # 确保 web 目录存在
    web_dir = Path("web")
    if not web_dir.exists():
        logger.error(f"Web 目录不存在: {web_dir.absolute()}")
        exit(1)

    logger.info("启动 Web 服务器...")
    logger.info(f"访问地址: http://localhost:9997")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=9997,
        log_level="info"
    )
