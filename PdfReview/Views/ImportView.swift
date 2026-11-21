//
//  ImportView.swift
//  PdfReview
//
//  导入入口。两条完全不同的路径：
//   1. 选一份带文字层的 PDF → 抽取文本 → 交给 AI 逐块生成卡片 → 写入 SwiftData
//   2. 选一份已经分析好的 .pdfreview.json → 校验 → 直接写入
//
//  所有耗时工作交给 `ImportSession`（@MainActor ObservableObject），
//  视图只读它的状态、调它的方法，这样取消与进度都有唯一的数据源。
//

import SwiftUI
import UniformTypeIdentifiers

// MARK: - 导入会话

/// 导入流程的状态机。
///
/// 单独拿出来而不是塞进 View 的 @State，是因为 AI 分析要在 Task 里跑，
/// 进度回调又是 `@Sendable` 的——只有类才能安全地把回调里的值搬回主线程。
@MainActor
final class ImportSession: ObservableObject {

    enum Stage: Equatable {
        /// 还没开始选文件。
        case idle
        /// 正在解析 PDF 文本。
        case preparing
        /// PDF 已解析好，等用户确认要不要分析。
        case ready
        /// 正在请求 AI。
        case analyzing
        /// 全部完成。
        case done
        /// 失败，错误文案在 errorMessage。
        case failed
    }

    /// PDF 解析结果摘要，用于「准备好了，要不要开始」这一屏。
    struct PDFSummary: Equatable {
        var fileName: String
        var pageCount: Int
        var characterCount: Int
        var chunkCount: Int
    }

    @Published private(set) var stage: Stage = .idle
    @Published private(set) var summary: PDFSummary?
    /// 0...1 的分析进度，仅在 `.analyzing` 时有意义。
    @Published private(set) var progress: Double = 0
    @Published private(set) var errorMessage: String?
    /// 成功写入后的牌组信息。
    @Published private(set) var finishedDeckTitle: String = ""
    @Published private(set) var finishedCardCount: Int = 0

    /// 解析好的文本块，供分析使用。
    private var chunks: [TextChunk] = []
    /// 当前 PDF 的元信息。
    private var pdfPageCount: Int = 0
    private var pdfFileName: String = ""
    /// 分析任务，用于取消。
    private var analysisTask: Task<Void, Never>?

    // MARK: PDF

    /// 解析选中的 PDF。失败会切到 `.failed`。
    func preparePDF(url: URL) {
        reset()
        stage = .preparing
        pdfFileName = url.lastPathComponent

        // PDFKit 的解析是同步阻塞的，放到后台避免卡住主线程。
        Task { [weak self] in
            let result: Result<PDFTextExtractor.Extraction, Error> = await Task.detached(
                priority: .userInitiated
            ) {
                do {
                    return .success(try PDFTextExtractor.extract(from: url))
                } catch {
                    return .failure(error)
                }
            }.value

            guard let self else { return }

            switch result {
            case let .success(extraction):
                let chunks = PDFTextExtractor.chunk(extraction)
                self.pdfPageCount = extraction.pageCount

                guard extraction.hasTextLayer else {
                    self.stage = .failed
                    self.errorMessage = "这份 PDF 里没有可提取的文字（可能是扫描件），当前版本暂不支持 OCR。"
                    return
                }
                guard !chunks.isEmpty else {
                    self.stage = .failed
                    self.errorMessage = "这份 PDF 里没有找到可以分析的内容。"
                    return
                }

                self.chunks = chunks
                self.summary = PDFSummary(
                    fileName: url.lastPathComponent,
                    pageCount: extraction.pageCount,
                    characterCount: extraction.fullText.count,
                    chunkCount: chunks.count
                )
                self.stage = .ready

            case let .failure(error):
                self.stage = .failed
                self.errorMessage = AppFormat.message(for: error)
            }
        }
    }

