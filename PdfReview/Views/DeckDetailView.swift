//
//  DeckDetailView.swift
//  PdfReview
//
//  单个牌组：顶部摘要与统计，下面是全部卡片。
//  卡片可以收藏、删除；整个牌组可以导出成 .pdfreview.json 分享出去。
//
//  导出复用 AnalysisImporter.writeTemporaryFile：它会把文档写成
//  「牌组名.pdfreview.json」放到临时目录，再用系统分享面板发出去。
//

import SwiftUI

struct DeckDetailView: View {

    @EnvironmentObject private var store: CardStore
    @Environment(\.dismiss) private var dismiss

    /// 由列表页传入。SwiftData 的 @Model 是引用类型，属性变化会自动反映。
    let deck: ReviewDeck

    /// 内容变化时通知列表页刷新（删除牌组后列表要变）。
    var onChanged: () -> Void = { }

    /// 编辑中的卡片。
    @State private var editingCard: ReviewCard?

    /// 待确认删除的卡片。
    @State private var pendingCardDeletion: ReviewCard?

    /// 待确认删除整个牌组。
    @State private var confirmDeckDeletion = false

    /// 导出文件的临时 URL。非 nil 时弹出分享面板。
    @State private var exportURL: URL?

    /// 操作失败提示。
    @State private var actionError: String?

    /// 局部刷新触发器。
    @State private var refreshToken = 0

    init(deck: ReviewDeck, onChanged: @escaping () -> Void = { }) {
        self.deck = deck
        self.onChanged = onChanged
    }

