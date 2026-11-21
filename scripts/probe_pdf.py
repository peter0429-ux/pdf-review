"""探测 PDF：页数、每页可提取字符数、是否有文字层。

用来判断这份 PDF 是「真文字」还是「扫描图片」——这决定了能不能提取文本，
进而决定能不能做真正的 AI 分析。
"""

import sys

from pypdf import PdfReader


def main(path):
    reader = PdfReader(path)
    total = len(reader.pages)
    print(f"页数: {total}")

    per_page = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # 单页失败不该中断整体探测
            text = ""
            print(f"  第 {i + 1} 页提取异常: {type(exc).__name__}: {exc}")
        per_page.append(len(text.strip()))

    nonempty = [n for n in per_page if n > 0]
    print(f"有文字的页: {len(nonempty)} / {total}")
    print(f"总字符数  : {sum(per_page)}")
    if nonempty:
        print(f"平均每页  : {sum(nonempty) // len(nonempty)} 字")
    print()

    print("前 15 页字符数:", per_page[:15])
    print("抽 5 页看看:", [(i + 1, per_page[i]) for i in range(0, total, max(1, total // 5))])

    # 判断是否有文字层：与 App 里 PDFTextExtractor 的规则保持一致
    has_layer = sum(per_page) >= 200 and (sum(per_page) / max(1, total)) >= 20
    print()
    print(f"判定有文字层: {has_layer}")

    if nonempty:
        print()
        print("=== 第 1 个有文字的页 前 800 字 ===")
        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if text:
                print(f"[第 {i + 1} 页]")
                print(text[:800])
                break


if __name__ == "__main__":
    main(sys.argv[1])
