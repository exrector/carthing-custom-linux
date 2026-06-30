import SwiftUI

struct OverviewView: View {
    @ObservedObject var model: LinkAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Car Thing")
                        .font(.largeTitle.weight(.semibold))
                    Text(model.deviceName)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                StatusLabel(
                    title: model.linkConnected
                        ? "CTSP подключён"
                        : model.phaseLabel,
                    active: model.linkConnected
                )
            }
            .padding(24)

            Divider()

            Grid(alignment: .leading, horizontalSpacing: 42, verticalSpacing: 18) {
                overviewRow(
                    "Bluetooth",
                    model.phaseLabel,
                    "dot.radiowaves.left.and.right"
                )
                overviewRow(
                    "L2CAP",
                    model.psm.map { "PSM \($0)" } ?? "Ожидание",
                    "link"
                )
                overviewRow(
                    "Ассистент",
                    model.assistantRunning ? "Работает" : "Ожидание",
                    "waveform"
                )
                overviewRow(
                    "Микрофоны",
                    model.micStreaming ? "Поток активен" : "Выключены",
                    "mic"
                )
                overviewRow(
                    "Модули",
                    "Активно: \(model.pluginRecords.filter(\.enabled).count)",
                    "puzzlepiece.extension"
                )
            }
            .padding(24)
            Spacer()
        }
        .navigationTitle("Обзор")
    }

    @ViewBuilder
    private func overviewRow(
        _ label: String,
        _ value: String,
        _ icon: String
    ) -> some View {
        GridRow {
            Label(label, systemImage: icon)
                .frame(width: 160, alignment: .leading)
                .foregroundStyle(.secondary)
            Text(value)
                .textSelection(.enabled)
        }
    }
}

private struct StatusLabel: View {
    let title: String
    let active: Bool

    var body: some View {
        Label(
            title,
            systemImage: active ? "checkmark.circle.fill" : "circle.dotted"
        )
        .foregroundStyle(active ? .green : .secondary)
    }
}
