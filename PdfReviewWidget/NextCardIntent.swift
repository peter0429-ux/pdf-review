//
//  NextCardIntent.swift
//  PdfReviewWidget
//
//  小组件「下一张」按钮。
//
//  只写 App Group 的轻量状态（UserDefaults + rotation-cache.json），
//  绝不碰 SwiftData（见 docs/architecture.md 第 5 节）。
//

import AppIntents
import Foundation
import WidgetKit

struct NextCardIntent: AppIntent {

    static var title: LocalizedStringResource = "下一张"

    /// 不进入系统「快捷指令」列表，只作为小组件按钮使用。
    static var isDiscoverable: Bool { false }

    /// 改变轮换状态，执行前不打开 App。
    static var openAppWhenRun: Bool { false }

    func perform() async throws -> some IntentResult {
        // cache 可能是首次加载或已被清空：此时无可前进的内容，只刷新一次。
        if let cache = RotationCache.load(), !cache.cards.isEmpty {
            // 偏移量的真相源是 App Group defaults（App 侧 advanceToNextCard()
            // 也是先读 defaults 再 +1），cache 只是它的镜像。
            // 但 defaults 里可能根本没有这个键（用户从未点过「下一张」，
            // 或 App 从未写过），此时 `integer(forKey:)` 会返回 0。
            // 直接拿它当基数会把 cache 里已有的偏移量重置成 1，所以要显式区分。
            let base: Int
            if AppGroup.defaults.object(forKey: SharedKeys.manualOffset) != nil {
                base = AppGroup.defaults.integer(forKey: SharedKeys.manualOffset)
            } else {
                base = cache.manualOffset
            }
            let next = base + 1

            AppGroup.defaults.set(next, forKey: SharedKeys.manualOffset)

            var updated = cache
            updated.manualOffset = next
            updated.generatedAt = Date()

            do {
                try updated.save()
            } catch {
                // 写盘失败时回滚 defaults，避免两处状态不一致。
                AppGroup.defaults.set(cache.manualOffset, forKey: SharedKeys.manualOffset)
            }
        }

        WidgetCenter.shared.reloadAllTimelines()
        return .result()
    }
}
