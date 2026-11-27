//
//  ReviewCard.swift
//  PdfReview
//
//  SwiftData 模型：一张复习卡片。
//

import Foundation
import SwiftData

@Model
final class ReviewCard {

    @Attribute(.unique) var id: UUID

    /// 题目（正面）。
    var question: String

    /// 答案（背面）。
    var answer: String

    /// 补充说明，可为空。
    var detail: String?

    /// 标签，最多 8 个。
    var tags: [String]

    /// 来源页码，可为空。
    var sourcePage: Int?

    /// 难度 1...5。
    var difficulty: Int

    /// 重要度 1...5。
    var importance: Int

    /// 是否被收藏。
    var isFavorite: Bool

    var createdAt: Date

    /// 卡片来源："analysis"（导入 PDF 后由 AI 分析产生）、"ask"（用户在提问页问出来、
    /// 又确认值得做成卡片）、"manual"（用户手工新建）。
    ///
    /// 带默认值，SwiftData 走轻量迁移；旧库里已有的卡片解出来就是 "analysis"，
    /// 这正是它们的事实来源，所以不需要额外的迁移代码。
    ///
    /// 刻意**不**进 `CardSnapshot`：小组件只关心「显示什么」，不关心卡片从哪来，
    /// 多带一个字段等于让 Widget 也参与迁移。
    var origin: String = ReviewCard.Origin.analysis

    /// 所属牌组。
    var deck: ReviewDeck?

    /// 展示历史。删除卡片时级联删除。
    @Relationship(deleteRule: .cascade, inverse: \CardDisplayRecord.card)
    var displays: [CardDisplayRecord]

    init(
        id: UUID = UUID(),
        question: String,
        answer: String,
        detail: String? = nil,
        tags: [String] = [],
        sourcePage: Int? = nil,
        difficulty: Int = 3,
        importance: Int = 3,
        isFavorite: Bool = false,
        createdAt: Date = Date(),
        origin: String = ReviewCard.Origin.analysis
    ) {
        self.id = id
        self.question = question
        self.answer = answer
        self.detail = detail
        self.tags = Array(tags.prefix(8))
        self.sourcePage = sourcePage
        self.difficulty = ReviewCard.clampScore(difficulty)
        self.importance = ReviewCard.clampScore(importance)
        self.isFavorite = isFavorite
        self.createdAt = createdAt
        self.origin = origin
        self.displays = []
    }

    /// 把任意整数夹到 1...5。
    static func clampScore(_ value: Int) -> Int {
        min(5, max(1, value))
    }
}

// MARK: - 来源

extension ReviewCard {
    /// 卡片来源的取值。用字符串而不是 enum，是因为 SwiftData 对 String 字段的
    /// 迁移最省事，而 enum 需要额外写 Codable 映射。
    enum Origin {
        static let analysis = "analysis"
        static let ask = "ask"
        static let manual = "manual"

        /// 给界面用的中文说明。未知值一律当「分析」处理，避免旧数据出现空白。
        static func label(for raw: String) -> String {
            switch raw {
            case ask: return "提问"
            case manual: return "手工"
            default: return "分析"
            }
        }
    }

    /// 是否来自提问。界面上用它决定要不要显示角标。
    var isFromAsk: Bool { origin == Origin.ask }
}

// MARK: - 转换

extension ReviewCard {
    /// 转成 Widget 可用的快照。`favoriteOverride` 用于把 App Group 里的收藏状态叠加进来。
    func snapshot(deckTitle: String, favoriteOverride: Bool? = nil) -> CardSnapshot {
        CardSnapshot(
            id: id,
            deckID: deck?.id ?? UUID(),
            deckTitle: deckTitle,
            question: question,
            answer: answer,
            detail: detail,
            tags: tags,
            sourcePage: sourcePage,
            isFavorite: favoriteOverride ?? isFavorite
        )
    }
}
