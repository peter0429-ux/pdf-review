//
//  OnboardingView.swift
//  PdfReview
//
//  首次启动引导。只说清楚三件事：这个 App 干什么、卡片怎么来、AI 需要自己填 Key。
//  不做分页轮播，一屏讲完，按钮点掉就把 hasCompletedOnboarding 置为 true。
//

import SwiftUI

struct OnboardingView: View {

    @EnvironmentObject private var settings: AppSettings
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    header

                    VStack(alignment: .leading, spacing: 16) {
                        featureRow(
                            icon: "doc.text.magnifyingglass",
                            title: "把 PDF 变成卡片",
                            message: "选一份带文字层的 PDF，AI 会逐段提炼题目与答案。"
                        )
                        featureRow(
                            icon: "rectangle.on.rectangle.angled",
                            title: "按轮换自动换卡",
                            message: "每几小时换一张，具体间隔可以在「设置」里改。"
                        )
                        featureRow(
                            icon: "square.grid.2x2",
                            title: "放到桌面随时看",
                            message: "添加「PDF 复习」小组件，点亮屏幕就能看到当前这张卡。"
                        )
                    }

                    Divider()

                    VStack(alignment: .leading, spacing: 8) {
                        Text("关于 AI 服务")
                            .font(.subheadline.weight(.semibold))
                        Text("需要你在「设置」里填写自己的 OpenAI 兼容接口地址、模型名与 API Key。App 不内置任何账号，也不会把你的内容发到别处。")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }

                    PrimaryButton(title: "开始使用") {
                        settings.hasCompletedOnboarding = true
                        dismiss()
                    }
                    .padding(.top, 4)
                }
                .padding(20)
            }
            .navigationTitle("欢迎使用")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    // MARK: 片段

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            Image(systemName: "rectangle.stack.fill")
                .font(.system(size: 40))
                .foregroundStyle(.tint)

            Text("把 PDF 变成每天能看两眼的小卡片")
                .font(.title2.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)

            Text("不用整篇重读，让一张卡片提醒你重点在哪里。")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func featureRow(icon: String, title: String, message: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.title3)
                .frame(width: 30, alignment: .center)
                .foregroundStyle(.tint)

            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Text(message)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
