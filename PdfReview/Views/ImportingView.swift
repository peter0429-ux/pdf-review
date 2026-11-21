//
//  ImportingView.swift
//  PdfReview
//
//  分析进行中的界面：进度条 + 阶段说明 + 取消按钮。
//
//  只负责展示，状态全部来自 ImportSession。取消不在这里直接调方法，
//  而是回调出去，保证「谁启动谁取消」。
//

import SwiftUI

struct ImportingView: View {

    /// 0...1。
    let progress: Double

    let onCancel: () -> Void

    @State private var confirmCancel = false

    var body: some View {
        VStack(spacing: 22) {
            Spacer(minLength: 20)

            Image(systemName: "sparkles")
                .font(.system(size: 42))
                .foregroundStyle(.tint)
                .symbolEffect(.pulse, options: .repeating)

            VStack(spacing: 8) {
                Text("正在分析")
                    .font(.title3.weight(.semibold))
                Text(stageText)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 28)
            }

            VStack(spacing: 8) {
                ProgressView(value: clampedProgress)
                    .progressViewStyle(.linear)
                    .padding(.horizontal, 32)

                Text(percentText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }

            Spacer(minLength: 12)

            Button(role: .cancel) {
                confirmCancel = true
            } label: {
                Text("取消")
                    .frame(maxWidth: 200)
                    .padding(.vertical, 10)
            }
            .buttonStyle(.bordered)
            .padding(.bottom, 24)
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

    // MARK: 文案

    private var clampedProgress: Double {
        min(1, max(0, progress))
    }

    private var percentText: String {
        "\(Int((clampedProgress * 100).rounded()))%"
    }

    private var stageText: String {
        if clampedProgress <= 0 {
            return "正在把文本发给模型…"
        }
        if clampedProgress >= 1 {
            return "正在保存卡片…"
        }
        return "已经完成大约 \(Int((clampedProgress * 100).rounded()))%，请保持 App 在前台。"
    }
}
