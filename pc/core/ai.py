"""调用 OpenAI 兼容接口做两件事：把文本块变成卡片，以及诊断连通性。

不用 `requests`：标准库的 `urllib.request` 够用，而且少一个依赖就少一个
打包时的坑（PyInstaller 对 requests 的证书与代理处理需要额外 hooks）。
代价是要自己处理超时、重试与错误分类 —— 下面这些就是。
"""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import cards as cards_mod
from . import limits
from .chunker import Chunk

#: 生成器标识，写进导出文件的 `generator` 字段。和 iOS 的 "PdfReview/1.0" 区分开，
#: 排查问题时一眼能看出这份卡片是电脑生成的还是手机生成的。
GENERATOR = "PdfReviewPC/0.1"

#: 单次请求的超时。分析一份文档可能几十次请求，一次卡住太久用户会以为死了。
DEFAULT_TIMEOUT = 120.0

#: 重试次数（首次之外）。与 iOS 一致。
RETRY_LIMIT = 2

#: 不重试的 HTTP 状态。401/403 是 Key 的问题、404 是地址或模型名的问题，
#: 重试只会浪费时间并让用户以为「再试一次就好了」。
NO_RETRY_STATUS = frozenset({400, 401, 403, 404})


class AIError(Exception):
    """调用失败。消息直接给用户看，所以要写人话并说清下一步怎么做。"""


class AIConfigError(AIError):
    """配置有问题（没填 Key、地址写错之类）。"""


class AICancelled(AIError):
    """用户点了取消。单独一个类型，好让上层区分「失败」与「不要了」。"""


# ---------------------------------------------------------------------------
# 请求配置
# ---------------------------------------------------------------------------


@dataclass
class AIConfig:
    """一次分析需要的连接参数。从 `settings.Settings` 构造。"""

    base_url: str
    model: str
    api_key: str
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_settings(cls, settings) -> "AIConfig":
        return cls(
            base_url=settings.base_url.strip().rstrip("/"),
            model=settings.model.strip(),
            api_key=settings.api_key.strip(),
        )

    def validate(self) -> None:
        if not self.base_url:
            raise AIConfigError("还没填接口地址")
        if not self.base_url.startswith(("http://", "https://")):
            raise AIConfigError("接口地址要以 http:// 或 https:// 开头")
        if not self.model:
            raise AIConfigError("还没填模型名")
        if not self.api_key:
            raise AIConfigError("还没填 API Key")

    @property
    def chat_url(self) -> str:
        """拼出 `/chat/completions`。

        用户填的地址可能已经带了 `/v1`，也可能带到了 `/v1/chat/completions`。
        两种都认：先看结尾是不是已经完整，再看要不要补 `/v1`。
        这比强制用户填某一种格式友好 —— 各家文档写法不一样。
        """
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


# ---------------------------------------------------------------------------
# 卡片生成
# ---------------------------------------------------------------------------

#: system prompt。与 iOS 的 `AIClient` 里那份规则一致：六条约束，
#: 核心是「题目必须能在原文找到依据」与「答案是自足的」。
SYSTEM_PROMPT = """你是一位帮人准备考试的老师。用户会给你一段文档原文，你要把它变成复习卡片。

规则：
1. 每张卡片只考一个知识点。一道题问两件事，答对一半也算错，复习时无法判断掌握程度。
2. 题目必须能在原文里找到依据。原文没写的内容不要编；原文讲得含糊的地方，宁可不出题。
3. 题目要是疑问句或填空题，能自测。「请说明……」这种开放题不好自测，尽量改成「……是什么？」「……的原因有哪些？」
4. 答案要能独立阅读。不要写「如上所述」「见第 3 节」，用户复习时看不到原文。
5. 忽略目录、页眉页脚、页码、版权声明、参考文献列表。
6. 只输出 JSON，不要 Markdown 代码块，不要任何解释性文字。

输出格式：
{"cards": [{"question": "...", "answer": "...", "detail": "...", "tags": ["..."], "sourcePage": 3, "difficulty": 3, "importance": 3}]}

detail、tags、sourcePage、difficulty、importance 都是可选的，没有就不写这个键。
difficulty 与 importance 取 1 到 5，3 表示普通。"""


