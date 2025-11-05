"""
认证 API 路由（简化版：用户名+密码）
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator
from typing import Optional
from sqlalchemy.orm import Session
import logging

from .models import User, get_session, init_db
from .utils import PasswordManager, TokenManager

logger = logging.getLogger(__name__)

# 初始化数据库
engine = init_db()

# 创建路由
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ============= Pydantic 模型 =============

class RegisterRequest(BaseModel):
    """注册请求"""
    username: str
    password: str

    @validator("username")
    def validate_username(cls, v):
        if len(v) < 3 or len(v) > 20:
            raise ValueError("用户名长度 3-20 位")
        if not v.isalnum():
            raise ValueError("用户名只能包含字母和数字")
        return v

    @validator("password")
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError("密码长度至少 6 位")
        return v


class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


class AuthResponse(BaseModel):
    """认证响应"""
    success: bool
    message: str
    token: Optional[str] = None
    user_id: Optional[int] = None
    username: Optional[str] = None


# ============= 认证接口 =============

@router.post("/register", response_model=AuthResponse)
async def register(req: RegisterRequest):
    """用户注册"""
    import time
    start_time = time.time()
    logger.info(f"[性能] 开始处理注册请求: {req.username}")

    session = get_session(engine)
    logger.info(f"[性能] 获取数据库会话耗时: {time.time() - start_time:.3f}s")

    try:
        # 检查用户是否已存在
        query_start = time.time()
        existing_user = session.query(User).filter(User.username == req.username).first()
        logger.info(f"[性能] 查询用户是否存在耗时: {time.time() - query_start:.3f}s")

        if existing_user:
            raise HTTPException(status_code=400, detail="用户名已存在")

        # 创建新用户
        hash_start = time.time()
        password_hash = PasswordManager.hash_password(req.password)
        logger.info(f"[性能] 密码哈希耗时: {time.time() - hash_start:.3f}s")

        user = User(
            username=req.username,
            password_hash=password_hash,
        )

        db_start = time.time()
        session.add(user)
        session.commit()
        session.refresh(user)
        logger.info(f"[性能] 数据库提交耗时: {time.time() - db_start:.3f}s")

        # 生成 Token
        token_start = time.time()
        token = TokenManager.create_token(user.id, user.username)
        logger.info(f"[性能] 生成Token耗时: {time.time() - token_start:.3f}s")

        logger.info(f"✅ 用户注册成功: {req.username}, 总耗时: {time.time() - start_time:.3f}s")

        return AuthResponse(
            success=True,
            message=f"注册成功，欢迎 {req.username}",
            token=token,
            user_id=user.id,
            username=user.username,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 注册失败: {e}")
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")
    finally:
        session.close()


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    """用户登录"""
    import time
    start_time = time.time()
    logger.info(f"[性能] 开始处理登录请求: {req.username}")

    session = get_session(engine)
    logger.info(f"[性能] 获取数据库会话耗时: {time.time() - start_time:.3f}s")

    try:
        # 查找用户
        query_start = time.time()
        user = session.query(User).filter(User.username == req.username).first()
        logger.info(f"[性能] 查询用户耗时: {time.time() - query_start:.3f}s")

        if not user:
            raise HTTPException(status_code=401, detail="用户不存在或密码错误")

        # 验证密码
        verify_start = time.time()
        if not PasswordManager.verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户不存在或密码错误")
        logger.info(f"[性能] 验证密码耗时: {time.time() - verify_start:.3f}s")

        # 生成 Token
        token_start = time.time()
        token = TokenManager.create_token(user.id, user.username)
        logger.info(f"[性能] 生成Token耗时: {time.time() - token_start:.3f}s")

        logger.info(f"✅ 用户登录成功: {req.username}, 总耗时: {time.time() - start_time:.3f}s")

        return AuthResponse(
            success=True,
            message=f"登录成功，欢迎回来 {req.username}",
            token=token,
            user_id=user.id,
            username=user.username,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 登录失败: {e}")
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")
    finally:
        session.close()


@router.get("/verify-token")
async def verify_token(token: str):
    """验证 Token 有效性"""
    payload = TokenManager.verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    return {
        "success": True,
        "user_id": payload.get("user_id"),
        "username": payload.get("username"),
    }
