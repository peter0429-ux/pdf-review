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
```

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
}
```

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
                 cardsPerChunk: Int, progress: @Sendable @escaping (Double) -> Void) async throws -> AnalysisDocument
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
Shared/            双 target 编译（Models / Store / Service）
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
