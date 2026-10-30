#include "CadView.h"
#include "ConversationView.h"
#include "WorkspaceIcons.h"
#include "WorkspaceTheme.h"
#include "WorkspaceWindow.h"
#include <QApplication>
#include <QComboBox>
#include <QDateTime>
#include <QLabel>
#include <QMenu>
#include <QLocale>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSettings>
#include <QTimer>
#include <QToolButton>

namespace {
QString effortPreference(const QString &provider, const QString &model) {
    return "v2/reasoningEffort/" + QString::fromLatin1(provider.toUtf8().toHex()) + "/" +
           QString::fromLatin1(model.toUtf8().toHex());
}
}

void WorkspaceWindow::refreshEffortControl() {
    if (!effortButton) return;
    auto *menu = effortButton->menu();
    menu->clear(); effortSelection.clear();
    const auto provider = state.value("runtime").toObject().value("agent").toObject().value("id").toString();
    const auto active = state.value("provider").toObject().value("active").toObject();
    const auto model = models->currentData().toString();
    const auto metadata = models->currentData(Qt::UserRole + 1).toJsonObject();
    const auto control = metadata.value("reasoning_effort").toObject();
    const auto status = control.value("state").toString("unavailable");
    QString caption = "Effort unavailable";
    QString explanation = control.value("message").toString("Refresh models to load reasoning effort capabilities.");
    const bool connected = state.value("provider").toObject().value("state") == "ready";
    const bool matches = !provider.isEmpty() && metadata.value("provider_id").toString() == provider &&
                         metadata.value("connection_id").toString() == active.value("id").toString();
    bool supported = false;
    if (!connected) explanation = "Reasoning effort unavailable. Connect an agent provider first.";
    else if (modelsLoading) { caption = "Loading effort…"; explanation = "Loading model capabilities."; }
    else if (model.isEmpty()) explanation = "Choose a model to see its supported reasoning effort settings.";
    else if (!matches) explanation = "Reasoning effort unavailable for this connection. Refresh models.";
    else if (!models->property("effortCatalogueFailure").toString().isEmpty())
        explanation = "Reasoning effort unavailable after model discovery failed. Refresh models to retry.\n" + models->property("effortCatalogueFailure").toString();
    else if (status == "unsupported") caption = "Effort unsupported";
    else if (status == "supported" && !control.value("options").toArray().isEmpty()) {
        supported = true;
        const auto options = control.value("options").toArray();
        const auto defaultId = control.value("default_id").toString();
        QSettings preferences;
        const auto remembered = preferences.value(effortPreference(provider, model)).toString();
        QStringList ids;
        for (const auto &entry : options) ids << entry.toObject().value("id").toString();
        effortSelection = ids.contains(remembered) ? remembered : ids.contains(defaultId) ? defaultId : QString();
        caption = "Effort: default";
        if (defaultId.isEmpty()) explanation += "\nThe provider did not report a usable default; leaving this unset uses its configuration.";
        if (!remembered.isEmpty() && !ids.contains(remembered)) explanation += "\nThe saved choice is not supported by this model catalogue; it has not been applied.";
        for (const auto &entry : options) {
            const auto option = entry.toObject();
            const auto id = option.value("id").toString();
            const auto label = option.value("label").toString(id);
            auto *action = menu->addAction(label + (id == defaultId ? " · default" : ""));
            action->setCheckable(true); action->setChecked(id == effortSelection);
            action->setToolTip(option.value("description").toString());
            action->setStatusTip(option.value("description").toString());
            if (id == effortSelection) {
                caption = "Effort: " + label;
                explanation += "\n" + label + ": " + option.value("description").toString();
            }
            connect(action, &QAction::triggered, this, [this, provider, model, id] {
                if (busy || models->currentData().toString() != model ||
                    state.value("runtime").toObject().value("agent").toObject().value("id").toString() != provider) return;
                QSettings preferences; preferences.setValue(effortPreference(provider, model), id);
                refreshEffortControl();
            });
        }
    }
    menu->setToolTipsVisible(true);
    effortButton->setText(effortButton->fontMetrics().elidedText(caption, Qt::ElideRight, 132));
    effortButton->setToolTip("Reasoning effort · " + caption + "\n" + explanation);
    effortButton->setAccessibleName("Reasoning effort: " + caption);
    effortButton->setAccessibleDescription(explanation);
    effortButton->setEnabled(supported && !busy && !imagePreflight && !modelsLoading);
}

void WorkspaceWindow::applyAppearance() {
    QSettings preferences;
    applyWorkspaceTheme(preferences.value("v2/theme", "dark").toString(), preferences.value("v2/textSize", 12).toInt());
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