    var body: some View {
        List {
            headerSection
            tagsSection
            cardsSection

            Section {
                Button(role: .destructive) {
                    confirmDeckDeletion = true
                } label: {
                    Label("删除整个牌组", systemImage: "trash")
                }
            } footer: {
                Text("删除后卡片与展示历史一并移除，无法恢复。建议先导出备份。")
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle(deck.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button {
                        exportDeck()
                    } label: {
                        Label("导出为 .pdfreview.json", systemImage: "square.and.arrow.up")
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
        .sheet(item: $editingCard) { card in
            CardEditorView(card: card) {
                refresh()
            }
        }
        .sheet(item: exportItem) { item in
            ShareSheetView(url: item.url)
        }
        .confirmationDialog(
            "删除这张卡片？",
            isPresented: cardDeletionBinding,
            titleVisibility: .visible
        ) {
            Button("删除卡片", role: .destructive) {
                confirmCardDeletion()
            }
            Button("取消", role: .cancel) {
                pendingCardDeletion = nil
            }
        }
        .confirmationDialog(
            "删除整个牌组？",
            isPresented: $confirmDeckDeletion,
            titleVisibility: .visible
        ) {
            Button("删除牌组", role: .destructive) {
                deleteDeck()
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("「\(deck.title)」及其 \(deck.cards.count) 张卡片都会被删除。")
        }
        .alert("操作失败", isPresented: errorBinding) {
            Button("好") { actionError = nil }
        } message: {
            Text(actionError ?? "")
        }
    }

    // MARK: 头部

    @ViewBuilder
    private var headerSection: some View {
        Section {
            VStack(alignment: .leading, spacing: 10) {
                Text(deck.title)
                    .font(.title3.weight(.semibold))
                    .fixedSize(horizontal: false, vertical: true)

                if let summary = deck.summary, !summary.isEmpty {
                    Text(summary)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                HStack(spacing: 8) {
                    StatTile(title: "卡片", value: "\(deck.cards.count)")
                    if deck.pageCount > 0 {
                        StatTile(title: "页数", value: "\(deck.pageCount)")
                    }
                    StatTile(
                        title: "收藏",
                        value: "\(deck.cards.filter(\.isFavorite).count)"
                    )
                }
                .padding(.top, 2)
            }
            .padding(.vertical, 4)

            LabeledContent("来源") {
                Text(deck.sourceKind == "pdf" ? "PDF 分析" : "文件导入")
            }
            if let fileName = deck.sourceFileName, !fileName.isEmpty {
                LabeledContent("文件名") {
                    Text(fileName)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
            }
            LabeledContent("创建时间") {
                Text(AppFormat.full(deck.createdAt))
            }
        }
    }

    // MARK: 标签

    @ViewBuilder
    private var tagsSection: some View {
        let tags = aggregatedTags
        if !tags.isEmpty {
            Section("标签") {
                FlowTagRow(tags: tags)
                    .padding(.vertical, 2)
            }
        }
    }

    /// 汇总本牌组所有卡片的标签，按出现次数降序。
    private var aggregatedTags: [String] {
        var counter: [String: Int] = [:]
        for card in deck.cards {
            for tag in card.tags {
                let key = tag.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !key.isEmpty else { continue }
                counter[key, default: 0] += 1
            }
        }
        return counter
            .sorted { lhs, rhs in
                lhs.value == rhs.value ? lhs.key < rhs.key : lhs.value > rhs.value
            }
            .map(\.key)
    }

    // MARK: 卡片列表

    @ViewBuilder
    private var cardsSection: some View {
        let cards = deck.sortedCards
        Section {
            if cards.isEmpty {
                ContentUnavailableView {
                    Label("这个牌组没有卡片", systemImage: "rectangle.on.rectangle.slash")
                } description: {
                    Text("可能导入的文件里卡片被过滤掉了。")
                }
                .listRowInsets(EdgeInsets(top: 16, leading: 12, bottom: 16, trailing: 12))
            } else {
                ForEach(cards, id: \.id) { card in
                    cardRow(card)
                        .contentShape(Rectangle())
                        .onTapGesture {
                            editingCard = card
                        }
                        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                            Button(role: .destructive) {
                                pendingCardDeletion = card
                            } label: {
                                Label("删除", systemImage: "trash")
                            }
                        }
                        .swipeActions(edge: .leading, allowsFullSwipe: true) {
                            Button {
                                toggleFavorite(card)
                            } label: {
                                Label(
                                    card.isFavorite ? "取消收藏" : "收藏",
                                    systemImage: card.isFavorite ? "star.slash" : "star"
                                )
                            }
                            .tint(.yellow)
                        }
                }
            }
        } header: {
            HStack {
                Text("卡片")
                Spacer()
                Text("\(cards.count) 张")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        } footer: {
            Text("点卡片可以编辑题目、答案与评分；左滑删除，右滑收藏。")
        }
    }

    private func cardRow(_ card: ReviewCard) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top, spacing: 8) {
                Text(card.question)
                    .font(.body.weight(.semibold))
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)

                if card.isFavorite {
                    Image(systemName: "star.fill")
                        .font(.caption)
                        .foregroundStyle(.yellow)
                }
            }

            Text(card.answer)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)

            if !card.tags.isEmpty {
                TagChips(tags: card.tags)
            }

            HStack(spacing: 10) {
                if let page = card.sourcePage {
                    Text("第 \(page) 页")
                }
                Text("难度 \(card.difficulty)")
                Text("重要度 \(card.importance)")
                // 提问来的卡片值得区分：用户看到「提问」就知道这是自己问出来的，
                // 而不是文档里本来就有的。手工加的也标出来，同上。
                if card.origin != ReviewCard.Origin.analysis {
                    Label(
                        ReviewCard.Origin.label(for: card.origin),
                        systemImage: card.isFromAsk ? "bubble.left" : "square.and.pencil"
                    )
                    .labelStyle(.titleAndIcon)
                }
            }
            .font(.caption2)
            .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 4)
    }

    // MARK: 操作

    private func refresh() {
        refreshToken &+= 1
        onChanged()
    }

    private func toggleFavorite(_ card: ReviewCard) {
        do {
            try store.toggleFavorite(card: card)
            refresh()
        } catch {
            actionError = AppFormat.message(for: error)
        }
    }

    private func confirmCardDeletion() {
        guard let card = pendingCardDeletion else { return }
        pendingCardDeletion = nil
        do {
            try store.delete(card: card)
            refresh()
        } catch {
            actionError = AppFormat.message(for: error)
        }
    }

    private func deleteDeck() {
        do {
            try store.delete(deck: deck)
            onChanged()
            dismiss()
        } catch {
            actionError = AppFormat.message(for: error)
        }
    }

    /// 把当前牌组拼成 AnalysisDocument 后写临时文件。
    private func exportDeck() {
        do {
            let document = makeDocument()
            try AnalysisValidator.validate(document)
            exportURL = try AnalysisImporter.writeTemporaryFile(document)
        } catch {
            actionError = AppFormat.message(for: error)
        }
    }

    private func makeDocument() -> AnalysisDocument {
        let items: [AnalysisDocument.CardItem] = deck.sortedCards.map { card in
            AnalysisDocument.CardItem(
                question: card.question,
                answer: card.answer,
                detail: card.detail,
                tags: card.tags.isEmpty ? nil : card.tags,
                sourcePage: card.sourcePage,
                difficulty: card.difficulty,
                importance: card.importance
            )
        }

        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withColonSeparatorInTimeZone]

        return AnalysisDocument(
            schemaVersion: AnalysisDocument.supportedVersion,
            generator: "PdfReview/1.0",
            generatedAt: formatter.string(from: Date()),
            source: AnalysisDocument.Source(
                fileName: deck.sourceFileName ?? "\(deck.title).pdf",
                pageCount: deck.pageCount,
                sha256: nil
            ),
            deck: AnalysisDocument.Deck(
                title: deck.title,
                summary: deck.summary,
                language: deck.language
            ),
            cards: items
        )
    }

    // MARK: 绑定

    /// 分享面板需要 Identifiable 的条目，这里包一层。
    private struct ExportItem: Identifiable {
        let id = UUID()
        let url: URL
    }

    private var exportItem: Binding<ExportItem?> {
        Binding(
            get: {
                guard let exportURL else { return nil }
                return ExportItem(url: exportURL)
            },
            set: { newValue in
                if newValue == nil { exportURL = nil }
            }
        )
    }

    private var cardDeletionBinding: Binding<Bool> {
        Binding(
            get: { pendingCardDeletion != nil },
            set: { newValue in if !newValue { pendingCardDeletion = nil } }
        )
    }

    private var errorBinding: Binding<Bool> {
        Binding(
            get: { actionError != nil },
            set: { newValue in if !newValue { actionError = nil } }
        )
    }
}
