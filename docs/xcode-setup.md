# Mac 端搭建与运行指南

本文写给**第一次在 Mac 上打开这份源码**的人：从打开工程、修签名、跑起来，到确认小组件真的在转。

> **先说清楚一件事**
> 仓库里的 `PdfReview.xcodeproj/project.pbxproj` 是由 `scripts/generate_pbxproj.py` 在 Windows 上生成的，
> **从未在 Xcode 里编译验证过**。因此本文把「打开现成工程」和「从零手工重建」两条路都写了。
> 如果第 1 节走通，就跳到第 3 节；走不通，直接从第 2 节开始重建。

---

## 0. 动手前必须知道的事（当前状态）

> 本节在最后一次核对时与仓库实况一致。若代码比文档新，以代码为准。

### 0.1 已经修好的两项（你不用再动手）

| 曾经的问题 | 现状 | 证据（可自行复核） |
|---|---|---|
| App target 没有 `@main` 入口 | **已修复** | `PdfReview/PdfReviewApp.swift` 存在，`@main struct PdfReviewApp: App` |
| Widget target 被编入 SwiftData 文件 | **已修复** | `scripts/generate_pbxproj.py:54` `SHARED_CORE_PREFIX = "Shared/Core/"`；`:171` `widget_sources = sorted(set(shared_core) \| set(widget_swift))`；`:180` 有回退断言 |

复核命令（在项目根目录）：

```bash
grep -n "SHARED_CORE_PREFIX\|shared_core" scripts/generate_pbxproj.py
python3 scripts/generate_pbxproj.py --check      # 应输出「自检通过：括号配平、对象 ID 全部闭合、必需段齐全。」
```

**入口 `PdfReviewApp.swift` 的要点**（供核对，不必重写）：

- `@main struct PdfReviewApp: App`
- `@StateObject private var store = CardStore.shared`、`@StateObject private var settings = AppSettings.shared`
- `.modelContainer(store.container)`
- `scenePhase == .active` 时 **先 `backlogHistory()`、再 `refreshRotationCache()`**——顺序不能反，
  否则刚过去的那个槽位会被新缓存口径覆盖，历史里少一条

### 0.2 仍然存在的缺口：`RootView` 引用了 4 个还没写的视图

`PdfReview/RootView.swift`（76 行）用 `TabView` 挂了四个标签页，但这四个类型
**全项目都没有定义**，App target 现在仍会在这些行上报 `Cannot find 'XxxView' in scope`：

| 引用处（`PdfReview/RootView.swift`） | 需要的类型 | 是否存在 |
|---|---|---|
| `ReviewView()` | `ReviewView` | ❌ 无定义 |
| `DeckListView()` | `DeckListView` | ❌ 无定义 |
| `HistoryView()` | `HistoryView` | ❌ 无定义 |
| `SettingsView()` | `SettingsView` | ❌ 无定义 |
| `OnboardingView()` | `OnboardingView` | ✅ `PdfReview/Views/OnboardingView.swift` |

> `TabView` 是 SwiftUI 自带类型，不需要定义。`scripts/check_swift_consistency.py` 会把它也列进
> 「疑似未定义」——那是正则近似检查的已知误报，可忽略（或把 `TabView` 加进脚本的 `FRAMEWORK_TYPES`）。

**补法**：在 `PdfReview/Views/` 下各建一个文件（都属于 App target），先给最小实现跑通，
再逐个替换成真实界面：

```swift
// PdfReview/Views/ReviewView.swift
import SwiftUI

struct ReviewView: View {
    @EnvironmentObject private var store: CardStore

    var body: some View {
        Text("复习")            // TODO: 接 store 的当前卡片
    }
}
```

`DeckListView` / `HistoryView` / `SettingsView` 同样处理。
`PdfReview/Views/Components/` 下已有 `EmptyHintView`、`Formatting`、`PrimaryButton`、`StatTile`、`TagChips`
可以复用（例如空列表用 `EmptyHintView`、统计块用 `StatTile`、标签用 `TagChips`）。

---

## 1. 打开现成工程

### 1.1 正常路径

1. 在 Finder 里进到项目根目录 `pdf-review/`。
2. 双击 `PdfReview.xcodeproj`。
3. 或者先开 Xcode → `File ▸ Open…` → 选 `PdfReview.xcodeproj`。

