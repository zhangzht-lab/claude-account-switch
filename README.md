# Claude 账号切换

在同一台 Windows 电脑上，给 Claude Code（VS Code 插件或命令行）一键切换多个 Claude 账号，并查看每个账号的 5 小时额度、本周额度和重置时间。切换时不用重新登录、不用再收验证邮件。

> 这是个人做的小工具，不是 Anthropic 官方产品。

![界面截图（示例数据）](docs/screenshot.png)

## 功能

- **一键切换**：点「切换到这个账号」，再在 VS Code 里执行 `Developer: Reload Window` 就生效。
- **尽量少联网**：其他账号只显示本机记下的数据；当前账号可以在设置里选择「联网查询」（默认开，只在点「刷新」时查，每分钟最多 3 次）或完全不联网。从不刷新令牌。
- **用量一目了然**：每个账号的 5 小时 / 本周用量进度条、重置时间和剩余时长，并注明是什么时候的数据；过了重置时间显示「已重置」，不再显示旧的百分比；自动标出「剩余额度最多」的账号。
- **登录状态**：登录（约 4 周有效）还剩几天，快到期时变色提醒；短期令牌（约 8 小时）由 Claude Code 自己续期。
- **手动刷新**：点「刷新」重新读取；标题下显示上次刷新时间。
- **设置**：右下角「⚙ 设置」，可切换界面语言（中文 / 日本語，立即生效）和「联网查询当前账号的用量」开关；「关于」里有版本号、「检查更新」和「打开下载页」。
- **账号管理**：每张卡片的「⋯」菜单可以设置备注名、删除不用的账号（正在用的不能删）。
- **自动发现新账号**：窗口开着时每 2 秒看一眼本机登录文件（不联网），在插件里 `/login` 新账号后马上出现；旧会话把令牌写乱时也会马上提示。
- **系统托盘**：关窗口（✕）时缩到右下角托盘，不退出；左键点图标打开窗口，右键菜单列出所有账号和用量，点一下直接切换（窗口藏着时用系统通知提示结果），菜单里「退出」才真正退出。用 Windows API 直接实现，没有多加依赖。
- **只开一个窗口**：已经开着时再双击，会把原窗口调到最前面。
- **单个 exe**：约 12 MB，不用装 Python，第一次运行在桌面建快捷方式。

## 下载使用

