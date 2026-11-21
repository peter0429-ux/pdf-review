//
//  ProbeView.swift
//  PdfReview
//
//  分步诊断界面。只在 -DPROBE_MINIMAL 编译时才存在（整个文件被 #if 包住）。
//
//  为什么需要它：
//  最小诊断版（只有一个 Text）在真机上能正常打开，说明签名和安装没问题，
//  问题在 App 自己的初始化代码里。但真机上崩溃一闪而过，看不出死在哪一步，
//  而每改一次代码要重新走一遍 CI + Sideloadly，成本太高。
//
//  所以把 7 个可疑动作串成一条链，每步之间停 1.5 秒，并且**在执行前**先把
//  「正在执行第 N 步」显示到界面上。一旦进程在这一步被终止，屏幕上留下的
//  最后一句话就精确指出了崩溃位置。
//

#if PROBE_MINIMAL

import SwiftUI
import SwiftData

/// 按顺序执行 7 个可疑动作，把进度实时反映到界面上。
@MainActor
final class ProbeRunner: ObservableObject {

    static let totalSteps = 7

    /// 当前正在做（或刚做完）的那一步。崩溃时这就是屏幕上最后一句话。
    @Published private(set) var headline: String = "准备开始"

    /// 已经顺利完成的步骤明细。
    @Published private(set) var lines: [String] = []

    /// 7 步全部走完才置真，此时界面切到真正的 RootView。
    @Published private(set) var finished = false

    @Published private(set) var store: CardStore?
    @Published private(set) var settings: AppSettings?

    private var isRunning = false

    func start() {
        guard !isRunning else { return }
        isRunning = true
        Task { await runAll() }
    }

    // MARK: - 主流程

    private func runAll() async {
        // 第 1 步：写日志。这一步失败说明连 Documents 都拿不到。
        await begin(1, "写启动日志")
        LaunchLog.note("=== 分步诊断启动 ===")
        LaunchLog.note("版本 \(Bundle.main.shortVersion)（build \(Bundle.main.buildNumber)）")
        await succeed("日志已写入 Documents/launch.log")

        // 第 2 步：读 UserDefaults.standard 里的停用标记。
        // 注意这一步**不碰** App Group，只读 standard。
        await begin(2, "读取 AppGroup 停用状态")
        let disabled = AppGroup.isDisabled
        await succeed("isDisabled = \(disabled)")

        // 第 3 步：真去取共享容器路径。侧载时这里是高风险点。
        await begin(3, "获取 App Group 共享容器路径")
        let containerAvailable = AppGroup.isContainerAvailable
        await succeed("isContainerAvailable = \(containerAvailable)")

        // 第 4 步：跨进程 UserDefaults。CFPrefs 那层是 C 代码，
        //         名字不在 entitlements 里时会直接杀进程，Swift 兜不住。
        await begin(4, "访问共享 UserDefaults 并写读校验")
        let defaultsProbe = AppGroup.defaults
        defaultsProbe.set("probe-ok", forKey: "probe.roundtrip")
        let readBack = defaultsProbe.string(forKey: "probe.roundtrip") ?? "(读不回)"
        await succeed("读写结果 = \(readBack)")

        // 第 5 步：SwiftData 容器。这是最可疑的一步。
        await begin(5, "创建 SwiftData 数据容器")
        let created = CardStore.shared
        await succeed("容器已建立，牌组数 = \(created.allDecks().count)")

        // 第 6 步：设置对象。它构造时会读一堆 UserDefaults。
        await begin(6, "创建 AppSettings")
        let createdSettings = AppSettings.shared
        await succeed("轮换间隔 = \(createdSettings.rotationIntervalHours) 小时")

        // 第 7 步：交给真正的界面。这一层再崩就是某个 View 的问题。
        await begin(7, "渲染完整界面")
        store = created
        settings = createdSettings
        await succeed("即将切到完整界面")
        try? await Task.sleep(nanoseconds: 800_000_000)
        headline = "全部 7 步通过，正在打开完整界面"
        finished = true
    }

    // MARK: - 进度辅助

    /// 先把「正在执行第 N 步」显示出来，再去执行。顺序不能反：
    /// 反过来的话，崩在这一步时界面还停在上一步的完成状态，会指错位置。
    private func begin(_ n: Int, _ title: String) async {
        headline = "正在执行第 \(n)/\(Self.totalSteps) 步：\(title)"
        // 给 SwiftUI 一帧时间把这个标题画到屏幕上。
        try? await Task.sleep(nanoseconds: 1_200_000_000)
    }

    private func succeed(_ detail: String) async {
        lines.append("✓  \(detail)")
        try? await Task.sleep(nanoseconds: 300_000_000)
    }
}

/// 诊断界面本体。
struct ProbeRootView: View {

    @StateObject private var runner = ProbeRunner()

    var body: some View {
        Group {
            if runner.finished, let store = runner.store, let settings = runner.settings {
                RootView()
                    .environmentObject(store)
                    .environmentObject(settings)
                    .modelContainer(store.container)
            } else {
                progressScreen
            }
        }
        .onAppear { runner.start() }
    }

    private var progressScreen: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("分步诊断")
                    .font(.title2.bold())

                Text(runner.headline)
                    .font(.headline)
                    .foregroundStyle(.tint)
                    .fixedSize(horizontal: false, vertical: true)

                Text("如果 App 在这里退出，请记住上面这句话里的步骤号。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                Divider()

                ForEach(Array(runner.lines.enumerated()), id: \.offset) { _, line in
                    Text(line)
                        .font(.callout)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
    }
}

#endif
