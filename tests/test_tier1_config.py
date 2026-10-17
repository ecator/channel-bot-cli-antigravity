"""Tier 1: Feature Coverage - Config loading, credentials, validation & channel inference."""

import pytest

from channel_bot_cli_antigravity.config import Config


def test_config_dingtalk_credentials_from_env(dingtalk_env: pytest.MonkeyPatch) -> None:
    """Verify loading DingTalk credentials (DD_CLIENT_ID, DD_CLIENT_SECRET) from environment."""
    cfg = Config.from_env()
    assert hasattr(cfg, "dd_client_id"), "Config must have dd_client_id attribute"
    assert hasattr(cfg, "dd_client_secret"), (
        "Config must have dd_client_secret attribute"
    )
    assert cfg.dd_client_id == "suite_dd_client_id_123"
    assert cfg.dd_client_secret == "suite_dd_client_secret_xyz"


def test_config_feishu_credentials_from_env(feishu_env: pytest.MonkeyPatch) -> None:
    """Verify loading Feishu credentials (FEISHU_APP_ID, FEISHU_APP_SECRET) from environment."""
    cfg = Config.from_env()
    assert hasattr(cfg, "feishu_app_id"), "Config must have feishu_app_id attribute"
    assert hasattr(cfg, "feishu_app_secret"), (
        "Config must have feishu_app_secret attribute"
    )
    assert cfg.feishu_app_id == "cli_feishu_test_app_id"
    assert cfg.feishu_app_secret == "sec_feishu_test_app_secret"


def test_config_feishu_backward_compatibility(
    legacy_lark_env: pytest.MonkeyPatch,
) -> None:
    """Verify backward compatibility: fallback to LARK_APP_ID / LARK_APP_SECRET when FEISHU_* unset."""
    cfg = Config.from_env()
    feishu_id = getattr(cfg, "feishu_app_id", None) or getattr(cfg, "lark_app_id", None)
    feishu_secret = getattr(cfg, "feishu_app_secret", None) or getattr(
        cfg, "lark_app_secret", None
    )
    assert feishu_id == "cli_legacy_lark_app_id"
    assert feishu_secret == "sec_legacy_lark_app_secret"


def test_config_property_aliases(feishu_env: pytest.MonkeyPatch) -> None:
    """Verify property aliases: lark_app_id -> feishu_app_id, lark_app_secret -> feishu_app_secret."""
    cfg = Config.from_env()
    if hasattr(cfg, "feishu_app_id"):
        assert cfg.lark_app_id == cfg.feishu_app_id
        assert cfg.lark_app_secret == cfg.feishu_app_secret


def test_config_validate_channel_dingtalk(clean_env: pytest.MonkeyPatch) -> None:
    """Verify validate_channel('dingtalk') checks DD credentials."""
    cfg = Config.from_env()
    assert hasattr(cfg, "validate_channel"), (
        "Config must implement validate_channel(channel)"
    )

    # Should raise when DD creds are missing
    with pytest.raises(ValueError, match="DD_CLIENT_ID|钉钉"):
        cfg.validate_channel("dingtalk")

    # Should pass when DD creds are populated
    clean_env.setenv("DD_CLIENT_ID", "valid_client_id")
    clean_env.setenv("DD_CLIENT_SECRET", "valid_secret")
    valid_cfg = Config.from_env()
    valid_cfg.validate_channel("dingtalk")


def test_config_validate_channel_feishu(clean_env: pytest.MonkeyPatch) -> None:
    """Verify validate_channel('feishu') checks Feishu credentials."""
    cfg = Config.from_env()
    assert hasattr(cfg, "validate_channel"), (
        "Config must implement validate_channel(channel)"
    )

    # Should raise when Feishu creds are missing
    with pytest.raises(ValueError, match="FEISHU_APP_ID|LARK_APP_ID|飞书"):
        cfg.validate_channel("feishu")

    # Should pass when Feishu creds are populated
    clean_env.setenv("FEISHU_APP_ID", "cli_app_123")
    clean_env.setenv("FEISHU_APP_SECRET", "sec_456")
    valid_cfg = Config.from_env()
    valid_cfg.validate_channel("feishu")


def test_config_validate_channel_all(clean_env: pytest.MonkeyPatch) -> None:
    """Verify validate_channel('all') requires both DD and Feishu credentials."""
    clean_env.setenv("DD_CLIENT_ID", "dd_ok")
    clean_env.setenv("DD_CLIENT_SECRET", "dd_sec")
    cfg = Config.from_env()
    assert hasattr(cfg, "validate_channel"), (
        "Config must implement validate_channel(channel)"
    )

    # DingTalk present, Feishu missing -> should raise
    with pytest.raises(ValueError, match="FEISHU_APP_ID|LARK_APP_ID|飞书"):
        cfg.validate_channel("all")

    # Both present -> should pass
    clean_env.setenv("FEISHU_APP_ID", "fs_ok")
    clean_env.setenv("FEISHU_APP_SECRET", "fs_sec")
    valid_cfg = Config.from_env()
    valid_cfg.validate_channel("all")


def test_config_infer_default_channel_matrix(clean_env: pytest.MonkeyPatch) -> None:
    """Verify channel inference priority: DD priority > Feishu fallback > default dingtalk."""
    cfg_empty = Config.from_env()
    assert hasattr(cfg_empty, "infer_default_channel"), (
        "Config must implement infer_default_channel()"
    )

    # 1. Neither set -> default dingtalk
    assert cfg_empty.infer_default_channel() == "dingtalk"

    # 2. Only Feishu set -> feishu
    clean_env.setenv("FEISHU_APP_ID", "fs_id")
    clean_env.setenv("FEISHU_APP_SECRET", "fs_sec")
    cfg_fs = Config.from_env()
    assert cfg_fs.infer_default_channel() == "feishu"

    # 3. Both DD and Feishu set -> dingtalk (DD priority)
    clean_env.setenv("DD_CLIENT_ID", "dd_id")
    clean_env.setenv("DD_CLIENT_SECRET", "dd_sec")
    cfg_both = Config.from_env()
    assert cfg_both.infer_default_channel() == "dingtalk"
