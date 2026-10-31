#include "CadView.h"
#include "ConversationView.h"
#include "WorkspaceIcons.h"
#include "WorkspaceTheme.h"
#include "WorkspaceWindow.h"
#include "WorkspaceControls.h"
#include <QApplication>
#include <QComboBox>
#include <QDateTime>
#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QMenu>
#include <QLocale>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSettings>
#include <QScreen>
#include <QSignalBlocker>
#include <QSlider>
#include <QTimer>
#include <QToolButton>
#include <QVBoxLayout>

namespace {
QString effortPreference(const QString &provider, const QString &model) {
    return "v2/reasoningEffort/" + QString::fromLatin1(provider.toUtf8().toHex()) + "/" +
           QString::fromLatin1(model.toUtf8().toHex());
}
}

QString WorkspaceWindow::modelConnectionContext() const {
    const auto connection = state.value("provider").toObject();
    const auto id = connection.value("active").toObject().value("id").toString();
    if (connection.value("state") != "ready" || id.isEmpty()) return {};
    const auto runtime = state.value("runtime").toObject();
    return runtime.value("agent").toObject().value("id").toString() + "\n" + id + "\n" + runtime.value("executable").toString();
}

void WorkspaceWindow::ensureModelDiscovery() {
    if (!modelDiscoveryTimer || smoke) return;
    const auto context = modelConnectionContext();
    if (context.isEmpty()) { automaticModelContext.clear(); return; }
    if (context != automaticModelContext && !busy && !loading && !modelsLoading && !modelDiscoveryTimer->isActive())
        modelDiscoveryTimer->start(0);
}

void WorkspaceWindow::refreshEffortControl() {
    const auto provider = state.value("runtime").toObject().value("agent").toObject().value("id").toString();
    const auto active = state.value("provider").toObject().value("active").toObject();
    const auto model = models->currentData().toString();
    const auto metadata = models->currentData(Qt::UserRole + 1).toJsonObject();
    const auto control = metadata.value("reasoning_effort").toObject();
    QString caption = "Unavailable";
    QString explanation = control.value("message").toString("Refresh models to load reasoning effort capabilities.");
    const bool connected = state.value("provider").toObject().value("state") == "ready";
    const bool interactive = !busy && !loading && !imagePreflight && !modelsLoading;
    models->setProperty("refreshAvailable", connected && interactive);
    models->setEnabled(interactive);
    if (!interactive) {
        models->hidePopup();
        if (effortPopover) effortPopover->close();
    }
    const bool matches = !provider.isEmpty() && metadata.value("provider_id").toString() == provider &&
                         metadata.value("connection_id").toString() == active.value("id").toString();
    effortSelection.clear();
    bool supported = false;
    if (!connected) explanation = "Reasoning effort unavailable. Connect an agent provider first.";
    else if (modelsLoading) { caption = "Loading…"; explanation = "Loading model capabilities."; }
    else if (model.isEmpty()) explanation = "Choose a model to see its supported reasoning effort settings.";
    else if (!matches) explanation = "Reasoning effort unavailable for this connection. Refresh models.";
    else if (!models->property("effortCatalogueFailure").toString().isEmpty())
        explanation = "Model discovery failed. Refresh models to retry.\n" + models->property("effortCatalogueFailure").toString();
    else if (control.value("state") == "unsupported") caption = "Unsupported";
    else if (control.value("state") == "supported" && !control.value("options").toArray().isEmpty()) {
        supported = true;
        const auto options = control.value("options").toArray();
        const auto defaultId = control.value("default_id").toString();
        const auto remembered = QSettings().value(effortPreference(provider, model)).toString();
        QStringList ids;
        for (const auto &entry : options) ids << entry.toObject().value("id").toString();
        effortSelection = ids.contains(remembered) ? remembered : ids.contains(defaultId) ? defaultId : QString();
        caption = "Default";
        if (defaultId.isEmpty()) explanation += "\nNo usable default was reported. Leaving effort unset uses provider configuration.";
        if (!remembered.isEmpty() && !ids.contains(remembered)) explanation += "\nThe saved effort is not supported and has not been applied.";
        for (const auto &entry : options) {
            const auto option = entry.toObject();
            if (option.value("id").toString() == effortSelection) {
                caption = option.value("label").toString(effortSelection);
                explanation += "\n" + caption + ": " + option.value("description").toString();
            }
        }
    }
    models->setProperty("effortCaption", model.isEmpty() && !modelsLoading ? QString() : caption);
    models->setProperty("effortExplanation", explanation);
    models->setProperty("effortSupported", supported);
    models->setProperty("effortLabel", caption);
    models->setToolTip(models->currentText() + "\nReasoning effort: " + caption + "\n" + explanation);
    models->setAccessibleName("Model and reasoning effort: " + models->currentText() + " · " + caption);
    const auto unavailable = modelsLoading ? QString("Loading model capabilities.")
        : imagePreflight ? QString("Checking reference images before submission.")
        : busy ? QString("Available after the current operation finishes.")
        : loading ? QString("Loading the current project.") : QString();
    models->setAccessibleDescription(unavailable.isEmpty() ? explanation : unavailable);
    if (!unavailable.isEmpty()) models->setToolTip(models->toolTip() + "\n" + unavailable);
    models->updateGeometry(); models->update();
    if (effortPopover && (busy || effortPopover->property("context").toString() != modelConnectionContext() + "/" + model ||
                          effortPopover->property("control").toJsonObject() != control)) effortPopover->close();
}

