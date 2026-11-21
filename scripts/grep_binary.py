#!/usr/bin/env python3
"""在打包出来的二进制里找几段字符串，确认某些代码路径真的被编进去了。

用途有限但很实用：本机不能编译，CI 只证明「编译通过」，而「这段新代码是不是
真的进了这个 target」只能靠翻二进制。字符串常量在 -O 下依然保留。
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: python scripts/grep_binary.py <二进制文件> <字符串1> [字符串2 ...]")
        return 2

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"找不到文件：{path}")
        return 2

    data = path.read_bytes()
    print(f"文件 {path.name}，{len(data)} 字节")
    print()

    # Swift 对小字符串有一套优化：15 个 UTF-8 字节以内的常量常常被内联进
    # 机器码（寄存器或立即数），根本不出现在 __cstring / 常量池里。
    # 所以短字符串「搜不到」不能说明没编进去 —— 这个工具只在长字符串上
    # 给可靠结论，短的一律标 UNCERTAIN，不参与判定。
    SMALL_STRING_LIMIT = 15

    missing = 0
    uncertain = 0
    for needle in sys.argv[2:]:
        raw = needle.encode("utf-8")
        as_utf8 = raw in data
        as_utf16 = needle.encode("utf-16-le") in data
        found = as_utf8 or as_utf16
        where = "utf-8" if as_utf8 else ("utf-16le" if as_utf16 else "")

        if found:
            print(f"  OK        {needle}  （{where}）")
        elif len(raw) <= SMALL_STRING_LIMIT:
            uncertain += 1
            print(f"  UNCERTAIN {needle}  （{len(raw)} 字节，Swift small-string "
                  f"优化可能把它内联掉了，搜不到属正常）")
        else:
            missing += 1
            print(f"  MISS      {needle}")
    print()

    if missing:
        print(f"{missing} 个长字符串在 UTF-8 与 UTF-16LE 里都没找到，"
              f"这类长度不会被 small-string 优化，说明确实没编进这个二进制。")
        return 1
    if uncertain:
        print(f"全部长字符串都找到；另有 {uncertain} 个短字符串无法判定"
              f"（small-string 优化），要确认它们请查别的证据。")
        return 0
    print("全部找到。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
