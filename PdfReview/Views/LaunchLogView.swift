//
//  LaunchLogView.swift
//  PdfReview
//
//  设置 → 启动日志。给用户一个不需要连电脑就能把诊断信息取出来的入口。
//
//  存在的理由：App 如果在启动时闪退，用户在界面上什么都看不到，也翻不到
//  iPhone 的「分析数据」。把启动过程落成明文日志，并允许直接分享出去，
//  是唯一能远程定位这类问题的办法。
//

import SwiftUI
import UIKit

struct LaunchLogView: View {

    @State private var text: String = LaunchLog.readAll()
    @State private var sharingFile: SharedFile?
    @State private var copied = false

    private let ticker = Timer.publish(every: 2, on: .main, in: .common).autoconnect()

    var body: some View {
        List {
            Section {
                if text.isEmpty {
                    Text("（还没有日志）")
                        .foregroundStyle(.secondary)
                } else {
                    Text(text)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                }
            } header: {
                Text("最近 400 行")
            } footer: {
                Text("App 每次启动都会在这里记下走到的步骤。如果 App 闪退，先把这段日志分享出来，能直接看出断在哪一步。")
            }
        }
        .navigationTitle("启动日志")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button {
                        copyAll()
                    } label: {
                        Label(copied ? "已复制" : "复制全部", systemImage: "doc.on.doc")
                    }
                    Button {
                        share()
                    } label: {
                        Label("分享日志文件", systemImage: "square.and.arrow.up")
                    }
                    Button(role: .destructive) {
                        LaunchLog.clear()
                        text = LaunchLog.readAll()
                    } label: {
                        Label("清空", systemImage: "trash")
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
        .onReceive(ticker) { _ in
            // 自动刷新，方便边看边操作时确认新写入的行。
            let latest = LaunchLog.readAll()
            if latest != text { text = latest }
        }
        .sheet(item: $sharingFile) { file in
            ShareSheetView(url: file.url)
        }
    }

    private func copyAll() {
        UIPasteboard.general.string = text
        copied = true
        Task {
            try? await Task.sleep(for: .seconds(2))
            copied = false
        }
    }

    private func share() {
        // 分享的是磁盘上的真实文件，不是内存字符串——这样用户拿到的是
        // 原始 launch.log，能确认它确实来自 App 而不是我拼的。
        guard let url = LaunchLog.currentFileURL,
              FileManager.default.fileExists(atPath: url.path)
        else {
            text = LaunchLog.readAll()
            return
        }
        sharingFile = SharedFile(url: url)
    }
}

// MARK: - 分享用的可识别包装

private struct SharedFile: Identifiable {
    let url: URL
    var id: String { url.absoluteString }
}
