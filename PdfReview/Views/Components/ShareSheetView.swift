//
//  ShareSheetView.swift
//  PdfReview
//
//  把系统分享面板包成 SwiftUI 视图。用于导出 .pdfreview.json 与
//  导出轮换缓存文件（排查问题用）。
//
//  为什么不用 ShareLink：ShareLink 需要 URL 在视图构建时就确定，
//  而我们的文件是「点了按钮才生成」的。用 sheet(item:) + UIActivityViewController
//  可以做到先生成再分享。
//

import SwiftUI
import UIKit

struct ShareSheetView: UIViewControllerRepresentable {

    let url: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {
        // 无需更新
    }
}
