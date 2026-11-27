//
//  AskView.swift
//  PdfReview
//
//  「提问」页：就某份牌组提问，AI 回答后判断值不值得做成复习卡片。
//
//  设计上的三个决定：
//  1. 回答与卡片分开呈现。用户至少要拿到答案，卡片是额外的。
//  2. 草稿默认收起、默认不保存。AI 觉得值得不等于用户想存。
//  3. 提问记录一律入库（`AskThread`）。哪怕这次没做成卡片，
//     用户事后还能翻回来重读那条回答 —— 这正是「历史」页存在的理由。
//

import SwiftUI

struct AskView: View {

    @EnvironmentObject private var store: CardStore
    @EnvironmentObject private var settings: AppSettings

    /// 由 RootView 注入：切到设置页补 API Key。
    let onOpenSettings: () -> Void

    /// 由 RootView 注入：打开历史页。
    let onOpenHistory: () -> Void

    // MARK: 输入

    @State private var question = ""
    @State private var selectedDeckID: UUID?

    // MARK: 状态

    @State private var isAsking = false
    @State private var errorMessage: String?

    /// 当前这一轮的问答结果。nil 表示还没问过。
    @State private var result: AskResult?

    /// 当前这一轮已经入库的提问记录 ID。用来在保存卡片后回写 `savedCardID`。
    @State private var currentThreadID: UUID?

    /// 当前结果对应的问题原文。单独存一份，避免在 body 里反查 SwiftData。
    @State private var currentQuestion = ""

    /// 当前结果对应的牌组（提问时锁定，避免中途改选导致存错地方）。
    @State private var resultDeckID: UUID?
    @State private var resultDeckTitle: String?

    // MARK: 草稿

    @State private var draftQuestion = ""
    @State private var draftAnswer = ""
    @State private var draftDetail = ""
    @State private var draftTagsText = ""
    @State private var draftDifficulty = 3
    @State private var draftImportance = 3
    @State private var draftExpanded = false

    /// 保存成功后的轻提示。
    @State private var toast: String?

    @FocusState private var questionFocused: Bool

