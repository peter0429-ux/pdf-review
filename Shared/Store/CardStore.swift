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
            CardDisplayRecord.self,
            AskThread.self
        ])

        // 顺序很重要：先落日志，再碰 App Group。
        // 字符串插值会先求值、后调用 `note`——如果求值那一步把进程带走，
        // 插值写法会导致日志一条都写不出来，看上去像「什么都没发生」。
        LaunchLog.note("启动：开始创建数据容器")

        // 为什么这里**不用** `groupContainer:`？
        //
        // 架构上 SwiftData 只有 App 一个写者，小组件读的是物化出来的
        // rotation-cache.json（见 docs/architecture.md 3.1）。把 SwiftData
        // 库文件放进 App Group 共享容器不带来任何收益，却引入一个致命风险：
        // 用免费 Apple ID 侧载时 provisioning profile 里没有 App Groups
        // 能力，`ModelConfiguration(groupContainer:)` 在那种环境下会直接
        // 崩——而且是 C 层的沙箱拒绝，不是可 catch 的 Swift 错误。
        //
        // 之前的实现把它放在第一级，于是「一打开就闪退」。现在改成本地存储，
        // 小组件那条路单独用 AppGroup 的断路器兜（见 Shared/Core/AppGroup.swift）。
        //
        // 两级降级：本地持久化 → 内存。
        do {
            let configuration = ModelConfiguration(
                schema: schema,
                isStoredInMemoryOnly: false,
                allowsSave: true
            )
            container = try ModelContainer(for: schema, configurations: [configuration])
            LaunchLog.note("容器：本地持久化")
            return
        } catch {
            lastError = "本地数据容器创建失败，已切换到临时存储：\(error.localizedDescription)"
            LaunchLog.note("容器：本地也失败 → \(error.localizedDescription)")
        }

        let configuration = ModelConfiguration(
            schema: schema,
            isStoredInMemoryOnly: true,
            allowsSave: true
        )
        // 内存容器在正常情况下不会失败；若仍失败则问题严重到无法运行。
        container = try! ModelContainer(for: schema, configurations: [configuration])
        LaunchLog.note("容器：内存模式（数据不持久化）")
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
        sourceText: String? = nil,
        cards: [AnalysisDocument.CardItem]
    ) throws -> UUID {
        let deck = ReviewDeck(
            title: title,
            sourceFileName: sourceFileName,
            sourceKind: sourceKind,
            pageCount: pageCount,
            summary: summary,
            language: language,
            sourceText: ReviewDeck.clippedSourceText(sourceText ?? "")
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
                importance: ReviewCard.clampScore(item.importance ?? 3),
                origin: ReviewCard.Origin.analysis
            )
            card.deck = deck
            context.insert(card)
        }

        try save()
        try refreshRotationCache()
        return deck.id
    }

    /// 往已有牌组里插入一张卡片。返回新卡片的 ID。
    ///
    /// 与 `insertDeck` 的区别只是「不新建牌组」，但物化缓存那一步不能省：
    /// 新卡片必须立刻进入轮换池，否则用户保存完在复习页看不到它。
    @discardableResult
    func insertCard(
        into deck: ReviewDeck,
        question: String,
        answer: String,
        detail: String? = nil,
        tags: [String] = [],
        sourcePage: Int? = nil,
        difficulty: Int = 3,
        importance: Int = 3,
        origin: String = ReviewCard.Origin.manual
    ) throws -> UUID {
        let card = ReviewCard(
            question: question.trimmingCharacters(in: .whitespacesAndNewlines),
            answer: answer.trimmingCharacters(in: .whitespacesAndNewlines),
            detail: detail,
            tags: tags,
            sourcePage: sourcePage,
            difficulty: difficulty,
            importance: importance,
            origin: origin
        )
        card.deck = deck
        context.insert(card)
        deck.updatedAt = Date()

        try save()
        try refreshRotationCache()
        return card.id
    }

    /// 保存一次提问记录。返回记录 ID。
    @discardableResult
    func insertAskThread(
        question: String,
        answer: String,
        worthSaving: Bool,
        reason: String?,
        deckID: UUID?,
        deckTitle: String?,
        draft: AnalysisDocument.CardItem?
    ) throws -> UUID {
        let thread = AskThread(
            question: question,
            answer: answer,
            worthSaving: worthSaving,
            reason: reason,
            deckID: deckID,
            deckTitle: deckTitle
        )
        thread.setDraft(draft)
        context.insert(thread)
        try save()
        return thread.id
    }

    /// 把提问记录标记为「已保存成卡片」。
    func markThreadSaved(_ thread: AskThread, cardID: UUID) throws {
        thread.savedCardID = cardID
        try save()
    }

    /// 按 ID 标记「已保存」。界面只持有 ID，不必为了拿到对象再查一次全部记录。
    func markThreadSaved(threadID: UUID, cardID: UUID) throws {
        var descriptor = FetchDescriptor<AskThread>(
            predicate: #Predicate<AskThread> { $0.id == threadID }
        )
        descriptor.fetchLimit = 1
        guard let thread = (try? context.fetch(descriptor))?.first else { return }
        thread.savedCardID = cardID
        try save()
    }

    func askThread(withID id: UUID) -> AskThread? {
        var descriptor = FetchDescriptor<AskThread>(
            predicate: #Predicate<AskThread> { $0.id == id }
        )
        descriptor.fetchLimit = 1
        return (try? context.fetch(descriptor))?.first
    }

    /// 最近的提问记录，新的在前。
    func askThreads(limit: Int = 100) -> [AskThread] {
        var descriptor = FetchDescriptor<AskThread>(
            sortBy: [SortDescriptor(\.createdAt, order: .reverse)]
        )
        descriptor.fetchLimit = max(1, limit)
        return (try? context.fetch(descriptor)) ?? []
    }

    func delete(askThread: AskThread) throws {
        context.delete(askThread)
        try save()
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

// MARK: - 内置种子牌组

extension CardStore {

    /// 首次启动时把内置的分析文件导入成一幅牌组。
    ///
    /// 为什么需要它：侧载（免费 Apple ID / 通配符描述文件的企业签名）拿不到
    /// App Groups，小组件读不到 App 写的数据，桌面会一直是空的。内置一份种子
    /// 内容让「装完就能看到东西」，而 App 里也必须有同一份，否则会出现
    /// 「桌面上有卡片、App 里空空」这种更让人困惑的状态。
    ///
    /// **幂等**：用 `UserDefaults.standard` 里的 `SharedKeys.seedImported` 打标记，
    /// 只导一次。用户要是把它删了，不该在下次启动时又冒出来。
    ///
    /// - Returns: 真的导入了才返回牌组 ID；已导过、无种子、或种子损坏返回 nil。
    @discardableResult
    func importSeedDeckIfNeeded(bundle: Bundle = .main) -> UUID? {
        let flags = UserDefaults.standard
        guard !flags.bool(forKey: SharedKeys.seedImported) else { return nil }

        // 先打标记，再干活。理由不是「失败就算了」，而是防崩溃循环：
        // 万一导入过程本身把进程带走，下次启动就不会再撞同一堵墙。
        // 可捕获的错误（文件缺失、校验失败）在下面会把标记复位，所以那种
        // 情况仍有重试机会——所以这个提前量只用来兜「崩掉」这一种。
        flags.set(true, forKey: SharedKeys.seedImported)

        // 注意资源名与扩展名的切分：文件名是 bundled-deck.pdfreview.json，
        // 真正的扩展名只有最后一段 "json"。写成 withExtension: "pdfreview.json"
        // 依赖 Foundation 把两段拼在一起，能跑但不该依赖。
        guard let url = bundle.url(forResource: "bundled-deck.pdfreview", withExtension: "json") else {
            LaunchLog.note("种子：bundle 里找不到 bundled-deck.pdfreview.json")
            flags.set(false, forKey: SharedKeys.seedImported)
            return nil
        }

        do {
            // load(from:) 内部已经做过 validate，这里不重复。
            let document = try AnalysisDocument.load(from: url)

            let deckID = try insertDeck(
                title: document.deck.title,
                sourceFileName: document.source.fileName,
                sourceKind: "imported",
                pageCount: document.source.pageCount,
                summary: document.deck.summary,
                language: document.deck.language,
                cards: document.cards
            )
            LaunchLog.note("种子：已导入内置牌组「\(document.deck.title)」，\(document.cards.count) 张卡片")
            return deckID
        } catch {
            // 我们活着走到了这里，说明没崩——复位标记，给下次启动留一条重试的路。
            flags.set(false, forKey: SharedKeys.seedImported)
            LaunchLog.note("种子：导入失败（标记已复位，下次启动会重试）→ \(error.localizedDescription)")
            return nil
        }
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
