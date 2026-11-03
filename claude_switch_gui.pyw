"""Claude 账号切换 · 图形界面。

切换、用量查询、令牌续期的逻辑都在 claude_switch.py，这里只负责显示。
用 pythonw 运行就不会弹黑色命令行窗口。
"""

import base64
import ctypes
import os
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # 打包后资源在 _MEIPASS
sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_switch as cs  # noqa: E402

APP_VERSION = "1.0.1"
REPO_URL = "https://gitee.com/zhang-bantao/claude-account-switch"
SHORTCUT_NAME = "切换Claude账号.lnk"
FONT = "Microsoft YaHei UI"
WEEKDAYS = "一二三四五六日"

C = {
    "bg": "#F4F5F8",
    "card": "#FFFFFF",
    "border": "#E4E7EC",
    "hover": "#F2F4F7",
    "text": "#1D2939",
    "muted": "#667085",
    "faint": "#98A2B3",
    "track": "#EEF0F3",
    "accent": "#D97757",       # Claude 橙
    "accent_dark": "#C2613F",
    "green": "#12B76A",
    "amber": "#F79009",
    "red": "#F04438",
}
TONES = {  # (文字, 背景)
    "green": ("#067647", "#ECFDF3"),
    "amber": ("#B54708", "#FFFAEB"),
    "red": ("#B42318", "#FEF3F2"),
    "accent": ("#B34A2A", "#FDF1EC"),
    "blue": ("#175CD3", "#EFF8FF"),
}
AVATAR = ["#D97757", "#7A5AF8", "#2E90FA", "#12B76A", "#F79009", "#EE46BC"]


def collect():
    """在后台线程里跑：保存当前账号，查询所有账号的用量和令牌状态。"""
    cs.save_current()
    items = cs.profiles()
    now_email = (cs.current()[0] or "").lower()

    def one(p):
        is_cur = p.stem.lower() == now_email
        usage, note, refreshed = cs.get_usage(p, is_cur)
        try:
            oauth = (cs.current()[1] if is_cur else None) or cs.load(p)["claudeAiOauth"]
        except (OSError, ValueError, KeyError):
            oauth = {}
        return {"path": p, "email": p.stem, "current": is_cur, "usage": usage,
                "note": note, "refreshed": refreshed, "oauth": oauth}

    with ThreadPoolExecutor(max_workers=max(1, len(items))) as pool:
        return list(pool.map(one, items))


def ensure_shortcut():
    """打包成 exe 后第一次运行时在桌面建快捷方式。只建一次，用户删掉后不会再建。返回是否新建了。"""
    if not getattr(sys, "frozen", False):
        return False
    marker = cs.STORE / ".shortcut-created"
    if marker.exists():
        return False
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) != 0:  # 0x10 = 桌面
            return False
        exe = Path(sys.executable)
        # WScript.Shell 保存 .lnk 时路径会按 ANSI 转换，中文名可能失败：先存到临时英文名，再用 Python 改名
        tmp = Path(tempfile.gettempdir()) / "claude-switch-shortcut.lnk"
        q = lambda p: str(p).replace("'", "''")  # noqa: E731
        script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(tmp)}');"
                  f"$s.TargetPath='{q(exe)}';$s.WorkingDirectory='{q(exe.parent)}';"
                  f"$s.IconLocation='{q(exe)},0';$s.Save()")
        ps = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        subprocess.run(
            [str(ps), "-NoProfile", "-NonInteractive", "-EncodedCommand",
             base64.b64encode(script.encode("utf-16-le")).decode()],
            creationflags=0x08000000, timeout=30, check=True,  # 不弹命令行窗口
        )
        os.replace(tmp, Path(buf.value) / SHORTCUT_NAME)
        cs.STORE.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(exe), encoding="utf-8")
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def left_text(minutes):
    days, rem = divmod(max(0, minutes), 1440)
    h, m = divmod(rem, 60)
    if days:
        return f"{days}天{h}小时"
    return f"{h}小时{m:02d}分" if h else f"{m}分钟"


