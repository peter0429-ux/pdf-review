# PdfReview 架构契约

> 本文档是 App、Widget、共享层三方唯一的接口约定。任何一方改动下列签名，必须同步改本文档与另外两方。

## 1. 目标与边界

| 项 | 内容 |
|---|---|
| 目标平台 | iOS 17.0+（iPhone 优先，iPad 自适应） |
| UI 框架 | SwiftUI |
| 持久化（App 侧） | SwiftData |
| 小组件 | WidgetKit + App Intents（交互式） |
| AI 接入 | OpenAI Chat Completions 兼容接口 |
| 离线导入 | `.pdfreview.json`（v1，见 `docs/pdf-analysis-format.md`） |

**明确不做**：扫描件 OCR、iCloud 同步、后端服务、内购、App Store 上架材料。

## 2. Target 与标识符

| Target | Bundle ID | 说明 |
|---|---|---|
| `PdfReview` | `com.pdfreview.app` | 主 App |
| `PdfReviewWidget` | `com.pdfreview.app.widget` | 小组件扩展 |
| App Group | `group.com.pdfreview.app` | 唯一共享容器 |

`Shared/` 目录下的全部源码**同时编译进两个 target**（不是 SPM 包，直接文件引用）。

## 3. 关键设计决策

### 3.1 小组件不直接读写 SwiftData

WidgetKit 的 Timeline Provider 运行在受限的独立进程里，直接操作 SwiftData 容易产生崩溃和数据竞争。因此：

```
[App]  SwiftData (真相源)
         │  变更后 → materialize
         ▼
       rotation-cache.json   ← 唯一共享读模型（App Group 容器内）
         │ 只读
         ▼
[Widget] 纯函数计算 slot → 构建 Timeline
```

- **App 是唯一写者**：任何卡片/牌组变更后调用 `CardStore.refreshRotationCache()` 重写 JSON。
- **Widget 只读 JSON**，通过 `RotationScheduler` 的纯函数算出该显示什么。
- **历史记录由 App 回填**：App 启动/前台时用同一套纯函数推算「已经过去的 slot」，写入 `CardDisplayRecord`。因此 App 与 Widget 看到的历史完全一致。

### 3.2 轮换数学（纯函数，App 与 Widget 必须逐位一致）

```swift
slotIndex(t) = floor((t - cache.epoch) / (cache.intervalHours * 3600)) + cache.manualOffset
slotStart(n) = cache.epoch + (n - cache.manualOffset) * intervalHours * 3600
```

- `epoch`：首次启用轮换的时间锚点，存于 cache。
- `manualOffset`：点「下一张」时 +1，存 App Group `UserDefaults`，同时写回 cache。Widget 重绘后立刻前进。
- 卡片选取：先用 `orderSalt` 做**确定性洗牌**（`SplitMix64` 种子 = `orderSalt` 的 FNV-1a 哈希），再按 `slotIndex` 取模循环取 `cardsPerSlot` 张。池变化时换 `orderSalt`，全量重新洗牌。

**保证**：同一份 cache + 同一时刻，App 与 Widget 结果必然相同。

### 3.3 提问链路（只走 App，不进小组件）

```
[用户提问]
    │  question + 所选牌组的 sourceText（前 40_000 字）
    ▼
[AIClient.ask]  → POST {baseURL}/chat/completions
    │             system prompt：先完整回答，再单独判断「值不值得做卡片」
    ▼
{ answer, worthSaving, reason, card }
    │
    ├─→ AskThread 入库（**无论如何都存**，哪怕没有卡片）
    │       └─ deckID / deckTitle / draftData / savedCardID
    │
    └─→ worthSaving == true 且 card 可解析
            └─→ 界面展示草稿 → 用户改 → insertCard(origin: "ask")
                                         └─→ refreshRotationCache()
```

三条不能破的性质：

