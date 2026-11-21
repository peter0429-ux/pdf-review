//
//  DocumentPicker.swift
//  PdfReview
//
//  文档选择器：直接包装 UIDocumentPickerViewController。
//
//  ── 为什么不用 SwiftUI 的 .fileImporter ────────────────────────────────
//  真机上（iOS 27）选择器能弹出来，但**所有文件都是灰的**，点不中。
//  依次试过这些 allowedContentTypes，全都没有改善：
//      [.pdf]              → 灰
//      [.pdf, .item]       → 灰
//      [.pdf, .item, .data] → 灰
//  也就是说「往里加更宽泛的类型」这条路走不通，问题不在类型集合的宽窄，
//  而在 .fileImporter 自己怎么把类型集合喂给系统。
//
//  改成直接用 UIViewControllerRepresentable 指定**单一**抽象类型 .item，
//  避开混合类型判定的那条路径。内容合法性交给读取阶段去校验：
//  PDF 由 PDFDocument 打不开就报错，分析文件有 looksLikeJSON 前置检查。
//
//  ── 为什么 asCopy: true ────────────────────────────────────────────────
//  ① 有些文件提供商（网盘类）不支持原地访问，in-place 模式下它们的文件
//     本身就是灰的。复制到沙盒后我们拿到的是真实可读的副本。
//  ② 复制出来的 URL 不是 security-scoped，后续读取不再依赖授权时序，
//     少一类「选完读不到」的失败模式。
//  代价是选大文件时多一次复制（70 MB 的 PDF 约一秒），换来稳定。
//

import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// 用 `UIDocumentPickerViewController` 实现的文件选择器。
///
/// 用法：
/// ```swift
/// .sheet(isPresented: $showPicker) {
///     DocumentPicker { url in
///         // 选中了，url 已经是沙盒里的副本
///     }
/// }
/// ```
struct DocumentPicker: UIViewControllerRepresentable {

    /// 选中一个文件。回调的 URL 指向 App 沙盒内的副本。
    let onPick: (URL) -> Void

    init(onPick: @escaping (URL) -> Void) {
        self.onPick = onPick
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(onPick: onPick)
    }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        // 只给 .item（public.item）。这是文件系统的根类型，PDF、json、
        // txt 全部落在它下面。宽是故意的——合法性在后面校验，而不是
        // 在这里把用户能看到的文件提前筛掉。
        let picker = UIDocumentPickerViewController(
            forOpeningContentTypes: [.item],
            asCopy: true
        )
        picker.allowsMultipleSelection = false
        picker.shouldShowFileExtensions = true
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {
        // 无状态，不需要更新。
    }

    final class Coordinator: NSObject, UIDocumentPickerDelegate {

        private let onPick: (URL) -> Void

        init(onPick: @escaping (URL) -> Void) {
            self.onPick = onPick
        }

        func documentPicker(
            _ controller: UIDocumentPickerViewController,
            didPickDocumentsAt urls: [URL]
        ) {
            guard let url = urls.first else { return }
            onPick(url)
        }

        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
            // 取消不需要做任何事：sheet 会自己收起，界面停在导入页。
        }
    }
}
