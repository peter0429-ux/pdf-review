//
//  PdfReviewWidget.swift
//  PdfReviewWidget
//
//  Widget 配置入口。
//

import SwiftUI
import WidgetKit

struct PdfReviewWidget: Widget {

    static let kind = "PdfReviewWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: Self.kind, provider: RotationProvider()) { entry in
            RotationEntryView(entry: entry)
        }
        .configurationDisplayName("PDF 复习卡片")
        .description("每 3 小时自动轮换一张复习卡片")
        .supportedFamilies([
            .systemSmall,
            .systemMedium,
            .systemLarge,
            .accessoryRectangular,
            .accessoryInline
        ])
    }
}
