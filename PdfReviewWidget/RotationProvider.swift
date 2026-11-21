//
//  RotationProvider.swift
//  PdfReviewWidget
//
//  Timeline Provider。只读 Shared/Core/RotationCache.swift 写出的 JSON 读模型，
//  用 Shared/Core/RotationScheduler.swift 的纯函数推算轮换结果。
//  小组件不链接 SwiftData，也不写 SwiftData（见 docs/architecture.md 3.1 / 7.3）。
//

import Foundation
import WidgetKit

// MARK: - App Group 键
//
// 键名统一用 Shared/Core/AppGroup.swift 里的 `SharedKeys`，不在这里另开一套，
// 否则 App 与 Widget 各写各的字符串字面量，改一处漏一处（docs/architecture.md 第 5 节）：
//   - SharedKeys.manualOffset      → "rotation.manualOffset"（Int）
//   - SharedKeys.favoriteCardIDs   → "favorites.cardIDs"（[String]，UUID 的 uuidString）
//   - SharedKeys.lastCacheRefresh  → "rotation.lastRefresh"（仅 App 使用）

// MARK: - 收藏集合

/// 收藏状态以 App Group UserDefaults 为准（App 侧负责回灌 SwiftData）。
enum FavoriteStore {

    /// 读取收藏集合；返回 nil 表示这个键从未被写过，此时沿用 cache 里的 isFavorite。
    static func storedIDs() -> Set<String>? {
        guard let raw = AppGroup.defaults.stringArray(forKey: SharedKeys.favoriteCardIDs) else {
            return nil
        }
        return Set(raw.map { $0.lowercased() })
    }

    static func contains(_ cardID: UUID, in set: Set<String>) -> Bool {
        set.contains(cardID.uuidString.lowercased())
    }

    /// 切换收藏状态，返回切换后的状态。
    /// 写回时的元素格式必须是 `UUID().uuidString`（大写），因为 App 侧的
    /// `CardStore.syncFavoritesFromSharedState()` 用 `favorites.contains(card.id.uuidString)`
    /// 做精确比对。读取时两端都做大小写不敏感比较，避免历史数据大小写不一致漏判。
    @discardableResult
    static func toggle(_ cardID: UUID) -> Bool {
        let key = SharedKeys.favoriteCardIDs
        var ids = AppGroup.defaults.stringArray(forKey: key) ?? []
        let target = cardID.uuidString
        let isFavorited: Bool

        if let index = ids.firstIndex(where: { $0.caseInsensitiveCompare(target) == .orderedSame }) {
            ids.remove(at: index)
            isFavorited = false
        } else {
            ids.append(target)
            isFavorited = true
        }

        AppGroup.defaults.set(ids, forKey: key)
        return isFavorited
    }

    /// 用收藏集合覆盖 CardSnapshot.isFavorite。
    /// 只覆盖一层拷贝，不修改 RotationCache 结构。
    static func applying(to cards: [CardSnapshot]) -> [CardSnapshot] {
        guard let stored = storedIDs() else { return cards }
        return cards.map { card in
            var copy = card
            copy.isFavorite = contains(card.id, in: stored)
            return copy
        }
    }
}

// MARK: - Entry

struct RotationEntry: TimelineEntry {
    let date: Date
    let current: CardSnapshot?
    /// 最近已展示过的卡片，按时间倒序。
    let history: [CardSnapshot]
    let upcomingCount: Int
    let totalCards: Int

    // 下面两个字段只在小组件内部使用，带默认值，App 侧不构造 RotationEntry，
    // 因此不影响 docs/architecture.md 里的契约。

    /// 轮换间隔（小时），用于「3 小时一换 · 剩余 …」文案与倒计时。
    var intervalHours: Double = 3
    /// 本轮轮换的真实起点。`date` 对「当前轮」取的是当前时刻，早于它，
    /// 所以倒计时必须以 slotStart 为锚点。
    var slotStart: Date? = nil