    var body: some View {
        NavigationStack {
            List {
                deckSection
                questionSection

                if let errorMessage {
                    Section {
                        Text(errorMessage)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }
                }

                if let result {
                    answerSection(result)
                    if result.worthSaving, result.draft != nil {
                        draftSection(result)
                    }
                    choiceSection
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("提问")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        onOpenHistory()
                    } label: {
                        Label("历史", systemImage: "clock.arrow.circlepath")
                    }
                }
            }
            .safeAreaInset(edge: .bottom) {
                askBar
            }
            .alert("保存成功", isPresented: toastBinding) {
                Button("好") { toast = nil }
            } message: {
                Text(toast ?? "")
            }
            .task {
                // 默认选中「当前正在复习的那张卡」所在的牌组：
                // 用户多半是想对刚看到的内容发问。
                if selectedDeckID == nil {
                    selectedDeckID = defaultDeckID()
                }
            }
        }
    }

    // MARK: 牌组选择

    private var deckSection: some View {
        Section {
            if decks.isEmpty {
                Text("还没有牌组。先导入一份 PDF 或用示例内容开始。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                Picker("牌组", selection: $selectedDeckID) {
                    ForEach(decks) { deck in
                        Text(deck.title).tag(Optional(deck.id))
                    }
                }
                .pickerStyle(.menu)
                .disabled(isAsking)

                if let deck = selectedDeck {
                    LabeledContent {
                        Text(deck.hasSourceText ? "有" : "无")
                            .foregroundStyle(deck.hasSourceText ? Color.secondary : Color.orange)
                    } label: {
                        Label("原文", systemImage: "doc.text")
                    }
                    .font(.footnote)

                    if !deck.hasSourceText {
                        Text("这份牌组没有保存原文，AI 只能凭已有卡片或通用知识回答。导入 PDF 生成的牌组才有原文。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        } header: {
            Text("问哪份资料")
        }
    }

    // MARK: 问题输入

    private var questionSection: some View {
        Section {
            TextField(
                "比如：为什么电容能隔直通交，而电感相反？",
                text: $question,
                axis: .vertical
            )
            .lineLimit(3...8)
            .focused($questionFocused)
            .disabled(isAsking)
        } header: {
            Text("你的问题")
        } footer: {
            Text("AI 会先回答问题；如果判断这个知识点值得复习，会另外给一张卡片草稿。")
        }
    }

    // MARK: 回答

    private func answerSection(_ result: AskResult) -> some View {
        Section {
            AskQuestionBubble(question: currentQuestionForDisplay)
                .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                .listRowBackground(Color.clear)

            AskAnswerCard(answer: result.answer)
                .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 4, trailing: 16))
                .listRowBackground(Color.clear)

            if let deckTitle = resultDeckTitle {
                Text("依据：\(deckTitle)")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }

            if result.worthSaving || result.reason != nil {
                AskVerdictRow(worthSaving: result.worthSaving, reason: result.reason)
            } else {
                AskVerdictRow(worthSaving: false, reason: nil)
            }
        } header: {
            Text("回答")
        }
    }

    // MARK: 草稿

    private func draftSection(_ result: AskResult) -> some View {
        Section {
            CardDraftView(
                question: $draftQuestion,
                answer: $draftAnswer,
                detail: $draftDetail,
                tagsText: $draftTagsText,
                difficulty: $draftDifficulty,
                importance: $draftImportance,
                isExpanded: $draftExpanded
            )
            .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
            .listRowBackground(Color.clear)

            if let deck = resultDeck {
                Button {
                    saveDraft(into: deck)
                } label: {
                    Label("保存到「\(deck.title)」", systemImage: "square.and.arrow.down")
                }
                .disabled(!canSaveDraft)
            } else {
                Text("这张卡片原本要存的牌组已经不在了，请重新提问。")
                    .font(.footnote)
                    .foregroundStyle(.orange)
            }
        } header: {
            Text("卡片草稿")
        } footer: {
            Text("保存后它会进入轮换池，到点自动出现在复习页与桌面小组件里。")
        }
    }

    // MARK: 底部操作

    private var choiceSection: some View {
        Section {
            Button {
                askAgain()
            } label: {
                Label("换个问法", systemImage: "arrow.clockwise")
            }
            .disabled(isAsking)

            Button(role: .destructive) {
                clearResult()
            } label: {
                Label("不要了", systemImage: "xmark")
            }
        }
    }

    private var askBar: some View {
        HStack(spacing: 12) {
            TextField("输入问题…", text: $question, axis: .vertical)
                .lineLimit(1...3)
                .textFieldStyle(.roundedBorder)
                .focused($questionFocused)
                .disabled(isAsking)

            Button {
                startAsk()
            } label: {
                if isAsking {
                    ProgressView()
                        .controlSize(.small)
                        .frame(width: 28, height: 28)
                } else {
                    Image(systemName: "paperplane.fill")
                        .frame(width: 28, height: 28)
                }
            }
            .buttonStyle(.borderedProminent)
            .clipShape(Circle())
            .disabled(!canAsk)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.bar)
    }

    // MARK: 计算属性

    private var decks: [ReviewDeck] {
        store.allDecks().filter { !$0.isArchived }
    }

    private var selectedDeck: ReviewDeck? {
        guard let selectedDeckID else { return nil }
        return store.deck(withID: selectedDeckID)
    }

    private var resultDeck: ReviewDeck? {
        guard let resultDeckID else { return nil }
        return store.deck(withID: resultDeckID)
    }

    /// 回答区显示的问题：用发问时锁定下来的原话，而不是输入框的当前内容
    /// （用户可能已经在输入框里改字准备下一个问题了）。
    private var currentQuestionForDisplay: String {
        currentQuestion.isEmpty ? question : currentQuestion
    }

    private var canAsk: Bool {
        !isAsking
            && !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && settings.isAIConfigured
            && selectedDeckID != nil
    }

    private var canSaveDraft: Bool {
        !draftQuestion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !draftAnswer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && draftQuestion.count <= AnalysisValidator.Limits.questionMax
            && draftAnswer.count <= AnalysisValidator.Limits.answerMax
            && draftDetail.count <= AnalysisValidator.Limits.detailMax
    }

    private var toastBinding: Binding<Bool> {
        Binding(
            get: { toast != nil },
            set: { if !$0 { toast = nil } }
        )
    }

    // MARK: 默认牌组

    /// 默认选中当前轮换槽位里那张卡所属的牌组。
    private func defaultDeckID() -> UUID? {
        if let cache = RotationCache.load(),
           let slot = RotationScheduler.slot(at: Date(), cache: cache),
           let snapshot = slot.cards.first,
           store.deck(withID: snapshot.deckID) != nil {
            return snapshot.deckID
        }
        // 缓存里没有（或那张卡所属牌组已删），退回到最近创建的牌组。
        return decks.first?.id
    }

    // MARK: 动作

    private func startAsk() {
        guard let deck = selectedDeck else {
            errorMessage = "请先选择一份牌组。"
            return
        }

        let config: AIRequestConfig
        do {
            config = try settings.aiConfig()
        } catch {
            errorMessage = AppFormat.message(for: error)
            return
        }

        let askedQuestion = question.trimmingCharacters(in: .whitespacesAndNewlines)
        let context = deck.sourceText ?? ""
        let digest = deck.sortedCards.map(\.question)

        isAsking = true
        errorMessage = nil
        questionFocused = false

        Task { @MainActor in
            do {
                let client = AIClient()
                let asked = try await client.ask(
                    question: askedQuestion,
                    deckTitle: deck.title,
                    context: context,
                    cardsDigest: digest,
                    config: config
                )

                // 提问记录一律入库 —— 哪怕没有卡片草稿。
                // 存失败不影响展示回答，所以单独 catch。
                var threadID: UUID?
                do {
                    threadID = try store.insertAskThread(
                        question: asked.question,
                        answer: asked.answer,
                        worthSaving: asked.worthSaving,
                        reason: asked.reason,
                        deckID: deck.id,
                        deckTitle: deck.title,
                        draft: asked.draft
                    )
                } catch {
                    store.reportError("提问记录保存失败：\(AppFormat.message(for: error))")
                }

                result = asked
                currentThreadID = threadID
                currentQuestion = asked.question
                resultDeckID = deck.id
                resultDeckTitle = deck.title
                prepareDraft(from: asked)
                isAsking = false
            } catch {
                errorMessage = AppFormat.message(for: error)
                isAsking = false
            }
        }
    }

    /// 把 AI 的草稿灌进编辑状态。
    private func prepareDraft(from result: AskResult) {
        guard let draft = result.draft else {
            draftQuestion = ""
            draftAnswer = ""
            draftDetail = ""
            draftTagsText = ""
            draftDifficulty = 3
            draftImportance = 3
            draftExpanded = false
            return
        }
        draftQuestion = draft.question
        draftAnswer = draft.answer
        draftDetail = draft.detail ?? ""
        draftTagsText = (draft.tags ?? []).joined(separator: "，")
        draftDifficulty = ReviewCard.clampScore(draft.difficulty ?? 3)
        draftImportance = ReviewCard.clampScore(draft.importance ?? 3)
        draftExpanded = false
    }

    private func saveDraft(into deck: ReviewDeck) {
        do {
            let cardID = try store.insertCard(
                into: deck,
                question: draftQuestion,
                answer: draftAnswer,
                detail: draftDetail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? nil
                    : draftDetail,
                tags: parsedDraftTags,
                sourcePage: nil,
                difficulty: draftDifficulty,
                importance: draftImportance,
                origin: ReviewCard.Origin.ask
            )

            // 回写提问记录，标记「已保存」。
            if let currentThreadID {
                try? store.markThreadSaved(threadID: currentThreadID, cardID: cardID)
            }

            toast = "已加入「\(deck.title)」，到点会出现在复习页与桌面小组件里。"
        } catch {
            errorMessage = "保存失败：\(AppFormat.message(for: error))"
        }
    }

    private var parsedDraftTags: [String] {
        let separators = CharacterSet(charactersIn: ",，、\n")
        let raw = draftTagsText.components(separatedBy: separators)

        var seen = Set<String>()
        var result: [String] = []
        for piece in raw {
            let trimmed = piece.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }
            let clipped = String(trimmed.prefix(AnalysisValidator.Limits.tagLengthMax))
            guard seen.insert(clipped).inserted else { continue }
            result.append(clipped)
            if result.count >= AnalysisValidator.Limits.tagsMax { break }
        }
        return result
    }

    private func askAgain() {
        clearResult()
        questionFocused = true
    }

    private func clearResult() {
        result = nil
        currentThreadID = nil
        currentQuestion = ""
        resultDeckID = nil
        resultDeckTitle = nil
        prepareDraft(from: AskResult(
            answer: "",
            worthSaving: false,
            reason: nil,
            draft: nil
        ))
        draftExpanded = false
    }
}
