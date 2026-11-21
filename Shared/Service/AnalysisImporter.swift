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
    /// 为什么末尾必须有 `.item` 和 `.data`：很多人从微信或 AirDrop 收到 `.json`，系统会
    /// 给它打上 `public.data` 这类泛类型标记，而 `public.data` **不**满足 `public.json`
    /// 的约束——文件在选择器里就是灰的，点不动。加泛类型让任何文件都能被选中，
    /// 选错类型的代价只是后面校验时报一句中文错误，比「文件明明在那儿却选不了」好得多。
    ///
    /// 为什么同时放 `.item` 和 `.data`：`.item`（public.item）在 UIDocumentPicker 里有
    /// 「导致所有文件变灰」的已知坑，社区通行做法是改用 `.data`（public.data）作为
    /// 「允许任意文件」。两个都放， whichever 生效都放行。
    ///
    /// 为什么不放 `UTType(filenameExtension: "pdfreview")`：那个扩展名改由 Info.plist 的
    /// `UTExportedTypeDeclarations` 注册为 `com.pdfreview.analysis`（见 PdfReview/Resources/
    /// Info.plist），`UTType(filenameExtension:)` 在未注册时返回 `dyn.*` 动态标识符，
    /// **动态类型放进 fileImporter 的过滤列表会让整个过滤失效**，连 `.json` 也一起灰。
    static var allowedContentTypes: [UTType] {
        [.json, .item, .data]
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
