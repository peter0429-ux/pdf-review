#!/usr/bin/env python3
"""核验 CI 产出的 IPA：架构、Info.plist、两个种子资源、以及种子内容本身。

为什么要有这一步：CI 的 xcode-build 只能证明「编译通过、IPA 打出来了」，
不能证明包里的东西对。种子资源要是不小心没进 Resources phase，App 装上
后小组件还是空的，而 CI 依然全绿。
"""

from __future__ import annotations

import json
import plistlib
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check_binary(app: Path) -> list[str]:
    problems: list[str] = []
    binary = app / "PdfReview"
    data = binary.read_bytes()
    magic = data[:4]
    cputype = struct.unpack("<i", data[4:8])[0]
    filetype = struct.unpack("<i", data[12:16])[0]

    print("=== 主二进制 ===")
    print(f"  大小     : {len(data)}")
    print(f"  magic    : {magic.hex().upper()}")
    print(f"  cputype  : 0x{cputype:08X}")
    print(f"  filetype : {filetype}")

    if magic.hex().upper() != "CFFAEDFE":
        problems.append(f"magic 不是 Mach-O 64 位小端：{magic.hex().upper()}")
    if cputype != 0x0100000C:
        problems.append(f"cputype 不是 arm64 真机：0x{cputype:08X}（模拟器版真机装不上）")
    if filetype != 2:
        problems.append(f"filetype 不是 MH_EXECUTE(2)：{filetype}")
    return problems


def check_app_plist(app: Path) -> list[str]:
    problems: list[str] = []
    with open(app / "Info.plist", "rb") as f:
        info = plistlib.load(f)

    print()
    print("=== App Info.plist ===")
    wanted = [
        "CFBundleIdentifier",
        "CFBundleShortVersionString",
        "CFBundleVersion",
        "MinimumOSVersion",
        "CFBundleDisplayName",
        "CFBundleExecutable",
    ]
    for key in wanted:
        print(f"  {key:<28} = {info.get(key)!r}")

    caps = info.get("UIRequiredDeviceCapabilities")
    print(f"  {'UIRequiredDeviceCapabilities':<28} = {caps}")
    if caps and "armv7" in caps:
        problems.append("UIRequiredDeviceCapabilities 含 armv7，真机会报「与此设备不兼容」")

    doc_types = info.get("CFBundleDocumentTypes", [])
    exported = info.get("UTExportedTypeDeclarations", [])
    print(f"  {'CFBundleDocumentTypes':<28} = {len(doc_types)} 条")
    print(f"  {'UTExportedTypeDeclarations':<28} = "
          f"{[d.get('UTTypeIdentifier') for d in exported]}")
    if len(doc_types) < 3:
        problems.append(f"CFBundleDocumentTypes 只有 {len(doc_types)} 条，应为 3 条")

    if info.get("CFBundleIdentifier") != "com.pdfreview.app":
        problems.append(f"CFBundleIdentifier 不对：{info.get('CFBundleIdentifier')}")

    widget_plist = app / "PlugIns" / "PdfReviewWidget.appex" / "Info.plist"
    if widget_plist.exists():
        with open(widget_plist, "rb") as f:
            winfo = plistlib.load(f)
        print()
        print("=== Widget Info.plist ===")
        print(f"  CFBundleIdentifier        = {winfo.get('CFBundleIdentifier')!r}")
        print(f"  CFBundlePackageType       = {winfo.get('CFBundlePackageType')!r}")
        point = winfo.get("NSExtension", {}).get("NSExtensionPointIdentifier")
        print(f"  NSExtensionPointIdentifier= {point!r}")
        if point != "com.apple.widgetkit-extension":
            problems.append(f"Widget 的 NSExtensionPointIdentifier 不对：{point}")
    else:
        problems.append("包里没有 PlugIns/PdfReviewWidget.appex")

    return problems


def check_seeds(app: Path) -> list[str]:
    problems: list[str] = []

    print()
    print("=== 种子资源是否真的打进包里 ===")

    widget_seed = app / "PlugIns" / "PdfReviewWidget.appex" / "rotation-cache.json"
    app_seed = app / "seed-analysis.pdfreview.json"

    for path, label in [(widget_seed, "小组件种子"), (app_seed, "App 种子")]:
        if path.exists():
            print(f"  OK   {label}: {path.name}  {path.stat().st_size} 字节")
        else:
            print(f"  缺失 {label}: {path.name}")
            problems.append(f"{label} {path.name} 没进包")

    if widget_seed.exists():
        cache = json.loads(widget_seed.read_text(encoding="utf-8"))
        cards = cache.get("cards", [])
        decks = cache.get("decks", [])
        ids = {c["id"] for c in cards}
        print()
        print("=== 小组件种子内容 ===")
        print(f"  version       : {cache.get('version')}")
        print(f"  epoch         : {cache.get('epoch')}")
        print(f"  intervalHours : {cache.get('intervalHours')}")
        print(f"  orderSalt     : {cache.get('orderSalt')}")
        print(f"  manualOffset  : {cache.get('manualOffset')}")
        print(f"  牌组          : {[d['title'] for d in decks]}")
        print(f"  卡片数        : {len(cards)}（唯一 ID {len(ids)}）")
        if len(ids) != len(cards):
            problems.append(f"种子卡片 ID 有重复：{len(cards)} 张只有 {len(ids)} 个唯一 ID")
        if not cards:
            problems.append("小组件种子里没有卡片")
        deck_ids = {d["id"] for d in decks}
        dangling = {c["deckID"] for c in cards} - deck_ids
        if dangling:
            problems.append(f"有卡片的 deckID 指向不存在的牌组：{dangling}")
        # epoch 必须是固定常量：换了它，两端 slotIndex 就会错位
        if cache.get("epoch") != "2026-01-01T00:00:00Z":
            problems.append(f"种子 epoch 不是约定的固定常量：{cache.get('epoch')}")

    if app_seed.exists():
        doc = json.loads(app_seed.read_text(encoding="utf-8"))
        print()
        print("=== App 种子内容 ===")
        print(f"  schemaVersion : {doc.get('schemaVersion')}")
        print(f"  deck.title    : {doc.get('deck', {}).get('title')}")
        print(f"  卡片数        : {len(doc.get('cards', []))}")
        if doc.get("schemaVersion") != "1.0":
            problems.append(f"App 种子 schemaVersion 不是 1.0：{doc.get('schemaVersion')}")

    return problems


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/verify_ipa.py <解包后的 Payload 目录>")
        return 2

    payload = Path(sys.argv[1])
    app = payload / "Payload" / "PdfReview.app"
    if not app.exists():
        app = payload / "PdfReview.app"
    if not app.exists():
        print(f"找不到 PdfReview.app，给定路径：{payload}")
        return 2

    problems: list[str] = []
    problems += check_binary(app)
    problems += check_app_plist(app)
    problems += check_seeds(app)

    print()
    print("=" * 60)
    if problems:
        print(f"核验失败，{len(problems)} 个问题：")
        for i, p in enumerate(problems, 1):
            print(f"  {i}. {p}")
        return 1
    print("核验通过：架构正确、Info.plist 完整、两个种子资源都在且内容自洽。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
