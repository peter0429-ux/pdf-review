# PDF Review（PdfReview）

一个 iOS App：上传 PDF，AI 提炼成复习卡片，在**桌面小组件**里每 3 小时自动轮换一张，帮你利用碎片时间复习。支持历史记录回看、收藏、离线导入/导出。

仓库里还有一个 **Windows 桌面版**（`pc/`）：同一套格式标准，支持 PDF / Word / PowerPoint / Excel / 纯文本 / Markdown / 网页 → `.pdfreview.json`，导出后传到手机上导入。适合「文档在电脑上、想先批量做完再导到手机」的场景。详见 [`pc/README.md`](pc/README.md)。

---

## ⚠️ 两条必须先读的事

### 1. 这个项目是 AI 写的

本仓库的源代码、工程文件（`project.pbxproj` 是脚本生成的）、文档与 CI 配置，**全部由一个 AI 编程代理编写**，人类只在需求层面做决策与验收。

这意味着什么，请照着对待：

| 事项 | 说明 |
|---|---|
| **不要当作生产级参考实现** | 它是能跑通、能过 CI 的完整工程，但缺少长期维护痕迹（无 issue 历史、无回归测试、无多设备实测）。 |
| **代码审查请照常做** | 每一行都值得怀疑。AI 会写出「看起来对、边界处错」的东西，也会写出自我说服式注释。 |
| **注释记录的是当时的推理** | 注释里大量写着「为什么这样做」，那是 AI 在写代码时给出的理由。理由可能是对的，也可能是事后编的，请自己判断。 |
| **已在真机上踩过的坑** | 见 `CHANGELOG.md`。历史上出现过：启动即闪退（构造时机问题）、文件选择器全部变灰（`.fileImporter` 喂了未注册的 UTI）、小组件拿不到数据（无 App Groups）。 |
| **编译验证在 CI 做** | 开发机是 Windows，没有 Xcode。所有编译验证靠 GitHub Actions 的 `macos-15` runner。 |

如果你要把它用进真实项目：请把它当成一份**可运行的原型 + 一份详细的踩坑记录**，而不是能直接依赖的库。

### 2. 小组件要正常工作，必须开 App Groups 权限

这是本项目**最容易踩、也最容易被忽略**的一点。

App 与桌面小组件是两个**独立进程**，各有各的沙盒。它们之间唯一的正规通路是 **App Group（`com.apple.security.application-groups`）** —— 一块两个进程都能读写的共享目录。

没有这个能力时会怎样：

- App 本身**能正常用**（导入 PDF、生成卡片、看历史、收藏，全都在）；
- 但桌面小组件**读不到** App 写的数据 → 一直显示空态或内置示例内容；
- 而且**不会报错、不会崩溃**，只是「小组件永远没东西」。这种静默失败最难查。

判断当前有没有生效：打开 App → **设置 → 关于 →「数据存储」那一行**
- 显示「共享容器（小组件可读）」→ 正常；
- 显示「App 本地（小组件读不到）」→ 没拿到 App Groups，小组件读不到你导入的内容。

#### 情况 A：你有开发者账号（推荐，功能完整）

在 Xcode 里两个 target 都勾上 App Groups，用同一个标识：

1. 选中 `PdfReview` target → **Signing & Capabilities** → **+ Capability** → **App Groups** → 添加 `group.com.pdfreview.app`；
2. 选中 `PdfReviewWidget` target → 同样添加 **同一个** `group.com.pdfreview.app`；
3. 两个 target 的 **Team** 必须是同一个；
4. 你的 App ID（`com.pdfreview.app`）在开发者后台要显式登记这个 App Group 标识符。

约束（苹果的硬规定，不是本项目的选择）：
- App Groups **必须绑定明确的 App ID**，**不能**用通配符（wildcard）描述文件；
- 组名必须与代码里 `Shared/Core/AppGroup.swift` 的 `AppGroup.identifier` 一致，改一处就要改三处（另两处见 `docs/xcode-setup.md` 3.2）。

#### 情况 B：你拿不到 App Groups（侧载 / 免费账号 / 通配符企业证书）

这时小组件读不到 App 的数据，**没有任何代码技巧能绕过** —— 这是 iOS 沙盒的边界。（CloudKit、iCloud Drive 同样需要在描述文件里登记容器，属于同一类限制；URL Scheme 只能唤起 App、传不了数据。）

可行做法是**「植入」**：把一份内容直接打进 App 包/小组件包，让它们各自本地就有一份可读数据，不依赖共享目录。

**B-1. 直接改内置示例内容（最简单，适合自用）**

随包已经内置了一套 24 张的示例牌组（`iOS 内存管理`）。把你自己准备好的内容换进去即可：

```bash
# 1. 准备一份符合格式标准的分析文件（格式见下方「分析文件格式」）
#    可以先在 App 里导入 PDF 生成，再用「设置 → 导出」导出成 .pdfreview.json

# 2. 替换 App 侧的内置牌组
cp 你的牌组.pdfreview.json PdfReview/Resources/bundled-deck.pdfreview.json

# 3. 重新生成小组件侧的内置轮换缓存
python scripts/build_seed_cache.py

# 4. 重新生成工程文件（如果文件清单没变可跳过）
python scripts/generate_pbxproj.py

# 5. 重新编译安装。首次启动会把内置牌组导入进 App。
```

