import ServerPlugins
import SwiftUI

struct ModulesView: View {
    @ObservedObject var model: LinkAppModel

    private var selectedRecord: DisplayPluginRecord? {
        model.pluginRecords.first { $0.id == model.selectedPluginID }
    }

    var body: some View {
        HSplitView {
            VStack(spacing: 0) {
                if model.pluginRecords.isEmpty {
                    ModuleEmptyState(
                        title: "Нет модулей",
                        systemImage: "puzzlepiece.extension",
                        detail: "Установите архив .ctplugin, чтобы добавить новый экранный модуль."
                    )
                } else {
                    List(
                        model.pluginRecords,
                        selection: $model.selectedPluginID
                    ) { record in
                        ModuleRow(
                            record: record,
                            enabled: Binding(
                                get: { record.enabled },
                                set: {
                                    model.setPluginEnabled($0, id: record.id)
                                }
                            )
                        )
                        .tag(record.id)
                    }
                    .listStyle(.inset)
                }
            }
            .frame(minWidth: 300, idealWidth: 340)

            ModuleDetail(
                record: selectedRecord,
                remove: {
                    guard let id = selectedRecord?.id else { return }
                    model.uninstallPlugin(id: id)
                }
            )
            .frame(minWidth: 330)
        }
        .navigationTitle("Модули")
        .toolbar {
            ToolbarItemGroup {
                Button {
                    model.revealPluginsFolder()
                } label: {
                    Image(systemName: "folder")
                }
                .help("Показать папку модулей")

                Button {
                    model.choosePluginArchive()
                } label: {
                    Label("Установить", systemImage: "plus")
                }
                .help("Установить архив .ctplugin")
            }
        }
    }
}

private struct ModuleRow: View {
    let record: DisplayPluginRecord
    @Binding var enabled: Bool

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: record.manifest.icon ?? "puzzlepiece.extension")
                .foregroundStyle(.secondary)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                Text(record.manifest.name)
                    .lineLimit(1)
                Text("\(record.manifest.version) · \(statusText)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            Toggle("", isOn: $enabled)
                .labelsHidden()
        }
        .padding(.vertical, 3)
    }

    private var statusText: String {
        switch record.status {
        case .disabled: return "выключен"
        case .starting: return "запуск"
        case .running: return "работает"
        case .failed: return "ошибка"
        case .stopped: return "остановлен"
        }
    }
}

private struct ModuleDetail: View {
    let record: DisplayPluginRecord?
    let remove: () -> Void

    var body: some View {
        if let record {
            Form {
                Section {
                    LabeledContent("Идентификатор", value: record.id)
                    LabeledContent("Версия", value: record.manifest.version)
                    LabeledContent("Карточек", value: "\(record.cardCount)")
                    LabeledContent("Состояние", value: record.status.rawValue)
                }
                if !record.manifest.summary.isEmpty {
                    Section("Описание") {
                        Text(record.manifest.summary)
                    }
                }
                Section("Заявленные возможности") {
                    if record.manifest.permissions.isEmpty {
                        Text("Не заявлены")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(record.manifest.permissions, id: \.self) {
                            Text($0)
                        }
                    }
                }
                if !record.message.isEmpty {
                    Section("Последнее сообщение") {
                        Text(record.message)
                            .foregroundStyle(
                                record.status == .failed ? .red : .secondary
                            )
                    }
                }
                Section {
                    Button("Удалить модуль", role: .destructive, action: remove)
                }
            }
            .formStyle(.grouped)
            .padding()
        } else {
            ModuleEmptyState(
                title: "Выберите модуль",
                systemImage: "sidebar.left",
                detail: "Здесь отображаются manifest, состояние и разрешения."
            )
        }
    }
}

private struct ModuleEmptyState: View {
    let title: String
    let systemImage: String
    let detail: String

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.system(size: 36))
                .foregroundStyle(.secondary)
            Text(title)
                .font(.title3.weight(.semibold))
            Text(detail)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 300)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(32)
    }
}
