//
//  CardDisplayRecord.swift
//  PdfReview
//
//  SwiftData 模型：一次「卡片被展示」的记录，用于历史回顾。
//  由 App 在启动/前台时按轮换规则回填，见 CardStore.backlogHistory(upTo:)。
//

import Foundation
import SwiftData

@Model
final class CardDisplayRecord {

    @Attribute(.unique) var id: UUID

    /// 展示时刻。
    var shownAt: Date

    /// 该次展示对应的轮换槽位序号。
    var slotIndex: Int

    /// 展示场景："widget" 或 "app"。
    var surface: String

    /// 被展示的卡片。
    var card: ReviewCard?

    init(
        id: UUID = UUID(),
        shownAt: Date,
        slotIndex: Int,
        surface: String = "widget",
        card: ReviewCard? = nil
    ) {
        self.id = id
        self.shownAt = shownAt
        self.slotIndex = slotIndex
        self.surface = surface
        self.card = card
    }
}

// MARK: - 常量

extension CardDisplayRecord {
    enum Surface {
        static let widget = "widget"
        static let app = "app"
    }
}