### 1.2 如果 Xcode 说打不开 / 工程损坏 / 只有空窗口

按顺序排查：

| 现象 | 检查 | 处理 |
|---|---|---|
| 双击没反应，或提示「无法打开」 | 确认 `PdfReview.xcodeproj/` 里到底有没有 `project.pbxproj` | 没有的话生成它，见下 |
| 能打开但左侧导航栏空 | 同上，`project.pbxproj` 缺失或为 0 字节 | 见下 |
| 提示「The project 'PdfReview' is damaged」 | 文件不完整 | 删掉 `.xcodeproj` 目录，重新生成 |

**重新生成工程**（在项目根目录执行）：

```bash
cd pdf-review
python3 scripts/generate_pbxproj.py           # 写入 PdfReview.xcodeproj/project.pbxproj
python3 scripts/generate_pbxproj.py --check   # 只自检，不写盘
```

`--check` 正常应输出：

```
自检通过：括号配平、对象 ID 全部闭合、必需段齐全。
```

如果生成后 Xcode 仍打不开，**不要再折腾**，直接用第 2 节手工重建——生成脚本只保证结构配平，
不保证 Xcode 的所有隐性要求（如 `PBXFileSystemSynchronizedRootGroup`、资源标签等）。

---

## 2. 手工重建工程（完整步骤）

全程在 Xcode 里点，**不要**去手改 `project.pbxproj`。

### 2.1 建 App 工程

`File ▸ New ▸ Project…`（⇧⌘N）：

| 项 | 填什么 |
|---|---|
| 平台 | iOS |
| 模板 | App |
| Product Name | `PdfReview` |
| Team | 你的 Apple ID（免费账号可选 "Personal Team"） |
| Organization Identifier | `com.pdfreview`（或你自己的反域名） |
| Bundle Identifier | 会自动拼成 `com.pdfreview.PdfReview`，**建完手动改成 `com.pdfreview.app`** |
| Interface | **SwiftUI** |
| Language | **Swift** |
| Storage | None（我们用 SwiftData，但不要勾，勾了会生成模板代码） |
| Include Tests | 不勾 |

建好后：选中工程 → `General` → **Minimum Deployments** 改成 **iOS 17.0**。
（低于 17.0 会直接报 `No such module 'SwiftData'`。）

同样在 `Build Settings` 里确认：

| 设置项 | 值 |
|---|---|
| `IPHONEOS_DEPLOYMENT_TARGET` | `17.0` |
| `SWIFT_VERSION` | `5.0` |
| `TARGETED_DEVICE_FAMILY` | `1,2`（iPhone + iPad） |
| `GENERATE_INFOPLIST_FILE` | **`NO`**（我们用仓库里的 Info.plist） |
| `MARKETING_VERSION` | `1.0` |
| `CURRENT_PROJECT_VERSION` | `1` |

删掉模板自动生成的 `ContentView.swift` 和 `PdfReviewApp.swift` 占位（入口按第 0 节缺口 1 自己写）。

### 2.2 加 Widget Extension target

`File ▸ New ▸ Target…` → **Widget Extension**：

| 项 | 填什么 |
|---|---|
| Product Name | `PdfReviewWidget` |
| Team | **和 App 同一个 Team** |
| Include Configuration Intent | **不勾** |
| Include Live Activity | 不勾 |

> **为什么不勾 Configuration Intent**：我们用的是 `StaticConfiguration`，
> 见 `PdfReviewWidget/PdfReviewWidget.swift`（`kind: "PdfReviewWidget"`）。
> 勾了会引入 `AppIntentConfiguration` 和一套 `ConfigurationIntent` 文件，
> 和现有代码的 `SupportedFamilies`、`Provider` 签名对不上，反而编译报错。

建完**立刻**把 Widget target 的 Bundle Identifier 改成 **`com.pdfreview.app.widget`**，
即 App Bundle ID + `.widget`。这条不能错——扩展的 Bundle ID 必须是宿主 App 的子标识符，否则安装时被拒。

Xcode 会问「Activate PdfReviewWidget scheme?」→ 选 **Activate**（后面冒烟测试要切换 scheme）。

**删掉**模板自动生成的 `PdfReviewWidget.swift` / `PdfReviewWidgetBundle.swift` 里的示例代码，
用仓库 `PdfReviewWidget/` 下的文件替换（见 2.5）。

