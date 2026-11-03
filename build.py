"""打包成单文件 exe，并和使用说明一起压成 zip。

需要 PyInstaller（python -m pip install pyinstaller）。图标 icon.ico 已生成好，改图标才需要跑 make_icon.py。
用法：python build.py   → dist/ClaudeSwitch.exe 和 dist/ClaudeSwitch-v<版本>-win64.zip
"""

import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
GUI = ROOT / "claude_switch_gui.pyw"
VERSION = re.search(r'APP_VERSION = "([^"]+)"', GUI.read_text(encoding="utf-8")).group(1)

subprocess.run([
    sys.executable, "-m", "PyInstaller", "--onefile", "--windowed", "--noconfirm", "--clean",
    "--log-level", "WARN",
    "--name", "ClaudeSwitch",
    "--icon", str(ROOT / "icon.ico"),
    "--add-data", f"{ROOT / 'icon.ico'};.",
    "--paths", str(ROOT),
    "--distpath", str(DIST), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
    str(GUI),
], check=True)

exe = DIST / "ClaudeSwitch.exe"
zip_path = DIST / f"ClaudeSwitch-v{VERSION}-win64.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(exe, exe.name)
    z.write(ROOT / "使用说明.txt", "使用说明.txt")

print(f"exe: {exe}  {exe.stat().st_size / 1024 / 1024:.1f} MB")
print(f"zip: {zip_path}  {zip_path.stat().st_size / 1024 / 1024:.1f} MB")
print("SHA256:", hashlib.sha256(zip_path.read_bytes()).hexdigest())