    /// 数据来源。空态文案要据此区分「还没导入过」和「签名缺 App Groups」，
    /// 否则用户会一直等一个不会发生的事。
    var source: DataSource = .shared

    enum DataSource {
        /// App 通过 App Group 共享容器写入的真实数据。
        case shared
        /// 内置种子（签名缺 App Groups 或 App 尚未写过缓存）。
        case bundledSeed
    }

    /// 倒计时锚点。
    var rotationAnchor: Date { slotStart ?? date }
}

// MARK: - Provider

struct RotationProvider: TimelineProvider {

    // MARK: 常量

    /// 每轮预排的 entry 数量。
    private static let entryCount = 8
    /// history 最多往回看多少个 slot。
    private static let historyLookbackSlots = 12
    /// history 最多展示几张。
    private static let historyLimit = 3
    /// 读不到 cache 时的重试间隔。
    private static let retryInterval: TimeInterval = 15 * 60
    /// cache.intervalHours 异常时的兜底值。
    private static let defaultIntervalHours: Double = 3
    /// 最后一个 entry 之后多久再续排。
    private static let trailingDelay: TimeInterval = 60

    // MARK: 缓存读取（带内置种子兜底）

    /// 读缓存，三级降级（实现见 `RotationCache.resolve`）：
    ///
    /// 1. **共享容器**里的 `rotation-cache.json` —— 正常路径。App 导入 PDF 后
    ///    由 `CardStore.refreshRotationCache()` 写入，是最新的真实数据。
    /// 2. **本进程缓存位置**里的同文件 —— 上一轮已把种子复制过来的副本，
    ///    带用户自己的收藏/手动翻页状态。
    /// 3. **内置种子**（bundle 资源）—— 首次安装、App 还没跑过、或签名缺
    ///    App Groups 时，保证小组件不显示空态。读到后会复制进本进程容器，
    ///    因为 `NextCardIntent` / `ToggleFavoriteIntent` 都要写缓存。
    ///
    /// 前两级在 App 进程里是同一个路径（App Group 容器，不可用时退化为
    /// App 自己的 Documents）；在 Widget 进程里是两个不同沙盒，
    /// 这正是需要种子兜底的原因。
    private static func loadCache() -> (cache: RotationCache, isSeeded: Bool)? {
        let resolved = RotationCache.resolve()
        guard let cache = resolved.cache else { return nil }
        return (cache, resolved.isSeeded)
    }

    // MARK: TimelineProvider

    func placeholder(in context: Context) -> RotationEntry {
        RotationProvider.previewEntry(now: Date())
    }

