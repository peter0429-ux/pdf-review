#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 .pdfreview.json 分析文件转成小组件用的内置轮换缓存。

为什么需要这个脚本
==================
App 与小组件需要**两种不同格式**的同一批卡片：

  - App 读 ``AnalysisDocument`` 格式（.pdfreview.json），用于导入 SwiftData
  - 小组件读 ``RotationCache`` 格式，直接渲染

两者字段集不同：RotationCache 多了 deckID / deckTitle / isFavorite，
少了 difficulty / importance（小组件不显示）。手工维护两份必然分叉，
所以只保留一份源数据，另一份由本脚本生成。

产出的文件名是 ``bundled-wheel.json``，不是 ``rotation-cache.json``：
后者是 App 运行时写进 App Group 容器的**可变缓存**的文件名，两者格式
相同但生命周期完全不同。名字分开，排查问题时才不会弄混。

UUID 必须稳定
=============
卡片 ID 用题面文本的 md5 派生（版本 5 风格），这样：
  - 重新生成种子时 ID 不变 → 用户已收藏的卡片不会丢
  - 换主题重新生成时，不同题面自然得到不同 ID

epoch 为什么固定在 2026-01-01
=============================
``slotIndex = floor((now - epoch) / intervalHours) + manualOffset``
epoch 固定，小组件在任何设备、任何安装时间算出的 slot 都一致。
用「首次启动时间」当 epoch 会导致重装后轮换位置跳变。

用法
====
    python scripts/build_seed_cache.py

输入：PdfReview/Resources/bundled-deck.pdfreview.json
输出：PdfReviewWidget/Resources/bundled-wheel.json
"""

import hashlib
import json
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCE = os.path.join(ROOT, "PdfReview", "Resources", "bundled-deck.pdfreview.json")
TARGET = os.path.join(ROOT, "PdfReviewWidget", "Resources", "bundled-wheel.json")

# 固定的轮换锚点。改这个值等于让所有设备上的轮换位置整体平移，不要随意改。
EPOCH = "2026-01-01T00:00:00Z"
# 固定的洗牌盐。改它就等于重新洗一遍牌。
ORDER_SALT = "bundled-basics-v1"
# 轮换周期（小时）。用户可在 App 里改，这里只是初始值。
INTERVAL_HOURS = 3
# 每轮显示几张。
CARDS_PER_SLOT = 1


def stable_uuid(text: str) -> str:
    """由字符串派生稳定的 UUID（RFC 4122 version 5 风格的构造方式）。"""
    digest = hashlib.md5(text.encode("utf-8")).digest()
    # 把版本位和变体位设成 v5 的样子，便于人眼看出版本是派生的
    b = bytearray(digest)
    b[6] = (b[6] & 0x0F) | 0x50
    b[8] = (b[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(b)))


def main() -> int:
    if not os.path.exists(SOURCE):
        print(f"找不到源文件：{SOURCE}", file=sys.stderr)
        return 1

    with open(SOURCE, "r", encoding="utf-8") as f:
        document = json.load(f)

    deck_title = document["deck"]["title"]
    cards_in = document["cards"]
    if not cards_in:
        print("源文件的 cards 是空的", file=sys.stderr)
        return 1

    deck_id = stable_uuid("deck:" + deck_title)

    cards_out = []
    for index, item in enumerate(cards_in):
        question = item["question"]
        cards_out.append(
            {
                "id": stable_uuid(f"card:{index}:{question}"),
                "deckID": deck_id,
                "deckTitle": deck_title,
                "question": question,
                "answer": item["answer"],
                "detail": item.get("detail"),
                "tags": item.get("tags") or [],
                "sourcePage": item.get("sourcePage"),
                "isFavorite": False,
            }
        )

    cache = {
        "version": 1,
        "generatedAt": EPOCH,
        "epoch": EPOCH,
        "intervalHours": INTERVAL_HOURS,
        "cardsPerSlot": CARDS_PER_SLOT,
        "orderSalt": ORDER_SALT,
        "manualOffset": 0,
        "decks": [
            {
                "id": deck_id,
                "title": deck_title,
                "cardCount": len(cards_out),
            }
        ],
        "cards": cards_out,
    }

    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    with open(TARGET, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size = os.path.getsize(TARGET)
    print(f"已写入 {os.path.relpath(TARGET, ROOT)}")
    print(f"  牌组：{deck_title}")
    print(f"  卡片：{len(cards_out)} 张")
    print(f"  deckID：{deck_id}")
    print(f"  epoch：{EPOCH}  盐：{ORDER_SALT}")
    print(f"  字节数：{size}")

    # 自检：ID 不许重复，否则小组件按 id 去重时会把卡片吞掉
    ids = [c["id"] for c in cards_out]
    if len(set(ids)) != len(ids):
        print("错误：生成的卡片 ID 有重复", file=sys.stderr)
        return 1

    # 自检：必填字段一个都不能少，否则 Swift 侧 Codable 解码会整份失败
    required = {"id", "deckID", "deckTitle", "question", "answer", "tags", "isFavorite"}
    for c in cards_out:
        missing = required - set(c.keys())
        if missing:
            print(f"错误：卡片缺少字段 {missing}", file=sys.stderr)
            return 1

    print("自检通过：ID 无重复、必填字段齐全。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