1. **回答优先**。AI 觉得不值得做成卡片，也必须把答案给用户。所以 `AskResult.answer` 为空即视为失败，而不是「没有卡片就什么都不显示」。
2. **`worthSaving` 与 `draft` 必须同时成立**。模型说「值得」却给不出可解析的卡（字段缺失、被截成空串），按不值得处理——否则用户点保存才发现是空卡。这条在 `AIClient.decodeAskResult` 里强制。
3. **提问记录独立于卡片**。`AskThread` 与 `ReviewCard` 之间没有 SwiftData 关系，只有 `savedCardID` 这个普通字段。卡片被删、被移到别的牌组，提问历史都不受影响。

问答完全不参与轮换：`AskThread` 不进 `RotationCache`，小组件也不读它。小组件只认 `CardSnapshot`。

## 4. 共享层 API（`Shared/`，双 target 编译）

### 4.1 `Shared/Core/AppGroup.swift`

```swift
enum AppGroup {
    static let identifier = "group.com.pdfreview.app"
    static var containerURL: URL          // 容器根；失败时降级到 Documents
    static var defaults: UserDefaults     // suiteName: identifier
    static var cacheFileURL: URL          // containerURL / "rotation-cache.json"
}
```

### 4.2 `Shared/Core/RotationCache.swift`

App 与 Widget 之间的**唯一数据结构**。

```swift
struct RotationCache: Codable {
    var version: Int            // 当前 1
    var generatedAt: Date
    var epoch: Date
    var intervalHours: Double
    var cardsPerSlot: Int
    var orderSalt: String
    var manualOffset: Int
    var decks: [DeckSnapshot]
    var cards: [CardSnapshot]

    static func load() -> RotationCache?      // 读 cacheFileURL，解码失败返回 nil
    func save() throws                        // 原子写入 cacheFileURL
    static func empty() -> RotationCache
}

struct DeckSnapshot: Codable, Identifiable {
    var id: UUID
    var title: String
    var cardCount: Int
}

struct CardSnapshot: Codable, Identifiable {
    var id: UUID
    var deckID: UUID
    var deckTitle: String
    var question: String
    var answer: String
    var detail: String?
    var tags: [String]
    var sourcePage: Int?
    var isFavorite: Bool
}
```

### 4.3 `Shared/Core/RotationScheduler.swift`

**无状态、纯函数**。App 与 Widget 都调用。

```swift
struct RotationSlot {
    var index: Int
    var start: Date
    var cards: [CardSnapshot]
}

enum RotationScheduler {
    static func slotIndex(at date: Date, cache: RotationCache) -> Int
    static func slotStart(index: Int, cache: RotationCache) -> Date
    static func slot(at date: Date, cache: RotationCache) -> RotationSlot?      // 池为空返回 nil
    static func upcoming(at date: Date, count: Int, cache: RotationCache) -> [RotationSlot]
    static func ordered(_ cards: [CardSnapshot], salt: String) -> [CardSnapshot]
}
```

### 4.4 `Shared/Models/`（SwiftData，仅 App 写）

```swift
@Model final class ReviewDeck {
    var id: UUID
    var title: String
    var sourceFileName: String?
    var sourceKind: String        // "pdf" | "imported"
    var summary: String?
    var sourceText: String?       // 原文前 40_000 字，供「提问」页当上下文
    var createdAt: Date
    var updatedAt: Date
    var isArchived: Bool
    @Relationship(deleteRule: .cascade, inverse: \ReviewCard.deck) var cards: [ReviewCard]
}

@Model final class ReviewCard {
    var id: UUID
    var question: String
    var answer: String
    var detail: String?
    var tags: [String]
    var sourcePage: Int?
    var difficulty: Int           // 1...5
    var importance: Int           // 1...5
    var isFavorite: Bool
    var origin: String            // "analysis" | "ask" | "manual"
    var createdAt: Date
    @Relationship(deleteRule: .cascade, inverse: \CardDisplayRecord.card) var displays: [CardDisplayRecord]
    var deck: ReviewDeck?
}

@Model final class CardDisplayRecord {
    var id: UUID
    var shownAt: Date
    var slotIndex: Int
    var surface: String           // "widget" | "app"
    var card: ReviewCard?
}

/// 一次提问的记录。**与 ReviewCard 没有 SwiftData 关系**：
/// 卡片可以单独删除、也可能被移到别的牌组，用关系会在删除时级联或置空，
/// 而提问历史应当独立存在。所以只留普通字段 savedCardID / deckID。
@Model final class AskThread {
    var id: UUID
    var question: String
    var answer: String
    var worthSaving: Bool
    var reason: String?
    var deckID: UUID?
    var deckTitle: String?
    var draftData: Data?          // AnalysisDocument.CardItem 的 JSON
    var savedCardID: UUID?
    var createdAt: Date
}
```