Widget target 的 Build Settings 额外确认：

| 设置项 | 值 |
|---|---|
| `IPHONEOS_DEPLOYMENT_TARGET` | `17.0` |
| `SWIFT_VERSION` | `5.0` |
| `SKIP_INSTALL` | `YES` |
| `GENERATE_INFOPLIST_FILE` | **`NO`** |
| `LD_RUNPATH_SEARCH_PATHS` | 含 `@executable_path/../../Frameworks` |

### 2.3 加 App Group capability（**最容易踩的坑**）

**两个 target 都要加，一个都不能漏。**

对 **PdfReview** target：`Signing & Capabilities` → 左上 `+ Capability` → 搜 **App Groups** → 双击添加
→ 在 App Groups 列表里点 `+` → 输入 `group.com.pdfreview.app`。

对 **PdfReviewWidget** target：**重复同样的操作**，添加同一个 `group.com.pdfreview.app`。

> 只给 App 加、忘了给 Widget 加，是最常见的失败：App 能跑，小组件永远空白，
> 因为扩展读不到共享容器（`AppGroup.containerURL` 返回 nil）。

三处标识符必须完全一致，任何一处不同都会静默失败：

1. App target 的 App Groups capability → `group.com.pdfreview.app`
2. Widget target 的 App Groups capability → `group.com.pdfreview.app`
3. `Shared/Core/AppGroup.swift` 里的 `static let identifier = "group.com.pdfreview.app"`

**如果你改了 Bundle ID**（比如 `com.pdfreview.app` 已被占用，换成 `com.yourname.pdfreview`），
那么 App Group 也要改名（如 `group.com.yourname.pdfreview`），并且**必须同步改**
`Shared/Core/AppGroup.swift` 的 `identifier` 常量，否则 App 写进一个容器、Widget 去另一个容器读。

### 2.4 配 Info.plist 与 entitlements

两个 target 都用仓库里现成的文件，**不要**让 Xcode 自动生成。

**PdfReview target**：

- `Build Settings ▸ INFOPLIST_FILE` = `PdfReview/Resources/Info.plist`
- `Build Settings ▸ CODE_SIGN_ENTITLEMENTS` = `PdfReview/Resources/PdfReview.entitlements`
- `GENERATE_INFOPLIST_FILE` = `NO`

**PdfReviewWidget target**：

- `INFOPLIST_FILE` = `PdfReviewWidget/Resources/Info.plist`
- `CODE_SIGN_ENTITLEMENTS` = `PdfReviewWidget/Resources/PdfReviewWidget.entitlements`
- `GENERATE_INFOPLIST_FILE` = `NO`

两份 Info.plist 的关键键（已在仓库文件里配好，此处供核对）：

| 键 | App | Widget |
|---|---|---|
| `CFBundleDisplayName` | `PDF 复习` | `PDF 复习卡片` |
| `NSExtension ▸ NSExtensionPointIdentifier` | — | **`com.apple.widgetkit-extension`** |
| `NSExtensionPrincipalClass` | — | **不要有**（WidgetKit 不需要，有反而崩） |
| `UIFileSharingEnabled` | `true` | — |
| `LSSupportsOpeningDocumentsInPlace` | `true` | — |

> `UIFileSharingEnabled` + `LSSupportsOpeningDocumentsInPlace` 是给「从文件 App 导入 PDF」用的，
> 少一个在模拟器里就看不到共享目录。

> **ℹ️ 关于 `UIRequiredDeviceCapabilities`（当前文件已无此键）**
> 仓库里的 `PdfReview/Resources/Info.plist` **已经删掉了整个 `UIRequiredDeviceCapabilities` 键**，
> 这是对的：本 App 没有摄像头、AR、陀螺仪这类必须声明的硬件依赖，
> 不写这个键就是「不限制设备」。
>
> **但如果你自己加回来，不要填 `armv7`。** `armv7` 是 32 位旧能力，
> 现代 arm64 iPhone/iPad 都不上报它，真机会直接装不上（报「此 App 与此设备不兼容」），
> 而模拟器不校验这一点，很容易到真机才发现。确实要声明就填 `arm64`。

### 2.5 把源文件加进正确的 target

