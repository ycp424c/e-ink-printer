"""凭据解析：从本机现有配置读取各平台的访问凭据，不要求用户手动复制。

优先级（高 → 低）：
- 进程环境变量显式覆盖
- 项目本地 `.env` 显式覆盖（见 .env.example）
- cc-switch SQLite DB（`~/.cc-switch/cc-switch.db`）里的 provider `settings_config.env.ANTHROPIC_AUTH_TOKEN`
- `~/.codex/auth.json`（只读取 Codex access token 和 account ID，由 Codex 自身维护）

TokenHub 的腾讯云 API 密钥（SecretId/SecretKey）只从进程环境变量或 `.env`
读取，不做本机文件自动发现。

绝不把凭据写进日志、预览图或 git。
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

HOME = Path.home()
CC_SWITCH_DB = Path(os.environ.get("CC_SWITCH_DB", "~/.cc-switch/cc-switch.db")).expanduser()
CODEX_AUTH_JSON = Path(os.environ.get("CODEX_AUTH_JSON", "~/.codex/auth.json")).expanduser()
ENV_FILE = Path(__file__).resolve().parent / ".env"

# cc-switch providers 表里的展示名
PROVIDER_NAME_DEEPSEEK = "DeepSeek"
PROVIDER_NAME_KIMI = "Kimi For Coding"


def _load_dotenv() -> dict[str, str]:
    """极简 .env 解析（KEY=VALUE，忽略注释/空行）。"""
    if not ENV_FILE.exists():
        return {}
    overrides: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        overrides[key.strip()] = value.strip().strip('"').strip("'")
    return overrides


def _explicit_value(name: str) -> str | None:
    """读取显式配置；进程环境变量优先于项目本地 `.env`。"""
    return os.environ.get(name) or _load_dotenv().get(name)


def _cc_switch_key(provider_name: str) -> str | None:
    """从 cc-switch DB 读取指定 provider 的 ANTHROPIC_AUTH_TOKEN。"""
    try:
        conn = sqlite3.connect(f"file:{CC_SWITCH_DB}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT settings_config FROM providers WHERE name = ?",
                (provider_name,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        config = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    return (config.get("env") or {}).get("ANTHROPIC_AUTH_TOKEN")


def deepseek_api_key() -> str | None:
    if explicit := _explicit_value("DEEPSEEK_API_KEY"):
        return explicit
    return _cc_switch_key(PROVIDER_NAME_DEEPSEEK)


def kimi_api_key() -> str | None:
    if explicit := _explicit_value("KIMI_API_KEY"):
        return explicit
    return _cc_switch_key(PROVIDER_NAME_KIMI)


def tokenhub_credentials() -> dict:
    """返回 TokenHub 查询所需的腾讯云 API 密钥；缺失项为空字符串。"""
    return {
        "secret_id": _explicit_value("TENCENTCLOUD_SECRET_ID") or "",
        "secret_key": _explicit_value("TENCENTCLOUD_SECRET_KEY") or "",
        "team_id": _explicit_value("TOKENHUB_TEAM_ID") or "",
    }


def codex_tokens() -> dict:
    """只返回余额查询所需的 access token 和 account ID。"""
    if not CODEX_AUTH_JSON.exists():
        stored = {}
    else:
        try:
            auth = json.loads(CODEX_AUTH_JSON.read_text())
        except (json.JSONDecodeError, OSError):
            auth = {}
        stored = auth.get("tokens") or {}

    tokens = {
        key: stored[key]
        for key in ("access_token", "account_id")
        if stored.get(key)
    }
    if access := _explicit_value("CODEX_ACCESS_TOKEN"):
        tokens["access_token"] = access
    if account_id := _explicit_value("CODEX_ACCOUNT_ID"):
        tokens["account_id"] = account_id
    return tokens


def resolve_secrets_keys() -> list[str]:
    """只返回已解析到的凭据名称，用于验证（不暴露任何值）。"""
    keys: list[str] = []
    if deepseek_api_key():
        keys.append("DEEPSEEK_API_KEY")
    if kimi_api_key():
        keys.append("KIMI_API_KEY")
    tokens = codex_tokens()
    if tokens.get("access_token"):
        keys.append("CODEX_ACCESS_TOKEN")
    if tokens.get("account_id"):
        keys.append("CODEX_ACCOUNT_ID")
    tokenhub = tokenhub_credentials()
    if tokenhub.get("secret_id") and tokenhub.get("secret_key"):
        keys.append("TENCENTCLOUD_SECRET_ID")
        keys.append("TENCENTCLOUD_SECRET_KEY")
    if tokenhub.get("team_id"):
        keys.append("TOKENHUB_TEAM_ID")
    return keys


if __name__ == "__main__":
    found = resolve_secrets_keys()
    print("解析到凭据:", ", ".join(found) if found else "(无)")
