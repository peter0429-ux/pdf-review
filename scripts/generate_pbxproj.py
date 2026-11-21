#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 PdfReview.xcodeproj/project.pbxproj

为什么用脚本而不是手写 pbxproj：
  pbxproj 里每个对象都要 24 位十六进制唯一 ID，且处处互相引用。
  脚本按「路径 → 稳定 ID」的规则生成，增删文件只需重跑，
  并且可以顺带做结构自检。

用法（在项目根目录）：
    python scripts/generate_pbxproj.py            # 生成
    python scripts/generate_pbxproj.py --check    # 只做一致性自检，不写盘

生成后请用 Xcode 打开确认；本机是 Windows，无法真正编译验证。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

# ---------------------------------------------------------------------------
# 基本参数
# ---------------------------------------------------------------------------

PROJECT_NAME = "PdfReview"
APP_TARGET = "PdfReview"
WIDGET_TARGET = "PdfReviewWidget"

APP_BUNDLE_ID = "com.pdfreview.app"
WIDGET_BUNDLE_ID = "com.pdfreview.app.widget"
APP_GROUP = "group.com.pdfreview.app"

DEPLOYMENT_TARGET = "17.0"
SWIFT_VERSION = "5.0"
MARKETING_VERSION = "1.0"
CURRENT_PROJECT_VERSION = "1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PBXPROJ_PATH = os.path.join(ROOT, PROJECT_NAME + ".xcodeproj", "project.pbxproj")

# 各 target 参与编译的源码目录。
#
# Shared/Core 下的三个文件（AppGroup / RotationCache / RotationScheduler）只依赖
# Foundation，App 与 Widget 都要用，因此**同时编进两个 target**。
#
# Shared/ 其余部分（Models / Store / Service）依赖 SwiftData、PDFKit、WidgetKit 等
# App 端专有框架，**只能编进 App target**——否则 Widget target 会因
# `import SwiftData` 直接编译失败。
SHARED_SOURCES = ["Shared"]
SHARED_CORE_PREFIX = "Shared/Core/"

APP_SOURCES = [APP_TARGET]
WIDGET_SOURCES = [WIDGET_TARGET]

APP_RESOURCES = [
    "PdfReview/Resources/Assets.xcassets",
    # 内置种子分析文件：首次启动时导入成一幅牌组，
    # 让「装完就有内容可复习」而不是面对一个空列表。
    "PdfReview/Resources/seed-analysis.pdfreview.json",
]
WIDGET_RESOURCES = [
    "PdfReviewWidget/Resources/Assets.xcassets",
    # 内置种子轮换缓存：侧载签名拿不到 App Groups 时，小组件读不到 App 写
    # 的数据，靠这份随包资源才不至于一直显示空态。
    "PdfReviewWidget/Resources/rotation-cache.json",
]

APP_INFO_PLIST = "PdfReview/Resources/Info.plist"
APP_ENTITLEMENTS = "PdfReview/Resources/PdfReview.entitlements"
WIDGET_INFO_PLIST = "PdfReviewWidget/Resources/Info.plist"
WIDGET_ENTITLEMENTS = "PdfReviewWidget/Resources/PdfReviewWidget.entitlements"


# ---------------------------------------------------------------------------
# 稳定 ID
# ---------------------------------------------------------------------------

_used_ids: dict[str, str] = {}


def oid(key: str) -> str:
    """由字符串键派生 24 位十六进制 ID，保证多次运行结果一致。"""
    digest = hashlib.md5(key.encode("utf-8")).hexdigest().upper()[:24]
    previous = _used_ids.get(digest)
    if previous is not None and previous != key:
        # 极小概率的哈希碰撞：加盐重算
        digest = hashlib.md5((key + "#salt").encode("utf-8")).hexdigest().upper()[:24]
    _used_ids[digest] = key
    return digest


# ---------------------------------------------------------------------------
# 收集文件
# ---------------------------------------------------------------------------

def collect_files(rel_dir: str, suffixes: tuple[str, ...]) -> list[str]:
    """递归收集目录下指定后缀的文件，返回项目根相对路径（用 / 分隔）。"""
    result: list[str] = []
    absolute = os.path.join(ROOT, rel_dir)
    if not os.path.isdir(absolute):
        return result
    for base, dirs, files in os.walk(absolute):
        dirs[:] = sorted(d for d in dirs if d != "__MACOSX")
        for name in sorted(files):
            if not name.lower().endswith(suffixes):
                continue
            full = os.path.join(base, name)
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            result.append(rel)
    return result


def collect_grouped(prefix: str, suffixes: tuple[str, ...]) -> list[str]:
    """把多个根目录下的文件合并去重。"""
    seen: set[str] = set()
    merged: list[str] = []
    for directory in prefix:
        for path in collect_files(directory, suffixes):
            if path not in seen:
                seen.add(path)
                merged.append(path)
    return merged


# ---------------------------------------------------------------------------
# 文件类型
# ---------------------------------------------------------------------------

