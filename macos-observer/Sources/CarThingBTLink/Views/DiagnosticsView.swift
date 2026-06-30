import SwiftUI

struct DiagnosticsView: View {
    @ObservedObject var model: LinkAppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("События текущего запуска")
                    .font(.headline)
                Spacer()
                if !model.lastError.isEmpty {
                    Label(model.lastError, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.red)
                        .lineLimit(1)
                }
            }
            .padding()
            Divider()
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(model.events.enumerated()), id: \.offset) {
                        Text($0.element)
                            .font(.system(.body, design: .monospaced))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding()
            }
        }
        .navigationTitle("Диагностика")
    }
}
