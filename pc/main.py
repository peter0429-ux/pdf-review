"""程序入口。

双击 `PdfReview.exe` 跑的就是这个文件。

放在 `pc/` 根目录而不是 `ui/` 里，是为了让 PyInstaller 的入口参数最短
（`pyinstaller main.py`），也方便直接从命令行 `python main.py` 试跑。

带一个诊断开关：`PdfReview.exe --selftest 报告.json`。它会不碰网络地把
抽取 → 切块 → 组文档 → 导出这条链路跑一遍，把每一步的结果写进 JSON。
打包后「某个依赖没被带进去」这种问题只在特定格式上才炸，用户报「导不出
Excel」时让他跑这个，比来回猜快得多。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 直接从源码跑时（python main.py），脚本所在目录不在 sys.path 上，
# core 与 ui 都 import 不到。打包成 exe 后 PyInstaller 会处理好，
# 但那段代码也得能跑——本机开发全靠它。
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def selftest(report_path: Path) -> int:
    """无界面自检。返回 0 表示全通过。"""
    import json
    import tempfile
    import traceback

    report: dict[str, object] = {"ok": True, "checks": []}

    def record(name: str, passed: bool, detail: str = "") -> None:
        report["checks"].append({"name": name, "ok": passed, "detail": detail})
        if not passed:
            report["ok"] = False

    # 逐项 import：哪个依赖没打进包里，这里就直接点出来
    modules = {
        "tkinter": "tkinter",
        "pypdf": "pypdf",
        "python-docx": "docx",
        "python-pptx": "pptx",
        "openpyxl": "openpyxl",
        "beautifulsoup4": "bs4",
        "lxml": "lxml",
        "Pillow": "PIL",
    }
    for label, module_name in modules.items():
        try:
            __import__(module_name)
        except Exception as exc:  # noqa: BLE001
            record(f"import {label}", False, f"{type(exc).__name__}: {exc}")
        else:
            record(f"import {label}", True)

    # schema 资源
    try:
        from core import schema_check

        schema = schema_check.load_schema()
        record("schema 能读到", isinstance(schema, dict), str(schema.get("title", "")))
    except Exception as exc:  # noqa: BLE001
        record("schema 能读到", False, f"{type(exc).__name__}: {exc}")

    # 真实跑一遍链路（用临时生成的 txt，不依赖任何样例文件）
    try:
        from core import export
        from core.cards import AnalysisDocument, Card, Deck, Source, now_iso8601
        from core.chunker import chunk_extraction
        from core.extract import Extraction, Segment

        text = "这是一个自检用的文档。\n\n" * 200
        extraction = Extraction(
            file_name="selftest.txt",
            kind="txt",
            unit_label="段",
            segments=[Segment(index=1, label="第 1 段", text=text)],
            full_text=text,
        )
        chunks = chunk_extraction(extraction)
        record("切块", len(chunks) >= 1, f"{len(chunks)} 块")

        document = AnalysisDocument(
            schema_version="1.0",
            generated_at=now_iso8601(),
            source=Source(file_name="selftest.txt", page_count=1),
            deck=Deck(title="自检", summary="自检用"),
            cards=[Card("自检题目？", "自检答案。")],
            generator="selftest",
        )
        problems = export.validate_for_export(document)
        record("文档能通过双重校验", problems == [], "；".join(problems))

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "selftest.pdfreview.json"
            export.export_to(document, target)
            record("能写出 .pdfreview.json", target.exists(), str(target.stat().st_size) + " 字节")
    except Exception:  # noqa: BLE001
        record("跑通导出链路", False, traceback.format_exc()[-800:])

    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        return 2

    return 0 if report["ok"] else 1


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--selftest":
        return selftest(Path(argv[1]))

    from ui.main_window import run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
