# 变更记录

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。版本号遵循语义化版本。

这个项目没有「发布过」的版本概念——没有上架 App Store，也没有 tag。下面按时间倒序列出做过的事，重点记**踩过的坑**，因为那才是这份记录真正有用的部分。

---

## [未发布]

### 新增
- **Windows 桌面版（`pc/`）**：同一套 `.pdfreview.json` 格式标准，支持 PDF / Word（`.docx`）/ PowerPoint（`.pptx`）/ Excel（`.xlsx`）/ 纯文本 / Markdown / 网页（`.html`）→ 复习卡片，导出后传到手机导入。
  - `pc/core/`：`limits` / `cards` / `settings` / `project` / `extract` / `chunker` / `schema_check` / `ai` / `analyzer` / `export` 十个模块，全部不 import tkinter。
  - `pc/ui/`：tkinter 界面（主窗口 / 新建牌组 / 设置 / 卡片预览），耗时操作走后台线程 + 队列轮询，窗口不假死。
  - `pc/scripts/`：`make_samples.py` 生成七种示例、`build.py` 打成 `--onedir` 并压 zip。
  - 打包产物带 `--selftest`：不联网地把八个依赖、schema、切块、导出各验一遍，用户报「导不出 Excel」时直接让他跑。
- **提问功能**：新增第五个标签页「提问」。选一份牌组提问，AI 先回答，再判断这个知识点值不值得做成复习卡片；值得时给一张可编辑的草稿，用户改完点一下就进了轮换池。
  - `AIClient.ask(...)` 与 `AskResult`（`answer` / `worthSaving` / `reason` / `draft`）。
  - `AskThread` 模型与 `CardStore` 的 `insertAskThread` / `markThreadSaved` / `askThread(withID:)` / `askThreads(limit:)` / `delete(askThread:)`。
  - 新增 `AskView`、`AskHistoryView`（按天分组、滑动删除、详情页）、`AskBubbleView`、`CardDraftView`。
  - 牌组详情页给非分析来源的卡片加「提问 / 手工」角标。
- **牌组保存原文**：`ReviewDeck.sourceText` 存前 40 000 字，作为提问时的上下文。导入 PDF 生成的牌组才有；早先导入的牌组没有原文，提问页会明确告知。
- **卡片记录来源**：`ReviewCard.origin`（`analysis` / `ask` / `manual`），带默认值 `"analysis"`，老库可轻量迁移。

### 变更
- `AIClient.analyze` 的进度回调从 `(Double) -> Void` 换成 `(AnalysisProgress) -> Void`（上一版已做，这里补记）。
- **内置示例内容换成无版权归属的自制牌组**。原先随包的 93 张卡片来自一份第三方讲义 PDF，在开源前被移除（连同 git 历史里的旧路径一起清理）。现在的内置内容是 24 张「iOS 内存管理」卡片，由项目自己编写。
- 内置资源改名，避免与运行时缓存混淆：
  - `PdfReview/Resources/seed-analysis.pdfreview.json` → `bundled-deck.pdfreview.json`
  - `PdfReviewWidget/Resources/rotation-cache.json` → `bundled-wheel.json`
  - `rotation-cache.json` 这个名字**只**指 App 运行时写进 App Group 容器的那份缓存。
- 设置页的「内置内容」不再硬编码牌组名，改为从内置缓存里读真实标题与卡片数。
- 仓库开源配套：MIT `LICENSE`、`CONTRIBUTING.md`、本文件；README 增加「AI 编写」与「App Groups 必须开启 / 植入方法」两节。
- `scripts/check_format_consistency.py` 增加第四方比对：`pc/core/limits.py` 的常量必须与 Swift 逐项一致。

### 说明
- **`AskThread` 刻意不建 SwiftData 关系**。卡片会被删、会被移到别的牌组；用 `@Relationship` 要么级联删掉提问历史，要么把 `savedCardID` 置空，两种都不对。留一个普通 `UUID` 字段，历史独立存活。
- **`worthSaving` 与 `draft` 必须同时成立**。模型说「值得」却给不出可解析的卡（字段缺失、被截成空串）时，按不值得处理——否则用户点保存才发现是空卡。这条在 `AIClient.decodeAskResult` 里强制，不信任模型的自我声明。
- **PC 版只打 `--onedir`**。`--onefile` 会把依赖解到临时目录再启动，沙箱里解压 VCRUNTIME140.dll 被拒（`fopen: Permission denied`），换 TEMP 与 `--runtime-tmpdir` 都无效。onedir 启动更快、缺 dll 也更容易定位。
- **`pc/requirements.txt` 必须纯 ASCII**。pip 用系统 locale（中文 Windows 是 GBK）解码它，UTF-8 中文注释会让 pip 直接 `UnicodeDecodeError` 退出。
- **PC 版不读 schema 文件来取上限**。schema 只描述什么合法，不描述「超了怎么截断」；而且打包后读资源文件多一层路径依赖。所以 `pc/core/limits.py` 自己写一份常量，靠 `check_format_consistency.py` 保证两边不漂移。

---

## 2026-11-22

### 新增
- **分析过程动画**：五步清单（读取文本 → 拆分块 → 逐块请求 → 生成卡片 → 保存）、环形进度、数字滚动、块号 `3 / 8`、每块产出的卡片逐张翻入（最多堆叠 3 张）。尊重「减弱动态效果」系统设置。
- `AnalysisProgress` 结构替换原来的 `(Double) -> Void` 进度回调，带上块号、累计卡片数与本块题面。
- `scripts/verify_ipa.py`：核验打出来的 IPA（Mach-O 架构必须是 arm64 真机、`Info.plist` 关键键、内置资源是否真的进包）。
- `scripts/grep_binary.py`：在二进制里确认代码路径真被编进去。
- `scripts/list_artifacts.py`：列出 CI 产物（`gh api` 在 PowerShell 里会被拆参，得绕一层）。

