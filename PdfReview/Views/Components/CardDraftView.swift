//
//  CardDraftView.swift
//  PdfReview
//
//  卡片草稿编辑器：AI 给出草稿、用户改完再决定要不要存。
//
//  为什么不复用 `CardEditorView`：那个面板操作的是已经存在的 `ReviewCard`
//  引用，点保存直接改模型。草稿在保存之前**根本没有模型对象**，硬套的话
//  得先插一张空卡再删，失败路径会留下垃圾数据。
//
//  所以这里的数据全部在 @State 里，保存时才交给 `CardStore.insertCard`。
//

import SwiftUI
import UIKit

struct CardDraftView: View {

    /// 绑定回父视图的草稿字段。父视图持有真正的值，这里只编辑。
    @Binding var question: String
    @Binding var answer: String
    @Binding var detail: String
    @Binding var tagsText: String
    @Binding var difficulty: Int
    @Binding var importance: Int

    /// 是否展开编辑。默认收起，避免一屏全是输入框。
    @Binding var isExpanded: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header

            if isExpanded {
                fields
            } else {
                preview
            }
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color(uiColor: .secondarySystemGroupedBackground))
        )
    }

    // MARK: 片段

    private var header: some View {
        HStack {
            Label("卡片草稿", systemImage: "rectangle.on.rectangle")
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)

            Spacer()

            Button(isExpanded ? "收起" : "改一改") {
                withAnimation(.easeInOut(duration: 0.2)) {
                    isExpanded.toggle()
                }
            }
            .font(.caption)
            .buttonStyle(.plain)
            .foregroundStyle(Color.accentColor)
        }
    }

    /// 收起状态下只看题面与答案首行，够判断「要不要存」。
    private var preview: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(question.isEmpty ? "（还没有题目）" : question)
                .font(.callout.weight(.medium))
                .fixedSize(horizontal: false, vertical: true)

            Text(answer.isEmpty ? "（还没有答案）" : answer)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var fields: some View {
        VStack(alignment: .leading, spacing: 10) {
            labeledEditor(
                title: "题目",
                text: $question,
                placeholder: "这张卡问什么？",
                limit: AnalysisValidator.Limits.questionMax,
                minHeight: 60
            )

            labeledEditor(
                title: "答案",
                text: $answer,
                placeholder: "答案写简短、能独立读懂。",
                limit: AnalysisValidator.Limits.answerMax,
                minHeight: 80
            )

            labeledEditor(
                title: "补充说明（可空）",
                text: $detail,
                placeholder: "易错点、出处。",
                limit: AnalysisValidator.Limits.detailMax,
                minHeight: 50
            )

            VStack(alignment: .leading, spacing: 4) {
                Text("标签")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TextField("用逗号分隔", text: $tagsText, axis: .vertical)
                    .font(.footnote)
                    .lineLimit(1...2)
                if !parsedTags.isEmpty {
                    TagChips(tags: parsedTags)
                }
            }

            Stepper(value: $difficulty, in: 1...5) {
                LabeledContent("难度", value: "\(difficulty) / 5")
                    .font(.footnote)
            }

            Stepper(value: $importance, in: 1...5) {
                LabeledContent("重要度", value: "\(importance) / 5")
                    .font(.footnote)
            }
        }
    }

    private func labeledEditor(
        title: String,
        text: Binding<String>,
        placeholder: String,
        limit: Int,
        minHeight: CGFloat
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(title)
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Spacer()

                Text("\(text.wrappedValue.count) / \(limit)")
                    .font(.caption2)
                    .monospacedDigit()
                    // 超限标红。.tertiary 是 ShapeStyle 不能与 Color 放进三目，
                    // 这里两边都用具体颜色（与分析/编辑面板保持同样的写法）。
                    .foregroundStyle(
                        text.wrappedValue.count > limit ? Color.red : Color.secondary
                    )
            }

            ZStack(alignment: .topLeading) {
                TextEditor(text: text)
                    .font(.footnote)
                    .frame(minHeight: minHeight)

                if text.wrappedValue.isEmpty {
                    Text(placeholder)
                        .font(.footnote)
                        .foregroundStyle(.tertiary)
                        .padding(.top, 8)
                        .padding(.leading, 5)
                        .allowsHitTesting(false)
                }
            }
        }
    }

    // MARK: 数据

    /// 把用户输入（中英文逗号、顿号、换行分隔）拆成标签，规则与 CardEditorView 一致。
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
}
