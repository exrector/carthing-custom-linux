import SwiftUI

struct AssistantView: View {
    @ObservedObject var model: LinkAppModel

    var body: some View {
        HSplitView {
            conversation
                .frame(minWidth: 390, idealWidth: 520)
            configuration
                .frame(minWidth: 310, idealWidth: 360, maxWidth: 420)
        }
        .navigationTitle("Ассистент")
    }

    private var conversation: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Label(
                    model.assistantStatus,
                    systemImage: model.assistantRunning
                        ? "waveform.circle.fill"
                        : "waveform.circle"
                )
                .foregroundStyle(
                    model.assistantRunning ? .green : .secondary
                )
                Spacer()
                if model.micStreaming {
                    Label("Микрофон", systemImage: "mic.fill")
                        .foregroundStyle(.green)
                }
                Button {
                    model.clearAssistantConversation()
                } label: {
                    Image(systemName: "trash")
                }
                .help("Очистить диалог")
                .disabled(
                    model.assistantMessages.isEmpty
                        && model.assistantLiveText.isEmpty
                )
            }
            .padding()

            Divider()

            if model.assistantMessages.isEmpty
                && model.assistantLiveText.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "text.bubble")
                        .font(.system(size: 36))
                        .foregroundStyle(.secondary)
                    Text("Диалог пуст")
                        .font(.title3.weight(.semibold))
                    Text(
                        "Реплики с Car Thing появятся здесь одновременно с экраном устройства."
                    )
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 320)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(32)
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 14) {
                            ForEach(model.assistantMessages) { message in
                                AssistantMessageRow(message: message)
                                    .id(message.id)
                            }
                            if !model.assistantLiveText.isEmpty {
                                AssistantLiveRow(
                                    text: model.assistantLiveText
                                )
                                .id("assistant-live")
                            }
                        }
                        .padding()
                    }
                    .onChange(of: model.assistantMessages.count) { _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: model.assistantLiveText) { _ in
                        scrollToBottom(proxy)
                    }
                }
            }
        }
    }

    private var configuration: some View {
        Form {
            Section {
                Toggle(
                    "Ассистент",
                    isOn: Binding(
                        get: { model.assistantEnabled },
                        set: { model.setAssistantEnabled($0) }
                    )
                )
                LabeledContent("Процесс") {
                    Text(model.assistantRunning ? "Работает" : "Остановлен")
                        .foregroundStyle(
                            model.assistantRunning ? .green : .secondary
                        )
                }
            }

            Section("Модель") {
                Picker(
                    "Провайдер",
                    selection: Binding(
                        get: { model.assistantProvider },
                        set: { model.selectAssistantProvider($0) }
                    )
                ) {
                    Text("Mistral").tag("mistral")
                    Text("Gemini").tag("gemini")
                }
                .pickerStyle(.segmented)

                TextField("Модель", text: $model.assistantModel)

                SecureField("API-ключ", text: $model.assistantAPIKey)
                    .textContentType(.password)
            }

            Section("Окружение") {
                HStack {
                    TextField(
                        "Файл .env",
                        text: $model.assistantEnvironmentFile
                    )
                    Button {
                        model.chooseAssistantEnvironmentFile()
                    } label: {
                        Image(systemName: "folder")
                    }
                    .help("Выбрать файл .env")
                }
            }

            Section("Системная инструкция") {
                TextEditor(text: $model.assistantSystemPrompt)
                    .font(.body)
                    .frame(minHeight: 110)
            }

            Section {
                Button {
                    model.saveAssistantConfiguration()
                } label: {
                    Label(
                        "Применить и перезапустить",
                        systemImage: "arrow.clockwise"
                    )
                }
                .disabled(!model.assistantEnabled)
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        withAnimation(.easeOut(duration: 0.15)) {
            if !model.assistantLiveText.isEmpty {
                proxy.scrollTo("assistant-live", anchor: .bottom)
            } else if let id = model.assistantMessages.last?.id {
                proxy.scrollTo(id, anchor: .bottom)
            }
        }
    }
}

private struct AssistantMessageRow: View {
    let message: AssistantMessage

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(message.role == .user ? "Вы" : "Ассистент")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(
                        message.role == .user ? .green : .blue
                    )
                Text(
                    message.timestamp.formatted(
                        date: .omitted,
                        time: .shortened
                    )
                )
                .font(.caption)
                .foregroundStyle(.tertiary)
            }
            Text(message.text)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private struct AssistantLiveRow: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Вы · распознавание")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.orange)
            Text(text + "▍")
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
