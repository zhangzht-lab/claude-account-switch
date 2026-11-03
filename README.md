# Claude 账号切换

在同一台 Windows 电脑上，给 Claude Code（VS Code 插件或命令行）一键切换多个 Claude 账号，并查看每个账号的 5 小时额度、本周额度和重置时间。切换时不用重新登录、不用再收验证邮件。

> 这是个人做的小工具，不是 Anthropic 官方产品。

![界面截图（示例数据）](docs/screenshot.png)

## 功能

- **一键切换**：点「切换到这个账号」，再在 VS Code 里执行 `Developer: Reload Window` 就生效。
- **用量一目了然**：每个账号的 5 小时 / 本周用量进度条、重置时间和剩余时长；自动标出「剩余额度最多」的账号。
- **登录状态**：登录（约 4 周有效）还剩几天，快到期时变色提醒；短期令牌（约 8 小时）自动续期。
- **手动刷新**：打开窗口时查询一次，之后点「刷新」才重新查询，不在后台反复请求；标题下显示上次刷新时间。查询失败或被限流时显示上次的数据。
- **设置**：右下角「⚙ 设置」，可切换界面语言（中文 / 日本語，立即生效）；「关于」里有版本号、项目地址和「检查更新」。
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

用量来自 Claude Code `/usage` 用的同一个接口 `https://api.anthropic.com/api/oauth/usage`。没在用的账号令牌过期时，用刷新令牌换新令牌并存回；正在用的账号交给 Claude Code 自己续期，避免把它的令牌顶掉。

## 从源码运行 / 打包

需要 Python 3.10+（官方安装包自带 tkinter），没有第三方依赖。

```powershell
pythonw claude_switch_gui.pyw          # 直接运行
python -m pip install pyinstaller
python build.py                        # 生成 dist\ClaudeSwitch.exe 和 zip
python make_icon.py                    # 改图标时才需要（要 Pillow）
```

| 文件 | 说明 |
|---|---|
| `claude_switch.py` | 核心逻辑：保存 / 切换账号、查询用量、续期令牌 |
| `claude_switch_gui.pyw` | tkinter 界面（主窗口 + 设置窗口） |
| `i18n.py` | 界面文字（中文 / 日本語），新增文字两种语言都要加 |
| `build.py` | PyInstaller 单文件打包 + 压缩包 |
| `make_icon.py` / `icon.ico` | 图标 |
| `使用说明.txt` | 随 exe 一起发布的说明 |

## 注意

- `%USERPROFILE%\.claude-accounts` 里是你的登录令牌，**不要发给别人，也不要上传**。
- 每人只保存自己的账号；共用账号违反 Anthropic 的使用条款。
- 用量查询和令牌续期用的是 Claude Code 内部接口，没有公开文档，Claude Code 更新后可能失效。
- 只支持 Windows。macOS 上 Claude Code 把令牌存在钥匙串里，本工具读不到。

## 许可证

[MIT](LICENSE)
