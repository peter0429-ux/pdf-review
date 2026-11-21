//
//  CardEditorView.swift
//  PdfReview
//
//  单张卡片的编辑面板：题目、答案、补充说明、标签、难度、重要度、收藏。
//
//  编辑在本地 State 里进行，点「保存」才写回模型并持久化，
//  这样用户中途取消不会留下半截修改。
//
//  本视图有私有 @State，必须显式写 init（否则合成的成员初始化器是 private）。
//

import SwiftUI

struct CardEditorView: View {

    @EnvironmentObject private var store: CardStore
    @Environment(\.dismiss) private var dismiss

    /// 被编辑的卡片（引用类型，保存时直接改它）。
    let card: ReviewCard

    /// 保存成功后的回调，让上层刷新列表。
    let onSaved: () -> Void

    @State private var question = ""
    @State private var answer = ""
    @State private var detail = ""
    @State private var tagsText = ""
    @State private var difficulty = 3
    @State private var importance = 3
    @State private var isFavorite = false
    @State private var saveError: String?
    @State private var didLoad = false

    init(card: ReviewCard, onSaved: @escaping () -> Void = { }) {
        self.card = card
        self.onSaved = onSaved
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("题目") {
                    editorPlaceholder(
                        text: $question,
                        placeholder: "这张卡问什么？",
                        minHeight: 70
                    )
                    characterCounter(question, limit: AnalysisValidator.Limits.questionMax)
                }

                Section("答案") {
                    editorPlaceholder(
                        text: $answer,
                        placeholder: "答案写简短、能独立读懂。",
                        minHeight: 100
                    )
                    characterCounter(answer, limit: AnalysisValidator.Limits.answerMax)
                }

                Section {
                    editorPlaceholder(
                        text: $detail,
                        placeholder: "可选：补充说明、易错点、出处。",
                        minHeight: 70
                    )
                    characterCounter(detail, limit: AnalysisValidator.Limits.detailMax)
                } header: {
                    Text("补充说明")
                } footer: {
                    Text("留空则不显示。")
                }

                Section {
                    TextField("用逗号分隔", text: $tagsText, axis: .vertical)
                        .lineLimit(1...3)
                    if !parsedTags.isEmpty {
                        TagChips(tags: parsedTags)
                    }
                } header: {
                    Text("标签")
                } footer: {
                    Text("最多 \(AnalysisValidator.Limits.tagsMax) 个，每个不超过 \(AnalysisValidator.Limits.tagLengthMax) 字，重复的会自动去掉。")
                }

                Section("评分") {
                    Stepper(value: $difficulty, in: 1...5) {
                        LabeledContent("难度", value: "\(difficulty) / 5")
                    }
                    Stepper(value: $importance, in: 1...5) {
                        LabeledContent("重要度", value: "\(importance) / 5")
                    }
                    Toggle(isOn: $isFavorite) {
                        Label("收藏", systemImage: "star")
                    }
                }

                if let saveError {
                    Section {
                        Text(saveError)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("编辑卡片")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") { save() }
                        .disabled(!canSave)
                }
            }
            .onAppear {
                guard !didLoad else { return }
                didLoad = true
                loadFromCard()
            }
        }
    }

    // MARK: 片段

    private func editorPlaceholder(
        text: Binding<String>,
        placeholder: String,
        minHeight: CGFloat
    ) -> some View {
        ZStack(alignment: .topLeading) {
            TextEditor(text: text)
                .frame(minHeight: minHeight)

            if text.wrappedValue.isEmpty {
                Text(placeholder)
                    .foregroundStyle(.tertiary)
                    .padding(.top, 8)
                    .padding(.leading, 5)
                    .allowsHitTesting(false)
            }
        }
    }

    private func characterCounter(_ text: String, limit: Int) -> some View {
        HStack {
            Spacer()
            Text("\(text.count) / \(limit)")
                .font(.caption2)
                .foregroundStyle(text.count > limit ? .red : .tertiary)
                .monospacedDigit()
        }
    }

    // MARK: 数据

    private func loadFromCard() {
        question = card.question
        answer = card.answer
        detail = card.detail ?? ""
        tagsText = card.tags.joined(separator: "，")
        difficulty = card.difficulty
        importance = card.importance
        isFavorite = card.isFavorite
    }

    /// 把用户输入（中英文逗号、顿号、换行分隔）拆成标签。
    private var parsedTags: [String] {
        let separators = CharacterSet(charactersIn: ",，、\n")
        let raw = tagsText.components(separatedBy: separators)

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

    private var canSave: Bool {
        !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && question.count <= AnalysisValidator.Limits.questionMax
            && answer.count <= AnalysisValidator.Limits.answerMax
            && detail.count <= AnalysisValidator.Limits.detailMax
    }

    private func save() {
        let trimmedQuestion = question.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedAnswer = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedDetail = detail.trimmingCharacters(in: .whitespacesAndNewlines)

        card.question = trimmedQuestion
        card.answer = trimmedAnswer
        card.detail = trimmedDetail.isEmpty ? nil : trimmedDetail
        card.tags = parsedTags
        card.difficulty = ReviewCard.clampScore(difficulty)
        card.importance = ReviewCard.clampScore(importance)
        card.isFavorite = isFavorite
        card.deck?.updatedAt = Date()

        do {
            try store.save()
            // 题面/标签/收藏都进了快照，必须重新物化一次。
            try store.refreshRotationCache()
            onSaved()
            dismiss()
        } catch {
            saveError = AppFormat.message(for: error)
        }
    }
}
