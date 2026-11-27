"""按 `schema/analysis.v1.schema.json` 校验导出的 JSON。

**为什么这里要自己写一个校验器，而不是装 `jsonschema`**：
  - 打包成 exe 后，`jsonschema` 是一个几百 KB 的依赖，而它支持的那一整套
    关键字我们只用到十来个。
  - 仓库根目录的 `scripts/check_format_consistency.py` 里已经有一个同类实现
    （那个脚本跑在开发机上，不能打进 exe）。这里复刻它的语义，让"导出前
    在电脑上校验"与"CI 里校验 schema 本身"用同一套规则。

**与 `cards.AnalysisDocument.validate()` 的分工**（两边都要过）：
  - 这里查**结构**：类型对不对、必填有没有、有没有多余字段、正则匹配。
  - 那边查**语义**：长度、非空、范围、标签去重。
  一条数据可能结构合法但语义不合法（例如 `question: ""` 类型对、长度不足
  1），也可能反过来。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

#: schema 文件位置。开发时读仓库里的那一份；打包后读随包带的那一份
#: （见 `packaging.py` 里对 `--add-data` 的说明）。
_SCHEMA_CACHE: Optional[dict] = None


def schema_path() -> Path:
    """schema 文件在哪。

    两种布局都要认：
      1. 开发时：`<repo>/pc/core/schema_check.py` → `<repo>/schema/...`
      2. 打包后：`<_MEIPASS>/schema/...`（PyInstaller 的 `--add-data`）

    找不到就抛 FileNotFoundError —— 宁可启动时报错，也不要偷偷跳过校验。
    """
    import sys

    # PyInstaller 解包目录
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / "schema" / "analysis.v1.schema.json"
        if candidate.exists():
            return candidate

    here = Path(__file__).resolve()
    # pc/core/schema_check.py → 上两级是仓库根
    candidate = here.parent.parent.parent / "schema" / "analysis.v1.schema.json"
    if candidate.exists():
        return candidate

    raise FileNotFoundError("找不到 schema/analysis.v1.schema.json")


def load_schema() -> dict:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = json.loads(schema_path().read_text(encoding="utf-8"))
    return _SCHEMA_CACHE


class SchemaViolation(Exception):
    """schema 校验失败。`errors` 里是逐条问题，界面可以全部列出来。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("；".join(errors[:3]))
        self.errors = errors


# ---------------------------------------------------------------------------
# 校验核心
# ---------------------------------------------------------------------------


def validate_document(data: Any) -> list[str]:
    """校验一份已解析成 Python 对象的文档。返回错误列表，空表示通过。"""
    return validate(data, load_schema(), load_schema(), "$")


def validate_file(path: Path | str) -> list[str]:
    """读文件并校验。读不出来时把 IO/JSON 错误也当一条错误返回。"""
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        return [f"读不了文件：{exc}"]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"不是合法的 JSON：{exc}"]
    return validate_document(data)


def validate(instance: Any, schema: dict, root: dict, path: str = "$") -> list[str]:
    """递归校验。语义与 `scripts/check_format_consistency.py` 的同名函数一致。"""
    errors: list[str] = []

    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            return [f"{path}: 不支持的外部 $ref {ref}"]
        node = root
        for part in ref[2:].split("/"):
            node = node[part]
        return validate(instance, node, root, path)

    expected_type = schema.get("type")
    if expected_type is not None and not _type_ok(instance, expected_type):
        return [
            f"{path}: 类型应为 {expected_type}，实际是 {type(instance).__name__}"
        ]

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: 必须等于 {schema['const']!r}，实际是 {instance!r}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(
                f"{path}: 长度 {len(instance)} 小于下限 {schema['minLength']}"
            )
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(
                f"{path}: 长度 {len(instance)} 超过上限 {schema['maxLength']}"
            )
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(
                f"{path}: 不匹配 pattern {schema['pattern']!r}，实际 {instance!r}"
            )

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} 小于最小值 {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} 超过最大值 {schema['maximum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(
                f"{path}: 至少 {schema['minItems']} 项，实际 {len(instance)}"
            )
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(
                f"{path}: 最多 {schema['maxItems']} 项，实际 {len(instance)}"
            )
        if schema.get("uniqueItems"):
            seen: set[str] = set()
            duplicates: set[str] = set()
            for item in instance:
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
                if key in seen:
                    duplicates.add(key)
                seen.add(key)
            if duplicates:
                errors.append(f"{path}: uniqueItems 不满足，重复项 {sorted(duplicates)}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                errors.extend(validate(item, item_schema, root, f"{path}[{index}]"))

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: 缺少必填字段 {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in properties:
                    errors.append(f"{path}: 出现未定义字段 {key!r}")
        for key, sub_schema in properties.items():
            if key in instance:
                errors.extend(
                    validate(instance[key], sub_schema, root, f"{path}.{key}")
                )

    return errors


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        # bool 是 int 的子类，要排除，否则 True 会被当成 1 通关
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True  # 不认识的类型不拦，免得静默放过真正关心的问题


# ---------------------------------------------------------------------------
# 未知字段检查（与 iOS 的 `checkUnknownFields` 对齐）
# ---------------------------------------------------------------------------

#: iOS 的 `AnalysisDocument.KnownKeys` 里那几个集合。这里写一份是为了在
#: schema 文件缺失或过期时仍能拦住多余字段 —— 多一个字段 iOS 会整个拒收，
#: 代价比少一个字段大得多。
KNOWN_ROOT_KEYS = frozenset(
    {"schemaVersion", "generator", "generatedAt", "source", "deck", "cards"}
)
KNOWN_SOURCE_KEYS = frozenset({"fileName", "pageCount", "sha256"})
KNOWN_DECK_KEYS = frozenset({"title", "summary", "language"})
KNOWN_CARD_KEYS = frozenset(
    {"question", "answer", "detail", "tags", "sourcePage", "difficulty", "importance"}
)


def check_unknown_keys(data: Any) -> list[str]:
    """逐层检查有没有 schema 之外的字段。返回错误列表。"""
    if not isinstance(data, dict):
        return ["$: 顶层不是对象"]

    errors: list[str] = []

    for key in data:
        if key not in KNOWN_ROOT_KEYS:
            errors.append(f"$: 出现未定义字段 {key!r}")

    source = data.get("source")
    if isinstance(source, dict):
        for key in source:
            if key not in KNOWN_SOURCE_KEYS:
                errors.append(f"$.source: 出现未定义字段 {key!r}")

    deck = data.get("deck")
    if isinstance(deck, dict):
        for key in deck:
            if key not in KNOWN_DECK_KEYS:
                errors.append(f"$.deck: 出现未定义字段 {key!r}")

    cards = data.get("cards")
    if isinstance(cards, list):
        for index, card in enumerate(cards):
            if not isinstance(card, dict):
                errors.append(f"$.cards[{index}]: 不是对象")
                continue
            for key in card:
                if key not in KNOWN_CARD_KEYS:
                    errors.append(f"$.cards[{index}]: 出现未定义字段 {key!r}")

    return errors


def ensure_valid(data: Any) -> None:
    """结构 + 未知字段都过，否则抛 SchemaViolation。导出前调用这个。"""
    errors = validate_document(data) + check_unknown_keys(data)
    if errors:
        raise SchemaViolation(errors)
