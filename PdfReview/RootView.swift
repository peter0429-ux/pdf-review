//
//  RootView.swift
//  PdfReview
//
//  根视图：四个标签页（复习 / 牌组 / 历史 / 设置），外加两个全局出入口：
//   - 导入流程以 sheet 呈现，由「复习」「牌组」两页的按钮触发
//   - 首次启动的引导页以 fullScreenCover 呈现
//
//  启动维护（收藏回灌、历史回填、缓存物化）在 PdfReviewApp 里已经做过一次，
//  这里不重复，只负责「首次启动要不要看引导」这一件界面相关的事。
//

import SwiftUI

struct RootView: View {

    @EnvironmentObject private var store: CardStore
    @EnvironmentObject private var settings: AppSettings

    /// 收件箱：从别的 App 分享进来的文件。
    @ObservedObject private var inbox = ImportInbox.shared

    /// 当前标签。默认停在「复习」，符合「打开就看一眼」的用法。
    @State private var selection: RootTab = .review

    /// 导入流程 sheet。
    @State private var showImport = false

    /// 从分享送进来的文件。有值时直接跳到导入面板的对应阶段。
    @State private var incoming: ImportInbox.Pending?

    /// 首次引导。
    @State private var showOnboarding = false

    enum RootTab: Hashable {
        case review
        case decks
        case history
        case settings
    }

    var body: some View {
        TabView(selection: $selection) {
            ReviewView(onRequestImport: { showImport = true })
                .tabItem {
                    Label("复习", systemImage: "rectangle.on.rectangle.angled")
                }
                .tag(RootTab.review)

            DeckListView(onRequestImport: { showImport = true })
                .tabItem {
                    Label("牌组", systemImage: "square.stack.3d.up")
                }
                .tag(RootTab.decks)

            HistoryView()
                .tabItem {
                    Label("历史", systemImage: "clock.arrow.circlepath")
                }
                .tag(RootTab.history)

            SettingsView()
                .tabItem {
                    Label("设置", systemImage: "gearshape")
                }
                .tag(RootTab.settings)
        }
        .tint(.accentColor)
        .sheet(isPresented: $showImport, onDismiss: handleInboxAfterDismiss) {
            ImportView()
        }
        .sheet(item: $incoming, onDismiss: handleInboxAfterDismiss) { pending in
            ImportView(prefilled: pending)
        }
        .fullScreenCover(isPresented: $showOnboarding) {
            OnboardingView()
        }
        .onChange(of: inbox.pending) { _, newValue in
            // 只有没在导入时才自动弹出，避免打断用户正在做的事。
            guard newValue != nil, !showImport, incoming == nil else { return }
            incoming = inbox.take()
        }
        .task {
            // 只在启动时判断一次。引导页自身会把 hasCompletedOnboarding 置为 true。
            if !settings.hasCompletedOnboarding {
                showOnboarding = true
            }
            // App 是被「分享到本 App」冷启动起来的：onOpenURL 在界面出现之前
            // 就送到了收件箱，onChange 可能错过这次变化，这里主动取一次。
            if inbox.pending != nil, incoming == nil {
                incoming = inbox.take()
            }
        }
    }

    /// 面板收起后，如果收件箱又攒了新文件（用户连着分享两份），继续弹。
    private func handleInboxAfterDismiss() {
        guard incoming == nil, inbox.pending != nil else { return }
        // 让 sheet 的收起动画先走完，否则新面板可能被系统忽略。
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
            guard incoming == nil, inbox.pending != nil else { return }
            incoming = inbox.take()
        }
    }
}