def reset_text(iso):
    t = datetime.fromisoformat(iso).astimezone()
    now = datetime.now().astimezone()
    minutes = int((t - now).total_seconds() // 60)
    if minutes < 0:
        return "已重置"
    when = f"{t:%H:%M}" if t.date() == now.date() else f"{t:%m/%d} 周{WEEKDAYS[t.weekday()]} {t:%H:%M}"
    return f"{when} 重置 · 还有 {left_text(minutes)}"


def level_color(pct):
    return C["green"] if pct < 60 else C["amber"] if pct < 85 else C["red"]


def score(a):
    """越小表示剩余额度越多；取 5 小时和本周里更紧张的那个。"""
    u = a["usage"] or {}
    vals = [(u.get(k) or {}).get("utilization") for k in ("five_hour", "seven_day")]
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


class App:
    def __init__(self, root):
        self.root = root
        self.dpi = root.winfo_fpixels("1i") / 96
        self.loading = False
        self.result = None
        self.placed = False
        self.data = None          # 上次查到的数据，本地每分钟重画倒计时用
        self.fetched_at = None    # 上次刷新时间

        root.title("Claude 账号切换")
        root.configure(bg=C["bg"])
        root.minsize(self.px(600), self.px(300))
        try:
            root.iconbitmap(default=str(HERE / "icon.ico"))
        except tk.TclError:
            pass

        self.build_header()
        self.banner = tk.Frame(root, bg=C["bg"])
        self.banner.pack(fill="x", padx=self.px(24))
        self.build_footer()
        # 卡片放在可滚动的 Canvas 里：账号多或屏幕矮（1366×768）时出现滚动条，而不是被截掉
        self.view = tk.Canvas(root, bg=C["bg"], highlightthickness=0)
        self.vbar = tk.Scrollbar(root, orient="vertical", command=self.view.yview)
        self.view.configure(yscrollcommand=self.vbar.set)
        self.view.pack(side="left", fill="both", expand=True, padx=(self.px(24), 0))
        self.cards = tk.Frame(self.view, bg=C["bg"])
        item = self.view.create_window(0, 0, window=self.cards, anchor="nw")
        # 窗口比卡片宽时（比如底部文字更长），让卡片跟着撑满
        self.view.bind("<Configure>", lambda e: self.view.itemconfigure(item, width=e.width))
        root.bind_all("<MouseWheel>", self.on_wheel)

        self.text(self.cards, "正在查询用量…", fg=C["muted"], bg=C["bg"]).pack(padx=self.px(220), pady=self.px(40))
        self.fit()
        self.refresh()
        self.root.after(60_000, self.tick)

        # 建快捷方式要启动 PowerShell，约 1～2 秒，放后台免得窗口卡住
        self.shortcut = None
        threading.Thread(target=lambda: setattr(self, "shortcut", ensure_shortcut()), daemon=True).start()
        self.poll_shortcut()

    def poll_shortcut(self):
        if self.shortcut is None:
            self.root.after(200, self.poll_shortcut)
        elif self.shortcut:
            self.show_banner("已在桌面创建「切换Claude账号」快捷方式，以后双击它就能打开。", "green")

    # ---------- 小工具 ----------
    def px(self, n):
        return int(round(n * self.dpi))

    def text(self, parent, s, size=10, bold=False, fg=None, bg=None, **kw):
        return tk.Label(parent, text=s, font=(FONT, size, "bold" if bold else "normal"),
                        fg=fg or C["text"], bg=bg or C["card"], **kw)

    def badge(self, parent, s, tone):
        fg, bg = TONES[tone]
        return tk.Label(parent, text=s, font=(FONT, 9), fg=fg, bg=bg,
                        padx=self.px(8), pady=self.px(1))

    def button(self, parent, s, cmd, kind="primary"):
        if kind == "primary":
            bg, fg, hover, border = C["accent"], "#FFFFFF", C["accent_dark"], C["accent"]
        else:
            bg, fg, hover, border = C["card"], C["text"], C["hover"], C["border"]
        b = tk.Label(parent, text=s, font=(FONT, 10), fg=fg, bg=bg, cursor="hand2",
                     padx=self.px(14), pady=self.px(5),
                     highlightthickness=1, highlightbackground=border)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(bg=hover))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        return b

    def bar(self, parent, pct, width=190, height=8):
        w, h = self.px(width), self.px(height)
        cv = tk.Canvas(parent, width=w, height=h, bg=C["card"], highlightthickness=0)
        r = h / 2
        cv.create_line(r, r, w - r, r, width=h, capstyle="round", fill=C["track"])
        if pct > 0:
            x = r + (w - h) * min(pct, 100) / 100
            cv.create_line(r, r, x, r, width=h, capstyle="round", fill=level_color(pct))
        return cv

    # ---------- 页面结构 ----------
    def build_header(self):
        head = tk.Frame(self.root, bg=C["bg"])
        head.pack(fill="x", padx=self.px(24), pady=(self.px(16), self.px(12)))

        s = self.px(40)
        logo = tk.Canvas(head, width=s, height=s, bg=C["bg"], highlightthickness=0)
        logo.create_oval(1, 1, s - 1, s - 1, fill=C["accent"], outline="")
        logo.create_text(s / 2, s / 2, text="C", fill="#FFFFFF", font=(FONT, 15, "bold"))
        logo.pack(side="left")

        titles = tk.Frame(head, bg=C["bg"])
        titles.pack(side="left", padx=(self.px(12), 0))
        self.text(titles, "Claude 账号切换", size=15, bold=True, bg=C["bg"]).pack(anchor="w")
        self.sub = self.text(titles, "", size=9, fg=C["muted"], bg=C["bg"])
        self.sub.pack(anchor="w")

        self.button(head, "刷新", self.refresh, kind="ghost").pack(side="right")

    def build_footer(self):
        foot = tk.Frame(self.root, bg=C["bg"])
        foot.pack(side="bottom", fill="x", padx=self.px(24), pady=(self.px(2), self.px(14)))
        # 右下角版本号，点击打开 Gitee 仓库
        ver = self.text(foot, f"v{APP_VERSION} · Gitee", size=9, fg=C["muted"], bg=C["bg"], cursor="hand2")
        ver.pack(side="right", anchor="s")
        ver.bind("<Button-1>", lambda e: webbrowser.open(REPO_URL))
        ver.bind("<Enter>", lambda e: ver.configure(fg=C["accent"], font=(FONT, 9, "underline")))
        ver.bind("<Leave>", lambda e: ver.configure(fg=C["muted"], font=(FONT, 9)))
        tips = ("添加账号：插件里 /login 新账号后点「刷新」 · 切换后在 VS Code 执行 Reload Window 生效\n"
                f"账号保存在 %USERPROFILE%\\{cs.STORE.name}（含登录令牌，不要发给别人）")
        self.text(foot, tips, size=9, fg=C["faint"], bg=C["bg"], justify="left").pack(side="left", anchor="w")

    def show_banner(self, msg, tone):
        for w in self.banner.winfo_children():
            w.destroy()
        fg, bg = TONES[tone]
        box = tk.Frame(self.banner, bg=bg, highlightthickness=1, highlightbackground=fg)
        box.pack(fill="x", pady=(0, self.px(10)))
        tk.Label(box, text=msg, font=(FONT, 10), fg=fg, bg=bg, justify="left",
                 wraplength=self.px(470)).pack(side="left", padx=self.px(14), pady=self.px(8))
        close = tk.Label(box, text="✕", font=(FONT, 10), fg=fg, bg=bg, cursor="hand2")
        close.pack(side="right", padx=self.px(12))
        close.bind("<Button-1>", lambda e: (box.destroy(), self.fit()))
        self.fit()

    def fit(self):
        """按内容定 Canvas 高度；超出屏幕就限高并显示滚动条，窗口底部不超出屏幕。"""
        self.root.update_idletasks()
        need_h, need_w = self.cards.winfo_reqheight(), self.cards.winfo_reqwidth()
        others = self.root.winfo_reqheight() - int(self.view.cget("height"))
        avail = self.root.winfo_screenheight() - self.px(100) - others  # 留出标题栏和任务栏
        h = max(self.px(160), min(need_h, avail))
        self.view.configure(width=need_w, height=h, scrollregion=(0, 0, need_w, need_h))
        if need_h > h:
            self.vbar.pack(side="right", fill="y", padx=(self.px(4), self.px(8)))
        else:
            self.vbar.pack_forget()
            self.view.yview_moveto(0)
        self.view.pack_configure(padx=(self.px(24), 0 if need_h > h else self.px(24)))
        self.root.update_idletasks()
        bottom = self.root.winfo_rooty() + self.root.winfo_reqheight()
        limit = self.root.winfo_screenheight() - self.px(60)
        if self.placed and bottom > limit:
            self.root.geometry(f"+{self.root.winfo_x()}+{max(0, self.root.winfo_y() - (bottom - limit))}")

    def on_wheel(self, e):
        if self.vbar.winfo_ismapped():
            self.view.yview_scroll(-1 * (e.delta // 120), "units")

    def card(self, i, a, best):
        cur = a["current"]
        outer = tk.Frame(self.cards, bg=C["accent"] if cur else C["border"])
        outer.pack(fill="x", pady=(0, self.px(10)))
        inner = tk.Frame(outer, bg=C["card"])
        inner.pack(fill="both", padx=(self.px(4) if cur else 1, 1), pady=1)
        body = tk.Frame(inner, bg=C["card"])
        # 当前账号左边有 4px 色条，其他卡片补 3px，让内容左右对齐
        body.pack(fill="x", padx=(self.px(18) if cur else self.px(18) + self.px(4) - 1, self.px(18)),
                  pady=self.px(12))

        # 第一行：头像 | 邮箱 + 标签 / 登录和令牌状态 | 按钮
        top = tk.Frame(body, bg=C["card"])
        top.pack(fill="x")
        s = self.px(34)
        av = tk.Canvas(top, width=s, height=s, bg=C["card"], highlightthickness=0)
        av.create_oval(1, 1, s - 1, s - 1, fill=AVATAR[i % len(AVATAR)], outline="")
        av.create_text(s / 2, s / 2, text=str(i + 1), fill="#FFFFFF", font=(FONT, 11, "bold"))
        av.pack(side="left")
        if cur:
            self.badge(top, "● 正在使用", "green").pack(side="right")
        else:
            self.button(top, "切换到这个账号", lambda: self.switch(a)).pack(side="right")

        info = tk.Frame(top, bg=C["card"])
        info.pack(side="left", padx=(self.px(10), 0))
        line1 = tk.Frame(info, bg=C["card"])
        line1.pack(anchor="w")
        self.text(line1, a["email"], size=11, bold=True).pack(side="left", padx=(0, self.px(8)))
        if best:
            self.badge(line1, "剩余额度最多", "blue").pack(side="left")
        line2 = tk.Frame(info, bg=C["card"])
        line2.pack(anchor="w")
        login, tone = self.login_text(a["oauth"])
        if login:
            self.text(line2, login, size=9, fg=TONES[tone][0] if tone else C["muted"]).pack(side="left")
        token = self.token_text(a)
        if token:
            self.text(line2, ("  ·  " if login else "") + token, size=9, fg=C["faint"]).pack(side="left")

        # 用量
        usage = a["usage"] or {}
        grid = tk.Frame(body, bg=C["card"])
        grid.pack(fill="x", pady=(self.px(10), 0))
        row = 0
        for key, name in (("five_hour", "5 小时"), ("seven_day", "本周")):
            u = usage.get(key)
            if not u or u.get("utilization") is None:
                continue
            pct = u["utilization"]
            pady = (self.px(4) if row else 0, 0)
            self.text(grid, name, size=10, fg=C["muted"]).grid(row=row, column=0, sticky="w", pady=pady)
            self.bar(grid, pct).grid(row=row, column=1, padx=(self.px(12), self.px(10)), pady=pady)
            self.text(grid, f"{pct:.0f}%", size=10, bold=True, fg=level_color(pct), width=4,
                      anchor="e").grid(row=row, column=2, sticky="e", pady=pady)
            reset = reset_text(u["resets_at"]) if u.get("resets_at") else ""
            if pct >= 100:
                reset = "已用完 · " + reset
            self.text(grid, reset, size=9, fg=C["muted"]).grid(row=row, column=3, sticky="w",
                                                               padx=(self.px(12), 0), pady=pady)
            row += 1
        if a["note"]:
            tone = "red" if "失效" in a["note"] or "失败" in a["note"] else "amber"
            self.text(body, a["note"], size=9, fg=TONES[tone][0], wraplength=self.px(500),
                      justify="left").pack(anchor="w", pady=(self.px(4), 0))

    def login_text(self, oauth):
        ms = oauth.get("refreshTokenExpiresAt")
        if not ms:
            return "", None
        t = datetime.fromtimestamp(ms / 1000)
        days = (t - datetime.now()).total_seconds() / 86400
        if days < 0:
            return f"登录已于 {t:%m/%d} 过期，请重新 /login", "red"
        if days < 3:
            return f"登录还剩 {days:.0f} 天，请尽快重新 /login", "amber"
        return f"登录还剩 {days:.0f} 天 · {t:%m/%d} 到期", None

    def token_text(self, a):
        ms = a["oauth"].get("expiresAt")
        if not ms:
            return ""
        t = datetime.fromtimestamp(ms / 1000)
        who = "插件自动续期" if a["current"] else "自动续期"
        if a["refreshed"]:
            return f"令牌刚刚已续期 · {t:%H:%M} 到期"
        if t < datetime.now():
            return f"令牌已过期 · {who}"
        return f"令牌 {t:%H:%M} 到期 · {who}"

    # ---------- 数据 ----------
    def refresh(self):
        if self.loading:
            return
        self.loading = True
        self.result = None
        self.sub.configure(text="正在查询用量…")

        def work():
            try:
                self.result = ("ok", collect())
            except Exception as e:  # 网络或文件问题都显示出来，不让窗口崩掉
                self.result = ("err", e)

        threading.Thread(target=work, daemon=True).start()
        self.poll()

    def poll(self):
        if self.result is None:
            self.root.after(100, self.poll)
            return
        self.loading = False
        kind, data = self.result
        if kind == "err":
            self.sub.configure(text=f"查询失败：{data}")
            return
        self.data, self.fetched_at = data, datetime.now()
        self.render(data)
        self.update_sub()

    def update_sub(self):
        if self.loading or not self.fetched_at:
            return
        minutes = int((datetime.now() - self.fetched_at).total_seconds() // 60)
        ago = "刚刚" if minutes < 1 else f"{left_text(minutes)}前"
        self.sub.configure(text=f"{self.fetched_at:%H:%M} 刷新（{ago}） · 点「刷新」获取最新用量")

    def tick(self):
        """每分钟只在本地更新「几分钟前」和倒计时，不联网；数据要用户点「刷新」才重新查询。"""
        if not self.loading and self.data is not None:
            self.render(self.data)
            self.update_sub()
        self.root.after(60_000, self.tick)

    def render(self, data):
        for w in self.cards.winfo_children():
            w.destroy()
        if not data:
            self.text(self.cards, "还没有保存任何账号。\n先在 Claude 插件里 /login，再点「刷新」。",
                      fg=C["muted"], bg=C["bg"]).pack(padx=self.px(150), pady=self.px(40))
            self.fit()
            return
        scored = [(score(a), i) for i, a in enumerate(data) if score(a) is not None]
        best = min(scored)[1] if len(scored) > 1 else None
        for i, a in enumerate(data):
            self.card(i, a, i == best)
        self.fit()
        if not self.placed:  # 第一次显示时居中
            self.placed = True
            self.root.update_idletasks()
            w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
            x = (self.root.winfo_screenwidth() - w) // 2
            y = max(0, (self.root.winfo_screenheight() - h) // 3)
            self.root.geometry(f"+{x}+{y}")

    def switch(self, a):
        try:
            cs.switch_to(a["path"])
        except Exception as e:
            self.show_banner(f"切换失败：{e}", "red")
            return
        self.show_banner(f"已切换到 {a['email']}。\n请在 VS Code 按 Ctrl+Shift+P → Developer: Reload Window，"
                         "重新加载后生效。", "green")
        self.refresh()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 高分屏下文字不发虚
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
