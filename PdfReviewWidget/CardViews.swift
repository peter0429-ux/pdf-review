//
//  CardViews.swift
//  PdfReviewWidget
//
//  小组件各尺寸的界面。所有视图都只依赖 RotationEntry 里的数据，
//  不读 cache、不读 SwiftData，因此 placeholder / Preview / 真实时间线共用同一套代码。
//

import AppIntents
import Foundation
import SwiftUI
import UIKit
import WidgetKit

// MARK: - 入口视图

/// 按 widgetFamily 分派到对应布局。
struct RotationEntryView: View {

    @Environment(\.widgetFamily) private var family

    let entry: RotationEntry

    var body: some View {
        // 锁屏（accessory*）尺寸不用 containerBackground，由系统提供底色；
        // 桌面尺寸才铺一层 .secondarySystemGroupedBackground。
        if isLockScreenFamily {
            content
        } else {
            content.containerBackground(for: .widget) { background }
        }
    }

    private var isLockScreenFamily: Bool {
        switch family {
        case .accessoryInline, .accessoryRectangular, .accessoryCircular:
            return true
        default:
            return false
        }
    }

    @ViewBuilder
    private var content: some View {
        switch family {
        case .accessoryInline:
            AccessoryInlineView(entry: entry)
        case .accessoryRectangular:
            AccessoryRectangularView(entry: entry)
        case .accessoryCircular:
            AccessoryCircularView(entry: entry)
        case .systemSmall:
            SmallCardView(entry: entry)
        case .systemMedium:
            MediumCardView(entry: entry)
        case .systemLarge:
            LargeCardView(entry: entry)
        case .systemExtraLarge:
            LargeCardView(entry: entry)
        @unknown default:
            SmallCardView(entry: entry)
        }
    }

    /// 深色模式自适应：全部走系统语义色。
    private var background: Color {
        Color(uiColor: .secondarySystemGroupedBackground)
    }
}

// MARK: - 空态

/// 统一的空态视图：没有 cache 或卡片池为空时使用。
///
/// 文案分两种：签名缺 App Groups 时，App 写的数据小组件读不到，若还说
/// 「在 App 中导入 PDF 后即可」用户会一直等一个不会发生的事。
struct EmptyStateView: View {

    var compact: Bool = false
    /// 是否因为签名缺 App Groups 而读不到共享数据。
    var sharedDataUnavailable: Bool = false

    var body: some View {
        VStack(spacing: compact ? 6 : 10) {
            Image(systemName: sharedDataUnavailable ? "exclamationmark.triangle" : "doc.badge.plus")
                .font(.system(size: compact ? 24 : 34, weight: .regular))
                .foregroundStyle(.secondary)

            Text(message)
                .font(compact ? .caption2 : .footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .lineLimit(4)
                .minimumScaleFactor(0.85)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, 4)
    }

    private var message: String {
        if sharedDataUnavailable {
            return "小组件读不到共享数据：当前签名缺少 App Groups 能力。改用带 App Groups 的签名后即可显示你导入的 PDF。"
        }
        return "在 App 中导入 PDF 后即可在此复习"
    }
}

// MARK: - systemSmall

struct SmallCardView: View {

    let entry: RotationEntry

    var body: some View {
        if let card = entry.current {
            VStack(alignment: .leading, spacing: 6) {
                header(card: card)

                Text(card.question)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
                    .lineLimit(3)
                    .minimumScaleFactor(0.9)

                maskedAnswer(card.answer)

                Spacer(minLength: 0)

                Text(entry.rotationRemainingText)
                    .font(.caption2)
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        } else {
            // entry.current 为 nil 有两种可能：真没导入过，或签名缺 App Groups
            // 导致读不到 App 写的缓存。后者要靠 source 区分，否则用户会一直
            // 等着一个不会出现的卡片。
            EmptyStateView(compact: true, sharedDataUnavailable: entry.source == .bundledSeed)
        }
    }

    private func header(card: CardSnapshot) -> some View {
        HStack(spacing: 4) {
            Text(card.deckTitle)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)

            Spacer(minLength: 2)

            FavoriteButton(card: card, compact: true)
            NextCardButton(compact: true)
        }
    }

