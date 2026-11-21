//
//  FlowTagRow.swift
//  PdfReview
//
//  自适应换行的标签行。TagChips 是横向滚动的单行，适合卡片内部；
//  牌组详情的「标签汇总」需要一次看全，所以这里做换行版本。
//

import SwiftUI

struct FlowTagRow: View {

    let tags: [String]
    var limit: Int = 12

    var body: some View {
        // iOS 17 的 Grid 只在固定列宽下换行，标签宽度不定，用 Layout 太重，
        // 这里用简单的分包策略：每行最多 3 个，够看且不会撑破行宽。
        let visible = Array(tags.prefix(limit))
        let rows = stride(from: 0, to: visible.count, by: 3).map { start in
            Array(visible[start..<min(start + 3, visible.count)])
        }

        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(rows.enumerated()), id: \.offset) { row in
                HStack(spacing: 6) {
                    ForEach(Array(row.element.enumerated()), id: \.offset) { item in
                        Text(item.element)
                            .font(.caption2)
                            .lineLimit(1)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(
                                Capsule(style: .continuous)
                                    .fill(Color.accentColor.opacity(0.12))
                            )
                            .foregroundStyle(Color.accentColor)
                    }
                    Spacer(minLength: 0)
                }
            }

            if tags.count > limit {
                Text("还有 \(tags.count - limit) 个标签")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
    }
}
