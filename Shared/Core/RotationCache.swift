//
//  RotationCache.swift
//  PdfReview
//
//  App 与 Widget 之间唯一的共享读模型。
//  App 是唯一写者；Widget 只读。见 docs/architecture.md 第 3.1 节。
//

import Foundation

// MARK: - 快照类型

/// 牌组的轻量快照。只保留 Widget 渲染需要的字段。
struct DeckSnapshot: Codable, Identifiable, Hashable {
    var id: UUID
    var title: String
    var cardCount: Int

    init(id: UUID, title: String, cardCount: Int) {
        self.id = id
        self.title = title
        self.cardCount = cardCount
    }
}

/// 卡片的轻量快照。只保留 Widget 渲染需要的字段。
struct CardSnapshot: Codable, Identifiable, Hashable {
    var id: UUID
    var deckID: UUID
    var deckTitle: String
    var question: String
    var answer: String
    var detail: String?
    var tags: [String]
    var sourcePage: Int?
    var isFavorite: Bool

    init(
        id: UUID,
        deckID: UUID,
        deckTitle: String,
        question: String,
        answer: String,
        detail: String? = nil,
        tags: [String] = [],
        sourcePage: Int? = nil,
        isFavorite: Bool = false
    ) {
        self.id = id
        self.deckID = deckID
        self.deckTitle = deckTitle
        self.question = question
        self.answer = answer
        self.detail = detail
        self.tags = tags
        self.sourcePage = sourcePage
        self.isFavorite = isFavorite
    }
}

// MARK: - 缓存

/// 轮换缓存。写入 App Group 容器的 `rotation-cache.json`。
/// 字段只增不改；改语义必须升 `version`。
struct RotationCache: Codable {

    /// 当前结构版本。
    static let currentVersion = 1

    var version: Int
    var generatedAt: Date
    /// 轮换周期锚点。首次启用时确定，之后不变。
    var epoch: Date
    var intervalHours: Double
    var cardsPerSlot: Int
    /// 确定性洗牌的盐。卡片池变化时更换，从而全量重排。
    var orderSalt: String
    var manualOffset: Int
    var decks: [DeckSnapshot]
    var cards: [CardSnapshot]

    /// 卡片池签名（卡片 ID + 题面的哈希）。用于判断是否需要重新洗牌。
    /// 只增字段，旧缓存缺这个字段时解码为 nil，视为「需要重排」。
    var signature: String?

    init(
        version: Int = RotationCache.currentVersion,
        generatedAt: Date = Date(),
        epoch: Date = Date(),
        intervalHours: Double = 3,
        cardsPerSlot: Int = 1,
        orderSalt: String = UUID().uuidString,
        manualOffset: Int = 0,
        decks: [DeckSnapshot] = [],
        cards: [CardSnapshot] = [],
        signature: String? = nil
    ) {
        self.version = version
        self.generatedAt = generatedAt
        self.epoch = epoch
        self.intervalHours = intervalHours
        self.cardsPerSlot = cardsPerSlot
        self.orderSalt = orderSalt
        self.manualOffset = manualOffset
        self.decks = decks
        self.cards = cards
        self.signature = signature
    }

    /// 空缓存。Widget 在 App 尚未写入时用它渲染引导态。
    static func empty() -> RotationCache {
        RotationCache(epoch: Date(), intervalHours: 3, cardsPerSlot: 1)
    }

    // MARK: 读写

    /// 从缓存位置读取。文件不存在或解码失败时返回 nil。
    ///
    /// 「缓存位置」在 App 进程里是 App Group 容器；在 Widget 进程里，
    /// 当 App Groups 不可用时是 Widget 自己的 Documents——这是刻意的，
    /// 见 `seedOwnContainerIfNeeded()` 的说明。
    static func load() -> RotationCache? {
        load(from: AppGroup.cacheFileURL)
    }

