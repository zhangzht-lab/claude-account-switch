"""claude_switch.py 的单元测试。全部在临时目录里跑，不碰真实账号文件，也不联网。

运行：python -m unittest discover tests
"""

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import claude_switch as cs  # noqa: E402

FAR = 9e12  # 很远的将来（毫秒），表示令牌没过期


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class Base(unittest.TestCase):
    """把 claude_switch 里用到的路径都指到临时目录。"""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.saved = {k: getattr(cs, k) for k in
                      ("CRED", "CONF", "STORE", "PROFILES", "USAGE_CACHE", "SETTINGS", "ONLINE_LOG", "http_json")}
        cs.CRED = self.home / ".claude" / ".credentials.json"
        cs.CONF = self.home / ".claude.json"
        cs.STORE = self.home / ".claude-accounts"
        cs.PROFILES = cs.STORE / "profiles"
        cs.USAGE_CACHE = cs.STORE / "usage-cache.json"
        cs.SETTINGS = cs.STORE / "settings.json"
        cs.ONLINE_LOG = cs.STORE / "online-log.json"
        self.requests = []
        cs.http_json = lambda url, token=None: self.requests.append(token) or {"five_hour": {"utilization": 10}}

        self.A = {"accessToken": "a1", "refreshToken": "ra1", "refreshTokenExpiresAt": 111, "expiresAt": FAR}
        self.B = {"accessToken": "b1", "refreshToken": "rb1", "refreshTokenExpiresAt": 222, "expiresAt": FAR}
        write(cs.PROFILES / "a@x.com.json", {"claudeAiOauth": self.A, "oauthAccount": {"emailAddress": "a@x.com"}})
        write(cs.PROFILES / "b@x.com.json", {"claudeAiOauth": self.B, "oauthAccount": {"emailAddress": "b@x.com"}})

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(cs, k, v)
        shutil.rmtree(self.home, ignore_errors=True)

    def login(self, cred, email, **conf):
        write(cs.CRED, {"claudeAiOauth": cred, "mcpOAuth": {"keep": 1}})
        write(cs.CONF, {"oauthAccount": {"emailAddress": email, "accountUuid": email}, **conf})

    def profile_token(self, email):
        return cs.load(cs.PROFILES / f"{email}.json")["claudeAiOauth"]["accessToken"]


class MismatchTest(Base):
    def test_normal_refresh_is_saved(self):
        # Claude Code 续期后令牌变了，但登录有效期没变
        self.login({**self.B, "accessToken": "b2", "refreshToken": "rb2"}, "b@x.com")
        self.assertIsNone(cs.mismatch())
        self.assertEqual(cs.save_current(), "b@x.com")
        self.assertEqual(self.profile_token("b@x.com"), "b2")

    def test_stale_session_token_is_not_saved(self):
        # 没 Reload 的旧会话把 A 续期后的令牌写回，账号信息仍是 B
        self.login({**self.A, "accessToken": "a9", "refreshToken": "ra9"}, "b@x.com")
        self.assertEqual(cs.mismatch(), ("a@x.com", "b@x.com"))
        self.assertIsNone(cs.save_current())
        self.assertEqual(self.profile_token("b@x.com"), "b1")
        self.assertEqual(cs.fetch_current_usage(), ("mismatch", None))
        self.assertEqual(self.requests, [])

    def test_fresh_login_and_new_account(self):
        self.login({"accessToken": "b3", "refreshToken": "rb3", "refreshTokenExpiresAt": 333, "expiresAt": FAR}, "b@x.com")
        self.assertEqual(cs.save_current(), "b@x.com")
        self.login({"accessToken": "c1", "refreshToken": "rc1", "refreshTokenExpiresAt": 444, "expiresAt": FAR}, "c@x.com")
        self.assertEqual(cs.save_current(), "c@x.com")
        self.assertTrue((cs.PROFILES / "c@x.com.json").exists())

    def test_switch_fixes_mismatch_and_keeps_other_settings(self):
        self.login({**self.A, "accessToken": "a9"}, "b@x.com", numStartups=5)
        cs.switch_to(cs.PROFILES / "a@x.com.json")
        self.assertIsNone(cs.mismatch())
        self.assertEqual(cs.current()[0], "a@x.com")
        self.assertEqual(cs.load(cs.CONF)["numStartups"], 5)
        self.assertEqual(cs.load(cs.CRED)["mcpOAuth"], {"keep": 1})
        self.assertTrue((cs.STORE / "claude.json.bak").exists())


