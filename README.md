# Claude 账号切换

在同一台 Windows 电脑上，给 Claude Code（VS Code 插件或命令行）一键切换多个 Claude 账号，并查看每个账号的 5 小时额度、本周额度和重置时间。切换时不用重新登录、不用再收验证邮件。

> 这是个人做的小工具，不是 Anthropic 官方产品。

![界面截图（示例数据）](docs/screenshot.png)

## 功能

- **一键切换**：点「切换到这个账号」，再在 VS Code 里执行 `Developer: Reload Window` 就生效。
- **用量一目了然**：每个账号的 5 小时 / 本周用量进度条、重置时间和剩余时长；自动标出「剩余额度最多」的账号。
- **登录状态**：登录（约 4 周有效）还剩几天，快到期时变色提醒；短期令牌（约 8 小时）只由 Claude Code 自己续期，本工具从不刷新令牌。
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

用量来自 Claude Code `/usage` 用的同一个接口 `https://api.anthropic.com/api/oauth/usage`，只用还没过期的访问令牌查询。

本工具**从不用刷新令牌换新令牌**：刷新令牌是一次性的，换一次旧的就作废，还开着的 Claude Code 会话手里那份会失效，出现 `OAuth session expired and could not be refreshed` 并要求重新登录（v1.0.0 的做法，v1.1.0 已去掉）。没在用的账号令牌过期后显示上次查到的数据，切换过去后由 Claude Code 自己续期。

切换账号后，**每个**开着 Claude Code 的 VS Code 窗口都要执行一次 `Developer: Reload Window`（或者重启 VS Code），否则旧会话还拿着上一个账号的令牌。

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
| `claude_switch.py` | 核心逻辑：保存 / 切换账号、查询用量 |
| `claude_switch_gui.pyw` | tkinter 界面（主窗口 + 设置窗口） |
| `i18n.py` | 界面文字（中文 / 日本語），新增文字两种语言都要加 |
| `build.py` | PyInstaller 单文件打包 + 压缩包 |
| `make_icon.py` / `icon.ico` | 图标 |
| `使用说明.txt` | 随 exe 一起发布的说明 |

## 注意

- `%USERPROFILE%\.claude-accounts` 里是你的登录令牌，**不要发给别人，也不要上传**。
- 每人只保存自己的账号；共用账号违反 Anthropic 的使用条款。
- 用量查询用的是 Claude Code 内部接口，没有公开文档，Claude Code 更新后可能失效。
- 《Anthropic 消费者条款》第 3 条禁止用脚本等自动化方式访问服务、禁止绕过系统的保护措施；用多个账号轮流规避用量上限是否算违规，Anthropic 没有明确说明。请自行判断风险，额度不够时优先考虑升级套餐。
- 只支持 Windows。macOS 上 Claude Code 把令牌存在钥匙串里，本工具读不到。

## 许可证

[MIT](LICENSE)