void WorkspaceWindow::showEffortPopover() {
    if (!models->isEnabled()) return;
    if (effortPopover && effortPopover->isVisible()) { effortPopover->raise(); return; }
    refreshEffortControl();
    const auto provider = state.value("runtime").toObject().value("agent").toObject().value("id").toString();
    const auto model = models->currentData().toString();
    const auto control = models->currentData(Qt::UserRole + 1).toJsonObject().value("reasoning_effort").toObject();
    const auto options = control.value("options").toArray();
    QStringList ids; for (const auto &entry : options) ids << entry.toObject().value("id").toString();
    const auto defaultId = control.value("default_id").toString();
    const auto context = modelConnectionContext() + "/" + model;
    const bool supported = models->property("effortSupported").toBool();
    auto *panel = new WorkspacePopover(models, "effortPopover");
    effortPopover = panel; panel->setAttribute(Qt::WA_DeleteOnClose); panel->setObjectName("effortPopover");
    panel->setProperty("context", context); panel->setProperty("control", control);
    auto *layout = new QVBoxLayout(panel); layout->setContentsMargins(16, 14, 16, 14); layout->setSpacing(9);
    auto *heading = new QHBoxLayout;
    auto *caption = new QLabel(models->property("effortLabel").toString()); caption->setObjectName("currentEffort");
    caption->setTextFormat(Qt::PlainText); caption->setAlignment(Qt::AlignCenter);
    heading->addSpacing(28); heading->addWidget(caption, 1);
    auto *reset = new QToolButton; setWorkspaceIcon(reset, "undo"); reset->setObjectName("resetEffort");
    reset->setAccessibleName("Reset to provider default"); reset->setToolTip("Reset reasoning effort to the provider-reported default");
    reset->setFixedSize(32, 32);
    reset->setEnabled(supported && ids.contains(defaultId) && !busy && !imagePreflight && !modelsLoading); heading->addWidget(reset); layout->addLayout(heading);
    auto *modelLink = new QToolButton;
    const auto modelName = models->currentText().isEmpty() ? QString("Choose model") : models->currentText();
    modelLink->setText(modelLink->fontMetrics().elidedText(modelName, Qt::ElideRight, 250) + " ›");
    modelLink->setToolTip(modelName);
    modelLink->setToolButtonStyle(Qt::ToolButtonTextOnly); modelLink->setObjectName("effortModelLink");
    modelLink->setAccessibleName("Choose model: " + modelName); modelLink->setEnabled(!modelsLoading && !busy && !imagePreflight);
    layout->addWidget(modelLink, 0, Qt::AlignHCenter);
    connect(modelLink, &QToolButton::clicked, panel, [this, panel] {
        panel->dismiss(false); QTimer::singleShot(0, models, [this] { static_cast<ModelPicker *>(models)->showModelPopup(); });
    });
    auto *description = new QLabel; description->setObjectName("muted"); description->setWordWrap(true); description->setTextFormat(Qt::PlainText);
    QSlider *slider = nullptr;
    if (supported && control.value("presentation") == "steps" && ids.size() > 1 && ids.contains(effortSelection)) {
        slider = new QSlider(Qt::Horizontal); slider->setObjectName("effortSlider");
        slider->setRange(0, ids.size() - 1); slider->setSingleStep(1); slider->setPageStep(1);
        slider->setTickPosition(QSlider::TicksBelow); slider->setTickInterval(1); slider->setValue(ids.indexOf(effortSelection));
        slider->setAccessibleName("Reasoning effort"); slider->setCursor(Qt::PointingHandCursor); layout->addWidget(slider);
        slider->setEnabled(!busy && !imagePreflight && !modelsLoading);
    }
    QComboBox *choices = nullptr;
    if (supported && !slider) {
        choices = new QComboBox; choices->setAccessibleName("Reasoning effort"); choices->setPlaceholderText("Choose effort");
        for (const auto &entry : options) { const auto option = entry.toObject(); choices->addItem(option.value("label").toString(), option.value("id")); }
        choices->setCurrentIndex(ids.indexOf(effortSelection)); layout->addWidget(choices);
        choices->setEnabled(!busy && !imagePreflight && !modelsLoading);
    }
    layout->addWidget(description);
    auto showChoice = [this, caption, description, slider, choices, options, ids] {
        caption->setText(models->property("effortLabel").toString());
        const int index = ids.indexOf(effortSelection);
        description->setText(index >= 0 ? options[index].toObject().value("description").toString() : models->property("effortExplanation").toString());
        if (slider && index >= 0) { QSignalBlocker blocker(slider); slider->setValue(index); slider->setToolTip(caption->text()); slider->setAccessibleDescription(caption->text()); }
        if (choices) { QSignalBlocker blocker(choices); choices->setCurrentIndex(index); }
    };
    auto choose = [this, provider, model, context, ids, showChoice](int index) {
        if (busy || index < 0 || index >= ids.size() || modelConnectionContext() + "/" + models->currentData().toString() != context) return;
        QSettings().setValue(effortPreference(provider, model), ids[index]); refreshEffortControl(); showChoice();
    };
    if (slider) connect(slider, &QSlider::valueChanged, panel, choose);
    if (choices) connect(choices, &QComboBox::currentIndexChanged, panel, choose);
    connect(reset, &QToolButton::clicked, panel, [this, provider, model, context, showChoice] {
        if (busy || modelConnectionContext() + "/" + models->currentData().toString() != context) return;
        QSettings().remove(effortPreference(provider, model)); refreshEffortControl(); showChoice();
    });
    auto *refresh = new QToolButton; setWorkspaceIcon(refresh, "redo"); refresh->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    refresh->setText(modelsLoading ? "Loading models…" : "Refresh models"); refresh->setAccessibleName("Refresh models");
    refresh->setEnabled(models->property("refreshAvailable").toBool());
    refresh->setToolTip(refresh->isEnabled() ? "Refresh the reported model catalogue"
                        : "Connect a provider and wait for the current operation to finish."); layout->addWidget(refresh, 0, Qt::AlignRight);
    connect(refresh, &QToolButton::clicked, panel, [this, panel] { panel->dismiss(); discoverModels(true); });
    showChoice(); panel->setFixedWidth(320); panel->adjustSize();
    panel->showAnchored(slider ? static_cast<QWidget *>(slider)
                              : choices ? static_cast<QWidget *>(choices) : modelLink);
}

