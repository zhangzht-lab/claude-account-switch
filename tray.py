"""系统托盘图标，直接用 Windows API（ctypes）实现，不依赖第三方库，exe 不会变大。

托盘在自己的线程里跑 Win32 消息循环；用户操作通过 on_event 回调告诉界面
（回调在托盘线程里执行，界面那边要放进队列再处理，tkinter 不能跨线程操作）：
  ("open",)          左键单击托盘图标、菜单「打开窗口」、或者又启动了一次程序
  ("switch", email)  在右键菜单里选了某个账号
  ("quit",)          菜单「退出」
"""

import ctypes
import threading
from ctypes import wintypes

TRAY_CLASS = "ClaudeAccountSwitchTray"   # 隐藏窗口的类名，第二次启动时靠它找到已运行的程序
WM_TRAY = 0x8000 + 1                      # WM_APP + 1：托盘图标的鼠标消息
WM_SHOW_REQUEST = 0x8000 + 2              # WM_APP + 2：另一个实例请求显示窗口

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                              wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.LPVOID]
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO = 0x1
WM_DESTROY, WM_CLOSE, WM_NULL = 0x2, 0x10, 0x0
WM_LBUTTONUP, WM_RBUTTONUP = 0x202, 0x205
MF_STRING, MF_SEPARATOR, MF_GRAYED, MF_CHECKED = 0x0, 0x800, 0x1, 0x8
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
ID_OPEN, ID_QUIT, ID_ACCOUNT = 1, 2, 100   # 账号菜单项从 100 开始编号


def request_show():
    """第二次启动时调用：找到已运行程序的托盘窗口，请它把主窗口显示出来。找到返回 True。"""
    hwnd = user32.FindWindowW(TRAY_CLASS, None)
    if not hwnd:
        return False
    user32.PostMessageW(hwnd, WM_SHOW_REQUEST, 0, 0)
    return True


class Tray:
    def __init__(self, icon_path, on_event):
        self.icon_path = str(icon_path)
        self.on_event = on_event
        self.hwnd = None
        self.hicon = None
        self.tooltip = ""
        self.items = []                 # [(菜单文字, 邮箱, 是否打勾), ...]，由界面线程更新
        self.labels = {"open": "Open", "quit": "Quit", "empty": "-"}
        self.ready = threading.Event()
        self._proc = WNDPROC(self._wndproc)  # 要一直引用着，不然回调会被回收
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")

    # ---------- 界面线程调用 ----------
    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        self.ready.wait(5)
        return self.hwnd is not None

    def set_tooltip(self, text):
        self.tooltip = text[:127]
        self._notify(NIM_MODIFY, NIF_TIP)

    def notify(self, title, text):
        """弹一条 Windows 通知（托盘气泡）。"""
        nid = self._nid(NIF_INFO)
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def stop(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # ---------- 托盘线程 ----------
    def _nid(self, flags):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = self.tooltip
        return nid

    def _notify(self, action, flags):
        if self.hwnd:
            shell32.Shell_NotifyIconW(action, ctypes.byref(self._nid(flags)))

    def _run(self):
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = TRAY_CLASS
        user32.RegisterClassW(ctypes.byref(wc))
        # 普通的隐藏窗口（不是 message-only 窗口），右键菜单才能在点别处时正常收起
        self.hwnd = user32.CreateWindowExW(0, TRAY_CLASS, TRAY_CLASS, 0, 0, 0, 0, 0, None, None, hinst, None)
        if not self.hwnd:
            self.ready.set()
            return
        size = user32.GetSystemMetrics(49)  # SM_CXSMICON：托盘小图标的尺寸
        self.hicon = user32.LoadImageW(None, self.icon_path, 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        self._notify(NIM_ADD, NIF_MESSAGE | NIF_ICON | NIF_TIP)
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                if lparam == WM_LBUTTONUP:
                    self.on_event(("open",))
                elif lparam == WM_RBUTTONUP:
                    self._menu()
                return 0
            if msg == WM_SHOW_REQUEST:
                self.on_event(("open",))
                return 0
            if msg == self._taskbar_created:  # 资源管理器重启后托盘图标会丢，重新加上
                self._notify(NIM_ADD, NIF_MESSAGE | NIF_ICON | NIF_TIP)
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                self._notify(NIM_DELETE, 0)
                user32.PostQuitMessage(0)
                return 0
        except Exception:  # 回调里的异常不能抛回 Windows
            pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self):
        items = list(self.items)
        menu = user32.CreatePopupMenu()
        for i, (text, _email, checked) in enumerate(items):
            user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if checked else 0), ID_ACCOUNT + i, text)
        if not items:
            user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, self.labels["empty"])
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_OPEN, self.labels["open"])
        user32.AppendMenuW(menu, MF_STRING, ID_QUIT, self.labels["quit"])
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)  # 不先这样，菜单点别处不会收起
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                    pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if cmd == ID_OPEN:
            self.on_event(("open",))
        elif cmd == ID_QUIT:
            self.on_event(("quit",))
        elif cmd >= ID_ACCOUNT and cmd - ID_ACCOUNT < len(items):
            self.on_event(("switch", items[cmd - ID_ACCOUNT][1]))
