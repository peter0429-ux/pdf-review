"""把 `pc/` 打成一个可交付的 zip。

为什么要有这个脚本而不是让人敲一遍 PyInstaller 命令：命令行参数里有一个
`--add-data "..\\schema\\...;schema"`，斜杠方向与分号是 Windows 特有的，
敲错一个字符不会报错，只会在用户点「导出」时崩。写进脚本就不会写错。

用法：
    python pc/scripts/build.py            打包并生成 zip
    python pc/scripts/build.py --no-zip   只打包，不压 zip
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


def run(command: list[str], cwd: Path) -> None:
    print("$", " ".join(command))
    result = subprocess.run(command, cwd=str(cwd))
    if result.returncode != 0:
        raise SystemExit(f"命令失败（退出码 {result.returncode}）")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-zip", action="store_true", help="只打包，不压缩")
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
