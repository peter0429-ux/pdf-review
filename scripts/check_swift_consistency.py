#!/usr/bin/env python3
"""静态检查 PdfReview 的 Swift 源码跨文件一致性。

本机是 Windows，没有 swiftc / xcodebuild，无法真正编译。这个脚本用正则做
近似解析，专门抓那几类「编译器一句话就报、人眼扫几千行却总会漏」的错误：

  1. 某个类型项目里定义过，却没编进当前 target —— 典型场景是把文件从
     Shared/ 挪到 Shared/Core/ 之后忘了改 target 归属。Widget 会因为看不到
     ReviewCard 而编译失败，症状却是「Cannot find 'ReviewCard' in scope」。
  2. 同一类型名在两个文件里重复定义（Swift 报 invalid redeclaration）。
  3. Widget target 误 import SwiftData —— 小组件扩展进程里创建
     ModelContainer 会崩，而且它是本架构明令禁止的（见 docs/architecture.md）。
  4. 花括号不配平。
  5. 两个 target 缺 @main 入口文件。

刻意不做的：类型检查、泛型推断、协议一致性。做不了，也不假装能做。
另一个关键取舍：**不检查框架符号**。`Foundation`/`TimeInterval`/`SecItemAdd`
这类名字没法跟 App 自定义类型可靠区分，硬查只会淹没在误报里。只查「项目
内部定义过的类型」，误报率接近零。

用法：
    python scripts/check_swift_consistency.py
    python scripts/check_swift_consistency.py --verbose
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SHARED_DIR = "Shared"
APP_DIR = "PdfReview"
WIDGET_DIR = "PdfReviewWidget"
SHARED_CORE_PREFIX = "Shared/Core/"

# 类型声明。分两层捕获缩进，用来区分顶层类型与嵌套类型 ——
# 嵌套类型（AppSettings.Keys 和 KeychainStore.Keys）同名不算错误。
TYPE_DECL_RE = re.compile(
    r"^([ \t]*)"
    r"(?:(?:@\w+(?:\([^)]*\))?|public|private|fileprivate|internal|open|final"
    r"|indirect|nonisolated)\s+)*"
    r"(struct|class|enum|protocol|actor|typealias)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)

EXTENSION_RE = re.compile(
    r"^\s*(?:(?:public|private|fileprivate|internal)\s+)?"
    r"extension\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)

IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)

# 类型使用：大写开头，后面跟这些字符之一。排除前面带点的（成员访问）。
TYPE_USE_RE = re.compile(
    r"(?<![A-Za-z0-9_.])([A-Z][A-Za-z0-9_]{2,})(?=[\s(.<>,)\]:?=!]|\Z)"
)

COMMENT_OR_STRING_RE = re.compile(
    r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"",
    re.DOTALL,
)

# @Attribute、@Relationship 这类属性包装器 + #Preview 这类宏。
ATTRIBUTE_RE = re.compile(r"(?:@|#)[A-Z][A-Za-z0-9_]*")

KEYWORDS = {
    "Self", "Any", "AnyObject", "Never", "Void", "True", "False", "Nil",
}

# 框架里的类型名。收得比较全，因为这一节只用来做「可疑名字」提示：
# 出现在这里就静音，漏收只会多一条提示，不会漏掉真问题。
FRAMEWORK_TYPES = set("""
String Int Double Float Bool Date Data UUID URL Error Codable Encodable
Decodable Equatable Hashable Identifiable Comparable LocalizedError
CaseIterable Sendable AnyObject Void Never Optional Array Dictionary Set
ClosedRange Range Result Character Substring Calendar Locale TimeZone
DateFormatter ISO8601DateFormatter JSONDecoder JSONEncoder JSONSerialization
Decoder Encoder CodingKey DecodingError EncodingError Timer NotificationCenter
Bundle ProcessInfo FileManager URLSession URLRequest HTTPURLResponse URLResponse
URLError Notification IndexSet DispatchQueue Task MainActor CancellationError
ContinuousClock Duration Hasher AnyHashable NSNumber NSString NSObject
NSTemporaryDirectory NSUUID NSLock NSCache NSAttributedString NSRange
Attribute Relationship Model ModelContainer ModelContext ModelConfiguration
Query FetchDescriptor SortDescriptor Predicate ModelActor PersistentModel Schema
View Text Image Button VStack HStack ZStack Spacer ScrollView List ForEach
NavigationStack NavigationLink NavigationSplitView Section Form Toggle TextField
SecureField Slider Stepper Picker Label ProgressView Divider Group
GeometryReader Color Font LinearGradient RoundedRectangle Capsule Circle Rectangle
Material Shape ViewBuilder Binding State StateObject ObservedObject Environment EnvironmentObject
ObservableObject Published Observable Animation Transition Namespace ToolbarItem
ToolbarItemGroup Menu Link ShareLink ContentUnavailableView DisclosureGroup
LazyVStack LazyHStack Grid GridRow ViewThatFits AnyView TupleView ModifiedContent
EmptyView Disabled AnimationCurve EdgeInsets Alignment HorizontalAlignment
VerticalAlignment Axis LayoutDirection WidgetFamily EmptyVisualEffect VisualEffect
Widget WidgetBundle WidgetConfiguration StaticConfiguration TimelineProvider
TimelineEntry Timeline TimelineReloadPolicy WidgetCenter AppIntent AppIntents
LocalizedStringResource IntentResult ProvidesDialog Parameter IntentParameter
SecItem OSStatus CFTypeRef SecAccessControl Security SecCopyErrorMessageString
SecItemAdd SecItemCopyMatching SecItemDelete SecItemUpdate CFDictionary
CFString kSecClass kSecAttrService kSecAttrAccount kSecValueData kSecReturnData
kSecMatchLimit kSecAttrAccessible kSecMatchLimitOne kSecClassGenericPassword
UIColor UIFont UIImage UIApplication UIScreen UIDevice UIWindowScene
UIActivityViewController UIKit SwiftUI Foundation Combine PDFKit SwiftData
WidgetKit AppIntents UniformTypeIdentifiers CharacterSet UTType
AccessoryWidgetBackground Preview Context Animation Spring
App Scene WindowGroup DocumentGroup Settings ImmersiveSpace MenuBarExtra
TimeInterval UInt UInt8 UInt16 UInt32 UInt64 Int8 Int16 Int32 Int64
Float80 Decimal NumberFormatter StringProtocol Sequence Collection IteratorProtocol
UserDefaults URLSessionConfiguration URLComponents URLQueryItem
PDFDocument PDFPage PDFSelection
CGFloat CGPoint CGSize CGRect CGColor CGImage CGContext
LabeledContent TextEditor TabView TabSection NavigationBarItem
NSError NSUserCancelledError NSUnderlyingErrorKey
UIViewControllerRepresentable UIViewController UIViewRepresentable UIView
UTType UIDocumentPickerViewController UIActivityItemSource
FileDocument ReferenceFileDocument ShareLink Transferable
AnyPublisher PassthroughSubject CurrentValueSubject ObservableObjectPublisher
AnyCancellable
FileHandle InputStream OutputStream FileWrapper UIPasteboard
""".split())


@dataclass
class SwiftFile:
    rel: str
    decls: set[str] = field(default_factory=set)          # 全部类型（含嵌套）
    top_level_decls: set[str] = field(default_factory=set)  # 仅顶层
    extensions: set[str] = field(default_factory=set)
    imports: set[str] = field(default_factory=set)
    uses: set[str] = field(default_factory=set)
    brace_delta: int = 0


def strip_noise(text: str) -> str:
    """去掉注释、字符串、属性、宏，只留代码骨架。"""
    def blank(m: re.Match) -> str:
        s = m.group(0)
        if s.startswith('"'):
            return '""'
        return "\n" * s.count("\n") if "\n" in s else " "

    text = COMMENT_OR_STRING_RE.sub(blank, text)
    text = ATTRIBUTE_RE.sub("", text)
    return text


def rel_posix(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def collect_targets() -> dict[str, list[Path]]:
    """按 generate_pbxproj.py 的同一套规则算出每个 target 编哪些文件。

    两处必须一致，否则脚本检查的和你实际编译的是两套东西。
    """
    shared = sorted((ROOT / SHARED_DIR).rglob("*.swift"))
    app = sorted((ROOT / APP_DIR).rglob("*.swift"))
    widget = sorted((ROOT / WIDGET_DIR).rglob("*.swift"))

    shared_core = [p for p in shared if rel_posix(p).startswith(SHARED_CORE_PREFIX)]
    return {
        "app": sorted(set(shared) | set(app)),
        "widget": sorted(set(shared_core) | set(widget)),
    }


def load_file(path: Path) -> SwiftFile:
    raw = path.read_text(encoding="utf-8")
    clean = strip_noise(raw)

    decls: set[str] = set()
    top_level: set[str] = set()
    for m in TYPE_DECL_RE.finditer(clean):
        indent, _, name = m.group(1), m.group(2), m.group(3)
        decls.add(name)
        if not indent:
            top_level.add(name)

    imports = {m.group(1) for m in IMPORT_RE.finditer(clean)}
    uses = {
        u for u in TYPE_USE_RE.findall(clean)
        if u not in decls and u not in KEYWORDS and u not in imports
    }

    return SwiftFile(
        rel=rel_posix(path),
        decls=decls,
        top_level_decls=top_level,
        extensions={m.group(1) for m in EXTENSION_RE.finditer(clean)},
        imports=imports,
        uses=uses,
        brace_delta=clean.count("{") - clean.count("}"),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="额外打印通过的检查项")
    args = ap.parse_args()

    if not ROOT.is_dir():
        print(f"找不到项目目录：{ROOT}")
        return 2

    targets = collect_targets()
    files: dict[str, SwiftFile] = {}
    for paths in targets.values():
        for p in paths:
            if p.exists():
                files[rel_posix(p)] = load_file(p)

    problems: list[str] = []
    passes: list[str] = []

    # 全项目类型索引：类型名 → 定义它的文件集合
    defined_in: dict[str, set[str]] = defaultdict(set)
    for rel, f in files.items():
        for d in f.decls:
            defined_in[d].add(rel)

    # ---- 1. 顶层类型重复定义 ----
    top_owner: dict[str, set[str]] = defaultdict(set)
    for rel, f in files.items():
        for d in f.top_level_decls:
            top_owner[d].add(rel)
    dup = {k: v for k, v in top_owner.items() if len(v) > 1}
    for name in sorted(dup):
        problems.append(
            f"[重复定义] 顶层类型 {name} 出现在多个文件，Swift 会报 invalid redeclaration："
            + "、".join(sorted(dup[name]))
        )
    if not dup:
        passes.append("无顶层类型重复定义")

    # ---- 2. 类型在某 target 里不可见 ----
    # 这是本脚本的核心检查：类型项目里存在，但这个 target 没编进去。
    for target, paths in targets.items():
        visible: set[str] = set()
        for p in paths:
            f = files.get(rel_posix(p))
            if f:
                visible |= f.decls | f.extensions

        missing: dict[str, set[str]] = defaultdict(set)
        for p in paths:
            f = files.get(rel_posix(p))
            if not f:
                continue
            for u in f.uses:
                if u in visible:
                    continue
                if u in defined_in:      # 项目里定义过，但这个 target 看不到
                    missing[u].add(f.rel)

        for name in sorted(missing):
            owners = sorted(defined_in[name])
            problems.append(
                f"[{target}] 类型 {name} 定义在 {owners}，但没有编进 {target} target，"
                f"编译会报 Cannot find '{name}' in scope（引用方：{sorted(missing[name])}）"
            )
        if not missing:
            passes.append(f"[{target}] 自有类型全部可见")

    # ---- 3. 引用了项目里根本不存在的类型 ----
    # 上一节只抓「定义过但没编进本 target」。这里抓「压根没定义」，
    # 典型是写完调用方忘了写实现（RootView 引用了但 RootView.swift 不存在）。
    # 靠 FRAMEWORK_TYPES 白名单压误报；漏收的框架类型会以「疑似」列出，
    # 由人扫一眼确认，不至于静默放过真正的缺失。
    all_decls: set[str] = set()
    for f in files.values():
        all_decls |= f.decls | f.extensions

    for target, paths in targets.items():
        phantom: dict[str, set[str]] = defaultdict(set)
        for p in paths:
            f = files.get(rel_posix(p))
            if not f:
                continue
            for u in f.uses:
                if u in all_decls or u in FRAMEWORK_TYPES:
                    continue
                phantom[u].add(f.rel)
        for name in sorted(phantom):
            problems.append(
                f"[{target}] 疑似未定义的类型 {name}（引用方：{sorted(phantom[name])}）"
                f"；若它是框架类型，请加进脚本的 FRAMEWORK_TYPES"
            )
        if not phantom:
            passes.append(f"[{target}] 无未定义类型引用")

    # ---- 4. Widget 不许 import SwiftData ----
    # 见 docs/architecture.md：小组件只读 App Group 里的 rotation-cache.json。
    for p in targets["widget"]:
        f = files.get(rel_posix(p))
        if f and "SwiftData" in f.imports:
            problems.append(
                f"[widget] {f.rel} 引入了 SwiftData；"
                f"小组件扩展里不能建 ModelContainer，架构上也禁止"
            )

    # ---- 4. 花括号配平 ----
    unbalanced = {r: f.brace_delta for r, f in files.items() if f.brace_delta != 0}
    for rel in sorted(unbalanced):
        problems.append(
            f"[括号] {rel} 花括号不配平，差值 {unbalanced[rel]:+d}"
            f"（正数表示缺右括号）"
        )
    if not unbalanced:
        passes.append("全部文件花括号配平")

    # ---- 5. 入口文件 ----
    app_rels = [rel_posix(p) for p in targets["app"] if p.exists()]
    widget_rels = [rel_posix(p) for p in targets["widget"] if p.exists()]
    if not any(r.endswith("PdfReviewApp.swift") for r in app_rels):
        problems.append("[app] 找不到 PdfReviewApp.swift（@main 入口）")
    else:
        passes.append("[app] @main 入口就位")
    if not any(r.endswith("PdfReviewWidgetBundle.swift") for r in widget_rels):
        problems.append("[widget] 找不到 PdfReviewWidgetBundle.swift（@main 入口）")
    else:
        passes.append("[widget] @main 入口就位")

    # ---- 输出 ----
    n_app = len(app_rels)
    n_widget = len(widget_rels)
    print("=" * 70)
    print("PdfReview 静态一致性检查")
    print(f"项目目录：{ROOT}")
    print(f"App target    ：{n_app} 个 Swift 文件")
    print(f"Widget target ：{n_widget} 个 Swift 文件")
    print("=" * 70)

    if args.verbose:
        for line in passes:
            print(f"  OK   {line}")
        print()

    if problems:
        print(f"发现 {len(problems)} 个问题：\n")
        for i, line in enumerate(problems, 1):
            print(f"{i:>3}. {line}")
        print()
        print("本脚本是正则近似检查，通过不等于能编译。")
        print("真正的验证必须在 macOS + Xcode 上做。")
        return 1

    print("未发现问题。")
    print()
    print("本脚本是正则近似检查，通过不等于能编译。")
    print("真正的验证必须在 macOS + Xcode 上做。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
