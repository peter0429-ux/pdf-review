//
//  ReviewView.swift
//  PdfReview
//
//  「复习」页：整个 App 的主界面。
//
//  显示的卡片不是从 SwiftData 里随便取的，而是用与小组件完全相同的纯函数算出：
//  RotationCache.load() 读共享缓存 → RotationScheduler.slot(at:cache:) 定位槽位。
//  这样 App 里看到的和桌面小组件上看到的必然是同一张，用户不会困惑。
//
//  倒计时用 Timer 每 30 秒推进一次 now，驱动文案刷新；跨槽位时补一次历史。
//

import SwiftUI
import Combine
import UIKit

struct ReviewView: View {

    @EnvironmentObject private var store: CardStore
    @EnvironmentObject private var settings: AppSettings

    /// 由 RootView 注入：打开导入 sheet。
    let onRequestImport: () -> Void

    /// 共享缓存的只读副本。nil 表示还没物化过（全新安装）。
    @State private var cache: RotationCache?

    /// 计时基准。每 30 秒推进一次，驱动倒计时文本与槽位重算。
    @State private var now = Date()

    /// 当前槽位序号，用来检测跨槽位。
    @State private var lastSlotIndex: Int?

    /// 收藏/前进这类操作的错误，用 alert 展示。
    @State private var actionError: String?

    private let ticker = Timer.publish(every: 30, on: .main, in: .common).autoconnect()

    init(onRequestImport: @escaping () -> Void) {
        self.onRequestImport = onRequestImport
    }