    func getSnapshot(in context: Context, completion: @escaping (RotationEntry) -> Void) {
        let now = Date()

        if context.isPreview {
            completion(RotationProvider.previewEntry(now: now))
            return
        }

        completion(RotationProvider.firstEntry(now: now))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<RotationEntry>) -> Void) {
        let now = Date()

        // cache 不存在或卡片池为空：先给占位，15 分钟后再试。
        // 这里必须写全 `RotationProvider.loadCache()`：TimelineProvider 的方法
        // 都是实例方法，而 loadCache 是 static，不能靠类型推断省掉前缀。
        guard let resolved = RotationProvider.loadCache() else {
            let entry = RotationProvider.emptyEntry(now: now)
            let policy = TimelineReloadPolicy.after(now.addingTimeInterval(RotationProvider.retryInterval))
            completion(Timeline(entries: [entry], policy: policy))
            return
        }

        let timelineEntries = RotationProvider.entries(
            now: now, cache: resolved.cache, isSeeded: resolved.isSeeded
        )
        let lastDate = timelineEntries.last?.date ?? now
        let refreshDate = lastDate.addingTimeInterval(RotationProvider.trailingDelay)
        completion(Timeline(entries: timelineEntries, policy: .after(refreshDate)))
    }

    // MARK: 构建

    private static func emptyEntry(now: Date) -> RotationEntry {
        RotationEntry(
            date: now,
            current: nil,
            history: [],
            upcomingCount: 0,
            totalCards: 0
        )
    }

    /// placeholder / Preview / Widget Gallery 用：静态样例数据，避免空白。
    private static func previewEntry(now: Date) -> RotationEntry {
        RotationEntry(
            date: now,
            current: CardSnapshot.preview,
            history: CardSnapshot.previewHistory,
            upcomingCount: 5,
            totalCards: 24,
            intervalHours: defaultIntervalHours,
            slotStart: now.addingTimeInterval(-20 * 60)
        )
    }

    private static func firstEntry(now: Date) -> RotationEntry {
        guard let resolved = loadCache() else {
            return emptyEntry(now: now)
        }
        return entries(now: now, cache: resolved.cache, isSeeded: resolved.isSeeded).first
            ?? emptyEntry(now: now)
    }

    /// 预排 entryCount 个 entry：当前轮 + 后续轮。
    private static func entries(
        now: Date,
        cache: RotationCache,
        isSeeded: Bool
    ) -> [RotationEntry] {
        let interval = normalizedInterval(cache)
        let scheduled = RotationScheduler.upcoming(at: now, count: entryCount, cache: cache)
        let currentSlot = RotationScheduler.slot(at: now, cache: cache)

        // upcoming 是否包含当前轮，取决于 Shared 侧的实现；两种语义都兼容。
        var window: [RotationSlot] = []
        if let currentSlot = currentSlot,
           !scheduled.contains(where: { $0.index == currentSlot.index }) {
            window.append(currentSlot)
        }
        window.append(contentsOf: scheduled)
        if window.isEmpty, let currentSlot = currentSlot {
            window.append(currentSlot)
        }
        guard !window.isEmpty else {
            return [emptyEntry(now: now)]
        }

        let slots = Array(window.prefix(entryCount))

        // 本轮之后、预排窗口内还会出现的卡片数（按 id 去重）。
        var upcomingCounts = Array(repeating: 0, count: slots.count)
        var seenAfter = Set<UUID>()
        var cursor = slots.count - 1
        while cursor >= 0 {
            upcomingCounts[cursor] = seenAfter.count
            for card in slots[cursor].cards {
                seenAfter.insert(card.id)
            }
            cursor -= 1
        }

        return slots.enumerated().map { offset, slot in
            let cards = FavoriteStore.applying(to: slot.cards)
            return RotationEntry(
                date: max(slot.start, now),
                current: cards.first,
                history: history(before: slot.index, cache: cache),
                upcomingCount: upcomingCounts[offset],
                totalCards: cache.cards.count,
                intervalHours: interval,
                slotStart: slot.start,
                source: isSeeded ? .bundledSeed : .shared
            )
        }
    }

    /// 历史回顾：从 `index` 之前的 slot 往前推最多 historyLookbackSlots 个，
    /// 收集卡片、去重、取最近 historyLimit 张。
    ///
    /// 直接复用 `RotationScheduler.recentHistory`，不在这里重写一遍槽位遍历：
    /// 契约要求 App 与 Widget 看到的历史完全一致（docs/architecture.md 3.1），
    /// 两处各写一份必然会在负索引取模、去重顺序这类细节上分叉。
    private static func history(before index: Int, cache: RotationCache) -> [CardSnapshot] {
        let interval = normalizedInterval(cache)
        // recentHistory 按 `slotIndex(at: probe)` 反推基准槽位，
        // 因此 probe 必须落在 `index` 这个 slot 内部的中点上：
        // 起点偏移 0.5 个 interval，floor 后正好落在 index。
        let start = RotationScheduler.slotStart(index: index, cache: cache)
        let probe = start.addingTimeInterval(interval * 3600 / 2)

        let cards = RotationScheduler.recentHistory(
            at: probe,
            count: historyLookbackSlots,
            cache: cache
        )

        let ordered = Array(cards.prefix(historyLimit))
        return FavoriteStore.applying(to: ordered)
    }

    private static func normalizedInterval(_ cache: RotationCache) -> Double {
        let raw = cache.intervalHours
        guard raw.isFinite, raw > 0 else { return defaultIntervalHours }
        return raw
    }
}
