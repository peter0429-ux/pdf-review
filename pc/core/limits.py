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

#: 单文件体积上限（8 MB），与 iOS 的 `AnalysisDocument.maxFileBytes` 一致
MAX_FILE_BYTES = 8 * 1024 * 1024

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