在 Finder 里把 `Shared/`、`PdfReview/`、`PdfReviewWidget/` 三个目录拖进 Xcode 导航栏
（**勾掉 "Copy items if needed"**，保持文件原地）。

添加时弹出的对话框里，`Add to targets` **先全部不勾**，之后按下面的表逐个设置——
因为同一个文件对不同 target 的归属是不同的。

给任意文件改归属：选中文件 → 右侧 `File Inspector`（⌥⌘1）→ `Target Membership` 里勾选对应 target。

### 2.6 逐文件目标归属表（**按实际 import 判定**）

判定规则很简单：**文件 `import SwiftData` 或只在 App 侧被用到 → 只进 App**；
**只依赖 `Foundation` 且 Widget 侧真的引用 → 两个 target 都进**。

#### `Shared/Core/` —— **两个 target 都勾**

| 文件 | import | App | Widget | 理由 |
|---|---|:---:|:---:|---|
| `Shared/Core/AppGroup.swift` | Foundation | ✅ | ✅ | 共享容器路径，两端都要读写 `rotation-cache.json` |
| `Shared/Core/RotationCache.swift` | Foundation | ✅ | ✅ | 缓存模型的编解码，两端都要 |
| `Shared/Core/RotationScheduler.swift` | Foundation | ✅ | ✅ | 槽位计算，Widget 侧 `RotationProvider` 直接调 |

#### `Shared/Models/` —— **只勾 App**

| 文件 | import | App | Widget | 理由 |
|---|---|:---:|:---:|---|
| `Shared/Models/AnalysisDocument.swift` | Foundation | ✅ | ❌ | 导入格式，只有 App 解析 |
| `Shared/Models/CardDisplayRecord.swift` | Foundation, **SwiftData** | ✅ | ❌ | `@Model`，Widget 不能碰 SwiftData |
| `Shared/Models/ReviewCard.swift` | Foundation, **SwiftData** | ✅ | ❌ | 同上 |
| `Shared/Models/ReviewDeck.swift` | Foundation, **SwiftData** | ✅ | ❌ | 同上 |

#### `Shared/Service/` —— **只勾 App**

| 文件 | import | App | Widget | 理由 |
|---|---|:---:|:---:|---|
| `Shared/Service/AIClient.swift` | Foundation | ✅ | ❌ | 网络调用只在 App 侧发生 |
| `Shared/Service/AnalysisImporter.swift` | Foundation, UniformTypeIdentifiers | ✅ | ❌ | 文件导入，App 专用 |
| `Shared/Service/AppSettings.swift` | Foundation, Combine | ✅ | ❌ | `@MainActor` + `@Published`，App 侧设置界面用 |
| `Shared/Service/KeychainStore.swift` | Foundation, Security | ✅ | ❌ | 存 API Key，Widget 不应持有凭据 |
| `Shared/Service/PDFTextExtractor.swift` | Foundation, **PDFKit** | ✅ | ❌ | PDFKit 太重，Widget 无此需求 |

#### `Shared/Store/` —— **只勾 App**

| 文件 | import | App | Widget | 理由 |
|---|---|:---:|:---:|---|
| `Shared/Store/CardStore.swift` | Foundation, **SwiftData**, WidgetKit | ✅ | ❌ | SwiftData 容器 + `ModelContext`，Widget 绝不能编进来 |

#### `PdfReview/` —— **只勾 App**

| 文件 | App | Widget |
|---|:---:|:---:|
| `PdfReview/PdfReviewApp.swift`（第 0 节缺口 1 需你自己创建） | ✅ | ❌ |
| `PdfReview/Views/Components/{EmptyHintView,Formatting,PrimaryButton,StatTile,TagChips}.swift` | ✅ | ❌ |

#### `PdfReviewWidget/` —— **只勾 Widget**

| 文件 | App | Widget | 说明 |
|---|:---:|:---:|---|
| `PdfReviewWidget/PdfReviewWidgetBundle.swift` | ❌ | ✅ | **含 `@main`（:11）** |
| `PdfReviewWidget/PdfReviewWidget.swift` | ❌ | ✅ | `StaticConfiguration(kind: "PdfReviewWidget")` |
| `PdfReviewWidget/RotationProvider.swift` | ❌ | ✅ | TimelineProvider；`RotationWidgetKeys` 定义在 :18 |
| `PdfReviewWidget/CardViews.swift` | ❌ | ✅ | 各尺寸卡片视图 |
| `PdfReviewWidget/NextCardIntent.swift` | ❌ | ✅ | AppIntent，「下一张」 |
| `PdfReviewWidget/FavoriteIntent.swift` | ❌ | ✅ | AppIntent，「收藏」 |