def build_user_prompt(chunk: Chunk, document_title: str, card_count: int) -> str:
    """把一块文本包成 user 消息。

    显式告诉模型「这一块来自第几页到第几页」，让它填 sourcePage 时有个准绳。
    不说的话它会瞎猜，或者干脆不填。
    """
    return (
        f"这段内容来自《{document_title}》，{chunk.segment_span}。\n"
        f"请从这段内容里提炼 {card_count} 张复习卡片。\n"
        f"如果这段内容不足以出 {card_count} 张有质量的卡片，少出几张也行，"
        f"不要为了凑数把同一个知识点拆成多张。\n\n"
        f"原文：\n{chunk.text}"
    )


@dataclass
class ChunkResult:
    """一块的处理结果。"""

    chunk_index: int
    cards: list[cards_mod.Card]
    #: 模型原始返回，出错时用来排查
    raw: str = ""


def analyze_chunk(
    chunk: Chunk,
    document_title: str,
    config: AIConfig,
    card_count: int,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> ChunkResult:
    """让模型把一块文本变成卡片。

    重试策略与 iOS 一致：首次 temperature 0.3，重试降到 0.1。
    降温的理由是「第一次拿到的东西结构不对，多半是模型太放飞」，
    同样的输入用更低温度重问，往往就规规矩矩给出 JSON 了。
    """
    config.validate()
    count = min(12, max(1, card_count))

    last_error: Optional[Exception] = None
    for attempt in range(RETRY_LIMIT + 1):
        if cancel_check is not None and cancel_check():
            raise AICancelled("已取消")

        temperature = 0.3 if attempt == 0 else 0.1
        try:
            raw = _post_chat(
                config=config,
                system=SYSTEM_PROMPT,
                user=build_user_prompt(chunk, document_title, count),
                temperature=temperature,
                max_tokens=3000,
                cancel_check=cancel_check,
            )
            cards = decode_cards(raw)
            return ChunkResult(chunk_index=chunk.index, cards=cards, raw=raw)
        except AICancelled:
            raise
        except AIConfigError:
            raise
        except AIError as exc:
            last_error = exc
            # 这几类错误重试也不会变好
            if getattr(exc, "status", None) in NO_RETRY_STATUS:
                raise
            if attempt < RETRY_LIMIT:
                # 稍等一下再试：网络抖动造成的失败，立刻重试大概率还是失败
                time.sleep(1.5 * (attempt + 1))
                continue
            raise

    raise last_error or AIError("未知错误")


# ---------------------------------------------------------------------------
# 解析模型返回
# ---------------------------------------------------------------------------


def decode_cards(raw: str) -> list[cards_mod.Card]:
    """从模型返回里抠出卡片。

    两种形态都要认：
      1. 接口原始响应：`{"choices":[{"message":{"content":"..."}}]}`
      2. 已经是内容文本：直接是 `{"cards":[...]}`

    第二种是为了方便测试（不联网也能验证解析逻辑）。
    """
    text = raw.strip()

    # 先试整体当接口响应解析
    try:
        outer = json.loads(text)
        if isinstance(outer, dict) and "choices" in outer:
            text = _content_from_response(outer)
    except json.JSONDecodeError:
        pass

    text = strip_code_fence(text)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIError(
            f"模型返回的不是合法 JSON（{exc}）。"
            f"开头是：{text[:120]!r}"
        ) from exc

    if isinstance(payload, list):
        raw_cards = payload
    elif isinstance(payload, dict):
        raw_cards = payload.get("cards")
        if raw_cards is None:
            # 有些模型会只返回一张卡，没有包一层 cards 数组
            if "question" in payload and "answer" in payload:
                raw_cards = [payload]
            else:
                raise AIError(
                    f"模型返回的 JSON 里没有 cards 字段。"
                    f"收到的键是：{list(payload)[:8]}"
                )
    else:
        raise AIError(f"模型返回的顶层是 {type(payload).__name__}，既不是对象也不是数组")

    if not isinstance(raw_cards, list):
        raise AIError("cards 字段不是数组")

    return parse_cards(raw_cards)


def _content_from_response(response: dict) -> str:
    """从 `/chat/completions` 的响应里取出正文。"""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AIError(f"接口返回里没有 choices。返回内容：{json.dumps(response, ensure_ascii=False)[:200]}")
    first = choices[0]
    if not isinstance(first, dict):
        raise AIError("choices[0] 不是对象")
    message = first.get("message")
    if not isinstance(message, dict):
        raise AIError("choices[0].message 不存在")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise AIError("模型返回的内容是空的（可能被 max_tokens 截断了）")
    return content


def strip_code_fence(text: str) -> str:
    """去掉 ```json ... ``` 包裹。

    明明在 prompt 里说了不要 Markdown，但模型经常还是加上。
    与其反复叮嘱，不如解析时容错。
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    # 去掉第一行（``` 或 ```json）
    lines = stripped.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    # 去掉最后的 ```
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_cards(raw_cards: list) -> list[cards_mod.Card]:
    """把模型给的原始数组变成 Card 列表。

    与 iOS 的 `parseCards` 一致的容错：
      - 缺 question 或 answer 的条目**跳过**，而不是整体失败。
        一块 8 张卡里坏 1 张，丢掉那 1 张比让整份文档作废好。
      - 超长字段截断而不是报错。模型偶尔多写几个字，没必要因此中断。
      - sourcePage < 1 当作没填。
      - difficulty / importance 夹到 1…5。
    """
    result: list[cards_mod.Card] = []

    for item in raw_cards:
        if not isinstance(item, dict):
            continue

        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if not question or not answer:
            continue

        detail = item.get("detail")
        detail_text = str(detail).strip() if detail is not None else ""
        if not detail_text:
            detail_text = ""

        tags_value = item.get("tags")
        tags: Optional[list[str]] = None
        if isinstance(tags_value, list):
            cleaned: list[str] = []
            for raw_tag in tags_value:
                tag = str(raw_tag).strip()
                if not tag:
                    continue
                if len(tag) > limits.TAG_LENGTH_MAX:
                    tag = tag[: limits.TAG_LENGTH_MAX]
                if tag not in cleaned:
                    cleaned.append(tag)
                if len(cleaned) >= limits.TAGS_MAX:
                    break
            tags = cleaned or None
        elif isinstance(tags_value, str) and tags_value.strip():
            tags = [tags_value.strip()[: limits.TAG_LENGTH_MAX]]

        source_page = _int_or_none(item.get("sourcePage"))
        if source_page is not None and source_page < 1:
            source_page = None

        difficulty = _int_or_none(item.get("difficulty"))
        importance = _int_or_none(item.get("importance"))

        result.append(
            cards_mod.Card(
                question=question[: limits.QUESTION_MAX],
                answer=answer[: limits.ANSWER_MAX],
                detail=detail_text[: limits.DETAIL_MAX] if detail_text else None,
                tags=tags,
                source_page=source_page,
                difficulty=limits.clamp_score(difficulty) if difficulty is not None else None,
                importance=limits.clamp_score(importance) if importance is not None else None,
            )
        )

    if not result:
        raise AIError("模型没有给出任何可用卡片（每条都缺题目或答案）")

    return result


def _int_or_none(value: Any) -> Optional[int]:
    """接 Int / 浮点 / 字符串数字。模型这三种都发过。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            try:
                return int(float(value.strip()))
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------------
# 去重
# ---------------------------------------------------------------------------

#: 归一化时要去掉的空白（含全角空格）
_SPACE_RE = re.compile(r"[\s\u3000]+")


def normalize_for_comparison(text: str) -> str:
    """把题面归一化后比较。

    只去掉空白、统一问号、转小写。别的都不动 —— 归一化太激进会把
    「电压与电流的关系」和「电流与电压的关系」当成同一张，而它们
    在复习时的侧重并不一样。
    """
    return _SPACE_RE.sub("", text).replace("？", "?").lower()


def deduplicate(items: list[cards_mod.Card]) -> list[cards_mod.Card]:
    """按归一化题面去重，保留先出现的。

    不同块之间可能有重叠内容（比如一章的总结页又讲了一遍前面的概念），
    重复的卡片在复习时很烦。
    """
    seen: set[str] = set()
    result: list[cards_mod.Card] = []
    for item in items:
        key = normalize_for_comparison(item.question)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _post_chat(
    config: AIConfig,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> str:
    """发一次请求，返回原始响应文本。

    `response_format: json_object` 不是所有兼容接口都支持（本地模型常见）。
    先带上试，如果服务端因为不认这个字段而返回 400，会自动去掉重发一次 ——
    见下面的 `_should_retry_without_json_mode`。
    """
    body = {
        "model": config.model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    return _post_json(config, body, cancel_check=cancel_check, allow_json_mode_retry=True)


def _post_json(
    config: AIConfig,
    body: dict,
    cancel_check: Optional[Callable[[], bool]] = None,
    allow_json_mode_retry: bool = False,
) -> str:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        config.chat_url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
            # 有些网关会按 User-Agent 拦请求，给个正常的
            "User-Agent": "PdfReviewPC/0.1",
        },
    )

    if cancel_check is not None and cancel_check():
        raise AICancelled("已取消")

    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = _read_error_body(exc)
        # 服务端不认 response_format：去掉再试一次
        if (
            allow_json_mode_retry
            and exc.code == 400
            and "response_format" in detail
        ):
            retry_body = dict(body)
            retry_body.pop("response_format", None)
            return _post_json(config, retry_body, cancel_check=cancel_check)
        raise _http_error(exc, detail) from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, socket.timeout):
            raise AIError(
                f"请求超时（等 {config.timeout:.0f} 秒没有回应）。"
                "文档很长时可以把「每块字符数」调小一点，分成多次分析。"
            ) from exc
        raise AIError(
            f"连不上接口：{reason}。检查一下地址对不对、网络通不通。"
        ) from exc
    except socket.timeout as exc:
        raise AIError(f"请求超时（{config.timeout:.0f} 秒）。") from exc
    except OSError as exc:
        raise AIError(f"网络错误：{exc}") from exc


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:500]
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
        message = parsed.get("message")
        if isinstance(message, str):
            return message
    return raw[:500]


