#include "CadView.h"
#include "WorkspaceTheme.h"
#include "WorkspaceWindow.h"
#include <QApplication>
#include <QDateTime>
#include <QDesktopServices>
#include <QLabel>
#include <QMenu>
#include <QPainter>
#include <QPlainTextEdit>
#include <QProgressBar>
#include <QPushButton>
#include <QScrollBar>
#include <QSettings>
#include <QTextBrowser>
#include <QTextDocument>
#include <QTimer>
#include <QUrl>
#include <cmath>

namespace {
QString markdown(const QString &text) {
    QTextDocument doc;
    doc.setDefaultFont(qApp->font());
    auto features = QTextDocument::MarkdownFeatures(QTextDocument::MarkdownDialectGitHub);
    features.setFlag(QTextDocument::MarkdownNoHTML);
    auto safe = text;
    safe.replace("![", "\\![");
    doc.setMarkdown(safe, features);
    auto html = doc.toHtml();
    const int body = html.indexOf("<body");
    if (body >= 0)
        html = html.mid(html.indexOf('>', body) + 1);
    return html.left(html.lastIndexOf("</body>"));
}
} // namespace

void WorkspaceWindow::applyAppearance() {
    QSettings p;
    applyWorkspaceTheme(p.value("v2/theme", "dark").toString(), p.value("v2/textSize", 12).toInt());
    setStyleSheet({});
    viewer->setLightTheme(lightWorkspaceTheme());
    renderChat();
    updateUsage();
}

void WorkspaceWindow::renderChat() {
    const bool follow = chat->verticalScrollBar()->value() >= chat->verticalScrollBar()->maximum() - 45;
    const int scroll = chat->verticalScrollBar()->value();
    const bool light = lightWorkspaceTheme();
    const auto text = light ? "#242428" : "#ededee";
    const auto muted = light ? "#73737c" : "#a1a1aa";
    const auto bubble = light ? "#ededf0" : "#303033";
    const auto card = light ? "#e7f0eb" : "#26352e";
    QString content = QString("<html><body style='color:%1;font-family:Segoe UI;'>").arg(text);
    auto message = [&](const QString &role, const QString &body, const QJsonObject &change = QJsonObject{}) {
        if (body.isEmpty())
            return;
        const bool user = role == "user";
        const auto author = user ? "You" : role == "assistant" ? "Codex" : "Notice";
        content += QString("<table width='100%' cellspacing='0' cellpadding='0'><tr><td "
                           "style='padding-top:20px;padding-bottom:6px;color:%1;font-size:11px;'><b>%2</b></"
                           "td></tr><tr><td bgcolor='%3' style='padding:%4px;'>%5</td></tr></table>")
                       .arg(muted, author, user ? bubble : (light ? "#f7f7f8" : "#1b1b1d"), user ? "12" : "0",
                            markdown(body));
        if (!change.isEmpty()) {
            QString parts;
            for (auto id : change.value("affected_components").toArray())
                parts += "<a href='component:" + id.toString().toHtmlEscaped() + "'>" +
                         id.toString().toHtmlEscaped() + "</a>  ";
            auto revision = change.value("result_revision_id").toString();
            content += QString("<table width='100%' cellpadding='12' cellspacing='0'><tr><td "
                               "bgcolor='%1'><b>Design updated</b><br>%2<br>Geometry and task scope "
                               "verified.<br><a href='revision:%3'>Restore revision %4</a></td></tr></table>")
                           .arg(card, parts, revision.toHtmlEscaped(), revision.left(8));
        }
    };
    auto messages = state.value("conversation").toObject().value("messages").toArray();
    for (auto item : messages) {
        auto m = item.toObject();
        message(m.value("role").toString(), m.value("content").toString(), m.value("change").toObject());
    }
    if (busy && !pendingUser.isEmpty()) {
        message("user", pendingUser);
        if (!liveAnswer.isEmpty())
            message("assistant", liveAnswer);
    }
    if (messages.isEmpty() && pendingUser.isEmpty())
        content +=
            QString("<p style='margin-top:28px;font-size:18px;'><b>What would you like to build?</b></p><p "
                    "style='color:%1;line-height:150%;'>Describe a part, include dimensions, or select "
                    "geometry to focus a change.</p><p style='color:%1;line-height:150%;'>Your conversation "
                    "stays with this project.</p>")
                .arg(muted);
    content += "</body></html>";
    chat->document()->setDefaultStyleSheet(QString("p {line-height:145%;} a {color:%1;} pre,code "
                                                   "{font-family:Consolas;background:%2;} li {margin:4px 0;}")
                                               .arg(light ? "#286654" : "#a5cebf", bubble));
    chat->document()->setDefaultFont(qApp->font());
    chat->setHtml(content);
    chat->verticalScrollBar()->setValue(follow ? chat->verticalScrollBar()->maximum() : scroll);
}

