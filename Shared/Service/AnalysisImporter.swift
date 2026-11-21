//
//  AnalysisImporter.swift
//  PdfReview
//
//  `.pdfreview.json` 的读写工具。校验逻辑在 AnalysisValidator，
//  这里只负责文件层面的操作（读取、编码、写临时文件用于分享）。
//

import Foundation
import UniformTypeIdentifiers

enum AnalysisImporter {

    /// 导入流程允许的文件类型。
    /// `.json` 放在最前面，因为多数文件选择器只认它；用户在文件 App 里选中
    /// `xxx.pdfreview.json` 时会命中 `json` 这一项。
    static var allowedContentTypes: [UTType] {
        var types: [UTType] = []
        if let json = UTType(filenameExtension: "json") {
            types.append(json)
        }
        if let custom = UTType(filenameExtension: "pdfreview") {
            types.append(custom)
        }
        return types.isEmpty ? [.json] : types
    }

    /// 从用户选择的 URL 导入。已完成解码与校验。
    static func decode(from url: URL) throws -> AnalysisDocument {
        try AnalysisDocument.load(from: url)
    }

    /// 分步版本：先读字节再校验，便于界面分阶段显示进度。
    static func readData(from url: URL) throws -> Data {
        let needsRelease = url.startAccessingSecurityScopedResource()
        defer {
            if needsRelease { url.stopAccessingSecurityScopedResource() }
        }
        do {
            return try Data(contentsOf: url)
        } catch {
            throw AnalysisValidator.ValidationError.unreadableFile(url.lastPathComponent)
        }
    }

    /// 把文档编码成 JSON 数据。
    static func encode(_ document: AnalysisDocument) throws -> Data {
        try document.encoded()
    }

    /// 把文档写到临时目录，返回可分享的 URL。文件名形如 `牌组名.pdfreview.json`。
    static func writeTemporaryFile(_ document: AnalysisDocument) throws -> URL {
        let data = try document.encoded()
        let safeName = sanitizeFileName(document.deck.title)
        let fileName = "\(safeName).pdfreview.json"
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(fileName)
        try data.write(to: url, options: .atomic)
        return url
    }

    /// 去掉文件名里的非法字符。
    static func sanitizeFileName(_ raw: String) -> String {
        let invalid = CharacterSet(charactersIn: "\\/:*?\"<>|\n\r\t")
        let cleaned = raw.components(separatedBy: invalid).joined(separator: "-")
        let trimmed = cleaned.trimmingCharacters(in: .whitespacesAndNewlines)
        let fallback = trimmed.isEmpty ? "复习卡片" : trimmed
        return String(fallback.prefix(60))
    }

    /// 读取并校验用户选中的文件，返回文档与来源文件名。
    static func importDocument(from url: URL) throws -> (document: AnalysisDocument, fileName: String) {
        let document = try decode(from: url)
        return (document, url.lastPathComponent)
    }
}