FILE_TYPES = {
    ".swift": "sourcecode.swift",
    ".plist": "text.plist.xml",
    ".entitlements": "text.plist.entitlements",
    ".json": "text.json",
    ".md": "net.daringfireball.markdown",
    ".xcassets": "folder.assetcatalog",
}


def file_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return FILE_TYPES.get(ext, "text")


def last_resort(path: str) -> str:
    return "lastKnownFileType"


# ---------------------------------------------------------------------------
# 生成各段
# ---------------------------------------------------------------------------

class Builder:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, text: str = "") -> None:
        self.lines.append(text)

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def build_pbxproj() -> str:
    shared_swift = collect_grouped(SHARED_SOURCES, (".swift",))
    app_swift = collect_grouped(APP_SOURCES, (".swift",))
    widget_swift = collect_grouped(WIDGET_SOURCES, (".swift",))

    # Shared 里只有 Core 子目录可以进 Widget；其余（Models/Store/Service）依赖 App 端框架。
    shared_core = [p for p in shared_swift if p.startswith(SHARED_CORE_PREFIX)]
    shared_app_only = [p for p in shared_swift if not p.startswith(SHARED_CORE_PREFIX)]

    app_sources = sorted(set(shared_swift) | set(app_swift))
    widget_sources = sorted(set(shared_core) | set(widget_swift))

    # 移除 Widget 目录误收进 App 的情况
    app_sources = [p for p in app_sources if not p.startswith(WIDGET_TARGET + "/")]
    widget_sources = [p for p in widget_sources if not p.startswith(APP_TARGET + "/")]

    # 防呆：Widget target 绝不能出现 import SwiftData / PDFKit 的文件
    if shared_app_only:
        leaked = [p for p in widget_sources if p.startswith("Shared/")]
        assert all(p in shared_core for p in leaked), (
            "Widget target 混入了 App 专用的 Shared 文件：" + repr(leaked)
        )

    app_resources = sorted(set(p for p in APP_RESOURCES if os.path.exists(os.path.join(ROOT, p))))
    widget_resources = sorted(
        set(p for p in WIDGET_RESOURCES if os.path.exists(os.path.join(ROOT, p)))
    )

    # ---- 校验必需文件
    missing = []
    for required in (APP_INFO_PLIST, APP_ENTITLEMENTS, WIDGET_INFO_PLIST, WIDGET_ENTITLEMENTS):
        if not os.path.exists(os.path.join(ROOT, required)):
            missing.append(required)
    if missing:
        print("警告：以下必需文件缺失，生成的工程可能无法构建：", file=sys.stderr)
        for path in missing:
            print("  - " + path, file=sys.stderr)

    if not app_sources:
        print("错误：没有找到任何 Swift 源文件。", file=sys.stderr)
        raise SystemExit(1)

    # ---- 文件引用 ID
    #
    # 除了编译进 target 的源码与资源，文档类文件（docs/ schema/ samples/
    # scripts/）也要进 file_ref，否则它们在 Xcode 导航器里是空组、点不开。
    # 它们不参与构建，只用于浏览。
    browse_only: set[str] = set()
    for dirname, suffixes in (
        ("docs", (".md",)),
        ("schema", (".json",)),
        ("samples", (".json",)),
        ("scripts", (".py", ".sh")),
    ):
        browse_only |= set(collect_files(dirname, suffixes))

    file_ref: dict[str, str] = {}
    for path in sorted(set(app_sources) | set(widget_sources) | set(app_resources)
                       | set(widget_resources) | {APP_INFO_PLIST, APP_ENTITLEMENTS,
                                                  WIDGET_INFO_PLIST, WIDGET_ENTITLEMENTS}
                       | browse_only):
        file_ref[path] = oid("fileref:" + path)

    # ---- 构建文件 ID（同一文件在不同 target 中需要使用不同 PBXBuildFile）
    def build_file_key(path: str, target: str) -> str:
        return oid("buildfile:" + target + ":" + path)

    # ---- target 级对象
    app_target_id = oid("target:" + APP_TARGET)
    widget_target_id = oid("target:" + WIDGET_TARGET)
    project_id = oid("project:" + PROJECT_NAME)

    app_sources_phase = oid("phase:sources:" + APP_TARGET)
    app_frameworks_phase = oid("phase:frameworks:" + APP_TARGET)
    app_resources_phase = oid("phase:resources:" + APP_TARGET)

    widget_sources_phase = oid("phase:sources:" + WIDGET_TARGET)
    widget_frameworks_phase = oid("phase:frameworks:" + WIDGET_TARGET)
    widget_resources_phase = oid("phase:resources:" + WIDGET_TARGET)

    embed_phase = oid("phase:embed:" + APP_TARGET)

    app_product = oid("product:" + APP_TARGET)
    widget_product = oid("product:" + WIDGET_TARGET)

    app_config_list = oid("configlist:" + APP_TARGET)
    widget_config_list = oid("configlist:" + WIDGET_TARGET)
    project_config_list = oid("configlist:project")

    app_debug = oid("config:" + APP_TARGET + ":Debug")
    app_release = oid("config:" + APP_TARGET + ":Release")
    widget_debug = oid("config:" + WIDGET_TARGET + ":Debug")
    widget_release = oid("config:" + WIDGET_TARGET + ":Release")
    project_debug = oid("config:project:Debug")
    project_release = oid("config:project:Release")

    dependency = oid("dependency:" + APP_TARGET + "->" + WIDGET_TARGET)
    container_proxy = oid("proxy:" + APP_TARGET + "->" + WIDGET_TARGET)

    # ---- 分组结构
    #
    # PBXGroup 的 path 决定子项从哪个目录开始解析。少了 path，子项会全部
    # 被解析到工程根，Xcode 就找不到文件（"Build input file cannot be
    # found"），而且它不会说清是哪个组的问题。所以每个目录组都必须带 path，
    # 且 path 是相对「父组」的单个目录名。
    #
    # 例：PdfReview/Resources/Info.plist
    #   mainGroup            无 path          → 解析基准 = 工程根
    #   └ PdfReview   path=PdfReview          → 基准 = <root>/PdfReview
    #     └ Resources path=Resources          → 基准 = <root>/PdfReview/Resources
    #       └ Info.plist path=Info.plist      → <root>/PdfReview/Resources/Info.plist ✓
    main_group = oid("group:main")
    products_group = oid("group:products")

    b = Builder()

    b.add("// !$*UTF8*$!")
    b.add("{")
    b.add("\tarchiveVersion = 1;")
    b.add("\tclasses = {")
    b.add("\t};")
    b.add("\tobjectVersion = 56;")
    b.add("\tobjects = {")
    b.add("")

    # =====================================================================
    # PBXBuildFile
    # =====================================================================
    b.add("/* Begin PBXBuildFile section */")
    for path in app_sources:
        bid = build_file_key(path, APP_TARGET)
        b.add(f"\t\t{bid} /* {os.path.basename(path)} in Sources */ = {{isa = PBXBuildFile; "
              f"fileRef = {file_ref[path]} /* {os.path.basename(path)} */; }};")
    for path in app_resources:
        bid = build_file_key(path, APP_TARGET)
        b.add(f"\t\t{bid} /* {os.path.basename(path)} in Resources */ = {{isa = PBXBuildFile; "
              f"fileRef = {file_ref[path]} /* {os.path.basename(path)} */; }};")
    for path in widget_sources:
        bid = build_file_key(path, WIDGET_TARGET)
        b.add(f"\t\t{bid} /* {os.path.basename(path)} in Sources */ = {{isa = PBXBuildFile; "
              f"fileRef = {file_ref[path]} /* {os.path.basename(path)} */; }};")
    for path in widget_resources:
        bid = build_file_key(path, WIDGET_TARGET)
        b.add(f"\t\t{bid} /* {os.path.basename(path)} in Resources */ = {{isa = PBXBuildFile; "
              f"fileRef = {file_ref[path]} /* {os.path.basename(path)} */; }};")
    # 把 Widget 扩展嵌进 App
    embed_build_file = oid("buildfile:embed:" + WIDGET_TARGET)
    b.add(f"\t\t{embed_build_file} /* {WIDGET_TARGET}.appex in Embed Foundation Extensions */ = "
          f"{{isa = PBXBuildFile; fileRef = {widget_product} /* {WIDGET_TARGET}.appex */; "
          f"settings = {{ATTRIBUTES = (RemoveHeadersOnCopy, ); }}; }};")
    b.add("/* End PBXBuildFile section */")
    b.add("")

    # =====================================================================
    # PBXContainerItemProxy
    # =====================================================================
    b.add("/* Begin PBXContainerItemProxy section */")
    b.add(f"\t\t{container_proxy} /* PBXContainerItemProxy */ = {{")
    b.add("\t\t\tisa = PBXContainerItemProxy;")
    b.add(f"\t\t\tcontainerPortal = {project_id} /* Project object */;")
    b.add("\t\t\tproxyType = 1;")
    b.add(f"\t\t\tremoteGlobalIDString = {widget_target_id};")
    b.add(f"\t\t\tremoteInfo = {WIDGET_TARGET};")
    b.add("\t\t};")
    b.add("/* End PBXContainerItemProxy section */")
    b.add("")

    # =====================================================================
    # PBXCopyFilesBuildPhase（嵌入扩展）
    # =====================================================================
    b.add("/* Begin PBXCopyFilesBuildPhase section */")
    b.add(f"\t\t{embed_phase} /* Embed Foundation Extensions */ = {{")
    b.add("\t\t\tisa = PBXCopyFilesBuildPhase;")
    b.add("\t\t\tbuildActionMask = 2147483647;")
    b.add("\t\t\tdstPath = \"\";")
    b.add("\t\t\tdstSubfolderSpec = 13;")
    b.add("\t\t\tfiles = (")
    b.add(f"\t\t\t\t{embed_build_file} /* {WIDGET_TARGET}.appex in Embed Foundation Extensions */,")
    b.add("\t\t\t);")
    b.add("\t\t\tname = \"Embed Foundation Extensions\";")
    b.add("\t\t\trunOnlyForDeploymentPostprocessing = 0;")
    b.add("\t\t};")
    b.add("/* End PBXCopyFilesBuildPhase section */")
    b.add("")

    # =====================================================================
    # PBXFileReference
    # =====================================================================
    b.add("/* Begin PBXFileReference section */")
    for path in sorted(file_ref):
        fid = file_ref[path]
        name = os.path.basename(path)
        ftype = file_type(path)
        b.add(f"\t\t{fid} /* {name} */ = {{isa = PBXFileReference; "
              f"{last_resort(path)} = {ftype}; path = \"{name}\"; sourceTree = \"<group>\"; }};")
    b.add(f"\t\t{app_product} /* {APP_TARGET}.app */ = {{isa = PBXFileReference; "
          f"explicitFileType = wrapper.application; includeInIndex = 0; "
          f"path = {APP_TARGET}.app; sourceTree = BUILT_PRODUCTS_DIR; }};")
    b.add(f"\t\t{widget_product} /* {WIDGET_TARGET}.appex */ = {{isa = PBXFileReference; "
          f"explicitFileType = \"wrapper.app-extension\"; includeInIndex = 0; "
          f"path = {WIDGET_TARGET}.appex; sourceTree = BUILT_PRODUCTS_DIR; }};")
    b.add("/* End PBXFileReference section */")
    b.add("")

    # =====================================================================
    # PBXFrameworksBuildPhase
    # =====================================================================
    b.add("/* Begin PBXFrameworksBuildPhase section */")
    for target, phase in ((APP_TARGET, app_frameworks_phase), (WIDGET_TARGET, widget_frameworks_phase)):
        b.add(f"\t\t{phase} /* Frameworks */ = {{")
        b.add("\t\t\tisa = PBXFrameworksBuildPhase;")
        b.add("\t\t\tbuildActionMask = 2147483647;")
        b.add("\t\t\tfiles = (")
        b.add("\t\t\t);")
        b.add("\t\t\trunOnlyForDeploymentPostprocessing = 0;")
        b.add("\t\t};")
    b.add("/* End PBXFrameworksBuildPhase section */")
    b.add("")

    # =====================================================================
    # PBXGroup
    #
    # 按磁盘目录真实还原层级，每个目录组都写 path。fileRef 的 path 只写
    # 文件名，靠父组逐级拼接还原绝对位置——这是 Xcode 自己的做法。
    # =====================================================================
    def group_lines(group_id: str, name: str | None, path: str | None,
                    children: list[str], comment: str) -> list[str]:
        out = [f"\t\t{group_id} /* {comment} */ = {{"]
        out.append("\t\t\tisa = PBXGroup;")
        out.append("\t\t\tchildren = (")
        for child in children:
            out.append(f"\t\t\t\t{child},")
        out.append("\t\t\t);")
        if name is not None:
            out.append(f'\t\t\tname = "{name}";')
        if path is not None:
            out.append(f'\t\t\tpath = "{path}";')
        out.append('\t\t\tsourceTree = "<group>";')
        out.append("\t\t};")
        return out

    def build_tree(paths: list[str]) -> tuple[list[str], dict[str, "list[str]"]]:
        """把一组「相对某目录」的路径切成直属文件名与子目录。

        返回 (直属文件名列表, {子目录名: 该子目录内的相对路径列表})。
        这里只切一层，递归交给 emit_tree —— 上一版把递归结果和路径混在
        同一个元组里，导致 emit_tree 拿到的类型和它自己以为的不一致。
        """
        direct: list[str] = []
        buckets: dict[str, list[str]] = {}
        for path in paths:
            if "/" in path:
                head, rest = path.split("/", 1)
                buckets.setdefault(head, []).append(rest)
            else:
                direct.append(path)
        return sorted(direct), buckets

    def emit_tree(base: str, paths: list[str], group_id: str, name: str,
                  display: str) -> None:
        """递归生成一个目录组及其子组。

        base  相对工程根的累积目录（"" 表示工程根）
        paths 相对 base 的路径列表
        """
        direct, children = build_tree(paths)

        child_refs: list[str] = []
        # 子目录先排，文件后排——和 Xcode 自己的习惯一致
        for child_name in sorted(children):
            child_base = f"{base}/{child_name}" if base else child_name
            child_refs.append(
                f'{oid("group:" + child_base)} /* {child_name} */'
            )
        for filename in direct:
            full = f"{base}/{filename}" if base else filename
            if full not in file_ref:
                raise SystemExit(f"内部错误：{full} 没有 fileRef")
            child_refs.append(file_ref[full])

        b.lines.extend(
            group_lines(group_id, name, name if base else None, child_refs, display)
        )
        for child_name in sorted(children):
            child_base = f"{base}/{child_name}" if base else child_name
            emit_tree(child_base, children[child_name],
                      oid("group:" + child_base), child_name, child_name)

    # mainGroup 不带 path：它的子项以工程根为基准。
    b.add("/* Begin PBXGroup section */")
    main_children = [oid("group:Shared"), oid("group:" + APP_TARGET),
                     oid("group:" + WIDGET_TARGET), oid("group:docs"),
                     oid("group:schema"), oid("group:samples"),
                     oid("group:scripts"), products_group]
    b.lines.extend(group_lines(main_group, None, None, main_children, "mainGroup"))

    b.lines.extend(group_lines(products_group, "Products", None,
                               [app_product, widget_product], "Products"))

    # 每个顶层目录单独建树。挂在各自 target 下的路径按 target 归属过滤，
    # 但树的形状完全由磁盘决定，不再凭路径前缀猜两级。
    for dirname in ("Shared", APP_TARGET, WIDGET_TARGET, "docs", "schema",
                    "samples", "scripts"):
        members = sorted(
            p for p in set(file_ref)
            if p.startswith(dirname + "/")
        )
        if not members:
            # 空目录也建组，方便用户在 Xcode 里看到结构调整
            b.lines.extend(group_lines(oid("group:" + dirname), dirname,
                                       dirname, [], dirname))
            continue
        relative = [p[len(dirname) + 1:] for p in members]
        emit_tree(dirname, relative, oid("group:" + dirname), dirname, dirname)

    b.add("/* End PBXGroup section */")
    b.add("")

    # =====================================================================
    # PBXNativeTarget
    # =====================================================================
    b.add("/* Begin PBXNativeTarget section */")

    b.add(f"\t\t{app_target_id} /* {APP_TARGET} */ = {{")
    b.add("\t\t\tisa = PBXNativeTarget;")
    b.add(f"\t\t\tbuildConfigurationList = {app_config_list} /* Build configuration list for "
          f"PBXNativeTarget \"{APP_TARGET}\" */;")
    b.add("\t\t\tbuildPhases = (")
    b.add(f"\t\t\t\t{app_sources_phase} /* Sources */,")
    b.add(f"\t\t\t\t{app_frameworks_phase} /* Frameworks */,")
    b.add(f"\t\t\t\t{app_resources_phase} /* Resources */,")
    b.add(f"\t\t\t\t{embed_phase} /* Embed Foundation Extensions */,")
    b.add("\t\t\t);")
    b.add("\t\t\tbuildRules = (")
    b.add("\t\t\t);")
    b.add("\t\t\tdependencies = (")
    b.add(f"\t\t\t\t{dependency} /* PBXTargetDependency */,")
    b.add("\t\t\t);")
    b.add(f"\t\t\tname = {APP_TARGET};")
    b.add(f"\t\t\tproductName = {APP_TARGET};")
    b.add(f"\t\t\tproductReference = {app_product} /* {APP_TARGET}.app */;")
    b.add("\t\t\tproductType = \"com.apple.product-type.application\";")
    b.add("\t\t};")

    b.add(f"\t\t{widget_target_id} /* {WIDGET_TARGET} */ = {{")
    b.add("\t\t\tisa = PBXNativeTarget;")
    b.add(f"\t\t\tbuildConfigurationList = {widget_config_list} /* Build configuration list for "
          f"PBXNativeTarget \"{WIDGET_TARGET}\" */;")
    b.add("\t\t\tbuildPhases = (")
    b.add(f"\t\t\t\t{widget_sources_phase} /* Sources */,")
    b.add(f"\t\t\t\t{widget_frameworks_phase} /* Frameworks */,")
    b.add(f"\t\t\t\t{widget_resources_phase} /* Resources */,")
    b.add("\t\t\t);")
    b.add("\t\t\tbuildRules = (")
    b.add("\t\t\t);")
    b.add("\t\t\tdependencies = (")
    b.add("\t\t\t);")
    b.add(f"\t\t\tname = {WIDGET_TARGET};")
    b.add(f"\t\t\tproductName = {WIDGET_TARGET};")
    b.add(f"\t\t\tproductReference = {widget_product} /* {WIDGET_TARGET}.appex */;")
    b.add("\t\t\tproductType = \"com.apple.product-type.app-extension\";")
    b.add("\t\t};")

    b.add("/* End PBXNativeTarget section */")
    b.add("")

    # =====================================================================
    # PBXProject
    # =====================================================================
    b.add("/* Begin PBXProject section */")
    b.add(f"\t\t{project_id} /* Project object */ = {{")
    b.add("\t\t\tisa = PBXProject;")
    b.add("\t\t\tattributes = {")
    b.add("\t\t\t\tBuildIndependentTargetsInParallel = 1;")
    b.add("\t\t\t\tLastSwiftUpdateCheck = 1500;")
    b.add("\t\t\t\tLastUpgradeCheck = 1500;")
    b.add("\t\t\t\tTargetAttributes = {")
    b.add(f"\t\t\t\t\t{app_target_id} = {{")
    b.add("\t\t\t\t\t\tCreatedOnToolsVersion = 15.0;")
    b.add("\t\t\t\t\t};")
    b.add(f"\t\t\t\t\t{widget_target_id} = {{")
    b.add("\t\t\t\t\t\tCreatedOnToolsVersion = 15.0;")
    b.add("\t\t\t\t\t};")
    b.add("\t\t\t\t};")
    b.add("\t\t\t};")
    b.add(f"\t\t\tbuildConfigurationList = {project_config_list} /* Build configuration list for "
          f"PBXProject \"{PROJECT_NAME}\" */;")
    b.add("\t\t\tcompatibilityVersion = \"Xcode 15.0\";")
    b.add("\t\t\tdevelopmentRegion = \"zh-Hans\";")
    b.add("\t\t\thasScannedForEncodings = 0;")
    b.add("\t\t\tknownRegions = (")
    b.add("\t\t\t\t\"zh-Hans\",")
    b.add("\t\t\t\ten,")
    b.add("\t\t\t\tBase,")
    b.add("\t\t\t);")
    b.add(f"\t\t\tmainGroup = {main_group};")
    b.add(f"\t\t\tproductRefGroup = {products_group} /* Products */;")
    b.add("\t\t\tprojectDirPath = \"\";")
    b.add("\t\t\tprojectRoot = \"\";")
    b.add("\t\t\ttargets = (")
    b.add(f"\t\t\t\t{app_target_id} /* {APP_TARGET} */,")
    b.add(f"\t\t\t\t{widget_target_id} /* {WIDGET_TARGET} */,")
    b.add("\t\t\t);")
    b.add("\t\t};")
    b.add("/* End PBXProject section */")
    b.add("")

    # =====================================================================
    # PBXResourcesBuildPhase
    # =====================================================================
    b.add("/* Begin PBXResourcesBuildPhase section */")
    for target, phase, resources in ((APP_TARGET, app_resources_phase, app_resources),
                                     (WIDGET_TARGET, widget_resources_phase, widget_resources)):
        b.add(f"\t\t{phase} /* Resources */ = {{")
        b.add("\t\t\tisa = PBXResourcesBuildPhase;")
        b.add("\t\t\tbuildActionMask = 2147483647;")
        b.add("\t\t\tfiles = (")
        for path in resources:
            b.add(f"\t\t\t\t{build_file_key(path, target)} /* {os.path.basename(path)} in Resources */,")
        b.add("\t\t\t);")
        b.add("\t\t\trunOnlyForDeploymentPostprocessing = 0;")
        b.add("\t\t};")
    b.add("/* End PBXResourcesBuildPhase section */")
    b.add("")

    # =====================================================================
    # PBXSourcesBuildPhase
    # =====================================================================
    b.add("/* Begin PBXSourcesBuildPhase section */")
    for target, phase, sources in ((APP_TARGET, app_sources_phase, app_sources),
                                   (WIDGET_TARGET, widget_sources_phase, widget_sources)):
        b.add(f"\t\t{phase} /* Sources */ = {{")
        b.add("\t\t\tisa = PBXSourcesBuildPhase;")
        b.add("\t\t\tbuildActionMask = 2147483647;")
        b.add("\t\t\tfiles = (")
        for path in sources:
            b.add(f"\t\t\t\t{build_file_key(path, target)} /* {os.path.basename(path)} in Sources */,")
        b.add("\t\t\t);")
        b.add("\t\t\trunOnlyForDeploymentPostprocessing = 0;")
        b.add("\t\t};")
    b.add("/* End PBXSourcesBuildPhase section */")
    b.add("")

    # =====================================================================
    # PBXTargetDependency
    # =====================================================================
    b.add("/* Begin PBXTargetDependency section */")
    b.add(f"\t\t{dependency} /* PBXTargetDependency */ = {{")
    b.add("\t\t\tisa = PBXTargetDependency;")
    b.add(f"\t\t\ttarget = {widget_target_id} /* {WIDGET_TARGET} */;")
    b.add(f"\t\t\ttargetProxy = {container_proxy} /* PBXContainerItemProxy */;")
    b.add("\t\t};")
    b.add("/* End PBXTargetDependency section */")
    b.add("")

    # =====================================================================
    # XCBuildConfiguration
    # =====================================================================
    def settings_block(settings: list[tuple[str, str]]) -> list[str]:
        out = ["\t\t\tbuildSettings = {"]
        for key, value in settings:
            out.append(f"\t\t\t\t{key} = {value};")
        out.append("\t\t\t};")
        return out

    common_project = [
        ("ALWAYS_SEARCH_USER_PATHS", "NO"),
        ("CLANG_ANALYZER_NONNULL", "YES"),
        ("CLANG_ENABLE_MODULES", "YES"),
        ("CLANG_ENABLE_OBJC_ARC", "YES"),
        ("CLANG_WARN_BOOL_CONVERSION", "YES"),
        ("CLANG_WARN_DOCUMENTATION_COMMENTS", "YES"),
        ("CLANG_WARN_EMPTY_BODY", "YES"),
        ("CLANG_WARN_ENUM_CONVERSION", "YES"),
        ("CLANG_WARN_INFINITE_RECURSION", "YES"),
        ("CLANG_WARN_INT_CONVERSION", "YES"),
        ("CLANG_WARN_UNREACHABLE_CODE", "YES"),
        ("COPY_PHASE_STRIP", "NO"),
        ("ENABLE_STRICT_OBJC_MSGSEND", "YES"),
        ("ENABLE_USER_SCRIPT_SANDBOXING", "NO"),
        ("GCC_C_LANGUAGE_STANDARD", "gnu17"),
        ("GCC_NO_COMMON_BLOCKS", "YES"),
        ("GCC_WARN_UNDECLARED_SELECTOR", "YES"),
        ("GCC_WARN_UNINITIALIZED_AUTOS", "YES_AGGRESSIVE"),
        ("GCC_WARN_UNUSED_FUNCTION", "YES"),
        ("GCC_WARN_UNUSED_VARIABLE", "YES"),
        ("IPHONEOS_DEPLOYMENT_TARGET", DEPLOYMENT_TARGET),
        ("MTL_FAST_MATH", "YES"),
        ("SDKROOT", "iphoneos"),
        ("SWIFT_VERSION", SWIFT_VERSION),
    ]

    project_debug_settings = common_project + [
        ("DEBUG_INFORMATION_FORMAT", "dwarf"),
        ("ENABLE_TESTABILITY", "YES"),
        ("GCC_DYNAMIC_NO_PIC", "NO"),
        ("GCC_OPTIMIZATION_LEVEL", "0"),
        ("GCC_PREPROCESSOR_DEFINITIONS", '(\n\t\t\t\t\t"DEBUG=1",\n\t\t\t\t\t"$(inherited)",\n\t\t\t\t)'),
        ("MTL_ENABLE_DEBUG_INFO", "INCLUDE_SOURCE"),
        ("ONLY_ACTIVE_ARCH", "YES"),
        ("SWIFT_ACTIVE_COMPILATION_CONDITIONS", "DEBUG"),
        ("SWIFT_OPTIMIZATION_LEVEL", '"-Onone"'),
    ]

    project_release_settings = common_project + [
        ("DEBUG_INFORMATION_FORMAT", '"dwarf-with-dsym"'),
        ("ENABLE_NS_ASSERTIONS", "NO"),
        ("MTL_ENABLE_DEBUG_INFO", "NO"),
        ("SWIFT_COMPILATION_MODE", "wholemodule"),
        ("SWIFT_OPTIMIZATION_LEVEL", '"-O"'),
        ("VALIDATE_PRODUCT", "YES"),
    ]

    def target_settings(bundle_id: str, info_plist: str, entitlements: str,
                        product_name: str, is_extension: bool) -> list[tuple[str, str]]:
        settings = [
            ("ASSETCATALOG_COMPILER_APPICON_NAME", "AppIcon" if not is_extension else '""'),
            ("ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME", "AccentColor"),
            ("CODE_SIGN_ENTITLEMENTS", f'"{entitlements}"'),
            ("CODE_SIGN_STYLE", "Automatic"),
            ("CURRENT_PROJECT_VERSION", CURRENT_PROJECT_VERSION),
            ("ENABLE_PREVIEWS", "YES"),
            ("GENERATE_INFOPLIST_FILE", "NO"),
            ("INFOPLIST_FILE", f'"{info_plist}"'),
            ("IPHONEOS_DEPLOYMENT_TARGET", DEPLOYMENT_TARGET),
            ("MARKETING_VERSION", MARKETING_VERSION),
            ("PRODUCT_BUNDLE_IDENTIFIER", bundle_id),
            ("PRODUCT_NAME", '"$(TARGET_NAME)"'),
            ("SWIFT_EMIT_LOC_STRINGS", "YES"),
            ("SWIFT_VERSION", SWIFT_VERSION),
            ("TARGETED_DEVICE_FAMILY", '"1,2"'),
        ]
        if is_extension:
            settings += [
                ("LD_RUNPATH_SEARCH_PATHS", '(\n\t\t\t\t\t"$(inherited)",\n\t\t\t\t\t"@executable_path/Frameworks",\n\t\t\t\t\t"@executable_path/../../Frameworks",\n\t\t\t\t)'),
                ("SKIP_INSTALL", "YES"),
            ]
        else:
            settings += [
                ("LD_RUNPATH_SEARCH_PATHS", '(\n\t\t\t\t\t"$(inherited)",\n\t\t\t\t\t"@executable_path/Frameworks",\n\t\t\t\t)'),
            ]
        return settings

    b.add("/* Begin XCBuildConfiguration section */")

    b.add(f"\t\t{project_debug} /* Debug */ = {{")
    b.add("\t\t\tisa = XCBuildConfiguration;")
    b.lines.extend(settings_block(project_debug_settings))
    b.add("\t\t\tname = Debug;")
    b.add("\t\t};")

    b.add(f"\t\t{project_release} /* Release */ = {{")
    b.add("\t\t\tisa = XCBuildConfiguration;")
    b.lines.extend(settings_block(project_release_settings))
    b.add("\t\t\tname = Release;")
    b.add("\t\t};")

    b.add(f"\t\t{app_debug} /* Debug */ = {{")
    b.add("\t\t\tisa = XCBuildConfiguration;")
    b.lines.extend(settings_block(target_settings(
        APP_BUNDLE_ID, APP_INFO_PLIST, APP_ENTITLEMENTS, APP_TARGET, False)))
    b.add("\t\t\tname = Debug;")
    b.add("\t\t};")

    b.add(f"\t\t{app_release} /* Release */ = {{")
    b.add("\t\t\tisa = XCBuildConfiguration;")
    b.lines.extend(settings_block(target_settings(
        APP_BUNDLE_ID, APP_INFO_PLIST, APP_ENTITLEMENTS, APP_TARGET, False)))
    b.add("\t\t\tname = Release;")
    b.add("\t\t};")

    b.add(f"\t\t{widget_debug} /* Debug */ = {{")
    b.add("\t\t\tisa = XCBuildConfiguration;")
    b.lines.extend(settings_block(target_settings(
        WIDGET_BUNDLE_ID, WIDGET_INFO_PLIST, WIDGET_ENTITLEMENTS, WIDGET_TARGET, True)))
    b.add("\t\t\tname = Debug;")
    b.add("\t\t};")

    b.add(f"\t\t{widget_release} /* Release */ = {{")
    b.add("\t\t\tisa = XCBuildConfiguration;")
    b.lines.extend(settings_block(target_settings(
        WIDGET_BUNDLE_ID, WIDGET_INFO_PLIST, WIDGET_ENTITLEMENTS, WIDGET_TARGET, True)))
    b.add("\t\t\tname = Release;")
    b.add("\t\t};")

    b.add("/* End XCBuildConfiguration section */")
    b.add("")

    # =====================================================================
    # XCConfigurationList
    # =====================================================================
    b.add("/* Begin XCConfigurationList section */")
    for list_id, label, debug_id, release_id in (
        (project_config_list, f"PBXProject \"{PROJECT_NAME}\"", project_debug, project_release),
        (app_config_list, f'PBXNativeTarget "{APP_TARGET}"', app_debug, app_release),
        (widget_config_list, f'PBXNativeTarget "{WIDGET_TARGET}"', widget_debug, widget_release),
    ):
        b.add(f"\t\t{list_id} /* Build configuration list for {label} */ = {{")
        b.add("\t\t\tisa = XCConfigurationList;")
        b.add("\t\t\tbuildConfigurations = (")
        b.add(f"\t\t\t\t{debug_id} /* Debug */,")
        b.add(f"\t\t\t\t{release_id} /* Release */,")
        b.add("\t\t\t);")
        b.add("\t\t\tdefaultConfigurationIsVisible = 0;")
        b.add("\t\t\tdefaultConfigurationName = Release;")
        b.add("\t\t};")
    b.add("/* End XCConfigurationList section */")

    b.add("\t};")
    b.add(f"\trootObject = {project_id} /* Project object */;")
    b.add("}")

    return b.text()


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def check(text: str) -> list[str]:
    """结构性自检：括号配平、ID 定义与引用是否闭合。"""
    problems: list[str] = []

    if text.count("{") != text.count("}"):
        problems.append(f"花括号不配平：{{={text.count('{')} }}={text.count('}')}")
    if text.count("(") != text.count(")"):
        problems.append(f"圆括号不配平")

    # 收集定义：行首形如 \t\tID /* ... */ = {
    defined: set[str] = set()
    import re
    for match in re.finditer(r"^\t\t([0-9A-F]{24})\b.*= \{", text, re.MULTILINE):
        defined.add(match.group(1))

    # 收集所有 24 位 ID 引用
    referenced: set[str] = set()
    for match in re.finditer(r"\b([0-9A-F]{24})\b", text):
        referenced.add(match.group(1))

    undefined = referenced - defined
    if undefined:
        problems.append(f"引用了未定义的对象 ID：{sorted(undefined)[:5]}")

    unused = defined - referenced
    # 定义对象本身会被引用一次（作为 Key 出现在 Id 位置），这里只统计完全未被引用的
    if unused:
        problems.append(f"定义了但从未被引用：{sorted(unused)[:5]}")

    # 必需段
    for section in ("PBXBuildFile", "PBXFileReference", "PBXGroup", "PBXNativeTarget",
                    "PBXProject", "PBXSourcesBuildPhase", "XCBuildConfiguration",
                    "XCConfigurationList", "PBXTargetDependency", "PBXContainerItemProxy",
                    "PBXCopyFilesBuildPhase", "PBXResourcesBuildPhase",
                    "PBXFrameworksBuildPhase"):
        if f"/* Begin {section} section */" not in text:
            problems.append(f"缺少段：{section}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 PdfReview.xcodeproj/project.pbxproj")
    parser.add_argument("--check", action="store_true", help="只做自检，不写盘")
    parser.add_argument("--out", default=PBXPROJ_PATH, help="输出路径")
    args = parser.parse_args()

    text = build_pbxproj()
    problems = check(text)

    if args.check:
        if problems:
            print("自检未通过：")
            for problem in problems:
                print("  - " + problem)
            return 1
        print("自检通过：括号配平、对象 ID 全部闭合、必需段齐全。")
        return 0

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)

    print(f"已写入 {args.out}")
    print(f"  字节数：{len(text.encode('utf-8'))}")
    problems = check(text)
    if problems:
        print("结构自检发现问题：")
        for problem in problems:
            print("  - " + problem)
        return 1
    print("结构自检通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