    /// 开始分析。`title` 用文件名去掉扩展名，用户之后可以在牌组详情里改。
    func startAnalysis(title: String, settings: AppSettings, store: CardStore) {
        guard !chunks.isEmpty else {
            stage = .failed
            errorMessage = "没有可分析的文本内容，请重新选择 PDF。"
            return
        }

        let config: AIRequestConfig
        do {
            config = try settings.aiConfig()
        } catch {
            stage = .failed
            errorMessage = AppFormat.message(for: error)
            return
        }

        stage = .analyzing
        progress = 0
        errorMessage = nil

        let chunks = self.chunks
        let cardsPerChunk = settings.cardsPerChunk
        let pageCount = self.pdfPageCount
        let fileName = self.pdfFileName
        let client = AIClient()

        analysisTask?.cancel()
        analysisTask = Task { [weak self] in
            // 进度回调从 AI actor 的上下文里来，必须跳回主线程再写 @Published。
            // 注意这里只捕获 self 引用本身，不捕获任何视图状态（那是并发违规）；
            // self?.progress 的写入在 @MainActor 隔离的 Task 里完成。
            let onProgress: @Sendable (Double) -> Void = { [weak self] value in
                Task { @MainActor in
                    self?.progress = value
                }
            }

            do {
                let document = try await client.analyze(
                    chunks: chunks,
                    title: title,
                    config: config,
                    cardsPerChunk: cardsPerChunk,
                    progress: onProgress
                )

                try Task.checkCancellation()
                guard let self else { return }

                do {
                    try store.insertDeck(
                        title: document.deck.title,
                        sourceFileName: fileName,
                        sourceKind: "pdf",
                        pageCount: pageCount > 0 ? pageCount : document.source.pageCount,
                        summary: document.deck.summary,
                        language: document.deck.language,
                        cards: document.cards
                    )
                    self.progress = 1
                    self.finishedDeckTitle = document.deck.title
                    self.finishedCardCount = document.cards.count
                    self.stage = .done
                } catch {
                    self.stage = .failed
                    self.errorMessage = "卡片生成好了，但保存失败：\(AppFormat.message(for: error))"
                }
            } catch is CancellationError {
                self?.stage = .failed
                self?.errorMessage = "已取消分析。"
            } catch {
                self?.stage = .failed
                self?.errorMessage = AppFormat.message(for: error)
            }
        }
    }

    /// 取消进行中的分析。
    func cancel() {
        analysisTask?.cancel()
        analysisTask = nil
        if stage == .analyzing {
            stage = .failed
            errorMessage = "已取消分析。"
        }
    }

    /// 回到第一步。
    func reset() {
        analysisTask?.cancel()
        analysisTask = nil
        chunks = []
        pdfPageCount = 0
        pdfFileName = ""
        summary = nil
        progress = 0
        errorMessage = nil
        finishedDeckTitle = ""
        finishedCardCount = 0
        stage = .idle
    }

    /// 直接从文件导入。
    func importAnalysisFile(url: URL, store: CardStore) {
        reset()
        do {
            let imported = try AnalysisImporter.importDocument(from: url)
            let document = imported.document
            try store.insertDeck(
                title: document.deck.title,
                sourceFileName: imported.fileName,
                sourceKind: "imported",
                pageCount: document.source.pageCount,
                summary: document.deck.summary,
                language: document.deck.language,
                cards: document.cards
            )
            finishedDeckTitle = document.deck.title
            finishedCardCount = document.cards.count
            stage = .done
        } catch {
            stage = .failed
            errorMessage = AppFormat.message(for: error)
        }
    }
}

// MARK: - 导入界面

struct ImportView: View {

