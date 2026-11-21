//
//  FavoriteIntent.swift
//  PdfReviewWidget
//
//  小组件「收藏 / 取消收藏」按钮。
//
//  收藏集合写在 App Group UserDefaults 的 "favorites.cardIDs"（[String]），
//  Widget 渲染时用该集合覆盖 CardSnapshot.isFavorite（见 RotationProvider），
//  App 启动时再把集合回灌 SwiftData。Widget 不写 SwiftData。
//

import AppIntents
import Foundation
import WidgetKit

struct ToggleFavoriteIntent: AppIntent {

    static var title: LocalizedStringResource = "收藏"

    /// 不进入系统「快捷指令」列表，只作为小组件按钮使用。
    static var isDiscoverable: Bool { false }

    /// 只改共享的轻量状态，不打开 App。
    static var openAppWhenRun: Bool { false }

    @Parameter(title: "卡片")
    var cardID: String

    init() {}

    init(cardID: String) {
        self.cardID = cardID
    }

    func perform() async throws -> some IntentResult {
        guard let id = UUID(uuidString: cardID) else {
            // 参数不是合法 UUID：不改动任何状态。
            return .result()
        }

        FavoriteStore.toggle(id)
        WidgetCenter.shared.reloadAllTimelines()
        return .result()
    }
}