**为什么 `sourceText` 只存前 40 000 字**：一份 79 页讲义的原文约 2.6 万字，存全文会让每份牌组多占几十 KB 到几百 KB；而问答只需要「够模型判断上下文」的量。超出部分截断，prompt 里也会说明「只看到前一部分」。

**为什么 `origin` 带默认值**：SwiftData 的轻量迁移只对「有默认值的新属性」安全。老库里的卡片读出来 `origin` 是 `"analysis"`，符合事实——提问功能上线前所有卡片都是分析产生的。

`AnalysisDocument` 是 **Codable 交换格式**，不是 SwiftData 模型（见 `Shared/Models/AnalysisDocument.swift` 与格式文档）。

### 4.5 `Shared/Store/CardStore.swift`（`@MainActor`，仅 App）

```swift
@MainActor final class CardStore: ObservableObject {
    static let shared: CardStore
    let container: ModelContainer
    var context: ModelContext

    func refreshRotationCache() throws           // 重写 JSON，签名变化时换 orderSalt
    func backlogHistory(upTo date: Date) throws  // 回填已过去的 slot 到 CardDisplayRecord
    func bumpManualOffset() throws               // 「下一张」：+1 并写回 cache
    func save() throws

    // 写入
    @discardableResult
    func insertDeck(title: String, sourceFileName: String?, sourceKind: String,
                    pageCount: Int, summary: String?, language: String?,
                    sourceText: String? = nil,
                    cards: [AnalysisDocument.CardItem]) throws -> UUID
    @discardableResult
    func insertCard(into deck: ReviewDeck, question: String, answer: String,
                    detail: String? = nil, tags: [String] = [], sourcePage: Int? = nil,
                    difficulty: Int = 3, importance: Int = 3,
                    origin: String = ReviewCard.Origin.manual) throws -> UUID

    // 提问记录
    @discardableResult
    func insertAskThread(question: String, answer: String, worthSaving: Bool,
                         reason: String?, deckID: UUID?, deckTitle: String?,
                         draft: AnalysisDocument.CardItem?) throws -> UUID
    func markThreadSaved(threadID: UUID, cardID: UUID) throws
    func askThread(withID id: UUID) -> AskThread?
    func askThreads(limit: Int = 100) -> [AskThread]
    func delete(askThread: AskThread) throws
}
```

**`insertCard` 必须调 `refreshRotationCache()`**：用户保存一张卡之后，期待的是「它已经进了轮换池」，而不是「下次启动才生效」。这和 `insertDeck` 的处理一致。

### 4.6 服务层

