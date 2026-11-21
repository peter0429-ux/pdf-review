//
//  ImportInbox.swift
//  PdfReview
//
//  收件箱：接住从别的 App 分享/「用其他应用打开」过来的文件。
//
//  ── 为什么需要它 ──────────────────────────────────────────────────────
//  真机上文件选择器里的文件全是灰的（iOS 27，见 DocumentPicker.swift 注释）。
//  选择器这条路在修，但用户手上必须有一条**一定能走通**的路。
//  「在『文件』App 里长按 → 共享 → PDF 复习」就是那条路，而且不依赖任何
//  选择器的类型过滤逻辑。
//
//  ── 为什么立刻复制到临时目录 ───────────────────────────────────────────
//  分享进来的 URL 可能是 security-scoped，也可能指向别的 App 的容器。
//  把「能不能读」这件事在收到的当下就解决掉、变成一个普通沙盒文件，
//  后面所有代码（PDFKit 解析、JSON 读取）都不用再关心授权时序。
//  代价是占一份磁盘，导入结束后会删。
//

import Combine
import Foundation
import UniformTypeIdentifiers

/// 收件箱：把「外部送进来的文件」暂存成一个 App 内部可读的 URL。
@MainActor
final class ImportInbox: ObservableObject {

    static let shared = ImportInbox()

    /// 送进来的是哪一类文件。决定后面走 PDF 分析还是 JSON 导入。
    enum Kind: Equatable {
        case pdf
        case analysis
    }

    struct Pending: Identifiable, Equatable {
        let id: UUID
        let url: URL
        let kind: Kind
        let originalName: String

        static func == (lhs: Pending, rhs: Pending) -> Bool {
            lhs.id == rhs.id
        }
    }

    /// 待处理文件。RootView 观察到它变化就弹出导入面板。
    @Published private(set) var pending: Pending?

    private init() { }

    /// 收到一个外部 URL。复制进临时目录后放进 pending。
    ///
    /// 复制失败时不抛错给调用方（`onOpenURL` 的闭包不能抛），
    /// 而是把失败原因记进日志，pending 保持 nil —— 界面不会假装收到了文件。
    func receive(_ url: URL) {
        let originalName = url.lastPathComponent

        // 有些分享来源需要显式开始访问；对普通沙盒 URL 调用返回 false 也无害。
        let scoped = url.startAccessingSecurityScopedResource()
        defer {
            if scoped { url.stopAccessingSecurityScopedResource() }
        }

        guard let copied = Self.copyIntoTemporary(url: url) else {
            LaunchLog.note("收件箱：复制失败 \(originalName)")
            return
        }

        let kind = Self.kind(of: copied, originalName: originalName)
        LaunchLog.note("收件箱：收到 \(originalName)，判定为 \(kind == .pdf ? "PDF" : "分析文件")")
        pending = Pending(
            id: UUID(),
            url: copied,
            kind: kind,
            originalName: originalName
        )
    }

    /// 取走待处理文件（取走后 pending 置空，避免同一份文件被导入两次）。
    func take() -> Pending? {
        let value = pending
        pending = nil
        return value
    }

    /// 放弃当前待处理文件，并删掉临时副本。
    func discard() {
        if let pending {
            try? FileManager.default.removeItem(at: pending.url)
        }
        pending = nil
    }

    // MARK: - 内部

    /// 复制到临时目录。返回的 URL 是普通沙盒文件，后续读取不需要授权。
    private static func copyIntoTemporary(url: URL) -> URL? {
        let manager = FileManager.default
        let name = sanitized(url.lastPathComponent)
        // 加 UUID 前缀：同一次运行里重复分享同名文件不会互相覆盖。
        let destination = manager.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString)-\(name)", isDirectory: false)

        do {
            if manager.fileExists(atPath: destination.path) {
                try manager.removeItem(at: destination)
            }
            try manager.copyItem(at: url, to: destination)
            return destination
        } catch {
            return nil
        }
    }

    /// 判定种类：先看扩展名，扩展名不可靠时嗅探首字节。
    private static func kind(of url: URL, originalName: String) -> Kind {
        // 取原始文件名的扩展名而不是复制品的：复制品被加了 UUID 前缀，
        // 但扩展名保留了，两者一致；用原始名只是让日志读起来更直观。
        let ext = (originalName as NSString).pathExtension.lowercased()
        if ext == "pdf" { return .pdf }
        if ext == "json" { return .analysis }

        // 扩展名缺失或不认识：读前若干字节判断。
        if let handle = try? FileHandle(forReadingFrom: url) {
            defer { try? handle.close() }
            if let head = try? handle.read(upToCount: 5), !head.isEmpty {
                // PDF 以 "%PDF-" 开头
                if head.count >= 5, String(data: head, encoding: .ascii)?.hasPrefix("%PDF-") == true {
                    return .pdf
                }
                // JSON 以 { 或 [ 开头（跳过空白、BOM）
                let trimmed = head.drop { byte in
                    byte == 0x20 || byte == 0x09 || byte == 0x0A || byte == 0x0D
                }
                if let first = trimmed.first, first == 0x7B || first == 0x5B {
                    return .analysis
                }
            }
        }
        return .analysis
    }

    /// 去掉路径分隔符等不安全字符，避免复制时越界写。
    private static func sanitized(_ name: String) -> String {
        let illegal = CharacterSet(charactersIn: "/\\:?%*|\"<>")
        let cleaned = name.components(separatedBy: illegal).joined(separator: "-")
        return cleaned.isEmpty ? "import" : cleaned
    }
}
