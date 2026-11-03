"""Claude Code 多账号切换的核心逻辑（界面在 claude_switch_gui.pyw）。

原理：Claude Code 的登录信息在两个地方——
  ~/.claude/.credentials.json 里的 claudeAiOauth（令牌）
  ~/.claude.json 里的 oauthAccount（邮箱、组织等）
每个账号的这两段存到 ~/.claude-accounts/profiles/<邮箱>.json，切换时换回去。
MCP 登录（mcpOAuth）和其他设置不动，所有账号共用。

用量：向 api.anthropic.com/api/oauth/usage 查询（和 Claude Code 里 /usage 同一个接口），
得到 5 小时额度、本周额度和各自的重置时间。非当前账号的令牌过期时会自动续期并存回。
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

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"  # Claude Code 的公开 client id


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


def refresh_profile(path, profile):
    """非当前账号的令牌过期了：用 refresh token 换新令牌，立即存回档案。"""
    oauth = profile["claudeAiOauth"]
    r = http_json(TOKEN_URL, body={
        "grant_type": "refresh_token",
        "refresh_token": oauth["refreshToken"],
        "client_id": CLIENT_ID,
        "scope": " ".join(oauth.get("scopes") or []),
    })
    oauth["accessToken"] = r["access_token"]
    oauth["refreshToken"] = r.get("refresh_token") or oauth["refreshToken"]
    oauth["expiresAt"] = int(time.time() * 1000) + int(r["expires_in"]) * 1000
    if r.get("refresh_token_expires_in"):
        oauth["refreshTokenExpiresAt"] = int(time.time() * 1000) + int(r["refresh_token_expires_in"]) * 1000
    dump(path, profile)


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
    """返回 (用量, 时间说明)：先用自己存的，再用 Claude Code 的缓存（只有当前账号有）。"""
    try:
        hit = load(USAGE_CACHE).get(email.lower())
    except (OSError, ValueError):
        hit = None
    if hit:
        return hit["usage"], time.strftime(" %m/%d %H:%M ", time.localtime(hit["at"]))
    if is_current:
        return cached_usage(profile), "上次缓存"
    return None, ""


def get_usage(path, is_current):
    """返回 (用量 dict 或 None, 说明文字, 本次是否自动续期了令牌)。"""
    if is_current:
        email, oauth, account = current()
        profile = {"claudeAiOauth": oauth, "oauthAccount": account}
    else:
        profile = load(path)
        oauth = profile["claudeAiOauth"]
    email = path.stem
    refreshed = False

    def fallback(reason):
        usage, when = last_usage(email, profile, is_current)
        return usage, (f"{reason}，显示{when}的数据" if usage else reason), refreshed

    try:
        if oauth["expiresAt"] < time.time() * 1000 + 60_000:
            if is_current:  # 当前账号由 Claude Code 自己续期，这里不碰，免得把它的令牌顶掉
                return fallback("令牌等插件续期")
            refresh_profile(path, profile)
            refreshed = True
            oauth = profile["claudeAiOauth"]
        usage = http_json(USAGE_URL, token=oauth["accessToken"])
        remember_usage(email, usage)
        return usage, "", refreshed
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            return None, "登录已失效，请在 Claude 插件里 /login 这个账号后点「刷新」", refreshed
        if e.code == 429:
            return fallback("查询太频繁被限流，稍后会自动重试")
        return fallback(f"查询失败（HTTP {e.code}）")
    except (OSError, ValueError, KeyError) as e:
        return fallback(f"查询失败（{type(e).__name__}）")