    /// 答案默认收起：模糊显示 + 提示点按打开 App 查看。
    private func maskedAnswer(_ answer: String) -> some View {
        ZStack(alignment: .leading) {
            Text(answer)
                .font(.caption)
                .lineLimit(2)
                .blur(radius: 6)
                .accessibilityHidden(true)

            HStack(spacing: 2) {
                Image(systemName: "lock.fill")
                    .font(.system(size: 8, weight: .semibold))
                Text("点按查看答案")
                    .font(.caption2.weight(.medium))
            }
            .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - systemMedium

struct MediumCardView: View {

    let entry: RotationEntry

    var body: some View {
        if let card = entry.current {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 4) {
                        Text(card.deckTitle)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)

                        Spacer(minLength: 2)

                        FavoriteButton(card: card, compact: true)
                        NextCardButton(compact: true)
                    }

                    Text(card.question)
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(3)
                        .minimumScaleFactor(0.9)

                    Text(card.answer)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)

                    Spacer(minLength: 0)

                    Text(entry.rotationRemainingText)
                        .font(.caption2)
                        .monospacedDigit()
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                }
                .frame(maxWidth: .infinity, alignment: .topLeading)

                Divider()

                HistoryColumn(cards: entry.history, limit: 3)
                    .frame(width: 118, alignment: .topLeading)
            }
        } else {
            EmptyStateView(sharedDataUnavailable: entry.source == .bundledSeed)
        }
    }
}

// MARK: - systemLarge / systemExtraLarge

struct LargeCardView: View {

    let entry: RotationEntry

    var body: some View {
        if let card = entry.current {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 6) {
                    Text(card.deckTitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)

                    Spacer(minLength: 4)

                    FavoriteButton(card: card, compact: false)
                    NextCardButton(compact: false)
                }

                Text(card.question)
                    .font(.title3.weight(.semibold))
                    .lineLimit(4)

                Text(card.answer)
                    .font(.callout)
                    .foregroundStyle(.primary)
                    .lineLimit(6)

                if let detail = card.detail, !detail.isEmpty {
                    Text(detail)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }

                if !card.tags.isEmpty {
                    TagRow(tags: card.tags, limit: 3)
                }

                Divider()

                HistoryList(cards: entry.history, limit: 3)

                Spacer(minLength: 0)

                ProgressFooter(entry: entry)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        } else {
            EmptyStateView(sharedDataUnavailable: entry.source == .bundledSeed)
        }
    }
}

// MARK: - accessoryRectangular

struct AccessoryRectangularView: View {

    let entry: RotationEntry

    var body: some View {
        if let card = entry.current {
            VStack(alignment: .leading, spacing: 2) {
                Text(card.deckTitle)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)

                Text(card.question)
                    .font(.headline)
                    .lineLimit(2)
                    .minimumScaleFactor(0.9)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        } else {
            VStack(alignment: .leading, spacing: 2) {
                Text("PDF 复习卡片")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text("在 App 中导入 PDF 后即可在此复习")
                    .font(.headline)
                    .lineLimit(2)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        }
    }
}

// MARK: - accessoryInline

struct AccessoryInlineView: View {

    let entry: RotationEntry

    var body: some View {
        // Inline 只能渲染单行 Text / Label。
        Label {
            Text(inlineText)
        } icon: {
            Image(systemName: "doc.text")
        }
    }

    private var inlineText: String {
        guard let card = entry.current else {
            return "在 App 中导入 PDF 后即可在此复习"
        }
        let question = card.question.trimmingCharacters(in: .whitespacesAndNewlines)
        return question.isEmpty ? card.deckTitle : question
    }
}

// MARK: - accessoryCircular

/// 契约里没有要求，但 supportedFamilies 之外也可能被系统请求，兜底成一个圆形进度样式。
struct AccessoryCircularView: View {

    let entry: RotationEntry

