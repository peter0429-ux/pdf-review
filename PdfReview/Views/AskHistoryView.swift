//
//  AskHistoryView.swift
//  PdfReview
//
//  提问历史：翻回来看问过什么、AI 答了什么、有没有存成卡片。
//
//  为什么值得存：用户问一个问题，AI 答得很好，但当时没想存卡片 ——
//  事后想再看一眼那条回答，如果只保留卡片就永远找不到了。
//

import SwiftUI

struct AskHistoryView: View {

    @EnvironmentObject private var store: CardStore
    @Environment(\.dismiss) private var dismiss

    @State private var threads: [AskThread] = []
    @State private var pendingDeletion: AskThread?
    @State private var actionError: String?

    var body: some View {
        NavigationStack {
            List {
                if threads.isEmpty {
                    Section {
                        EmptyHintView(
                            icon: "bubble.left.and.bubble.right",
                            title: "还没有提问记录",
                            message: "在「提问」页问一个问题，记录会出现在这里。"
                        )
                    }
                } else {
                    ForEach(groupedThreads, id: \.title) { group in
                        Section(group.title) {
                            ForEach(group.threads) { thread in
                                NavigationLink {
                                    AskThreadDetailView(thread: thread)
                                } label: {
                                    row(thread)
                                }
                            }
                            .onDelete { offsets in
                                guard let index = offsets.first else { return }
                                pendingDeletion = group.threads[index]
                            }
                        }
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("提问历史")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("关闭") { dismiss() }
                }
            }
            .task { reload() }
            .confirmationDialog(
                "删除这条提问记录？",
                isPresented: deletionBinding,
                titleVisibility: .visible
            ) {
                Button("删除", role: .destructive) { confirmDeletion() }
                Button("取消", role: .cancel) { pendingDeletion = nil }
            } message: {
                Text("只删除问答记录，已经存下来的卡片不受影响。")
            }
            .alert("操作失败", isPresented: errorBinding) {
                Button("好") { actionError = nil }
            } message: {
                Text(actionError ?? "")
            }
        }
    }

    // MARK: 行

    private func row(_ thread: AskThread) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Text(thread.question)
                    .font(.callout)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)

                Spacer(minLength: 0)

                if thread.isSaved {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(Color.green)
                } else if thread.worthSaving {
                    Image(systemName: "lightbulb.fill")
                        .font(.caption)
                        .foregroundStyle(Color.orange)
                }
            }

            HStack(spacing: 6) {
                if let deckTitle = thread.deckTitle, !deckTitle.isEmpty {
                    Text(deckTitle)
                        .lineLimit(1)
                }
                Text("·")
                Text(AppFormat.clock(thread.createdAt))
                if thread.isSaved {
                    Text("· 已存成卡片")
                }
            }
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }

    // MARK: 分组

    private struct DayGroup {
        let title: String
        let threads: [AskThread]
    }

    /// 按天分组，新的在前。分组标题用与「历史」页相同的格式。
    private var groupedThreads: [DayGroup] {
        var order: [Date] = []
        var buckets: [Date: [AskThread]] = [:]

        for thread in threads {
            let day = AppFormat.dayStart(thread.createdAt)
            if buckets[day] == nil {
                buckets[day] = []
                order.append(day)
            }
            buckets[day]?.append(thread)
        }

        return order.map { day in
            DayGroup(
                title: AppFormat.dayTitle(day),
                threads: buckets[day] ?? []
            )
        }
    }

    // MARK: 数据

    private func reload() {
        threads = store.askThreads(limit: 200)
    }

    private var deletionBinding: Binding<Bool> {
        Binding(
            get: { pendingDeletion != nil },
            set: { if !$0 { pendingDeletion = nil } }
        )
    }

    private var errorBinding: Binding<Bool> {
        Binding(
            get: { actionError != nil },
            set: { if !$0 { actionError = nil } }
        )
    }

    private func confirmDeletion() {
        guard let thread = pendingDeletion else { return }
        pendingDeletion = nil
        do {
            try store.delete(askThread: thread)
            reload()
        } catch {
            actionError = AppFormat.message(for: error)
        }
    }
}

// MARK: - 详情

/// 单条提问的详情：完整问答 + 当时给出的卡片草稿。
struct AskThreadDetailView: View {

    let thread: AskThread

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        List {
            Section("你的问题") {
                Text(thread.question)
                    .font(.callout)
                    .textSelection(.enabled)
            }

            Section("回答") {
                Text(thread.answer)
                    .font(.callout)
                    .textSelection(.enabled)
            }

            if thread.worthSaving || thread.reason != nil {
                Section("AI 的判断") {
                    AskVerdictRow(worthSaving: thread.worthSaving, reason: thread.reason)
                }
            }

            if let draft = thread.draft {
                Section("当时的卡片草稿") {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(draft.question)
                            .font(.callout.weight(.medium))
                            .fixedSize(horizontal: false, vertical: true)

                        Text(draft.answer)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)

                        if let detail = draft.detail, !detail.isEmpty {
                            Text(detail)
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(.vertical, 2)
                }
            }

            Section {
                LabeledContent("时间", value: AppFormat.full(thread.createdAt))
                if let deckTitle = thread.deckTitle {
                    LabeledContent("牌组", value: deckTitle)
                }
                LabeledContent(
                    "状态",
                    value: thread.isSaved ? "已存成卡片" : "未存成卡片"
                )
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("提问详情")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("关闭") { dismiss() }
            }
        }
    }
}
