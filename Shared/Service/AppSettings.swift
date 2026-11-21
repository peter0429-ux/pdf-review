//
//  AppSettings.swift
//  PdfReview
//
//  用户设置。API Key 走 Keychain，其余走 UserDefaults。
//  轮换间隔与每槽张数会被 CardStore 写入 RotationCache，供 Widget 使用。
//

import Foundation
import Combine

@MainActor
final class AppSettings: ObservableObject {

    static let shared = AppSettings()

    private enum Keys {
        static let baseURL = "settings.baseURL"
        static let model = "settings.model"
        static let intervalHours = "settings.intervalHours"
        static let cardsPerSlot = "settings.cardsPerSlot"
        static let cardsPerChunk = "settings.cardsPerChunk"
        static let hasCompletedOnboarding = "settings.hasCompletedOnboarding"
    }

    static let defaultBaseURL = "https://api.openai.com/v1"
    static let defaultModel = "gpt-4o-mini"
    static let defaultIntervalHours: Double = 3
    static let defaultCardsPerSlot = 1
    static let defaultCardsPerChunk = 6

    private let defaults = UserDefaults.standard

    /// OpenAI 兼容接口的 Base URL，例如 `https://api.openai.com/v1`。
    @Published var baseURLString: String {
        didSet { defaults.set(baseURLString, forKey: Keys.baseURL) }
    }

    /// 模型名，例如 `gpt-4o-mini`、`deepseek-chat`。
    @Published var model: String {
        didSet { defaults.set(model, forKey: Keys.model) }
    }

    /// 轮换间隔（小时）。范围 0.25...24，默认 3。
    @Published var rotationIntervalHours: Double {
        didSet {
            let clamped = min(24, max(0.25, rotationIntervalHours))
            if clamped != rotationIntervalHours {
                rotationIntervalHours = clamped
                return
            }
            defaults.set(rotationIntervalHours, forKey: Keys.intervalHours)
        }
    }

    /// 每轮展示几张。范围 1...10，默认 1。
    @Published var cardsPerSlot: Int {
        didSet {
            let clamped = min(10, max(1, cardsPerSlot))
            if clamped != cardsPerSlot {
                cardsPerSlot = clamped
                return
            }
            defaults.set(cardsPerSlot, forKey: Keys.cardsPerSlot)
        }
    }

    /// 每次 AI 请求生成几张卡片。范围 3...12，默认 6。
    @Published var cardsPerChunk: Int {
        didSet {
            let clamped = min(12, max(3, cardsPerChunk))
            if clamped != cardsPerChunk {
                cardsPerChunk = clamped
                return
            }
            defaults.set(cardsPerChunk, forKey: Keys.cardsPerChunk)
        }
    }

    /// 是否已完成首次引导。
    @Published var hasCompletedOnboarding: Bool {
        didSet { defaults.set(hasCompletedOnboarding, forKey: Keys.hasCompletedOnboarding) }
    }

    private init() {
        baseURLString = defaults.string(forKey: Keys.baseURL) ?? Self.defaultBaseURL
        model = defaults.string(forKey: Keys.model) ?? Self.defaultModel
        rotationIntervalHours = defaults.object(forKey: Keys.intervalHours) as? Double
            ?? Self.defaultIntervalHours
        cardsPerSlot = defaults.object(forKey: Keys.cardsPerSlot) as? Int
            ?? Self.defaultCardsPerSlot
        cardsPerChunk = defaults.object(forKey: Keys.cardsPerChunk) as? Int
            ?? Self.defaultCardsPerChunk
        hasCompletedOnboarding = defaults.bool(forKey: Keys.hasCompletedOnboarding)
    }

    // MARK: API Key

    /// 读取 API Key（Keychain）。为空表示未配置。
    var apiKey: String {
        get { KeychainStore.get(KeychainStore.Keys.apiKey) ?? "" }
        set {
            let trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty {
                KeychainStore.remove(KeychainStore.Keys.apiKey)
            } else {
                try? KeychainStore.set(trimmed, for: KeychainStore.Keys.apiKey)
            }
            // 触发 UI 刷新
            objectWillChange.send()
        }
    }

    /// 是否已具备调用 AI 的最低配置。
    var isAIConfigured: Bool {
        !apiKey.isEmpty && normalizedBaseURL != nil && !model.isEmpty
    }

    /// 规范化后的 Base URL。不合法返回 nil。
    var normalizedBaseURL: URL? {
        let trimmed = baseURLString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        var candidate = trimmed
        // 允许用户省略协议头
        if !candidate.contains("://") {
            candidate = "https://" + candidate
        }
        // 去掉结尾斜杠，避免拼接出双斜杠
        while candidate.hasSuffix("/") {
            candidate.removeLast()
        }
        guard let url = URL(string: candidate),
              let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https",
              url.host?.isEmpty == false
        else {
            return nil
        }
        return url
    }

    /// 构造一次 AI 请求所需的配置。缺配置时抛出错误。
    func aiConfig() throws -> AIRequestConfig {
        guard let url = normalizedBaseURL else {
            throw AIError.missingConfiguration("Base URL 无效，请在设置中填写以 http(s):// 开头的地址。")
        }
        let key = apiKey
        guard !key.isEmpty else {
            throw AIError.missingConfiguration("尚未填写 API Key。")
        }
        let name = model.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else {
            throw AIError.missingConfiguration("尚未填写模型名。")
        }
        return AIRequestConfig(baseURL: url, model: name, apiKey: key)
    }
}
