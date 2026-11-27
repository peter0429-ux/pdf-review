//
//  AIClient.swift
//  PdfReview
//
//  OpenAI Chat Completions 兼容客户端。
//  面向「任意兼容服务」设计：只依赖 /chat/completions 这一条路径与最基础的请求体字段。
//

import Foundation

// MARK: - 配置

struct AIRequestConfig {
    var baseURL: URL
    var model: String
    var apiKey: String
}

// MARK: - 错误

enum AIError: LocalizedError {
    case missingConfiguration(String)
    case network(String)
    case http(Int, String)
    case invalidResponse(String)
    case decoding(String)
    case cancelled

    var errorDescription: String? {
        switch self {
        case let .missingConfiguration(message):
            return message
        case let .network(message):
            return "网络请求失败：\(message)"
        case let .http(code, body):
            let hint: String
            switch code {
            case 401: hint = "API Key 无效或已过期。"
            case 403: hint = "该 Key 没有访问此模型的权限。"
            case 404: hint = "接口路径或模型名不存在，请检查 Base URL 与模型名。"
            case 429: hint = "请求过于频繁或额度不足，请稍后再试。"
            case 500...599: hint = "服务端错误，请稍后重试。"
            default: hint = "服务返回异常。"
            }
            let snippet = body.count > 300 ? String(body.prefix(300)) + "…" : body
            return "\(hint)（HTTP \(code)）\n\(snippet)"
        case let .invalidResponse(message):
            return "模型返回内容无法解析：\(message)"
        case let .decoding(message):
            return "模型返回的 JSON 结构不符合格式要求：\(message)"
        case .cancelled:
            return "已取消。"
        }
    }
}

// MARK: - 进度

/// 分析进度。比单个 `Double` 多带三样东西，界面上「看到分析到哪一步」全靠它：
/// 当前第几块、共几块、已产出几张卡、以及最近几块的卡面用于翻入动画。
///
/// 之所以要带「已产出卡片」而不是只带数字：模型每块耗时差别很大，
/// 只涨百分比的话用户无法判断「是卡住了还是在干活」。看到卡片一张张
/// 冒出来，比任何进度条都更能说明它没死。
struct AnalysisProgress: Sendable, Equatable {

    /// 0...1，已经完成的块数占比。
    var fraction: Double

    /// 正在处理第几块（1 起）。已全部完成时等于 `chunkTotal`。
    var chunkIndex: Int

    /// 总块数。
    var chunkTotal: Int

    /// 到目前为止产出的卡片张数。
    var cardsSoFar: Int

    /// 最近完成的这一块产出的卡片题面，给界面的翻入动画用。
    /// 只放题面，不放答案与解析 —— 预览不该把内容全剧透。
    var recentQuestions: [String]

    /// 全部完成时的状态。
    static func finished(chunkTotal: Int, cards: Int) -> AnalysisProgress {
        AnalysisProgress(
            fraction: 1,
            chunkIndex: chunkTotal,
            chunkTotal: chunkTotal,
            cardsSoFar: cards,
            recentQuestions: []
        )
    }
}

// MARK: - 问答

/// 一次提问的结果。
///
/// 「回答」与「值不值得做成卡片」是两件独立的事：用户问的往往是个具体疑惑，
/// 而卡片必须是能自测的题。所以要分别给，不能用「worthSaving == false 就连回答都没有」
/// 这种设计 —— 用户至少该拿到答案。
struct AskResult: Sendable, Equatable {

    /// 直接回答用户问题的正文。
    var answer: String

    /// AI 判断这个知识点值不值得做成复习卡片。
    var worthSaving: Bool

    /// 判断理由，一句话。可能为 nil。
    var reason: String?

    /// 卡片草稿。`worthSaving == true` 时应当有；解析失败时为 nil，
    /// 界面据此退化成「只显示回答，不给保存按钮」。
    var draft: AnalysisDocument.CardItem?
}

// MARK: - 客户端

