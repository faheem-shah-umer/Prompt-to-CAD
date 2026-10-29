#include "CadView.h"
#include "ConversationView.h"
#include "WorkspaceIcons.h"
#include "WorkspaceTheme.h"
#include "WorkspaceWindow.h"
#include <QApplication>
#include <QDateTime>
#include <QLabel>
#include <QLocale>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSettings>
#include <QTimer>

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
    if (busy && !pendingUser.isEmpty()) {
        messages.append(QJsonObject{{"role", "user"}, {"content", pendingUser}});
        QJsonArray events;
        for (const auto &message : currentActivity)
            events.append(QJsonObject{{"message", message}});
        messages.append(QJsonObject{{"role", "assistant"}, {"content", liveAnswer},
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
        stopButton->hide();
    }
    if (!chatRefresh->isActive())
        chatRefresh->start();
}

void WorkspaceWindow::updateUsage() {
    const auto provider = state.value("provider").toObject();
    const auto active = provider.value("active").toObject();
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
        if (text.isEmpty()) text = total + " tokens";
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
    accountBadge->setToolTip("Account and connection settings");
    refreshConnectionControls();
}
