import AppKit
import SwiftUI
import Foundation
import Combine
import Security

// Disambiguate the property wrapper from the newer SDK State macro.
typealias ViewState<Value> = SwiftUI.State<Value>

enum UIStrings {
    static let english: [String: String] = [
        "通用": "General", "模型与密钥": "Models & keys", "文献来源": "Sources", "分类与期刊": "Categories & journals",
        "摘要生成": "Summaries", "摘要服务": "Provider", "API 密钥": "API key",
        "已保存到钥匙串": "Saved in Keychain", "未配置密钥": "No API key configured",
        "留空保留现有密钥": "Leave blank to keep the current key",
        "密钥保存失败，请解锁钥匙串后重试。": "Could not save the key. Unlock Keychain and try again.",
        "全部已读": "Read all",
        "问题": "Problem", "方法": "Methods", "结果": "Results",
        "更新完成": "Update complete",
        "正在更新文献…": "Updating papers…",
        "全部标为已读": "Mark all as read",
        "将当前列表中的未读论文标为已读": "Mark unread papers in this list as read",
        "取消收藏会将 Zotero 文献移入回收站": "Unfavorite moves the Zotero item to Trash",
        "收藏并开始精读": "Favorite and start reading",
        "设置": "Settings",
        "收藏精读": "Favorite reading",
        "模型": "Model",
        "推理强度": "Reasoning effort",
        "每日文献": "Daily papers",
        "每日精选": "Daily selection",
        "篇": "papers",
        "至少选择一个来源": "Select at least one source",
        "arXiv 分类": "arXiv categories",
        "bioRxiv 分类": "bioRxiv categories",
        "期刊": "Journals",
        "选择期刊": "Select journals",
        "至少选择一本期刊": "Select at least one journal",
        "官方分类说明": "Official categories",
        "来源与篇数在下次更新时生效。": "Sources and paper count take effect on the next update.",
        "关闭": "Close",
        "保存": "Save",
        "语言": "Language",
        "未读": "Unread",
        "全部": "All",
        "收藏": "Favorites",
        "已读": "Read",
        "今日值得读": "Worth reading today",
        "更新中": "Updating",
        "更新": "Update",
        "搜索标题、摘要或作者": "Search titles, abstracts, or authors",
        "正在载入文献": "Loading papers",
        "这里暂时没有文献": "No papers here yet",
        "文献和摘要载入后会显示在这里。": "Papers and summaries will appear here.",
        "收藏和已读记录会保存在本机。": "Favorites and read status are saved locally.",
        "已选中": "Selected",
        "尚未更新": "Not updated yet",
        "最近更新": "Last updated",
        "已排队": "Queued",
        "正在提交": "Submitting",
        "正在精读": "Reading",
        "精读待补全": "Reading incomplete",
        "精读未完成": "Reading failed",
        "需要查看任务": "Task needs attention",
        "精读任务": "Reading task",
        "打开 Codex": "Open Codex",
        "无分数": "No score",
        "作者信息待补齐": "Authors unavailable",
        "日期未获取": "Date unavailable",
        "摘要尚未生成。": "Summary not generated yet.",
        "标题": "Title",
        "原文链接": "Paper link",
        "打开原文链接": "Open paper link",
        "相关性": "Relevance",
        "相关性不可用": "Relevance unavailable",
        "作者": "Authors",
        "主要单位": "Affiliations",
        "未获取": "Unavailable",
        "摘要": "Summary",
        "代码与相关资源": "Code and resources",
        "打开相关资源": "Open resource",
        "已收藏": "Favorited",
        "设为未读": "Mark unread",
        "标记已读": "Mark read",
        "打开原文": "Open paper",
        "打开论文原始页面": "Open the original paper page",
        "未读文献已全部读完": "All unread papers are finished",
        "选择一篇论文开始阅读": "Select a paper to start reading",
        "打开文献收件箱": "Open Paper Inbox",
        "退出 Paper Inbox": "Quit Paper Inbox",
        "设置…": "Settings…",
        "编辑": "Edit",
        "拷贝": "Copy",
        "粘贴": "Paste",
        "全选": "Select All",
        "立即更新": "Update now",
        "每日篇数需为 1–50，并至少选择一个来源。": "Choose 1–50 papers and at least one source.",
        "已保存": "Saved",
        "来源与篇数已保存": "Sources and paper count saved",
        "保存未完成。": "Save incomplete. ",
        "本地服务暂不可用：": "Local service unavailable. ",
        "未找到本地服务，请使用启动脚本打开应用。": "Local service missing. Open the app using its launcher.",
        "无法启动本地服务：": "Could not start the local service. ",
        "更新未完成": "Update incomplete"
    ]
    static func text(_ value: String, language: String) -> String {
        language == "en" ? english[value] ?? value : value
    }
}

struct Paper: Identifiable, Decodable {
    let id: String
    let title: String
    let url: String
    let source: String
    let journal: String
    let score: Double?
    let summary: String
    let summary_zh: String
    let summary_en: String
    let abstract: String
    let authors: [String]
    let affiliations: [String]
    let author_affiliations: [String: [Int]]
    let published: String
    let read: Bool
    let favorite: Bool
    let reading: ReadingTask?
    enum CodingKeys: String, CodingKey { case id, title, url, source, journal, score, summary, summary_zh, summary_en, abstract, authors, affiliations, published, read, favorite, reading, author_affiliations }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func string(_ key: CodingKeys) -> String { (try? c.decode(String.self, forKey: key)) ?? "" }
        func array(_ key: CodingKeys) -> [String] {
            if let items = try? c.decode([String].self, forKey: key) { return items }
            let text = string(key); return text.isEmpty ? [] : [text]
        }
        id = string(.id); title = string(.title); url = string(.url); source = string(.source); journal = string(.journal)
        abstract = string(.abstract); summary = string(.summary); summary_zh = string(.summary_zh); summary_en = string(.summary_en); authors = array(.authors); affiliations = array(.affiliations)
        author_affiliations = (try? c.decode([String: [Int]].self, forKey: .author_affiliations)) ?? [:]
        published = string(.published); score = try? c.decode(Double.self, forKey: .score)
        read = (try? c.decode(Bool.self, forKey: .read)) ?? false
        favorite = (try? c.decode(Bool.self, forKey: .favorite)) ?? false
        reading = try? c.decode(ReadingTask.self, forKey: .reading)
    }
}
extension Paper {
    var displaySource: String { journal.isEmpty ? source : journal }
    var displayTitle: String {
        title.replacingOccurrences(of: "{triangleup}{triangleup}", with: "ΔΔ")
            .replacingOccurrences(of: "&amp;", with: "&")
            .replacingOccurrences(of: "&lt;", with: "<")
            .replacingOccurrences(of: "&gt;", with: ">")
            .replacingOccurrences(of: "&quot;", with: "\"")
            .replacingOccurrences(of: "&#39;", with: "'")
    }
    private func superscript(_ value: Int) -> String {
        let digits: [Character: Character] = ["0":"⁰", "1":"¹", "2":"²", "3":"³", "4":"⁴", "5":"⁵", "6":"⁶", "7":"⁷", "8":"⁸", "9":"⁹"]
        return String(String(value).map { digits[$0] ?? $0 })
    }
    var linkedAuthors: String {
        authors.map { name in
            let indices = Array(Set(author_affiliations[name] ?? [])).filter { $0 > 0 && $0 <= affiliations.count }.sorted()
            let parts = name.split(separator: ",", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            let displayName = parts.count == 2 ? parts[1] + " " + parts[0] : name
            return displayName + indices.map { superscript($0) }.joined(separator: "˒")
        }.joined(separator: ", ")
    }
    var numberedAffiliations: String {
        guard author_affiliations.values.contains(where: { !$0.isEmpty }) else { return affiliations.joined(separator: "\n") }
        return affiliations.enumerated().map { "\(superscript($0.offset + 1)) \($0.element)" }.joined(separator: "\n")
    }
    var principalAuthors: String {
        guard let first = authors.first else { return "作者信息待补齐" }
        guard authors.count > 1, let last = authors.last else { return first }
        return "\(first) · \(last)"
    }
    var resourceLinks: [URL] {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else { return [] }
        let text = abstract
        var seen = Set<String>()
        return detector.matches(in: text, range: NSRange(text.startIndex..., in: text)).compactMap { match in
            guard let link = match.url, ["http", "https"].contains(link.scheme?.lowercased() ?? ""), link.absoluteString != url, seen.insert(link.absoluteString).inserted else { return nil }
            return link
        }
    }
    var displayScore: String? { score.map { String(format: "%.1f", $0) } }
    func localizedSummary(_ language: String) -> String {
        language == "en" ? summary_en : (summary_zh.isEmpty ? summary : summary_zh)
    }
    var displayPublished: String { published.isEmpty ? "日期未获取" : published }
    var publicationMonth: String {
        let parts = published.prefix(7).split(separator: "-", omittingEmptySubsequences: false)
        guard parts.count == 2, parts[0].count == 4, parts[1].count == 2,
              let year = Int(parts[0]), year > 0, let month = Int(parts[1]), (1...12).contains(month) else { return "" }
        return String(published.prefix(7))
    }
}

struct PaperMonthSection: Identifiable {
    let id: String
    let papers: [Paper]

