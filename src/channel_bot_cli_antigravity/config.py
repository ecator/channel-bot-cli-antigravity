"""配置管理模块。"""

from __future__ import annotations

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


@dataclass(init=False)
class Config:
    """机器人与服务配置项。"""

    dd_client_id: str = ""
    dd_client_secret: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_domain: str | None = None
    log_level: str = "INFO"
    agy_model: str | None = None
    agy_image_model: str | None = None

    def __init__(
        self,
        dd_client_id: str = "",
        dd_client_secret: str = "",
        feishu_app_id: str = "",
        feishu_app_secret: str = "",
        feishu_domain: str | None = None,
        log_level: str = "INFO",
        agy_model: str | None = None,
        agy_image_model: str | None = None,
        *,
        lark_app_id: str | None = None,
        lark_app_secret: str | None = None,
        lark_domain: str | None = None,
    ) -> None:
        self.dd_client_id = dd_client_id
        self.dd_client_secret = dd_client_secret
        self.feishu_app_id = feishu_app_id or (lark_app_id or "")
        self.feishu_app_secret = feishu_app_secret or (lark_app_secret or "")
        self.feishu_domain = feishu_domain if feishu_domain is not None else lark_domain
        self.log_level = log_level
        self.agy_model = agy_model
        self.agy_image_model = agy_image_model

    @property
    def lark_app_id(self) -> str:
        """向后兼容属性：返回 feishu_app_id。"""
        return self.feishu_app_id

    @lark_app_id.setter
    def lark_app_id(self, value: str) -> None:
        self.feishu_app_id = value

    @property
    def lark_app_secret(self) -> str:
        """向后兼容属性：返回 feishu_app_secret。"""
        return self.feishu_app_secret

    @lark_app_secret.setter
    def lark_app_secret(self, value: str) -> None:
        self.feishu_app_secret = value

    @property
    def lark_domain(self) -> str | None:
        """向后兼容属性：返回 feishu_domain。"""
        return self.feishu_domain

    @lark_domain.setter
    def lark_domain(self, value: str | None) -> None:
        self.feishu_domain = value

    @classmethod
    def from_env(cls) -> Config:
        """从环境变量读取配置。

        优先级说明：
        - 飞书凭据优先读取 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_DOMAIN，
          若未设置则降级回退至历史兼容变量 LARK_APP_ID / LARK_APP_SECRET / LARK_DOMAIN。
        - 钉钉凭据读取 DD_CLIENT_ID / DD_CLIENT_SECRET。
        """
        feishu_app_id = (
            os.getenv("FEISHU_APP_ID", "").strip()
            or os.getenv("LARK_APP_ID", "").strip()
        )
        feishu_app_secret = (
            os.getenv("FEISHU_APP_SECRET", "").strip()
            or os.getenv("LARK_APP_SECRET", "").strip()
        )
        feishu_domain = (
            os.getenv("FEISHU_DOMAIN", "").strip()
            or os.getenv("LARK_DOMAIN", "").strip()
            or None
        )
        dd_client_id = os.getenv("DD_CLIENT_ID", "").strip()
        dd_client_secret = os.getenv("DD_CLIENT_SECRET", "").strip()
        log_level = os.getenv("LOG_LEVEL", "INFO").strip()
        agy_model = os.getenv("AGY_MODEL", "").strip() or None
        agy_image_model = os.getenv("AGY_IMAGE_MODEL", "").strip() or None

        return cls(
            dd_client_id=dd_client_id,
            dd_client_secret=dd_client_secret,
            feishu_app_id=feishu_app_id,
            feishu_app_secret=feishu_app_secret,
            feishu_domain=feishu_domain,
            log_level=log_level,
            agy_model=agy_model,
            agy_image_model=agy_image_model,
        )

    def validate_channel(self, channel: str) -> None:
        """校验指定渠道的关键凭据是否已配置。

        参数:
            channel: 渠道名称，支持 "dingtalk"、"feishu" 或 "all"（不区分大小写）。

        异常:
            ValueError: 当渠道名称不支持或关键凭据缺失时抛出明确描述。
        """
        ch = channel.strip().lower()
        if ch == "dingtalk":
            if not self.dd_client_id and not self.dd_client_secret:
                raise ValueError(
                    "请在环境变量或 .env 中配置 DD_CLIENT_ID 与 DD_CLIENT_SECRET（钉钉凭据未配置）"
                )
            if not self.dd_client_id:
                raise ValueError(
                    "请在环境变量或 .env 中配置 DD_CLIENT_ID（钉钉 Client ID 未配置）"
                )
            if not self.dd_client_secret:
                raise ValueError(
                    "请在环境变量或 .env 中配置 DD_CLIENT_SECRET（钉钉 Client Secret 未配置）"
                )
        elif ch == "feishu":
            if not self.feishu_app_id and not self.feishu_app_secret:
                raise ValueError(
                    "请在环境变量或 .env 中配置 FEISHU_APP_ID (或 LARK_APP_ID) 与 "
                    "FEISHU_APP_SECRET (或 LARK_APP_SECRET)（飞书凭据未配置）"
                )
            if not self.feishu_app_id:
                raise ValueError(
                    "请在环境变量或 .env 中配置 FEISHU_APP_ID (或 LARK_APP_ID)（飞书 App ID 未配置）"
                )
            if not self.feishu_app_secret:
                raise ValueError(
                    "请在环境变量或 .env 中配置 FEISHU_APP_SECRET (或 LARK_APP_SECRET)（飞书 App Secret 未配置）"
                )
        elif ch == "all":
            self.validate_channel("dingtalk")
            self.validate_channel("feishu")
        else:
            raise ValueError(
                f"不支持的渠道类型: {channel!r}。仅支持 'dingtalk'、'feishu' 或 'all'"
            )

    def infer_default_channel(self) -> str:
        """根据配置的凭据推断默认渠道类型。

        策略：
        1. 若钉钉凭据已配置（dd_client_id 与 dd_client_secret），优先返回 "dingtalk"；
        2. 若仅配置了飞书凭据（feishu_app_id 与 feishu_app_secret），返回 "feishu"；
        3. 若均未完整配置或无法推断，默认返回 "dingtalk"。
        """
        has_dd = bool(self.dd_client_id and self.dd_client_secret)
        has_feishu = bool(self.feishu_app_id and self.feishu_app_secret)

        if has_dd:
            return "dingtalk"
        if has_feishu:
            return "feishu"
        return "dingtalk"

    def validate(self) -> None:
        """校验凭据是否已配置（向后兼容方法）。"""
        channel = self.infer_default_channel()
        self.validate_channel(channel)


def get_config() -> Config:
    """获取配置实例。"""
    return Config.from_env()
