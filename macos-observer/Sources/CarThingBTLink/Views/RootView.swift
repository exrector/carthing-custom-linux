import SwiftUI

private enum AppSection: String, CaseIterable, Identifiable {
    case overview
    case assistant
    case modules
    case diagnostics

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview: return "Обзор"
        case .assistant: return "Ассистент"
        case .modules: return "Модули"
        case .diagnostics: return "Диагностика"
        }
    }

    var icon: String {
        switch self {
        case .overview: return "dot.radiowaves.left.and.right"
        case .assistant: return "waveform"
        case .modules: return "puzzlepiece.extension"
        case .diagnostics: return "waveform.path.ecg"
        }
    }
}

struct RootView: View {
    @ObservedObject var model: LinkAppModel
    @State private var selection: AppSection? = .overview

    var body: some View {
        NavigationSplitView {
            List(AppSection.allCases, selection: $selection) { section in
                Label(section.title, systemImage: section.icon)
                    .tag(section)
            }
            .listStyle(.sidebar)
            .navigationTitle("Car Thing")
        } detail: {
            switch selection ?? .overview {
            case .overview:
                OverviewView(model: model)
            case .assistant:
                AssistantView(model: model)
            case .modules:
                ModulesView(model: model)
            case .diagnostics:
                DiagnosticsView(model: model)
            }
        }
    }
}
