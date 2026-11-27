//
//  ReviewDeck.swift
//  PdfReview
//
//  SwiftData 模型：一个牌组对应一份 PDF（或一次导入）。
//  注意：此文件只编译进 App target，Widget 不链接 SwiftData。
//

import Foundation
import SwiftData

@Model
final class ReviewDeck {

    /// 稳定标识。SwiftData 自带 persistentModelID，但那是存储层概念，
    /// 导出/导入与 App Group 共享需要一个跨设备稳定的 UUID。
    @Attribute(.unique) var id: UUID

    var title: String

    /// 源文件名。导入 PDF 时记录，手工导入时为 nil。
    var sourceFileName: String?

    /// 来源类型："pdf" 或 "imported"。
    var sourceKind: String

    /// PDF 页数（未知时为 0）。
    var pageCount: Int

    /// 牌组摘要（AI 生成或来自格式文件）。
    var summary: String?

    /// 语言标记，如 "zh-Hans"。
    var language: String?

    /// PDF 原文（切块之前的完整文本），提问时作为 AI 的上下文。
    ///
    /// 只存前 `ReviewDeck.sourceTextLimit` 个字：完整原文动辄几万字，
    /// 存下来会让库膨胀，而 AI 回答单次提问也用不到那么多。
    /// 为 nil 表示这份牌组没有可用的原文（手工导入的格式文件、或旧数据）。
    var sourceText: String?

    var createdAt: Date
    var updatedAt: Date
    var isArchived: Bool

    /// 删除牌组时级联删除其卡片。
    @Relationship(deleteRule: .cascade, inverse: \ReviewCard.deck)
    var cards: [ReviewCard]

    init(
        id: UUID = UUID(),
        title: String,
        sourceFileName: String? = nil,
        sourceKind: String = "pdf",
        pageCount: Int = 0,
        summary: String? = nil,
        language: String? = nil,
        sourceText: String? = nil,
        createdAt: Date = Date(),
        updatedAt: Date = Date(),
        isArchived: Bool = false
    ) {
        self.id = id
        self.title = title
        self.sourceFileName = sourceFileName
        self.sourceKind = sourceKind
        self.pageCount = pageCount
        self.summary = summary
        self.language = language
        self.sourceText = sourceText
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.isArchived = isArchived
        self.cards = []
    }
}

// MARK: - 便捷访问

extension ReviewDeck {
    /// 原文最多保留多少字。约 12 万字节，单牌组可接受；
    /// 也给 AI 留了足够上下文（远超一次问答实际需要）。
    static let sourceTextLimit = 40_000

    /// 按创建时间排序的卡片。
    var sortedCards: [ReviewCard] {
        cards.sorted { $0.createdAt < $1.createdAt }
    }

    /// 未归档的牌组（用于构建轮换池）。
    var isRotatable: Bool { !isArchived && !cards.isEmpty }

    /// 是否有可用于问答的原文。
    var hasSourceText: Bool {
        guard let sourceText else { return false }
        return !sourceText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// 截断到上限。导入时调用，避免把整份原文塞进库里。
    static func clippedSourceText(_ text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if trimmed.count <= sourceTextLimit { return trimmed }
        return String(trimmed.prefix(sourceTextLimit))
    }
}
