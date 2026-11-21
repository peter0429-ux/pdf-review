#!/usr/bin/env python3
"""反向测试 check_bare_static_calls：它到底能不能抓到真 bug。

一个检查器第一次跑就全绿，有两种可能：代码真没问题，或者检查器根本
不起作用。这里把真 bug 注入一份临时副本，看它是否报出来。

真 bug 取自 CI run 44922102188 的编译错误：
    static member 'loadCache' cannot be used on instance of type 'RotationProvider'
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from check_swift_consistency import check_bare_static_calls  # noqa: E402

TARGET = ROOT / "PdfReviewWidget" / "RotationProvider.swift"
GOOD_CALL = "guard let resolved = RotationProvider.loadCache() else {"
BAD_CALL = "guard let resolved = loadCache() else {"


def true_line_number(source: str, needle: str) -> int:
    """needle 在源文件里的真实行号（1 起）。"""
    for i, line in enumerate(source.splitlines(), 1):
        if needle in line:
            return i
    return -1


def main() -> int:
    source = TARGET.read_text(encoding="utf-8")
    if GOOD_CALL not in source:
        print("找不到被修好前的那一行，测试无法进行")
        return 2

    expected_line = true_line_number(source, GOOD_CALL)

    broken = source.replace(GOOD_CALL, BAD_CALL)
    probe = ROOT / "tmp" / "_probe_broken.swift"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(broken, encoding="utf-8")

    try:
        hits_broken = check_bare_static_calls(probe)
        hits_good = check_bare_static_calls(TARGET)
    finally:
        probe.unlink(missing_ok=True)

    print(f"注入 bug 后命中 {len(hits_broken)} 条：")
    for h in hits_broken:
        print("   ", h)
    print(f"正确版本命中 {len(hits_good)} 条")

    # 期望：坏版本至少 1 条、好版本 0 条，且报出的行号就是真 bug 所在行。
    ok = len(hits_broken) >= 1 and len(hits_good) == 0
    line_numbers = [int(m.group(1)) for m in (re.search(r":(\d+)\s", h) for h in hits_broken) if m]
    near = any(abs(n - expected_line) <= 1 for n in line_numbers)

    print()
    print(f"真 bug 应在第 {expected_line} 行，检查器报出 {line_numbers}")
    if ok and near:
        print("通过：坏版本被抓且行号准确，好版本干净")
        return 0
    if ok:
        print("部分通过：能抓，但行号偏离，定位不可信")
        return 1
    print("失败：检查器抓不到这个 bug，等于没做")
    return 1


if __name__ == "__main__":
    sys.exit(main())
