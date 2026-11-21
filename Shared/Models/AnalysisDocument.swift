//
//  AnalysisDocument.swift
//  PdfReview
//
//  `.pdfreview.json` 交换格式（v1）的内存表示。
//  既是 AI 分析的输出结构，也是离线导入的输入结构——两者完全等价。
//  字段定义必须与 schema/analysis.v1.schema.json 保持一致。
//

import Foundation

// MARK: - 顶层

struct AnalysisDocument: Codable {

    /// 格式版本。当前只接受 "1.0"，校验规则见 AnalysisValidator。
    var schemaVersion: String

    /// 生成工具标识，如 "PdfReview/1.0"、"manual"、"chatgpt"。
    var generator: String?

    /// 生成时间，ISO 8601 字符串。
    var generatedAt: String

    /// 来源信息。
    var source: Source

    /// 牌组信息。
    var deck: Deck

    /// 卡片列表，1...500 张。
    var cards: [CardItem]

    /// 当前支持的版本。
    static let supportedVersion = "1.0"

    /// 文件后缀。
    static let fileExtension = "pdfreview.json"

    /// 单文件体积上限（8 MB）。
    static let maxFileBytes = 8 * 1024 * 1024

    struct Source: Codable {
        var fileName: String
        var pageCount: Int
        var sha256: String?
    }

    struct Deck: Codable {
        var title: String
        var summary: String?
        var language: String?
    }

    struct CardItem: Codable {
        var question: String
        var answer: String
        var detail: String?
        var tags: [String]?
        var sourcePage: Int?
        var difficulty: Int?
        var importance: Int?
    }
}

// MARK: - 校验

/// 导入校验。所有错误都给出可读的中文描述，直接展示给用户。
enum AnalysisValidator {

    enum ValidationError: Error, LocalizedError {
        case unreadableFile(String)
        case fileTooLarge(Int)
        case invalidJSON(String)
        case unsupportedVersion(String)
        case missingField(String)
        case emptyCards
        case tooManyCards(Int)
        case fieldTooLong(field: String, index: Int, max: Int)
        case fieldEmpty(field: String, index: Int)
        case outOfRange(field: String, index: Int, min: Int, max: Int)
        case invalidPage(index: Int)
        case tooManyTags(index: Int, max: Int)
        case duplicateTag(index: Int, tag: String)
        case unknownField(String)
        case invalidTimestamp(String)
        case metadataTooLong(field: String, max: Int)

        var errorDescription: String? {
            switch self {
            case let .unreadableFile(name):
                return "无法读取文件「\(name)」。请确认它存在且可访问。"
            case let .fileTooLarge(bytes):
                let mb = Double(bytes) / 1024 / 1024
                return String(format: "文件过大（%.1f MB），上限为 8 MB。", mb)
            case let .invalidJSON(detail):
                return "JSON 格式有误：\(detail)"
            case let .unsupportedVersion(version):
                return "不支持的文件版本「\(version)」，本 App 只支持 \(AnalysisDocument.supportedVersion)。"
            case let .missingField(name):
                return "缺少必填字段：\(name)。"
            case .emptyCards:
                return "文件里没有任何卡片。"
            case let .tooManyCards(count):
                return "卡片数量 \(count) 张，超过上限 500 张。"
            case let .fieldTooLong(field, index, max):
                return "第 \(index + 1) 张卡片的 \(field) 超过 \(max) 字。"
            case let .fieldEmpty(field, index):
                return "第 \(index + 1) 张卡片的 \(field) 不能为空。"
            case let .outOfRange(field, index, min, max):
                return "第 \(index + 1) 张卡片的 \(field) 必须在 \(min)...\(max) 之间。"
            case let .invalidPage(index):
                return "第 \(index + 1) 张卡片的页码必须大于等于 1。"
            case let .tooManyTags(index, max):
                return "第 \(index + 1) 张卡片的标签超过 \(max) 个。"
            case let .duplicateTag(index, tag):
                return "第 \(index + 1) 张卡片的标签「\(tag)」重复了。"
            case let .unknownField(name):
                return "出现了格式里没有定义的字段：\(name)。"
            case let .invalidTimestamp(value):
                return "生成时间「\(value)」不是合法的 ISO 8601 时间，"
                    + "应形如 2026-11-21T10:00:00+08:00（必须带时区）。"
            case let .metadataTooLong(field, max):
                return "\(field) 超过 \(max) 字的上限。"
            }
        }
    }