void WorkspaceWindow::applyAppearance() {
    QSettings preferences;
    applyWorkspaceTheme(preferences.value("v2/theme", "dark").toString(), preferences.value("v2/textSize", 14).toInt());
    setStyleSheet({});
    viewer->setLightTheme(lightWorkspaceTheme());
    refreshWorkspaceIcons(this);
    renderChat();
    updateUsage();
}

void WorkspaceWindow::receiveAssistant(const QJsonObject &event, bool complete) {
    const auto id = event.value("item_id").toString("message");
    if (!liveMessages.contains(id)) liveOrder << id;
    if (event.value("phase").isString()) livePhases[id] = event.value("phase").toString();
    if (complete) liveMessages[id] = event.value("message").toString();
    else liveMessages[id] += event.value("message").toString();
    QStringList replies;
    for (const auto &key : liveOrder)
        if (livePhases.value(key) != "commentary") replies << liveMessages.value(key);
    liveAnswer = replies.join("\n\n");
    if (livePhases.value(id) == "commentary")
        updateTask("running", liveMessages.value(id));
    if (!chatRefresh->isActive()) chatRefresh->start();
}

void WorkspaceWindow::renderChat() {
    auto messages = state.value("conversation").toObject().value("messages").toArray();
    if (busy && (!pendingUser.isEmpty() || !submittedAttachments.isEmpty())) {
        messages.append(QJsonObject{{"role", "user"}, {"content", pendingUser}, {"attachments", submittedAttachments}});
        QJsonArray events;
        for (const auto &message : currentActivity)
            events.append(QJsonObject{{"message", message}});
        messages.append(QJsonObject{{"role", "assistant"}, {"content", liveAnswer},
                                    {"agent", taskAgent},
                                   {"task_id", activeTaskId}, {"working", true},
                                   {"phase", currentTaskMessage}, {"activity", events},
                                   {"elapsed_seconds", taskClock.isValid() ? taskClock.elapsed() / 1000.0 : 0}});
    }
    chat->setMessages(messages, state.value("conversation").toObject().value("conversation_id").toString());
}

