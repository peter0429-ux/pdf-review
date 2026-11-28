# 分析文件格式标准 v1（`.pdfreview.json`）

> 面向两类读者：**① 想用别的工具生成分析结果再导入 App 的用户**（脚本、ChatGPT、其他 LLM）；**② 实现导入功能的开发者**。
> 本文与 `docs/architecture.md` 的 `AnalysisDocument` / `RotationCache` 契约一致。机器可读定义见 `schema/analysis.v1.schema.json`，可直接用的样例见 `samples/`。

---

## 1. 概述

| 项 | 规定 |
|---|---|
| 文件后缀 | `.pdfreview.json`（例如 `iOS内存管理.pdfreview.json`） |
| 编码 | UTF-8，**不带 BOM** |
| 顶层 | 单一 JSON 对象（`{ ... }`），不能是数组，也不能是多个对象拼接 |
| 大小上限 | 8 MB（**指这份分析文件本身**，超过直接拒绝导入） |
| 版本 | 当前为 `1.0` |
| 语义 | 一个文件 = 一个牌组（deck）+ 若干卡片（cards） |

这份文件是**纯交换格式**：它不包含 `id`、`isFavorite`、`createdAt` 等运行时状态，这些都由 App 在导入时生成。因此同一份文件重复导入不会因为字段不同而产生两份不同的数据。

> **和内部缓存的区别**：`rotation-cache.json` 是 App 写给小组件读的内部缓存，**格式不承诺稳定**，不要拿它做数据交换；要导出/交换数据请用 `.pdfreview.json`。详见第 8 节。

---

## 2. 完整字段表

### 2.1 顶层

| 字段 | 类型 | 必填 | 默认值 | 说明 | 约束 |
|---|---|---|---|---|---|
| `schemaVersion` | String | **是** | — | 格式版本 | 当前只接受 `"1.0"` |
| `generator` | String | 否 | 无 | 生成工具标识 | 建议 `"PdfReview/1.0"`、`"manual"`、模型名 |
| `generatedAt` | String | **是** | — | 生成时间，ISO 8601 **必须带时区** | 如 `"2026-11-21T10:00:00+08:00"` |
| `source` | Object | **是** | — | 来源文件信息 | 见 2.2 |
| `deck` | Object | **是** | — | 牌组元信息 | 见 2.3 |
| `cards` | Array\<Card\> | **是** | — | 卡片数组 | 1…500 张 |

顶层**不允许**出现未列出的字段（`additionalProperties: false`）。

### 2.2 `source`

| 字段 | 类型 | 必填 | 默认值 | 说明 | 约束 |
|---|---|---|---|---|---|
| `fileName` | String | **是** | — | 源文件名，不含路径 | 1…255 字 |
| `pageCount` | Int | **是** | — | 源文件页数 | ≥0；`0` 表示未知/非 PDF，此时卡片不要填 `sourcePage` |
| `sha256` | String | 否 | 无 | 源文件 SHA-256 摘要 | 64 位十六进制 |

### 2.3 `deck`

| 字段 | 类型 | 必填 | 默认值 | 说明 | 约束 |
|---|---|---|---|---|---|
| `title` | String | **是** | — | 牌组标题，显示在列表与小组件 | 1…200 字 |
| `summary` | String | 否 | 无 | 一两句话说明覆盖范围 | ≤2000 字 |
| `language` | String | 否 | 无 | 卡片主语言 | BCP 47，如 `"zh-Hans"`、`"en"`、`"ja"` |

### 2.4 `cards[]`（Card）

| 字段 | 类型 | 必填 | 默认值 | 说明 | 约束 |
|---|---|---|---|---|---|
| `question` | String | **是** | — | 问答正面（问题） | 1…500 字 |
| `answer` | String | **是** | — | 问答背面（答案） | 1…2000 字 |
| `detail` | String | 否 | 无 | 补充说明、示例、延伸阅读 | ≤2000 字（超出即校验失败） |
| `tags` | Array\<String\> | 否 | `[]` | 标签 | ≤8 个，每个 1…32 字，**不重复** |
| `sourcePage` | Int | 否 | 无 | 对应源 PDF 页码 | ≥1（从 1 开始） |
| `difficulty` | Int | 否 | `3` | 难度 | 1…5 |
| `importance` | Int | 否 | `3` | 重要度 | 1…5 |

> `difficulty` / `importance` 超出 1…5 是**校验错误**，不会被静默裁剪成边界值 —— 写错了就是写错了，报错比悄悄改值好排查。

---

## 3. 校验规则

导入器（`AnalysisImporter.validate`）按下表检查；**任何一条不通过都拒绝整个文件**，不做部分导入。