#### 资源文件

| 文件 | 归属 |
|---|---|
| `PdfReview/Resources/Assets.xcassets` | App target 的 `Copy Bundle Resources` |
| `PdfReviewWidget/Resources/Assets.xcassets` | Widget target 的 `Copy Bundle Resources` |
| `PdfReview/Resources/Info.plist` | **不加入任何 target**（由 `INFOPLIST_FILE` 引用） |
| `PdfReviewWidget/Resources/Info.plist` | **不加入任何 target**（同上） |
| `*.entitlements` | **不加入任何 target**（由 `CODE_SIGN_ENTITLEMENTS` 引用） |

> 两个 Info.plist 若被加进 `Copy Bundle Resources`，会报
> 「Multiple commands produce …/Info.plist」。这是白搭进去的半小时，别踩。

### 2.7 确认扩展被嵌入

选中 **PdfReview** target → `Build Phases` → 应该有 **`Embed Foundation Extensions`** 阶段，
里面包含 `PdfReviewWidget.appex`，`Destination` 为 `PlugIns`，勾选 `Code Sign On Copy`、`Remove Headers On Copy`。

没有这个阶段，去 `General ▸ Frameworks, Libraries, and Embedded Content` 里
把 `PdfReviewWidget.appex` 加进来并设为 **Embed & Sign**。

同时确认 `Build Phases ▸ Dependencies` 里有 `PdfReviewWidget`（保证先编扩展再编 App）。

### 2.8 重建后的目录对照

搭建完成后，Xcode 导航栏应该长这样（✅ = 已存在，⬜ = 需你补）：

```
PdfReview.xcodeproj
PdfReview/
├── PdfReviewApp.swift          ⬜ 缺口 1，自己建
├── Views/
│   ├── <根视图>.swift           ⬜ 自己建（目前没有主界面）
│   └── Components/             ✅ EmptyHintView / Formatting / PrimaryButton
│                               ✅ StatTile / TagChips
└── Resources/
    ├── Info.plist              ✅
    ├── PdfReview.entitlements  ✅
    └── Assets.xcassets         ✅
PdfReviewWidget/
├── PdfReviewWidgetBundle.swift ✅ @main
├── PdfReviewWidget.swift       ✅
├── RotationProvider.swift      ✅
├── CardViews.swift             ✅
├── NextCardIntent.swift        ✅
├── FavoriteIntent.swift        ✅
└── Resources/
    ├── Info.plist              ✅
    ├── PdfReviewWidget.entitlements ✅
    └── Assets.xcassets         ✅
Shared/
├── Core/    (3 文件，双 target) ✅
├── Models/  (4 文件，仅 App)    ✅
├── Service/ (5 文件，仅 App)    ✅
└── Store/   (1 文件，仅 App)    ✅
```

---

## 3. 签名与 Bundle ID

### 3.1 两个 target 的 Team 必须一致

选中工程 → 分别点 **PdfReview** 和 **PdfReviewWidget** → `Signing & Capabilities`：

- `Team` 选同一个 Apple ID
- `Automatically manage signing` 勾上
- `Bundle Identifier` 分别为 `com.pdfreview.app` 和 `com.pdfreview.app.widget`

> 两个 target Team 不一致 → 归档/安装时报「扩展签名与宿主不匹配」，
> 模拟器有时能装上但小组件不出现在列表里。

### 3.2 改了 Bundle ID 怎么办

如果 `com.pdfreview.app` 在你账号下被占用（或你想用自己的域名），要**同时**改四样：

1. App target 的 `PRODUCT_BUNDLE_IDENTIFIER` → 如 `com.yourname.pdfreview`
2. Widget target 的 `PRODUCT_BUNDLE_IDENTIFIER` → App 的 + `.widget`，即 `com.yourname.pdfreview.widget`
3. 两个 target 的 App Groups → 如 `group.com.yourname.pdfreview`
4. `Shared/Core/AppGroup.swift` 的 `static let identifier` → 与新 App Group 一致

