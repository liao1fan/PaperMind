"""
认证工具：密码哈希、JWT Token
"""

import os
from datetime import datetime, timedelta
from typing import Optional, Dict

from passlib.context import CryptContext
import jwt

# 密码哈希配置（使用 bcrypt，在低配置服务器上速度更快）
# bcrypt 比 argon2 更快，且对低配置服务器更友好
pwd_context = CryptContext(
    schemes=["bcrypt", "argon2"],  # bcrypt 优先，argon2 作为后备（用于验证旧密码）
    deprecated="auto",
    bcrypt__rounds=10  # bcrypt 轮数（默认12，降低到10以提升速度）
)

# JWT 配置
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 7 天


class PasswordManager:
    """密码管理工具"""

    @staticmethod
    def hash_password(password: str) -> str:
        """哈希密码"""
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        return pwd_context.verify(plain_password, hashed_password)


class TokenManager:
    """JWT Token 管理"""

    @staticmethod
    def create_token(user_id: int, username: str) -> str:
        """创建 JWT Token"""
        payload = {
            "user_id": user_id,
            "username": username,
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
            "iat": datetime.utcnow(),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        return token

    @staticmethod
    def verify_token(token: str) -> Optional[Dict]:
        """验证 JWT Token"""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    @staticmethod
    def get_user_from_token(token: str) -> Optional[Dict]:
        """从 Token 中提取用户信息"""
        payload = TokenManager.verify_token(token)
        if payload:
            return {
                "user_id": payload.get("user_id"),
                "username": payload.get("username"),
            }
        return None