想让「装完就重新导入一次」，把 `UserDefaults` 里的 `seed.deckImported` 清掉（重装 App 即可）。

限制：内容是**固定的**，不是你新导入的 PDF；换内容要重新打包。App 内自己导入的 PDF 依然能用（存在于 App 沙盒），只是同步不到桌面小组件。

**B-2. 用你自己的 App Group 名**

如果你的签名环境**能**提供 App Groups，但组名不是 `group.com.pdfreview.app`，把这些地方统一改掉：

| 位置 | 内容 |
|---|---|
| `scripts/generate_pbxproj.py` | `APP_GROUP` 常量（第 35 行附近） |
| `Shared/Core/AppGroup.swift` | `AppGroup.identifier`（第 30 行） |
| `PdfReview/Resources/PdfReview.entitlements` | `com.apple.security.application-groups` 数组 |
| `PdfReviewWidget/Resources/PdfReviewWidget.entitlements` | 同上 |

改完重跑 `python scripts/generate_pbxproj.py`，并在 Xcode / 签名工具里同步勾选该组名。

**B-3. 换签名方式**

三条路的取舍：

| 方式 | App Groups | 代价 |
|---|---|---|
| 免费 Apple ID 侧载 | ❌ | 7 天有效期，小组件收不到数据 |
| 付费开发者账号（$99/年） | ✅ | 有年费，功能完整 |
| 企业签名（明确 App ID + 登记过组） | ✅ | 依赖签名商；通配符描述文件**不行** |

---

## 功能一览

| 功能 | 说明 |
|---|---|
| PDF → 复习卡片 | 内置 PDFKit 文本抽取 + OpenAI 兼容接口分析，按 chunk 生成卡片 |
| 分析过程可视化 | 五步清单 + 环形进度 + 每块产出的卡片逐张翻入，能看出「卡住了还是在干活」 |
| 离线导入 | 支持 `.pdfreview.json` 格式（自建标准，见下） |
| 桌面小组件 | systemSmall/Medium/Large + 灵动岛配件（rectangular/inline/circular），显示当前卡片、历史与倒计时 |
| 自动轮换 | 默认每 3 小时换一张，间隔 0.25–24 小时可调；「下一张」按钮手动跳过 |
| 历史记录 | App 与小组件**共用同一套推算**，逐位一致 |
| 收藏 | 两端同步（App Group + UserDefaults） |
| 导出 | 任意牌组一键导出为 `.pdfreview.json`，可分享、可再次导入 |
| 内置示例内容 | 首次启动自动导入 24 张示例卡片，装完就有东西看 |
| 提问 | 就着牌组原文向 AI 提问；AI 判断值得记的，能一键变成一张卡片存进指定牌组，历史可翻回 |
| **Windows 桌面版** | 同一套格式标准，支持 7 种文档格式 → `.pdfreview.json`，见 [`pc/README.md`](pc/README.md) |

## 分析文件格式（自建标准）

`pdfreview.json` v1.0 —— 三份真相源保持一致：

- 机器可校验 Schema：`schema/analysis.v1.schema.json`（JSON Schema draft 2020-12）
- Swift 实现：`Shared/Models/AnalysisDocument.swift`（`AnalysisValidator`）
- **PC 实现：`pc/core/limits.py` + `pc/core/cards.py`**（独立的一套，常量逐字对齐）
- 人读文档：`docs/pdf-analysis-format.md`
- 示例：`samples/sample-analysis.json`（完整）、`samples/sample-analysis-minimal.json`（最小）

文件必须通过 8MB 上限 + 未知字段拒绝 + 全字段范围校验。校验错误全是中文描述。

`scripts/check_format_consistency.py` 会把 Swift / PC / schema 三方的常量逐项比对——任何一边改了另一边没跟上，CI 会红。这类偏差不会报错，只会让两边导入行为悄悄不一致，等到有用户碰到边界文件才暴露。

## 目录结构