    var body: some View {
        ZStack {
            AccessoryWidgetBackground()

            VStack(spacing: 1) {
                Image(systemName: "doc.text")
                    .font(.system(size: 13, weight: .semibold))
                Text(entry.current == nil ? "添加" : "复习")
                    .font(.system(size: 9, weight: .medium))
                    .lineLimit(1)
            }
        }
    }
}

// MARK: - 子视图

/// 「下一张」按钮：执行 NextCardIntent，不打开 App。
struct NextCardButton: View {

    var compact: Bool

    var body: some View {
        Button(intent: NextCardIntent()) {
            Image(systemName: "arrow.triangle.2.circlepath")
                .font(.system(size: compact ? 11 : 13, weight: .semibold))
                .foregroundStyle(Color.accentColor)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text("下一张"))
    }
}

/// 「收藏 / 取消收藏」按钮：执行 ToggleFavoriteIntent。
struct FavoriteButton: View {

    let card: CardSnapshot
    var compact: Bool

    var body: some View {
        Button(intent: ToggleFavoriteIntent(cardID: card.id.uuidString)) {
            Image(systemName: card.isFavorite ? "heart.fill" : "heart")
                .font(.system(size: compact ? 11 : 13, weight: .semibold))
                .foregroundStyle(card.isFavorite ? Color.red : Color.secondary)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(card.isFavorite ? "取消收藏" : "收藏"))
    }
}

/// systemMedium 右侧的「历史回顾」竖列。
struct HistoryColumn: View {

    let cards: [CardSnapshot]
    let limit: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("历史回顾")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)

            if cards.isEmpty {
                Text("暂无记录")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            } else {
                ForEach(Array(cards.prefix(limit))) { card in
                    VStack(alignment: .leading, spacing: 1) {
                        Text(card.deckTitle)
                            .font(.system(size: 9))
                            .foregroundStyle(.tertiary)
                            .lineLimit(1)
                        Text(card.question)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
            }

            Spacer(minLength: 0)
        }
        .frame(maxHeight: .infinity, alignment: .topLeading)
    }
}

/// systemLarge 里的「历史回顾」列表。
struct HistoryList: View {

