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

#if PROBE_MINIMAL
    // ── 诊断用最小模式 ──────────────────────────────────────────────
    // 编译时加 -DPROBE_MINIMAL 会走这一支：完全没有 SwiftData 容器、
    // 没有 App Group、没有启动维护、没有业务视图，只有一个 Text。
    //
    // 它的唯一用途是把问题切开：
    //   · 若最小版能打开 → 问题在我们自己的初始化代码里
    //   · 若最小版也打不开 → 问题在签名/安装环节，跟代码无关
    //
    // 之所以要这个开关：真机「一点就闪退」且启动日志空白，说明进程在
    // 执行任何一行代码之前就被终止了。继续在完整版上猜没有意义。
    var body: some Scene {
        WindowGroup {
            VStack(spacing: 12) {
                Text("PDF 复习")
                    .font(.title2)
                Text("最小诊断模式")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
    }

#else

    /// 全局数据仓库。构造失败时它自己会降级到内存模式并记下 lastError，
    /// 不会抛错把 App 打挂。
    ///
    /// 注意这两个属性**不能**写成 `= CardStore.shared` 的默认值形式。
    /// Swift 会在进入 init() 函数体之前先求值存储属性的默认值，那样
    /// CardStore 就会在下面任何一行日志之前被构造出来——一旦它崩了，
    /// 启动日志会是空的，看上去像「什么都没发生」，无法诊断。
    /// 所以改成「无默认值 + 在 init() 里显式赋值」，把日志抢在前面。
    @StateObject private var store: CardStore
    @StateObject private var settings: AppSettings

    @Environment(\.scenePhase) private var scenePhase

    init() {
        // 最早的一行日志，必须发生在任何可能失败的构造之前。
        LaunchLog.note("=== PdfReview 启动 ===")
        LaunchLog.note("版本 \(Bundle.main.shortVersion)（build \(Bundle.main.buildNumber)）")
        LaunchLog.note("系统 \(ProcessInfo.processInfo.operatingSystemVersionString)")
        LaunchLog.note("日志位置 \(LaunchLog.currentFileURL?.path ?? "未知")")
        LaunchLog.note("AppGroup 已停用 = \(AppGroup.isDisabled)")

        _store = StateObject(wrappedValue: CardStore.shared)
        _settings = StateObject(wrappedValue: AppSettings.shared)

        // CardStore 里会再写一行「容器：…」，据此判断走到了哪一级降级。
        LaunchLog.note("=== 初始化完成 ===")
    }

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

#endif
}
