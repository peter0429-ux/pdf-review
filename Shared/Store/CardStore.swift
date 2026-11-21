//
//  CardStore.swift
//  PdfReview
//
//  App 侧唯一的 SwiftData 写者。负责：
//   1. 增删牌组与卡片
//   2. 把 SwiftData 变更物化成 App Group 的 rotation-cache.json
//   3. 回填历史展示记录
//   4. 处理「下一张」与收藏的共享状态
//
//  设计要点见 docs/architecture.md 第 3.1 节：Widget 永远不直接读写 SwiftData。
//

import Foundation
import SwiftData
import WidgetKit

@MainActor
final class CardStore: ObservableObject {

    static let shared = CardStore()

    let container: ModelContainer
    var context: ModelContext { container.mainContext }

    /// 最近一次物化失败的原因，供界面提示。
    @Published private(set) var lastError: String?

    /// 记录一条非致命错误供界面展示。外部（App 入口、视图）用它汇报
    /// 那些「不该打断操作但用户需要知道」的失败。
    func reportError(_ message: String) {
        lastError = message
    }

    /// 用户看过提示后清掉，避免横幅一直挂着。
    func clearError() {
        lastError = nil
    }

    // MARK: 初始化

    init() {
        let schema = Schema([
            ReviewDeck.self,
            ReviewCard.self,
            CardDisplayRecord.self
        ])

        // 三级降级，目标是「无论签名环境如何，App 都能启动」：
        //  1. App Group 容器可用 → 用共享容器，小组件能读到同一份数据（正式形态）
        //  2. 容器不可用（典型场景：用免费 Apple ID 侧载，provisioning profile
        //     里没有 App Groups 能力，系统不会给容器）→ 退回 App 自己的本地
        //     存储。数据照常持久化，只是小组件读不到。
        //  3. 连本地存储都建不起来 → 内存模式，至少不至于白屏。
        if AppGroup.isContainerAvailable {
            do {
                let configuration = ModelConfiguration(
                    schema: schema,
                    isStoredInMemoryOnly: false,
                    allowsSave: true,
                    groupContainer: .identifier(AppGroup.identifier)
                )
                container = try ModelContainer(for: schema, configurations: [configuration])
                return
            } catch {
                lastError = "共享数据容器创建失败，已退回本地存储：\(error.localizedDescription)"
            }
        }

        do {
            let configuration = ModelConfiguration(
                schema: schema,
                isStoredInMemoryOnly: false,
                allowsSave: true
            )
            container = try ModelContainer(for: schema, configurations: [configuration])
            return
        } catch {
            lastError = "本地数据容器创建失败，已切换到临时存储：\(error.localizedDescription)"
        }

        let configuration = ModelConfiguration(
            schema: schema,
            isStoredInMemoryOnly: true,
            allowsSave: true
        )
        // 内存容器在正常情况下不会失败；若仍失败则问题严重到无法运行。
        container = try! ModelContainer(for: schema, configurations: [configuration])
    }

    // MARK: 查询

    func allDecks() -> [ReviewDeck] {
        let descriptor = FetchDescriptor<ReviewDeck>(
            sortBy: [SortDescriptor(\.createdAt, order: .reverse)]
        )
        return (try? context.fetch(descriptor)) ?? []
    }

    func deck(withID id: UUID) -> ReviewDeck? {
        var descriptor = FetchDescriptor<ReviewDeck>(
            predicate: #Predicate<ReviewDeck> { $0.id == id }
        )
        descriptor.fetchLimit = 1
        return (try? context.fetch(descriptor))?.first
    }

    func card(withID id: UUID) -> ReviewCard? {
        var descriptor = FetchDescriptor<ReviewCard>(
            predicate: #Predicate<ReviewCard> { $0.id == id }
        )
        descriptor.fetchLimit = 1
        return (try? context.fetch(descriptor))?.first
    }

    /// 所有可参与轮换的卡片（未归档牌组内的卡片）。
    func rotatableCards() -> [ReviewCard] {
        allDecks().filter(\.isRotatable).flatMap(\.sortedCards)
    }

    // MARK: 写入