### 修复
- 小组件 `getTimeline` 里裸调 `loadCache()` 导致编译失败：`TimelineProvider` 的方法是实例方法，必须写全 `RotationProvider.` 前缀。
- 静态检查器新增「实例方法里裸调本类型 static 成员」检测，并加了反向测试 `verify_static_check.py`（注入真 bug，断言检查器会报且行号准确）。

### 说明
- `repeatForever` 动画不会自己播：它绑在 `.animation(_:value:)` 上时，如果那个 value 在分支里是常量，一次都不会播。要拆出独立视图用它自己的 `@State` 驱动。

---

## 2026-11-21

### 新增
- **内置示例内容**：首次启动自动导入一幅牌组；小组件在没有 App Groups 时也能从随包资源里读到内容，不至于一直空态。
- 启动日志（`Documents/launch.log` + 设置页「启动日志」）：把「打开就闪退」从无从下手变成能看出断在哪一步。
- App 图标（1024×1024，无图集缺 `filename` 字段的坑一并修掉）。
- CI 第三个 job `simulator-smoke`：在模拟器里真跑，12 秒后检查进程是否还在。

### 修复
- **启动即闪退**（真机，侧载）。根因是 `CardStore` / `AppSettings` 作为 `@StateObject` 的存储属性默认值，在 `App.init()` 的函数体之前就被求值——那里一旦失败，连日志都写不出来，表现为「点一下就闪退、什么都没发生」。改为新建 `AppRootView` 启动壳：先画占位界面，再在 `.task` 里构造单例，失败时显示可读的错误界面。
- **文件选择器所有文件变灰**。`UTType(filenameExtension: "pdfreview")` 在扩展名未注册时返回 `dyn.*` 动态标识符，**一旦混进 `allowedContentTypes`，整个过滤就失效**，连本该能选的 `.json` 一起变灰。三套类型组合（含加 `.item` / `.data`）在 iOS 27 真机上全都不行，最终弃用 `.fileImporter`，改为自写 `DocumentPicker` 直接包 `UIDocumentPickerViewController(forOpeningContentTypes: [.item], asCopy: true)`；同时加 `onOpenURL` 支持从「文件」App 分享导入。
- App Group 拿不到时 `UserDefaults(suiteName:)` 会在 CFPrefs 层直接杀掉进程（C 代码，Swift 的 `??` 兜不住）。改为先用探测文件确认容器可写，再取 suite。
- `AppGroup.defaults` 从 `static var` 改为 `static let` 单次解析。
- `CardStore` 不再把 SwiftData 库放进 App Group 共享容器（架构上只有 App 一个写者，放进去只带来侧载崩溃风险）。
- `signature(of:)` 用 Swift `Hasher` 导致每次启动签名都不同 → 整副牌每次打开都重排、3 小时轮换节奏失效。改为 FNV-1a。

### 说明
- 模拟器冒烟测试**覆盖不到**真机侧载场景：未签名模拟器版 `containerURL` 返回 nil，走的是降级路径；被签名工具注入 App Groups 的真机版才走共享容器。所以「模拟器过了」不等于「真机没问题」。
- 用免费 Apple ID 侧载时，`provisioning profile` 里没有 App Groups 能力，代码里再怎么写都拿不到共享容器。

---

## 2026-11-20 及更早

### 新增
- 项目从零搭建：`Shared/Core`（轮换数学、缓存格式、App Group 封装）、`Shared/Models`（SwiftData 模型）、`Shared/Service`（AI 客户端、PDF 抽取、Keychain、设置）、`Shared/Store`（`CardStore`）。
- Widget target：`StaticConfiguration` + `TimelineProvider` + 两个 App Intent（下一张 / 收藏）。
- App UI：复习、牌组列表、牌组详情、导入（含分析进度）、历史、设置、引导。
- 文件格式标准 `pdfreview.json` v1.0，三份真相源（JSON Schema / Swift `AnalysisValidator` / 人读文档）互相对齐。
- 工程文件用脚本生成（`generate_pbxproj.py`），并自写 OpenStep plist 解析器做独立校验（`check_pbxproj.py`）。
- CI：静态检查 + 真机 `iphoneos` Release 编译 + 打未签名 IPA。

### 修复
- `pbxproj` 的 `PBXGroup` 全部缺 `path`：文件会被解析到工程根，Xcode 报 "Build input file cannot be found"。
- `Info.plist` 里 `UIRequiredDeviceCapabilities` 含 `armv7`：现代 arm64 设备不上报这个能力，真机可能报「App 与此设备不兼容」，而模拟器不校验所以发现不了。
- `AppSettings` 调 `KeychainStore.set(_:forKey:)` 参数标签写错（真实签名是 `for:`）。
- `CardEditorView` 的 `.foregroundStyle(cond ? .red : .tertiary)`：`.tertiary` 是 `ShapeStyle` 修饰符，不能和 `Color` 进同一个三目。
- CI 用 `-sdk iphonesimulator` 产出模拟器架构的包 → Sideloadly 重签后真机拒装（"Unable to Install"）。改 `-sdk iphoneos -configuration Release`。
