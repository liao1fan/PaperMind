"""
对话管理 API 路由
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from .models import Conversation, Message, get_session, init_db
from .utils import TokenManager

logger = logging.getLogger(__name__)

# 初始化数据库引擎
engine = init_db()

# 创建路由
router = APIRouter(prefix="/api/conversation", tags=["conversation"])


# ============= Pydantic 模型 =============

class MessageResponse(BaseModel):
    """消息响应"""
    id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    """对话响应"""
    id: int
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    messages: List[MessageResponse] = []

    class Config:
        from_attributes = True


class CreateConversationRequest(BaseModel):
    """创建对话请求"""
    title: Optional[str] = None


class SendMessageRequest(BaseModel):
    """发送消息请求"""
    conversation_id: int
    content: str


class UpdateConversationRequest(BaseModel):
    """更新对话请求"""
    title: Optional[str] = None


# ============= 辅助函数 =============

def get_current_user_id(token: str) -> int:
    """从 Token 提取用户 ID"""
    payload = TokenManager.verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    return payload.get("user_id")


def verify_conversation_ownership(session: Session, conversation_id: int, user_id: int) -> Conversation:
    """验证对话所有权"""
    conversation = session.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在或无权访问")

    return conversation


# ============= API 端点 =============

@router.post("/create", response_model=ConversationResponse)
async def create_conversation(req: CreateConversationRequest, token: str = Query(...)):
    """创建新对话"""
    session = get_session(engine)

    try:
        user_id = get_current_user_id(token)

        # 创建对话
        conversation = Conversation(
            user_id=user_id,
            title=req.title or f"对话 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        session.add(conversation)
        session.commit()
        session.refresh(conversation)

        logger.info(f"✅ 用户 {user_id} 创建对话 {conversation.id}")

        return ConversationResponse.model_validate(conversation)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 创建对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建对话失败: {str(e)}")
    finally:
        session.close()


@router.get("/list", response_model=List[ConversationResponse])
async def list_conversations(token: str = Query(...)):
    """获取用户的所有对话"""
    session = get_session(engine)

    try:
        user_id = get_current_user_id(token)

        # 获取用户的所有对话，按更新时间倒序排列
        conversations = session.query(Conversation).filter(
            Conversation.user_id == user_id
        ).order_by(Conversation.updated_at.desc()).all()

        return [ConversationResponse.model_validate(c) for c in conversations]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取对话列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取对话列表失败: {str(e)}")
    finally:
        session.close()


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: int, token: str = Query(...)):
    """获取对话详情"""
    session = get_session(engine)

    try:
        user_id = get_current_user_id(token)
        conversation = verify_conversation_ownership(session, conversation_id, user_id)

        # 加载消息
        messages = session.query(Message).filter(
            Message.conversation_id == conversation_id
        ).order_by(Message.created_at.asc()).all()

        conversation.messages = messages

        return ConversationResponse.model_validate(conversation)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取对话失败: {str(e)}")
    finally:
        session.close()


@router.post("/{conversation_id}/message", response_model=MessageResponse)
async def add_message(conversation_id: int, req: SendMessageRequest, token: str = Query(...)):
    """添加消息到对话"""
    session = get_session(engine)

    try:
        user_id = get_current_user_id(token)
        verify_conversation_ownership(session, conversation_id, user_id)

        # 创建消息
        message = Message(
            conversation_id=conversation_id,
            role="user",
            content=req.content
        )

        session.add(message)

        # 更新对话的 updated_at
        conversation = session.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()
        conversation.updated_at = datetime.utcnow()

        session.commit()
        session.refresh(message)

        logger.info(f"✅ 用户 {user_id} 添加消息到对话 {conversation_id}")

        return MessageResponse.model_validate(message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 添加消息失败: {e}")
        raise HTTPException(status_code=500, detail=f"添加消息失败: {str(e)}")
    finally:
        session.close()


@router.post("/{conversation_id}/response", response_model=MessageResponse)
async def add_response(conversation_id: int, content: str = Query(...), token: str = Query(...)):
    """添加助手响应消息"""
    session = get_session(engine)

    try:
        user_id = get_current_user_id(token)
        verify_conversation_ownership(session, conversation_id, user_id)

        # 创建助手消息
        message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=content
        )

        session.add(message)

        # 更新对话的 updated_at
        conversation = session.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()
        conversation.updated_at = datetime.utcnow()

        session.commit()
        session.refresh(message)

        return MessageResponse.model_validate(message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 添加响应失败: {e}")
        raise HTTPException(status_code=500, detail=f"添加响应失败: {str(e)}")
    finally:
        session.close()


@router.put("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(conversation_id: int, req: UpdateConversationRequest, token: str = Query(...)):
    """更新对话"""
    session = get_session(engine)

    try:
        user_id = get_current_user_id(token)
        conversation = verify_conversation_ownership(session, conversation_id, user_id)

        if req.title:
            conversation.title = req.title

        conversation.updated_at = datetime.utcnow()
        session.commit()
        session.refresh(conversation)

        logger.info(f"✅ 用户 {user_id} 更新对话 {conversation_id}")

        return ConversationResponse.model_validate(conversation)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 更新对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新对话失败: {str(e)}")
    finally:
        session.close()


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: int, token: str = Query(...)):
    """删除对话"""
    session = get_session(engine)

    try:
        user_id = get_current_user_id(token)
        conversation = verify_conversation_ownership(session, conversation_id, user_id)

        session.delete(conversation)
        session.commit()

        logger.info(f"✅ 用户 {user_id} 删除对话 {conversation_id}")

        return {"success": True, "message": "对话已删除"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 删除对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除对话失败: {str(e)}")
    finally:
        session.close()
