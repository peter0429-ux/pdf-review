"""把 `pc/` 打成一个可交付的 zip。

为什么要有这个脚本而不是让人敲一遍 PyInstaller 命令：命令行参数里有一个
`--add-data "..\\schema\\...;schema"`，斜杠方向与分号是 Windows 特有的，
敲错一个字符不会报错，只会在用户点「导出」时崩。写进脚本就不会写错。

用法：
    python pc/scripts/build.py            打包并生成 zip
    python pc/scripts/build.py --no-zip   只打包，不压 zip
    python pc/scripts/build.py --with-settings
                                          顺便把本机已保存的 settings.json
                                          带进包里（便携模式）
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PC_DIR = Path(__file__).resolve().parent.parent
ROOT = PC_DIR.parent
VENV_PYTHON = PC_DIR / ".venv" / "Scripts" / "python.exe"
DIST = PC_DIR / "dist" / "PdfReview"
SCHEMA = ROOT / "schema" / "analysis.v1.schema.json"
OUT_DIR = ROOT / "outputs" / "deliver"

#: 放在 exe 旁边就让程序进便携模式：设置与牌组都存这个文件夹。
#: 交付的是 zip，用户解压到哪儿、程序就在哪儿存东西，不用去 %APPDATA% 找。
PORTABLE_MARKER = "portable.txt"


def run(command: list[str], cwd: Path) -> None:
    print("$", " ".join(command))
    result = subprocess.run(command, cwd=str(cwd))
    if result.returncode != 0:
        raise SystemExit(f"命令失败（退出码 {result.returncode}）")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-zip", action="store_true", help="只打包，不压缩")
    parser.add_argument(
        "--with-settings",
        action="store_true",
        help="把本机已保存的 settings.json 一并放进包里（会带上加密后的 Key）",
    )
    args = parser.parse_args()

    python = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
    if not SCHEMA.exists():
        raise SystemExit(f"找不到 schema：{SCHEMA}")

    run(
        [
            str(python),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--windowed",
            "--name",
            "PdfReview",
            # 打包后 `core/schema_check.py` 会先找 sys._MEIPASS/schema/，
            # 所以这里必须把 schema 拷进包的根下同名目录。
            "--add-data",
            f"{SCHEMA};schema",
            # 这三个是标着可选、实际会把包撑大几十 MB 的，本项目一个都不用。
            "--exclude-module",
            "numpy",
            "--exclude-module",
            "matplotlib",
            "--exclude-module",
            "pandas",
            "main.py",
        ],
        cwd=PC_DIR,
    )

    if not (DIST / "PdfReview.exe").exists():
        raise SystemExit("打包结束但没找到 PdfReview.exe")

    # 便携标记：有了它，程序把设置和牌组都存在自己旁边，不写 %APPDATA%。
    # 交付的是压缩包，用户随便解压到哪儿都能用，也不用去找隐藏目录。
    (DIST / PORTABLE_MARKER).write_text(
        "这个文件让程序进入便携模式：设置与牌组都存在当前文件夹里。\n"
        "删掉它就回到 %APPDATA%\\PdfReviewPC 的常规模式。\n",
        encoding="utf-8",
    )
    print(f"写入便携标记：{DIST / PORTABLE_MARKER}")

    if args.with_settings:
        # 只在本机已经配好时才有意义。加密后的 Key 与当前 Windows 账户绑定，
        # 换了账户或换了电脑都解不开——这一点写进 README 了，别指望它能跨机器。
        sys.path.insert(0, str(PC_DIR))
        from core import settings as settings_mod  # 本脚本在 pc/scripts 下，要手动补路径

        current = settings_mod.load_settings()
        if not current.is_configured:
            print("本机还没配置好接口，跳过打包设置。")
        else:
            settings_mod.save_settings(current, DIST / settings_mod.SETTINGS_FILE_NAME)
            print(f"已把设置写进包里：{DIST / settings_mod.SETTINGS_FILE_NAME}")

    total = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    print(f"\n打包完成：{DIST}")
    print(f"体积：{total / 1024 / 1024:.1f} MB")

    if args.no_zip:
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / "PdfReview-PC-win64.zip"
    if target.exists():
        target.unlink()

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(DIST.rglob("*")):
            if path.is_file():
                bundle.write(path, Path("PdfReview") / path.relative_to(DIST))

    print(f"压缩包：{target}（{target.stat().st_size / 1024 / 1024:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
