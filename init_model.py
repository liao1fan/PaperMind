"""
模型初始化模块

功能：
- 根据 provider 创建 OpenAI 兼容的客户端
- 提供两种模型：tool_model（轻量）和 reason_model（推理）
- 支持 OpenAI 和 DeepSeek 两种 provider

环境变量配置（.env 文件）：
- LLM_PROVIDER: "openai" 或 "deepseek"（默认 openai）
- OPENAI_API_KEY: OpenAI API 密钥
- OPENAI_BASE_URL: OpenAI API 端点
- DEEPSEEK_API_KEY: DeepSeek API 密钥
- DEEPSEEK_BASE_URL: DeepSeek API 端点（默认 https://api.deepseek.com）
"""

import os
from typing import Literal
from openai import AsyncOpenAI
from agents import OpenAIChatCompletionsModel, set_default_openai_client
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# Provider 类型
ProviderType = Literal["openai", "deepseek"]

# 模型配置
MODEL_CONFIGS = {
    "openai": {
        "base_url_env": "OPENAI_BASE_URL",
        "api_key_env": "OPENAI_API_KEY",
        "default_base_url": "https://api.openai.com/v1",
        "models": {
            "tool": "gpt-5-mini",      # 轻量化模型
            "reason": "gpt-5",          # 复杂推理模型
        }
    },
    "deepseek": {
        "base_url_env": "DEEPSEEK_BASE_URL",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_base_url": "https://api.deepseek.com",
        "models": {
            "tool": "deepseek-chat",    # 轻量化模型
            "reason": "deepseek-chat",  # 复杂推理模型（DeepSeek 只有一个模型）
        }
    }
}


class ModelFactory:
    """模型工厂类"""

    def __init__(self, provider: ProviderType = None):
        """
        初始化模型工厂

        Args:
            provider: 模型提供商，"openai" 或 "deepseek"
                     如果为 None，则从环境变量 LLM_PROVIDER 读取
        """
        # 确定 provider
        if provider is None:
            provider = os.getenv("LLM_PROVIDER", "openai").lower()

        if provider not in MODEL_CONFIGS:
            raise ValueError(f"不支持的 provider: {provider}，支持的值: {list(MODEL_CONFIGS.keys())}")

        self.provider = provider
        self.config = MODEL_CONFIGS[provider]

        # 创建客户端
        self.client = self._create_client()

        # 设置为默认客户端
        set_default_openai_client(self.client, use_for_tracing=False)

        # 创建模型实例
        self.tool_model = self._create_model("tool")
        self.reason_model = self._create_model("reason")

        print(f"✅ 模型初始化完成:")
        print(f"   Provider: {self.provider}")
        print(f"   Tool Model: {self.config['models']['tool']}")
        print(f"   Reason Model: {self.config['models']['reason']}")

    def _create_client(self) -> AsyncOpenAI:
        """创建 AsyncOpenAI 客户端"""
        # 获取配置
        base_url = os.getenv(
            self.config["base_url_env"],
            self.config["default_base_url"]
        )
        api_key = os.getenv(self.config["api_key_env"])

        if not api_key:
            raise ValueError(
                f"未设置 {self.config['api_key_env']} 环境变量，"
                f"请在 .env 文件中配置"
            )

        # 创建客户端
        client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )

        print(f"   Base URL: {base_url}")

        return client

    def _create_model(self, model_type: Literal["tool", "reason"]) -> OpenAIChatCompletionsModel:
        """
        创建模型对象

        Args:
            model_type: "tool" 或 "reason"

        Returns:
            OpenAIChatCompletionsModel 实例
        """
        model_name = self.config["models"][model_type]

        return OpenAIChatCompletionsModel(
            model=model_name,
            openai_client=self.client
        )

    def get_tool_model(self) -> OpenAIChatCompletionsModel:
        """获取轻量化工具模型"""
        return self.tool_model

    def get_reason_model(self) -> OpenAIChatCompletionsModel:
        """获取复杂推理模型"""
        return self.reason_model

    def get_client(self) -> AsyncOpenAI:
        """获取客户端"""
        return self.client


# 全局变量
_factory: ModelFactory = None
tool_model: OpenAIChatCompletionsModel = None
reason_model: OpenAIChatCompletionsModel = None
openai_client: AsyncOpenAI = None


def init_models(provider: ProviderType = None) -> ModelFactory:
    """
    初始化模型

    Args:
        provider: 模型提供商，"openai" 或 "deepseek"
                 如果为 None，则从环境变量 LLM_PROVIDER 读取

    Returns:
        ModelFactory 实例
    """
    global _factory, tool_model, reason_model, openai_client

    _factory = ModelFactory(provider)
    tool_model = _factory.get_tool_model()
    reason_model = _factory.get_reason_model()
    openai_client = _factory.get_client()

    return _factory


def get_factory() -> ModelFactory:
    """
    获取全局 ModelFactory 实例

    如果尚未初始化，则自动初始化
    """
    global _factory

    if _factory is None:
        init_models()

    return _factory


# 便捷函数
def get_tool_model() -> OpenAIChatCompletionsModel:
    """获取轻量化工具模型"""
    return get_factory().get_tool_model()


def get_reason_model() -> OpenAIChatCompletionsModel:
    """获取复杂推理模型"""
    return get_factory().get_reason_model()


def get_client() -> AsyncOpenAI:
    """获取客户端"""
    return get_factory().get_client()


if __name__ == "__main__":
    # 测试代码
    print("\n" + "="*70)
    print("测试模型初始化")
    print("="*70 + "\n")

    # 初始化模型
    factory = init_models()

    print(f"\n工具模型: {tool_model}")
    print(f"推理模型: {reason_model}")
    print(f"客户端: {openai_client}")

    print("\n" + "="*70)
    print("✅ 测试完成")
    print("="*70 + "\n")