    /// 保存新牌组及其卡片。返回牌组 ID。
    @discardableResult
    func insertDeck(
        title: String,
        sourceFileName: String?,
        sourceKind: String,
        pageCount: Int,
        summary: String?,
        language: String?,
        cards: [AnalysisDocument.CardItem]
    ) throws -> UUID {
        let deck = ReviewDeck(
            title: title,
            sourceFileName: sourceFileName,
            sourceKind: sourceKind,
            pageCount: pageCount,
            summary: summary,
            language: language
        )
        context.insert(deck)

        for item in cards {
            let card = ReviewCard(
                question: item.question.trimmingCharacters(in: .whitespacesAndNewlines),
                answer: item.answer.trimmingCharacters(in: .whitespacesAndNewlines),
                detail: item.detail,
                tags: item.tags ?? [],
                sourcePage: item.sourcePage,
                difficulty: ReviewCard.clampScore(item.difficulty ?? 3),
                importance: ReviewCard.clampScore(item.importance ?? 3)
            )
            card.deck = deck
            context.insert(card)
        }

        try save()
        try refreshRotationCache()
        return deck.id
    }

    /// 删除牌组（级联删除卡片与展示记录）。
    func delete(deck: ReviewDeck) throws {
        context.delete(deck)
        try save()
        try refreshRotationCache()
    }

    /// 删除单张卡片。
    func delete(card: ReviewCard) throws {
        context.delete(card)
        try save()
        try refreshRotationCache()
    }

    /// 切换收藏。
    func toggleFavorite(card: ReviewCard) throws {
        card.isFavorite.toggle()
        try save()
        // 同步到 App Group，供 Widget 立即感知
        var favorites = Set(AppGroup.defaults.stringArray(forKey: SharedKeys.favoriteCardIDs) ?? [])
        if card.isFavorite {
            favorites.insert(card.id.uuidString)
        } else {
            favorites.remove(card.id.uuidString)
        }
        AppGroup.defaults.set(Array(favorites), forKey: SharedKeys.favoriteCardIDs)
        try refreshRotationCache()
    }

    // MARK: 持久化

    func save() throws {
        if context.hasChanges {
            try context.save()
        }
    }

    // MARK: 物化到 App Group

