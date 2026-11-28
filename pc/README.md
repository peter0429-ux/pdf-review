# PDF 复习 · PC 版

把一份文档变成复习卡片，导出 `.pdfreview.json` 传到 iPhone，在 App 里导入就能复习。

这个目录是 PC 版，用 Python + tkinter 写的 Windows 桌面程序。iOS 版在仓库根目录。

## 为什么有 PC 版

iOS 版分析一份 PDF 要花几分钟，而且必须一直开着 App。文档在电脑上时，
用 PC 版先批量做出来、再导到手机上更顺。反过来也行——PC 版不读手机的数据，
两边都通过 `.pdfreview.json` 交接。

## 支持的文件

| 格式 | 说明 |
| --- | --- |
| `.pdf` | 有文字层的才读得出来；扫描件（整页是图片）不支持 |
| `.docx` | 按标题样式分节，表格按行拆 |
| `.pptx` | 每张幻灯片一段 |
| `.xlsx` | 每个工作表一段，首行当表头 |
| `.txt` / `.md` | 纯文本；Markdown 按 `#` 标题分节 |
| `.html` / `.htm` | 去掉脚本、导航、页眉页脚后取正文 |

单份源文档上限 300 MB。**这个上限只管"能不能读进来"**：体积几乎全在内嵌图片上，
真正送给模型的只有文字层，所以一份七十多 MB 的讲义通常只抽出两三万字。
真正的瓶颈是文字量——文字太多会切成很多块、请求很多次，选完文件后对话框会给出
预估的块数与耗时。

（导出/导入的 `.pdfreview.json` 另有 8 MB 上限，那是交换文件，和源文档不是一回事。）

## 怎么用

1. 双击 `PdfReview.exe`
2. 第一次启动会弹「设置」，填三样东西：
   - **接口地址**：填到 `/v1` 为止，比如 `https://api.openai.com/v1`
   - **模型名**：比如 `gpt-4o-mini`、`deepseek-chat`
   - **API Key**：只存在这台电脑上，用 Windows 账户加密
3. 点「新建牌组…」，选文件、确认名字、点「开始分析」
4. 分析完在列表里选中它，点「导出给 iPhone」
5. 把导出的 `.pdfreview.json` 传到手机（微信/邮件/iCloud 都行），在 App 里点「导入」

## API Key 存在哪

`%APPDATA%\PdfReviewPC\settings.json`，Key 那一项用 Windows 的 DPAPI 加密。

DPAPI 的密钥绑当前 Windows 账户：把文件拷到别的电脑或别的账户下，
解不开，程序会让你重填。**所以不要把这个文件发给别人**，倒不是怕泄露
（拷过去也解不开），而是没必要。

## 牌组存在哪

`%USERPROFILE%\Documents\PdfReviewPC\decks\`，一个牌组一个文件夹：

```
decks/
  iOS 内存管理-3ec7b8ab/
    deck.pdfreview.json     ← 牌组内容（就是导出给 iPhone 的那个格式）
    meta.json               ← 来源文件、时间、块数这些
```

想备份就整个 `decks` 目录拷走。想手动改内容就编辑 `deck.pdfreview.json`，
改完在程序里重新选中它就会读到新的（重启程序更稳）。

## 自己从源码跑

```bash
cd pc
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

`requirements.txt` 必须保持纯 ASCII：pip 会用系统 locale（中文 Windows 是 GBK）
解码它，写中文注释会让 pip 直接报 `UnicodeDecodeError` 退出。

### 打包

```bash
.venv\Scripts\python scripts\build.py
```

产出 `outputs/deliver/PdfReview-PC-win64.zip`。

**只能打成 `--onedir`，不能 `--onefile`。** 这个会话的沙箱里 `--onefile` 必然失败：

```
[PYI-xxxxx:ERROR] Failed to extract VCRUNTIME140.dll:
failed to open target file! fopen: Permission denied
```

换 `TEMP`、换 `--runtime-tmpdir` 都没用。真机上 `--onefile` 大概率能过，但
`--onedir` 启动更快、也更容易排查「缺了哪个 dll」，所以就用它。

### 打包后自检

```
PdfReview.exe --selftest 报告.json
```

它不联网，只做四件事：把八个依赖各 import 一次、读 schema、跑一遍切块、
写一份 `.pdfreview.json` 到临时目录。哪一项缺东西会写在报告里。

用户报「导不出 Excel」时让他跑这个，比来回猜快得多。

## 目录结构

```
pc/
  main.py              程序入口 + --selftest
  requirements.txt     依赖（纯 ASCII）
  core/                业务逻辑，不许 import tkinter
    limits.py          和 iOS 逐字对齐的上限常量
    cards.py           Card / Deck / Source / AnalysisDocument
    settings.py        设置 + DPAPI
    project.py         牌组库（一个牌组一个文件夹）
    extract.py         七种格式的文本抽取
    chunker.py         按段落攒块
    schema_check.py    独立的 JSON Schema 校验器
    ai.py              OpenAI 兼容接口
    analyzer.py        串起整条链路
    export.py          导出（双重校验）
  ui/
    theme.py           配色、字体、间距
    worker.py          后台线程 + 队列，界面不卡
    preview.py         右侧卡片预览
    settings_dialog.py 设置窗口
    analyze_dialog.py  新建牌组窗口
    main_window.py     主窗口
  scripts/
    make_samples.py    生成七种示例文件
    build.py           打包 + 压 zip
```

`core/` 里不许出现 `tkinter`：界面换掉（比如将来做命令行版）时，核心逻辑
一行都不用改。这条规矩写在 `core/__init__.py` 的 docstring 里。

## 和 iOS 版的一致性

两边的上限常量必须一样：题目 500 字、答案 2000、补充说明 2000、标签最多 8 个、
单个标签 32 字、卡片最多 500 张、标题 200 字、格式版本 `1.0`。

体积上限有两套，**不要合并**：`.pdfreview.json` 交换文件 8 MB（两端一致，iOS 的
`AnalysisDocument.maxFileBytes` 与 PC 的 `limits.MAX_FILE_BYTES` 对应）；源文档
300 MB 只有 PC 版有（`limits.MAX_SOURCE_BYTES`），因为 iOS 版选 PDF 时本来就不设
体积限制。`check_format_consistency.py` 会断言这两个数都存在且不相等。

`scripts/check_format_consistency.py`（在仓库根目录的 `scripts/` 下）会读
`pc/core/limits.py`、iOS 的 `AnalysisDocument.swift`、`schema/analysis.v1.schema.json`
三份东西逐项比对。任何一边改了另一边没跟上，CI 会红。

**为什么值得多这一道**：这种偏差不会报错，只会让两边的导入行为悄悄不一致，
直到有用户碰到一份刚好卡在边界上的文件——那种 bug 从现象根本查不到原因。

## 已知限制

- **不做 OCR**：扫描件、图片里的文字都读不到。Windows 上没有 iOS 那种免费的
  系统级 OCR，硬做只有 Tesseract，中文效果明显更差。
- **不自动同步**：没有账号、没有云。数据交换全靠手动导出导入。
- **不能编辑卡片**：PC 版只负责批量生产。改卡片回手机上改。
- **只有 Windows**：tkinter 本身跨平台，但 DPAPI 加密是 Windows 独有的。
  Mac 上跑要换 Keychain，那块没写。
