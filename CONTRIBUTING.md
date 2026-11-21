# 贡献指南

## 先说清楚这个项目是怎么来的

本仓库的代码由 AI 编程代理编写，人类负责需求与验收。所以：

- **不要假设代码是经过深思熟虑的**。它会写出「看着对、边界处错」的实现。
- **注释里的「为什么」是 AI 当时的推理**，可能是对的，也可能是事后编的。
- 发现可疑处请直接开 issue / PR，不用客气。

## 开发环境

开发机是 Windows，**没有 Xcode**。所以本地只能做静态检查，真正的编译验证在

- GitHub Actions（`macos-15` runner），见 `.github/workflows/ci.yml`；
- 或者你自己的 macOS 机器。

提交前请在本地跑完这四条（它们和 CI 的 `static-checks` 一致）：

```bash
python scripts/check_pbxproj.py
python scripts/check_swift_consistency.py
python scripts/verify_static_check.py
python scripts/check_format_consistency.py
```

改了 Swift 文件清单（新增/删除/移动）之后，还必须重新生成工程文件，否则 CI 的 `xcode-build` 会因为「pbxproj 与磁盘文件清单不一致」失败：

```bash
python scripts/generate_pbxproj.py
```

## 提交前检查清单

- [ ] 四条静态检查全绿
- [ ] 如果动了 Swift 文件清单，跑过 `generate_pbxproj.py`
- [ ] 如果动了 `schema/` 或 `AnalysisDocument.swift`，两边和 `docs/pdf-analysis-format.md` 保持一致（`check_format_consistency.py` 会查）
- [ ] 如果动了内置示例内容（`bundled-deck.pdfreview.json`），跑过 `build_seed_cache.py` 重新生成 `bundled-wheel.json`
- [ ] commit message 用英文且是祈使句（`Add ...` / `Fix ...` / `Regenerate ...`）。**不要用中文全角标点**——Windows 的 PowerShell 会把它拆成 pathspec，导致 commit 失败
- [ ] 没有把 `outputs/`、`tmp/`、`DerivedData` 加进版本库

## 代码约定

### 目录归属是硬约束

| 目录 | 编进哪个 target |
|---|---|
| `Shared/Core/` | **App 和 Widget 都编**（只有这三个文件） |
| `Shared/Models/`、`Shared/Service/`、`Shared/Store/` | **只编 App** |
| `PdfReview/` | 只编 App |
| `PdfReviewWidget/` | 只编 Widget |

**Widget target 禁止 `import SwiftData`。** 这不是风格问题：WidgetKit 的 Timeline Provider 跑在受限的独立进程里，直接操作 SwiftData 会崩，而且崩溃报告指向的位置毫无意义。`check_pbxproj.py` 会静态拦截这一条。

如果某个类型两端都要用，它要么放进 `Shared/Core/`，要么在两端各写一份纯数据版本（参考 `RotationCache` 的 `CardSnapshot` 与 SwiftData 的 `ReviewCard` 的关系）。

### 轮换算法必须是纯函数

`Shared/Core/RotationScheduler.swift` 里**不允许**读时钟、读 SwiftData、发网络请求。它的输入只有「时间点 + RotationCache」，输出是确定的槽位。App 与 Widget 各算一遍，结果必须逐位一致——历史记录能对上全靠这个。

需要「现在几点」时，由调用方把 `Date` 传进去。

### 用户可见文案全部简体中文

包括错误信息。`AnalysisValidator.ValidationError` 的每个 case 都有中文 `errorDescription`，请保持这个习惯。

### 新增错误分支时想清楚是「可恢复」还是「致命」

`CardStore.init()` 与 `AppGroup` 的写法可以参考：它们宁可降级到功能更少的模式（内存存储 / 不共享），也不让 App 起不来。启动阶段的崩溃在真机上的表现是「点一下就闪退、没有任何信息」，极难诊断。

## 提交 PR

1. Fork → 建分支（`fix/xxx`、`feat/xxx`）；
2. 写清楚**问题是什么、怎么复现、为什么这样修**；
3. 如果改动会影响到小组件、签名要求或格式标准，请在描述里显式写出「用户需要做什么」；
4. CI 绿了再请求 review。

## 报告 bug

请附上：

- iOS 版本、机型、签名方式（Xcode 自己的账号 / Sideloadly / 企业签名 / 其他）；
- App 内 **设置 → 启动日志** 的内容（这一页能看出数据容器走的是哪一级降级，绝大多数「小组件没数据」「一打开就闪退」都能在这里定位）；
- 如果是小组件问题，附上 **设置 → 关于 →「数据存储」** 那行显示的是「共享容器」还是「App 本地」。

## 明确不做的事

这些是当前范围的边界，提 PR 前请先开 issue 讨论：

- 扫描件 OCR（只处理有文字层的 PDF）
- iCloud 同步 / 多设备同步
- 后端服务
- App Store 上架材料
- iPad 专属布局 / macCatalyst

## 许可

提交即表示同意以 MIT 许可（见 `LICENSE`）发布你的贡献。
