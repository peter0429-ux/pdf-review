//
//  LaunchLog.swift
//  PdfReview
//
//  极简启动日志，写到 App 自己的 Documents 目录。
//
//  为什么需要它：闪退发生在启动路径上时，用户拿不到任何可读信息——
//  Xcode 连不上、崩溃报告在「分析数据」里翻起来很麻烦、模拟器又复现不了
//  侧载的签名环境。把「走到哪一步」落到磁盘，下次闪退就能直接看出断在
//  哪一级（容器降到哪层、App Group 能不能写）。
//
//  必须是同步写：如果异步派发，崩溃恰好发生在写盘之前，日志就是空的——
//  那正是最需要它的时刻。启动路径上只记几行，同步写的代价可以忽略。
//
//  App 的 Info.plist 已开 UIFileSharingEnabled，用户可以用 Finder 或
//  「文件」App 直接取走 launch.log，不必连电脑调试。
//
//  注意：这个文件只编译进 App target，Widget 不需要。
//

import Foundation

enum LaunchLog {

    private static let fileName = "launch.log"

    /// 只保留最近这么多行，避免无限增长。
    private static let maxLines = 400

    /// 串行保护，避免多线程同时写同一个文件。
    private static let lock = NSLock()

    private static var fileURL: URL? {
        FileManager.default
            .urls(for: .documentDirectory, in: .userDomainMask)
            .first?
            .appendingPathComponent(fileName, isDirectory: false)
    }

    /// 日志文件位置，供界面或诊断文案展示。
    static var currentFileURL: URL? { fileURL }

    /// 记一行。任何失败都静默吞掉——日志本身绝不能成为新的崩溃源。
    static func note(_ message: String) {
        lock.lock()
        defer { lock.unlock() }
        append(message)
    }

    private static func append(_ message: String) {
        guard let url = fileURL else { return }

        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MM-dd HH:mm:ss"
        let stamp = formatter.string(from: Date())

        let line = "[\(stamp)] \(message)\n"
        guard let data = line.data(using: .utf8) else { return }

        if let handle = try? FileHandle(forWritingTo: url) {
            defer { try? handle.close() }
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
            trimIfNeeded(url: url)
        } else {
            try? data.write(to: url, options: .atomic)
        }
    }

    private static func trimIfNeeded(url: URL) {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return }
        var lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        guard lines.count > maxLines else { return }
        lines = Array(lines.suffix(maxLines))
        try? lines.joined(separator: "\n").write(to: url, atomically: true, encoding: .utf8)
    }

    /// 读出当前日志全文，供设置页的「诊断」展示。
    static func readAll() -> String {
        guard let url = fileURL,
              let text = try? String(contentsOf: url, encoding: .utf8)
        else {
            return "（还没有日志。应用启动过一次后就会生成。）"
        }
        return text
    }

    /// 清空日志。
    static func clear() {
        lock.lock()
        defer { lock.unlock() }
        guard let url = fileURL else { return }
        try? FileManager.default.removeItem(at: url)
    }
}

// MARK: - Bundle 版本号

extension Bundle {
    /// 面向用户的版本号，如 "1.0"。
    var shortVersion: String {
        object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?"
    }

    /// 构建号。
    var buildNumber: String {
        object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "?"
    }
}