actor AIClient {

    private let session: URLSession

    init() {
        let configuration = URLSessionConfiguration.default
        // 单块分析可能较慢，给足超时
        configuration.timeoutIntervalForRequest = 120
        configuration.timeoutIntervalForResource = 300
        configuration.waitsForConnectivity = true
        session = URLSession(configuration: configuration)
    }

    // MARK: 主流程

    /// 分析整份文档：逐块请求后合并成一份 `AnalysisDocument`。
    func analyze(
        chunks: [TextChunk],
        title: String,
        config: AIRequestConfig,
        cardsPerChunk: Int,
        progress: @Sendable @escaping (AnalysisProgress) -> Void
    ) async throws -> AnalysisDocument {

        guard !chunks.isEmpty else {
            throw AIError.invalidResponse("没有可分析的文本内容。")
        }

        var collected: [AnalysisDocument.CardItem] = []
        let total = chunks.count
        let perChunk = min(12, max(3, cardsPerChunk))

        // 第一块开始前先报一次 0%，界面才不会空着等第一块回来。
        progress(
            AnalysisProgress(
                fraction: 0,
                chunkIndex: 1,
                chunkTotal: total,
                cardsSoFar: 0,
                recentQuestions: []
            )
        )

        for chunk in chunks {
            try Task.checkCancellation()

            let items = try await analyzeChunk(
                chunk,
                documentTitle: title,
                config: config,
                cardCount: perChunk
            )
            collected.append(contentsOf: items)

            progress(
                AnalysisProgress(
                    fraction: Double(chunk.index + 1) / Double(total),
                    chunkIndex: chunk.index + 1,
                    chunkTotal: total,
                    cardsSoFar: collected.count,
                    recentQuestions: items.map(\.question)
                )
            )

            // 卡片总量保护
            if collected.count >= AnalysisValidator.Limits.cardsMax {
                collected = Array(collected.prefix(AnalysisValidator.Limits.cardsMax))
                break
            }
        }

        let deduped = Self.deduplicate(collected)
        guard !deduped.isEmpty else {
            throw AIError.invalidResponse("模型没有生成任何有效卡片，请检查文档内容或更换模型。")
        }

        var document = AnalysisDocument(
            schemaVersion: AnalysisDocument.supportedVersion,
            generator: "PdfReview/1.0",
            generatedAt: Self.iso8601Now(),
            source: AnalysisDocument.Source(
                fileName: "\(title).pdf",
                pageCount: chunks.map(\.pageRange.upperBound).max() ?? 0,
                sha256: nil
            ),
            deck: AnalysisDocument.Deck(
                title: title,
                summary: nil,
                language: "zh-Hans"
            ),
            cards: deduped
        )
        document.deck.summary = "共 \(deduped.count) 张卡片，覆盖第 1 至 \(document.source.pageCount) 页。"
        return document
    }

    // MARK: 问答

    /// 就一份牌组里的内容提问。
    ///
    /// - Parameters:
    ///   - question: 用户原话。
    ///   - deckTitle: 牌组标题，给模型一个「在问哪份资料」的锚点。
    ///   - context: 牌组原文（可能已被截断）。传空串表示没有原文，
    ///     此时模型只能凭 `cardsDigest` 或通用知识回答，界面应提示用户。
    ///   - cardsDigest: 已有卡片的题面摘要，原文缺失时作为替代上下文。
    func ask(
        question: String,
        deckTitle: String,
        context: String,
        cardsDigest: [String],
        config: AIRequestConfig
    ) async throws -> AskResult {

        let trimmedQuestion = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedQuestion.isEmpty else {
            throw AIError.invalidResponse("请先输入问题。")
        }

        var lastError: Error?

        for attempt in 0..<2 {
            do {
                return try await performAskRequest(
                    question: trimmedQuestion,
                    deckTitle: deckTitle,
                    context: context,
                    cardsDigest: cardsDigest,
                    config: config,
                    temperature: attempt == 0 ? 0.4 : 0.2
                )
            } catch let error as AIError {
                lastError = error
                switch error {
                case .missingConfiguration, .cancelled:
                    throw error
                case .http(401, _), .http(403, _), .http(404, _):
                    throw error
                default:
                    continue
                }
            } catch is CancellationError {
                throw AIError.cancelled
            } catch {
                lastError = error
                continue
            }
        }

        throw lastError ?? AIError.invalidResponse("提问失败，请稍后再试。")
    }

    private func performAskRequest(
        question: String,
        deckTitle: String,
        context: String,
        cardsDigest: [String],
        config: AIRequestConfig,
        temperature: Double
    ) async throws -> AskResult {

        let systemPrompt = """
        你是一位耐心的学科答疑老师，同时负责判断哪些问答值得沉淀成复习卡片。

        你必须**先完整回答**用户的问题，再**单独判断**这个知识点值不值得做成卡片。
        两件事互不依赖：即使不值得做卡片，回答也必须给全。

        什么样的问题值得做成卡片：
        - 问的是一个可复用的知识（概念、原理、公式、易错点），不是「这段文字怎么读」这类一次性疑问。
        - 换一个人、换一天再问，答案仍然成立。
        - 答案能独立读懂，不需要再翻回原文。

        什么样的问题不值得：
        - 只是在问某个文件的操作方法、页码、格式。
        - 答案严重依赖本次对话的上下文，脱离后无法理解。
        - 问题本身有歧义、或你无法确定答案。

        卡片的题目必须改写成**能自测的疑问句或填空句**，不要照抄用户原话。
        例如用户问「什么是循环引用」，卡片的题目应该是「ARC 下什么情况会造成循环引用？」而不是「什么是循环引用」。
        改写后仍要能回答用户原本的困惑。

        只用简体中文输出。只输出一个 JSON 对象，不要 Markdown 代码块，不要任何解释文字。
        """

        // 上下文缺失时的降级：告诉模型「你只有卡片题面」，别让它假装读过原文。
        let contextBlock: String
        if !context.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            contextBlock = """
            资料原文（可能已被截断）：
            ---
            \(context)
            ---
            """
        } else if !cardsDigest.isEmpty {
            let digest = cardsDigest.prefix(60).map { "- \($0)" }.joined(separator: "\n")
            contextBlock = """
            注意：这份资料没有保存原文，你只能看到已有卡片的题面。
            回答时如果缺乏依据，请直说「资料里没有这部分内容」，不要编造。

            已有卡片的题面：
            \(digest)
            """
        } else {
            contextBlock = """
            注意：这份资料既没有原文也没有卡片，请仅凭通用知识回答，
            并在回答里提醒用户这条回答不是基于他的资料。
            """
        }

        let userPrompt = """
        资料标题：\(deckTitle)

        \(contextBlock)

        用户的问题：
        \(question)

        严格按以下 JSON 结构输出：

        {
          "answer": "对用户问题的完整回答",
          "worthSaving": true 或 false,
          "reason": "一句话说明为什么值得/不值得做成卡片",
          "card": {
            "question": "改写成能自测的疑问句或填空句",
            "answer": "卡片背面的答案，简洁且可独立阅读",
            "detail": "可选的补充说明或易错点，没有就给 null",
            "tags": ["标签1", "标签2"],
            "difficulty": 1到5的整数,
            "importance": 1到5的整数
          }
        }

        worthSaving 为 false 时，card 给 null。
        worthSaving 为 true 时，card 必须有 question 与 answer。
        """

        let body: [String: Any] = [
            "model": config.model,
            "temperature": temperature,
            "max_tokens": 4000,
            "response_format": ["type": "json_object"],
            "messages": [
                ["role": "system", "content": systemPrompt],
                ["role": "user", "content": userPrompt]
            ]
        ]

        let data = try await postChatCompletion(body: body, config: config)
        return try Self.decodeAskResult(from: data)
    }

    /// 从 Chat Completions 响应里解析出问答结果。
    static func decodeAskResult(from responseData: Data) throws -> AskResult {

        guard
            let root = try? JSONSerialization.jsonObject(with: responseData) as? [String: Any]
        else {
            throw AIError.invalidResponse("响应不是合法 JSON。")
        }

        if let errorObject = root["error"] as? [String: Any],
           let message = errorObject["message"] as? String {
            throw AIError.invalidResponse("服务返回错误：\(message)")
        }

        guard
            let choices = root["choices"] as? [[String: Any]],
            let first = choices.first,
            let message = first["message"] as? [String: Any],
            let content = message["content"] as? String
        else {
            throw AIError.invalidResponse("响应里没有 choices[0].message.content。")
        }

        let cleaned = stripCodeFence(content)
        guard let contentData = cleaned.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: contentData) as? [String: Any]
        else {
            throw AIError.decoding("模型输出的内容不是 JSON 对象。")
        }

        guard let answer = (object["answer"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
            !answer.isEmpty
        else {
            throw AIError.decoding("模型没有给出回答。")
        }

        // worthSaving 可能是 Bool，也可能是 "true"/"false" 字符串（部分模型如此）。
        let worthSaving = boolValue(object["worthSaving"])

        // reason 可能缺失或为空白串，两种情况都归一成 nil。
        let reasonText = (object["reason"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let reason: String? = (reasonText?.isEmpty == false) ? reasonText : nil

        // 草稿解析：拆成单张卡走已有的 parseCards，保证字段截断规则与分析流程一致。
        // parseCards 在「全部缺 question/answer」时会抛错——这里正是想要的效果，
        // 让 worthSaving 退化成 false，而不是给一张空卡。
        var draft: AnalysisDocument.CardItem?
        if worthSaving, let rawCard = object["card"] as? [String: Any] {
            draft = (try? parseCards([rawCard]))?.first
        }

        // 模型说值得、却给不出可用的卡：按不值得处理，别让用户点了保存才发现是空卡。
        let effectiveWorthSaving = worthSaving && draft != nil

        return AskResult(
            answer: answer,
            worthSaving: effectiveWorthSaving,
            reason: reason,
            draft: effectiveWorthSaving ? draft : nil
        )
    }

    /// JSON 里的布尔可能是 Bool，也可能是字符串或数字。
    private static func boolValue(_ any: Any?) -> Bool {
        if let bool = any as? Bool { return bool }
        if let number = any as? NSNumber { return number.boolValue }
        if let string = any as? String {
            return ["true", "yes", "1", "是"].contains(string.lowercased())
        }
        return false
    }

    // MARK: 单块请求

    /// 分析一个文本块。失败时自动重试一次（降低 max_tokens 与温度）。
    private func analyzeChunk(
        _ chunk: TextChunk,
        documentTitle: String,
        config: AIRequestConfig,
        cardCount: Int
    ) async throws -> [AnalysisDocument.CardItem] {

        var lastError: Error?

        for attempt in 0..<2 {
            do {
                return try await performChunkRequest(
                    chunk,
                    documentTitle: documentTitle,
                    config: config,
                    cardCount: cardCount,
                    temperature: attempt == 0 ? 0.3 : 0.1
                )
            } catch let error as AIError {
                lastError = error
                // 配置类与取消类错误重试没有意义
                switch error {
                case .missingConfiguration, .cancelled:
                    throw error
                case .http(401, _), .http(403, _), .http(404, _):
                    throw error
                default:
                    continue
                }
            } catch is CancellationError {
                throw AIError.cancelled
            } catch {
                lastError = error
                continue
            }
        }

        throw lastError ?? AIError.invalidResponse("第 \(chunk.index + 1) 块分析失败。")
    }

    private func performChunkRequest(
        _ chunk: TextChunk,
        documentTitle: String,
        config: AIRequestConfig,
        cardCount: Int,
        temperature: Double
    ) async throws -> [AnalysisDocument.CardItem] {

        let pageLabel = chunk.pageRange.lowerBound == chunk.pageRange.upperBound
            ? "第 \(chunk.pageRange.lowerBound) 页"
            : "第 \(chunk.pageRange.lowerBound)–\(chunk.pageRange.upperBound) 页"

        let systemPrompt = """
        你是一位严谨的复习卡片编写者。用户会给你一份文档的片段，你要从中提炼可供自测的知识点。

        规则：
        1. 每张卡片只考一个知识点，题目必须能在原文中找到明确依据。
        2. 题目用疑问句或填空题形式，避免「请简述」这类过于宽泛的问法。
        3. 答案要简洁、可独立阅读，不要出现「如上文所述」这类指代。
        4. 忽略目录、页眉页脚、参考文献列表、封面等无学习价值的内容。
        5. 只用简体中文输出。
        6. 只输出一个 JSON 对象，不要 Markdown 代码块，不要任何解释文字。
        """

        let userPrompt = """
        文档标题：\(documentTitle)
        本片段位置：\(pageLabel)

        请生成 \(cardCount) 张复习卡片，严格按以下 JSON 结构输出：

        {
          "cards": [
            {
              "question": "题目文本",
              "answer": "答案文本",
              "detail": "可选的补充说明，没有就给 null",
              "tags": ["标签1", "标签2"],
              "sourcePage": 该知识点所在页码（整数，依据片段位置估算）,
              "difficulty": 1到5的整数，表示难度,
              "importance": 1到5的整数，表示重要程度
            }
          ]
        }

        文档片段如下：
        ---
        \(chunk.text)
        ---
        """

        let body: [String: Any] = [
            "model": config.model,
            "temperature": temperature,
            "max_tokens": 3000,
            "response_format": ["type": "json_object"],
            "messages": [
                ["role": "system", "content": systemPrompt],
                ["role": "user", "content": userPrompt]
            ]
        ]

        let data = try await postChatCompletion(
            body: body,
            config: config
        )

        return try Self.decodeCards(from: data)
    }

    // MARK: HTTP

    private func postChatCompletion(
        body: [String: Any],
        config: AIRequestConfig
    ) async throws -> Data {

        let endpoint = config.baseURL.appendingPathComponent("chat/completions")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(config.apiKey)", forHTTPHeaderField: "Authorization")

        do {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        } catch {
            throw AIError.network("请求体构造失败：\(error.localizedDescription)")
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch is CancellationError {
            throw AIError.cancelled
        } catch let error as URLError {
            if error.code == .cancelled { throw AIError.cancelled }
            throw AIError.network(error.localizedDescription)
        } catch {
            throw AIError.network(error.localizedDescription)
        }

        guard let http = response as? HTTPURLResponse else {
            throw AIError.invalidResponse("未收到有效的 HTTP 响应。")
        }

        guard (200...299).contains(http.statusCode) else {
            let text = String(data: data, encoding: .utf8) ?? ""
            throw AIError.http(http.statusCode, text)
        }

        return data
    }

    // MARK: 解析

    /// 从 Chat Completions 响应里取出 content，再解析成卡片数组。
    static func decodeCards(from responseData: Data) throws -> [AnalysisDocument.CardItem] {
        // 第一层：取 choices[0].message.content
        guard
            let root = try? JSONSerialization.jsonObject(with: responseData) as? [String: Any]
        else {
            throw AIError.invalidResponse("响应不是合法 JSON。")
        }

        if let errorObject = root["error"] as? [String: Any],
           let message = errorObject["message"] as? String {
            throw AIError.invalidResponse("服务返回错误：\(message)")
        }

        guard
            let choices = root["choices"] as? [[String: Any]],
            let first = choices.first,
            let message = first["message"] as? [String: Any],
            let content = message["content"] as? String
        else {
            throw AIError.invalidResponse("响应里没有 choices[0].message.content。")
        }

        // 第二层：content 本身应是 JSON 对象
        let cleaned = stripCodeFence(content)
        guard let contentData = cleaned.data(using: .utf8) else {
            throw AIError.decoding("模型输出不是 UTF-8 文本。")
        }

        // 兼容部分模型把数组直接放在顶层的情况
        if let array = try? JSONSerialization.jsonObject(with: contentData) as? [[String: Any]] {
            return try parseCards(array)
        }

        guard let object = try? JSONSerialization.jsonObject(with: contentData) as? [String: Any] else {
            throw AIError.decoding("模型输出的内容不是 JSON 对象。")
        }

        guard let rawCards = object["cards"] as? [[String: Any]] else {
            throw AIError.decoding("JSON 中缺少 cards 数组。")
        }

        return try parseCards(rawCards)
    }

    private static func parseCards(_ rawCards: [[String: Any]]) throws -> [AnalysisDocument.CardItem] {
        var result: [AnalysisDocument.CardItem] = []

        for raw in rawCards {
            guard
                let question = (raw["question"] as? String)?
                    .trimmingCharacters(in: .whitespacesAndNewlines),
                let answer = (raw["answer"] as? String)?
                    .trimmingCharacters(in: .whitespacesAndNewlines),
                !question.isEmpty, !answer.isEmpty
            else {
                continue   // 跳过残缺条目，不因为一张坏卡放弃整块
            }

            let detail = (raw["detail"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            let tags = (raw["tags"] as? [Any])?
                .compactMap { $0 as? String }
                .prefix(AnalysisValidator.Limits.tagsMax)

            let sourcePage = intValue(raw["sourcePage"])
            let difficulty = intValue(raw["difficulty"])
            let importance = intValue(raw["importance"])

            result.append(
                AnalysisDocument.CardItem(
                    question: String(question.prefix(AnalysisValidator.Limits.questionMax)),
                    answer: String(answer.prefix(AnalysisValidator.Limits.answerMax)),
                    detail: detail.flatMap { $0.isEmpty ? nil : String($0.prefix(AnalysisValidator.Limits.detailMax)) },
                    tags: tags.map(Array.init),
                    sourcePage: sourcePage.flatMap { $0 >= 1 ? $0 : nil },
                    difficulty: difficulty.map(ReviewCard.clampScore),
                    importance: importance.map(ReviewCard.clampScore)
                )
            )
        }

        guard !result.isEmpty else {
            throw AIError.decoding("模型返回的卡片全部缺少题目或答案。")
        }
        return result
    }

    /// JSON 里的数字可能是 Int、Double 或 String，统一转 Int。
    private static func intValue(_ any: Any?) -> Int? {
        if let int = any as? Int { return int }
        if let double = any as? Double { return Int(double) }
        if let number = any as? NSNumber { return number.intValue }
        if let string = any as? String { return Int(string) }
        return nil
    }

    /// 去掉可能出现的 ```json 围栏。
    private static func stripCodeFence(_ text: String) -> String {
        var trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("```") else { return trimmed }

        // 去掉首行围栏
        if let firstNewline = trimmed.firstIndex(of: "\n") {
            trimmed = String(trimmed[trimmed.index(after: firstNewline)...])
        } else {
            return trimmed.replacingOccurrences(of: "```", with: "")
        }
        // 去掉结尾围栏
        if let range = trimmed.range(of: "```", options: .backwards) {
            trimmed = String(trimmed[trimmed.startIndex..<range.lowerBound])
        }
        return trimmed.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    // MARK: 去重

    /// 按归一化题面去重，保留先出现的那张。
    private static func deduplicate(_ items: [AnalysisDocument.CardItem]) -> [AnalysisDocument.CardItem] {
        var seen = Set<String>()
        var result: [AnalysisDocument.CardItem] = []

        for item in items {
            let key = normalizeForComparison(item.question)
            if seen.insert(key).inserted {
                result.append(item)
            }
        }
        return result
    }

    private static func normalizeForComparison(_ text: String) -> String {
        let stripped = text
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: "\u{3000}", with: "")
            .replacingOccurrences(of: "？", with: "?")
            .lowercased()
        return stripped
    }

    private static func iso8601Now() -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withColonSeparatorInTimeZone]
        return formatter.string(from: Date())
    }
}