void WorkspaceWindow::updateTask(const QString &status, const QString &message) {
    currentTaskState = status;
    const bool running = status == "running" || status == "connecting" || status == "cancelling";
    taskProgress->setVisible(running);
    taskTitle->setText(status == "connecting"            ? "Connecting to Codex"
                       : status == "cancelling"          ? "Stopping task"
                       : status == "waiting_for_input"   ? "Your input is needed"
                       : status == "completed"           ? "Design updated"
                       : status == "completed_no_change" ? "Response complete"
                       : status == "cancelled"           ? "Task stopped"
                       : status == "failed"              ? "Task could not finish"
                       : status == "usage_limit"         ? "Usage limit reached"
                       : status == "disconnected"        ? "Codex is not connected"
                       : status == "idle"                ? "Ready"
                                                         : "Working on your design");
    taskActivity->setText(
        status == "completed" ? "Saved an accepted revision. Geometry and task scope checks passed."
        : status == "completed_no_change" ? "Response finished. No geometry revision was created."
                                          : message.left(220));
    if (running || status == "waiting_for_input") {
        if (!taskClock.isValid())
            taskClock.start();
        taskPulse->start();
    } else {
        taskPulse->stop();
        stopButton->hide();
    }
}

void WorkspaceWindow::updateUsage() {
    const auto provider = state.value("provider").toObject();
    const auto usage = provider.value("usage").toObject();
    const auto active = provider.value("active").toObject();
    QString text = active.value("connected").toBool()
                       ? (active.value("connection") == "api" ? "API usage" : "Allowance unavailable")
                       : "Sign in for usage";
    QStringList details;
    double remaining = -1;
    const auto windows = active.value("connected").toBool() ? usage.value("windows").toArray() : QJsonArray{};
    for (auto item : windows) {
        const auto w = item.toObject();
        const auto label = w.value("label").toString("Usage window");
        const auto percentage = w.value("remaining_percent").toDouble();
        auto row = label + " · " + QString::number(qRound(percentage)) + "% left";
        if (!w.value("bucket").toString().isEmpty() && w.value("bucket") != "codex")
            row = w.value("bucket_label").toString(w.value("bucket").toString()) + " · " + row;
        if (remaining < 0) {
            text = row;
            remaining = percentage;
        }
        const auto reset = w.value("resets_at").toInteger();
        if (reset > 0)
            row += " · resets " + QDateTime::fromSecsSinceEpoch(reset).toLocalTime().toString("ddd HH:mm");
        details << row;
    }
    if (!active.value("connected").toBool())
        details << "Connect your account in Settings to view available usage.";
    if (details.isEmpty())
        details << usage.value("message").toString("Allowance has not been reported by this connection.");
    auto tokens = state.value("conversation").toObject().value("token_usage").toObject();
    if (tokens.contains("totalTokens"))
        details << "Conversation tokens: " + QString::number(tokens.value("totalTokens").toInteger()) +
                       " · input " + QString::number(tokens.value("inputTokens").toInteger()) + " · output " +
                       QString::number(tokens.value("outputTokens").toInteger());
    tokenUsageLabel->setText(tokens.contains("totalTokens")
                                 ? QString::number(tokens.value("totalTokens").toInteger()) + " tokens"
                                 : QString());
    details << "Token counts are separate from your plan allowance.";
    usageBadge->setText(text);
    usageBadge->setToolTip(details.join('\n'));
    QPixmap icon(18, 18);
    icon.fill(Qt::transparent);
    QPainter painter(&icon);
    painter.setRenderHint(QPainter::Antialiasing);
    painter.setPen(QPen(QColor(lightWorkspaceTheme() ? "#c9c9d0" : "#53535a"), 2));
    painter.drawEllipse(QRectF(3, 3, 12, 12));
    painter.setPen(
        QPen(QColor(lightWorkspaceTheme() ? "#417662" : "#a6c6b6"), 2, Qt::SolidLine, Qt::RoundCap));
    if (remaining >= 0)
        painter.drawArc(QRectF(3, 3, 12, 12), 90 * 16, -int(remaining * 3.6 * 16));
    usageBadge->setIcon(QIcon(icon));
    refreshConnectionControls();
}

void WorkspaceWindow::refreshUsage() {
    if (busy)
        return;
    busy = true;
    sendButton->setEnabled(false);
    usageBadge->setText("Checking usage…");
    usageBadge->setEnabled(false);
    rpc->call("provider.usage", {}, [this](auto r, auto e) {
        busy = false;
        sendButton->setEnabled(!state.value("project").toObject().isEmpty() &&
                               !composer->toPlainText().trimmed().isEmpty());
        usageBadge->setEnabled(true);
        auto provider = state.value("provider").toObject();
        provider["usage"] = e.isEmpty() ? r.value("usage").toObject()
                                        : QJsonObject{{"available", false},
                                                      {"message", "Connect an account to check its usage."}};
        state["provider"] = provider;
        updateUsage();
    });
}
