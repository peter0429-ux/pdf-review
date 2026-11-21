//
//  DeckListView.swift
//  PdfReview
//
//  「牌组」页：列出所有牌组，进入详情、归档、删除。
//  归档只是从轮换池里移出（ReviewDeck.isArchived），不会删数据，
//  用户想找回来随时可以取消归档。
//

import SwiftUI

struct DeckListView: View {

    @EnvironmentObject private var store: CardStore

    /// 由 RootView 注入：打开导入 sheet。
    let onRequestImport: () -> Void

    /// 数据版本号。SwiftData 的模型对象不是 Observable，
    /// 增删改之后要靠这个 token 让列表重新取一次数据。
    @State private var refreshToken = 0

    /// 待确认删除的牌组。
    @State private var pendingDeletion: ReviewDeck?

    /// 操作失败提示。
    @State private var actionError: String?

    init(onRequestImport: @escaping () -> Void) {
        self.onRequestImport = onRequestImport
    }

    var body: some View {
        NavigationStack {
            List {
                if let lastError = store.lastError {
                    Section {
                        ErrorBannerView(message: lastError) {
                            store.clearError()
                        }
                        .listRowInsets(EdgeInsets())
                        .listRowBackground(Color.clear)
                    }
                }

                if decks.isEmpty {
                    emptySection
                } else {
                    decksSection
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("牌组")
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
                refresh()
            }
            .confirmationDialog(
                "删除这个牌组？",
                isPresented: deletionBinding,
                titleVisibility: .visible
            ) {
                Button("删除牌组", role: .destructive) {
                    confirmDeletion()
                }
                Button("取消", role: .cancel) {
                    pendingDeletion = nil
                }
            } message: {
                Text("「\(pendingDeletion?.title ?? "")」及其全部卡片、展示历史都会被删除，且无法恢复。")
            }
            .alert("操作失败", isPresented: errorBinding) {
                Button("好") { actionError = nil }
            } message: {
                Text(actionError ?? "")
            }
        }
    }

    // MARK: 列表

    @ViewBuilder
    private var decksSection: some View {
        Section {
            ForEach(decks, id: \.id) { deck in
                NavigationLink {
                    DeckDetailView(deck: deck, onChanged: refresh)
                } label: {
                    row(for: deck)
                }
                .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                    Button(role: .destructive) {
                        pendingDeletion = deck
                    } label: {
                        Label("删除", systemImage: "trash")
                    }

                    Button {
                        toggleArchive(deck)
                    } label: {
                        Label(deck.isArchived ? "取消归档" : "归档",
                              systemImage: deck.isArchived ? "tray.and.arrow.up" : "archivebox")
                    }
                    .tint(.orange)
                }
            }
        } footer: {
            Text("归档的牌组不会出现在轮换里，数据仍然保留。")
        }
    }

    private func row(for deck: ReviewDeck) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Text(deck.title)
                    .font(.body.weight(.medium))
                    .lineLimit(2)

                if deck.isArchived {
                    Text("已归档")
                        .font(.caption2)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(
                            Capsule().fill(Color.secondary.opacity(0.15))
                        )
                        .foregroundStyle(.secondary)
                }
            }

            HStack(spacing: 8) {
                Label("\(deck.cards.count) 张卡", systemImage: "rectangle.on.rectangle")
                Text("·")
                Text(sourceLabel(for: deck))
                if deck.pageCount > 0 {
                    Text("·")
                    Text("\(deck.pageCount) 页")
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            .lineLimit(1)

            Text(AppFormat.full(deck.createdAt) + " 创建")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 3)
    }

    private func sourceLabel(for deck: ReviewDeck) -> String {
        deck.sourceKind == "pdf" ? "来自 PDF" : "来自导入"
    }

    // MARK: 空态

    @ViewBuilder
    private var emptySection: some View {
        Section {
            ContentUnavailableView {
                Label("还没有牌组", systemImage: "square.stack.3d.up.slash")
            } description: {
                Text("导入一份 PDF 让 AI 生成卡片，或导入别人给的 .pdfreview.json。")
            } actions: {
                Button("导入") {
                    onRequestImport()
                }
                .buttonStyle(.borderedProminent)
            }
            .listRowInsets(EdgeInsets(top: 20, leading: 12, bottom: 20, trailing: 12))
        }
    }

    // MARK: 数据与操作

    private var decks: [ReviewDeck] {
        // 读一下 token，建立依赖关系，刷新时 body 会重算。
        _ = refreshToken
        return store.allDecks()
    }

    private func refresh() {
        refreshToken &+= 1
    }

    private func toggleArchive(_ deck: ReviewDeck) {
        do {
            deck.isArchived.toggle()
            deck.updatedAt = Date()
            try store.save()
            try store.refreshRotationCache()
            refresh()
        } catch {
            actionError = AppFormat.message(for: error)
        }
    }

    private func confirmDeletion() {
        guard let deck = pendingDeletion else { return }
        pendingDeletion = nil
        do {
            try store.delete(deck: deck)
            refresh()
        } catch {
            actionError = AppFormat.message(for: error)
        }
    }

    private var deletionBinding: Binding<Bool> {
        Binding(
            get: { pendingDeletion != nil },
            set: { newValue in if !newValue { pendingDeletion = nil } }
        )
    }

    private var errorBinding: Binding<Bool> {
        Binding(
            get: { actionError != nil },
            set: { newValue in if !newValue { actionError = nil } }
        )
    }
}