    var body: some View {
        NavigationStack {
            List {
                statusSection

                if let slot = currentSlot {
                    cardSection(slot: slot)
                    upcomingSection
                } else {
                    emptySection
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("复习")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        onRequestImport()
                    } label: {
                        Label("导入", systemImage: "plus")
                    }
                }
            }
            .refreshable {
                reloadCache()
                try? store.backlogHistory()
            }
            .alert("操作失败", isPresented: errorBinding) {
                Button("好") { actionError = nil }
            } message: {
                Text(actionError ?? "")
            }
        }
        .task {
            reloadCache()
        }
        .onReceive(ticker) { date in
            now = date
            reloadCache()
            if let index = currentSlotIndex, index != lastSlotIndex {
                lastSlotIndex = index
                try? store.backlogHistory()
            }
        }
    }

    // MARK: 顶部状态

    @ViewBuilder
    private var statusSection: some View {
        Section {
            if let cache, !cache.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(alignment: .firstTextBaseline) {
                        Text("当前轮换")
                            .font(.subheadline.weight(.semibold))
                        Spacer()
                        Text("每 \(AppFormat.intervalText(cache.intervalHours)) 一轮")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    Text(AppFormat.remainingText(
                        RotationScheduler.secondsRemaining(at: now, cache: cache)
                    ))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()

                    Button {
                        goToNextCard()
                    } label: {
                        Label("下一张", systemImage: "forward.fill")
                            .font(.subheadline.weight(.semibold))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 9)
                    }
                    .buttonStyle(.borderedProminent)
                    .buttonBorderShape(.roundedRectangle(radius: 10))
                }
                .padding(.vertical, 4)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    Text("还没有卡片")
                        .font(.subheadline.weight(.semibold))
                    Text("导入一份 PDF，让 AI 帮你提炼成能随手看两眼的卡片。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.vertical, 4)
            }
        }
    }

    // MARK: 当前卡片

    @ViewBuilder
    private func cardSection(slot: RotationSlot) -> some View {
        Section {
            ForEach(slot.cards) { snapshot in
                VStack(alignment: .leading, spacing: 10) {
                    CardFaceView(
                        question: snapshot.question,
                        answer: snapshot.answer,
                        detail: snapshot.detail,
                        tags: snapshot.tags,
                        sourcePage: snapshot.sourcePage,
                        header: snapshot.deckTitle
                    )

                    HStack(spacing: 16) {
                        Button {
                            toggleFavorite(snapshot: snapshot)
                        } label: {
                            Label(
                                isFavorite(snapshot: snapshot) ? "已收藏" : "收藏",
                                systemImage: isFavorite(snapshot: snapshot) ? "star.fill" : "star"
                            )
                            .font(.footnote)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(isFavorite(snapshot: snapshot) ? Color.yellow : Color.accentColor)

                        Spacer()

                        Text("第 \(slot.index) 轮")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .monospacedDigit()
                    }
                    .padding(.horizontal, 4)
                }
                .listRowInsets(EdgeInsets(top: 10, leading: 12, bottom: 10, trailing: 12))
                .listRowSeparator(.hidden)
            }
        } header: {
            Text("现在看的")
        } footer: {
            Text("点卡片任意位置翻转答案。")
        }
    }

    // MARK: 接下来

    @ViewBuilder
    private var upcomingSection: some View {
        if let cache, !cache.isEmpty {
            let upcoming = RotationScheduler.upcoming(at: now, count: 3, cache: cache)
            if upcoming.count > 1 {
                Section("接下来") {
                    // 第 0 个就是当前槽位，跳过它。
                    ForEach(Array(upcoming.dropFirst().enumerated()), id: \.offset) { item in
                        HStack(alignment: .top, spacing: 10) {
                            Text(AppFormat.clock(item.element.start))
                                .font(.caption)
                                .monospacedDigit()
                                .foregroundStyle(.secondary)
                                .frame(width: 46, alignment: .leading)

                            Text(item.element.cards.first?.question ?? "")
                                .font(.footnote)
                                .foregroundStyle(.primary)
                                .lineLimit(2)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .padding(.vertical, 2)
                    }
                }
            }
        }
    }

    // MARK: 空态

    @ViewBuilder
    private var emptySection: some View {
        Section {
            ContentUnavailableView {
                Label("还没有牌组", systemImage: "tray")
            } description: {
                Text("导入 PDF 让 AI 生成卡片，或直接导入已经分析好的 .pdfreview.json 文件。")
            } actions: {
                Button("开始导入") {
                    onRequestImport()
                }
                .buttonStyle(.borderedProminent)
            }
            .listRowInsets(EdgeInsets(top: 20, leading: 12, bottom: 20, trailing: 12))
        }
    }

    // MARK: 数据

    /// 当前应展示的槽位。
    private var currentSlot: RotationSlot? {
        guard let cache else { return nil }
        return RotationScheduler.slot(at: now, cache: cache)
    }

    private var currentSlotIndex: Int? {
        guard let cache, !cache.isEmpty else { return nil }
        return RotationScheduler.slotIndex(at: now, cache: cache)
    }

    private func reloadCache() {
        cache = RotationCache.load()
    }

    /// 收藏状态以 SwiftData 为准（快照里的可能略旧）。
    private func isFavorite(snapshot: CardSnapshot) -> Bool {
        if let card = store.card(withID: snapshot.id) {
            return card.isFavorite
        }
        return snapshot.isFavorite
    }

    private func toggleFavorite(snapshot: CardSnapshot) {
        guard let card = store.card(withID: snapshot.id) else {
            actionError = "这张卡已经不在库里了，可能所属牌组刚被删除。"
            return
        }
        do {
            try store.toggleFavorite(card: card)
            reloadCache()
        } catch {
            actionError = AppFormat.message(for: error)
        }
    }

    private func goToNextCard() {
        do {
            try store.advanceToNextCard()
            now = Date()
            reloadCache()
            lastSlotIndex = currentSlotIndex
        } catch {
            actionError = AppFormat.message(for: error)
        }
    }

    private var errorBinding: Binding<Bool> {
        Binding(
            get: { actionError != nil },
            set: { newValue in if !newValue { actionError = nil } }
        )
    }
}
