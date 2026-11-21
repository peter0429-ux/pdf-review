"""从 PDF 提取全文，并清理旧式 CID 字体造成的「部首字」。

为什么需要这一步：这份 PDF 提取出来的汉字里混着两种替换字符——

1. 康熙部首区 U+2F00–U+2FDF（例如「⼦」U+2F26）→ NFKC 能折回统一汉字，够用。
2. CJK 部首补充区 U+2E80–U+2EFF（例如「⻅」U+2EC5、「⻓」U+2ED3）→
   **NFKC 折不动**，因为 Unicode 认为部首字本身就是终态，不是兼容变体。

不清理的话，卡片里会出现「常⻅」「成⻓」这种看着一样、但搜索、排序、
以及 App 里的题面去重都会算成不同字的文本。所以补一张手工映射表。

映射表只覆盖这份 PDF 实际出现的 8 个字，找不到就原样保留并报警，
不会静默吞掉——宁可留个怪字被看见，也不要悄悄改错教材原意。
"""

import sys
import unicodedata

from pypdf import PdfReader

# CJK 部首补充区 → 统一汉字。键是部首字，值是它对应的常用汉字。
RADICAL_FIXES = {
    "\u2EC5": "\u89C1",  # ⻅ → 见
    "\u2EC6": "\u89D2",  # ⻆ → 角
    "\u2ECB": "\u8F66",  # ⻋ → 车
    "\u2ED3": "\u957F",  # ⻓ → 长
    "\u2ED4": "\u95E8",  # ⻔ → 门
    "\u2EDB": "\u98CE",  # ⻛ → 风
    "\u2EE3": "\u9AA8",  # ⻣ → 骨
    "\u2EE9": "\u9EC4",  # ⻩ → 黄
}


def clean(text):
    """先 NFKC 折康熙部首，再手工折部首补充区，最后清掉残留控制字符。"""
    text = unicodedata.normalize("NFKC", text)

    leftovers = set()
    out = []
    for ch in text:
        if ch in RADICAL_FIXES:
            out.append(RADICAL_FIXES[ch])
        else:
            if 0x2E80 <= ord(ch) <= 0x2EFF or 0x2F00 <= ord(ch) <= 0x2FDF:
                leftovers.add(ch)
            out.append(ch)

    if leftovers:
        detail = "、".join(f"U+{ord(c):04X}({c})" for c in sorted(leftovers))
        print(f"警告: 仍有未映射的部首字 {detail}", file=sys.stderr)

    text = "".join(out)

    # 这份 PDF 的项目符号用的是一个没有 ToUnicode 映射的字形，提取出来是 NUL。
    # 它会让文件被当成二进制、也会把卡片正文弄脏，直接换成间隔号。
    text = text.replace("\x00", "·")

    # 其余控制字符（保留换行和制表）一律扔掉
    text = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 0x20)

    return text


def extract(path):
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(clean(text).strip())
    return pages


def main(path, out):
    pages = extract(path)

    with open(out, "w", encoding="utf-8") as f:
        for i, text in enumerate(pages):
            f.write(f"\n===== 第 {i + 1} 页 =====\n")
            f.write(text)
            f.write("\n")

    body = "".join(pages)
    print(f"页数 {len(pages)}，字符 {len(body)}，已写入 {out}")
    print("前 160 字:", body[:160].replace("\n", " "))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