    static func grouped(_ papers: [Paper]) -> [PaperMonthSection] {
        let groups = Dictionary(grouping: papers, by: \.publicationMonth)
        return groups.keys.sorted(by: >).map { PaperMonthSection(id: $0, papers: groups[$0] ?? []) }
    }

    func title(language: String) -> String {
        guard !id.isEmpty else { return language == "en" ? "Date unavailable" : "日期未获取" }
        let parts = id.split(separator: "-")
        let year = Int(parts[0]) ?? 0
        let month = Int(parts[1]) ?? 1
        if language != "en" { return "\(year)年\(month)月" }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US")
        return "\(formatter.monthSymbols[month - 1]) \(year)"
    }
}

struct RunStatus: Decodable {
    var message: String = ""
    var updating: Bool = false
    var last_update: String = ""
    var last_update_at: String = ""
    var warnings: [String] = []
    enum CodingKeys: String, CodingKey { case message, updating, last_update, last_update_at, warnings }
    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        message = (try? c.decode(String.self, forKey: .message)) ?? ""
        updating = (try? c.decode(Bool.self, forKey: .updating)) ?? false
        last_update = (try? c.decode(String.self, forKey: .last_update)) ?? ""
        last_update_at = (try? c.decode(String.self, forKey: .last_update_at)) ?? ""
        warnings = (try? c.decode([String].self, forKey: .warnings)) ?? []
    }
}
struct ReadingSettings: Decodable, Equatable {
    var model: String = "gpt-6-astra"
    var effort: String = "high"
    static let models = ["gpt-6-astra", "gpt-6.1-sol"]
    static func modelName(_ model: String) -> String { model }
    static let efforts = ["low", "medium", "high", "xhigh", "max", "ultra"]
    static func defaultEffort(for model: String) -> String { model == "gpt-6.1-sol" ? "medium" : "high" }
}
struct JournalOption: Decodable, Identifiable {
    let id: String
    let name: String
    static let defaults: [JournalOption] = [
        JournalOption(id: "nature", name: "Nature"),
        JournalOption(id: "science", name: "Science"),
        JournalOption(id: "nature_biotechnology", name: "Nature Biotechnology"),
        JournalOption(id: "nature_methods", name: "Nature Methods"),
        JournalOption(id: "nature_chemical_biology", name: "Nature Chemical Biology"),
        JournalOption(id: "nature_structural_molecular_biology", name: "Nature Structural & Molecular Biology"),
        JournalOption(id: "nature_machine_intelligence", name: "Nature Machine Intelligence"),
        JournalOption(id: "nature_computational_science", name: "Nature Computational Science"),
        JournalOption(id: "science_advances", name: "Science Advances"),
        JournalOption(id: "bioinformatics", name: "Bioinformatics"),
        JournalOption(id: "briefings_in_bioinformatics", name: "Briefings in Bioinformatics"),
        JournalOption(id: "nucleic_acids_research", name: "Nucleic Acids Research"),
        JournalOption(id: "nature_communications", name: "Nature Communications")
    ]
}
enum SummaryKeychain {
    static let service = "org.paperinbox.openai"
    static var query: [String: Any] { [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: "default"] }
    static func configured() -> Bool {
        var q = query; q[kSecReturnAttributes as String] = true
        q[kSecUseAuthenticationUI as String] = kSecUseAuthenticationUIFail
        return SecItemCopyMatching(q as CFDictionary, nil) == errSecSuccess
    }
    static func save(_ value: String) throws {
        let key = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { return }
        let data = Data(key.utf8)
        var status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var q = query; q[kSecValueData as String] = data
            q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            status = SecItemAdd(q as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw NSError(domain: "PaperInboxKeychain", code: Int(status)) }
    }
}
struct AppSettings: Decodable, Equatable {
    var summary_provider = "codex"
    var summary_model = "gpt-5.4-mini"
    var summary_effort = "none"
    static let summaryModels = ["gpt-5.4-mini", "gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra"]
    static func summaryEfforts(_ model: String) -> [String] {
        if model == "gpt-5.4-mini" { return ["none", "low", "medium", "high", "xhigh"] }
        if model == "gpt-6-astra" || model == "gpt-6.1-sol" { return ["low", "medium", "high", "xhigh", "max"] }
        return ["none", "low", "medium", "high", "xhigh", "max"]
    }
    var daily_limit: Int = 10
    var arxiv_query: String = "cs.AI+cs.LG+q-bio.BM"
    var biorxiv_query: String = "bioinformatics+biophysics"
    var journal_group: String = "xx"
    var journals: [String] = JournalOption.defaults.map { $0.id }
    var language: String = "zh-Hans"
    var enabled_sources: [String] = ["arXiv", "bioRxiv", "Journals"]
    static let sources = ["arXiv", "bioRxiv", "Journals"]
    enum CodingKeys: String, CodingKey { case daily_limit, arxiv_query, biorxiv_query, journal_group, journals, language, enabled_sources, summary_provider, summary_model, summary_effort }
    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        summary_provider = (try? c.decode(String.self, forKey: .summary_provider)) ?? "codex"
        summary_model = (try? c.decode(String.self, forKey: .summary_model)) ?? "gpt-5.4-mini"
        summary_effort = (try? c.decode(String.self, forKey: .summary_effort)) ?? "none"
        daily_limit = (try? c.decode(Int.self, forKey: .daily_limit)) ?? 10
        arxiv_query = (try? c.decode(String.self, forKey: .arxiv_query)) ?? "cs.AI+cs.LG+q-bio.BM"
        biorxiv_query = (try? c.decode(String.self, forKey: .biorxiv_query)) ?? "bioinformatics+biophysics"
        journal_group = (try? c.decode(String.self, forKey: .journal_group)) ?? "xx"
        journals = (try? c.decode([String].self, forKey: .journals)) ?? JournalOption.defaults.map { $0.id }
        language = (try? c.decode(String.self, forKey: .language)) ?? "zh-Hans"
        enabled_sources = (try? c.decode([String].self, forKey: .enabled_sources)) ?? Self.sources
    }
    var payload: [String: Any] {
        ["summary_provider": summary_provider,"summary_model": summary_model,"summary_effort": summary_effort,"daily_limit": daily_limit, "arxiv_query": arxiv_query, "biorxiv_query": biorxiv_query,
         "journal_group": journal_group, "journals": journals, "language": language, "enabled_sources": enabled_sources]
    }
}
struct ReadingTask: Decodable {
    let status: String?
    let message: String?
    let thread_url: String?
    let motivation: String?
    let take_home_message: String?
    let motivation_zh: String?
    let motivation_en: String?
    let take_home_message_zh: String?
    let take_home_message_en: String?
    func localizedMotivation(_ language: String) -> String? {
        language == "en" ? (motivation_en ?? motivation_zh ?? motivation) : (motivation_zh ?? motivation ?? motivation_en)
    }
    func localizedTakeHome(_ language: String) -> String? {
        language == "en" ? (take_home_message_en ?? take_home_message_zh ?? take_home_message) : (take_home_message_zh ?? take_home_message ?? take_home_message_en)
    }
    var statusLabel: String {
        switch status {
        case "pending": return "已排队"
        case "creating", "thread_created", "submitting": return "正在提交"
        case "running": return "正在精读"
        case "completed": return "精读完成"
        case "incomplete": return "精读待补全"
        case "failed": return "精读未完成"
        case "needs_attention", "submission_unknown": return "需要查看任务"
        default: return "精读任务"
        }
    }
    var threadURL: URL? {
        guard let thread_url, let url = URL(string: thread_url), url.scheme == "codex" else { return nil }
        return url
    }
}
struct InboxState: Decodable {
    let papers: [Paper]
    let status: RunStatus
    let reading_settings: ReadingSettings?
    let app_settings: AppSettings?
    let journal_options: [JournalOption]?
}
struct ServerInfo: Decodable { let port: Int; let token: String }