漏掉第 4 步的表现：App 正常运行、能导入、能分析，但小组件永远显示占位。

### 3.3 免费账号的限制

免费 Apple ID 可以真机调试，但有约束：

- 描述文件 **7 天过期**，到期需重新 Run 一次
- 最多 3 个 App ID、最多 1 台设备
- **App Groups capability 需要付费开发者账号**（$99/年）

> 这条很关键：用免费账号时，App Groups 在真机上很可能不可用，
> `AppGroup.containerURL` 会走降级分支（落到 App 自己的 Documents），
> 此时**小组件读不到数据，属于预期失败**。要完整验证小组件，必须用付费账号，
> 或在模拟器上测（模拟器不校验 App Group 描述文件）。

---

## 4. 运行 App

1. Xcode 顶部 scheme 选 **PdfReview**（不是 PdfReviewWidget）。
2. 设备选一个 **iOS 17+ 的模拟器**（`iPhone 15` 之类）。
3. `⌘R`。
4. 首次启动可能弹「需要开启开发者模式」（真机），见第 6 节。

模拟器上验证 App 是否正常，看这几件事：能不能进主界面、能不能导入 PDF、历史记录有没有回填。

---

## 5. 添加小组件

1. 回到模拟器桌面（`⌘⇧H`）。
2. 长按桌面空白处，直到图标开始抖动。
3. 点左上角 **`+`**。
4. 搜索框输入 **`PDF 复习`**（如果搜不到，搜 `PdfReview` 或 `PDF`）。
5. 选一个尺寸（Small / Medium / Large 都支持），点 **Add Widget**。
6. 点空白处退出抖动。

> **长按后左上角是 `+` 还是 `Edit`**：iOS 17 是 `+`。若看到的是 `Edit`，先点 `Customize` 再找 `+`。
> 注入 Widget 前必须先**至少运行一次 App**（让 Xcode 把 App 和 .appex 一起装上），
> 否则小组件列表里根本不会有这一项。

锁屏小组件（accessory 系列）：锁屏长按 → `Customize` → 选锁屏 → 添加 `PDF 复习卡片`。
支持 `accessoryRectangular` 和 `accessoryInline` 两种。

---

## 6. 真机运行的额外步骤

1. **开发者模式**：iPhone → `设置 ▸ 隐私与安全性 ▸ 开发者模式` → 打开 → 重启手机 → 重启后确认。
   （iOS 16+ 必需；不打开时 Xcode 报 `Developer Mode disabled`。）
2. **信任开发者证书**：首次 Run 后，手机会提示「不受信任的开发者」。
   `设置 ▸ 通用 ▸ VPN与设备管理` → 找到你的 Apple ID → **信任**。
3. **设备配对**：用数据线连 Mac，手机点「信任此电脑」，Xcode 顶部设备列表里能看到机型名。
4. **App Group 注册**：真机上 App Group 必须已在开发者账号后台注册（Xcode 勾 capability 时会自动尝试注册）。
   免费账号此处大概率失败，见 3.3。

---

## 7. 常见报错对照表

