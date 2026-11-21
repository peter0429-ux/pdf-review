//
//  AppGroup.swift
//  PdfReview
//
//  App Group 容器的统一入口。App 与 Widget 都从这里取共享路径与 UserDefaults。
//  注意：该文件同时编译进 PdfReview 与 PdfReviewWidget 两个 target。
//

import Foundation

enum AppGroup {

    /// App Group 标识符。若在 Xcode 中改了 Bundle ID，这里必须同步改。
    static let identifier = "group.com.pdfreview.app"

    /// 共享容器根目录。容器不可用时降级到 App 的 Documents 目录，
    /// 以保证 App 侧功能仍可用（此时 Widget 读不到数据，属可接受的降级）。
    static var containerURL: URL {
        if let url = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: identifier
        ) {
            return url
        }
        let fallback = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)
            .first ?? URL(fileURLWithPath: NSTemporaryDirectory())
        return fallback
    }

    /// 共享 UserDefaults。用于保存轻量状态（手动偏移量、收藏集合等）。
    /// 容器不可用时同样降级到 standard，避免崩溃。
    static var defaults: UserDefaults {
        UserDefaults(suiteName: identifier) ?? .standard
    }

    /// 轮换缓存文件路径。
    static var cacheFileURL: URL {
        containerURL.appendingPathComponent("rotation-cache.json", isDirectory: false)
    }

    /// 共享容器是否可用（用于在设置页给出提示）。
    static var isContainerAvailable: Bool {
        FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: identifier
        ) != nil
    }
}

// MARK: - 共享键名

/// App Group 中使用的键名，集中管理，避免散落的字符串字面量。
enum SharedKeys {
    /// 手动偏移量（点「下一张」时递增）。类型：Int
    static let manualOffset = "rotation.manualOffset"
    /// 收藏的卡片 ID 集合。类型：[String]（UUID 的 uuidString）
    static let favoriteCardIDs = "favorites.cardIDs"
    /// 最近一次 App 侧刷新缓存的时间，用于诊断。类型：Double（timeIntervalSince1970）
    static let lastCacheRefresh = "rotation.lastRefresh"
}