@MainActor final class InboxModel: ObservableObject {
    @Published var papers: [Paper] = []
    @Published var status = RunStatus()
    @Published var error = ""
    @Published var selected: String?
    @Published var filter = "未读"
    @Published var searching = ""
    @Published var requestingUpdate = false
    @Published var markingAllRead = false
    @Published var busyIDs: Set<String> = []
    @Published var refreshing = false
    @Published var readingSettings = ReadingSettings()
    @Published var appSettings = AppSettings()
    @Published var journalOptions = JournalOption.defaults
    @Published var showingSettings = false
    @Published var savingSettings = false
    @Published var settingsMessage = ""
    @Published var settingsError = ""
    private var settingsRevision = 0
    private var hasLoadedPapers = false
    private var lastLaunchAttempt = Date.distantPast
    private var process: Process?
    private var timer: Timer?
    var onUnread: ((Int) -> Void)?
    let root: URL
    init() {
        root = URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "PaperInboxRoot") as? String ?? FileManager.default.currentDirectoryPath)
    }
    var visible: [Paper] {
        papers.filter { p in
            let matches = filter == "全部" || (filter == "未读" && !p.read) || (filter == "收藏" && p.favorite) || (filter == "已读" && p.read)
            return matches && (searching.isEmpty || "\(p.title) \(p.summary) \(p.summary_en) \(p.authors.joined(separator: " "))".localizedCaseInsensitiveContains(searching))
        }
    }
    var selectedPaper: Paper? { papers.first { $0.id == selected } }
    var groupsByMonth: Bool { ["全部", "收藏", "已读"].contains(filter) }
    var visibleSections: [PaperMonthSection] {
        groupsByMonth ? PaperMonthSection.grouped(visible) : [PaperMonthSection(id: "", papers: visible)]
    }
    func count(_ f: String) -> Int { papers.filter { f == "全部" || (f == "未读" && !$0.read) || (f == "收藏" && $0.favorite) || (f == "已读" && $0.read) }.count }
    func start() {
        Task { await refresh() }
        timer = Timer.scheduledTimer(withTimeInterval: 8, repeats: true) { [weak self] _ in Task { @MainActor in await self?.refresh() } }
    }
    func request(_ endpoint: String, payload: [String:Any]? = nil) async throws -> Data {
        let info = try JSONDecoder().decode(ServerInfo.self, from: Data(contentsOf: root.appendingPathComponent("cache/server.json")))
        guard (1024...65535).contains(info.port), let url = URL(string: "http://127.0.0.1:\(info.port)\(endpoint)") else { throw URLError(.badURL) }
        var req = URLRequest(url: url); req.timeoutInterval = 15
        req.setValue("Bearer \(info.token)", forHTTPHeaderField: "Authorization")
        if let payload {
            req.httpMethod = "POST"; req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: payload)
        }
        let (data, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            let text = String(data: data, encoding: .utf8) ?? "请求失败"
            throw NSError(domain: "PaperInbox", code: 1, userInfo: [NSLocalizedDescriptionKey: String(text.prefix(250))])
        }
        return data
    }
    func refresh() async {
        guard !refreshing else { return }; refreshing = true; defer { refreshing = false }
        let revision = settingsRevision
        do {
            let data = try await request("/api/state")
            let value = try JSONDecoder().decode(InboxState.self, from: data)
            papers = value.papers; status = value.status; error = ""
            if !savingSettings, revision == settingsRevision {
                if let settings = value.reading_settings { readingSettings = settings }
                if let settings = value.app_settings { appSettings = settings }
                if let options = value.journal_options, !options.isEmpty { journalOptions = options }
            }
            if !hasLoadedPapers && !papers.isEmpty {
                selected = visible.first?.id
                hasLoadedPapers = true
            } else if selected != nil && !papers.contains(where: { $0.id == selected }) {
                selected = visible.first?.id
            }
            onUnread?(papers.filter { !$0.read }.count)
        } catch {
            self.error = L("本地服务暂不可用：") + error.localizedDescription
            launchBackend()
        }
    }
    private func launchBackend() {
        guard Date().timeIntervalSince(lastLaunchAttempt) >= 30 else { return }
        guard process?.isRunning != true else { return }
        lastLaunchAttempt = Date()
        let backend = root.appendingPathComponent("src/server.py")
        guard FileManager.default.fileExists(atPath: backend.path) else { error = L("未找到本地服务，请使用启动脚本打开应用。"); return }
        do {
            let cache = root.appendingPathComponent("cache")
            try FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
            let logfile = cache.appendingPathComponent("backend.log")
            if !FileManager.default.fileExists(atPath: logfile.path) { FileManager.default.createFile(atPath: logfile.path, contents: nil) }
            let log = try FileHandle(forWritingTo: logfile); try log.seekToEnd()
            let runtimeData = try Data(contentsOf: root.appendingPathComponent("sources.json"))
            let runtime = try JSONSerialization.jsonObject(with: runtimeData) as? [String: Any] ?? [:]
            let python = runtime["retrieval_python"] as? String ?? "/usr/bin/python3"
            let p = Process(); p.executableURL = URL(fileURLWithPath: python)
            p.arguments = ["-B", backend.path]; p.currentDirectoryURL = root
            var environment = ProcessInfo.processInfo.environment
            environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            p.environment = environment
            p.standardOutput = log; p.standardError = log
            try p.run(); process = p
        } catch { self.error = L("无法启动本地服务：") + error.localizedDescription }
    }
    func nextUnread(after id: String, in items: [Paper]) -> Paper? {
        guard let index = items.firstIndex(where: { $0.id == id }) else {
            return items.first { !$0.read && $0.id != id }
        }
        return items.dropFirst(index + 1).first { !$0.read && $0.id != id }
            ?? items.prefix(index).first { !$0.read && $0.id != id }
    }
    func markVisibleRead() {
        guard !markingAllRead else { return }
        let ids = visible.filter { !$0.read }.map { $0.id }
        guard !ids.isEmpty else { return }
        markingAllRead = true
        Task {
            defer { markingAllRead = false }
            do {
                let data = try await request("/api/read-many", payload: ["ids": ids])
                let value = try JSONDecoder().decode(InboxState.self, from: data)
                papers = value.papers; status = value.status; error = ""
                onUnread?(papers.filter { !$0.read }.count)
                if !visible.contains(where: { $0.id == selected }) { selected = visible.first?.id }
            } catch { self.error = error.localizedDescription }
        }
    }
    func action(_ paper: Paper, _ action: String) {
        guard !busyIDs.contains(paper.id) else { return }
        busyIDs.insert(paper.id)
        let previousOrder = visible.map { $0.id }
        Task {
            defer { busyIDs.remove(paper.id) }
            do {
                let data = try await request("/api/action", payload: ["id": paper.id, "action": action])
                let value = try JSONDecoder().decode(InboxState.self, from: data)
                papers = value.papers; status = value.status; error = ""
                onUnread?(papers.filter { !$0.read }.count)
                if action == "read", selected == paper.id {
                    let scoped = previousOrder.compactMap { id in papers.first { $0.id == id } }
                    let next = nextUnread(after: paper.id, in: scoped) ?? nextUnread(after: paper.id, in: papers)
                    if let next, !scoped.contains(where: { $0.id == next.id }) {
                        filter = "未读"; searching = ""
                    }
                    selected = next?.id
                }
            }
            catch { self.error = error.localizedDescription }
        }
    }
    func L(_ value: String) -> String { UIStrings.text(value, language: appSettings.language) }
    func openSettings() {
        if !showingSettings {
            settingsMessage = ""
            settingsError = ""
        }
        showingSettings = true
    }
    func saveSettings(app: AppSettings, reading: ReadingSettings) async {
        guard !savingSettings else { return }
        guard (1...50).contains(app.daily_limit), !app.enabled_sources.isEmpty else {
            settingsError = L("每日篇数需为 1–50，并至少选择一个来源。")
            return
        }
        guard !app.enabled_sources.contains("Journals") || !app.journals.isEmpty else {
            settingsError = L("至少选择一本期刊")
            return
        }
        savingSettings = true
        settingsRevision += 1
        settingsMessage = ""
        settingsError = ""
        defer {
            savingSettings = false
            settingsRevision += 1
        }
        var savedApp = false
        do {
            if app != appSettings {
                let data = try await request("/api/app-settings", payload: app.payload)
                let value = try JSONDecoder().decode(InboxState.self, from: data)
                appSettings = value.app_settings ?? app
                savedApp = true
            }
            if reading != readingSettings {
                let data = try await request("/api/reading-settings", payload: ["model": reading.model, "effort": reading.effort])
                let value = try JSONDecoder().decode(InboxState.self, from: data)
                readingSettings = value.reading_settings ?? reading
            }
            settingsMessage = L("已保存")
        } catch {
            if savedApp { settingsMessage = L("来源与篇数已保存") }
            settingsError = L("保存未完成。") + error.localizedDescription
        }
    }
    func update() {
        guard !requestingUpdate && !status.updating else { return }
        requestingUpdate = true
        Task {
            defer { requestingUpdate = false }
            do { _ = try await request("/api/update", payload: [:]); await refresh() }
            catch { self.error = error.localizedDescription }
        }
    }
}