    let cards: [CardSnapshot]
    let limit: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("历史回顾")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            if cards.isEmpty {
                Text("暂无历史记录")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            } else {
                ForEach(Array(cards.prefix(limit))) { card in
                    HStack(spacing: 6) {
                        Image(systemName: "clock")
                            .font(.system(size: 9))
                            .foregroundStyle(.tertiary)

                        VStack(alignment: .leading, spacing: 0) {
                            Text(card.question)
                                .font(.caption)
                                .lineLimit(1)
                            Text(card.deckTitle)
                                .font(.system(size: 9))
                                .foregroundStyle(.tertiary)
                                .lineLimit(1)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// systemLarge 底部的进度信息。
struct ProgressFooter: View {

    let entry: RotationEntry

    var body: some View {
        HStack(spacing: 6) {
            Text("共 \(entry.totalCards) 张")
                .font(.caption2)
                .monospacedDigit()
                .foregroundStyle(.secondary)

            if entry.upcomingCount > 0 {
                Text("· 后续还有 \(entry.upcomingCount) 张")
                    .font(.caption2)
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 2)

            if entry.source == .bundledSeed {
                // 内置内容时明确告知：这些不是用户导入的 PDF，换一份签名才会变。
                Label("内置", systemImage: "shippingbox")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .labelStyle(.titleAndIcon)
            }

            Text(entry.rotationRemainingText)
                .font(.caption2)
                .monospacedDigit()
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// 标签行。
struct TagRow: View {

    let tags: [String]
    let limit: Int

    var body: some View {
        HStack(spacing: 4) {
            ForEach(Array(tags.prefix(limit)), id: \.self) { tag in
                Text(tag)
                    .font(.system(size: 9))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 2)
                    .background(
                        Capsule().fill(Color(uiColor: .tertiarySystemFill))
                    )
            }
        }
        .lineLimit(1)
    }
}

// MARK: - 倒计时文案

extension RotationEntry {

    /// 「3 小时一换 · 剩余 x 分钟」。
    /// 以轮换起点（slotStart）为锚点计算，避免首个 entry 的 date 取「现在」导致倒计时偏大。
    var rotationRemainingText: String {
        let interval = intervalHours.isFinite && intervalHours > 0 ? intervalHours : 3
        let intervalText = Self.formatInterval(interval)
        let end = rotationAnchor.addingTimeInterval(interval * 3600)
        let remaining = end.timeIntervalSince(date)

        if !remaining.isFinite || remaining <= 0 {
            return "\(intervalText)一换 · 即将轮换"
        }

        let minutes = max(1, Int((remaining / 60).rounded(.up)))
        return "\(intervalText)一换 · 剩余 \(minutes) 分钟"
    }

    private static func formatInterval(_ hours: Double) -> String {
        if hours == hours.rounded() {
            return "\(Int(hours)) 小时"
        }
        return String(format: "%.1f 小时", hours)
    }
}

// MARK: - 预览数据

extension CardSnapshot {

    /// 预览/占位用的样例卡片。
    static let preview = CardSnapshot(
        id: UUID(uuidString: "11111111-1111-4111-8111-111111111111") ?? UUID(),
        deckID: UUID(uuidString: "22222222-2222-4222-8222-222222222222") ?? UUID(),
        deckTitle: "分布式系统",
        question: "什么是 CAP 定理？实际系统中该如何取舍？",
        answer: "一致性、可用性、分区容错三者最多同时满足两个；分区不可避免，所以真实系统在 CP 与 AP 之间取舍。",
        detail: "常见做法是按业务分级：账户余额走 CP，商品浏览走 AP。",
        tags: ["理论", "面试"],
        sourcePage: 12,
        isFavorite: true
    )

    static let previewAlt = CardSnapshot(
        id: UUID(uuidString: "33333333-3333-4333-8333-333333333333") ?? UUID(),
        deckID: UUID(uuidString: "22222222-2222-4222-8222-222222222222") ?? UUID(),
        deckTitle: "系统设计",
        question: "一致性哈希为什么需要虚拟节点？",
        answer: "为了缓解数据倾斜：少量物理节点容易分布不均，虚拟节点让负载更平均，节点增减时迁移量也更小。",
        detail: nil,
        tags: ["架构"],
        sourcePage: 34,
        isFavorite: false
    )

    static let previewThird = CardSnapshot(
        id: UUID(uuidString: "44444444-4444-4444-8444-444444444444") ?? UUID(),
        deckID: UUID(uuidString: "55555555-5555-4555-8555-555555555555") ?? UUID(),
        deckTitle: "算法",
        question: "快速排序的平均与最坏时间复杂度分别是多少？",
        answer: "平均 O(n log n)，最坏 O(n²)；随机化选择枢轴可让最坏情况几乎不出现。",
        detail: nil,
        tags: ["排序"],
        sourcePage: 8,
        isFavorite: false
    )

    /// 历史回顾用的样例数据（按时间倒序）。
    static let previewHistory: [CardSnapshot] = [previewAlt, previewThird]
}

extension RotationEntry {

    /// 预览/占位用的样例 entry，8 个预排内的任意一轮都长得一样。
    static let previewEntry = RotationEntry(
        date: Date(),
        current: CardSnapshot.preview,
        history: CardSnapshot.previewHistory,
        upcomingCount: 5,
        totalCards: 24,
        intervalHours: 3,
        slotStart: Date().addingTimeInterval(-20 * 60)
    )

    /// 空池时的样例 entry。
    static let previewEmpty = RotationEntry(
        date: Date(),
        current: nil,
        history: [],
        upcomingCount: 0,
        totalCards: 0
    )
}

// MARK: - Previews

#Preview(as: .systemSmall) {
    PdfReviewWidget()
} timeline: {
    RotationEntry.previewEntry
}

#Preview(as: .systemMedium) {
    PdfReviewWidget()
} timeline: {
    RotationEntry.previewEntry
}

#Preview(as: .systemLarge) {
    PdfReviewWidget()
} timeline: {
    RotationEntry.previewEntry
}

#Preview(as: .accessoryRectangular) {
    PdfReviewWidget()
} timeline: {
    RotationEntry.previewEntry
}

#Preview(as: .systemSmall) {
    PdfReviewWidget()
} timeline: {
    RotationEntry.previewEmpty
}
