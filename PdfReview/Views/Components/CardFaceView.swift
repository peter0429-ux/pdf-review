//
//  CardFaceView.swift
//  PdfReview
//
//  一张「可翻转」的卡片：默认只看题目，点一下展开答案与补充说明。
//  复习页与牌组详情页共用，保证两处的视觉与交互完全一致。
//
//  注意：本视图有私有 @State，所以显式写 init，否则合成的成员初始化器
//  是 private，别的文件构造不了。
//

import SwiftUI
import UIKit

struct CardFaceView: View {

    let question: String
    let answer: String
    let detail: String?
    let tags: [String]
    let sourcePage: Int?
    let header: String?

    /// 是否已展开答案。进入视图时总是收起的，避免一进来就被剧透。
    @State private var revealed = false

    init(
        question: String,
        answer: String,
        detail: String? = nil,
        tags: [String] = [],
        sourcePage: Int? = nil,
        header: String? = nil
    ) {
        self.question = question
        self.answer = answer
        self.detail = detail
        self.tags = tags
        self.sourcePage = sourcePage
        self.header = header
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let header, !header.isEmpty {
                Text(header)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Text(question)
                .font(.title3.weight(.semibold))
                .foregroundStyle(.primary)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)

            if revealed {
                Divider()

                Text(answer)
                    .font(.body)
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)

                if let detail, !detail.isEmpty {
                    Text(detail)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                Text("点一下看答案")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            if !tags.isEmpty {
                TagChips(tags: tags)
            }

            if let sourcePage {
                Text("第 \(sourcePage) 页")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color(uiColor: .secondarySystemGroupedBackground))
        )
        .contentShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .onTapGesture {
            withAnimation(.easeInOut(duration: 0.22)) {
                revealed.toggle()
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityHint(revealed ? "已显示答案" : "点两下显示答案")
    }
}