| # | 检查项 | 判定 | 失败提示 |
|---|---|---|---|
| 1 | 文件大小 | > 8 MB（指这份分析 JSON） | 文件超过 8 MB，请拆分后导入 |
| 2 | UTF-8 解码 | 解码失败 | 文件不是有效的 UTF-8 文本 |
| 3 | JSON 语法 | 解析失败 | JSON 语法错误（第 N 行附近） |
| 4 | 顶层类型 | 不是对象 | 顶层必须是 JSON 对象 |
| 5 | `schemaVersion` | 不匹配 `^1\.[0-9]+$`，或不是 `"1.0"` | 不支持的格式版本 X（当前支持 1.0） |
| 6 | 必填缺失 | 缺 `generatedAt` / `source` / `deck` / `cards`，或卡片缺 `question`/`answer` | 缺少必填字段：`<字段路径>` |
| 7 | 类型错误 | 类型不符（如 `difficulty: "3"`、`difficulty: 3.5`） | 字段 `<路径>` 应为整数，实际为 … |
| 8 | 枚举/范围越界 | `difficulty`/`importance` 不在 1…5，`sourcePage` < 1 | 字段 `<路径>` 超出允许范围 1…5 |
| 9 | 长度越界 | `question` > 500 字、`answer` > 2000 字等 | 字段 `<路径>` 超过最大长度 N |
| 10 | 数组超限 | `cards` 为空或 > 500；`tags` > 8 | 卡片数量必须在 1…500 之间 |
| 11 | 数组重复 | `tags` 内有重复项 | 标签重复：`<tag>` |
| 12 | 未知字段 | 出现字段表之外的键 | 不允许的字段 `<路径>` |

**错误提示的写法要求**：必须带 **JSON 路径**（如 `$.cards[2].difficulty`），让用户能直接定位到出错的那张卡。只报"格式错误"没有意义。

---

## 4. 完整示例

### 4.1 最小可用（3 张卡，只含必填字段）

文件：`samples/sample-analysis-minimal.json`

```json
{
  "schemaVersion": "1.0",
  "generatedAt": "2026-11-21T10:00:00+08:00",
  "source": {
    "fileName": "最小示例.pdf",
    "pageCount": 3
  },
  "deck": {
    "title": "最小可用示例"
  },
  "cards": [
    {
      "question": "这份文件最少必须包含哪些字段？",
      "answer": "顶层需要 schemaVersion、generatedAt、source、deck、cards；每张卡至少要有 question 与 answer。其余字段都是可选的。"
    },
    {
      "question": "source 里 pageCount 可以写 0 吗？",
      "answer": "可以。pageCount 为 0 表示页数未知或来源不是 PDF，此时卡片不要填 sourcePage。"
    },
    {
      "question": "difficulty 不写会怎样？",
      "answer": "会被当作默认值 3。importance 同理，缺省也是 3。"
    }
  ]
}
```

**这份文件能导入**：`generator`、`deck.summary`、`deck.language`、`source.sha256`、每张卡的 `detail`/`tags`/`sourcePage`/`difficulty`/`importance` 全部省略即可，缺省值自动补齐。

### 4.2 典型（8 张卡，带 tags 与 sourcePage）

文件：`samples/sample-analysis.json`（节选前两张，全文见该文件）

```json
{
  "schemaVersion": "1.0",
  "generator": "PdfReview/1.0",
  "generatedAt": "2026-11-21T10:00:00+08:00",
  "source": {
    "fileName": "iOS内存管理.pdf",
    "pageCount": 12,
    "sha256": "3f786850e387550fdab836ed7e6dc881de23001b2b1a0d2c1b1a1d0b6a8f4c21"
  },
  "deck": {
    "title": "iOS 内存管理",
    "summary": "覆盖 ARC 引用计数、循环引用、weak/unowned 选择、autoreleasepool 与常见泄漏排查。",
    "language": "zh-Hans"
  },
  "cards": [
    {
      "question": "ARC 在编译期做了什么，运行期又由谁负责释放对象？",
      "answer": "ARC 是编译器特性：编译期在合适位置插入 retain/release/autorelease 调用，运行期由这些调用维护引用计数，计数归零时对象调用 deinit 并释放内存。ARC 不改变引用计数的语义，只是免去手写。",
      "detail": "可在 Build Settings 的 Objective-C Automatic Reference Counting 确认开关状态；Swift 没有 non-ARC 模式。",
      "tags": ["ARC", "引用计数", "基础"],
      "sourcePage": 1,
      "difficulty": 2,
      "importance": 5
    },
    {
      "question": "强引用循环是怎么产生的？给出一个典型例子。",
      "answer": "两个对象互相持有强引用，各自引用计数都不会归零。典型例子：父子关系里父对象强引用子对象，子对象又用强引用指回父对象；或者闭包捕获了持有该闭包的对象（self 强捕获）。",
      "detail": "self.handler = { self.doSomething() } 会让 self 与闭包互相持有。",
      "tags": ["循环引用", "内存泄漏"],
      "sourcePage": 3,
      "difficulty": 3,
      "importance": 5
    }
  ]
}
```

