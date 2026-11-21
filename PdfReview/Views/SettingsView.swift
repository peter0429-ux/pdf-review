//
//  SettingsView.swift
//  PdfReview
//
//  「设置」页：AI 配置（Base URL / 模型 / API Key）、轮换参数、数据管理。
//
//  与 AppSettings 的对应关系：
//   - baseURLString / model 直接双向绑定到 @Published 字段，didSet 自动落盘
//   - apiKey 是计算属性（走 Keychain），所以用本地 @State 镜像 + onChange 写回，
//     避免每敲一个字符就写一次钥匙串
//   - rotationIntervalHours / cardsPerSlot 改动后要同步到 RotationCache，
//     这个同步在 CardStore.refreshRotationCache() 里做，这里只负责调
//

import SwiftUI
import Combine

struct SettingsView: View {

    @EnvironmentObject private var store: CardStore
    @EnvironmentObject private var settings: AppSettings

    // MARK: 本地镜像状态

    /// Keychain 不能和普通 UserDefaults 字段一样双向绑定，用本地镜像过渡。
    @State private var apiKeyDraft: String = ""

    /// 提交后的轻提示。
    @State private var toast: String?

    /// 防抖任务：停顿 600ms 后才把草稿写进 Keychain。
    @State private var keyDebounce: AnyCancellable?

    // MARK: Body

    var body: some View {
        NavigationStack {
            Form {
                aiSection
                rotationSection
                dataSection
                aboutSection
            }
            .navigationTitle("设置")
            .onAppear { apiKeyDraft = settings.apiKey }
            .onDisappear { keyDebounce?.cancel() }
            .background(
                toastView
            )
        }
    }

    // MARK: AI 配置

    private var aiSection: some View {
        Section {
            LabeledContent("状态") {
                Text(settings.isAIConfigured ? "已就绪" : "未配置")
                    .foregroundStyle(settings.isAIConfigured ? .green : .secondary)
            }

            TextField("https://api.openai.com/v1", text: $settings.baseURLString)
                .keyboardType(.URL)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.plain)

            TextField("gpt-4o-mini", text: $settings.model)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.plain)

            SecureField("sk-...", text: $apiKeyDraft)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .onChange(of: apiKeyDraft) { _, newValue in
                    scheduleKeyWrite(newValue)
                }

            LabeledContent("连接测试") {
                Button("发送一条测试消息") {
                    toast = "连接测试功能开发中，可先保存后到「导入」页试用。"
                }
                .buttonStyle(.borderless)
                .font(.subheadline)
            }

        } header: {
            Text("AI 配置（OpenAI 兼容接口）")
        } footer: {
            Text("Base URL 填到 /v1 这一层即可。兼容 DeepSeek、Moonshot、通义、OpenRouter 等所有 OpenAI 格式的服务。")
        }
    }

    /// 600ms 防抖，避免每个按键都写一次 Keychain。
    private func scheduleKeyWrite(_ value: String) {
        keyDebounce?.cancel()
        keyDebounce = Timer.publish(every: 0.6, on: .main, in: .common)
            .autoconnect()
            .sink { _ in
                settings.apiKey = value.trimmingCharacters(in: .whitespacesAndNewlines)
                keyDebounce?.cancel()
            }
    }

    // MARK: 轮换

    private var rotationSection: some View {
        Section {
            LabeledContent("轮换间隔") {
                Text(AppFormat.intervalText(settings.rotationIntervalHours))
                    .monospacedDigit()
            }

            Slider(value: $settings.rotationIntervalHours,
                   in: 0.25...24, step: 0.25) {
                Text("轮换间隔（小时）")
            }

            Stepper(value: $settings.cardsPerSlot, in: 1...10) {
                LabeledContent("每轮展示张数") {
                    Text("\(settings.cardsPerSlot) 张").monospacedDigit()
                }
            }

            Stepper(value: $settings.cardsPerChunk, in: 3...12) {
                LabeledContent("AI 每次生成") {
                    Text("\(settings.cardsPerChunk) 张").monospacedDigit()
                }
            }
        } header: {
            Text("轮换节奏")
        } footer: {
            Text("改完间隔或张数后，桌面小组件会在几分钟内自动换到新节奏。")
        }
        .onChange(of: settings.rotationIntervalHours) { _, _ in
            store.refreshRotationCache()
        }
        .onChange(of: settings.cardsPerSlot) { _, _ in
            store.refreshRotationCache()
        }
    }

    // MARK: 数据

    private var dataSection: some View {
        Section {
            LabeledContent("牌组数") {
                Text("\(store.allDecks().count)").monospacedDigit()
            }
            LabeledContent("卡片总数") {
                Text("\(store.rotatableCards().count)").monospacedDigit()
            }

            NavigationLink("导出与分享") {
                ExportListView()
            }
        } header: {
            Text("数据")
        }
    }

    // MARK: 关于

    private var aboutSection: some View {
        Section {
            LabeledContent("版本") {
                Text("1.0").monospacedDigit()
            }
            LabeledContent("分析文件格式") {
                Text("pdfreview.json v1.0")
            }
        } header: {
            Text("关于")
        }
    }

    // MARK: Toast

    @ViewBuilder
    private var toastView: some View {
        if let toast {
            VStack {
                Spacer()
                Text(toast)
                    .font(.footnote)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .background(.thinMaterial, in: Capsule())
                    .padding(.bottom, 24)
            }
            .allowsHitTesting(false)
        }
    }
}