    @EnvironmentObject private var store: CardStore
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.dismiss) private var dismiss

    /// 由 RootView 注入：关掉导入面板并切到设置页。
    let onOpenSettings: () -> Void

    @StateObject private var session = ImportSession()

    /// 当前要弹出哪种选择器。
    ///
    /// 用一个枚举而不是两个 Bool：同一个视图上挂两个 `.sheet(isPresented:)`
    /// SwiftUI 只会生效其中一个，另一个静默失效——那种 bug 极难看出来。
    private enum PickerKind: String, Identifiable {
        case pdf
        case json
        var id: String { rawValue }
    }

    @State private var activePicker: PickerKind?

    /// 从「分享到本 App」送进来的文件。非 nil 时一进面板就直奔对应阶段。
    let prefilled: ImportInbox.Pending?

    init(prefilled: ImportInbox.Pending? = nil, onOpenSettings: @escaping () -> Void = { }) {
        self.prefilled = prefilled
        self.onOpenSettings = onOpenSettings
    }

    var body: some View {
        NavigationStack {
            Group {
                switch session.stage {
                case .idle:
                    chooserView
                case .preparing:
                    preparingView
                case .ready:
                    readyView
                case .analyzing:
                    ImportingView(
                        progress: session.progress,
                        onCancel: { session.cancel() }
                    )
                case .done:
                    finishedView
                case .failed:
                    failedView
                }
            }
            .navigationTitle("导入")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") {
                        session.cancel()
                        dismiss()
                    }
                }
            }
            // 选择器改用自写的 DocumentPicker（见 DocumentPicker.swift）。
            // 之前用 .fileImporter：选择器能弹出，但所有文件是灰的、点不中。
            // [.pdf]、[.pdf,.item]、[.pdf,.item,.data] 三种都试过，全无效。
            //
            // 用 .sheet(item:) 挂一个选择器、由 activePicker 决定弹出哪一种。
            // 不能挂两个 .sheet(isPresented:)：同一视图上 SwiftUI 只认第一个。
            .sheet(item: $activePicker) { kind in
                switch kind {
                case .pdf:
                    DocumentPicker { url in
                        session.preparePDF(url: url)
                    }
                case .json:
                    DocumentPicker { url in
                        session.importAnalysisFile(url: url, store: store)
                    }
                }
            }
            .task {
                // 分享进来的文件：一进面板就直奔对应阶段，用户不用再点一次。
                guard let prefilled else { return }
                switch prefilled.kind {
                case .pdf:
                    session.preparePDF(url: prefilled.url)
                case .analysis:
                    session.importAnalysisFile(url: prefilled.url, store: store)
                }
            }
        }
    }

    // MARK: 第一步：选择来源

    private var chooserView: some View {
        List {
            Section {
                Button {
                    if settings.isAIConfigured {
                        activePicker = .pdf
                    }
                } label: {
                    entry(
                        icon: "doc.text.magnifyingglass",
                        title: "从 PDF 生成卡片",
                        subtitle: settings.isAIConfigured
                            ? "选一份带文字层的 PDF，AI 会逐段提炼题目与答案。"
                            : "需要先配置 AI 服务才能使用。"
                    )
                }
                .disabled(!settings.isAIConfigured)

                Button {
                    activePicker = .json
                } label: {
                    entry(
                        icon: "square.and.arrow.down",
                        title: "导入 .pdfreview.json",
                        subtitle: "已经在别处分析好的文件，直接导入即可，不需要联网。"
                    )
                }
            }

            if !settings.isAIConfigured {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("还没配置 AI 服务", systemImage: "exclamationmark.circle")
                            .font(.subheadline.weight(.semibold))
                        Text("「从 PDF 生成卡片」需要 Base URL、模型名与 API Key。可以先跳过，直接导入现成的 .pdfreview.json。")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        Button("去设置") {
                            onOpenSettings()
                            dismiss()
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                    }
                    .padding(.vertical, 4)
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    private func entry(icon: String, title: String, subtitle: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.title2)
                .frame(width: 30)
                .foregroundStyle(.tint)

            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.body.weight(.medium))
                    .foregroundStyle(.primary)
                Text(subtitle)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
    }

    // MARK: 解析中

    private var preparingView: some View {
        VStack(spacing: 14) {
            ProgressView()
            Text("正在读取 PDF 文本…")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: 第二步：确认

    @ViewBuilder
    private var readyView: some View {
        List {
            if let summary = session.summary {
                Section("准备就绪") {
                    LabeledContent("文件") {
                        Text(summary.fileName)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    LabeledContent("页数", value: "\(summary.pageCount) 页")
                    LabeledContent("字数", value: "约 \(summary.characterCount) 字")
                    LabeledContent("分块", value: "\(summary.chunkCount) 块")
                }

                Section {
                    PrimaryButton(title: "开始分析") {
                        session.startAnalysis(
                            title: suggestedTitle(from: summary.fileName),
                            settings: settings,
                            store: store
                        )
                    }
                } footer: {
                    Text("每块会生成 \(settings.cardsPerChunk) 张卡片，共需请求 \(summary.chunkCount) 次，可能耗时几分钟。分析期间请保持 App 在前台。")
                }
            }

            Section {
                Button("重新选择文件") {
                    session.reset()
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    /// 用文件名（去扩展名）当默认牌组标题。
    private func suggestedTitle(from fileName: String) -> String {
        let stem = (fileName as NSString).deletingPathExtension
        let trimmed = stem.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "未命名牌组" : trimmed
    }

    // MARK: 完成

    @ViewBuilder
    private var finishedView: some View {
        List {
            Section {
                ContentUnavailableView {
                    Label("导入完成", systemImage: "checkmark.circle")
                } description: {
                    Text("「\(session.finishedDeckTitle)」已加入牌组，共 \(session.finishedCardCount) 张卡片。")
                } actions: {
                    Button("完成") {
                        dismiss()
                    }
                    .buttonStyle(.borderedProminent)
                }
                .listRowInsets(EdgeInsets(top: 20, leading: 12, bottom: 20, trailing: 12))
            }

            Section {
                Button("再导入一份") {
                    session.reset()
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    // MARK: 失败

    @ViewBuilder
    private var failedView: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 10) {
                    Label("没能完成导入", systemImage: "exclamationmark.triangle")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.orange)

                    Text(session.errorMessage ?? "未知错误。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.vertical, 4)
            }

            Section {
                Button("重试 / 重新选择") {
                    session.reset()
                }
                if !settings.isAIConfigured {
                    Button("去配置 AI 服务") {
                        onOpenSettings()
                        dismiss()
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }
}

// MARK: - 常量

/// 系统取消的错误码，用来区分「用户主动取消」与「真的出错」。
private let NSUserCancelledError = 3072