    /// 从指定文件读取。解码失败返回 nil，不抛错——Widget 侧拿不到数据
    /// 只能退化为空态，崩掉整个 timeline 更糟。
    static func load(from url: URL) -> RotationCache? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(RotationCache.self, from: data)
    }

    // MARK: 内置种子
    //
    // 背景：App Group 需要 provisioning profile 里登记，企业签名/免费账号
    // 往往拿不到。此时 App 写进自己 Documents 的缓存，Widget 在物理上读不到
    // （不同沙盒）。唯一能让 Widget 一装上就有内容的办法，是把一份数据打进
    // Widget 自己的 bundle 资源里，由它复制到自己的沙盒后再读。

    /// 内置种子文件名。`PdfReviewWidget/Resources/rotation-cache.json`。
    static let bundledSeedName = "rotation-cache"

    /// 从**当前进程**的 bundle 读内置种子。
    ///
    /// 编进两个 target，但只有 Widget 的资源里放了这份文件；App 侧调用
    /// 会返回 nil（Bundle.main 里没有同名资源），不影响 App。
    static func loadBundled(bundle: Bundle = .main) -> RotationCache? {
        guard let url = bundle.url(forResource: bundledSeedName, withExtension: "json") else {
            return nil
        }
        return load(from: url)
    }

    /// 把内置种子复制到当前进程的缓存位置（那里已有文件则不动）。
    ///
    /// 为什么必须复制而不是每次直接读 bundle 资源：
    /// `NextCardIntent`（点「下一张」）和 `ToggleFavoriteIntent`（收藏）都要
    /// **写**缓存。bundle 是只读的，读到的种子若不落地成可写文件，
    /// 这两个交互按下就会失败。复制一次之后，Widget 在自己的沙盒里
    /// 就有一份可读可写的副本。
    ///
    /// - Returns: 是否真的写入了（`false` 表示已有文件、跳过，或资源缺失）。
    @discardableResult
    static func seedOwnContainerIfNeeded(bundle: Bundle = .main) -> Bool {
        let target = AppGroup.cacheFileURL
        if FileManager.default.fileExists(atPath: target.path) { return false }
        guard let seed = loadBundled(bundle: bundle) else { return false }
        do {
            try seed.write(to: target)
            return true
        } catch {
            return false
        }
    }

    /// 三级降级读取：缓存 → 落地后的种子副本 → 内置种子（内存）。
    ///
    /// 小组件进程专用。App 进程里这三级其实是同一处（或前两级），
    /// 用 `load()` 就够；Widget 才需要这套兜底。
    ///
    /// 最后一级返回的是**内存里的种子**：写盘失败时（只读文件系统等），
    /// 至少这次还能渲染出内容，代价只是「下一张」写不进磁盘。
    static func loadResolved(bundle: Bundle = .main) -> RotationCache? {
        resolve(bundle: bundle).cache
    }

    /// 与 `loadResolved` 相同，但额外告诉调用方数据是**从哪一级**来的。
    /// 空态文案要据此区分「还没导入过」与「签名缺 App Groups」。
    static func resolve(bundle: Bundle = .main) -> (cache: RotationCache?, isSeeded: Bool) {
        if let cache = load(), !cache.cards.isEmpty {
            return (cache, false)
        }
        if seedOwnContainerIfNeeded(bundle: bundle),
           let seeded = load(), !seeded.cards.isEmpty {
            return (seeded, true)
        }
        if let seed = loadBundled(bundle: bundle), !seed.cards.isEmpty {
            return (seed, true)
        }
        return (nil, false)
    }

    /// 原子写入缓存位置。先写临时文件再替换，避免 Widget 读到半个文件。
    func save() throws {
        try write(to: AppGroup.cacheFileURL)
    }

    /// 原子写入指定路径。
    func write(to target: URL) throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(self)

        let directory = target.deletingLastPathComponent()
        try FileManager.default.createDirectory(
            at: directory, withIntermediateDirectories: true
        )

        let temporary = directory.appendingPathComponent(
            "rotation-cache.\(UUID().uuidString).tmp"
        )
        try data.write(to: temporary, options: .atomic)

        if FileManager.default.fileExists(atPath: target.path) {
            _ = try FileManager.default.replaceItemAt(target, withItemAt: temporary)
        } else {
            try FileManager.default.moveItem(at: temporary, to: target)
        }
    }

    // MARK: 派生信息

    /// 卡片池是否为空。
    var isEmpty: Bool { cards.isEmpty }

    /// 按 ID 快速查找。
    func card(withID id: UUID) -> CardSnapshot? {
        cards.first { $0.id == id }
    }
}

// MARK: - 日历无关的支持

extension RotationCache {
    /// 由 App 写入时使用：把当前设置固化进缓存，供 Widget 读取。
    mutating func applySettings(intervalHours: Double, cardsPerSlot: Int) {
        let clampedInterval = max(0.25, min(24, intervalHours))
        let clampedCount = max(1, min(10, cardsPerSlot))
        self.intervalHours = clampedInterval
        self.cardsPerSlot = clampedCount
    }
}
