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
        createdAt: Date = Date()
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
        self.displays = []
    }

    /// 把任意整数夹到 1...5。
    static func clampScore(_ value: Int) -> Int {
        min(5, max(1, value))
    }
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