void WorkspaceWindow::updateTask(const QString &status, const QString &message) {
    currentTaskState = status;
    currentTaskMessage = message.left(220);
    if (QStringList{"connecting", "running", "cancelling", "waiting_for_input"}.contains(status)) {
        if (!taskClock.isValid())
            taskClock.start();
        taskPulse->start();
    } else {
        taskPulse->stop();

    }
    updateSendControl();
    if (!chatRefresh->isActive())
        chatRefresh->start();
}

void WorkspaceWindow::updateUsage() {
    const auto provider = state.value("provider").toObject();
    const auto active = provider.value("active").toObject();
    const auto runtime = state.value("runtime").toObject();
    const auto agent = runtime.value("agent").toObject();
    auto agentName = agent.value("display_name").toString().trimmed();
    if (agentName.isEmpty()) agentName = !runtime.contains("agent") && runtime.value("provider") == "Codex App Server"
                                           ? "Codex" : "Assistant";
    agentButton->setText(agentName);
    agentButton->setAccessibleName(agentName + " connection settings");
    const auto usage = provider.value("usage").toObject();
    const auto tokens = state.value("conversation").toObject().value("token_usage").toObject();
    QString text;
    QStringList details;
    if (active.value("connected").toBool())
        for (auto item : usage.value("windows").toArray()) {
            const auto window = item.toObject();
            auto row = window.value("label").toString("Usage window") + " · " +
                       QString::number(qRound(window.value("remaining_percent").toDouble())) + "% left";
            const auto reset = window.value("resets_at").toInteger();
            if (text.isEmpty()) text = row;
            if (reset > 0)
                row += " · resets " + QDateTime::fromSecsSinceEpoch(reset).toLocalTime().toString("ddd HH:mm");
            details << row;
        }
    if (tokens.contains("totalTokens")) {
        const auto total = QLocale().toString(tokens.value("totalTokens").toInteger());
        if (text.isEmpty()) { auto count=tokens.value("totalTokens").toInteger();text=count>=1000000?QString::number(count/1000000.0,'f',1)+"M tokens":count>=1000?QString::number(count/1000.0,'f',1)+"k tokens":total+" tokens"; }
        details << "Reported tokens: " + total;
        for (const auto &field : {qMakePair("inputTokens", "Input"), qMakePair("cachedInputTokens", "Cached input"),
                                  qMakePair("outputTokens", "Output")})
            if (tokens.contains(field.first))
                details << QString(field.second) + ": " + QLocale().toString(tokens.value(field.first).toInteger());
        details << "Reported token usage is separate from plan allowance and API cost.";
    }
    usageBadge->setText(text);
    usageBadge->setToolTip(details.join('\n'));
    usageBadge->setVisible(!text.isEmpty());
    setWorkspaceIcon(usageBadge, "clock-three");
    if (active.value("connected").toBool()) {
        auto initials = active.value("email").toString().section('@', 0, 0).left(2).toUpper();
        accountBadge->setIcon({});
        accountBadge->setText(initials.isEmpty() ? "U" : initials);
        accountBadge->setProperty("workspaceIcon", {});
        accountBadge->setProperty("connected", true);
    } else {
        accountBadge->setText({});
        setWorkspaceIcon(accountBadge, "user");
        accountBadge->setProperty("connected", false);
    }
    accountBadge->setToolTip("Account details");
    refreshConnectionControls();
}

void WorkspaceWindow::updateSendControl() {
    const bool stopping = currentTaskState == "cancelling";
    setWorkspaceIcon(sendButton, taskRunning ? "stop" : "arrow-up", true);
    sendButton->setAccessibleName(taskRunning ? (stopping ? "Stopping task" : "Stop task") : "Send request");
    sendButton->setToolTip(taskRunning ? (stopping ? "Stopping…" : "Stop task") : "Send · Enter (Shift+Enter for a new line)");
    const bool finished = QStringList{"completed", "completed_no_change", "cancelled", "failed", "usage_limit"}.contains(currentTaskState);
    sendButton->setEnabled(taskRunning ? !stopping && !finished : !busy && !state.value("conversation").toObject().isEmpty() &&
                            (!composer->toPlainText().trimmed().isEmpty() || !draftAttachments.isEmpty()));
}