    /// 把当前 SwiftData 内容物化为 Widget 可读的缓存文件。
    /// 卡片池签名变化（增删卡片/改题面）时更换 `orderSalt`，实现全量重排。
    func refreshRotationCache() throws {
        let settings = AppSettings.shared
        let decks = allDecks().filter(\.isRotatable)

        let favoriteIDs = Set(AppGroup.defaults.stringArray(forKey: SharedKeys.favoriteCardIDs) ?? [])

        let deckSnapshots: [DeckSnapshot] = decks.map {
            DeckSnapshot(id: $0.id, title: $0.title, cardCount: $0.cards.count)
        }

        let cardSnapshots: [CardSnapshot] = decks.flatMap { deck in
            deck.sortedCards.map { card in
                card.snapshot(
                    deckTitle: deck.title,
                    favoriteOverride: favoriteIDs.contains(card.id.uuidString) ? true : card.isFavorite
                )
            }
        }

        // 读取现有缓存，保留 epoch 与盐（除非卡片池变了）
        let existing = RotationCache.load()
        let signature = Self.signature(of: cardSnapshots)

        var cache: RotationCache
        if let existing = existing,
           existing.epoch.timeIntervalSince1970 > 0 {
            cache = existing
            cache.generatedAt = Date()
            cache.decks = deckSnapshots
            cache.cards = cardSnapshots
            cache.applySettings(
                intervalHours: settings.rotationIntervalHours,
                cardsPerSlot: settings.cardsPerSlot
            )
            // 卡片池变化 → 换盐重排，避免总看同一张
            if existing.signature != signature {
                cache.orderSalt = UUID().uuidString
            }
        } else {
            cache = RotationCache(
                epoch: Date(),
                intervalHours: settings.rotationIntervalHours,
                cardsPerSlot: settings.cardsPerSlot,
                orderSalt: UUID().uuidString,
                manualOffset: AppGroup.defaults.integer(forKey: SharedKeys.manualOffset),
                decks: deckSnapshots,
                cards: cardSnapshots
            )
        }

        cache.signature = signature
        try cache.save()
        AppGroup.defaults.set(
            Date().timeIntervalSince1970,
            forKey: SharedKeys.lastCacheRefresh
        )
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// 卡片池签名：卡片 ID + 题面。用于判断是否需要重新洗牌。
    ///
    /// 不能用 Swift 的 `Hasher`：它每次进程启动都会被随机播种，同一批卡片
    /// 两次启动算出的值不同，于是 `orderSalt` 会被反复判定为"变了"并重排，
    /// 用户每开一次 App 就看到一副新顺序，3 小时轮换彻底失效。
    /// 这里改用 FNV-1a（与 RotationScheduler 洗牌用的是同一个函数），
    /// 结果跨进程、跨设备稳定。
    private static func signature(of cards: [CardSnapshot]) -> String {
        var accumulator: UInt64 = 0xcbf2_9ce4_8422_2325
        for card in cards {
            // 依次混入 ID 与题面；用分隔符隔开，避免 "ab"+"c" 与 "a"+"bc" 撞车
            for piece in [card.id.uuidString, "\u{1F}", card.question, "\u{1E}"] {
                let h = RotationScheduler.fnv1a(piece)
                accumulator ^= h
                accumulator = accumulator &* 0x0000_0100_0000_01b3
            }
        }
        return String(accumulator, radix: 16)
    }

    // MARK: 历史回填

    /// 回填历史展示记录。
    ///
    /// 思路：用与 Widget 相同的纯函数推算「从上次回填到现在」之间已经过去的槽位，
    /// 为每个槽位写一条 `CardDisplayRecord`。因此 App 内的历史与小组件展示完全一致。
    func backlogHistory(upTo now: Date = Date()) throws {
        guard let cache = RotationCache.load(), !cache.isEmpty else { return }

        let currentIndex = RotationScheduler.slotIndex(at: now, cache: cache)

        // 找到已记录的最大槽位序号
        let descriptor = FetchDescriptor<CardDisplayRecord>(
            sortBy: [SortDescriptor(\.slotIndex, order: .reverse)]
        )
        let latest = (try? context.fetch(descriptor))?.first
        let lastRecordedIndex = latest?.slotIndex

        // 首次运行时只回填最近 8 个槽位，避免一次写入过多
        let startIndex: Int
        if let last = lastRecordedIndex {
            startIndex = max(last + 1, currentIndex - 8)
        } else {
            startIndex = currentIndex - 8
        }

        // 当前槽位之前（不含当前，当前槽位由 Widget 正在展示）
        guard startIndex < currentIndex else { return }

        var inserted = 0
        for index in startIndex..<currentIndex {
            guard let slot = RotationScheduler.slot(index: index, cache: cache) else { continue }
            for snapshot in slot.cards {
                guard let card = self.card(withID: snapshot.id) else { continue }
                let record = CardDisplayRecord(
                    shownAt: slot.start,
                    slotIndex: index,
                    surface: CardDisplayRecord.Surface.widget,
                    card: card
                )
                context.insert(record)
                inserted += 1
            }
            if inserted >= 200 { break }  // 单次回填上限，防止极端情况卡顿
        }

        if inserted > 0 {
            try save()
        }
    }

    /// 历史记录（最近的在前）。返回 (卡片, 展示时刻) 元组。
    func history(limit: Int = 100) -> [(card: ReviewCard, shownAt: Date, slotIndex: Int)] {
        var descriptor = FetchDescriptor<CardDisplayRecord>(
            sortBy: [SortDescriptor(\.shownAt, order: .reverse)]
        )
        descriptor.fetchLimit = limit
        let records = (try? context.fetch(descriptor)) ?? []
        return records.compactMap { record in
            guard let card = record.card else { return nil }
            return (card, record.shownAt, record.slotIndex)
        }
    }

    // MARK: 手动前进

    /// 「下一张」：把共享的 manualOffset 加一并写回缓存，然后重载小组件。
    func advanceToNextCard() throws {
        let next = AppGroup.defaults.integer(forKey: SharedKeys.manualOffset) + 1
        AppGroup.defaults.set(next, forKey: SharedKeys.manualOffset)

        if var cache = RotationCache.load() {
            cache.manualOffset = next
            try cache.save()
        }
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// 供 App 内「立即刷新小组件」按钮调用。
    func reloadWidgets() {
        WidgetCenter.shared.reloadAllTimelines()
    }
}

// MARK: - 布隆式收藏同步

extension CardStore {
    /// 把 App Group 里的收藏集合回灌到 SwiftData（Widget 里的收藏按钮改的是共享集合）。
    func syncFavoritesFromSharedState() throws {
        let favorites = Set(AppGroup.defaults.stringArray(forKey: SharedKeys.favoriteCardIDs) ?? [])
        guard !favorites.isEmpty else { return }

        let allCards = (try? context.fetch(FetchDescriptor<ReviewCard>())) ?? []
        var changed = false
        for card in allCards {
            let shouldBeFavorite = favorites.contains(card.id.uuidString)
            if card.isFavorite != shouldBeFavorite {
                card.isFavorite = shouldBeFavorite
                changed = true
            }
        }
        if changed {
            try save()
        }
    }
}