```swift
struct TextChunk { var index: Int; var pageRange: ClosedRange<Int>; var text: String }

enum PDFTextExtractor {
    struct Extraction { var pageCount: Int; var pages: [String]; var fullText: String; var hasTextLayer: Bool }
    static func extract(from url: URL) throws -> Extraction
    static func chunk(_ e: Extraction, maxChars: Int) -> [TextChunk]
}

struct AIRequestConfig { var baseURL: URL; var model: String; var apiKey: String }

enum AIError: Error, LocalizedError {
    case missingConfiguration, network(String), http(Int, String), invalidResponse(String), decoding(String)
}

actor AIClient {
    func analyze(chunks: [TextChunk], title: String, config: AIRequestConfig,
                 cardsPerChunk: Int,
                 progress: @Sendable @escaping (AnalysisProgress) -> Void) async throws -> AnalysisDocument

    // 问答：先回答，再判断值不值得做成卡片。
    // context 为空时降级到「卡片题面摘要」或「通用知识」，prompt 里会要求模型不要编造。
    func ask(question: String, deckTitle: String, context: String,
             cardsDigest: [String],
             config: AIRequestConfig) async throws -> AskResult
}

/// 分析进度。带块号与已产出卡片数，界面才能显示「第 3/8 块」「已生成 18 张」。
struct AnalysisProgress: Sendable, Equatable {
    var fraction: Double          // 0...1
    var chunkIndex: Int           // 1 起
    var chunkTotal: Int
    var cardsSoFar: Int
    var recentQuestions: [String] // 最近一块产出的题面，供逐块翻入动画
}

/// 一次提问的结果。worthSaving 为 true 时 draft 必有值
/// （模型说值得却给不出可用卡的，视作不值得）。
struct AskResult: Sendable, Equatable {
    var answer: String
    var worthSaving: Bool
    var reason: String?
    var draft: AnalysisDocument.CardItem?
}

enum AnalysisImporter {
    static func decode(from url: URL) throws -> AnalysisDocument
    static func validate(_ data: Data) throws
    static func encode(_ doc: AnalysisDocument) throws -> Data
}

enum KeychainStore {
    static func set(_ value: String, for key: String) throws
    static func get(_ key: String) -> String?
    static func remove(_ key: String)
}

enum AnalysisKeys {                       // Keychain/UserDefaults 键名
    static let apiKey = "ai.apiKey"
    static let baseURL = "ai.baseURL"     // UserDefaults
    static let model = "ai.model"         // UserDefaults
}
```

### 4.7 `Shared/Service/AppSettings.swift`

```swift
@MainActor final class AppSettings: ObservableObject {
    static let shared: AppSettings
    @Published var baseURLString: String     // 默认 "https://api.openai.com/v1"
    @Published var model: String             // 默认 "gpt-4o-mini"
    @Published var rotationIntervalHours: Double   // 默认 3
    @Published var cardsPerSlot: Int               // 默认 1
    var apiKey: String { get set }           // 走 Keychain
}
```

## 5. App Intent 契约

| Intent | 作用 | 落点 |
|---|---|---|
| `NextCardIntent` | 小组件「下一张」 | `manualOffset += 1` 写 App Group defaults + cache，`reloadTimelines` |
| `ToggleFavoriteIntent`（基于 `CardSnapshot.id`） | 收藏/取消 | 写 `favoriteIDs` 集合到 App Group defaults，Widget 读该集合覆盖 `isFavorite`；App 启动时回灌 SwiftData |

Widget 不写 SwiftData；Intent 只写 App Group 的轻量状态。

### 5.1 无 App Groups 时的降级路径（内置种子）

App Groups 要求 provisioning profile 绑定**明确的 App ID** 并登记该 group。
侧载场景（免费 Apple ID、以及国内常见的通配符描述文件企业签名）通常不满足，
`FileManager.containerURL(forSecurityApplicationGroupIdentifier:)` 会返回 nil 或
给出一个不可写目录。这时小组件与 App 是两个互不相通的沙盒，**App 写的数据
小组件永远读不到**，桌面会一直是空态。

处理方式是随包预置一份内容，让「装完就有东西可看」，而不是显示一句
永远等不到的「导入 PDF 后即可复习」。