到 [发行版](https://gitee.com/zhang-bantao/claude-account-switch/releases) 下载 `ClaudeSwitch-v*-win64.zip`，解压后看里面的 `使用说明.txt`。简单来说：

1. 把 `ClaudeSwitch.exe` 放到固定位置，双击打开，Claude Code 当前登录的账号会自动保存。
2. 在 Claude 插件里 `/login` 另一个账号，回到窗口点「刷新」，就加进来了。每个账号只需要这样做一次。
3. 以后点「切换到这个账号」→ VS Code 里 `Ctrl+Shift+P` → `Developer: Reload Window`。

Windows 提示「Windows 已保护你的电脑」时，点「更多信息」→「仍要运行」（程序没有数字签名）。

## 原理

Claude Code 的登录信息存在两个文件里：

| 文件 | 内容 |
|---|---|
| `%USERPROFILE%\.claude\.credentials.json` | `claudeAiOauth`：访问令牌和刷新令牌 |
| `%USERPROFILE%\.claude.json` | `oauthAccount`：邮箱、组织等账号信息 |

本工具把每个账号的这两段存到 `%USERPROFILE%\.claude-accounts\profiles\<邮箱>.json`，切换时写回去，其他设置（MCP 登录、项目配置等）都不动。

**用量**：

- **当前账号**：设置里「联网查询当前账号的用量」打开时（默认），点「刷新」会用当前账号还没过期的访问令牌查一次 `https://api.anthropic.com/api/oauth/usage`，和 Claude 插件面板显示用量时发的请求一样。只在你点「刷新」（以及打开窗口、切换账号后）时查，**每分钟最多 3 次**（记录在 `online-log.json`，重开程序也算数），超过时提示还要等几秒并显示本机数据。关掉这个开关就完全不联网，只读 Claude Code 缓存在 `%USERPROFILE%\.claude.json` 的 `cachedUsageUtilization`（插件不常更新它，可能不是最新）。
- **其他账号**：从不联网，显示上次使用这个账号时记下的数据（`usage-cache.json`）。过了重置时间显示「已重置」。

本工具**从不刷新令牌**。刷新令牌是一次性的，换一次旧的就作废，还开着的 Claude Code 会话手里那份会失效，出现 `OAuth session expired and could not be refreshed` 并要求重新登录（v1.0.0 会这样做，v1.1.0 起已去掉）。访问令牌过期时不查询，等插件自己续期。「关于」页的「检查更新」只在手动点时查询 Gitee。

切换账号后，**每个**开着 Claude Code 的 VS Code 窗口都要执行一次 `Developer: Reload Window`（或者重启 VS Code），否则旧会话还拿着上一个账号的令牌。

**账号不一致检测**：没 Reload 的旧会话续期时，可能把它自己账号的令牌写回 `.credentials.json`，而 `.claude.json` 里已经是新账号。这时如果照常保存，会把 A 的令牌存进 B 的档案。工具每次保存前都会比对：当前令牌的刷新令牌、访问令牌或登录有效期（`refreshTokenExpiresAt`，续期后不变）和另一个账号的档案相同，就判定为不一致，暂停保存和联网查询，并显示红色提示，直到 Reload 或切换后恢复。切换时读写 `.claude.json` 紧挨着进行，并先备份到 `claude.json.bak`。

## 从源码运行 / 打包

需要 Python 3.10+（官方安装包自带 tkinter），没有第三方依赖。

```powershell
pythonw claude_switch_gui.pyw          # 直接运行
python -m pip install pyinstaller
python build.py                        # 生成 dist\ClaudeSwitch.exe 和 zip
python make_icon.py                    # 改图标时才需要（要 Pillow）
python -m unittest discover tests      # 单元测试（临时目录里跑，不碰真实账号，不联网）
```

| 文件 | 说明 |
|---|---|
| `claude_switch.py` | 核心逻辑：保存 / 切换账号、读取用量（本机缓存 + 当前账号限频联网查询） |
| `claude_switch_gui.pyw` | tkinter 界面（主窗口 + 设置窗口） |
| `tray.py` | 系统托盘（ctypes 调 Shell_NotifyIcon，自己的线程跑消息循环） |
| `i18n.py` | 界面文字（中文 / 日本語），新增文字两种语言都要加 |
| `build.py` | PyInstaller 单文件打包 + 压缩包 |
| `tests/test_core.py` | 单元测试：账号不一致、限频、切换保留其他设置、本机用量、备注名和删除 |
| `make_icon.py` / `icon.ico` | 图标 |
| `使用说明.txt` | 随 exe 一起发布的说明 |

## 注意

- `%USERPROFILE%\.claude-accounts` 里是你的登录令牌，**不要发给别人，也不要上传**。
- 每人只保存自己的账号；共用账号违反 Anthropic 的使用条款。
- 读的是 Claude Code 的本地文件格式和内部接口，没有公开文档，Claude Code 更新后可能需要跟着改。
- 《Anthropic 消费者条款》第 3 条禁止用脚本等自动化方式访问服务（联网查询虽然和插件面板的请求一样、频率更低，严格说仍属此类，不放心可以在设置里关掉），也禁止绕过系统的保护措施；用多个账号轮流规避用量上限是否算违规，Anthropic 没有明确说明。请自行判断风险，额度不够时优先考虑升级套餐。
- 只支持 Windows。macOS 上 Claude Code 把令牌存在钥匙串里，本工具读不到。

## 许可证

[MIT](LICENSE)
