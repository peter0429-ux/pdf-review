//
//  Formatting.swift
//  PdfReview
//
//  界面通用格式化工具：时长、轮换间隔、日期分组、错误文案。
//  只做纯展示转换，不碰存储，不读 SwiftData。
//

import Foundation

enum AppFormat {

    // MARK: 时长

    /// 把剩余秒数格式化成中文倒计时文案。
    /// 例：「距下次轮换还有 2 小时 15 分」「距下次轮换还有 8 分钟」。
    static func remainingText(_ seconds: TimeInterval) -> String {
        let total = max(0, Int(seconds.rounded(.down)))
        let minutes = total / 60
        if minutes >= 60 {
            let hours = minutes / 60
            let rest = minutes % 60
            return rest == 0
                ? "距下次轮换还有 \(hours) 小时"
                : "距下次轮换还有 \(hours) 小时 \(rest) 分"
        }
        if minutes >= 1 {
            return "距下次轮换还有 \(minutes) 分钟"
        }
        return "距下次轮换还有不到 1 分钟"
    }

    /// 轮换间隔的中文描述：0.5 → 「30 分钟」，3 → 「3 小时」。
    static func intervalText(_ hours: Double) -> String {
        let safe = max(0, hours)
        let minutes = Int((safe * 60).rounded())
        if minutes < 60 {
            return "\(minutes) 分钟"
        }
        if minutes % 60 == 0 {
            return "\(minutes / 60) 小时"
        }
        return String(format: "%.1f 小时", safe)
    }

    // MARK: 日期

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_Hans_CN")
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    private static let monthDayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_Hans_CN")
        formatter.dateFormat = "M 月 d 日"
        return formatter
    }()

    private static let fullFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_Hans_CN")
        formatter.dateFormat = "yyyy 年 M 月 d 日 HH:mm"
        return formatter
    }()

    /// 只显示时分，例如「14:05」。
    static func clock(_ date: Date) -> String {
        timeFormatter.string(from: date)
    }

    /// 完整时间，例如「2025 年 3 月 8 日 14:05」。
    static func full(_ date: Date) -> String {
        fullFormatter.string(from: date)
    }

    /// 历史记录分组标题：今天 / 昨天 / 具体日期。
    static func dayTitle(_ date: Date, now: Date = Date()) -> String {
        let calendar = Calendar.current
        if calendar.isDateInToday(date) { return "今天" }
        if calendar.isDateInYesterday(date) { return "昨天" }
        return monthDayFormatter.string(from: date)
    }

    /// 历史分组排序用的「当天零点」。
    static func dayStart(_ date: Date) -> Date {
        Calendar.current.startOfDay(for: date)
    }

    // MARK: 错误

    /// 把任意错误转成可直接展示的中文文案。
    /// `AIError`、`AnalysisValidator.ValidationError`、`PDFTextExtractor.ExtractError`
    /// 都实现了 `LocalizedError`，这里优先取它们的中文描述。
    static func message(for error: Error) -> String {
        if let localized = error as? LocalizedError,
           let text = localized.errorDescription,
           !text.isEmpty {
            return text
        }
        return error.localizedDescription
    }
}
