//
//  RotationScheduler.swift
//  PdfReview
//
//  轮换调度：纯函数，无状态、不读时钟、不碰存储。
//  App 与 Widget 都调用同一套实现，因此同 cache + 同时刻必然得到同一结果。
//  见 docs/architecture.md 第 3.2 节。
//

import Foundation

// MARK: - 槽位

/// 一个轮换槽位：从 `start` 开始、持续 `intervalHours` 小时的那一轮。
struct RotationSlot: Identifiable, Hashable {
    /// 槽位序号，可为负（epoch 之前）。
    var index: Int
    /// 该槽位的起始时刻。
    var start: Date
    /// 该槽位展示的卡片（按确定性洗牌后的顺序）。
    var cards: [CardSnapshot]

    var id: Int { index }

    /// 该槽位的结束时刻。
    func end(intervalHours: Double) -> Date {
        start.addingTimeInterval(intervalHours * 3600)
    }
}

// MARK: - 调度器

enum RotationScheduler {

    // MARK: 槽位数学

    /// 给定时刻落在哪个槽位。`manualOffset` 参与计算，因此点「下一张」会立刻前进。
    static func slotIndex(at date: Date, cache: RotationCache) -> Int {
        let interval = intervalSeconds(cache)
        let elapsed = date.timeIntervalSince(cache.epoch)
        // 用 floor 保证 epoch 之前也得到正确的负序号。
        let raw = (elapsed / interval).rounded(.down)
        guard raw.isFinite else { return cache.manualOffset }
        return Int(raw) + cache.manualOffset
    }

    /// 槽位序号对应的起始时刻。与 `slotIndex(at:cache:)` 严格互逆。
    static func slotStart(index: Int, cache: RotationCache) -> Date {
        let interval = intervalSeconds(cache)
        let steps = Double(index - cache.manualOffset)
        return cache.epoch.addingTimeInterval(steps * interval)
    }

    // MARK: 槽位内容

    /// 某时刻应展示的槽位。卡片池为空时返回 nil。
    static func slot(at date: Date, cache: RotationCache) -> RotationSlot? {
        guard !cache.cards.isEmpty else { return nil }
        let index = slotIndex(at: date, cache: cache)
        return slot(index: index, cache: cache)
    }

    /// 由槽位序号构造槽位。序号可以是负数。
    static func slot(index: Int, cache: RotationCache) -> RotationSlot? {
        guard !cache.cards.isEmpty else { return nil }
        let pool = ordered(cache.cards, salt: cache.orderSalt)
        guard !pool.isEmpty else { return nil }

        let perSlot = max(1, cache.cardsPerSlot)
        let total = pool.count

        // 一个完整循环覆盖全部卡片：槽位数 = 卡片数 / 每槽张数（向上取整）。
        // 把可能是负数的槽位序号规范化到 [0, slotsPerCycle)，避免负索引。
        let slotsPerCycle = max(1, (total + perSlot - 1) / perSlot)
        let normalizedSlot = ((index % slotsPerCycle) + slotsPerCycle) % slotsPerCycle

        var picked: [CardSnapshot] = []
        picked.reserveCapacity(perSlot)
        for offset in 0..<perSlot {
            let position = (normalizedSlot * perSlot + offset) % total
            picked.append(pool[position])
        }

        return RotationSlot(
            index: index,
            start: slotStart(index: index, cache: cache),
            cards: picked
        )
    }

    /// 从某时刻起预排 `count` 个槽位，供 WidgetKit 构建 Timeline。
    /// 第 0 个是「当前时刻所处的槽位」，但起始时间保留真实值，
    /// 调用方若需要「从下一个整点开始」应自行调整。
    static func upcoming(at date: Date, count: Int, cache: RotationCache) -> [RotationSlot] {
        guard !cache.cards.isEmpty, count > 0 else { return [] }
        let base = slotIndex(at: date, cache: cache)
        var result: [RotationSlot] = []
        result.reserveCapacity(count)
        for step in 0..<count {
            if let slot = slot(index: base + step, cache: cache) {
                result.append(slot)
            }
        }
        return result
    }

    /// 从某时刻往回收集最近 `count` 个槽位（不含当前槽位），用于历史回顾。
    /// 结果按时间倒序（最近的在前），并去重（同一张卡只保留最近一次）。
    static func recentHistory(
        at date: Date,
        count: Int,
        cache: RotationCache,
        excludingCurrent: Bool = true
    ) -> [CardSnapshot] {
        guard !cache.cards.isEmpty, count > 0 else { return [] }
        let base = slotIndex(at: date, cache: cache)
        let start = excludingCurrent ? base - 1 : base

        var seen = Set<UUID>()
        var result: [CardSnapshot] = []

        // 最多回看 count 个槽位；卡片池很小时会自然重复，靠 seen 去重。
        for step in 0..<count {
            guard let slot = slot(index: start - step, cache: cache) else { continue }
            for card in slot.cards.reversed() {
                if seen.insert(card.id).inserted {
                    result.append(card)
                }
            }
        }
        return result
    }

    // MARK: 时长换算

    /// 距当前槽位结束还剩多少秒（用于小组件倒计时）。
    static func secondsRemaining(at date: Date, cache: RotationCache) -> TimeInterval {
        let interval = intervalSeconds(cache)
        let index = slotIndex(at: date, cache: cache)
        let end = slotStart(index: index + 1, cache: cache)
        return max(0, end.timeIntervalSince(date))
    }

    // MARK: 确定性洗牌

    /// 基于盐的确定性洗牌。同样的输入与盐必然得到同样的顺序，且跨进程一致。
    /// 使用 SplitMix64 + Fisher–Yates，种子取自盐的 FNV-1a 哈希。
    static func ordered(_ cards: [CardSnapshot], salt: String) -> [CardSnapshot] {
        guard cards.count > 1 else { return cards }
        var generator = SplitMix64(seed: fnv1a(salt))
        var result = cards
        var i = result.count - 1
        while i > 0 {
            let j = Int(generator.next() % UInt64(i + 1))
            result.swapAt(i, j)
            i -= 1
        }
        return result
    }

    // MARK: 内部工具

    private static func intervalSeconds(_ cache: RotationCache) -> Double {
        let hours = cache.intervalHours
        // 防御非法值：小于 15 分钟或大于 24 小时都视为 3 小时。
        guard hours.isFinite, hours >= 0.25, hours <= 24 else {
            return 3 * 3600
        }
        return hours * 3600
    }

    /// FNV-1a 64 位哈希，用于把字符串盐转成种子。
    static func fnv1a(_ string: String) -> UInt64 {
        var hash: UInt64 = 0xcbf2_9ce4_8422_2325
        for byte in string.utf8 {
            hash ^= UInt64(byte)
            hash = hash &* 0x0000_0100_0000_01b3
        }
        return hash
    }
}

// MARK: - SplitMix64

/// 极简确定性伪随机数生成器。跨平台、跨进程结果一致，不依赖标准库实现细节。
struct SplitMix64 {
    private var state: UInt64

    init(seed: UInt64) {
        self.state = seed
    }

    mutating func next() -> UInt64 {
        state = state &+ 0x9e37_79b9_7f4a_7c15
        var z = state
        z = (z ^ (z >> 30)) &* 0xbf58_476d_1ce4_e5b9
        z = (z ^ (z >> 27)) &* 0x94d0_49bb_1331_11eb
        return z ^ (z >> 31)
    }
}