```
pdf-review/
├── docs/                    # 架构文档 / 格式标准 / Xcode 手工搭建指南
│   ├── architecture.md      # 唯一真相源：架构契约
│   ├── pdf-analysis-format.md
│   └── xcode-setup.md       # 打不开工程时的手工重建指南（30 章节）
├── schema/                  # JSON Schema
├── samples/                 # 示例分析文件
├── scripts/                 # 生成器 + 全部静态检查脚本
│   ├── generate_pbxproj.py          # 生成 project.pbxproj
│   ├── check_pbxproj.py             # 独立解析+校验 pbxproj（自写 OpenStep 解析器）
│   ├── check_swift_consistency.py   # 跨文件类型可见性检查
│   ├── verify_static_check.py       # 上一条的反向测试（注入 bug 验证检查器真的会报）
│   ├── check_format_consistency.py  # schema/Swift/文档三方一致性
│   ├── build_seed_cache.py          # 把分析文件转成小组件用的内置轮换缓存
│   ├── verify_ipa.py                # 核验打出来的 IPA（架构/plist/内置资源）
│   └── grep_binary.py               # 在二进制里确认代码路径真被编进去
├── Shared/                  # 双端共享
│   ├── Core/                # ← 这三个文件编进 App 和 Widget 两个 target
│   │   ├── AppGroup.swift
│   │   ├── RotationCache.swift
│   │   └── RotationScheduler.swift
│   ├── Models/              # SwiftData 模型（仅 App target）
│   ├── Service/             # AI / PDF / Keychain / 设置 / 启动日志（仅 App target）
│   └── Store/               # CardStore（仅 App target）
├── PdfReview/               # App target（SwiftUI 视图）
│   └── Resources/           # 含 bundled-deck.pdfreview.json（内置示例牌组）
├── PdfReviewWidget/         # Widget target（Timeline Provider + App Intents）
│   └── Resources/           # 含 bundled-wheel.json（内置轮换缓存）
├── pc/                      # Windows 桌面版（Python + tkinter）
│   ├── core/                # 业务逻辑（不许 import tkinter）
│   ├── ui/                  # 界面
│   └── scripts/             # 生成示例 / 打包
└── PdfReview.xcodeproj/
```

**关键红线**：`Shared/Core/` 三个文件是唯一的双 target 文件；Widget target 禁止 `import SwiftData`。`scripts/check_pbxproj.py` 会自动验证这两条。

**为什么有两份内置内容**：`bundled-deck.pdfreview.json`（App）与 `bundled-wheel.json`（Widget）是同源异体的两份资源，不是重复文件——前者是导入格式，后者是轮换缓存格式。改内容要改前者再跑 `python scripts/build_seed_cache.py` 生成后者，别手工同步。详见 [docs/architecture.md](docs/architecture.md) 的 5.1 节。

**两个名字容易混**：
- `bundled-wheel.json` = 随包发布、只读的内置缓存副本（本仓库里的文件）；
- `rotation-cache.json` = App 运行时写进 App Group 容器的缓存（不随仓库分发）。

## 快速开始（macOS）

```bash
# 1. 生成工程文件（已生成，改动 Swift 文件清单后需重新生成）
python scripts/generate_pbxproj.py

# 2. 静态自检
python scripts/check_pbxproj.py
python scripts/check_swift_consistency.py
python scripts/verify_static_check.py
python scripts/check_format_consistency.py

# 3. 用 Xcode 打开 PdfReview.xcodeproj，配置签名后 Cmd+R
```

首次运行需要：
1. 在 **Signing & Capabilities** 里给两个 target 配同一个 Team；
2. 给两个 target 都勾上 App Group `group.com.pdfreview.app`（否则小组件收不到数据，见上文第 2 节）；
3. 在 App「设置」页填入 Base URL / 模型 / API Key。

详细步骤、常见报错对照（14 条）、5 分钟冒烟测试清单见 `docs/xcode-setup.md`。

## 架构要点

- **小组件不直接读写 SwiftData**。App 是唯一写者，变更后物化成 App Group 容器内的 `rotation-cache.json`，Widget 只读该 JSON。理由：WidgetKit Timeline Provider 是受限独立进程，直接操作 SwiftData 易崩溃。
- **轮换数学是纯函数**（`RotationScheduler`），App 与 Widget 调用同一实现，保证历史推算逐位一致。
- **卡片选取确定性**：按 `orderSalt` 做确定性洗牌（SplitMix64），同一批卡片在两端产生同一顺序。
- 启动时先 `backlogHistory`（回填历史）再 `refreshRotationCache`（物化缓存），顺序反了会丢一条历史。
- **启动不用存储属性默认值构造单例**。`CardStore` / `AppSettings` 在占位界面出现之后才构造（`AppRootView.bootstrap()`），否则一旦构造失败连日志都写不出来。
- **内置内容用固定 `epoch` + 文本派生卡片 ID**，保证任何设备、任何安装时间算出的轮换位置一致，且重新打包不会让收藏丢失。

完整架构文档见 `docs/architecture.md`。

## 技术栈

- iOS 17.0+，Swift 5
- SwiftUI + SwiftData
- WidgetKit + App Intents（交互式小组件按钮）
- PDFKit（文本抽取）
- OpenAI 兼容 Chat Completions 接口（可配 Base URL）

## CI

`.github/workflows/ci.yml` 三个 job：

| job | 做什么 |
|---|---|
| `static-checks` | 跑全部静态检查脚本 + 反向测试（验证检查器真的会报错） |
| `xcode-build` | 真机 `iphoneos` Release 编译 → 打未签名 IPA → 上传 artifact |
| `simulator-smoke` | 在模拟器里真跑一次，12 秒后看进程是否还活着（抓启动崩溃） |

Windows 上没有 Xcode，编译正确性完全靠这条流水线。

## 贡献

见 `CONTRIBUTING.md`。

## 许可

MIT，见 `LICENSE`。Copyright (c) 2026 peter0429-ux