| # | 现象 | 原因 | 解决 |
|---|---|---|---|
| 1 | `Cannot find 'AppGroup' in scope` / `Cannot find 'RotationCache' in scope` | `Shared/Core/` 的文件没加进当前 target 的 Compile Sources | 按 **2.6** 表逐个勾 Target Membership；Widget target 至少要 `Shared/Core/` 三个文件 |
| 2 | `No such module 'SwiftData'` | 部署版本低于 iOS 17.0 | 两个 target 的 `IPHONEOS_DEPLOYMENT_TARGET` 都改 `17.0`（2.1 / 2.2） |
| 3 | 小组件一直显示占位/空白，App 里数据正常 | ①App Group 没配或两端不一致 ②App 还没写 `rotation-cache.json` ③Widget 编进了 SwiftData | ①按 **3.1/3.2** 对齐三处标识符 ②先跑 App、导入至少一个 deck ③按 **2.6** 把 `Shared/Models`、`Shared/Store` 从 Widget target 移除 |
| 4 | `App Group 容器返回 nil`（运行时日志） | capability 没开，或描述文件未包含该 App Group | 两个 target 都加 App Groups（**2.3**）；真机需付费账号（**3.3**） |
| 5 | 扩展签名被拒 / `The operation couldn't be completed. (LaunchServicesError)` | 两个 target 的 Team 不一致，或 Widget Bundle ID 不是 App 的 `.widget` 子标识 | 见 **3.1**；Bundle ID 必须是 `com.pdfreview.app.widget` |
| 6 | `duplicate symbol '_main'` / 两个 `@main` | 同一个含 `@main` 的文件被加进了两个 target | `PdfReviewWidgetBundle.swift` 只勾 Widget；你新建的 `PdfReviewApp.swift` 只勾 App（**2.6**） |
| 7 | `Multiple commands produce .../Info.plist` | Info.plist 被加进了 `Copy Bundle Resources` | 从 Build Phases 的 Copy Bundle Resources 里移除（**2.6** 资源表） |
| 8 | 小组件装上后一直不换卡 | Timeline 刷新策略 + 系统调度延迟；也可能 `reloadAllTimelines()` 没被调到 | 见 **8.2**；App 内点「立即刷新小组件」（调 `CardStore.reloadWidgets()`）。系统对刷新频率有限流，前几次可能要等几分钟 |
| 9 | 导入 PDF 提示「无可提取文本」 | 扫描件（图片型 PDF）没有文本层 | 首版不支持 OCR（`PDFTextExtractor` 只取文本层）。换带文本层的 PDF，或先用其他工具 OCR |
| 10 | AI 分析报 `401 Unauthorized` | API Key 错，或 Base URL 与 Key 的供应商不匹配 | 设置里核对 `baseURL`（默认 `https://api.openai.com/v1`）、`model`（默认 `gpt-4o-mini`）与 Key 三者是否同一家 |
| 11 | `Build input file cannot be found: .../Info.plist` | `INFOPLIST_FILE` 路径写错，或 `GENERATE_INFOPLIST_FILE` 仍为 `YES` | 按 **2.4** 核对路径，并设为 `NO` |
| 12 | Xcode 打开工程是空的 / 提示损坏 | `PdfReview.xcodeproj/project.pbxproj` 不存在或损坏 | 重新生成（**1.2**），或直接手工重建（**第 2 节**） |
| 13 | 编译报 `'main' attribute cannot be used in a module that contains top-level code` | App target 里混进了 Widget 的 `@main` 文件 | 同 #6，检查 Target Membership |
| 14 | 真机安装报「此 App 与此设备不兼容」/ 模拟器正常 | `Info.plist` 的 `UIRequiredDeviceCapabilities` 写了 `armv7` | 改成 `arm64` 或删掉该键（见 **2.4** 的已知隐患提示） |

---

## 8. 5 分钟冒烟测试清单

按顺序做完，全部打勾才算搭好。**前提**：已按第 0 节补好 App 入口，已按 2.6 配好归属。

### 8.1 两个 target 都编过（约 1 分钟）

```bash
# 在项目根目录，列出两个 scheme 与它们的可编译性
xcodebuild -list -project PdfReview.xcodeproj

# 编 App（含扩展依赖）
xcodebuild -project PdfReview.xcodeproj -scheme PdfReview \
  -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 15' build
```

- [ ] `xcodebuild -list` 能看到 `PdfReview` 和 `PdfReviewWidget` 两个 scheme
- [ ] App scheme 编译 **`BUILD SUCCEEDED`**
- [ ] Widget scheme 单独编也 `BUILD SUCCEEDED`（scheme 切到 `PdfReviewWidget` 再 `⌘B`）
- [ ] 编译产物里有 `PdfReview.app/PlugIns/PdfReviewWidget.appex`：

  ```bash
  find ~/Library/Developer/Xcode/DerivedData -name "PdfReviewWidget.appex" -maxdepth 8
  ```

### 8.2 App 能跑、能写缓存（约 2 分钟）

- [ ] 模拟器 `⌘R` 启动 App，界面出现，无崩溃
- [ ] 导入一个**带文本层**的 PDF，提示成功
- [ ] 配置好 AI（Base URL + Key + model）后点分析，卡片列表出现内容
- [ ] 点「立即刷新小组件」，不报错

验证缓存文件真的落盘（模拟器路径）：

