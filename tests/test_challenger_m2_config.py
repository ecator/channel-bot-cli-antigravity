"""Empirical verification test suite by challenger_m2_1 (Config & Precedence Challenger).

Adversarially probes and stress-tests:
1. infer_default_channel across all combinations (DD only, Feishu only, Both, Neither,
   partial DD, partial Feishu, whitespace, fallback).
2. Environment precedence (FEISHU_* overriding LARK_*, whitespace fallbacks, domains).
3. validate_channel edge cases (case variations like DINGTALK/Feishu/ALL, whitespace padding,
   invalid channels, granular credential error messages).
4. Backward-compatible property setters, getters, __init__ kwargs, and validate() method.
5. CLI parsing and UTF-8 / BOM / stdin handling resilience.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from channel_bot_cli_antigravity.cli import (
    create_parser,
    read_stdin_content,
    resolve_send_message,
)
from channel_bot_cli_antigravity.config import Config, get_config, load_env_file


# ---------------------------------------------------------------------------
# Scope 1: infer_default_channel across all permutations
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("dd_id", "dd_sec", "feishu_id", "feishu_sec", "expected"),
    [
        # 1. DD only -> dingtalk
        ("dd_client_1", "dd_secret_1", "", "", "dingtalk"),
        # 2. Feishu only -> feishu
        ("", "", "feishu_app_1", "feishu_secret_1", "feishu"),
        # 3. Both complete -> dingtalk (priority)
        ("dd_client_1", "dd_secret_1", "feishu_app_1", "feishu_secret_1", "dingtalk"),
        # 4. Neither complete -> dingtalk (default fallback)
        ("", "", "", "", "dingtalk"),
        # 5. Partial DD only: id without secret -> neither complete -> dingtalk
        ("dd_client_1", "", "", "", "dingtalk"),
        # 6. Partial DD only: secret without id -> neither complete -> dingtalk
        ("", "dd_secret_1", "", "", "dingtalk"),
        # 7. Partial Feishu only: id without secret -> neither complete -> dingtalk
        ("", "", "feishu_app_1", "", "dingtalk"),
        # 8. Partial Feishu only: secret without id -> neither complete -> dingtalk
        ("", "", "", "feishu_secret_1", "dingtalk"),
        # 9. Partial DD + Complete Feishu -> feishu (DD incomplete, Feishu valid)
        ("dd_client_1", "", "feishu_app_1", "feishu_secret_1", "feishu"),
        ("", "dd_secret_1", "feishu_app_1", "feishu_secret_1", "feishu"),
        # 10. Complete DD + Partial Feishu -> dingtalk (DD complete wins)
        ("dd_client_1", "dd_secret_1", "feishu_app_1", "", "dingtalk"),
        ("dd_client_1", "dd_secret_1", "", "feishu_secret_1", "dingtalk"),
    ],
)
def test_infer_default_channel_permutations(
    dd_id: str, dd_sec: str, feishu_id: str, feishu_sec: str, expected: str
) -> None:
    """Exhaustively verify infer_default_channel across complete, partial, and empty credentials."""
    cfg = Config(
        dd_client_id=dd_id,
        dd_client_secret=dd_sec,
        feishu_app_id=feishu_id,
        feishu_app_secret=feishu_sec,
    )
    assert cfg.infer_default_channel() == expected


def test_infer_default_channel_from_legacy_kwargs() -> None:
    """infer_default_channel correctly recognizes credentials passed via legacy kwargs."""
    cfg_legacy = Config(lark_app_id="legacy_id", lark_app_secret="legacy_sec")
    assert cfg_legacy.infer_default_channel() == "feishu"

    cfg_both = Config(
        dd_client_id="dd_id",
        dd_client_secret="dd_sec",
        lark_app_id="legacy_id",
        lark_app_secret="legacy_sec",
    )
    assert cfg_both.infer_default_channel() == "dingtalk"


# ---------------------------------------------------------------------------
# Scope 2: Environment Precedence (FEISHU_* over LARK_*)
# ---------------------------------------------------------------------------
def test_env_precedence_feishu_overrides_lark(monkeypatch: pytest.MonkeyPatch) -> None:
    """FEISHU_* env variables must strictly override LARK_* env variables."""
    monkeypatch.setenv("FEISHU_APP_ID", "feishu_override_id")
    monkeypatch.setenv("LARK_APP_ID", "lark_legacy_id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "feishu_override_sec")
    monkeypatch.setenv("LARK_APP_SECRET", "lark_legacy_sec")
    monkeypatch.setenv("FEISHU_DOMAIN", "https://feishu.custom.cn")
    monkeypatch.setenv("LARK_DOMAIN", "https://lark.custom.com")

    cfg = Config.from_env()
    assert cfg.feishu_app_id == "feishu_override_id"
    assert cfg.lark_app_id == "feishu_override_id"
    assert cfg.feishu_app_secret == "feishu_override_sec"
    assert cfg.lark_app_secret == "feishu_override_sec"
    assert cfg.feishu_domain == "https://feishu.custom.cn"
    assert cfg.lark_domain == "https://feishu.custom.cn"


def test_env_precedence_fallback_to_lark_when_feishu_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When FEISHU_* is unset or empty, Config.from_env must fall back to LARK_*."""
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.delenv("FEISHU_DOMAIN", raising=False)

    monkeypatch.setenv("LARK_APP_ID", "lark_only_id")
    monkeypatch.setenv("LARK_APP_SECRET", "lark_only_sec")
    monkeypatch.setenv("LARK_DOMAIN", "https://open.larksuite.com")

    cfg = Config.from_env()
    assert cfg.feishu_app_id == "lark_only_id"
    assert cfg.feishu_app_secret == "lark_only_sec"
    assert cfg.feishu_domain == "https://open.larksuite.com"