class OnlineTest(Base):
    def test_three_per_minute(self):
        self.login(self.A, "a@x.com")
        results = [cs.fetch_current_usage()[0] for _ in range(5)]
        self.assertEqual(results, ["ok", "ok", "ok", "limited", "limited"])
        self.assertEqual(len(self.requests), 3)

    def test_limit_window_slides(self):
        self.login(self.A, "a@x.com")
        write(cs.ONLINE_LOG, [time.time() - 61] * 3)  # 一分钟前的不算
        self.assertEqual(cs.fetch_current_usage()[0], "ok")

    def test_expired_token_is_never_refreshed(self):
        self.login({**self.A, "expiresAt": 0}, "a@x.com")
        self.assertEqual(cs.fetch_current_usage(), ("wait", None))
        self.assertEqual(self.requests, [])

    def test_result_is_cached_as_online(self):
        self.login(self.A, "a@x.com")
        cs.fetch_current_usage()
        usage, source, _ = cs.get_usage("a@x.com", True)
        self.assertEqual(source, "online")
        self.assertEqual(usage["five_hour"]["utilization"], 10)
        self.assertEqual(cs.get_usage("a@x.com", False)[1], "last")


class LocalUsageTest(Base):
    def test_snapshot_only_when_cache_belongs_to_current_account(self):
        cache = {"accountUuid": "someone-else", "fetchedAtMs": 1000, "utilization": {"five_hour": {"utilization": 50}}}
        self.login(self.A, "a@x.com", cachedUsageUtilization=cache)
        self.assertFalse(cs.snapshot_usage())
        self.assertEqual(cs.get_usage("a@x.com", True), (None, None, None))
        self.login(self.A, "a@x.com", cachedUsageUtilization={**cache, "accountUuid": "a@x.com"})
        self.assertTrue(cs.snapshot_usage())
        self.assertEqual(cs.get_usage("a@x.com", True)[1], "live")

    def test_watch_signature_ignores_unrelated_changes(self):
        self.login(self.A, "a@x.com", numStartups=1)
        sig = cs.watch_signature()
        self.login(self.A, "a@x.com", numStartups=2)
        self.assertEqual(cs.watch_signature(), sig)
        self.login(self.B, "b@x.com", numStartups=2)
        self.assertNotEqual(cs.watch_signature(), sig)


class AccountTest(Base):
    def test_alias_set_and_clear(self):
        cs.set_alias("A@x.com", "  工作号 ")
        self.assertEqual(cs.aliases(), {"a@x.com": "工作号"})
        cs.set_alias("a@x.com", "")
        self.assertEqual(cs.aliases(), {})

    def test_delete_account(self):
        self.login(self.A, "a@x.com")
        cs.remember_usage("b@x.com", {"five_hour": {}}, 1, "online")
        cs.set_alias("b@x.com", "备用")
        self.assertFalse(cs.delete_account("a@x.com"))  # 正在用的不能删
        self.assertTrue(cs.delete_account("b@x.com"))
        self.assertFalse((cs.PROFILES / "b@x.com.json").exists())
        self.assertNotIn("b@x.com", cs.load(cs.USAGE_CACHE))
        self.assertEqual(cs.aliases(), {})


if __name__ == "__main__":
    unittest.main()
