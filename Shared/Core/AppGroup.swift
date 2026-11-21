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
    ///
    /// 这里必须先用 `isContainerAvailable` 挡一道，不能直接
    /// `UserDefaults(suiteName:) ?? .standard`。原因：侧载（免费 Apple ID
    /// 重签）时 App 没有 App Groups 能力，而 `UserDefaults(suiteName:)`
    /// 传一个不在 entitlements 里的组名，系统会在 CFPrefs 层直接抛出
    /// 致命错误把进程杀掉——那一层是 C 代码，Swift 的 `??` 兜不住，
    /// 表现就是「一打开就闪退」，且不是崩溃报告里那种可读的 Swift 异常。
    ///
    /// 用 `static let` 而不是每次现算：`defaults` 在启动路径上被反复读，
    /// 而且 `isContainerAvailable` 会真写一个探测文件。`static let` 由
    /// Swift 保证只初始化一次且线程安全，顺带避开可变全局状态。
    static let defaults: UserDefaults = {
        guard isContainerAvailable else { return UserDefaults.standard }
        return UserDefaults(suiteName: identifier) ?? .standard
    }()

    /// 轮换缓存文件路径。
    static var cacheFileURL: URL {
        containerURL.appendingPathComponent("rotation-cache.json", isDirectory: false)
    }

    /// 共享容器是否可用（用于在设置页给出提示，也用于决定要不要建
    /// groupContainer 的 ModelContainer）。
    ///
    /// 不能只判断 `containerURL(...) != nil`：用免费 Apple ID 侧载时
    /// provisioning profile 里没有 App Groups 能力，系统有可能给出一个
    /// URL，但那个目录不可写。真正写一个探测文件才知道能不能用——
    /// 这一步必须做，因为拿不可写的容器去建 SwiftData 容器会直接崩，
    /// 而不是抛个能 catch 的错误。
    static var isContainerAvailable: Bool {
        guard let url = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: identifier
        ) else {
            return false
        }
        let probe = url.appendingPathComponent(".probe-\(UUID().uuidString)")
        do {
            try Data("ok".utf8).write(to: probe, options: .atomic)
            try? FileManager.default.removeItem(at: probe)
            return true
        } catch {
            return false
        }
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
