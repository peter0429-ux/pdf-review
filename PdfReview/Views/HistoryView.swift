//
//  HistoryView.swift
//  PdfReview
//
//  「历史」页：按天列出最近被展示过的卡片。
//
//  数据来自 CardStore.history(limit:)，返回 (卡片, 展示时刻, 槽位号)。
//  展示时刻是「那一轮开始的时间」，不是用户真正看到它的时间——
//  App 和小组件共用同一套推算，所以这个时间对两边都成立。
//

import SwiftUI

struct HistoryView: View {

    @EnvironmentObject private var store: CardStore

    /// 单次读取多少条。够看且不会拖慢列表。
    @State private var limit = 200

    /// 局部刷新触发器。
    @State private var refreshToken = 0

    var body: some View {
        NavigationStack {
            List {
                if records.isEmpty {
                    emptySection
                } else {
                    statsSection
                    ForEach(groups, id: \.day) { group in
                        Section(AppFormat.dayTitle(group.day)) {
                            ForEach(group.items, id: \.id) { item in
                                row(item)
                            }
                        }
                    }

                    if records.count >= limit {
                        Section {
                            Button("显示更多") {
                                limit += 200
                            }
                        }
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("历史")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        refreshToken &+= 1
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("刷新")
                }
            }
            .refreshable {
                try? store.backlogHistory()
                refreshToken &+= 1
            }
        }
    }

    // MARK: 统计

    @ViewBuilder
    private var statsSection: some View {
        Section {
            HStack(spacing: 8) {
                StatTile(title: "累计展示", value: "\(records.count)", unit: "次")
                StatTile(title: "不同卡片", value: "\(distinctCardCount)", unit: "张")
            }
            .listRowInsets(EdgeInsets(top: 8, leading: 12, bottom: 8, trailing: 12))
            .listRowBackground(Color.clear)

            if let last = records.first {
                LabeledContent("最近一次轮换") {
                    Text(AppFormat.full(last.shownAt))
                }
            }
        } header: {
            Text("概览")
        }
    }

    private var distinctCardCount: Int {
        Set(records.map { $0.card.id }).count
    }

    // MARK: 行

    private func row(_ item: HistoryEntry) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .top, spacing: 8) {
                Text(item.card.question)
                    .font(.subheadline.weight(.medium))
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)

                if item.card.isFavorite {
                    Image(systemName: "star.fill")
                        .font(.caption2)
                        .foregroundStyle(.yellow)
                }
            }

            HStack(spacing: 8) {
                Text(AppFormat.clock(item.shownAt))
                    .monospacedDigit()
                Text("·")
                Text(item.card.deck?.title ?? "未知牌组")
                    .lineLimit(1)
                if item.card.deck == nil {
                    Text("（已删除）")
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            Text("第 \(item.slotIndex) 轮")
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .monospacedDigit()
        }
        .padding(.vertical, 3)
    }

    // MARK: 空态

    @ViewBuilder
    private var emptySection: some View {
        Section {
            ContentUnavailableView {
                Label("还没有展示记录", systemImage: "clock.badge.questionmark")
            } description: {
                Text("把「PDF 复习」小组件放到桌面，或者在这里点「下一张」，之后就能看到历史。")
            }
            .listRowInsets(EdgeInsets(top: 20, leading: 12, bottom: 20, trailing: 12))
        }
    }

    // MARK: 数据

    /// 一条历史记录。用卡片 ID + 时刻做稳定标识。
    private struct HistoryEntry: Identifiable {
        let id: String
        let card: ReviewCard
        let shownAt: Date
        let slotIndex: Int
    }

    private struct DayGroup {
        let day: Date
        let items: [HistoryEntry]
    }

    /// 读一次数据。`refreshToken` 让它随刷新重算。
    private var records: [HistoryEntry] {
        _ = refreshToken
        return store.history(limit: limit).map { tuple in
            HistoryEntry(
                id: "\(tuple.card.id.uuidString)-\(tuple.shownAt.timeIntervalSince1970)-\(tuple.slotIndex)",
                card: tuple.card,
                shownAt: tuple.shownAt,
                slotIndex: tuple.slotIndex
            )
        }
    }

    /// 按「当天零点」分组，组内保持已有的倒序，组间也按时间倒序。
    private var groups: [DayGroup] {
        var buckets: [Date: [HistoryEntry]] = [:]
        for entry in records {
            let day = AppFormat.dayStart(entry.shownAt)
            buckets[day, default: []].append(entry)
        }
        return buckets
            .sorted { $0.key > $1.key }
            .map { DayGroup(day: $0.key, items: $0.value) }
    }
}
