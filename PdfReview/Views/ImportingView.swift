//
//  ImportingView.swift
//  PdfReview
//
//  分析进行中的界面。
//
//  这一屏要回答用户的三个问题：
//    1. 还在动吗？（环形进度 + 呼吸图标；只在百分比涨的话，模型某一块慢下来
//       十几秒，用户就以为卡死了）
//    2. 到哪一步了？（五步流程清单，当前步高亮、已完成打勾）
//    3. 真在产出东西吗？（卡片一张张翻入，题面露出一部分）
//
//  只负责展示，状态全部来自 ImportSession。取消不在这里直接调方法，
//  而是回调出去，保证「谁启动谁取消」。
//
//  动效全部尊重「减弱动态效果」：开了这个辅助功能就只保留淡入淡出，
//  否则缩放/翻入对晕动症用户是折磨。
//

import SwiftUI
// 用到 Color(uiColor:)，参数类型 UIColor 来自 UIKit。
// SwiftUI 在 iOS 上确实会 re-export 一部分 UIKit，但那是实现细节、
// 不是承诺；项目里其它用 uiColor 的文件也都显式 import 了 UIKit。
import UIKit

struct ImportingView: View {

    /// 分析进度详情。
    let progress: AnalysisProgress

    /// 已产出卡片的题面，按顺序累积，用于堆叠展示。
    let revealedQuestions: [String]

    let onCancel: () -> Void

