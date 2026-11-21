//
//  PDFTextExtractor.swift
//  PdfReview
//
//  从 PDF 抽取文本层并切块。
//  首版只处理带文本层的 PDF；扫描件会返回 hasTextLayer = false，由界面提示用户。
//

import Foundation
import PDFKit

enum PDFTextExtractor {

    struct Extraction {
        var pageCount: Int
        var pages: [String]
        var fullText: String
        /// 是否检测到可用文本层。false 表示疑似扫描件。
        var hasTextLayer: Bool
    }

    enum ExtractError: LocalizedError {
        case cannotOpen(String)
        case permissionDenied
        case emptyDocument

        var errorDescription: String? {
            switch self {
            case let .cannotOpen(name):
                return "无法打开 PDF「\(name)」。文件可能已损坏或受密码保护。"
            case .permissionDenied:
                return "没有权限读取该文件，请重新选择。"
            case .emptyDocument:
                return "这份 PDF 是空的。"
            }
        }
    }

    /// 抽取全文与逐页文本。
    static func extract(from url: URL) throws -> Extraction {
        let needsRelease = url.startAccessingSecurityScopedResource()
        defer {
            if needsRelease { url.stopAccessingSecurityScopedResource() }
        }

        guard let document = PDFDocument(url: url) else {
            throw ExtractError.cannotOpen(url.lastPathComponent)
        }
        guard !document.isLocked else {
            throw ExtractError.cannotOpen(url.lastPathComponent)
        }

        let pageCount = document.pageCount
        guard pageCount > 0 else { throw ExtractError.emptyDocument }

        var pages: [String] = []
        pages.reserveCapacity(pageCount)

        for index in 0..<pageCount {
            guard let page = document.page(at: index) else {
                pages.append("")
                continue
            }
            let text = page.string ?? ""
            pages.append(normalize(text))
        }

        let fullText = pages.joined(separator: "\n\n")
        // 文本层判定：去空白后总字符数达到阈值，且平均每页有一定内容
        let substantial = fullText.trimmingCharacters(in: .whitespacesAndNewlines).count
        let hasTextLayer = substantial >= 200 && Double(substantial) / Double(pageCount) >= 20

        return Extraction(
            pageCount: pageCount,
            pages: pages,
            fullText: fullText,
            hasTextLayer: hasTextLayer
        )
    }

    /// 切成适合单次请求的块。
    /// 按页累积，超过 `maxChars` 就断开；单页超长时按段落再切。
    static func chunk(_ extraction: Extraction, maxChars: Int = 12_000) -> [TextChunk] {
        guard maxChars > 500 else { return [] }
        var chunks: [TextChunk] = []
        var buffer = ""
        var startPage = 1
        var endPage = 1

        for (index, pageText) in extraction.pages.enumerated() {
            let pageNumber = index + 1
            let trimmed = pageText.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }

            if trimmed.count > maxChars {
                // 先把已有缓冲落盘
                if !buffer.isEmpty {
                    chunks.append(
                        TextChunk(
                            index: chunks.count,
                            pageRange: startPage...endPage,
                            text: buffer
                        )
                    )
                }
                buffer = ""
                // 超长单页按段落切
                for piece in splitLongText(trimmed, maxChars: maxChars) {
                    chunks.append(
                        TextChunk(
                            index: chunks.count,
                            pageRange: pageNumber...pageNumber,
                            text: piece
                        )
                    )
                }
                startPage = pageNumber + 1
                endPage = pageNumber
                continue
            }

            if buffer.isEmpty {
                startPage = pageNumber
                buffer = trimmed
            } else if buffer.count + trimmed.count + 2 > maxChars {
                chunks.append(
                    TextChunk(
                        index: chunks.count,
                        pageRange: startPage...endPage,
                        text: buffer
                    )
                )
                startPage = pageNumber
                buffer = trimmed
            } else {
                buffer += "\n\n" + trimmed
            }
            endPage = pageNumber
        }

        if !buffer.isEmpty {
            chunks.append(
                TextChunk(
                    index: chunks.count,
                    pageRange: startPage...endPage,
                    text: buffer
                )
            )
        }

        return chunks
    }

    /// 把超长文本按段落（退化为按字符）切分。
    private static func splitLongText(_ text: String, maxChars: Int) -> [String] {
        var pieces: [String] = []
        var current = ""

        for paragraph in text.components(separatedBy: "\n") {
            let line = paragraph.trimmingCharacters(in: .whitespaces)
            if line.count > maxChars {
                if !current.isEmpty {
                    pieces.append(current)
                    current = ""
                }
                var rest = Substring(line)
                while rest.count > maxChars {
                    let cut = rest.index(rest.startIndex, offsetBy: maxChars)
                    pieces.append(String(rest[rest.startIndex..<cut]))
                    rest = rest[cut...]
                }
                if !rest.isEmpty { current = String(rest) }
                continue
            }

            if current.isEmpty {
                current = line
            } else if current.count + line.count + 1 > maxChars {
                pieces.append(current)
                current = line
            } else {
                current += "\n" + line
            }
        }

        if !current.isEmpty { pieces.append(current) }
        return pieces
    }

    /// 归一化：去掉零宽字符，合并过多空行，统一换行符。
    private static func normalize(_ text: String) -> String {
        var result = text
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .replacingOccurrences(of: "\u{200B}", with: "")
            .replacingOccurrences(of: "\u{FEFF}", with: "")

        // 三个以上连续换行压成两个
        while result.contains("\n\n\n") {
            result = result.replacingOccurrences(of: "\n\n\n", with: "\n\n")
        }
        return result.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

// MARK: - 文本块

/// 送入 AI 的一段文本。
struct TextChunk {
    var index: Int
    var pageRange: ClosedRange<Int>
    var text: String
}
