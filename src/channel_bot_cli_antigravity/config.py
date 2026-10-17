"""配置管理模块。"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


def load_env_file(env_path: str | Path | None = None) -> bool:
    """加载 .env 环境变量文件。

    若指定 env_path 则优先加载该文件；
    若未指定，则通过 find_dotenv(usecwd=True) 自动从当前工作目录及上层目录查找并加载。
    """
    if env_path:
        target = Path(env_path)
        if target.is_file():
            return load_dotenv(target, override=True)
        return False

    cwd_env = find_dotenv(usecwd=True)
    if cwd_env:
        return load_dotenv(cwd_env, override=True)
    return False


@dataclass
class Config:
    """机器人与服务配置项。"""

    lark_app_id: str = ""
    lark_app_secret: str = ""
    lark_domain: str | None = None
    log_level: str = "INFO"
    agy_model: str | None = None
    agy_image_model: str | None = None

    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量读取配置。"""
        agy_model = os.getenv("AGY_MODEL", "").strip() or None
        agy_image_model = os.getenv("AGY_IMAGE_MODEL", "").strip() or None
        return cls(
            lark_app_id=os.getenv("LARK_APP_ID", "").strip(),
            lark_app_secret=os.getenv("LARK_APP_SECRET", "").strip(),
            lark_domain=os.getenv("LARK_DOMAIN"),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip(),
            agy_model=agy_model,
            agy_image_model=agy_image_model,
        )

    def validate(self) -> None:
        """校验关键凭据是否已配置。"""
        if not self.lark_app_id or not self.lark_app_secret:
            raise ValueError(
                "请在环境变量或 .env 文件中配置 LARK_APP_ID 与 LARK_APP_SECRET"
            )


def get_config() -> Config:
    """获取配置实例。"""
    return Config.from_env()
