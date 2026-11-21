//
//  TagChips.swift
//  PdfReview
//
//  标签行：把 [String] 渲染成一排圆角小胶囊，横向可滚动。
//  用于牌组详情与卡片编辑，避免长标签撑破行宽。
//

import SwiftUI

struct TagChips: View {

    let tags: [String]

    /// 最多展示几个，默认 8（与 `AnalysisValidator.Limits.tagsMax` 一致）。
    var limit: Int = 8

    var body: some View {
        if tags.isEmpty {
            EmptyView()
        } else {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(Array(tags.prefix(limit).enumerated()), id: \.offset) { item in
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
                }
                .padding(.vertical, 1)
            }
        }
    }
}