def test_env_precedence_whitespace_feishu_falls_back_to_lark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace-only FEISHU_* env vars are stripped and correctly fall back to LARK_*."""
    monkeypatch.setenv("FEISHU_APP_ID", "   ")
    monkeypatch.setenv("LARK_APP_ID", "lark_fallback_id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "  \t  ")
    monkeypatch.setenv("LARK_APP_SECRET", "lark_fallback_sec")
    monkeypatch.setenv("FEISHU_DOMAIN", "   ")
    monkeypatch.setenv("LARK_DOMAIN", "https://open.feishu.cn")

    cfg = Config.from_env()
    assert cfg.feishu_app_id == "lark_fallback_id"
    assert cfg.feishu_app_secret == "lark_fallback_sec"
    assert cfg.feishu_domain == "https://open.feishu.cn"


def test_env_dingtalk_and_agy_model_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Config.from_env parses DD credentials, LOG_LEVEL, AGY_MODEL, and AGY_IMAGE_MODEL."""
    monkeypatch.setenv("DD_CLIENT_ID", "  dd_app_key  ")
    monkeypatch.setenv("DD_CLIENT_SECRET", "  dd_app_secret  ")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("AGY_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("AGY_IMAGE_MODEL", "imagen-3.0")

    cfg = Config.from_env()
    assert cfg.dd_client_id == "dd_app_key"
    assert cfg.dd_client_secret == "dd_app_secret"
    assert cfg.log_level == "DEBUG"
    assert cfg.agy_model == "gemini-2.5-flash"
    assert cfg.agy_image_model == "imagen-3.0"


def test_get_config_function(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_config() factory returns Config instance loaded from environment."""
    monkeypatch.setenv("DD_CLIENT_ID", "factory_dd_id")
    cfg = get_config()
    assert isinstance(cfg, Config)
    assert cfg.dd_client_id == "factory_dd_id"


# ---------------------------------------------------------------------------
# Scope 3: validate_channel Edge Cases & Case Normalization
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "channel_case",
    [
        "DINGTALK",
        "DingTalk",
        "dingtalk",
        "dInGtAlK",
        "  dingtalk  ",
        "  DINGTALK\t",
    ],
)
def test_validate_channel_dingtalk_case_insensitivity(channel_case: str) -> None:
    """validate_channel accepts all case and whitespace variants of 'dingtalk'."""
    cfg = Config(dd_client_id="id", dd_client_secret="sec")
    cfg.validate_channel(channel_case)  # should not raise


@pytest.mark.parametrize(
    "channel_case",
    [
        "FEISHU",
        "Feishu",
        "feishu",
        "fEiShU",
        "  feishu  ",
        "\tFEISHU  ",
    ],
)
def test_validate_channel_feishu_case_insensitivity(channel_case: str) -> None:
    """validate_channel accepts all case and whitespace variants of 'feishu'."""
    cfg = Config(feishu_app_id="id", feishu_app_secret="sec")
    cfg.validate_channel(channel_case)  # should not raise


@pytest.mark.parametrize(
    "channel_case",
    [
        "ALL",
        "All",
        "all",
        "aLl",
        "  all  ",
        "ALL\n",
    ],
)
def test_validate_channel_all_case_insensitivity(channel_case: str) -> None:
    """validate_channel accepts all case and whitespace variants of 'all'."""
    cfg = Config(
        dd_client_id="id",
        dd_client_secret="sec",
        feishu_app_id="fid",
        feishu_app_secret="fsec",
    )
    cfg.validate_channel(channel_case)  # should not raise


@pytest.mark.parametrize(
    "invalid_channel",
    [
        "unknown",
        "wechat",
        "slack",
        "qq",
        "lark",  # lark is not a canonical channel name for validate_channel
        "dd",  # dd is not canonical for validate_channel
        "",
        "   ",
        "123",
    ],
)
def test_validate_channel_unsupported_names_raise_value_error(
    invalid_channel: str,
) -> None:
    """Unsupported or non-canonical channel names raise ValueError."""
    cfg = Config(
        dd_client_id="id",
        dd_client_secret="sec",
        feishu_app_id="fid",
        feishu_app_secret="fsec",
    )
    with pytest.raises(ValueError) as exc_info:
        cfg.validate_channel(invalid_channel)
    assert "不支持的渠道类型" in str(exc_info.value)


def test_validate_channel_dingtalk_missing_error_messages() -> None:
    """validate_channel produces distinct, specific error messages for DingTalk."""
    # Both missing
    cfg_empty = Config()
    with pytest.raises(ValueError) as exc1:
        cfg_empty.validate_channel("dingtalk")
    assert "DD_CLIENT_ID" in str(exc1.value) and "DD_CLIENT_SECRET" in str(exc1.value)

    # Only secret missing
    cfg_no_sec = Config(dd_client_id="some_id")
    with pytest.raises(ValueError) as exc2:
        cfg_no_sec.validate_channel("dingtalk")
    assert "DD_CLIENT_SECRET" in str(exc2.value)

    # Only id missing
    cfg_no_id = Config(dd_client_secret="some_sec")
    with pytest.raises(ValueError) as exc3:
        cfg_no_id.validate_channel("dingtalk")
    assert "DD_CLIENT_ID" in str(exc3.value)


def test_validate_channel_feishu_missing_error_messages() -> None:
    """validate_channel produces distinct, specific error messages for Feishu."""
    # Both missing
    cfg_empty = Config()
    with pytest.raises(ValueError) as exc1:
        cfg_empty.validate_channel("feishu")
    assert "FEISHU_APP_ID" in str(exc1.value) and "FEISHU_APP_SECRET" in str(exc1.value)

    # Only secret missing
    cfg_no_sec = Config(feishu_app_id="some_id")
    with pytest.raises(ValueError) as exc2:
        cfg_no_sec.validate_channel("feishu")
    assert "FEISHU_APP_SECRET" in str(exc2.value)

    # Only id missing
    cfg_no_id = Config(feishu_app_secret="some_sec")
    with pytest.raises(ValueError) as exc3:
        cfg_no_id.validate_channel("feishu")
    assert "FEISHU_APP_ID" in str(exc3.value)


def test_validate_channel_all_requires_both_platforms() -> None:
    """validate_channel('all') enforces credentials for BOTH DingTalk and Feishu."""
    # DD present, Feishu missing -> fails
    cfg_dd_only = Config(dd_client_id="id", dd_client_secret="sec")
    with pytest.raises(ValueError) as exc1:
        cfg_dd_only.validate_channel("all")
    assert "FEISHU_APP_ID" in str(exc1.value)

    # Feishu present, DD missing -> fails
    cfg_feishu_only = Config(feishu_app_id="fid", feishu_app_secret="fsec")
    with pytest.raises(ValueError) as exc2:
        cfg_feishu_only.validate_channel("all")
    assert "DD_CLIENT_ID" in str(exc2.value)


# ---------------------------------------------------------------------------
# Scope 4: Backward-Compatible Property Setters, Getters & validate()
# ---------------------------------------------------------------------------
def test_backward_compatible_property_mutations() -> None:
    """Mutating legacy property setters updates canonical fields, and vice versa."""
    cfg = Config()

    # Mutate through legacy setters
    cfg.lark_app_id = "mutated_lark_id"
    assert cfg.feishu_app_id == "mutated_lark_id"
    assert cfg.lark_app_id == "mutated_lark_id"

    cfg.lark_app_secret = "mutated_lark_sec"
    assert cfg.feishu_app_secret == "mutated_lark_sec"
    assert cfg.lark_app_secret == "mutated_lark_sec"

    cfg.lark_domain = "https://mutated.domain"
    assert cfg.feishu_domain == "https://mutated.domain"
    assert cfg.lark_domain == "https://mutated.domain"

    # Mutate through canonical attributes
    cfg.feishu_app_id = "mutated_feishu_id"
    assert cfg.lark_app_id == "mutated_feishu_id"

    cfg.feishu_app_secret = "mutated_feishu_sec"
    assert cfg.lark_app_secret == "mutated_feishu_sec"

    cfg.feishu_domain = None
    assert cfg.lark_domain is None


def test_backward_compatible_validate_wrapper() -> None:
    """cfg.validate() delegates to validate_channel(infer_default_channel())."""
    # When DD configured, validate() checks DD
    cfg_dd = Config(dd_client_id="id", dd_client_secret="sec")
    cfg_dd.validate()  # passes

    # When DD missing, validate() raises DD error
    cfg_empty = Config()
    with pytest.raises(ValueError) as exc1:
        cfg_empty.validate()
    assert "DD_CLIENT_ID" in str(exc1.value)

    # When only Feishu configured, validate() checks Feishu
    cfg_feishu = Config(feishu_app_id="fid", feishu_app_secret="fsec")
    cfg_feishu.validate()  # passes


# ---------------------------------------------------------------------------
# Scope 5: CLI Parser & Stdin Handling Robustness
# ---------------------------------------------------------------------------
def test_cli_parser_channel_choices() -> None:
    """CLI subparsers accept appropriate channel arguments."""
    parser = create_parser()

    # send accepts dingtalk and feishu
    args_send = parser.parse_args(
        ["send", "--chat-id", "cid123", "--channel", "dingtalk", "-m", "hello"]
    )
    assert args_send.channel == "dingtalk"

    args_send_fs = parser.parse_args(
        ["send", "--chat-id", "cid123", "--channel", "feishu", "-m", "hello"]
    )
    assert args_send_fs.channel == "feishu"

    # send rejects "all"
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["send", "--chat-id", "cid123", "--channel", "all", "-m", "hello"]
        )

    # listen accepts dingtalk, feishu, and all
    args_listen_all = parser.parse_args(["listen", "--channel", "all"])
    assert args_listen_all.channel == "all"


def test_read_stdin_content_utf8_bom_removal() -> None:
    """read_stdin_content correctly strips UTF-8 BOM."""
    raw_bom_text = b"\xef\xbb\xbf\xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x8c\xe4\xb8\x96\xe7\x95\x8c\xf0\x9f\x9a\x80"
    mock_stdin = MagicMock()
    mock_stdin.buffer = io.BytesIO(raw_bom_text)
    mock_stdin.isatty.return_value = False

    with patch.object(sys, "stdin", mock_stdin):
        result = read_stdin_content()
    assert result == "你好，世界🚀"
    assert not result.startswith("\ufeff")


def test_resolve_send_message_stdin_and_dash() -> None:
    """resolve_send_message correctly processes -m '-' as stdin request."""
    parser = create_parser()
    args = parser.parse_args(["send", "--chat-id", "c1", "-m", "-"])

    with patch(
        "channel_bot_cli_antigravity.cli.read_stdin_content",
        return_value="piped content",
    ):
        msg = resolve_send_message(args)
    assert msg == "piped content"


def test_cli_main_validation_failure_returns_exit_code_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() prints error and returns 1 when credentials validation fails."""
    from channel_bot_cli_antigravity.cli import main

    # Clear all credentials
    for var in [
        "DD_CLIENT_ID",
        "DD_CLIENT_SECRET",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "LARK_APP_ID",
        "LARK_APP_SECRET",
    ]:
        monkeypatch.delenv(var, raising=False)

    exit_code = main(
        ["send", "--chat-id", "oc_123", "-m", "hello", "--channel", "dingtalk"]
    )
    assert exit_code == 1


def test_cli_main_version_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """main(['version']) prints package name and version; --short prints version only."""
    from channel_bot_cli_antigravity import __version__
    from channel_bot_cli_antigravity.cli import main

    res = main(["version"])
    assert res == 0
    captured = capsys.readouterr().out.strip()
    assert captured == f"channel-bot-cli-antigravity {__version__}"

    res_short = main(["version", "--short"])
    assert res_short == 0
    captured_short = capsys.readouterr().out.strip()
    assert captured_short == __version__


def test_load_env_file_missing_and_existing(tmp_path: Path) -> None:
    """load_env_file returns False for non-existent file, True for existing .env."""
    assert not load_env_file(tmp_path / "does_not_exist.env")

    env_file = tmp_path / ".env"
    env_file.write_text("TEST_KEY=TEST_VAL\n", encoding="utf-8")
    assert load_env_file(env_file)
    assert os.getenv("TEST_KEY") == "TEST_VAL"
