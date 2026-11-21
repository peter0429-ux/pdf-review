//
//  AppGroup.swift
//  PdfReview
//
//  App Group 容器的统一入口。App 与 Widget 都从这里取共享路径与 UserDefaults。
//  注意：该文件同时编译进 PdfReview 与 PdfReviewWidget 两个 target。
//
//  ── 侧载安全（重要，别把这些保护删掉）──
//
//  用免费 Apple ID 经 Sideloadly 重签时，provisioning profile 里通常没有
//  App Groups 能力。此时访问共享容器有可能不是抛错，而是被系统直接 SIGKILL：
//  进程秒退、没有崩溃报告、连一行日志都写不出来。那一层是 C 代码的沙箱拒绝，
//  Swift 的 `??` 和 do/catch 都兜不住。
//
//  所以这里用一个「崩溃断路器」：
//    1. 每次真去碰共享容器之前，先在 UserDefaults.standard 里落一个标记
//       （standard 本身永远可用，不依赖 App Groups）
//    2. 探测顺利结束后清掉标记
//    3. 下次启动若发现标记还在，说明上次正是死在这一步 → 永久停用 App Group
//
//  代价是：极端情况下放弃小组件共享，但 App 一定能打开。这个取舍是对的——
//  打不开的 App 没有任何价值。
//

import Foundation

enum AppGroup {

    /// App Group 标识符。若在 Xcode 中改了 Bundle ID，这里必须同步改。
    static let identifier = "group.com.pdfreview.app"

    // MARK: - 侧载断路器

    /// 探测进行中的标记。必须在真正接触共享容器之前写入。
    private static let probeMarkerKey = "appgroup.probeInFlight"
    /// 获取容器路径进行中的标记（独立于上面的写入探测）。
    private static let containerMarkerKey = "appgroup.containerLookupInFlight"
    /// 已判定不可用的标记。写入后本次安装不再尝试 App Group。
    private static let disabledKey = "appgroup.disabled"
    /// 判定为不可用的原因，供设置页展示。
    private static let disableReasonKey = "appgroup.disabledReason"

    /// 本次安装是否已停用 App Group（只用 App 本地存储）。
    static var isDisabled: Bool {
        UserDefaults.standard.bool(forKey: disabledKey)
    }

    /// 停用原因，没有则为 nil。
    static var disableReason: String? {
        UserDefaults.standard.string(forKey: disableReasonKey)
    }

    /// 永久停用 App Group。只在确认 App Group 这条路走不通时调用。
    static func disablePermanently(reason: String) {
        let standard = UserDefaults.standard
        standard.set(true, forKey: disabledKey)
        standard.set(reason, forKey: disableReasonKey)
        standard.set(false, forKey: probeMarkerKey)
    }

    /// 清掉停用标记，下次启动重新尝试（设置页「重试共享容器」用）。
    static func resetAvailabilityForRetry() {
        let standard = UserDefaults.standard
        standard.set(false, forKey: disabledKey)
        standard.set(false, forKey: probeMarkerKey)
        standard.removeObject(forKey: disableReasonKey)
    }

    // MARK: - 路径

    /// 共享容器根目录。App Group 不可用或已停用时返回 App 自己的 Documents，
    /// 以保证 App 侧功能仍可用（此时 Widget 读不到数据，属可接受的降级）。
    ///
    /// 注意 `containerURL(forSecurityApplicationGroupIdentifier:)` 本身在
    /// 缺少 entitlement 的侧载环境下也可能直接把进程带走（不是返回 nil）。
    /// 所以这里同样由断路器保护：先落标记，拿到路径再清。
    static var containerURL: URL {
        let fallback = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)
            .first ?? URL(fileURLWithPath: NSTemporaryDirectory())

        guard !isDisabled else { return fallback }

        let standard = UserDefaults.standard
        if standard.bool(forKey: containerMarkerKey) {
            // 上次就是死在这一句上。
            disablePermanently(reason: "上次启动在获取共享容器路径时异常退出")
            return fallback
        }

