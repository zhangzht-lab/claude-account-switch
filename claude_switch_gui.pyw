"""Claude 账号切换 · 图形界面。

切换、用量查询的逻辑都在 claude_switch.py，界面文字在 i18n.py，这里只负责显示。
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
import tkinter.font as tkfont
from tkinter import messagebox
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # 打包后资源在 _MEIPASS
sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_switch as cs  # noqa: E402
from i18n import DEFAULT_LANG, LANGS, STRINGS  # noqa: E402

APP_VERSION = "1.2.1"
REPO_URL = "https://gitee.com/zhang-bantao/claude-account-switch"
RELEASES_URL = REPO_URL + "/releases"
LATEST_API = "https://gitee.com/api/v5/repos/zhang-bantao/claude-account-switch/releases/latest"
FONT = "Microsoft YaHei UI"
MIN_VISIBLE_CARDS = 2   # 窗口最矮时能看到的卡片数
MAX_VISIBLE_CARDS = 3   # 窗口最高时能看到的卡片数，更多的用滚动条

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
    "accent_soft": "#FDF1EC",
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

lang = DEFAULT_LANG
online = True   # 设置「联网查询当前账号用量」，保存在 settings.json 的 online
NOTE_CODES = ("wait", "invalid", "rate", "http", "error")  # 联网没查成时，在当前账号卡片上说明原因


def pick_font(root):
    """日语界面优先用日文字体（汉字字形是日式的），系统没有就退回雅黑。"""
    global FONT
    families = set(tkfont.families(root))
    wanted = ["Yu Gothic UI", "Meiryo UI"] if lang == "ja" else []
    FONT = next((f for f in wanted if f in families), "Microsoft YaHei UI")


def t(key, **kw):
    s = STRINGS[lang][key]
    return s.format(**kw) if kw else s


def collect():
    """在后台线程里跑：保存当前账号；开了联网查询就查一次当前账号的用量；再读出所有账号的数据。
    返回 (账号列表, 联网结果, 不一致)。联网结果是 cs.fetch_current_usage() 的 (code, arg)，没开为 ("off", None)；
    不一致是 cs.mismatch() 的结果（令牌和账号信息对不上时为 (令牌所属邮箱, 账号信息邮箱)）。"""
    mm = cs.mismatch()
    cs.save_current()  # 对不上时它自己会跳过，不保存
    fetch = cs.fetch_current_usage() if online else ("off", None)
    items = cs.profiles()
    now_email = (cs.current()[0] or "").lower()

    def one(p):
        is_cur = p.stem.lower() == now_email
        usage, source, at = cs.get_usage(p.stem, is_cur)
        try:
            # 对不上时当前令牌不是这个账号的，登录 / 令牌信息改用档案里的
            oauth = (cs.current()[1] if is_cur and not mm else None) or cs.load(p)["claudeAiOauth"]
        except (OSError, ValueError, KeyError):
            oauth = {}
        note = fetch if is_cur and fetch[0] in NOTE_CODES else None
        return {"path": p, "email": p.stem, "current": is_cur, "usage": usage,
                "source": source, "at": at, "oauth": oauth, "note": note}

    with ThreadPoolExecutor(max_workers=max(1, len(items))) as pool:
        return list(pool.map(one, items)), fetch, mm


def ensure_shortcut():
    """打包成 exe 后第一次运行时在桌面建快捷方式。只建一次，用户删掉后不会再建。返回快捷方式名，没建返回 None。"""
    if not getattr(sys, "frozen", False):
        return None
    marker = cs.STORE / ".shortcut-created"
    if marker.exists():
        return None
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) != 0:  # 0x10 = 桌面
            return None
        exe = Path(sys.executable)
        name = t("shortcut_name")
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
        os.replace(tmp, Path(buf.value) / name)
        cs.STORE.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(exe), encoding="utf-8")
        return Path(name).stem
    except (OSError, subprocess.SubprocessError):
        return None


def left_text(minutes):
    days, rem = divmod(max(0, minutes), 1440)
    h, m = divmod(rem, 60)
    if days:
        return t("dur_days", d=days, h=h)
    return t("dur_hours", h=h, m=m) if h else t("dur_mins", m=m)


def reset_text(iso):
    when_t = datetime.fromisoformat(iso).astimezone()
    now = datetime.now().astimezone()
    minutes = int((when_t - now).total_seconds() // 60)
    if minutes < 0:
        return t("reset_done")
    hm = f"{when_t:%H:%M}"
    when = hm if when_t.date() == now.date() else t(
        "date_fmt", md=f"{when_t:%m/%d}", wd=t("weekdays")[when_t.weekday()], hm=hm)
    return t("reset_at", when=when, left=left_text(minutes))


def window_pct(u):
    """返回 (百分比, 是否已过重置时间)。数据是以前记下的，过了重置时间时进度条清空、
    界面显示「已重置」；排「剩余额度最多」时按 0% 算（额度已经恢复）。"""
    if not u or u.get("utilization") is None:
        return None, False
    if u.get("resets_at") and datetime.fromisoformat(u["resets_at"]).astimezone() <= datetime.now().astimezone():
        return 0, True
    return u["utilization"], False


def level_color(pct):
    return C["green"] if pct < 60 else C["amber"] if pct < 85 else C["red"]


def score(a):
    """越小表示剩余额度越多；取 5 小时和本周里更紧张的那个。"""
    u = a["usage"] or {}
    vals = [window_pct(u.get(k))[0] for k in ("five_hour", "seven_day")]
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


def version_tuple(v):
    return tuple(int(x) for x in v.lstrip("vV").split(".") if x.isdigit())


class Widgets:
    """主窗口和设置窗口共用的小控件。"""

    def px(self, n):
        return int(round(n * self.dpi))

    def text(self, parent, s, size=10, bold=False, fg=None, bg=None, **kw):
        return tk.Label(parent, text=s, font=(FONT, size, "bold" if bold else "normal"),
                        fg=fg or C["text"], bg=bg or C["card"], **kw)

    def badge(self, parent, s, tone):
        fg, bg = TONES[tone]
        return tk.Label(parent, text=s, font=(FONT, 9), fg=fg, bg=bg,
                        padx=self.px(8), pady=self.px(1))

    def button(self, parent, s, cmd, kind="primary", size=10):
        if kind == "primary":
            bg, fg, hover, border = C["accent"], "#FFFFFF", C["accent_dark"], C["accent"]
        else:
            bg, fg, hover, border = C["card"], C["text"], C["hover"], C["border"]
        b = tk.Label(parent, text=s, font=(FONT, size), fg=fg, bg=bg, cursor="hand2",
                     padx=self.px(14), pady=self.px(5),
                     highlightthickness=1, highlightbackground=border)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(bg=hover))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        return b

    def logo(self, parent, size, bg):
        s = self.px(size)
        cv = tk.Canvas(parent, width=s, height=s, bg=bg, highlightthickness=0)
        cv.create_oval(1, 1, s - 1, s - 1, fill=C["accent"], outline="")
        cv.create_text(s / 2, s / 2, text="C", fill="#FFFFFF", font=(FONT, int(size * 0.37), "bold"))
        return cv


class App(Widgets):
    def __init__(self, root):
        self.root = root
        self.dpi = root.winfo_fpixels("1i") / 96
        self.loading = False
        self.result = None
        self.placed = False
        self.data = None          # 上次查到的数据，本地每分钟重画倒计时、切换语言后重画用
        self.fetched_at = None    # 上次刷新时间
        self.settings_win = None

        root.configure(bg=C["bg"])
        root.minsize(self.px(600), self.px(300))
        try:
            root.iconbitmap(default=str(HERE / "icon.ico"))
        except tk.TclError:
            pass
        root.bind_all("<MouseWheel>", self.on_wheel)

        self.build()
        self.refresh()
        self.root.after(60_000, self.tick)

        # 建快捷方式要启动 PowerShell，约 1～2 秒，放后台免得窗口卡住
        self.shortcut = False
        threading.Thread(target=lambda: setattr(self, "shortcut", ensure_shortcut()), daemon=True).start()
        self.poll_shortcut()

    def poll_shortcut(self):
        if self.shortcut is False:
            self.root.after(200, self.poll_shortcut)
        elif self.shortcut:
            self.show_banner(t("shortcut_created", name=self.shortcut), "green")

    # ---------- 页面结构 ----------
    def build(self):
        """建整个主界面；切换语言时会整体重建。"""
        for w in self.root.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        pick_font(self.root)
        self.root.title(t("title"))
        self.build_header()
        self.toast = None
        self.build_footer()
        # 卡片放在可滚动的 Canvas 里：账号多或屏幕矮（1366×768）时出现滚动条，而不是被截掉
        self.view = tk.Canvas(self.root, bg=C["bg"], highlightthickness=0)
        self.vbar = tk.Scrollbar(self.root, orient="vertical", command=self.view.yview)
        self.view.configure(yscrollcommand=self.vbar.set)
        self.view.pack(side="left", fill="both", expand=True, padx=(self.px(24), self.px(24)))
        self.view_need = 0
        self.cards = tk.Frame(self.view, bg=C["bg"])
        self.view_item = self.view.create_window(0, 0, window=self.cards, anchor="nw")
        self.view.bind("<Configure>", self.on_view_resize)

        if self.data is None:
            self.text(self.cards, t("loading"), fg=C["muted"], bg=C["bg"]).pack(
                padx=self.px(220), pady=self.px(40))
            self.fit()
        else:
            self.render(self.data)
        if self.loading:
            self.sub.configure(text=t("loading"))
        else:
            self.update_sub()

    def build_header(self):
        head = tk.Frame(self.root, bg=C["bg"])
        head.pack(fill="x", padx=self.px(24), pady=(self.px(16), self.px(12)))
        self.logo(head, 40, C["bg"]).pack(side="left")
        titles = tk.Frame(head, bg=C["bg"])
        titles.pack(side="left", padx=(self.px(12), 0))
        self.text(titles, t("title"), size=15, bold=True, bg=C["bg"]).pack(anchor="w")
        self.sub = self.text(titles, "", size=9, fg=C["muted"], bg=C["bg"])
        self.sub.pack(anchor="w")
        self.button(head, t("refresh"), self.refresh, kind="ghost").pack(side="right")

    def build_footer(self):
        foot = tk.Frame(self.root, bg=C["bg"])
        foot.pack(side="bottom", fill="x", padx=self.px(24), pady=(self.px(2), self.px(14)))
        self.settings_btn = self.button(foot, "⚙ " + t("settings"), self.open_settings, kind="ghost", size=9)
        self.settings_btn.pack(side="right", anchor="s")
        tips = t("footer") + "\n" + t("footer_online" if online else "footer_local")
        self.tips = self.text(foot, tips, size=9, fg=C["faint"], bg=C["bg"], justify="left")
        self.tips.pack(side="left", anchor="w")

    def show_banner(self, msg, tone, seconds=3, kind=None):
        """提示条放在账号列表上方，倒计时结束自动消失；seconds=None 时一直显示，直到点 ✕。

        出现时卡片区相应变矮（多出的卡片用滚动条看），消失后再恢复，所以窗口大小始终不变（见 fit）。
        kind 用来认出某一类提示（比如账号不一致的警告），好在问题消失后自动关掉。
        """
        self.hide_banner(refit=False)
        fg, bg = TONES[tone]
        box = tk.Frame(self.root, bg=bg, highlightthickness=1, highlightbackground=fg)
        box.kind = kind
        self.toast = box
        right = tk.Frame(box, bg=bg)
        right.pack(side="right", padx=(0, self.px(12)))
        close = tk.Label(right, text="✕", font=(FONT, 10), fg=fg, bg=bg, cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.hide_banner(box))
        count = tk.Label(right, font=(FONT, 9), fg=fg, bg=bg)
        count.pack(side="right", padx=(0, self.px(10)))
        width = max(self.px(300), self.root.winfo_width() - self.px(48 + 150))  # 右边留给倒计时和 ✕
        tk.Label(box, text=msg, font=(FONT, 10), fg=fg, bg=bg, justify="left",
                 wraplength=width).pack(side="left", padx=self.px(14), pady=self.px(8))
        box.pack(fill="x", padx=self.px(24), pady=(0, self.px(10)), before=self.view)
        self.fit()

        def tick(n):
            if self.toast is not box or not box.winfo_exists():
                return
            if n <= 0:
                self.hide_banner(box)
                return
            count.configure(text=t("toast_countdown", n=n))
            box.after(1000, tick, n - 1)

        if seconds is not None:
            tick(seconds)

    def hide_banner(self, box=None, refit=True):
        """关掉提示条；传了 box 时只关这一条（避免旧倒计时关掉新提示）。"""
        if self.toast is None or (box is not None and box is not self.toast):
            return
        if self.toast.winfo_exists():
            self.toast.destroy()
        self.toast = None
        if refit:
            self.fit()

    def fit(self):
        """卡片区高度在「2 张卡片」到「3 张卡片」之间：窗口只能在这个范围内拉高缩矮，
        放不下的卡片一律用滚动条看。屏幕太矮时上限再缩，窗口底部不超出屏幕。"""
        self.root.update_idletasks()
        need_h, need_w = self.cards.winfo_reqheight(), self.cards.winfo_reqwidth()
        # 底部说明按卡片宽度换行，免得把窗口撑宽或和设置按钮重叠
        self.tips.configure(wraplength=max(self.px(280), need_w - self.settings_btn.winfo_reqwidth() - self.px(16)))
        self.root.update_idletasks()
        # 提示条占的高度从卡片区里扣，窗口总高度不变
        toast_h = self.toast.winfo_reqheight() + self.px(10) if self.toast and self.toast.winfo_exists() else 0
        others = self.root.winfo_reqheight() - int(self.view.cget("height")) - toast_h
        avail = self.root.winfo_screenheight() - self.px(100) - others  # 留出标题栏和任务栏
        if self.data:  # 账号卡片
            heights = [c.winfo_reqheight() + self.px(10) for c in self.cards.winfo_children()]
            lo, hi = sum(heights[:MIN_VISIBLE_CARDS]), sum(heights[:MAX_VISIBLE_CARDS])
        else:  # 「正在查询」「还没有账号」这类提示
            lo = hi = need_h
        hi = max(self.px(120), min(hi, avail))
        lo = min(lo, hi)
        self.view_need = need_h
        self.view.configure(width=need_w, height=max(self.px(40), hi - toast_h),
                            scrollregion=(0, 0, need_w, need_h))
        self.root.update_idletasks()
        self.root.minsize(self.root.winfo_reqwidth(), others + lo)
        self.root.maxsize(self.root.winfo_screenwidth(), others + hi)
        self.update_scrollbar()
        self.root.update_idletasks()
        bottom = self.root.winfo_rooty() + self.root.winfo_reqheight()
        limit = self.root.winfo_screenheight() - self.px(60)
        if self.placed and bottom > limit:
            self.root.geometry(f"+{self.root.winfo_x()}+{max(0, self.root.winfo_y() - (bottom - limit))}")

    def update_scrollbar(self, height=None):
        """按卡片区实际高度决定要不要滚动条（拉伸窗口时也会调用）。"""
        h = height or self.view.winfo_height()
        if h <= 1:  # 还没显示出来时用设定高度
            h = int(self.view.cget("height"))
        need = self.view_need > h + 1
        if need and not self.vbar.winfo_ismapped():
            # 滚动条 + 两侧间距正好等于原来的右边距，出现/消失时窗口宽度不变
            right = max(0, self.px(24) - self.px(4) - self.vbar.winfo_reqwidth())
            self.vbar.pack(side="right", fill="y", padx=(self.px(4), right), before=self.view)
            self.view.pack_configure(padx=(self.px(24), 0))
        elif not need and self.vbar.winfo_ismapped():
            self.vbar.pack_forget()
            self.view.pack_configure(padx=(self.px(24), self.px(24)))
            self.view.yview_moveto(0)

    def on_view_resize(self, e):
        self.view.itemconfigure(self.view_item, width=e.width)  # 窗口比卡片宽时，让卡片跟着撑满
        self.update_scrollbar(e.height)

    def on_wheel(self, e):
        if self.vbar.winfo_exists() and self.vbar.winfo_ismapped():
            self.view.yview_scroll(-1 * (e.delta // 120), "units")

    def bar(self, parent, pct, width=190, height=8):
        w, h = self.px(width), self.px(height)
        cv = tk.Canvas(parent, width=w, height=h, bg=C["card"], highlightthickness=0)
        r = h / 2
        cv.create_line(r, r, w - r, r, width=h, capstyle="round", fill=C["track"])
        if pct > 0:
            x = r + (w - h) * min(pct, 100) / 100
            cv.create_line(r, r, x, r, width=h, capstyle="round", fill=level_color(pct))
        return cv

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
            self.badge(top, t("in_use"), "green").pack(side="right")
        else:
            self.button(top, t("switch_btn"), lambda: self.switch(a)).pack(side="right")

        info = tk.Frame(top, bg=C["card"])
        info.pack(side="left", padx=(self.px(10), 0))
        line1 = tk.Frame(info, bg=C["card"])
        line1.pack(anchor="w")
        self.text(line1, a["email"], size=11, bold=True).pack(side="left", padx=(0, self.px(8)))
        if best:
            self.badge(line1, t("best"), "blue").pack(side="left")
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
        for key in ("five_hour", "seven_day"):
            u = usage.get(key)
            pct, was_reset = window_pct(u)
            if pct is None:
                continue
            pady = (self.px(4) if row else 0, 0)
            name = t("five_hour" if key == "five_hour" else "week")
            self.text(grid, name, size=10, fg=C["muted"]).grid(row=row, column=0, sticky="w", pady=pady)
            self.bar(grid, pct).grid(row=row, column=1, padx=(self.px(12), self.px(10)), pady=pady)
            # 过了重置时间：旧数据已经不准，不显示百分比，只写「已重置」
            self.text(grid, "—" if was_reset else f"{pct:.0f}%", size=10, bold=True,
                      fg=C["faint"] if was_reset else level_color(pct), width=4,
                      anchor="e").grid(row=row, column=2, sticky="e", pady=pady)
            if was_reset:
                reset = t("reset_since")
            else:
                reset = reset_text(u["resets_at"]) if u.get("resets_at") else ""
                if pct >= 100:
                    reset = t("used_up") + reset
            self.text(grid, reset, size=9, fg=C["muted"]).grid(row=row, column=3, sticky="w",
                                                               padx=(self.px(12), 0), pady=pady)
            row += 1

        # 数据来源：标明是哪里、哪个时间的数据
        if a["source"]:
            at = datetime.fromtimestamp(a["at"])
            when = f"{at:%H:%M}" if at.date() == datetime.now().date() else f"{at:%m/%d %H:%M}"
            src = t("src_" + a["source"], at=when)
            fg = C["faint"]
        else:
            src, fg = t("src_none"), TONES["amber"][0]
        self.text(body, src, size=9, fg=fg, wraplength=self.px(520), justify="left").pack(
            anchor="w", pady=(self.px(6) if row else 0, 0))
        if a.get("note"):  # 这次联网没查成的原因
            code, arg = a["note"]
            self.text(body, t("note_" + code, arg=arg), size=9, fg=TONES["amber"][0],
                      wraplength=self.px(520), justify="left").pack(anchor="w")

    def login_text(self, oauth):
        ms = oauth.get("refreshTokenExpiresAt")
        if not ms:
            return "", None
        end = datetime.fromtimestamp(ms / 1000)
        days = (end - datetime.now()).total_seconds() / 86400
        if days < 0:
            return t("login_expired", d=f"{end:%m/%d}"), "red"
        if days < 3:
            return t("login_soon", n=f"{days:.0f}"), "amber"
        return t("login_ok", n=f"{days:.0f}", d=f"{end:%m/%d}"), None

    def token_text(self, a):
        ms = a["oauth"].get("expiresAt")
        if not ms:
            return ""
        end = datetime.fromtimestamp(ms / 1000)
        who = t("renew_plugin") if a["current"] else t("renew_auto")
        if end < datetime.now():
            return t("token_expired", who=who)
        return t("token_ok", t=f"{end:%H:%M}", who=who)

    # ---------- 数据 ----------
    def refresh(self):
        if self.loading:
            return
        self.loading = True
        self.result = None
        self.sub.configure(text=t("loading"))

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
        kind, val = self.result
        if kind == "err":
            self.sub.configure(text=t("load_failed", e=val))
            return
        data, (code, arg), mm = val
        self.data, self.fetched_at = data, datetime.now()
        self.render(data)
        self.update_sub()
        if mm:  # 一直显示，直到问题解决
            self.show_banner(t("mismatch", owner=mm[0], email=mm[1]), "red", seconds=None, kind="mismatch")
        elif self.toast is not None and getattr(self.toast, "kind", None) == "mismatch":
            self.hide_banner()
        if code == "limited" and not mm:
            self.show_banner(t("online_limited", s=arg), "amber")

    def update_sub(self):
        if self.loading or not self.fetched_at:
            return
        minutes = int((datetime.now() - self.fetched_at).total_seconds() // 60)
        ago = t("just_now") if minutes < 1 else t("ago", x=left_text(minutes))
        self.sub.configure(text=t("fetched", time=f"{self.fetched_at:%H:%M}", ago=ago))

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
            self.text(self.cards, t("empty"), fg=C["muted"], bg=C["bg"]).pack(
                padx=self.px(150), pady=self.px(40))
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
        # Claude Code 运行时也会写这两个文件，同时写可能互相覆盖：先提醒一下
        if cs.claude_running() and not messagebox.askokcancel(
                t("confirm_title"), t("confirm_running", email=a["email"]), parent=self.root):
            return
        try:
            cs.switch_to(a["path"])
        except Exception as e:
            self.show_banner(t("switch_failed", e=e), "red")
            return
        self.show_banner(t("switched", email=a["email"]), "green")
        self.refresh()

    # ---------- 设置 ----------
    def open_settings(self, page="general"):
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.lift()
            self.settings_win.focus_force()
            return
        self.settings_win = SettingsWindow(self, page)

    def set_lang(self, new):
        global lang
        if new == lang:
            return
        lang = new
        cs.save_settings({**cs.load_settings(), "lang": new})
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.close()
        self.build()
        self.open_settings("general")

    def set_online(self, on):
        global online
        if on == online:
            return
        online = on
        cs.save_settings({**cs.load_settings(), "online": on})
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.close()
        self.build()  # 底部说明随开关变
        self.open_settings("general")


class SettingsWindow(tk.Toplevel, Widgets):
    """设置窗口：左侧边栏（常规 / 关于），右侧内容。模态，关掉才能回主窗口操作。"""

    def __init__(self, app, page):
        super().__init__(app.root, bg=C["card"])
        self.app, self.dpi = app, app.dpi
        self.title(t("settings"))
        self.resizable(False, False)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.update_result = None

        w, h = self.px(600), self.px(380)
        root = app.root
        x = root.winfo_rootx() + (root.winfo_width() - w) // 2
        y = root.winfo_rooty() + max(0, (root.winfo_height() - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")

        side = tk.Frame(self, bg=C["bg"], width=self.px(160))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(self, bg=C["border"], width=1).pack(side="left", fill="y")
        self.content = tk.Frame(self, bg=C["card"])
        self.content.pack(side="left", fill="both", expand=True)

        tk.Frame(side, bg=C["bg"], height=self.px(16)).pack()
        self.nav = {}
        for key, label in (("general", t("nav_general")), ("about", t("nav_about"))):
            item = tk.Frame(side, bg=C["bg"], cursor="hand2")
            item.pack(fill="x", padx=self.px(10), pady=(0, self.px(4)))
            mark = tk.Frame(item, bg=C["bg"], width=self.px(3))
            mark.pack(side="left", fill="y")
            lb = tk.Label(item, text=label, font=(FONT, 10), bg=C["bg"], fg=C["text"], anchor="w",
                          padx=self.px(12), pady=self.px(7), cursor="hand2")
            lb.pack(side="left", fill="x", expand=True)
            for wdg in (item, lb):
                wdg.bind("<Button-1>", lambda e, k=key: self.show(k))
            self.nav[key] = (item, mark, lb)
        self.show(page)
        self.grab_set()
        self.focus_force()

    def close(self):
        self.grab_release()
        self.destroy()

    def show(self, page):
        for key, (item, mark, lb) in self.nav.items():
            on = key == page
            bg = C["accent_soft"] if on else C["bg"]
            item.configure(bg=bg)
            lb.configure(bg=bg, fg=C["accent_dark"] if on else C["text"],
                         font=(FONT, 10, "bold" if on else "normal"))
            mark.configure(bg=C["accent"] if on else bg)
        for w in self.content.winfo_children():
            w.destroy()
        body = tk.Frame(self.content, bg=C["card"])
        body.pack(fill="both", expand=True, padx=self.px(28), pady=self.px(22))
        (self.page_general if page == "general" else self.page_about)(body)

    def page_general(self, body):
        self.text(body, t("nav_general"), size=13, bold=True).pack(anchor="w")
        self.text(body, t("language"), size=10, fg=C["muted"]).pack(anchor="w", pady=(self.px(18), self.px(8)))
        self.segmented(body, list(LANGS.items()), lang, self.app.set_lang)
        self.text(body, t("language_hint"), size=9, fg=C["faint"]).pack(anchor="w", pady=(self.px(8), 0))

        self.text(body, t("online_label"), size=10, fg=C["muted"]).pack(anchor="w", pady=(self.px(20), self.px(8)))
        self.segmented(body, [(True, t("online_on")), (False, t("online_off"))], online, self.app.set_online)
        self.text(body, t("online_hint"), size=9, fg=C["faint"], wraplength=self.px(370),
                  justify="left").pack(anchor="w", pady=(self.px(8), 0))

    def segmented(self, body, options, value, on_pick):
        """一排互斥按钮（选中的是橙色）。"""
        seg = tk.Frame(body, bg=C["card"])
        seg.pack(anchor="w")
        for code, name in options:
            on = code == value
            lb = tk.Label(seg, text=name, font=(FONT, 10, "bold" if on else "normal"),
                          bg=C["accent"] if on else C["card"], fg="#FFFFFF" if on else C["text"],
                          padx=self.px(18), pady=self.px(6), cursor="hand2",
                          highlightthickness=1, highlightbackground=C["accent"] if on else C["border"])
            lb.pack(side="left", padx=(0, self.px(8)))
            lb.bind("<Button-1>", lambda e, c=code: on_pick(c))

    def page_about(self, body):
        self.text(body, t("nav_about"), size=13, bold=True).pack(anchor="w")
        head = tk.Frame(body, bg=C["card"])
        head.pack(anchor="w", pady=(self.px(16), self.px(10)))
        self.logo(head, 48, C["card"]).pack(side="left")
        names = tk.Frame(head, bg=C["card"])
        names.pack(side="left", padx=(self.px(12), 0))
        self.text(names, t("title"), size=12, bold=True).pack(anchor="w")
        self.text(names, t("version", v=APP_VERSION), size=9, fg=C["muted"]).pack(anchor="w")

        self.text(body, t("about_desc"), size=9, fg=C["text"], wraplength=self.px(370),
                  justify="left").pack(anchor="w")

        btns = tk.Frame(body, bg=C["card"])
        btns.pack(anchor="w", pady=(self.px(14), self.px(6)))
        self.button(btns, t("check_update"), self.check_update, size=9).pack(side="left")
        self.button(btns, t("open_releases"), lambda: webbrowser.open(RELEASES_URL),
                    kind="ghost", size=9).pack(side="left", padx=(self.px(8), 0))
        self.status = self.text(body, "", size=9, fg=C["muted"], wraplength=self.px(370), justify="left")
        self.status.pack(anchor="w")
        self.text(body, t("about_foot"), size=8, fg=C["faint"]).pack(side="bottom", anchor="w")

    def check_update(self):
        """只在点按钮时联网查 Gitee 最新发行版。"""
        self.status.configure(text=t("checking"), fg=C["muted"])
        self.update_result = None

        def work():
            try:
                self.update_result = ("ok", cs.http_json(LATEST_API)["tag_name"])
            except Exception as e:
                self.update_result = ("err", e)

        threading.Thread(target=work, daemon=True).start()
        self.poll_update()

    def poll_update(self):
        if not self.winfo_exists():
            return
        if self.update_result is None:
            self.after(100, self.poll_update)
            return
        kind, val = self.update_result
        if not self.status.winfo_exists():
            return
        if kind == "err":
            self.status.configure(text=t("check_failed", e=val), fg=TONES["red"][0])
        elif version_tuple(val) > version_tuple(APP_VERSION):
            self.status.configure(text=t("new_version", v=val), fg=TONES["accent"][0])
        else:
            self.status.configure(text=t("up_to_date"), fg=TONES["green"][0])


def already_running():
    """只允许开一个窗口：用命名互斥量判断；已经开着就把那个窗口调到前面，返回 True。"""
    kernel32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    global _mutex  # 句柄要一直留着，进程退出时系统自动释放
    _mutex = kernel32.CreateMutexW(None, False, "Local\\ClaudeAccountSwitch.SingleInstance")
    if kernel32.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
        return False
    for strings in STRINGS.values():  # 窗口标题随语言变，两种都找
        hwnd = user32.FindWindowW(None, strings["title"])
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE：最小化了也还原
            user32.SetForegroundWindow(hwnd)
            break
    return True


def main():
    global lang, online
    if already_running():
        return
    settings = cs.load_settings()
    lang = settings.get("lang") if settings.get("lang") in STRINGS else DEFAULT_LANG
    online = settings.get("online", True) is not False
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 高分屏下文字不发虚
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
