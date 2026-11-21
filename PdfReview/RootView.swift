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

    /// 当前标签。默认停在「复习」，符合「打开就看一眼」的用法。
    @State private var selection: RootTab = .review

    /// 导入流程 sheet。
    @State private var showImport = false

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
        .sheet(isPresented: $showImport) {
            ImportView()
        }
        .fullScreenCover(isPresented: $showOnboarding) {
            OnboardingView()
        }
        .task {
            // 只在启动时判断一次。引导页自身会把 hasCompletedOnboarding 置为 true。
            if !settings.hasCompletedOnboarding {
                showOnboarding = true
            }
        }
    }
}
