#!/usr/bin/env python3
"""交叉核对 .pdfreview.json 格式标准的三份真相源。

格式标准分散在三个地方，任何一处改了另外两处没跟上，用户就会遇到
「文档说能导入，App 说格式错」这类最难查的问题：

  A. schema/analysis.v1.schema.json  —— 给外部工具和校验器看的机器可读定义
  B. Shared/Models/AnalysisDocument.swift 的 AnalysisValidator —— App 实际执行的校验
  C. docs/pdf-analysis-format.md     —— 给人看的说明

这个脚本逐项比对三者的数字与规则，并用 A + B 的合并语义去验 schema 里
声明的每个约束、跑一遍 samples/ 下的示例文件。

不依赖 jsonschema 库（本机没装），自己实现需要的那部分 JSON Schema 子集：
type / required / additionalProperties / properties / items / minItems /
maxItems / minLength / maxLength / minimum / maximum / pattern / const /
uniqueItems / $ref / $defs。

用法：
    python scripts/check_format_consistency.py
    python scripts/check_format_consistency.py --verbose
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "analysis.v1.schema.json"
SWIFT_PATH = ROOT / "Shared" / "Models" / "AnalysisDocument.swift"
DOC_PATH = ROOT / "docs" / "pdf-analysis-format.md"
PC_LIMITS_PATH = ROOT / "pc" / "core" / "limits.py"
SAMPLES_DIR = ROOT / "samples"


# --------------------------------------------------------------------------
# 一个够用的 JSON Schema 校验器（draft 2020-12 的子集）
# --------------------------------------------------------------------------

class SchemaError(Exception):
    pass


def validate(instance, schema, root, path="$"):
    """返回错误信息列表。空列表 = 通过。"""
    errors: list[str] = []

    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            return [f"{path}: 不支持的外部 $ref {ref}"]
        node = root
        for part in ref[2:].split("/"):
            node = node[part]
        return validate(instance, node, root, path)

    t = schema.get("type")
    if t is not None and not type_ok(instance, t):
        return [f"{path}: 类型应为 {t}，实际是 {type(instance).__name__}"]

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
            errors.append(f"{path}: 至少 {schema['minItems']} 项，实际 {len(instance)}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: 最多 {schema['maxItems']} 项，实际 {len(instance)}")
        if schema.get("uniqueItems"):
            seen, dups = set(), set()
            for item in instance:
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
                if key in seen:
                    dups.add(key)
                seen.add(key)
            if dups:
                errors.append(f"{path}: uniqueItems 不满足，重复项 {sorted(dups)}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(instance):
                errors.extend(validate(item, item_schema, root, f"{path}[{i}]"))

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: 缺少必填字段 {key!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append(f"{path}: 出现未定义字段 {key!r}")
        for key, sub in props.items():
            if key in instance:
                errors.extend(validate(instance[key], sub, root, f"{path}.{key}"))

    return errors


# 与 schema 的 generatedAt.pattern 一致：必须有日期、时间与 Z 或 ±HH:MM 时区。
ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$"
)


def iso8601_ok(value: str) -> bool:
    """近似 Swift 的 AnalysisValidator.isISO8601：必须带时区。"""
    return bool(ISO8601_RE.match(value))


def type_ok(value, expected) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True  # 不认识的类型不拦


# --------------------------------------------------------------------------
# 从 Swift 源码里抠常量和校验规则
# --------------------------------------------------------------------------

def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def swift_limits(src: str) -> dict[str, int]:
    """解析 AnalysisValidator.Limits 里的 `static let name = <int>`。"""
    limits: dict[str, int] = {}
    block = re.search(r"enum Limits\s*\{(.*?)\n    \}", src, re.DOTALL)
    if not block:
        return limits
    for m in re.finditer(r"static let (\w+)\s*=\s*(\d+)", block.group(1)):
        limits[m.group(1)] = int(m.group(2))
    return limits


def swift_supported_version(src: str) -> str | None:
    m = re.search(r'static let supportedVersion\s*=\s*"([^"]+)"', src)
    return m.group(1) if m else None


def swift_max_file_bytes(src: str) -> int | None:
    m = re.search(r"static let maxFileBytes\s*=\s*(\d+)\s*\*\s*(\d+)\s*\*\s*(\d+)", src)
    if m:
        return int(m.group(1)) * int(m.group(2)) * int(m.group(3))
    m = re.search(r"static let maxFileBytes\s*=\s*(\d+)", src)
    return int(m.group(1)) if m else None


def swift_known_keys(src: str) -> dict[str, set[str]]:
    """解析 KnownKeys 里每一层的白名单。"""
    result: dict[str, set[str]] = {}
    block = re.search(r"enum KnownKeys\s*\{(.*?)\n    \}", src, re.DOTALL)
    if not block:
        return result
    for m in re.finditer(r"static let (\w+)\s*:\s*Set<String>\s*=\s*\[(.*?)\]",
                         block.group(1), re.DOTALL):
        keys = set(re.findall(r'"([^"]+)"', m.group(2)))
        result[m.group(1)] = keys
    return result


def pc_limits(src: str) -> dict[str, object]:
    """从 `pc/core/limits.py` 里抠出常量，用于第四方比对。

    PC 版是独立实现的，最容易出的问题不是「写错了」而是「有一天 iOS 改了，
    PC 没跟着改」。这种偏差不会报错——它只是让两边的导入行为悄悄不一致，
    直到用户碰到一份刚好卡在边界上的文件。
    """
    out: dict[str, object] = {}

    simple = {
        "QUESTION_MAX": "questionMax",
        "ANSWER_MAX": "answerMax",
        "DETAIL_MAX": "detailMax",
        "TAGS_MAX": "tagsMax",
        "TAG_LENGTH_MAX": "tagLengthMax",
        "CARDS_MAX": "cardsMax",
        "TITLE_MAX": "titleMax",
        "SUMMARY_MAX": "summaryMax",
        "GENERATOR_MAX": "generatorMax",
        "SCORE_MIN": "scoreMin",
        "SCORE_MAX": "scoreMax",
        "CHUNK_MAX_CHARS": "chunkMaxChars",
    }
    for const, key in simple.items():
        match = re.search(rf"^{const}\s*=\s*([0-9][0-9_]*)\s*$", src, re.MULTILINE)
        if match:
            out[key] = int(match.group(1).replace("_", ""))

    version = re.search(r'^SUPPORTED_VERSION\s*=\s*"([^"]+)"', src, re.MULTILINE)
    if version:
        out["supportedVersion"] = version.group(1)

    # MAX_FILE_BYTES = 8 * 1024 * 1024
    size = re.search(
        r"^MAX_FILE_BYTES\s*=\s*(\d+)\s*\*\s*(\d+)\s*\*\s*(\d+)", src, re.MULTILINE
    )
    if size:
        out["maxFileBytes"] = int(size.group(1)) * int(size.group(2)) * int(size.group(3))
    else:
        size = re.search(r"^MAX_FILE_BYTES\s*=\s*(\d+)\s*$", src, re.MULTILINE)
        if size:
            out["maxFileBytes"] = int(size.group(1))

    return out


def schema_constraints(schema: dict) -> dict[str, object]:
    """把 schema 里关心的数字提取成扁平字典，便于和 Swift 比对。"""
    card = schema["$defs"]["card"]
    out = {
        "cardsMin": schema["properties"]["cards"]["minItems"],
        "cardsMax": schema["properties"]["cards"]["maxItems"],
        "titleMax": schema["properties"]["deck"]["properties"]["title"]["maxLength"],
        "questionMax": card["properties"]["question"]["maxLength"],
        "answerMax": card["properties"]["answer"]["maxLength"],
        "tagsMax": card["properties"]["tags"]["maxItems"],
        "tagLengthMax": card["properties"]["tags"]["items"]["maxLength"],
        "difficultyMin": card["properties"]["difficulty"]["minimum"],
        "difficultyMax": card["properties"]["difficulty"]["maximum"],
        "importanceMin": card["properties"]["importance"]["minimum"],
        "importanceMax": card["properties"]["importance"]["maximum"],
        "sourcePageMin": card["properties"]["sourcePage"]["minimum"],
        "schemaVersionConst": schema["properties"]["schemaVersion"].get("const"),
        "generatorMax": schema["properties"]["generator"].get("maxLength"),
        "deckSummaryMax": schema["properties"]["deck"]["properties"]["summary"].get("maxLength"),
    }
    if "maxLength" in card["properties"].get("detail", {}):
        out["detailMax"] = card["properties"]["detail"]["maxLength"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    problems: list[str] = []
    notes: list[str] = []

    for path in (SCHEMA_PATH, SWIFT_PATH, DOC_PATH):
        if not path.exists():
            print(f"缺少文件：{path}")
            return 2

    schema = json.loads(read(SCHEMA_PATH))
    swift = read(SWIFT_PATH)
    doc = read(DOC_PATH)

    limits = swift_limits(swift)
    constraints = schema_constraints(schema)
    supported = swift_supported_version(swift)

    # ---- 1. 版本号 ----
    if supported != constraints["schemaVersionConst"]:
        problems.append(
            f"版本号不一致：Swift supportedVersion={supported!r}，"
            f"schema const={constraints['schemaVersionConst']!r}"
        )
    else:
        notes.append(f"版本号一致：{supported!r}")

    # ---- 2. 数字约束逐项比对 ----
    pairs = [
        ("cardsMax", "cardsMax", "卡片数量上限"),
        ("titleMax", "titleMax", "牌组标题上限"),
        ("questionMax", "questionMax", "题目上限"),
        ("answerMax", "answerMax", "答案上限"),
        ("detailMax", "detailMax", "补充说明上限"),
        ("tagsMax", "tagsMax", "标签数量上限"),
        ("tagLengthMax", "tagLengthMax", "单个标签长度上限"),
    ]
    for swift_key, schema_key, label in pairs:
        s_val = limits.get(swift_key)
        c_val = constraints.get(schema_key)
        if s_val is None:
            problems.append(f"Swift 里找不到 Limits.{swift_key}（{label}）")
        elif c_val is None:
            problems.append(f"schema 里找不到 {schema_key}（{label}），Swift 是 {s_val}")
        elif s_val != c_val:
            problems.append(
                f"{label}不一致：Swift Limits.{swift_key}={s_val}，schema {schema_key}={c_val}"
            )
        else:
            notes.append(f"{label}一致：{s_val}")

    # ---- 3. PC 版的常量必须与 Swift 一致 ----
    if not PC_LIMITS_PATH.exists():
        problems.append(f"找不到 PC 版的常量文件：{PC_LIMITS_PATH}")
    else:
        pc = pc_limits(read(PC_LIMITS_PATH))
        pc_pairs = [
            ("questionMax", "题目上限"),
            ("answerMax", "答案上限"),
            ("detailMax", "补充说明上限"),
            ("tagsMax", "标签数量上限"),
            ("tagLengthMax", "单个标签长度上限"),
            ("cardsMax", "卡片数量上限"),
            ("titleMax", "牌组标题上限"),
            ("maxFileBytes", "单文件体积上限"),
        ]
        for key, label in pc_pairs:
            s_val = limits.get(key) if key != "maxFileBytes" else swift_max_file_bytes(swift)
            p_val = pc.get(key)
            if p_val is None:
                problems.append(f"PC 版 limits.py 里找不到 {key}（{label}）")
            elif s_val is not None and s_val != p_val:
                problems.append(
                    f"{label}在两端不一致：Swift={s_val}，PC={p_val}"
                )
            elif s_val is not None:
                notes.append(f"{label}两端一致：{p_val}")

        pc_version = pc.get("supportedVersion")
        if pc_version is None:
            problems.append("PC 版 limits.py 里找不到 SUPPORTED_VERSION")
        elif pc_version != supported:
            problems.append(
                f"格式版本号两端不一致：Swift={supported!r}，PC={pc_version!r}"
            )
        else:
            notes.append(f"格式版本号两端一致：{pc_version!r}")

    # ---- 4. schema 的 additionalProperties:false 必须与 KnownKeys 对得上 ----
    known = swift_known_keys(swift)
    schema_key_sets = {
        "root": set(schema["properties"].keys()),
        "source": set(schema["properties"]["source"]["properties"].keys()),
        "deck": set(schema["properties"]["deck"]["properties"].keys()),
        "card": set(schema["$defs"]["card"]["properties"].keys()),
    }
    if not known:
        problems.append(
            "Swift 里找不到 KnownKeys 白名单；未知字段检查没有生效，"
            "schema 的 additionalProperties:false 在 App 侧无人执行"
        )
    else:
        for layer, schema_keys in schema_key_sets.items():
            swift_keys = known.get(layer)
            if swift_keys is None:
                problems.append(f"Swift KnownKeys 缺少 {layer} 层")
                continue
            if swift_keys != schema_keys:
                only_swift = swift_keys - schema_keys
                only_schema = schema_keys - swift_keys
                detail = []
                if only_schema:
                    detail.append(f"schema 有而 Swift 没有 {sorted(only_schema)}")
                if only_swift:
                    detail.append(f"Swift 有而 schema 没有 {sorted(only_swift)}")
                problems.append(
                    f"{layer} 层字段白名单不一致：" + "；".join(detail)
                )
            else:
                notes.append(f"{layer} 层字段白名单一致（{len(schema_keys)} 个字段）")

    # ---- 4. schema 声明了、但 Swift 没校验的约束 ----
    # 这不是错误——Swift 可以放宽，但必须是有意为之。列出来让人确认。
    unchecked: list[str] = []
    if constraints.get("generatorMax") and "generatorMax" not in limits:
        unchecked.append(
            f"generator 的 maxLength={constraints['generatorMax']}（可选字段，"
            f"App 未校验，仅 schema 约束）"
        )
    if constraints.get("deckSummaryMax") and "summaryMax" not in limits:
        unchecked.append(
            f"deck.summary 的 maxLength={constraints['deckSummaryMax']}（可选字段，"
            f"App 未校验，仅 schema 约束）"
        )
    if constraints.get("sourcePageMin") and "sourcePageMin" not in limits:
        pass  # Swift 用专门的 invalidPage 错误，等价，不算缺失

    # ---- 5. 文档里的关键数字 ----
    doc_checks = [
        ("题目 500", r"1…500\s*字", "questionMax=500"),
        ("答案 2000", r"1…2000\s*字", "answerMax=2000"),
        ("标签 8 个", r"≤8\s*个", "tagsMax=8"),
        ("标签 32 字", r"1…32\s*字", "tagLengthMax=32"),
        ("卡片 500 张", r"最多\s*500\s*张|1…500\s*张|≤\s*500", "cardsMax=500"),
        ("牌组标题 200", r"1…200\s*字", "titleMax=200"),
    ]
    for label, pattern, expected in doc_checks:
        if not re.search(pattern, doc):
            problems.append(f"文档里找不到「{label}」的约束说明（对应 {expected}）")
        else:
            notes.append(f"文档已写明 {label}")

    # 文档里的校验规则条数应与实际实现相符
    rule_rows = re.findall(r"^\|\s*(\d+)\s*\|", doc, re.MULTILINE)
    if rule_rows:
        declared = max(int(x) for x in rule_rows)
        notes.append(f"文档声明了 {declared} 条校验规则")

    # ---- 6. 用 schema 校验 samples/ ----
    samples = sorted(SAMPLES_DIR.glob("*.json"))
    if not samples:
        problems.append("samples/ 下没有示例文件")
    for sample in samples:
        try:
            data = json.loads(read(sample))
        except json.JSONDecodeError as exc:
            problems.append(f"{sample.name}: 不是合法 JSON —— {exc}")
            continue

        errs = validate(data, schema, schema)
        if errs:
            for e in errs:
                problems.append(f"{sample.name}: {e}")
        else:
            notes.append(f"{sample.name} 通过 schema 校验")

        # 再用 Swift 的语义补校验（schema 没管但 App 会拒绝的）
        cards = data.get("cards", [])
        if isinstance(cards, list):
            for i, card in enumerate(cards):
                if not isinstance(card, dict):
                    continue
                for field in ("question", "answer"):
                    val = card.get(field)
                    if isinstance(val, str) and not val.strip():
                        problems.append(
                            f"{sample.name}: cards[{i}].{field} 全是空白字符，"
                            f"Swift 的 validate 会抛 fieldEmpty"
                        )
                tags = card.get("tags") or []
                if tags and len(tags) != len(set(tags)):
                    problems.append(
                        f"{sample.name}: cards[{i}].tags 有重复项，"
                        f"Swift 的 validate 会抛 duplicateTag"
                    )

        # Swift 的 isISO8601 会拒绝无时区的时间，示例必须能过
        stamp = data.get("generatedAt")
        if isinstance(stamp, str) and not iso8601_ok(stamp):
            problems.append(
                f"{sample.name}: generatedAt={stamp!r} 过不了 Swift 的 isISO8601 "
                f"（必须带 Z 或 ±HH:MM 时区）"
            )

    # ---- 7. 文件体积上限 ----
    max_bytes = swift_max_file_bytes(swift)
    if max_bytes is None:
        problems.append("Swift 里找不到 maxFileBytes")
    else:
        mb = max_bytes // (1024 * 1024)
        notes.append(f"单文件上限 {mb} MB")
        if not re.search(rf"{mb}\s*MB", doc):
            problems.append(f"文档里没写单文件上限 {mb} MB")
        for sample in samples:
            size = sample.stat().st_size
            if size > max_bytes:
                problems.append(f"{sample.name} 体积 {size} 字节，超过上限 {max_bytes}")

    # ---- 输出 ----
    print("=" * 70)
    print("PdfReview 格式标准一致性检查")
    print("=" * 70)

    if args.verbose:
        for n in notes:
            print(f"  OK   {n}")
        print()

    if unchecked:
        print("以下约束只在 schema 里声明、App 未执行（可能是有意放宽，请确认）：")
        for u in unchecked:
            print(f"  --   {u}")
        print()

    if problems:
        print(f"发现 {len(problems)} 个问题：\n")
        for i, p in enumerate(problems, 1):
            print(f"{i:>3}. {p}")
        return 1

    print("三份真相源一致，示例文件全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
