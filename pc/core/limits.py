"""文档格式的硬性限制 —— 与 iOS 侧逐字对齐。

这几个数字散落在三个地方，改一处必须同时改另外两处：

  1. `schema/analysis.v1.schema.json` 的 minLength / maxLength / maxItems
  2. `Shared/Models/AnalysisDocument.swift` 的 `AnalysisValidator.Limits`
  3. 这里

仓库根目录的 `scripts/check_format_consistency.py` 会比对 1 与 2；
它也会检查这个文件（见该脚本的 `PC_LIMITS_PATH`），所以三处不会悄悄分叉。

**为什么 PC 版要自己写一份而不是读 schema**：
  - schema 只描述「合法」，不描述「超了怎么截断」。AI 返回超长文本时
    要按上限截断，这个行为得写在代码里。
  - 读 schema 意味着运行时依赖 JSON 文件；打包成 exe 后要额外处理资源路径，
    收益不足以抵消复杂度。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 字段长度上限
# ---------------------------------------------------------------------------

#: 卡片题面上限
QUESTION_MAX = 500

#: 卡片答案上限
ANSWER_MAX = 2000

#: 卡片补充说明上限
DETAIL_MAX = 2000

#: 单张卡片最多几个标签
TAGS_MAX = 8

#: 单个标签的长度上限
TAG_LENGTH_MAX = 32

#: 一份文件最多几张卡片
CARDS_MAX = 500

#: 牌组标题上限
TITLE_MAX = 200

#: 牌组摘要上限
SUMMARY_MAX = 2000

#: generator 字段上限
GENERATOR_MAX = 128

#: 导入分析文件（`.pdfreview.json`）的体积上限：8 MB。
#:
#: 注意它管的是**分析结果**，不是源文档。这个数字与 iOS 的
#: `AnalysisDocument.maxFileBytes` 一一对应，两边必须一致——它是跨端
#: 交接的格式约束，改了两端就互相打不开。
MAX_FILE_BYTES = 8 * 1024 * 1024

#: 源文档（PDF / Office / 文本）的体积上限：300 MB。
#:
#: 与上面的 `MAX_FILE_BYTES` **不是同一个东西**，别再合并：
#: - `MAX_FILE_BYTES` 约束的是导出的 JSON 有多大（文字量决定的）
#: - 这里约束的是用户选的原始文件有多大（图片/嵌入字体决定的）
#:
#: 一份 79 页的图文讲义可以到 74 MB，但抽出来的文字只有 2 万多字。
#: 图片根本不会被读取，按体积拦它属于拦错了对象。真正决定分析成本
#: 的是文本量，那是 `CHUNK_MAX_CHARS` 与 `CARDS_MAX` 的事。
#:
#: 300 MB 只用来防「手滑选了个几百兆的扫描件」：那种文件抽不出字，
#: 会走到「没有文字层」的分支，但先得花时间读完才判得出来。
MAX_SOURCE_BYTES = 300 * 1024 * 1024

#: 支持的格式版本
SUPPORTED_VERSION = "1.0"

#: 难度、重要度的合法区间
SCORE_MIN = 1
SCORE_MAX = 5

# ---------------------------------------------------------------------------
# 分块
# ---------------------------------------------------------------------------

#: 单块最大字符数。与 iOS 的 `PDFTextExtractor.chunk(maxChars:)` 默认值一致。
#:
#: 12000 是权衡：太小则块数多、请求多、每块信息少导致卡片质量下降；
#: 太大则超出小模型的上下文窗口，或者单次响应被 max_tokens 截断。
CHUNK_MAX_CHARS = 12_000

#: 判定「有文字层」的最小总字数。与 iOS 的 `PDFTextExtractor.extract` 一致。
TEXT_LAYER_MIN_CHARS = 200

#: 判定「有文字层」的最小平均每页字数。
TEXT_LAYER_MIN_PER_PAGE = 20


def clamp_score(value: int) -> int:
    """把难度/重要度夹到 1...5。与 iOS 的 `ReviewCard.clampScore` 一致。"""
    return min(SCORE_MAX, max(SCORE_MIN, value))


def clamp_text(text: str, limit: int) -> str:
    """按字符数截断。

    注意用切片而不是正则：Python 的 str 已经是码点序列，中文一字算一，
    与 Swift 的 `String.prefix` 语义一致（都按 extended grapheme cluster，
    普通中文文本下两者结果相同；组合表情符号的极端情况会有差异，但
    这类内容不会出现在复习卡片里）。
    """
    if len(text) <= limit:
        return text
    return text[:limit]