    /// 字段长度限制，集中定义，与 schema 一致。
    /// 改任何一个数字都必须同步改 schema/analysis.v1.schema.json 与
    /// docs/pdf-analysis-format.md；scripts/check_format_consistency.py 会核对。
    enum Limits {
        static let questionMax = 500
        static let answerMax = 2000
        static let detailMax = 2000
        static let tagsMax = 8
        static let tagLengthMax = 32
        static let cardsMax = 500
        /// 牌组标题上限。必须与 schema/analysis.v1.schema.json 里
        /// deck.title.maxLength 保持一致。
        static let titleMax = 200
        /// 可选的牌组摘要上限。
        static let summaryMax = 2000
        /// 可选的生成工具标识上限。
        static let generatorMax = 128
    }

    /// 校验已解码的文档。抛出 `ValidationError`。
    static func validate(_ document: AnalysisDocument) throws {
        // 版本
        let trimmedVersion = document.schemaVersion.trimmingCharacters(in: .whitespaces)
        guard trimmedVersion == AnalysisDocument.supportedVersion else {
            throw ValidationError.unsupportedVersion(document.schemaVersion)
        }

        // 生成时间必须能被解析——字段本身是字符串，但写错了就是坏数据，
        // 后面按日期排序/去重时才会莫名其妙出错，不如现在拦住。
        guard Self.isISO8601(document.generatedAt) else {
            throw ValidationError.invalidTimestamp(document.generatedAt)
        }

        // 可选字段的长度上限：schema 里声明了，这里也得执行，
        // 否则「照文档写合法、App 却拒收」或反过来的裂缝会出现。
        if let generator = document.generator, generator.count > Limits.generatorMax {
            throw ValidationError.metadataTooLong(field: "generator", max: Limits.generatorMax)
        }
        if let summary = document.deck.summary, summary.count > Limits.summaryMax {
            throw ValidationError.metadataTooLong(field: "deck.summary", max: Limits.summaryMax)
        }

        // 牌组标题
        let title = document.deck.title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else {
            throw ValidationError.missingField("deck.title")
        }
        guard title.count <= Limits.titleMax else {
            throw ValidationError.fieldTooLong(field: "牌组标题", index: 0, max: Limits.titleMax)
        }

        // 卡片数量
        guard !document.cards.isEmpty else { throw ValidationError.emptyCards }
        guard document.cards.count <= Limits.cardsMax else {
            throw ValidationError.tooManyCards(document.cards.count)
        }

        // 逐张校验
        for (index, card) in document.cards.enumerated() {
            let question = card.question.trimmingCharacters(in: .whitespacesAndNewlines)
            let answer = card.answer.trimmingCharacters(in: .whitespacesAndNewlines)

            guard !question.isEmpty else {
                throw ValidationError.fieldEmpty(field: "题目(question)", index: index)
            }
            guard !answer.isEmpty else {
                throw ValidationError.fieldEmpty(field: "答案(answer)", index: index)
            }
            guard question.count <= Limits.questionMax else {
                throw ValidationError.fieldTooLong(field: "题目", index: index, max: Limits.questionMax)
            }
            guard answer.count <= Limits.answerMax else {
                throw ValidationError.fieldTooLong(field: "答案", index: index, max: Limits.answerMax)
            }
            if let detail = card.detail, detail.count > Limits.detailMax {
                throw ValidationError.fieldTooLong(field: "补充说明", index: index, max: Limits.detailMax)
            }

            let tags = card.tags ?? []
            guard tags.count <= Limits.tagsMax else {
                throw ValidationError.tooManyTags(index: index, max: Limits.tagsMax)
            }
            var seenTags = Set<String>()
            for tag in tags {
                guard tag.count <= Limits.tagLengthMax else {
                    throw ValidationError.fieldTooLong(field: "标签", index: index, max: Limits.tagLengthMax)
                }
                guard !tag.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                    throw ValidationError.fieldEmpty(field: "标签", index: index)
                }
                guard seenTags.insert(tag).inserted else {
                    throw ValidationError.duplicateTag(index: index, tag: tag)
                }
            }

            if let page = card.sourcePage, page < 1 {
                throw ValidationError.invalidPage(index: index)
            }
            if let difficulty = card.difficulty, !(1...5).contains(difficulty) {
                throw ValidationError.outOfRange(field: "难度", index: index, min: 1, max: 5)
            }
            if let importance = card.importance, !(1...5).contains(importance) {
                throw ValidationError.outOfRange(field: "重要度", index: index, min: 1, max: 5)
            }
        }
    }

    // MARK: - 时间戳

    /// 判断字符串是否是合法 ISO 8601 时间。要求带时区，与 schema 的 pattern 一致。
    ///
    /// 兼容 `2026-11-21T10:00:00Z`、`2026-11-21T10:00:00+08:00`、
    /// `2026-11-21T10:00:00.123+08:00` 三种写法。
    static func isISO8601(_ string: String) -> Bool {
        let formatter = ISO8601DateFormatter()
        if formatter.date(from: string) != nil { return true }

        // ISO8601DateFormatter 默认不认小数秒，换带选项的再试一次
        formatter.formatOptions = [
            .withInternetDateTime, .withFractionalSeconds,
        ]
        return formatter.date(from: string) != nil
    }
}

