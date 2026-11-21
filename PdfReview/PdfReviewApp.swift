//
//  PdfReviewApp.swift
//  PdfReview
//
//  App 入口。这里刻意保持**极薄**：不构造任何单例、不做任何维护。
//
//  为什么（有真机证据，别改回去）：
//  之前把 `CardStore.shared` / `AppSettings.shared` 放在 App 的存储属性里，
//  Swift 会在 `App.init()` 之前就求值它们——那时 SwiftUI 还没起来，真机上
//  进程直接就没了，启动日志一条都写不出来。把同样的构造挪到「首帧之后」
//  （`AppRootView.bootstrap()`），真机就能正常进入界面。
//
//  所以分工是：
//    · 本文件   —— 只交出窗口，一个语句都不多做
//    · AppRootView.swift —— 首帧后建容器、跑维护、渲染 RootView
//
//  另外 `scenePhase` 回到前台时的刷新也放在 AppRootView 里，因为它需要拿到
//  已经构造好的 store。
//

import SwiftUI

@main
struct PdfReviewApp: App {

#if PROBE_MINIMAL
    // ── 诊断模式 ────────────────────────────────────────────────────
    // 编译时加 -DPROBE_MINIMAL 走这一支，按顺序跑 7 个可疑动作并把进度画在
    // 屏幕上，用于真机上定位崩溃点。正常构建不会编到这里。
    var body: some Scene {
        WindowGroup {
            ProbeRootView()
        }
    }

#else

    var body: some Scene {
        WindowGroup {
            AppRootView()
                // 从别的 App「分享 → PDF 复习」送进来的文件走这里。
                // 这条路径不经过任何文件选择器，是选择器出问题时的兜底入口。
                .onOpenURL { url in
                    ImportInbox.shared.receive(url)
                }
        }
    }

#endif
}
