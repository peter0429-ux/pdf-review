//
//  EmptyHintView.swift
//  PdfReview
//
//  空状态占位。基于系统 `ContentUnavailableView`，保持 iOS 原生观感。
//  需要带操作按钮的场景，直接在页面里用 `ContentUnavailableView { } actions: { }`。
//

import SwiftUI

struct EmptyHintView: View {

    let icon: String
    let title: String
    let message: String

    var body: some View {
        ContentUnavailableView {
            Label(title, systemImage: icon)
        } description: {
            Text(message)
        }
    }
}
