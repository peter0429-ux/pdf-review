# PDF Review（PdfReview）

一个 iOS App：上传 PDF，AI 提炼成复习卡片，在**桌面小组件**里每 3 小时自动轮换一张，帮你利用碎片时间复习。支持历史记录回看、收藏、离线导入/导出。

> ⚠️ 本工程目前只在 Windows 上完成**源码与工程文件**的编写和静态校验，尚未在 macOS/Xcode 真机编译。首次编译可能需要小修，详见 `docs/xcode-setup.md` 第 0 节与第 7 节。

## 功能一览

| 功能 | 说明 |
|---|---|
| PDF → 复习卡片 | 内置 PDFKit 文本抽取 + OpenAI 兼容接口分析，按 chunk 生成卡片 |
| 离线导入 | 支持 `.pdfreview.json` 格式（自建标准，见下） |
| 桌面小组件 | systemSmall/Medium/Large + 灵动岛配件（rectangular/inline/circular），显示当前卡片、历史与倒计时 |
| 自动轮换 | 默认每 3 小时换一张，间隔 0.25–24 小时可调；「下一张」按钮手动跳过 |
| 历史记录 | App 与小组件**共用同一套推算**，逐位一致 |
| 收藏 | 两端同步（App Group + UserDefaults） |
| 导出 | 任意牌组一键导出为 `.pdfreview.json`，可分享、可再次导入 |

## 分析文件格式（自建标准）

`pdfreview.json` v1.0 —— 三份真相源保持一致：

- 机器可校验 Schema：`schema/analysis.v1.schema.json`（JSON Schema draft 2020-12）
- Swift 实现：`Shared/Models/AnalysisDocument.swift`（`AnalysisValidator`）
- 人读文档：`docs/pdf-analysis-format.md`
- 示例：`samples/sample-analysis.json`（完整）、`samples/sample-analysis-minimal.json`（最小）

文件必须通过 8MB 上限 + 未知字段拒绝 + 全字段范围校验。校验错误全是中文描述。

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
│   ├── check_format_consistency.py  # schema/Swift/文档三方一致性
│   └── build_seed_cache.py          # 把分析文件转成小组件用的种子缓存
├── Shared/                  # 双端共享
│   ├── Core/                # ← 这三个文件编进 App 和 Widget 两个 target
│   │   ├── AppGroup.swift
│   │   ├── RotationCache.swift
│   │   └── RotationScheduler.swift
│   ├── Models/              # SwiftData 模型（仅 App target）
│   ├── Service/             # AI / PDF / Keychain / 设置（仅 App target）
│   └── Store/               # CardStore（仅 App target）
├── PdfReview/               # App target（SwiftUI 视图）
│   └── Resources/           # 含 seed-analysis.pdfreview.json（内置牌组）
├── PdfReviewWidget/         # Widget target（Timeline Provider + App Intents）
│   └── Resources/           # 含 rotation-cache.json（内置轮换缓存）
└── PdfReview.xcodeproj/
```

**关键红线**：`Shared/Core/` 三个文件是唯一的双 target 文件；Widget target 禁止 `import SwiftData`。`scripts/check_pbxproj.py` 会自动验证这两条。

**为什么有两份种子**：`seed-analysis.pdfreview.json`（App）与 `rotation-cache.json`（Widget）是同源异体的两份资源，不是重复文件——前者是导入格式，后者是轮换缓存格式。改内容要改前者再跑 `python scripts/build_seed_cache.py` 生成后者，别手工同步。详见 [docs/architecture.md](docs/architecture.md) 的 5.1 节。

## 快速开始（macOS）

```bash
# 1. 生成工程文件（已生成，改动 Swift 文件清单后需重新生成）
python scripts/generate_pbxproj.py

# 2. 静态自检（三连）
python scripts/check_pbxproj.py
python scripts/check_swift_consistency.py
python scripts/check_format_consistency.py

# 3. 用 Xcode 打开 PdfReview.xcodeproj，配置签名后 Cmd+R
```

首次运行需要：
1. 在 **Signing & Capabilities** 里给两个 target 配同一个 Team；
2. 确认 App Group `group.com.pdfreview.app` 两端都已勾选；
3. 在 App「设置」页填入 Base URL / 模型 / API Key。

详细步骤、常见报错对照（14 条）、5 分钟冒烟测试清单见 `docs/xcode-setup.md`。

## 架构要点

- **小组件不直接读写 SwiftData**。App 是唯一写者，变更后物化成 App Group 容器内的 `rotation-cache.json`，Widget 只读该 JSON。理由：WidgetKit Timeline Provider 是受限独立进程，直接操作 SwiftData 易崩溃。
- **轮换数学是纯函数**（`RotationScheduler`），App 与 Widget 调用同一实现，保证历史推算逐位一致。
- **卡片选取确定性**：按 `orderSalt` 做确定性洗牌（SplitMix64），同一批卡片在两端产生同一顺序。
- 启动时先 `backlogHistory`（回填历史）再 `refreshRotationCache`（物化缓存），顺序反了会丢一条历史。

完整架构文档见 `docs/architecture.md`。

## 技术栈

- iOS 17.0+，Swift 5
- SwiftUI + SwiftData
- WidgetKit + App Intents（交互式小组件按钮）
- PDFKit（文本抽取）
- OpenAI 兼容 Chat Completions 接口（可配 Base URL）

## 许可

未定。代码仅供个人使用。
