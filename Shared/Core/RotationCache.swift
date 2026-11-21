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

    /// 从 App Group 容器读取缓存。文件不存在或解码失败时返回 nil。
    static func load() -> RotationCache? {
        let url = AppGroup.cacheFileURL
        guard let data = try? Data(contentsOf: url) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(RotationCache.self, from: data)
    }

    /// 原子写入 App Group 容器。先写临时文件再替换，避免 Widget 读到半个文件。
    func save() throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(self)

        let target = AppGroup.cacheFileURL
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
