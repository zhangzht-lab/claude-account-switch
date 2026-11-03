"""Claude Code 多账号切换的核心逻辑（界面在 claude_switch_gui.pyw）。

原理：Claude Code 的登录信息在两个地方——
  ~/.claude/.credentials.json 里的 claudeAiOauth（令牌）
  ~/.claude.json 里的 oauthAccount（邮箱、组织等）
每个账号的这两段存到 ~/.claude-accounts/profiles/<邮箱>.json，切换时换回去。
MCP 登录（mcpOAuth）和其他设置不动，所有账号共用。

用量：向 api.anthropic.com/api/oauth/usage 查询（和 Claude Code 里 /usage 同一个接口），
得到 5 小时额度、本周额度和各自的重置时间。令牌只由 Claude Code 自己续期，本工具从不刷新令牌。
"""

import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
CRED = HOME / ".claude" / ".credentials.json"
CONF = HOME / ".claude.json"
STORE = HOME / ".claude-accounts"
PROFILES = STORE / "profiles"
USAGE_CACHE = STORE / "usage-cache.json"
SETTINGS = STORE / "settings.json"

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump(path, data):
    # 先写临时文件再替换，避免写一半损坏
    tmp = path.with_name(path.name + ".switch-tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def current():
    """返回 (邮箱, 令牌, 账号信息)；未登录时邮箱为 None。"""
    try:
        oauth = load(CRED).get("claudeAiOauth")
        account = load(CONF).get("oauthAccount")
    except FileNotFoundError:
        return None, None, None
    if not oauth or not account or not account.get("emailAddress"):
        return None, None, None
    return account["emailAddress"], oauth, account


def profiles():
    PROFILES.mkdir(parents=True, exist_ok=True)
    return sorted(PROFILES.glob("*.json"), key=lambda p: p.stem.lower())


def save_current():
    """把当前登录的账号存进档案（新账号就新增，老账号就更新令牌）。返回邮箱。"""
    email, oauth, account = current()
    if not email:
        return None
    PROFILES.mkdir(parents=True, exist_ok=True)
    dump(PROFILES / f"{email}.json", {"claudeAiOauth": oauth, "oauthAccount": account})
    return email


def switch_to(path):
    target = load(path)
    email_now = save_current()  # 令牌会自动刷新，切走前先存最新的
    if email_now and email_now.lower() == path.stem.lower():
        return

    shutil.copy2(CONF, STORE / "claude.json.bak")  # 留一份备份
    cred = load(CRED) if CRED.exists() else {}
    cred["claudeAiOauth"] = target["claudeAiOauth"]
    dump(CRED, cred)
    conf = load(CONF)
    conf["oauthAccount"] = target["oauthAccount"]
    dump(CONF, conf)


def http_json(url, token=None, body=None):
    headers = {"User-Agent": "claude-account-switch", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["anthropic-beta"] = "oauth-2025-04-20"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def cached_usage(profile):
    try:
        cache = load(CONF).get("cachedUsageUtilization") or {}
    except (OSError, ValueError):
        return None
    if cache.get("accountUuid") == profile["oauthAccount"].get("accountUuid"):
        return cache.get("utilization")
    return None


_cache_lock = threading.Lock()


def remember_usage(email, usage):
    """把查到的用量存到 usage-cache.json，下次查询失败（如被限流）时拿来顶上。"""
    with _cache_lock:
        try:
            cache = load(USAGE_CACHE)
        except (OSError, ValueError):
            cache = {}
        cache[email.lower()] = {"usage": usage, "at": int(time.time())}
        STORE.mkdir(parents=True, exist_ok=True)
        dump(USAGE_CACHE, cache)


def last_usage(email, profile, is_current):
    """返回 (用量, 数据时间)：先用自己存的（时间为秒级时间戳），再用 Claude Code 的缓存（时间为 "cache"）。"""
    try:
        hit = load(USAGE_CACHE).get(email.lower())
    except (OSError, ValueError):
        hit = None
    if hit:
        return hit["usage"], hit["at"]
    if is_current:
        return cached_usage(profile), "cache"
    return None, None


def get_usage(path, is_current):
    """返回 (用量 dict 或 None, 说明 或 None)。

    说明是 {"code": invalid|rate|http|error|wait|expired, "arg": ..., "stale": 时间戳|"cache"|None}，
    由界面按语言翻译；stale 不为 None 表示显示的是以前的数据。

    本工具从不用刷新令牌换新令牌：刷新令牌是一次性的，换一次旧的就作废，
    还开着的 Claude Code 会话手里的那份会失效，出现「OAuth session expired」要求重新登录。
    访问令牌过期了就显示上次的数据，等切换到这个账号后由 Claude Code 自己续期。
    """
    if is_current:
        email, oauth, account = current()
        profile = {"claudeAiOauth": oauth, "oauthAccount": account}
    else:
        profile = load(path)
        oauth = profile["claudeAiOauth"]
    email = path.stem

    def fallback(code, arg=None):
        usage, stale = last_usage(email, profile, is_current)
        return usage, {"code": code, "arg": arg, "stale": stale if usage else None}

    try:
        if oauth["expiresAt"] < time.time() * 1000 + 60_000:
            return fallback("wait" if is_current else "expired")
        usage = http_json(USAGE_URL, token=oauth["accessToken"])
        remember_usage(email, usage)
        return usage, None
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            return None, {"code": "invalid", "arg": None, "stale": None}
        if e.code == 429:
            return fallback("rate")
        return fallback("http", e.code)
    except (OSError, ValueError, KeyError) as e:
        return fallback("error", type(e).__name__)


def load_settings():
    try:
        return load(SETTINGS)
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    STORE.mkdir(parents=True, exist_ok=True)
    dump(SETTINGS, settings)