    @State private var confirmCancel = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                header
                ringSection
                stepsSection
                if !previewQuestions.isEmpty {
                    questionsSection
                }
                cancelButton
            }
            .padding(.horizontal, 24)
            .padding(.top, 28)
            .padding(.bottom, 32)
            .frame(maxWidth: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .confirmationDialog(
            "取消分析？",
            isPresented: $confirmCancel,
            titleVisibility: .visible
        ) {
            Button("取消分析", role: .destructive) {
                onCancel()
            }
            Button("继续分析", role: .cancel) {}
        } message: {
            Text("已经生成的卡片不会被保存。")
        }
    }

    // MARK: 头部

    private var header: some View {
        VStack(spacing: 8) {
            Text("正在分析")
                .font(.title3.weight(.semibold))
            Text(headlineText)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .animation(.easeInOut(duration: 0.25), value: headlineText)
        }
    }

    // MARK: 环形进度

    private var ringSection: some View {
        ZStack {
            Circle()
                .stroke(Color.secondary.opacity(0.18), lineWidth: 10)

            Circle()
                .trim(from: 0, to: clampedFraction)
                .stroke(
                    Color.accentColor,
                    style: StrokeStyle(lineWidth: 10, lineCap: .round)
                )
                .rotationEffect(.degrees(-90))
                .animation(.easeInOut(duration: 0.45), value: clampedFraction)

            VStack(spacing: 2) {
                Text("\(percentText)")
                    .font(.system(size: 30, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .contentTransition(.numericText())
                    .animation(.easeInOut(duration: 0.3), value: percentText)

                if progress.chunkTotal > 0 {
                    Text("第 \(progress.chunkIndex) / \(progress.chunkTotal) 块")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
            }
        }
        .frame(width: 150, height: 150)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("分析进度 \(percentText)")
    }

    // MARK: 五步流程

    private var stepsSection: some View {
        VStack(spacing: 0) {
            ForEach(Array(Step.allCases.enumerated()), id: \.element) { index, step in
                StepRow(
                    title: step.title,
                    state: state(of: step),
                    isLast: index == Step.allCases.count - 1,
                    reduceMotion: reduceMotion
                )
            }
        }
        .padding(.vertical, 6)
    }

    // MARK: 卡片预览

    private var questionsSection: some View {
        VStack(spacing: 10) {
            HStack {
                Text("刚生成的卡片")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Text("共 \(progress.cardsSoFar) 张")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .contentTransition(.numericText())
                    .animation(.easeInOut(duration: 0.3), value: progress.cardsSoFar)
            }
            .padding(.horizontal, 4)

            // 只露最近 3 张：多了挤不下，也失去了「新的在最上面」的层次感。
            // reversed + 旋转 180 的那种技巧这里不用 —— 直接用 stack 顺序
            // 加 transition 更直观，而且过渡动画会自动只作用在新元素上。
            VStack(spacing: -8) {
                ForEach(Array(previewQuestions.enumerated()), id: \.offset) { index, question in
                    QuestionChip(question: question, depth: index)
                        .transition(
                            reduceMotion
                                ? .opacity
                                : .asymmetric(
                                    insertion: .move(edge: .bottom).combined(with: .opacity),
                                    removal: .opacity
                                )
                        )
                }
            }
            .animation(.spring(response: 0.42, dampingFraction: 0.78), value: previewQuestions)
        }
    }

    // MARK: 取消

    private var cancelButton: some View {
        Button(role: .cancel) {
            confirmCancel = true
        } label: {
            Text("取消")
                .frame(maxWidth: 200)
                .padding(.vertical, 10)
        }
        .buttonStyle(.bordered)
        .padding(.top, 8)
    }

    // MARK: 派生值

    private var clampedFraction: Double {
        min(1, max(0, progress.fraction))
    }

    private var percentText: String {
        "\(Int((clampedFraction * 100).rounded()))%"
    }

    /// 只取最近 3 张，并且倒序 —— 最新的排在视觉最前面。
    private var previewQuestions: [String] {
        Array(revealedQuestions.suffix(3).reversed())
    }

    private var headlineText: String {
        if clampedFraction <= 0 {
            return "正在把文本发给模型…"
        }
        if clampedFraction >= 1 {
            return "正在保存卡片…"
        }
        if progress.cardsSoFar > 0 {
            return "已生成 \(progress.cardsSoFar) 张卡片，请保持 App 在前台。"
        }
        return "请保持 App 在前台，离开后分析可能中断。"
    }

    // MARK: 步骤状态

    /// 什么时候算「某一步已完成」。
    ///
    /// 这里没有真实的分阶段回调 —— 分析开始前读取与分块早就做完了，
    /// 所以它们直接算完成；保存要等 `stage` 变 `.done`，而这一屏在
    /// 那时已经被切换掉了，于是靠 `fraction >= 1` 近似。宁可早一点
    /// 显示完成，也不要让最后一步永远空着引人怀疑。
    private func state(of step: Step) -> StepState {
        switch step {
        case .read, .split:
            return .done

        case .analyze:
            if clampedFraction >= 1 { return .done }
            return .active

        case .cards:
            // 真产出一张卡才算进到这一步；否则一直停在 pending，
            // 用户能看出「模型还没开始吐东西」和「已经在吐了」的区别。
            if clampedFraction >= 1 { return .done }
            return progress.cardsSoFar > 0 ? .active : .pending

        case .save:
            return clampedFraction >= 1 ? .active : .pending
        }
    }
}

// MARK: - 步骤定义
//
// 放在文件作用域而不是 ImportingView 内部：`private` 写在类型里只对
// 该类型自身可见，下面的 `StepRow` 是另一个顶层类型，看不到嵌套的
// private 成员。顶层 `private` 等价于 `fileprivate`，两边都能用。

private enum Step: Int, CaseIterable {
    case read
    case split
    case analyze
    case cards
    case save

    var title: String {
        switch self {
        case .read: return "读取 PDF 文本"
        case .split: return "按页拆分成块"
        case .analyze: return "逐块请求模型"
        case .cards: return "生成复习卡片"
        case .save: return "保存到本地"
        }
    }
}

// `.animation(_:value:)` 要求 value 是 Equatable。没有关联值的 enum
// 其实自动满足，但显式写出来，读代码的人不用去查这条规则。
private enum StepState: Equatable {
    case done
    case active
    case pending
}

// MARK: - 呼吸点

/// 当前步骤旁边那个会呼吸的小圆点。
///
/// 单独成一个 View 是为了让它有**自己的** @State：`repeatForever` 动画
/// 需要一个真实变化的值来触发，绑在父视图那个恒定的 `state` 上永远不会播。
private struct PulsingDot: View {

    let reduceMotion: Bool

    @State private var expanded = false

    var body: some View {
        ZStack {
            Circle()
                .stroke(Color.accentColor.opacity(0.3), lineWidth: 2)
                .frame(width: 18, height: 18)

            Circle()
                .fill(Color.accentColor)
                .frame(width: 7, height: 7)
                .scaleEffect(expanded ? 1.45 : 0.9)
                .opacity(expanded ? 0.65 : 1)
        }
        .frame(width: 18, height: 18)
        .onAppear {
            // 开了「减弱动态效果」就停在静止状态，别让晕动症用户受罪。
            guard !reduceMotion else { return }
            withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) {
                expanded = true
            }
        }
    }
}

// MARK: - 步骤行

private struct StepRow: View {

    let title: String
    let state: StepState
    let isLast: Bool
    let reduceMotion: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(spacing: 0) {
                indicator
                if !isLast {
                    Rectangle()
                        .fill(Color.secondary.opacity(0.22))
                        .frame(width: 2, height: 18)
                }
            }

            Text(title)
                .font(.subheadline)
                .foregroundStyle(textColor)
                .padding(.top, 3)

            Spacer(minLength: 0)
        }
        .animation(reduceMotion ? .easeInOut(duration: 0.2) : .spring(response: 0.35, dampingFraction: 0.8), value: state)
    }

    @ViewBuilder
    private var indicator: some View {
        switch state {
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 18))
                .foregroundStyle(Color.accentColor)
                .transition(.scale.combined(with: .opacity))

        case .active:
            // 呼吸点：靠自己的 @State 驱动，不能用 `.animation(..., value: state)`。
            // `state` 在这一行是常量（它就是 .active 才走到这个分支），
            // 绑定到它等于绑定一个永不变化的值，repeatForever 一次都不会播。
            PulsingDot(reduceMotion: reduceMotion)

        case .pending:
            Circle()
                .stroke(Color.secondary.opacity(0.35), lineWidth: 2)
                .frame(width: 18, height: 18)
        }
    }

    private var textColor: Color {
        switch state {
        case .done: return .primary
        case .active: return .primary
        case .pending: return .secondary
        }
    }
}

// MARK: - 题面小条

private struct QuestionChip: View {

    let question: String
    /// 0 是最新那张。越往后越暗、越窄，形成层次。
    let depth: Int

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "rectangle.on.rectangle.angled")
                .font(.caption)
                .foregroundStyle(.secondary)

            Text(shortQuestion)
                .font(.subheadline)
                .lineLimit(1)
                .truncationMode(.tail)
                .foregroundStyle(.primary)

            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .frame(maxWidth: .infinity)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color(uiColor: .secondarySystemGroupedBackground))
                .opacity(depth == 0 ? 1 : (depth == 1 ? 0.75 : 0.5))
        )
        .padding(.horizontal, CGFloat(depth) * 10)
    }

    /// 只露前十几个字。预览的作用是「让你相信有东西在产出」，
    /// 不是让你提前读卡片内容 —— 那样第一次复习就没意义了。
    private var shortQuestion: String {
        let trimmed = question.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.count <= 16 { return trimmed }
        return String(trimmed.prefix(16)) + "…"
    }
}
