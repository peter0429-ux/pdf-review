//
//  PdfReviewApp.swift
//  PdfReview
//
//  App 入口。三件事：建 ModelContainer、注入共享状态、首次启动做一次性维护。
//
//  维护时机很关键：小组件和 App 必须看到同一份轮换状态，所以每次进入前台
//  都要把 SwiftData 重新物化成 App Group 里的 rotation-cache.json，并回填
//  已经过去的槽位到历史记录。否则用户装好小组件几小时后打开 App，历史页
//  会是空的——而小组件明明已经换过好几张卡了。
//

import SwiftUI
import SwiftData
import WidgetKit

@main
struct PdfReviewApp: App {

    /// 全局数据仓库。构造失败时它自己会降级到内存模式并记下 lastError，
    /// 不会抛错把 App 打挂。
    @StateObject private var store = CardStore.shared
    @StateObject private var settings = AppSettings.shared

    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(store)
                .environmentObject(settings)
                .task {
                    // 启动维护只跑一次。失败不阻断界面——用户至少要能看设置页
                    // 去修配置，而不是对着白屏。
                    await performStartupMaintenance()
                }
        }
        .modelContainer(store.container)
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            Task { await performForegroundRefresh() }
        }
    }

    // MARK: - 维护

    /// 启动时：同步收藏状态、回填历史、刷新小组件缓存。
    private func performStartupMaintenance() async {
        do {
            try store.syncFavoritesFromSharedState()
        } catch {
            store.reportError("同步收藏状态失败：\(AppFormat.message(for: error))")
        }

        await performForegroundRefresh()
    }

    /// 进入前台时：把时间推进造成的槽位变化补齐。
    ///
    /// 顺序有讲究——先 `backlogHistory`（按旧缓存推算已经过去的槽位，写进
    /// 历史），再 `refreshRotationCache`（物化新缓存）。反过来会让刚过去的
    /// 那个槽位被新缓存的口径覆盖掉，历史里就少一条。
    private func performForegroundRefresh() async {
        do {
            try store.backlogHistory()
        } catch {
            store.reportError("回填历史失败：\(AppFormat.message(for: error))")
        }

        do {
            try store.refreshRotationCache()
        } catch {
            store.reportError("刷新小组件缓存失败：\(AppFormat.message(for: error))")
        }
    }
}