        standard.set(true, forKey: containerMarkerKey)
        let resolved = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: identifier
        )
        standard.set(false, forKey: containerMarkerKey)

        return resolved ?? fallback
    }

    /// 轮换缓存文件路径。
    static var cacheFileURL: URL {
        containerURL.appendingPathComponent("rotation-cache.json", isDirectory: false)
    }

    // MARK: - 可用性探测

    /// 共享容器是否可用。
    ///
    /// 不能只判断 `containerURL(...) != nil`：侧载时系统有可能给一个 URL，
    /// 但那个目录不可写。真写一个探测文件才知道能不能用——而且必须做，
    /// 因为拿不可写的容器去建 SwiftData 容器会直接崩，不是抛可 catch 的错误。
    ///
    /// 整个探测被断路器包住：宁可下次启动少一次尝试，也不要再死一次。
    static var isContainerAvailable: Bool {
        if isDisabled { return false }

        let standard = UserDefaults.standard

        // 上次启动正是在这一步没的 → 永久跳过，不再冒险。
        if standard.bool(forKey: probeMarkerKey) {
            disablePermanently(reason: "上次启动在访问共享容器时异常退出")
            return false
        }

        // 先落标记，再去碰共享容器。若这之后进程被杀，标记会留在磁盘上，
        // 下次启动据此判定「这条路不通」。
        standard.set(true, forKey: probeMarkerKey)

        guard let url = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: identifier
        ) else {
            // 没拿到容器 = 没有 App Groups 能力，这是正常情况，不算崩溃。
            standard.set(false, forKey: probeMarkerKey)
            return false
        }

        let probe = url.appendingPathComponent(".probe-\(UUID().uuidString)")
        var writable = false
        do {
            try Data("ok".utf8).write(to: probe, options: .atomic)
            try? FileManager.default.removeItem(at: probe)
            writable = true
        } catch {
            writable = false
        }

        standard.set(false, forKey: probeMarkerKey)
        return writable
    }

    // MARK: - 共享 UserDefaults

    /// 共享 UserDefaults。用于保存轻量状态（手动偏移量、收藏集合等）。
    ///
    /// 必须先用 `isContainerAvailable` 挡一道，不能直接
    /// `UserDefaults(suiteName:) ?? .standard`：传一个不在 entitlements 里的
    /// 组名，系统会在 CFPrefs 层直接抛致命错误把进程杀掉。
    ///
    /// 光探测「容器目录能不能写」还不够——Domain 的注册是另一条路径，
    /// 同样可能在那一步死掉。所以这里用同一个断路器包住「建 Domain + 写一次」
    /// 的全过程：先把标记落盘，写成功再清标记。若这一整个过程把进程带走，
    /// 标记会留在磁盘上，下次启动直接走 `UserDefaults.standard`。
    ///
    /// 用 `static let` 而不是每次现算：`defaults` 在启动路径上被反复读。
    /// `static let` 由 Swift 保证只初始化一次且线程安全。
    static let defaults: UserDefaults = {
        guard isContainerAvailable else { return UserDefaults.standard }

        let standard = UserDefaults.standard
        standard.set(true, forKey: probeMarkerKey)

        guard let suite = UserDefaults(suiteName: identifier) else {
            standard.set(false, forKey: probeMarkerKey)
            return .standard
        }

        // 真写一次再读回。Domain 建不起来的情况下，这一步就是那道坎。
        let probeKey = "appgroup.suiteProbe"
        suite.set("ok", forKey: probeKey)
        let readBack = suite.string(forKey: probeKey)
        suite.removeObject(forKey: probeKey)

        standard.set(false, forKey: probeMarkerKey)

        guard readBack == "ok" else {
            disablePermanently(reason: "共享 UserDefaults 写入后读不回")
            return .standard
        }
        return suite
    }()
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
