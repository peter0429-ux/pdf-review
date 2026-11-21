//
//  AppRootView.swift
//  PdfReview
//
//  App 的启动壳。**关键：所有单例都在这里、在第一帧之后再构造**，
//  不再放在 `PdfReviewApp.init()` 里。
//
//  为什么这样改（有真机证据）：
//  此前完整版把 `CardStore.shared` / `AppSettings.shared` 放在 `App.init()` 里构造，
//  真机一点图标就退出，启动日志一条都没有。把同样两个单例移到「界面出来之后」
//  再构造（诊断版就是这么做的），真机就能正常进入界面了。
//  也就是说，崩溃与**构造时机**有关，而不是与代码本身有关。
//
//  另一件事：`performStartupMaintenance()` 里的三步维护（同步收藏 / 回填历史 /
//  刷新小组件缓存）也一起挪到界面出来之后，并且每一步前后都写 LaunchLog。
//  万一它崩，日志最后一行就是断点位置。
//

import SwiftUI
import SwiftData

/// 启动壳：先显示一个极轻的占位，界面出来后再建数据容器、再跑维护。
struct AppRootView: View {

    /// 三态：nil = 还在启动；.ready = 可以显示主界面；.failed = 连容器都建不起来。
    private enum Phase {
        case booting
        case ready(CardStore, AppSettings)
        case failed(String)
    }

    @State private var phase: Phase = .booting

    /// 首帧启动维护是否已经跑过。用来避免「首次进入前台」被重复当成
    /// 「从后台回来」再刷一遍。
    @State private var didFirstMaintenance = false

    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            switch phase {
            case .booting:
                bootingView

            case let .ready(store, settings):
                RootView()
                    .environmentObject(store)
                    .environmentObject(settings)
                    .modelContainer(store.container)

            case let .failed(message):
                failedView(message)
            }
        }
        .task {
            await bootstrap()
        }
        .onChange(of: scenePhase) { _, newPhase in
            guard newPhase == .active, didFirstMaintenance else { return }
            guard case let .ready(store, _) = phase else { return }
            Task { await performForegroundRefresh(store) }
        }
    }

    // MARK: - 启动流程

    private func bootstrap() async {
        // 第 0 步：最早的一行日志。此时界面已经在屏幕上，写盘一定来得及。
        LaunchLog.note("=== PdfReview 启动 ===")
        LaunchLog.note("版本 \(Bundle.main.shortVersion)（build \(Bundle.main.buildNumber)）")
        LaunchLog.note("系统 \(ProcessInfo.processInfo.operatingSystemVersionString)")
        LaunchLog.note("日志位置 \(LaunchLog.currentFileURL?.path ?? "未知")")
        LaunchLog.note("AppGroup 已停用 = \(AppGroup.isDisabled)")

        // 让系统把占位界面画出来，再开始干重活。
        // 这一步不是装饰：真机上把单例构造放在首帧之后，才躲开了启动崩溃。
        await Task.yield()
        try? await Task.sleep(nanoseconds: 120_000_000)

        // 构造两个单例。顺序不重要，但每个都单独记日志。
        LaunchLog.note("开始构造 CardStore")
        let store = CardStore.shared
        LaunchLog.note("CardStore 构造完成，牌组数 = \(store.allDecks().count)")

        LaunchLog.note("开始构造 AppSettings")
        let settings = AppSettings.shared
        LaunchLog.note("AppSettings 构造完成")

        // 一旦容器建不起来、退到内存模式，这里不会崩，但我希望用户看得见。
        phase = .ready(store, settings)

        // 收起键盘/滚动都可能被首帧打断，让界面先稳定下来。
        try? await Task.sleep(nanoseconds: 150_000_000)

        await performStartupMaintenance(store)
    }

    /// 启动维护。每一步前后都写日志，崩在哪一步一眼可见。
    private func performStartupMaintenance(_ store: CardStore) async {
        LaunchLog.note("维护 1/3：同步收藏状态")
        do {
            try store.syncFavoritesFromSharedState()
            LaunchLog.note("维护 1/3 完成")
        } catch {
            LaunchLog.note("维护 1/3 失败：\(error.localizedDescription)")
            store.reportError("同步收藏状态失败：\(AppFormat.message(for: error))")
        }

        LaunchLog.note("维护 2/3：回填历史")
        do {
            try store.backlogHistory()
            LaunchLog.note("维护 2/3 完成")
        } catch {
            LaunchLog.note("维护 2/3 失败：\(error.localizedDescription)")
            store.reportError("回填历史失败：\(AppFormat.message(for: error))")
        }

        LaunchLog.note("维护 3/3：刷新小组件缓存")
        do {
            try store.refreshRotationCache()
            LaunchLog.note("维护 3/3 完成")
        } catch {
            LaunchLog.note("维护 3/3 失败：\(error.localizedDescription)")
            store.reportError("刷新小组件缓存失败：\(AppFormat.message(for: error))")
        }

        LaunchLog.note("=== 启动维护全部完成 ===")

        didFirstMaintenance = true
    }

    /// 从后台回到前台时：把时间推进造成的槽位变化补齐。
    ///
    /// 顺序有讲究——先 `backlogHistory`（按旧缓存推算已经过去的槽位，写进
    /// 历史），再 `refreshRotationCache`（物化新缓存）。反过来会让刚过去的
    /// 那个槽位被新缓存的口径覆盖掉，历史里就少一条。
    private func performForegroundRefresh(_ store: CardStore) async {
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

    // MARK: - 占位界面

    private var bootingView: some View {
        VStack(spacing: 14) {
            Image(systemName: "doc.text.magnifyingglass")
                .font(.system(size: 44))
                .foregroundStyle(.tint)
            Text("正在准备…")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func failedView(_ message: String) -> some View {
        VStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 40))
                .foregroundStyle(.orange)
            Text("数据存储初始化失败")
                .font(.headline)
            Text(message)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 28)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
