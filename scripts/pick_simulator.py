#!/usr/bin/env python3
"""从 xcrun simctl list devices available -j 的输出里挑一台可用的 iPhone 模拟器。

CI 里单独成文件而不是塞进 workflow 的内联 heredoc：YAML 块里的
Python 引号嵌套极难维护，出错时 GitHub 只报「YAML 解析失败」，很难查。
"""

import json
import subprocess
import sys


def main() -> int:
    raw = subprocess.run(
        ["xcrun", "simctl", "list", "devices", "available", "-j"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    data = json.loads(raw)["devices"]

    candidates = []
    for runtime, items in data.items():
        if "iOS" not in runtime:
            continue
        for device in items:
            if not device.get("isAvailable"):
                continue
            name = device.get("name", "")
            if not name.startswith("iPhone"):
                continue
            candidates.append((runtime, name, device["udid"]))

    if not candidates:
        print("没有可用的 iPhone 模拟器", file=sys.stderr)
        return 1

    # 优先最新 runtime（runtime 标识形如 com.apple.CoreSimulator.SimRuntime.iOS-18-5）
    def runtime_key(entry):
        runtime = entry[0]
        parts = runtime.split(".")[-1].replace("iOS-", "").split("-")
        try:
            return tuple(int(p) for p in parts)
        except ValueError:
            return (0,)

    candidates.sort(key=runtime_key)
    runtime, name, udid = candidates[-1]
    print(f"选中 {name}（{runtime}）", file=sys.stderr)
    print(udid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
