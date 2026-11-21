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
    ///
    /// 为什么末尾必须有 `.item`：很多人从微信或 AirDrop 收到 `.json`，系统会给它打上
    /// `public.data` 这类泛类型标记，而 `public.data` **不**满足 `public.json` 的约束——
    /// 文件在选择器里就是灰的，点不动。加 `.item` 让任何文件都能被选中，选错类型的
    /// 代价只是后面校验时报一句中文错误，比「文件明明在那儿却选不了」好得多。
    ///
    /// 为什么不再放 `UTType(filenameExtension: "pdfreview")`：这个扩展名没有在
    /// Info.plist 里注册（本项目也没打算注册），`UTType(filenameExtension:)` 会返回一个
    /// 动态标识符 `dyn.xxxxxxxx`。**动态类型放进 fileImporter 的过滤列表会让整个过滤失效**，
    /// 连本该能选的 `.json` 也一起变灰——这正是用户反馈「没法选中这个文件」的根因。
    static var allowedContentTypes: [UTType] {
        [.json, .item]
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