### 4.3 每个字段在实际使用中的含义

- **`generatedAt`**：仅用于展示"这份卡片什么时候生成的"和排查来源，不参与去重。**必须带时区**——写成 `"2026-11-21T10:00:00"` 会解析失败，因为无法判断是哪个时区的时间。
- **`source.fileName`**：显示在牌组详情里（"来自 iOS内存管理.pdf"）。不含路径，因为导入方和生成方的路径不可能一致。
- **`source.pageCount`**：给"跳转到原页"功能一个上界校验——若某张卡 `sourcePage` > `pageCount`，App 会显示但跳转按钮置灰。
- **`source.sha256`**：用来判断"这份文件我是不是已经导入过"。不提供也能导，只是去重会退化成按 `fileName` 判断。
- **`deck.summary`**：牌组列表页的一行摘要；小组件不显示它（小组件空间太小）。
- **`deck.language`**：提示用的是哪种语言，**不会触发任何翻译**。用来让中文用户导入英文卡时不至于以为出错。
- **`cards[].detail`**：翻到答案后再展开的"更多内容"，适合放代码示例、易错点、延伸阅读。它是可选的——不是每张卡都需要。
- **`cards[].tags`**：用于牌组内筛选。**上限 8 个**是刻意的：手机屏幕一行放不下更多，且标签太碎等于没有标签。
- **`cards[].sourcePage`**：从 1 开始（和阅读器一致，不是从 0）。只有源文件是 PDF 且有文本层时才填。
- **`cards[].difficulty` / `importance`**：两个维度分开。`difficulty` 表示"这张卡难不难"，`importance` 表示"该不该经常出现"。轮换时 `importance` 高的卡出现得更频繁，`difficulty` 目前只用于展示与排序。

---

## 5. 如何用 LLM 生成

把下面这段提示词连同 PDF 正文（或你的笔记）一起发给模型。**关键三点**：只输出 JSON、不要 Markdown 代码块、严格遵循字段表。

```text
你是一个复习卡片生成器。请阅读我提供的文本，输出一个 JSON 对象，用于导入 PdfReview App。

严格要求：
1. 只输出 JSON 本体，不要任何解释文字，不要用 ```json 代码块包裹，不要加注释。
2. 严格遵循下面的字段表，不要增加字段表中没有的字段（否则导入会失败）。
3. 所有字符串使用中文（除非原文是英文术语）。

输出结构（字段名必须完全一致）：
{
  "schemaVersion": "1.0",
  "generator": "<你的模型名>",
  "generatedAt": "<当前时间，ISO 8601 带时区，例如 2026-11-21T10:00:00+08:00>",
  "source": {
    "fileName": "<源文件名>",
    "pageCount": <页数，未知填 0>
  },
  "deck": {
    "title": "<牌组标题>",
    "summary": "<一到两句话摘要>",
    "language": "zh-Hans"
  },
  "cards": [
    {
      "question": "<问题，1~500 字>",
      "answer": "<答案，1~2000 字>",
      "detail": "<可选：补充说明或示例>",
      "tags": ["<标签1>", "<标签2>"],
      "sourcePage": <页码，从 1 开始，未知则省略该字段>,
      "difficulty": <1~5 的整数，默认 3>,
      "importance": <1~5 的整数，默认 3>
    }
  ]
}

硬性约束：
- cards 至少 1 张，最多 500 张。
- 每张卡的 question 与 answer 都必填，且不能为空字符串。
- tags 最多 8 个，每个不超过 32 字，且不能重复。
- difficulty 与 importance 必须是 1~5 的整数，不能是小数或字符串。
- generatedAt 必须带时区（+08:00 或 Z）。
- 不要输出 id、isFavorite、createdAt 字段，这些由 App 生成。

请生成 <N> 张卡片。现在开始输出 JSON：
```

**保存方式**：把模型输出**原样**存成 `xxx.pdfreview.json`（UTF-8，无 BOM）。如果模型仍用 ` ```json ` 包裹，把首尾两行代码围栏删掉——这是最常见的导入失败原因。