/// A fixed-size surface: feedback changes color only, so rows never shift under the pointer.
struct InboxSurfaceStyle: ButtonStyle {
    var selected = false
    var cornerRadius: CGFloat = 0
    let accent: Color
    @ViewState<Bool> private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(accent.opacity(configuration.isPressed ? 0.19 : selected ? 0.12 : hovering ? 0.055 : 0), in: RoundedRectangle(cornerRadius: cornerRadius))
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius)
                    .strokeBorder(accent.opacity(hovering || configuration.isPressed ? 0.15 : 0), lineWidth: 1)
            }
            .onHover { hovering = $0 }
            .animation(reduceMotion ? nil : .easeOut(duration: 0.13), value: hovering)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.10), value: configuration.isPressed)
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.16), value: selected)
    }
}

struct InboxSettingsView: View {
    @ObservedObject var model: InboxModel
    @Environment(\.dismiss) private var dismiss
    @ViewState private var app: AppSettings
    @ViewState private var reading: ReadingSettings
    @ViewState private var choosingJournals = false
    @ViewState private var apiKey = ""
    @ViewState private var keyConfigured = SummaryKeychain.configured()
    @ViewState private var section = "models"
    private let accent = Color(red: 0.14, green: 0.38, blue: 0.34)
    func L(_ value: String) -> String { UIStrings.text(value, language: app.language) }
    init(model: InboxModel) {
        self.model = model
        _app = ViewState(initialValue: model.appSettings)
        _reading = ViewState(initialValue: model.readingSettings)
    }
    private var sectionTitle: String {
        L(section == "general" ? "通用" : section == "models" ? "模型与密钥" : "文献来源")
    }
    private func row<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 16) {
            Text(L(title)).font(.system(size: 13)).foregroundStyle(.secondary).frame(width: 116, alignment: .leading)
            content().frame(maxWidth: .infinity, alignment: .leading)
        }.frame(minHeight: 27)
    }
    private func card<Content: View>(_ title: String, symbol: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 15) {
            Label(L(title), systemImage: symbol).font(.system(size: 13, weight: .semibold)).foregroundStyle(accent)
            content()
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(nsColor: .windowBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.primary.opacity(0.065), lineWidth: 1))
    }
    private var generalSettings: some View {
        VStack(spacing: 16) {
            card("语言", symbol: "globe") {
                row("语言") {
                    Picker(L("语言"), selection: $app.language) {
                        Text("中文").tag("zh-Hans")
                        Text("English").tag("en")
                    }.labelsHidden().pickerStyle(.segmented).frame(width: 210)
                }
            }
            card("每日文献", symbol: "calendar") {
                row("每日精选") {
                    HStack {
                        Text("\(app.daily_limit) \(L("篇"))").monospacedDigit()
                        Spacer()
                        Stepper(L("每日精选"), value: $app.daily_limit, in: 1...50).labelsHidden().fixedSize()
                    }
                }
                Text(L("来源与篇数在下次更新时生效。")).font(.caption).foregroundStyle(.secondary)
            }
        }
    }
    private var modelSettings: some View {
        VStack(spacing: 16) {
            card("摘要生成", symbol: "text.alignleft") {
                row("摘要服务") {
                    Picker(L("摘要服务"), selection: $app.summary_provider) {
                        Text("Codex").tag("codex")
                        Text("OpenAI API").tag("openai")
                    }.labelsHidden()
                }
                if app.summary_provider == "openai" {
                    row("模型") {
                        Picker(L("模型"), selection: Binding(get: { app.summary_model }, set: { value in
                            app.summary_model = value
                            if !AppSettings.summaryEfforts(value).contains(app.summary_effort) { app.summary_effort = "medium" }
                        })) {
                            ForEach(AppSettings.summaryModels, id: \.self) { Text($0).tag($0) }
                        }.labelsHidden()
                    }
                    row("推理强度") {
                        Picker(L("推理强度"), selection: $app.summary_effort) {
                            ForEach(AppSettings.summaryEfforts(app.summary_model), id: \.self) { Text($0).tag($0) }
                        }.labelsHidden()
                    }
                    Divider().padding(.vertical, 1)
                    row("API 密钥") {
                        SecureField(L("API 密钥"), text: $apiKey).textFieldStyle(.roundedBorder)
                    }
                    HStack(spacing: 6) {
                        Image(systemName: keyConfigured ? "checkmark.shield" : "key")
                        Text(L(keyConfigured ? "已保存到钥匙串" : "未配置密钥"))
                        Spacer()
                    }.font(.caption).foregroundStyle(keyConfigured ? accent : .secondary)
                    Text(L("留空保留现有密钥")).font(.caption).foregroundStyle(.secondary)
                }
            }
            card("收藏精读", symbol: "book.closed") {
                row("模型") {
                    Picker(L("模型"), selection: Binding(get: { reading.model }, set: { selected in
                        reading.model = selected
                        reading.effort = ReadingSettings.defaultEffort(for: selected)
                    })) {
                        ForEach(ReadingSettings.models, id: \.self) { Text($0).tag($0) }
                    }.labelsHidden()
                }
                row("推理强度") {
                    Picker(L("推理强度"), selection: $reading.effort) {
                        ForEach(ReadingSettings.efforts, id: \.self) { Text($0).tag($0) }
                    }.labelsHidden()
                }
            }
        }
    }
    private var sourceSettings: some View {
        VStack(spacing: 16) {
            card("文献来源", symbol: "square.stack") {
                HStack(spacing: 22) {
                    ForEach(AppSettings.sources, id: \.self) { source in
                        Toggle(source == "Journals" ? L("期刊") : source, isOn: Binding(get: {
                            app.enabled_sources.contains(source)
                        }, set: { enabled in
                            app.enabled_sources.removeAll { $0 == source }
                            if enabled { app.enabled_sources.append(source) }
                            app.enabled_sources = AppSettings.sources.filter { app.enabled_sources.contains($0) }
                        })).toggleStyle(.checkbox)
                    }
                }
                if app.enabled_sources.isEmpty { Text(L("至少选择一个来源")).font(.caption).foregroundStyle(.red) }
            }
            card("分类与期刊", symbol: "line.3.horizontal.decrease") {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(L("arXiv 分类")).font(.system(size: 12, weight: .medium))
                        Spacer()
                        Link(L("官方分类说明"), destination: URL(string: "https://arxiv.org/category_taxonomy")!).font(.caption)
                    }
                    TextField("cs.AI+cs.LG+q-bio.BM", text: $app.arxiv_query).textFieldStyle(.roundedBorder)
                }.disabled(!app.enabled_sources.contains("arXiv"))
                Divider()
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(L("bioRxiv 分类")).font(.system(size: 12, weight: .medium))
                        Spacer()
                        Link(L("官方分类说明"), destination: URL(string: "https://www.biorxiv.org/collection")!).font(.caption)
                    }
                    TextField("bioinformatics+biophysics", text: $app.biorxiv_query).textFieldStyle(.roundedBorder)
                }.disabled(!app.enabled_sources.contains("bioRxiv"))
                Divider()
                Button { choosingJournals = true } label: {
                    HStack {
                        Text(L("选择期刊"))
                        Spacer()
                        Text("\(app.journals.count)").monospacedDigit().foregroundStyle(.secondary)
                        Image(systemName: "chevron.right").font(.system(size: 10, weight: .semibold)).foregroundStyle(.tertiary)
                    }.padding(.vertical, 3).contentShape(Rectangle())
                }.buttonStyle(.plain).disabled(!app.enabled_sources.contains("Journals"))
                Text(model.journalOptions.filter { app.journals.contains($0.id) }.map { $0.name }.joined(separator: " · "))
                    .font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(3).lineSpacing(3)
                if app.enabled_sources.contains("Journals"), app.journals.isEmpty {
                    Text(L("至少选择一本期刊")).font(.caption).foregroundStyle(.red)
                }
            }
            Text(L("来源与篇数在下次更新时生效。")).font(.caption).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading)
        }
    }
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 24) {
                    Text(L("设置")).font(.system(size: 22, weight: .semibold)).padding(.horizontal, 10)
                    VStack(spacing: 6) {
                        ForEach([("general", "通用", "gearshape"), ("models", "模型与密钥", "cpu"), ("sources", "文献来源", "square.stack")], id: \.0) { id, title, symbol in
                            Button { section = id } label: {
                                HStack(spacing: 10) {
                                    Image(systemName: symbol).frame(width: 18)
                                    Text(L(title)).font(.system(size: 13, weight: section == id ? .semibold : .regular))
                                    Spacer(minLength: 0)
                                }.foregroundStyle(section == id ? accent : Color.primary)
                                    .padding(.horizontal, 11).padding(.vertical, 10)
                                    .background(section == id ? accent.opacity(0.11) : .clear, in: RoundedRectangle(cornerRadius: 8))
                                    .contentShape(Rectangle())
                            }.buttonStyle(.plain)
                        }
                    }
                    Spacer()
                }.padding(.horizontal, 14).padding(.top, 28).frame(width: 168)
                    .background(Color(nsColor: .controlBackgroundColor).opacity(0.65))
                Divider()
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        Text(sectionTitle).font(.system(size: 20, weight: .semibold)).padding(.bottom, 2)
                        Group {
                            if section == "general" { generalSettings }
                            else if section == "models" { modelSettings }
                            else { sourceSettings }
                        }
                    }.padding(26).frame(maxWidth: .infinity, alignment: .leading)
                }.background(Color(nsColor: .controlBackgroundColor).opacity(0.28))
            }
            Divider()
            HStack(spacing: 12) {
                if model.savingSettings { ProgressView().controlSize(.small) }
                if !model.settingsError.isEmpty {
                    Text(L(model.settingsError)).font(.caption).foregroundStyle(.red).textSelection(.enabled).lineLimit(2)
                } else if !model.settingsMessage.isEmpty {
                    Label(L(model.settingsMessage), systemImage: "checkmark.circle").font(.caption).foregroundStyle(accent).lineLimit(2)
                }
                Spacer(minLength: 8)
                Button(L("关闭")) { dismiss() }.keyboardShortcut(.cancelAction)
                Button(L("保存")) { Task {
                    do {
                        if !apiKey.isEmpty { try SummaryKeychain.save(apiKey); apiKey = ""; keyConfigured = true }
                        await model.saveSettings(app: app, reading: reading)
                    } catch { model.settingsError = L("密钥保存失败，请解锁钥匙串后重试。") }
                } }.keyboardShortcut(.defaultAction)
                    .disabled(app.enabled_sources.isEmpty || (app.enabled_sources.contains("Journals") && app.journals.isEmpty))
            }.padding(.horizontal, 24).padding(.vertical, 15)
        }.frame(width: 760, height: 620).disabled(model.savingSettings)
            .interactiveDismissDisabled(model.savingSettings)
            .sheet(isPresented: $choosingJournals) {
                VStack(alignment: .leading, spacing: 16) {
                    Text(L("选择期刊")).font(.title2)
                    ScrollView {
                        VStack(alignment: .leading, spacing: 12) {
                            ForEach(model.journalOptions) { journal in
                                Toggle(journal.name, isOn: Binding(get: { app.journals.contains(journal.id) }, set: { enabled in
                                    app.journals.removeAll { $0 == journal.id }
                                    if enabled { app.journals.append(journal.id) }
                                    app.journals = model.journalOptions.map { $0.id }.filter { app.journals.contains($0) }
                                })).toggleStyle(.checkbox)
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }.frame(height: 390)
                    HStack { Spacer(); Button(L("关闭")) { choosingJournals = false }.keyboardShortcut(.defaultAction) }
                }.padding(24).frame(width: 460)
            }
            .onChange(of: app) { _ in model.settingsMessage = ""; model.settingsError = "" }
            .onChange(of: reading) { _ in model.settingsMessage = ""; model.settingsError = "" }
    }
}