| 环节 | 落点 | 说明 |
|---|---|---|
| 种子源 | `PdfReview/Resources/bundled-deck.pdfreview.json` | 与用户手动导入的格式完全相同，走同一套 `AnalysisDocument` + `AnalysisValidator` |
| 生成小组件缓存 | `PdfReviewWidget/Resources/bundled-wheel.json` | 由 `scripts/build_seed_cache.py` 从上面那份生成，**同一份内容两种编码** |
| Widget 读取 | `RotationCache.resolve(bundle:)` | 三级：共享容器 → 本进程容器里的副本 → 内置种子 |
| Widget 写入 | `RotationCache.seedOwnContainerIfNeeded(bundle:)` | 读到种子后复制进自己容器，否则 `NextCardIntent` 的写盘无处落地 |
| App 读取 | `CardStore.importSeedDeckIfNeeded(bundle:)` | 首次启动导入成一幅 `ReviewDeck`，用 `SharedKeys.seedImported` 保证只导一次 |

**命名要分清**：`bundled-wheel.json` 是随包发布的**只读副本**；
`rotation-cache.json` 是 App 运行时写进 App Group 容器的**可变缓存**
（见 §4.2 与 `AppGroup.cacheFileURL`）。两者格式相同但生命周期不同，
不要混用同一个名字，否则排查「读到的到底是包里的还是刚写的」会很费劲。

两条必须守住的性质：

1. **`epoch` 必须固定为常量**（当前 `2026-01-01T00:00:00Z`），不能取「首次启动时间」。
   `slotIndex = floor((now - epoch) / intervalHours) + manualOffset`，
   epoch 一旦随设备/安装时间变化，各设备算出的槽位就不同，重装后轮换位置还会跳变。
2. **卡片 ID 由题面文本派生**（`stable_uuid`，`scripts/build_seed_cache.py`），
   不能是随机 UUID。种子重新生成时 ID 必须不变，否则用户收藏会全部丢失。

小组件据此区分空态文案：`RotationEntry.source == .bundledSeed` 时说明
「当前签名缺少 App Groups 能力」，而不是让用户以为导入功能坏了。

## 6. 目录结构

```
Shared/            双 target 编译（Core 两端；Models / Store / Service 仅 App）
PdfReview/         主 App（Views / Resources）
PdfReviewWidget/   小组件扩展
docs/              架构、格式、搭建、自检
schema/  samples/  scripts/
```

两个种子资源分属不同 target，不能合并成一个：

```
PdfReview/Resources/bundled-deck.pdfreview.json         → App target Resources
PdfReviewWidget/Resources/bundled-wheel.json            → Widget target Resources
```

它们**不是**同一份文件的副本：前者是 `AnalysisDocument`（`cards` 用
`question`/`answer` 等业务字段），后者是 `RotationCache`（`cards` 用
`CardSnapshot`，多出 `deckTitle`/`isFavorite`、日期为刻度基准）。让它们保持
同源靠的是 `scripts/build_seed_cache.py` 单向生成，不是手工同步。

## 7. 一致性红线

1. `RotationScheduler` 必须是纯函数，**不得**读 SwiftData、网络、时钟（时间由参数传入）。
2. `RotationCache` 字段只增不改；改语义必须升 `version`。
3. Widget target **不得** `import SwiftData`。
4. App 的 `AnalysisDocument` 结构与 `schema/analysis.v1.schema.json` 必须一致。
5. 所有面向用户的文案使用简体中文。
6. 种子的 `epoch` 与卡片 ID 必须可复现（常量 + 文本派生），**不得**引入随机或时钟相关的初值。
7. `AskThread` **不得** 加 `@Relationship` 指向 `ReviewCard` 或 `ReviewDeck`。卡片会被人删、会换牌组，提问历史必须独立存活。
8. 新增的 SwiftData 属性**必须带默认值**（`origin: String = "analysis"`、`sourceText: String? = nil`）。没有默认值的非可选新属性会让老库无法轻量迁移，用户升级即崩。
