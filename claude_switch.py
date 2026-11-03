"""Claude Code 多账号切换的核心逻辑（界面在 claude_switch_gui.pyw）。

原理：Claude Code 的登录信息在两个地方——
  ~/.claude/.credentials.json 里的 claudeAiOauth（令牌）
  ~/.claude.json 里的 oauthAccount（邮箱、组织等）
每个账号的这两段存到 ~/.claude-accounts/profiles/<邮箱>.json，切换时换回去。
MCP 登录（mcpOAuth）和其他设置不动，所有账号共用。

用量：其他账号只显示上次使用时记下的数据（usage-cache.json），不联网。
当前账号：设置里开了「联网查询」时，点「刷新」联网查一次（1 分钟最多 3 次）；
否则读 Claude Code 自己缓存在 ~/.claude.json 的用量。令牌只由 Claude Code 自己续期。
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
ONLINE_LOG = STORE / "online-log.json"

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"  # 和 Claude 插件面板查用量用的是同一个
ONLINE_LIMIT, ONLINE_WINDOW = 3, 60                      # 联网查询：1 分钟最多 3 次


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
    snapshot_usage()            # 切走前记下当前账号的用量
    email_now = save_current()  # 令牌会被 Claude Code 自动续期，切走前先存最新的
    if email_now and email_now.lower() == path.stem.lower():
        return

    shutil.copy2(CONF, STORE / "claude.json.bak")  # 留一份备份
    cred = load(CRED) if CRED.exists() else {}
    cred["claudeAiOauth"] = target["claudeAiOauth"]
    dump(CRED, cred)
    conf = load(CONF)
    conf["oauthAccount"] = target["oauthAccount"]
    dump(CONF, conf)


def http_json(url, token=None):
    headers = {"User-Agent": "claude-account-switch"}
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["anthropic-beta"] = "oauth-2025-04-20"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


_cache_lock = threading.Lock()


def remember_usage(email, usage, at, src):
    """存一份用量到 usage-cache.json；只在比已有的更新时才覆盖。src 是 "online" 或 "claude"。"""
    with _cache_lock:
        try:
            saved = load(USAGE_CACHE)
        except (OSError, ValueError):
            saved = {}
        old = saved.get(email.lower())
        if not old or old["at"] < at:
            saved[email.lower()] = {"usage": usage, "at": at, "src": src}
            STORE.mkdir(parents=True, exist_ok=True)
            dump(USAGE_CACHE, saved)


def online_wait():
    """联网查询限频：1 分钟最多 ONLINE_LIMIT 次。返回还要等几秒，0 表示现在可以查。
    记录存在文件里，重开程序也算数。"""
    now = time.time()
    try:
        log = [t for t in load(ONLINE_LOG) if now - t < ONLINE_WINDOW]
    except (OSError, ValueError, TypeError):
        log = []
    if len(log) < ONLINE_LIMIT:
        return 0
    return int(ONLINE_WINDOW - (now - min(log))) + 1


def fetch_current_usage():
    """联网查一次当前账号的用量（和 Claude 插件面板发的请求一样），结果存进 usage-cache.json。

    只查当前账号、只用还没过期的访问令牌，从不刷新令牌：刷新令牌是一次性的，
    换一次旧的就作废，还开着的 Claude Code 会话会因此掉线（「OAuth session expired」）。
    返回 (code, arg)：ok / limited(秒数) / wait / invalid / rate / http(状态码) / error(异常名) / none。
    """
    email, oauth, account = current()
    if not email:
        return "none", None
    if oauth.get("expiresAt", 0) < time.time() * 1000 + 60_000:
        return "wait", None  # 令牌过期了，等 Claude Code 自己续期
    wait = online_wait()
    if wait:
        return "limited", wait
    now = time.time()
    try:
        log = [t for t in load(ONLINE_LOG) if now - t < ONLINE_WINDOW]
    except (OSError, ValueError, TypeError):
        log = []
    STORE.mkdir(parents=True, exist_ok=True)
    dump(ONLINE_LOG, log + [now])
    try:
        usage = http_json(USAGE_URL, token=oauth["accessToken"])
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "invalid", None
        return ("rate", None) if e.code == 429 else ("http", e.code)
    except (OSError, ValueError, KeyError) as e:
        return "error", type(e).__name__
    remember_usage(email, usage, int(now), "online")
    return "ok", None


def snapshot_usage():
    """把 Claude Code 缓存里当前账号的用量记到 usage-cache.json（按邮箱）。

    Claude Code 自己查用量（比如在插件里输入 /usage）后会写进 ~/.claude.json 的
    cachedUsageUtilization；这里只是读出来另存一份，切到别的账号后还能看到。
    返回 True 表示缓存确实属于当前账号（显示为「最新」）。
    """
    try:
        conf = load(CONF)
    except (OSError, ValueError):
        return False
    account = conf.get("oauthAccount") or {}
    cache = conf.get("cachedUsageUtilization") or {}
    email = account.get("emailAddress")
    if not email or not cache.get("utilization") or cache.get("accountUuid") != account.get("accountUuid"):
        return False
    at = int((cache.get("fetchedAtMs") or 0) / 1000) or int(time.time())
    remember_usage(email, cache["utilization"], at, "claude")
    return True


def get_usage(email, is_current):
    """返回 (用量 dict 或 None, 来源, 数据时间戳)。只读本机文件，不联网。

    来源："online" = 刚联网查到的（当前账号）；"live" = Claude Code 缓存里的（当前账号）；
    "last" = 以前记下的；None = 没有数据。
    """
    live = snapshot_usage() if is_current else False
    try:
        hit = load(USAGE_CACHE).get(email.lower())
    except (OSError, ValueError):
        hit = None
    if not hit:
        return None, None, None
    if not is_current:
        source = "last"
    elif hit.get("src") == "online":
        source = "online"
    else:
        source = "live" if live else "last"
    return hit["usage"], source, hit["at"]


def load_settings():
    try:
        return load(SETTINGS)
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    STORE.mkdir(parents=True, exist_ok=True)
    dump(SETTINGS, settings)