struct InboxView: View {
    @ObservedObject var model: InboxModel
    @ViewState private var collapsedMonths: Set<String> = []
    func L(_ value: String) -> String { UIStrings.text(value, language: model.appSettings.language) }
    let accent = Color(red: 0.14, green: 0.38, blue: 0.34)
    private func monthKey(_ month: PaperMonthSection) -> String { model.filter + ":" + month.id }
    private func monthIsCollapsed(_ month: PaperMonthSection) -> Bool { collapsedMonths.contains(monthKey(month)) }
    private func toggleMonth(_ month: PaperMonthSection) {
        let key = monthKey(month)
        withAnimation(.easeInOut(duration: 0.18)) {
            if collapsedMonths.contains(key) { collapsedMonths.remove(key) }
            else { collapsedMonths.insert(key) }
        }
    }
    private func monthAccessibilityLabel(_ month: PaperMonthSection) -> String {
        let title = month.title(language: model.appSettings.language)
        if model.appSettings.language == "en" { return (monthIsCollapsed(month) ? "Expand " : "Collapse ") + title }
        return (monthIsCollapsed(month) ? "展开" : "收起") + title
    }
    var body: some View {
        HStack(spacing: 0) {
            sidebar
            Divider()
            VStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 12) {
                    Text(L(model.filter == "未读" ? "今日值得读" : model.filter)).font(.system(size: 23, weight: .semibold))
                    HStack {
                    Button { model.markVisibleRead() } label: { Label(L("全部已读"), systemImage: "checkmark.circle").fixedSize() }
                        .help(L("将当前列表中的未读论文标为已读"))
                        .accessibilityLabel(L("全部标为已读"))
                        .disabled(model.markingAllRead || !model.busyIDs.isEmpty || !model.visible.contains { !$0.read })
                    if model.status.updating { ProgressView().controlSize(.small) }
                    Button { model.update() } label: { Label(L(model.status.updating ? "更新中" : "更新"), systemImage: "arrow.clockwise") }
                        .disabled(model.status.updating || model.requestingUpdate)
                    Group {
                        if model.status.updating || model.requestingUpdate {
                            Text(L("更新中")).foregroundStyle(.secondary)
                        } else if !model.error.isEmpty || model.status.message.hasPrefix("更新未完成") {
                            Text(L("更新未完成")).foregroundStyle(.orange)
                        } else if !model.status.last_update.isEmpty {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(L("更新完成")).foregroundStyle(accent)
                                if !model.status.last_update_at.isEmpty {
                                    Text(String(model.status.last_update_at.dropFirst(5).prefix(11)).replacingOccurrences(of: "T", with: " ")).monospacedDigit().foregroundStyle(.secondary)
                                }
                            }
                        }
                    }.font(.system(size: 11)).lineLimit(1).minimumScaleFactor(0.8)
                    Spacer()
                    }
                }.padding(22)
                HStack {
                    Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                    TextField(L("搜索标题、摘要或作者"), text: $model.searching).textFieldStyle(.plain)
                }.padding(10).background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 8)).padding(.horizontal, 22).padding(.bottom, 15)
                Divider()
                if model.visible.isEmpty {
                    Spacer()
                    Image(systemName: "tray").font(.system(size: 35, weight: .light)).foregroundStyle(.secondary)
                    Text(L(model.papers.isEmpty ? "正在载入文献" : "这里暂时没有文献")).font(.headline).padding(.top, 12)
                    if model.papers.isEmpty { Text(L("文献和摘要载入后会显示在这里。")).font(.caption).foregroundStyle(.secondary).padding(.top, 3) }
                    Spacer()
                } else {
                    ScrollView {
                        LazyVStack(spacing: 0, pinnedViews: [.sectionHeaders]) {
                            ForEach(model.visibleSections) { month in
                                Section {
                                    if !model.groupsByMonth || !monthIsCollapsed(month) {
                                    ForEach(month.papers) { paper in
                                        Button { model.selected = paper.id } label: {
                                            paperRow(paper)
                                                .contentShape(Rectangle())
                                        }
                                        .buttonStyle(InboxSurfaceStyle(selected: model.selected == paper.id, accent: accent))
                                        .accessibilityValue(model.selected == paper.id ? L("已选中") : "")
                                        Divider().padding(.leading, 20)
                                    }
                                    }
                                } header: {
                                    if model.groupsByMonth {
                                        Button { toggleMonth(month) } label: {
                                        HStack {
                                            Image(systemName: monthIsCollapsed(month) ? "chevron.right" : "chevron.down")
                                                .font(.system(size: 10, weight: .semibold)).frame(width: 10)
                                            Text(month.title(language: model.appSettings.language))
                                                .font(.system(size: 12, weight: .semibold))
                                            Spacer()
                                            Text("\(month.papers.count)")
                                                .font(.system(size: 11, design: .monospaced))
                                                .foregroundStyle(.secondary)
                                        }
                                        .padding(.horizontal, 20).padding(.vertical, 10)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .background(Color(nsColor: .controlBackgroundColor))
                                        .contentShape(Rectangle())
                                        }
                                        .buttonStyle(.plain)
                                        .accessibilityLabel(monthAccessibilityLabel(month))
                                    }
                                }
                            }
                        }
                    }
                }
            }.frame(minWidth: 340, idealWidth: 420, maxWidth: 490)
            Divider()
            detail.frame(minWidth: 370, maxWidth: .infinity)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .frame(minWidth: 980, minHeight: 640)
        .tint(accent)
        .sheet(isPresented: $model.showingSettings) { InboxSettingsView(model: model) }
    }
    var sidebar: some View {
        VStack(alignment: .leading, spacing: 24) {
            VStack(alignment: .leading, spacing: 8) {
                Image(systemName: "books.vertical.fill").font(.system(size: 25)).foregroundStyle(accent)
                Text("Paper Inbox").font(.system(size: 18, weight: .semibold))
            }.padding(.top, 15)
            VStack(spacing: 5) {
                ForEach(["未读", "全部", "收藏", "已读"], id: \.self) { f in
                    Button {
                        model.filter = f; model.selected = model.visible.first?.id
                    } label: {
                        HStack {
                            Image(systemName: ["未读":"tray", "全部":"square.stack", "收藏":"star", "已读":"checkmark.circle"][f]!).frame(width: 19)
                            Text(L(f)).lineLimit(1).fixedSize(horizontal: true, vertical: false); Spacer(); Text("\(model.count(f))").font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
                        }.padding(.horizontal, 10).padding(.vertical, 10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(InboxSurfaceStyle(selected: model.filter == f, cornerRadius: 8, accent: accent))
                    .accessibilityValue(model.filter == f ? L("已选中") : "")
                }
            }
            Spacer()
            Button { model.openSettings() } label: {
                Label(L("设置"), systemImage: "gearshape")
                    .frame(maxWidth: .infinity, alignment: .leading).padding(10)
            }.buttonStyle(InboxSurfaceStyle(cornerRadius: 8, accent: accent))
        }.padding(18).frame(width: 190).background(Color(nsColor: .controlBackgroundColor).opacity(0.5))
    }
    func readingStatus(_ reading: ReadingTask) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            if reading.status != "completed" {
                Text(L(reading.statusLabel))
                    .font(.system(size: 12)).foregroundStyle(.secondary).textSelection(.enabled)
            }
            if let motivation = reading.localizedMotivation(model.appSettings.language), !motivation.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Motivation").font(.system(size: 12, weight: .semibold))
                    Text((try? AttributedString(markdown: motivation, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(motivation)).font(.system(size: 13)).lineSpacing(5).textSelection(.enabled)
                }
            }
            if let takeHome = reading.localizedTakeHome(model.appSettings.language), !takeHome.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Take-home message").font(.system(size: 12, weight: .semibold))
                    Text((try? AttributedString(markdown: takeHome, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(takeHome)).font(.system(size: 13)).lineSpacing(5).textSelection(.enabled)
                }
            }
            if let url = reading.threadURL {
                Link(destination: url) { Label(L("打开 Codex"), systemImage: "arrow.up.right.square") }
                    .font(.system(size: 11))
            }
        }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
            .background(accent.opacity(0.055), in: RoundedRectangle(cornerRadius: 8))
    }
    func paperRow(_ p: Paper) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 7) {
                if !p.read { Circle().fill(accent).frame(width: 5, height: 5) }
                Text(L(p.displaySource)).font(.system(size: 10, weight: .semibold)).foregroundStyle(accent)
                Spacer()
                if p.favorite { Image(systemName: "star.fill").foregroundStyle(.orange).font(.caption) }
                Text(p.displayScore ?? L("无分数")).font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
            }
            Text(p.displayTitle).font(.system(size: 14, weight: .medium)).lineLimit(3).lineSpacing(3)
            Text(L(p.principalAuthors)).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1)
            Text(L(p.displayPublished)).font(.system(size: 10)).foregroundStyle(.tertiary)
        }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
    }
    /// A single Text retains native selection across all summary paragraphs.
    func summaryText(_ summary: String) -> Text {
        guard !summary.isEmpty else { return Text(L("摘要尚未生成。")) }
        var content = AttributedString()
        for (index, line) in summary.components(separatedBy: "\n").enumerated() {
            if index > 0 { content.append(AttributedString("\n")) }
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            let labels = [("问题：", "问题"), ("方法：", "方法"), ("结果：", "结果"), ("问题:", "问题"), ("方法:", "方法"), ("结果:", "结果"), ("Problem:", "问题"), ("Methods:", "方法"), ("Method:", "方法"), ("Results:", "结果"), ("Result:", "结果")]
            let matched = labels.first { trimmed.lowercased().hasPrefix($0.0.lowercased()) }
            if let (label, key) = matched {
                let headingText = L(key) + (model.appSettings.language == "en" ? ": " : "：")
                var heading = AttributedString(headingText)
                heading.font = .system(size: 14, weight: .semibold)
                content.append(heading)
                content.append(AttributedString(String(trimmed.dropFirst(label.count))))
            } else {
                content.append(AttributedString(line))
            }
        }
        return Text(content)
    }

    var detail: some View {
        VStack(alignment: .leading, spacing: 0) {
            if !model.error.isEmpty {
                Text(model.error).font(.caption).foregroundStyle(.red).padding(14).frame(maxWidth: .infinity, alignment: .leading).background(Color.red.opacity(0.06))
            }
            if model.status.message.hasPrefix("更新未完成") {
                Text(L("更新未完成")).font(.caption).foregroundStyle(.red).padding(14)
            }
            if let p = model.selectedPaper {
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        HStack {
                            Text(L(p.displaySource).uppercased()).font(.system(size: 10, weight: .bold)).tracking(1).foregroundStyle(accent)
                            Spacer()
                            Text(L(p.displayPublished)).font(.caption).foregroundStyle(.secondary)
                        }
                        VStack(alignment: .leading, spacing: 8) {
                            Text(L("标题")).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
                            Text(p.displayTitle).font(.system(size: 25, weight: .semibold)).lineSpacing(5).textSelection(.enabled)
                        }
                        if let url = URL(string: p.url), ["https", "http"].contains(url.scheme ?? "") {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(L("原文链接")).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
                                HStack(alignment: .top, spacing: 8) {
                                    Text(p.url).font(.system(size: 12)).foregroundStyle(accent).textSelection(.enabled)
                                    Link(destination: url) { Image(systemName: "arrow.up.right.square") }
                                        .accessibilityLabel(L("打开原文链接"))
                                }
                            }
                        }
                        HStack(spacing: 10) {
                            Label(p.displayScore.map { L("相关性") + " \($0)" } ?? L("相关性不可用"), systemImage: "sparkle").font(.system(size: 11)).foregroundStyle(accent)
                            if p.read { Label(L("已读"), systemImage: "checkmark.circle").font(.caption).foregroundStyle(.secondary) }
                        }
                        Divider()
                        VStack(alignment: .leading, spacing: 8) {
                            Text(L("作者")).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
                            Text(p.authors.isEmpty ? L("未获取") : p.linkedAuthors).font(.system(size: 12)).textSelection(.enabled)
                            Text(L("主要单位")).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary).padding(.top, 7)
                            Text(p.affiliations.isEmpty ? L("未获取") : p.numberedAffiliations).font(.system(size: 12)).foregroundStyle(.secondary).textSelection(.enabled)
                        }
                        if let reading = p.reading { readingStatus(reading) }
                        Divider()
                        VStack(alignment: .leading, spacing: 12) {
                            Text(L("摘要")).font(.system(size: 13, weight: .semibold))
                            summaryText(p.localizedSummary(model.appSettings.language))
                                .font(.system(size: 14))
                                .lineSpacing(8)
                                .fixedSize(horizontal: false, vertical: true)
                                .textSelection(.enabled)
                            if !p.resourceLinks.isEmpty {
                                Text(L("代码与相关资源")).font(.system(size: 12, weight: .semibold))
                                ForEach(p.resourceLinks, id: \.absoluteString) { link in
                                    HStack(alignment: .top) {
                                        Text(link.absoluteString).font(.system(size: 12))
                                            .foregroundStyle(accent).textSelection(.enabled)
                                        Link(destination: link) { Image(systemName: "arrow.up.right.square") }
                                            .accessibilityLabel(L("打开相关资源"))
                                    }
                                }
                            }
                        }

                    }.padding(28)
                }.id(p.id)
                Divider()
                HStack(spacing: 10) {
                    Button { model.action(p, p.favorite ? "unfavorite" : "favorite") } label: { Label(L(p.favorite ? "已收藏" : "收藏"), systemImage: p.favorite ? "star.fill" : "star") }
                        .buttonStyle(.borderedProminent).disabled(model.busyIDs.contains(p.id))
                        .help(L(p.favorite ? "取消收藏会将 Zotero 文献移入回收站" : "收藏并开始精读"))
                    Button { model.action(p, p.read ? "unread" : "read") } label: { Label(L(p.read ? "设为未读" : "标记已读"), systemImage: p.read ? "arrow.uturn.backward" : "checkmark") }.disabled(model.busyIDs.contains(p.id))
                    Spacer()
                    Button {
                        if let url = URL(string: p.url), ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
                    } label: { Label(L("打开原文"), systemImage: "arrow.up.right.square") }.help(L("打开论文原始页面"))
                }.padding(18)
            } else {
                Spacer(); HStack { Spacer(); Text(L(!model.papers.isEmpty && model.papers.allSatisfy { $0.read } ? "未读文献已全部读完" : "选择一篇论文开始阅读")).foregroundStyle(.secondary); Spacer() }; Spacer()
            }
        }
    }
}

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = InboxModel()
    var statusItem: NSStatusItem!
    var window: NSWindow!
    private var textShortcutMonitor: Any?
    private var languageObserver: AnyCancellable?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let mainMenu = NSMenu()
        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "打开文献收件箱", action: #selector(showWindow), keyEquivalent: "o").target = self
        appMenu.addItem(withTitle: "设置…", action: #selector(openSettings), keyEquivalent: ",").target = self
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出 Paper Inbox", action: #selector(quit), keyEquivalent: "q").target = self
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)
        let editMenuItem = NSMenuItem(title: "编辑", action: nil, keyEquivalent: "")
        let editMenu = NSMenu(title: "编辑")
        editMenu.addItem(withTitle: "拷贝", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editMenuItem.submenu = editMenu
        mainMenu.addItem(editMenuItem)
        NSApp.mainMenu = mainMenu
        textShortcutMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            guard event.modifierFlags.intersection(.deviceIndependentFlagsMask) == .control,
                  let responder = NSApp.keyWindow?.firstResponder,
                  let textInput = responder as? NSTextInputClient else { return event }
            switch event.charactersIgnoringModifiers?.lowercased() {
            case "c" where textInput.selectedRange().length > 0:
                return NSApp.sendAction(#selector(NSText.copy(_:)), to: nil, from: nil) ? nil : event
            case "v":
                guard let text = responder as? NSTextView, text.isEditable else { return event }
                text.paste(nil)
                return nil
            default:
                return event
            }
        }
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        let menuIcon = Bundle.main.url(forResource: "MenuBarIcon", withExtension: "png").flatMap { NSImage(contentsOf: $0) }
        menuIcon?.size = NSSize(width: 18, height: 18)
        menuIcon?.isTemplate = true
        statusItem.button?.image = menuIcon ?? NSImage(systemSymbolName: "tray", accessibilityDescription: "Paper Inbox")
        if let iconURL = Bundle.main.url(forResource: "AppIcon", withExtension: "icns") {
            NSApp.applicationIconImage = NSImage(contentsOf: iconURL)
        }
        statusItem.button?.imagePosition = .imageLeading
        statusItem.button?.toolTip = "Paper Inbox · 文献收件箱"
        let menu = NSMenu()
        menu.addItem(withTitle: "打开文献收件箱", action: #selector(showWindow), keyEquivalent: "o").target = self
        menu.addItem(withTitle: "立即更新", action: #selector(update), keyEquivalent: "r").target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "退出 Paper Inbox", action: #selector(quit), keyEquivalent: "q").target = self
        statusItem.menu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1190, height: 790), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Paper Inbox"; window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 980, height: 640)
        window.contentView = NSHostingView(rootView: InboxView(model: model)); window.center()
        model.onUnread = { [weak self] count in self?.statusItem.button?.title = count > 0 ? " \(count)" : "" }
        registerMenuKeys(mainMenu)
        registerMenuKeys(menu)
        languageObserver = model.$appSettings.map { $0.language }.removeDuplicates().sink { [weak self] language in
            self?.localizeMenu(mainMenu, language: language)
            self?.localizeMenu(menu, language: language)
        }
        model.start(); showWindow()
    }
    private func registerMenuKeys(_ menu: NSMenu) {
        for item in menu.items where !item.isSeparatorItem {
            item.representedObject = item.title
            if let submenu = item.submenu { registerMenuKeys(submenu) }
        }
    }
    private func localizeMenu(_ menu: NSMenu, language: String) {
        for item in menu.items {
            if let key = item.representedObject as? String { item.title = UIStrings.text(key, language: language) }
            if let submenu = item.submenu { localizeMenu(submenu, language: language) }
        }
        statusItem.button?.toolTip = "Paper Inbox"
    }
    @objc func showWindow() { NSApp.activate(ignoringOtherApps: true); window.makeKeyAndOrderFront(nil) }
    @objc func openSettings() { showWindow(); model.openSettings() }
    @objc func update() { model.update() }
    @objc func quit() { NSApp.terminate(nil) }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return true
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}
@main struct PaperInboxMain {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate(); app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