```bash
# 找到 App 的 App Group 容器
find ~/Library/Developer/CoreSimulator/Devices -type d \
  -name "group.com.pdfreview.app" 2>/dev/null | head -1
```

进去之后应该有 `rotation-cache.json`：

```bash
cat "<上一步的路径>/rotation-cache.json" | python3 -m json.tool | head -40
```

- [ ] 文件存在
- [ ] 顶层含 `version`（应为 `1`）、`intervalHours`（默认 `3`）、`cardsPerSlot`（默认 `1`）、`orderSalt`、`cards` 数组非空

> 若 `AppGroup.containerURL` 走降级分支（App Group 未生效），缓存会落在 App 自己的 Documents 里，
> 而不是 App Group 容器。此时小组件读不到——回到 **2.3** 检查 capability。

### 8.3 小组件真的每 3 小时换（约 1 分钟配置 + 观察）

- [ ] 按第 5 节把 Small 尺寸小组件加到桌面，显示的是**真实卡片**（不是占位文字）
- [ ] 点小组件上的「下一张」（`NextCardIntent`），卡片立即变化
- [ ] 点「收藏」（`FavoriteIntent`），星标状态切换，且 App 内历史记录里能看到收藏

确认 3 小时周期**配置**正确（不必真等 3 小时）：

```bash
# 看缓存里的间隔设置
python3 -c "
import json,glob
p=glob.glob('''<CoreSimulator 路径>/group.com.pdfreview.app/rotation-cache.json''')[0]
d=json.load(open(p))
print('intervalHours =',d['intervalHours'])
print('cardsPerSlot  =',d['cardsPerSlot'])
print('epoch         =',d['epoch'])
print('slot 数       =',len(d['cards']))
"
```

- [ ] `intervalHours` 为 `3`（对应 `AppSettings.defaultIntervalHours = 3`）
- [ ] `cardsPerSlot` 为 `1`

**要真的看到切换**，用「改槽位」而不是等 3 小时——在 App 里把间隔临时改成 `0.25` 小时（15 分钟）。
`AppSettings.rotationIntervalHours` 的允许范围是 `0.25…24`（`RotationCache.applySettings` 在
`RotationCache.swift:167` 会夹这个区间，`cardsPerSlot` 则在 :168 被夹到 `1…10`）。
然后等 15 分钟看小组件换卡。**测完记得改回 3**。

> 小组件刷新受系统限流：短时间内频繁 `reloadAllTimelines()` 会被系统忽略，
> 前几次刷新可能要等几分钟才生效。这不是 bug。

### 8.4 历史记录能回填（约 1 分钟）

- [ ] App 里打开历史记录页，能看到过去的槽位记录
- [ ] 记录里每条都有卡片问题、时间、以及来源标记（`CardDisplayRecord.Surface.widget` 表示由小组件触发）
- [ ] 新增一次「下一张」后，历史记录里多一条

首次回填逻辑：`CardStore.backlogHistory(upTo:)` 只回填**最近 8 个 slot**，单次上限 200 条。
所以首次进入看到 8 条左右是正常的，不是没生效。

---

## 9. 附：一键自检脚本

把下面存成 `scripts/smoke.sh`（**注意：本仓库的 `scripts/` 归生成脚本所有，加文件前先确认不会被打包**），
在 Mac 上 `chmod +x` 后运行：

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")/.."

echo "==> 1. 生成/校验工程文件"
python3 scripts/generate_pbxproj.py --check

echo "==> 2. scheme 列表"
xcodebuild -list -project PdfReview.xcodeproj

echo "==> 3. 编 App"
xcodebuild -project PdfReview.xcodeproj -scheme PdfReview \
  -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 15' \
  build | tail -20

echo "==> 4. .appex 是否嵌入"
find ~/Library/Developer/Xcode/DerivedData -name "PdfReviewWidget.appex" -maxdepth 8 | head -3

echo "==> 全部通过"
```

---

## 相关文档

- `docs/architecture.md` —— 目录结构、`AnalysisDocument` / `RotationCache` 契约、target 依赖红线
- `docs/pdf-analysis-format.md` —— `.pdfreview.json` v1 格式标准
- `schema/analysis.v1.schema.json` —— 分析文件的 JSON Schema
- `scripts/generate_pbxproj.py` —— 工程文件生成器（`--check` 可单独自检）