**验证方式**：用 `schema/analysis.v1.schema.json` 校验，或直接看导入时的报错路径。

---

## 6. 与 App 内 AI 分析的关系

App 在设置里配置 OpenAI Chat Completions 兼容接口（`baseURL` + `model` + `apiKey`），调用 `AIClient.analyze(...)` 后产出的**就是同一个 `AnalysisDocument` 结构**。

因此：

- **两种来源完全等价**：AI 生成的、脚本生成的、手写的 `.pdfreview.json`，进入 App 后走同一条解码与校验路径（`AnalysisImporter.decode`）。
- **可以混合**：同一个牌组里可以先导入一批 AI 生成卡，再补导入一批手工整理的卡；也可以把 AI 生成的 `.pdfreview.json` 导出后用外部工具改，再导回来。
- **唯一的差别在 `generator` 字段**：AI 分析会写 `"PdfReview/1.0"`，导入文件通常写工具名。它只用于展示来源，不影响任何行为。

这条等价性是刻意保证的（见 `docs/architecture.md` §7 一致性红线第 4 条）：**App 的 `AnalysisDocument` 结构与 `schema/analysis.v1.schema.json` 必须一致**。任何一方改了字段，另一方必须同步。

一个已知的实践差异：App 内 AI 分析会按章节分块多次请求再合并（`AIClient.analyze(chunks:...)`），合并后仍然是单个 `AnalysisDocument`；而外部生成的通常是单次产出。两者在文件层面没有区别。

---

## 7. 版本演进策略

`schemaVersion` 采用"主版本.次版本"两段式，规则如下：

| 变更类型 | 是否改版本 | 兼容性 |
|---|---|---|
| 新增**可选**字段 | `1.0` → `1.1` | 向后兼容：旧版 App 忽略未知字段即可读 |
| 放宽约束（如 tags 上限 8 → 12） | 次版本 +1 | 向后兼容 |
| 新增必填字段 | **不允许在 1.x 内做** | 必须进 2.0 |
| 收紧约束（如 answer 上限 2000 → 1000） | **不允许在 1.x 内做** | 必须进 2.0 |
| 改字段语义、删字段、改类型 | **不允许在 1.x 内做** | 必须进 2.0 |

**给实现者的要求**：

1. **写入方**：当前写 `"1.0"`。若将来用到 1.1 的可选字段，仍可写 `"1.0"`（因为字段可选），写 `"1.1"` 更准确。
2. **读取方（App 1.0）**：只接受精确的 `"1.0"`。遇到 `"1.1"` 等更晚的次版本，**不应报"格式错误"**，而应提示"此文件由更新版本的 App 生成，请升级后导入"——这是同样的兼容家族。
3. **读取方遇到 `"2.0"`**：明确拒绝，提示版本不支持。
4. **`additionalProperties: false` 的例外处理**：JSON Schema 里设为 `false` 是为了在自己人之间尽早发现拼写错误。若未来做 1.1 的宽松读取，读取器应改为"忽略未知字段"而不是"拒绝"。当前 v1 严格拒绝，**这是有意的**——两个字段名拼错（`diffculty`）静默通过、结果全部卡片都是默认难度 3，比直接报错难查得多。

---

## 8. 外部读取：为什么别用 `rotation-cache.json`

App Group 容器里有两个 JSON：

| 文件 | 是什么 | 稳定性 |
|---|---|---|
| `rotation-cache.json` | App 写、Widget 读的**内部缓存**，服务于轮换排期 | **不承诺稳定** |
| `*.pdfreview.json` | 用户/工具的**交换格式** | 本文件定义的契约 |

`rotation-cache.json` 的内容是 `RotationCache`（见 `docs/architecture.md` §4.2）：它包含 `epoch`、`orderSalt`、`intervalHours`、`manualOffset` 这类**只对轮换算法有意义**的运行时状态，以及 `CardSnapshot` 的扁平副本。它还会在每次卡片变更时被整体重写。

**所以**：

- 它可能随时新增字段、调整结构、改变 `orderSalt` 的生成方式——只要 App 与 Widget 同步改就行，不需要对外兼容。
- 里面没有牌组摘要、没有 `difficulty`/`importance`、没有生成时间，**不足以还原一份完整的分析文件**。
- 直接从缓存里抠数据，下次 App 更新可能就失效了。

**要交换数据，用 `.pdfreview.json`**：App 的导出功能产出的就是这种格式；它跨版本、跨工具，且带完整校验规则。如果你是开发者想读小组件当前显示什么，读缓存可以，但要接受它随时会变（并且只读，不要写——App 是唯一写者，见 `docs/architecture.md` §3.1）。
