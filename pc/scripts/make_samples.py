"""生成几份示例文档，用来真跑抽取与切分。

这些不提交进仓库（`pc/.gitignore` 里挡掉了 `samples/`），
但它们是从零验证 extract.py 的唯一办法 —— 光读代码看不出
python-docx 的 block 顺序、openpyxl 的表头处理有没有写对。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

TARGET = HERE / "samples"


def make_txt() -> Path:
    path = TARGET / "sample.txt"
    path.write_text(
        "第一章 电阻\n\n"
        "电阻是电路里最常见的元件，作用是限制电流。单位是欧姆，符号 Ω。\n\n"
        "色环电阻用四条或五条彩色环表示阻值。第一条与第二条是有效数字，"
        "第三条是倍率，第四条是误差。\n\n"
        "第二章 电容\n\n"
        "电容储存电荷，单位是法拉，符号 F。常见的有陶瓷电容、电解电容。\n\n"
        "电解电容有极性，接反会炸。陶瓷电容没有极性。\n",
        encoding="utf-8",
    )
    return path


def make_md() -> Path:
    path = TARGET / "sample.md"
    path.write_text(
        "# 二极管\n\n"
        "二极管只允许电流单向通过。三角形指向的那一侧是阳极，竖线那侧是阴极。\n\n"
        "## 正向导通\n\n"
        "阳极电压高于阴极约 0.7V（硅管）时导通。\n\n"
        "## 反向截止\n\n"
        "反向电压超过击穿电压会击穿，普通二极管击穿后损坏，稳压二极管则是利用这个特性工作。\n\n"
        "# 三极管\n\n"
        "三极管有三个极：基极、集电极、发射极。小电流控制大电流。\n",
        encoding="utf-8",
    )
    return path


def make_html() -> Path:
    path = TARGET / "sample.html"
    path.write_text(
        """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>变压器</title>
<style>body { font-family: sans-serif; }</style>
<script>console.log("这段不该出现在正文里");</script>
</head>
<body>
<nav>首页 | 产品 | 关于我们</nav>
<h1>变压器</h1>
<p>变压器利用电磁感应改变交流电压。原线圈与副线圈的匝数比等于电压比。</p>
<h2>升压与降压</h2>
<p>副线圈匝数多于原线圈是升压，少于则是降压。</p>
<h2>损耗</h2>
<p>主要损耗来自线圈电阻发热与铁芯涡流。</p>
<footer>版权所有</footer>
</body>
</html>
""",
        encoding="utf-8",
    )
    return path


def make_docx() -> Path:
    import docx

    document = docx.Document()
    document.add_heading("第一章 欧姆定律", level=1)
    document.add_paragraph("电压等于电流乘以电阻，即 U = I × R。")
    document.add_paragraph("这个公式只对线性电阻成立。")

    document.add_heading("第二章 功率", level=1)
    document.add_paragraph("功率等于电压乘以电流，即 P = U × I。")

    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "元件"
    table.cell(0, 1).text = "单位"
    table.cell(1, 0).text = "电阻"
    table.cell(1, 1).text = "欧姆"
    table.cell(2, 0).text = "电容"
    table.cell(2, 1).text = "法拉"

    path = TARGET / "sample.docx"
    document.save(str(path))
    return path


def make_pptx() -> Path:
    from pptx import Presentation
    from pptx.util import Inches, Pt

    presentation = Presentation()

    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "第一章 半导体"
    slide.placeholders[1].text = "导体、半导体、绝缘体的区别在于导电能力。\n硅和锗是最常用的半导体材料。"

    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "第二章 PN 结"
    slide.placeholders[1].text = "P 型半导体多空穴，N 型多自由电子。\n两者接触形成的 PN 结具有单向导电性。"

    # 纯图片页（没有文字）—— 验证抽取时会跳过它
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    left = top = Inches(1)
    slide.shapes.add_textbox(left, top, Inches(1), Inches(1))

    path = TARGET / "sample.pptx"
    presentation.save(str(path))
    return path


def make_xlsx() -> Path:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "元件参数"
    sheet.append(["元件", "单位", "常见值"])
    sheet.append(["电阻", "欧姆", "100, 1k, 10k"])
    sheet.append(["电容", "法拉", "100nF, 10uF"])
    sheet.append(["电感", "亨利", "10uH, 1mH"])

    sheet2 = workbook.create_sheet("公式说明")
    sheet2.append(["名称", "公式"])
    sheet2.append(["欧姆定律", "U = I × R"])
    sheet2.append(["功率", "P = U × I"])

    path = TARGET / "sample.xlsx"
    workbook.save(str(path))
    return path


def make_pdf() -> Path:
    """手搓一个最小可用 PDF。

    不引入 reportlab（又多一个依赖、几十 MB）。PDF 的文本对象格式很简单，
    手工拼一份足够让 pypdf 抽出一页文字。
    """
    lines = [
        "第一章 电路基础",
        "",
        "电流的方向规定为正电荷移动的方向。",
        "电压是两点之间的电位差，单位是伏特。",
        "",
        "第二章 串并联",
        "",
        "串联电路中电流处处相等，电压分配。",
        "并联电路中电压处处相等，电流分配。",
    ]

    def escape(text: str) -> str:
        return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    # 中文字符不在 WinAnsiEncoding 里，pypdf 用 extract_text 会抽不出来。
    # 所以这份 PDF 故意只用 ASCII 文字 —— 它的用途是验证「能打开、
    # 能读页数、能走完 chunk 流程」，不是验证中文抽取。
    ascii_lines = [
        "Chapter 1 Circuit Basics",
        "",
        "Current flows from higher potential to lower potential.",
        "Voltage is the difference in electric potential, in volts.",
        "",
        "Chapter 2 Series and Parallel",
        "",
        "In series, current is the same through every component.",
        "In parallel, voltage is the same across every component.",
    ]

    content_parts = ["BT", "/F1 14 Tf", "50 750 Td", "18 TL"]
    for line in ascii_lines:
        content_parts.append(f"({escape(line)}) Tj")
        content_parts.append("T*")
    content_parts.append("ET")
    stream = "\n".join(content_parts)

    objects: list[str] = []
    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    objects.append("<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    objects.append(
        f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream"
    )
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = ["%PDF-1.4"]
    offsets: list[int] = []
    cursor = len(out[0]) + 1  # 第一行加换行

    for index, body in enumerate(objects, start=1):
        entry = f"{index} 0 obj\n{body}\nendobj"
        offsets.append(cursor)
        out.append(entry)
        cursor += len(entry) + 1

    xref_start = cursor
    xref_lines = ["xref", f"0 {len(objects) + 1}", "0000000000 65535 f "]
    for offset in offsets:
        xref_lines.append(f"{offset:010d} 00000 n ")
    out.append("\n".join(xref_lines))
    out.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF"
    )

    path = TARGET / "sample.pdf"
    path.write_bytes(("\n".join(out) + "\n").encode("latin-1"))
    return path


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    makers = [
        ("txt", make_txt),
        ("md", make_md),
        ("html", make_html),
        ("docx", make_docx),
        ("pptx", make_pptx),
        ("xlsx", make_xlsx),
        ("pdf", make_pdf),
    ]
    for name, maker in makers:
        try:
            path = maker()
            print(f"  OK   {name:5s} {path.stat().st_size:>8d} B  {path.name}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {name:5s} {exc}")
            return 1
    print(f"\n生成完毕：{TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
