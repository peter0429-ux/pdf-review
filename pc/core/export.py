"""导出 `.pdfreview.json`——PC 与 iOS 之间唯一的交接点，所以这里宁可多拒几次。

两道校验都要过才写盘：

1. `AnalysisDocument.validate()` —— 语义：长度、非空、范围、标签去重。
2. `schema_check.ensure_valid()` —— 结构：类型、必填、未知键、正则。

为什么两道都要：它们查的是不同的东西。`validate()` 是我按 iOS 的
`AnalysisValidator` 逐条抄的，管「内容讲不讲道理」；schema 是给第三方
校验器看的机器可读契约，管「字段名和类型对不对」。只过一道就可能出现
「PC 打得开、iOS 说文件格式不对」——那种错误用户完全无从下手。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import schema_check
from .cards import AnalysisDocument


class ExportError(Exception):
    """导出失败。消息可以直接展示给用户。"""


def validate_for_export(document: AnalysisDocument) -> list[str]:
    """导出前体检，返回所有问题（空列表表示可以导出）。

    故意收集全部问题而不是遇到第一个就抛：用户改一次文件就能看到
    所有要修的地方，而不是修一条、再导出、再发现下一条。
    """
    problems: list[str] = []

    # 第一道：语义
    try:
        problems.extend(document.validate())
    except Exception as exc:  # noqa: BLE001 - validate 不该抛，抛了也要说清楚
        problems.append(f"内容校验时出错：{exc}")

    # 第二道：结构
    try:
        schema_check.ensure_valid(document.to_json())
    except schema_check.SchemaViolation as exc:
        problems.extend(exc.errors)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"格式校验时出错：{exc}")

    return problems


def dump(document: AnalysisDocument) -> str:
    """把文档变成要写进文件的字符串。校验不过就抛 ExportError。"""
    problems = validate_for_export(document)
    if problems:
        raise ExportError(
            "这份内容还不符合导出格式，先修好这几处：\n"
            + "\n".join(f"· {item}" for item in problems)
        )
    return document.encoded()


def export_to(document: AnalysisDocument, destination: Path | str) -> Path:
    """写到指定路径。父目录不存在会建。

    先写临时文件再原子替换：半路失败不会留下一个「看起来能用、其实是半截」
    的 json——用户拿去导入 iOS 才发现坏了，那时代码已经不在现场了。
    """
    target = Path(destination)
    text = dump(document)

    if target.suffix.lower() != ".json":
        raise ExportError("导出文件必须用 .json 结尾。")

    parent = target.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(f"建不了目录 {parent}：{exc}") from exc

    tmp = target.with_name(target.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        tmp.replace(target)
    except OSError as exc:
        # 清掉半截的临时文件，别在用户文件夹里留垃圾
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise ExportError(f"写不了文件 {target}：{exc}") from exc

    return target


def default_export_name(document: AnalysisDocument, title: Optional[str] = None) -> str:
    """给「另存为」对话框一个像样的默认文件名。

    用牌组标题而不是原文件名：用户认识的是牌组名，而且同一个 PDF 分析两次
    出来的两个牌组不应该在导出目录里互相覆盖。
    """
    source = title or document.deck.title or "复习卡片"
    illegal = '<>:"/\\|?*'
    cleaned = "".join("_" if char in illegal else char for char in source).strip()
    cleaned = cleaned.rstrip(". ") or "复习卡片"
    return f"{cleaned[:60]}.pdfreview.json"