// MARK: - 导出列表

/// 「导出与分享」页：列出所有牌组，逐个导出为 .pdfreview.json。
/// 真正的分享动作走 ShareSheetView（UIActivityViewController）。
struct ExportListView: View {

    @EnvironmentObject private var store: CardStore

    /// 当前正在分享的临时文件。非 nil 时弹分享面板。
    /// Identifiable 包装让 sheet(item:) 可用，也符合 ShareSheetView 注释里的
    /// 「先生成再分享」用法。
    @State private var sharingFile: SharedFile?

    /// 分享目标的轻包装。
    private struct SharedFile: Identifiable {
        let url: URL
        var id: String { url.absoluteString }
    }

    var body: some View {
        List {
            if store.allDecks().isEmpty {
                ContentUnavailableView {
                    Label("没有可导出的牌组", systemImage: "square.and.arrow.up")
                } description: {
                    Text("先导入一份分析文件，或用 AI 分析一个 PDF。")
                }
            } else {
                ForEach(store.allDecks()) { deck in
                    Button {
                        export(deck)
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(deck.title)
                                    .foregroundStyle(.primary)
                                Text("\(deck.sortedCards.count) 张卡片")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "square.and.arrow.up")
                                .foregroundStyle(.tint)
                        }
                    }
                }
            }
        }
        .navigationTitle("导出与分享")
        .sheet(item: $sharingFile) { file in
            ShareSheetView(url: file)
        }
    }

    private func export(_ deck: ReviewDeck) {
        do {
            let document = try makeAnalysisDocument(for: deck)
            let file = try AnalysisImporter.writeTemporaryFile(document)
            sharingFile = SharedFile(url: file)
        } catch {
            sharingFile = nil
            store.reportError("导出失败：\(AppFormat.message(for: error))")
        }
    }

    /// 把牌组还原成 AnalysisDocument，供导出/再次导入。
    ///
    /// 构造的 document 必须能通过 AnalysisValidator 校验，否则导出的文件
    /// 连自家导入都拒绝。generator 置 nil（这是本 App 导出的特征，便于
    /// 区分外部工具生成的文件），generatedAt 用带时区的当前时间。
    private func makeAnalysisDocument(for deck: ReviewDeck) throws -> AnalysisDocument {
        let cards = deck.sortedCards.map { card in
            AnalysisDocument.CardItem(
                question: card.question,
                answer: card.answer,
                detail: card.detail,
                tags: card.tags.isEmpty ? nil : card.tags,
                sourcePage: card.sourcePage,
                difficulty: card.difficulty,
                importance: card.importance
            )
        }
        let document = AnalysisDocument(
            schemaVersion: AnalysisDocument.supportedVersion,
            generator: nil,
            generatedAt: ISO8601DateFormatter().string(from: Date()),
            source: AnalysisDocument.Source(
                fileName: deck.sourceFileName ?? deck.title,
                pageCount: deck.pageCount,
                sha256: nil
            ),
            deck: AnalysisDocument.Deck(
                title: deck.title,
                summary: deck.summary,
                language: deck.language
            ),
            cards: cards
        )
        try AnalysisValidator.validate(document)
        return document
    }
}