def _http_error(exc: urllib.error.HTTPError, detail: str) -> AIError:
    code = exc.code
    hints = {
        400: "请求被拒绝。多半是模型名不对，或者这个接口不支持 JSON 模式。",
        401: "API Key 无效。检查一下 Key 有没有复制全、是不是过期了。",
        403: "这个 Key 没有权限访问该模型，或者账户余额不足。",
        404: "接口地址不对。多数服务要求地址带 /v1，例如 https://api.openai.com/v1。",
        429: "请求太频繁或超出配额。等一会儿再试，或者把「每块卡片数」调小。",
    }
    if code in hints:
        message = hints[code]
    elif 500 <= code < 600:
        message = "服务端出错。这通常是临时的，等几分钟再试。"
    else:
        message = f"接口返回 HTTP {code}。"

    if detail:
        message = f"{message}\n\n服务端原话：{detail}"

    error = AIError(message)
    error.status = code  # type: ignore[attr-defined]
    return error


# ---------------------------------------------------------------------------
# 连通性测试
# ---------------------------------------------------------------------------


def test_connection(config: AIConfig) -> str:
    """发一个最小的请求验证配置。返回一句给用户看的结果。"""
    config.validate()
    body = {
        "model": config.model,
        "messages": [{"role": "user", "content": "回答一个字：好"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    raw = _post_json(config, body)
    try:
        response = json.loads(raw)
        content = _content_from_response(response)
    except (json.JSONDecodeError, AIError):
        return f"连上了，但返回的内容看不懂：{raw[:120]}"
    return f"连接正常，模型回了一个：{content.strip()[:20]}"