// MARK: - 编解码

extension AnalysisDocument {

    /// 从文件 URL 读取并校验。
    static func load(from url: URL) throws -> AnalysisDocument {
        let needsRelease = url.startAccessingSecurityScopedResource()
        defer {
            if needsRelease { url.stopAccessingSecurityScopedResource() }
        }

        let data: Data
        do {
            data = try Data(contentsOf: url)
        } catch {
            throw AnalysisValidator.ValidationError.unreadableFile(url.lastPathComponent)
        }

        guard data.count <= maxFileBytes else {
            throw AnalysisValidator.ValidationError.fileTooLarge(data.count)
        }

        let document = try decode(data)
        try AnalysisValidator.validate(document)
        return document
    }

    /// 从 Data 解码。把 DecodingError 翻译成可读中文。
    ///
    /// 解码前先做一遍键名白名单检查：手写 JSON 时把 `question` 拼成
    /// `questoin`，若只依赖 Codable，这个字段会被静默丢弃（Codable 对
    /// 未知键不报错），导入"成功"了但卡片是空的——比直接报错难查得多。
    static func decode(_ data: Data) throws -> AnalysisDocument {
        try checkUnknownFields(in: data)

        let decoder = JSONDecoder()
        do {
            return try decoder.decode(AnalysisDocument.self, from: data)
        } catch let error as DecodingError {
            throw AnalysisValidator.ValidationError.invalidJSON(Self.describe(error))
        } catch {
            throw AnalysisValidator.ValidationError.invalidJSON(error.localizedDescription)
        }
    }

    /// 编码成适合分享的 JSON（人类可读、键名排序稳定）。
    func encoded() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }

    /// 把 DecodingError 转成带字段路径的中文说明。
    private static func describe(_ error: DecodingError) -> String {
        switch error {
        case let .keyNotFound(key, context):
            return "缺少字段「\(key.stringValue)」，位置：\(path(context.codingPath))"
        case let .typeMismatch(_, context):
            return "字段类型不正确，位置：\(path(context.codingPath))"
        case let .valueNotFound(_, context):
            return "字段值为空，位置：\(path(context.codingPath))"
        case let .dataCorrupted(context):
            let reason = context.debugDescription
            return "数据损坏，位置：\(path(context.codingPath))（\(reason)）"
        @unknown default:
            return "未知的解析错误"
        }
    }

    private static func path(_ codingPath: [CodingKey]) -> String {
        guard !codingPath.isEmpty else { return "根对象" }
        return codingPath.map(\.stringValue).joined(separator: ".")
    }

    // MARK: - 未知字段检查

    /// 各层的合法键名。必须与 schema/analysis.v1.schema.json 的
    /// properties 列表逐一字面一致——改这里就要同步改 schema 和格式文档。
    private enum KnownKeys {
        static let root: Set<String> = [
            "schemaVersion", "generator", "generatedAt", "source", "deck", "cards",
        ]
        static let source: Set<String> = ["fileName", "pageCount", "sha256"]
        static let deck: Set<String> = ["title", "summary", "language"]
        static let card: Set<String> = [
            "question", "answer", "detail", "tags", "sourcePage", "difficulty", "importance",
        ]
    }

    /// 扫一遍 JSON，遇到白名单之外的键就报错。任何语法/结构问题都只是
    /// 静默跳过——真正的错误留给下一步 Codable 去报告，避免同一个问题报两次。
    private static func checkUnknownFields(in data: Data) throws {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }

        try reject(root, known: KnownKeys.root, prefix: "")

        if let source = root["source"] as? [String: Any] {
            try reject(source, known: KnownKeys.source, prefix: "source.")
        }
        if let deck = root["deck"] as? [String: Any] {
            try reject(deck, known: KnownKeys.deck, prefix: "deck.")
        }
        if let cards = root["cards"] as? [[String: Any]] {
            for (index, card) in cards.enumerated() {
                try reject(card, known: KnownKeys.card, prefix: "cards[\(index)].")
            }
        }
    }

    private static func reject(_ object: [String: Any],
                               known: Set<String>,
                               prefix: String) throws {
        // 有序遍历，让同一份文件每次报同一个字段，便于复现。
        for key in object.keys.sorted() where !known.contains(key) {
            throw AnalysisValidator.ValidationError.unknownField(prefix + key)
        }
    }
}
