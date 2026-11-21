#!/usr/bin/env python3
"""独立校验生成的 project.pbxproj。

生成器自己有 check()，但那是自己检查自己。这个脚本换完全独立的手段：
先把 OpenStep plist 真正解析成 Python 字典（自己写的解析器，见下），
再逐项核对结构语义。

为什么不用 plistlib：Python 3.10 的 plistlib 只支持 XML 和 binary 两种
输入格式，OpenStep（就是 pbxproj 用的这种）只支持「写」不支持「读」，
loads() 一律抛 InvalidFileException。所以这里自己实现解析器。

能抓到的错误：
  - 格式根本不合法（Xcode 打开就报 "project is damaged"）
  - rootObject / targets / buildPhases 指向不存在的对象
  - 某个 .swift 文件没进任何 Sources phase
  - Widget 的 .appex 没被嵌入 App（用户装完看不到小组件）
  - 两个 target 的 Bundle ID / Info.plist / entitlements 路径不对
  - App Group 标识符两端不一致
  - Widget target 里混进了 import SwiftData 的文件
  - Shared/Core 的文件漏编进任一个 target

用法：
    python scripts/check_pbxproj.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PBXPROJ = ROOT / "PdfReview.xcodeproj" / "project.pbxproj"

APP_TARGET = "PdfReview"
WIDGET_TARGET = "PdfReviewWidget"
APP_BUNDLE_ID = "com.pdfreview.app"
WIDGET_BUNDLE_ID = "com.pdfreview.app.widget"
APP_GROUP = "group.com.pdfreview.app"


# --------------------------------------------------------------------------
# OpenStep plist 解析器
# --------------------------------------------------------------------------

class PlistError(Exception):
    """语法错误，附带出错位置方便定位。"""

    def __init__(self, message: str, pos: int, text: str) -> None:
        line = text.count("\n", 0, pos) + 1
        column = pos - text.rfind("\n", 0, pos)
        super().__init__(f"{message}（第 {line} 行第 {column} 列）")


class OpenStepParser:
    """解析 Xcode 的 pbxproj 方言。

    支持：
        字典    { key = value; ... }
        数组    ( a, b, c )
        字符串  "..."   或裸词（字母数字 _ $ / . - : 等）
        注释    /* ... */  与  // ...  （行首编码声明）

    字符串一律解析成 str，这一点和 Xcode 自己的行为一致——pbxproj 里没有
    数字或布尔类型，所有值都是字符串。
    """

    # 裸词允许的字符。Xcode 生成的文件里出现的都是这些。
    BARE = set(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        "_$/:.-"
    )

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.n = len(text)

    # -- 基础工具 ----------------------------------------------------------

    def error(self, message: str) -> PlistError:
        return PlistError(message, self.pos, self.text)

    def skip(self) -> None:
        """跳过空白和两种注释。"""
        while self.pos < self.n:
            ch = self.text[self.pos]
            if ch in " \t\r\n":
                self.pos += 1
            elif self.text.startswith("//", self.pos):
                end = self.text.find("\n", self.pos)
                self.pos = self.n if end < 0 else end + 1
            elif self.text.startswith("/*", self.pos):
                end = self.text.find("*/", self.pos + 2)
                if end < 0:
                    raise self.error("块注释没有闭合")
                self.pos = end + 2
            else:
                return

    def peek(self) -> str:
        self.skip()
        if self.pos >= self.n:
            raise self.error("文件意外结束")
        return self.text[self.pos]

    # -- 各种值 ------------------------------------------------------------

    def parse_value(self):
        ch = self.peek()
        if ch == "{":
            return self.parse_dict()
        if ch == "(":
            return self.parse_array()
        if ch == '"':
            return self.parse_quoted()
        return self.parse_bare()

    def parse_dict(self) -> dict:
        assert self.peek() == "{"
        self.pos += 1
        result: dict = {}
        while True:
            ch = self.peek()
            if ch == "}":
                self.pos += 1
                return result
            key = self.parse_quoted() if ch == '"' else self.parse_bare()
            if self.peek() != "=":
                raise self.error(f"键 {key!r} 后面缺少 =")
            self.pos += 1
            value = self.parse_value()
            if self.peek() != ";":
                raise self.error(f"键 {key!r} 的值后面缺少分号")
            self.pos += 1
            if key in result:
                raise self.error(f"字典里键 {key!r} 重复")
            result[key] = value

    def parse_array(self) -> list:
        assert self.peek() == "("
        self.pos += 1
        result: list = []
        while True:
            ch = self.peek()
            if ch == ")":
                self.pos += 1
                return result
            result.append(self.parse_value())
            ch = self.peek()
            if ch == ",":
                self.pos += 1
            elif ch == ")":
                continue
            else:
                raise self.error("数组元素之间缺少逗号")

    def parse_quoted(self) -> str:
        assert self.peek() == '"'
        self.pos += 1
        out: list[str] = []
        while True:
            if self.pos >= self.n:
                raise self.error("引号没有闭合")
            ch = self.text[self.pos]
            if ch == "\\":
                self.pos += 1
                if self.pos >= self.n:
                    raise self.error("转义符在文件末尾")
                nxt = self.text[self.pos]
                out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                self.pos += 1
            elif ch == '"':
                self.pos += 1
                return "".join(out)
            else:
                out.append(ch)
                self.pos += 1

    def parse_bare(self) -> str:
        start = self.pos
        while self.pos < self.n and self.text[self.pos] in self.BARE:
            self.pos += 1
        if self.pos == start:
            raise self.error(f"这里不该出现字符 {self.text[self.pos]!r}")
        return self.text[start:self.pos]

    def parse_document(self):
        value = self.parse_value()
        self.skip()
        if self.pos != self.n:
            raise self.error("主值后面还有多余内容")
        return value


def parse_pbxproj(text: str) -> dict:
    return OpenStepParser(text).parse_document()


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------

def main() -> int:
    if not PBXPROJ.exists():
        print(f"找不到 {PBXPROJ}")
        print("先跑：python scripts/generate_pbxproj.py")
        return 2

    raw = PBXPROJ.read_bytes()
    if raw[:3] == b"\xef\xbb\xbf":
        print("pbxproj 带了 UTF-8 BOM，Xcode 会拒绝打开。")
        return 1
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        print(f"pbxproj 不是合法 UTF-8：{exc}")
        return 1

    problems: list[str] = []
    notes: list[str] = []

    if not text.startswith("// !$*UTF8*$!"):
        problems.append("pbxproj 首行不是 `// !$*UTF8*$!` 编码声明")

    # ---- 1. 真正解析一遍 ----
    try:
        doc = parse_pbxproj(text)
    except PlistError as exc:
        print(f"pbxproj 语法错误：{exc}")
        print("Xcode 会直接报「project 已损坏」，无法打开。")
        return 1

    if not isinstance(doc, dict):
        print("pbxproj 顶层不是字典")
        return 1

    objects = doc.get("objects")
    root_id = doc.get("rootObject")
    if not isinstance(objects, dict) or not isinstance(root_id, str):
        print("pbxproj 缺少 objects 或 rootObject")
        return 1
    notes.append(f"OpenStep 解析成功，共 {len(objects)} 个对象")

    if doc.get("archiveVersion") != "1":
        problems.append(f"archiveVersion 是 {doc.get('archiveVersion')!r}，应为 '1'")
    if doc.get("objectVersion") != "56":
        notes.append(f"objectVersion = {doc.get('objectVersion')}（56 对应 Xcode 14+，可用）")

    root = objects.get(root_id)
    if not isinstance(root, dict):
        print(f"rootObject {root_id} 不存在")
        return 1
    if root.get("isa") != "PBXProject":
        problems.append(f"rootObject 的 isa 是 {root.get('isa')!r}，应为 PBXProject")

    # ---- 2. 悬空引用 ----
    referenced = set(re.findall(r"\b([0-9A-F]{24})\b", text))
    missing_ids = {i for i in referenced if i not in objects}
    if missing_ids:
        problems.append(
            f"有 {len(missing_ids)} 个被引用的对象 ID 不存在："
            f"{sorted(missing_ids)[:5]}"
        )
    else:
        notes.append(f"{len(referenced)} 个对象 ID 全部闭合")

    # ---- 3. 两个 target ----
    targets: dict[str, tuple[str, dict]] = {}
    for tid in root.get("targets", []):
        t = objects.get(tid)
        if not isinstance(t, dict):
            problems.append(f"targets 里列出的 {tid} 不存在")
            continue
        name = t.get("name")
        if isinstance(name, str):
            targets[name] = (tid, t)

    for name in (APP_TARGET, WIDGET_TARGET):
        if name not in targets:
            problems.append(f"缺少 target {name}")
    if APP_TARGET not in targets or WIDGET_TARGET not in targets:
        report(notes, problems)
        return 1

    # ---- 4. build settings ----
    def settings_of(target: dict) -> dict[str, str]:
        merged: dict[str, str] = {}
        list_id = target.get("buildConfigurationList")
        cfg_list = objects.get(list_id, {}) if isinstance(list_id, str) else {}
        for cfg_id in cfg_list.get("buildConfigurations", []):
            cfg = objects.get(cfg_id, {})
            settings = cfg.get("buildSettings", {})
            if isinstance(settings, dict):
                merged.update({k: v for k, v in settings.items() if isinstance(v, str)})
        return merged

    app_settings = settings_of(targets[APP_TARGET][1])
    widget_settings = settings_of(targets[WIDGET_TARGET][1])

    for label, settings, bid in (
        ("App", app_settings, APP_BUNDLE_ID),
        ("Widget", widget_settings, WIDGET_BUNDLE_ID),
    ):
        actual = settings.get("PRODUCT_BUNDLE_IDENTIFIER")
        if actual != bid:
            problems.append(f"{label} 的 Bundle ID 是 {actual!r}，应为 {bid!r}")
        else:
            notes.append(f"{label} Bundle ID 正确：{bid}")

    for label, settings, expected in (
        ("App", app_settings, "PdfReview/Resources/Info.plist"),
        ("Widget", widget_settings, "PdfReviewWidget/Resources/Info.plist"),
    ):
        actual = settings.get("INFOPLIST_FILE")
        if actual != expected:
            problems.append(f"{label} 的 INFOPLIST_FILE 是 {actual!r}，应为 {expected!r}")

    for label, settings, expected in (
        ("App", app_settings, "PdfReview/Resources/PdfReview.entitlements"),
        ("Widget", widget_settings, "PdfReviewWidget/Resources/PdfReviewWidget.entitlements"),
    ):
        actual = settings.get("CODE_SIGN_ENTITLEMENTS")
        if actual != expected:
            problems.append(f"{label} 的 CODE_SIGN_ENTITLEMENTS 是 {actual!r}，应为 {expected!r}")

    for label, settings in (("App", app_settings), ("Widget", widget_settings)):
        if settings.get("IPHONEOS_DEPLOYMENT_TARGET") != "17.0":
            problems.append(
                f"{label} 的 IPHONEOS_DEPLOYMENT_TARGET 是 "
                f"{settings.get('IPHONEOS_DEPLOYMENT_TARGET')!r}，应为 '17.0'"
            )
        if settings.get("SWIFT_VERSION") != "5.0":
            problems.append(
                f"{label} 的 SWIFT_VERSION 是 {settings.get('SWIFT_VERSION')!r}，应为 '5.0'"
            )
        if settings.get("GENERATE_INFOPLIST_FILE") == "YES":
            problems.append(
                f"{label} 开了 GENERATE_INFOPLIST_FILE，会与手写 Info.plist 冲突"
            )

    # ---- 5. Sources phase ----
    def paths_in_phase_type(target: dict, isa: str) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for ph_id in target.get("buildPhases", []):
            ph = objects.get(ph_id, {})
            if ph.get("isa") != isa:
                continue
            for bf_id in ph.get("files", []):
                bf = objects.get(bf_id, {})
                ref = objects.get(bf.get("fileRef", ""), {})
                path = ref.get("path")
                if isinstance(path, str):
                    out.append((path, ph))
        return out

    app_sources = {p for p, _ in paths_in_phase_type(targets[APP_TARGET][1], "PBXSourcesBuildPhase")}
    widget_sources = {p for p, _ in paths_in_phase_type(targets[WIDGET_TARGET][1], "PBXSourcesBuildPhase")}

    notes.append(f"App Sources phase：{len(app_sources)} 个文件")
    notes.append(f"Widget Sources phase：{len(widget_sources)} 个文件")

    disk_app = {p.name for p in (ROOT / "PdfReview").rglob("*.swift")}
    disk_widget = {p.name for p in (ROOT / "PdfReviewWidget").rglob("*.swift")}
    disk_shared = {p.name for p in (ROOT / "Shared").rglob("*.swift")}
    disk_core = {p.name for p in (ROOT / "Shared" / "Core").rglob("*.swift")}

    for label, disk, in_phase in (
        ("App", disk_app, app_sources),
        ("Widget", disk_widget, widget_sources),
    ):
        missing = disk - in_phase
        if missing:
            problems.append(f"这些 {label} 源文件没进 Sources phase：{sorted(missing)}")
        else:
            notes.append(f"{label} 下全部 .swift 均已编入")

    miss_core_app = disk_core - app_sources
    miss_core_widget = disk_core - widget_sources
    if miss_core_app:
        problems.append(f"Shared/Core 这些文件没进 App target：{sorted(miss_core_app)}")
    if miss_core_widget:
        problems.append(f"Shared/Core 这些文件没进 Widget target：{sorted(miss_core_widget)}")
    if not miss_core_app and not miss_core_widget:
        notes.append(f"Shared/Core 的 {len(disk_core)} 个文件两端都在")

    # Widget 不许依赖 SwiftData
    swiftdata_files: set[str] = set()
    for base in (ROOT / "Shared", ROOT / "PdfReviewWidget"):
        for p in base.rglob("*.swift"):
            body = p.read_text(encoding="utf-8")
            if re.search(r"^\s*import\s+SwiftData", body, re.MULTILINE):
                swiftdata_files.add(p.name)
    leaked = swiftdata_files & widget_sources
    if leaked:
        problems.append(
            f"Widget target 混进了 import SwiftData 的文件 {sorted(leaked)}，"
            f"小组件扩展里会崩"
        )
    else:
        notes.append("Widget target 无 SwiftData 依赖")

    wrongly = (disk_shared - disk_core) & widget_sources
    if wrongly:
        problems.append(f"Shared 下的 App 专用文件混进了 Widget target：{sorted(wrongly)}")

    # ---- 6. .appex 嵌入 ----
    app_target = targets[APP_TARGET][1]
    copy_phases = []
    embedded = False
    for ph_id in app_target.get("buildPhases", []):
        ph = objects.get(ph_id, {})
        if ph.get("isa") != "PBXCopyFilesBuildPhase":
            continue
        copy_phases.append(ph)
        for bf_id in ph.get("files", []):
            bf = objects.get(bf_id, {})
            ref = objects.get(bf.get("fileRef", ""), {})
            if str(ref.get("path", "")).endswith(".appex"):
                embedded = True
                if ph.get("dstSubfolderSpec") != "13":
                    problems.append(
                        f"嵌入 .appex 的 CopyFiles phase dstSubfolderSpec 是 "
                        f"{ph.get('dstSubfolderSpec')!r}，应为 '13'（PlugIns）"
                    )
    if not copy_phases:
        problems.append("App target 没有 PBXCopyFilesBuildPhase，小组件不会被装进 App")
    elif not embedded:
        problems.append("PBXCopyFilesBuildPhase 里没有 .appex，小组件不会被装进 App")
    else:
        notes.append("Widget .appex 已通过 CopyFiles phase 嵌入（dstSubfolderSpec=13）")

    # ---- 7. target 依赖 ----
    deps = app_target.get("dependencies", [])
    if not deps:
        problems.append("App target 没有 dependencies，构建顺序无保证")
    else:
        found = False
        for dep_id in deps:
            dep = objects.get(dep_id, {})
            if dep.get("target") == targets[WIDGET_TARGET][0]:
                found = True
                proxy = objects.get(dep.get("targetProxy", ""), {})
                if proxy.get("proxyType") != "1":
                    problems.append(
                        f"PBXContainerItemProxy 的 proxyType 是 "
                        f"{proxy.get('proxyType')!r}，应为 '1'"
                    )
        if found:
            notes.append("App 依赖 Widget target，proxyType=1")
        else:
            problems.append("App 的 dependencies 里没有指向 Widget target")

    # ---- 8. entitlements 的 App Group ----
    for label, rel in (
        ("App", "PdfReview/Resources/PdfReview.entitlements"),
        ("Widget", "PdfReviewWidget/Resources/PdfReviewWidget.entitlements"),
    ):
        path = ROOT / rel
        if not path.exists():
            problems.append(f"{label} 的 entitlements 文件不存在：{rel}")
            continue
        body = path.read_text(encoding="utf-8")
        if APP_GROUP not in body:
            problems.append(f"{label} 的 entitlements 里没有 {APP_GROUP}")
        else:
            notes.append(f"{label} entitlements 含 {APP_GROUP}")

    # ---- 9. 把 group 树还原成真实路径，验证每个资源/源码文件确实在磁盘上 ----
    #
    # fileRef 的 path 只写文件名，真实位置靠父组逐级拼接。少写一层 group 的
    # path，子项就全落到工程根——Xcode 会说 "Build input file cannot be
    # found"，但不告诉你是哪个组。这里自己走一遍树，把拼出来的路径与磁盘比对。
    children_of: dict[str, list] = {}
    parent_of: dict[str, str] = {}
    for oid_, obj in objects.items():
        if not isinstance(obj, dict) or obj.get("isa") != "PBXGroup":
            continue
        for child in obj.get("children", []):
            child_id = child.split(" // ")[0].strip()
            children_of.setdefault(oid_, []).append(child_id)
            parent_of[child_id] = oid_

    def real_path(object_id: str) -> str | None:
        """从 fileRef 往上爬到 mainGroup，拼出相对工程根的路径。"""
        parts: list[str] = []
        current = object_id
        seen: set[str] = set()
        while current in objects and current not in seen:
            seen.add(current)
            obj = objects[current]
            isa = obj.get("isa")
            if isa == "PBXGroup" and current == root.get("mainGroup"):
                break
            path = obj.get("path")
            if isinstance(path, str) and path:
                parts.append(path)
            elif isa == "PBXGroup":
                name = obj.get("name")
                if isinstance(name, str) and name:
                    parts.append(name)
            tree = obj.get("sourceTree", "")
            if tree != "<group>":
                # SOURCE_ROOT 之外的基准（BUILT_PRODUCTS_DIR 等）拼不出来
                return None
            nxt = parent_of.get(current)
            if nxt is None:
                break
            current = nxt
        return "/".join(reversed(parts)) if parts else None

    checked = 0
    for label, tid in ((APP_TARGET, targets[APP_TARGET][0]),
                       (WIDGET_TARGET, targets[WIDGET_TARGET][0])):
        target = objects[tid]
        for phase_key in ("buildPhases",):
            for ph_id in target.get(phase_key, []):
                ph = objects.get(ph_id, {})
                if ph.get("isa") not in ("PBXSourcesBuildPhase", "PBXResourcesBuildPhase"):
                    continue
                for bf_id in ph.get("files", []):
                    bf = objects.get(bf_id, {})
                    ref_id = bf.get("fileRef")
                    if not isinstance(ref_id, str):
                        continue
                    resolved = real_path(ref_id)
                    if resolved is None:
                        continue
                    checked += 1
                    if not (ROOT / resolved).exists():
                        kind = "源文件" if ph["isa"] == "PBXSourcesBuildPhase" else "资源"
                        problems.append(
                            f"{label} 的{kind}解析成 {resolved!r}，磁盘上不存在"
                            f"（多半是某个 PBXGroup 少了 path）"
                        )

    if checked and not any("磁盘上不存在" in p for p in problems):
        notes.append(f"{checked} 个构建文件的 group 路径全部还原正确")

    report(notes, problems)
    return 0 if not problems else 1


def report(notes: list[str], problems: list[str]) -> None:
    print("=" * 70)
    print("project.pbxproj 独立校验（自写 OpenStep 解析器，不依赖 plistlib）")
    print("=" * 70)
    for n in notes:
        print(f"  OK   {n}")
    print()
    if problems:
        print(f"发现 {len(problems)} 个问题：\n")
        for i, p in enumerate(problems, 1):
            print(f"{i:>3}. {p}")
        return
    print("结构合法，target 归属与签名配置正确。")
    print()
    print("注意：这验证的是工程文件的结构，不是「Xcode 能编译通过」。")
    print("编译必须在 macOS 上做。")


if __name__ == "__main__":
    sys.exit(main())
