//
//  AskBubbleView.swift
//  PdfReview
//
//  提问页的两个气泡：用户在右、AI 在左。
//
//  为什么不用系统 Messages 那种对齐气泡：这里只有一轮问答，不需要「对话感」，
//  需要的是「读起来舒服」。AI 的回答可能有好几段，气泡太窄会读得很累，
//  所以 AI 那侧用整行宽的卡片，用户那侧才缩进靠右。
//

import SwiftUI
import UIKit

/// 用户提问的气泡（靠右、窄）。
struct AskQuestionBubble: View {

    let question: String

    var body: some View {
        HStack {
            Spacer(minLength: 40)

            Text(question)
                .font(.body)
                .foregroundStyle(.white)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(Color.accentColor)
                )
                .textSelection(.enabled)
        }
    }
}

/// AI 回答的卡片（整行宽、左对齐）。
struct AskAnswerCard: View {

    let answer: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("回答", systemImage: "sparkles")
                .font(.caption)
                .foregroundStyle(.secondary)

            Text(answer)
                .font(.body)
                .foregroundStyle(.primary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color(uiColor: .secondarySystemGroupedBackground))
        )
    }
}

/// AI 判断「值得做成卡片」时的理由条。
///
/// 理由要说出来 —— 用户如果不同意这个判断，至少知道自己被什么理由说服（或冒犯）了。
struct AskVerdictRow: View {

    let worthSaving: Bool
    let reason: String?

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: worthSaving ? "lightbulb.fill" : "info.circle")
                .foregroundStyle(worthSaving ? Color.orange : Color.secondary)
                .font(.footnote)

            VStack(alignment: .leading, spacing: 2) {
                Text(worthSaving ? "值得做成卡片" : "这次先不存成卡片")
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(worthSaving ? Color.orange : Color.secondary)

                if let reason, !reason.isEmpty {
                    Text(reason)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            Spacer(minLength: 0)
        }
        .padding(.vertical, 2)
    }
}
