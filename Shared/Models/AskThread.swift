//
//  AskThread.swift
//  PdfReview
//
//  SwiftData 模型：一次提问的记录。
//
//  为什么单独建模型而不是塞进 ReviewCard：提问的价值不止「最后有没有做成卡片」。
//  用户问了一个问题、AI 答得很好、但当时没保存 —— 事后想翻回去看那条回答，
//  如果只存卡片就永远找不到了。
//
//  `AskThread` 与 `ReviewCard` 没有 SwiftData 关系，只靠 `savedCardID` 这个
//  普通字段指过去。理由是：卡片可以被单独删除（用户可能只想删掉那张卡，
//  但保留当时的问答记录），用关系的话级联删除规则会很难定；而且这张卡
//  也可能被移到别的牌组，关系反而会跟着乱。
//

import Foundation
import SwiftData

@Model
final class AskThread {

    @Attribute(.unique) var id: UUID

    /// 用户的原话。存档用，不做改写。
    var question: String

    /// AI 的回答。可能很长，不设硬上限。
    var answer: String

    /// AI 判断这个知识点值不值得做成复习卡片。
    var worthSaving: Bool

    /// AI 给的理由（一句话）。为 nil 表示模型没给。
    var reason: String?

    /// 提问时选定的牌组 ID。牌组后来被删了这里会指向一个不存在的 ID，
    /// 界面按「牌组已删除」处理，不做级联删除 —— 问答记录本身仍有价值。
    var deckID: UUID?

    /// 提问时牌组的标题，留个快照，牌组删了也能看懂当时问的是哪份资料。
    var deckTitle: String?

    /// AI 给出的卡片草稿（JSON 编码的 `AnalysisDocument.CardItem`）。
    ///
    /// 存成 Data 而不是拆成一堆字段：草稿是「模型输出」的原始形态，
    /// 拆字段意味着每加一个卡片属性都要改三处（模型、快照、编辑器）。
    /// 解码失败时当没有草稿处理。
    var draftData: Data?

    /// 已保存成卡片时记下卡片 ID。为 nil 表示还没保存。
    var savedCardID: UUID?

    var createdAt: Date

    init(
        id: UUID = UUID(),
        question: String,
        answer: String,
        worthSaving: Bool = false,
        reason: String? = nil,
        deckID: UUID? = nil,
        deckTitle: String? = nil,
        draftData: Data? = nil,
        savedCardID: UUID? = nil,
        createdAt: Date = Date()
    ) {
        self.id = id
        self.question = question
        self.answer = answer
        self.worthSaving = worthSaving
        self.reason = reason
        self.deckID = deckID
        self.deckTitle = deckTitle
        self.draftData = draftData
        self.savedCardID = savedCardID
        self.createdAt = createdAt
    }
}

// MARK: - 草稿

extension AskThread {
    /// 解密草稿。解码失败返回 nil（旧版本写入的、或字段结构变了的，都当没有）。
    var draft: AnalysisDocument.CardItem? {
        guard let draftData else { return nil }
        let decoder = JSONDecoder()
        return try? decoder.decode(AnalysisDocument.CardItem.self, from: draftData)
    }

    /// 写入草稿。编码失败则清空，不留半截数据。
    func setDraft(_ item: AnalysisDocument.CardItem?) {
        guard let item else {
            draftData = nil
            return
        }
        draftData = try? JSONEncoder().encode(item)
    }

    /// 已保存过就不再允许重复保存。
    var isSaved: Bool { savedCardID != nil }
}
