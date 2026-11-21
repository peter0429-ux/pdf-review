//
//  PrimaryButton.swift
//  PdfReview
//
//  主操作按钮：满宽、强调色、可带加载中状态。
//  加载时显示 ProgressView 并自动禁用，避免重复提交。
//

import SwiftUI

struct PrimaryButton: View {

    let title: String
    var isLoading: Bool = false
    var isDisabled: Bool = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if isLoading {
                    ProgressView()
                        .controlSize(.small)
                        .tint(.white)
                }
                Text(title)
                    .font(.body.weight(.semibold))
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
        }
        .buttonStyle(.borderedProminent)
        .disabled(isDisabled || isLoading)
    }
}
