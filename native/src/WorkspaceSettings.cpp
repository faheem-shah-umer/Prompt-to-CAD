#include "CadView.h"
#include "WorkspaceWindow.h"
#include <QApplication>
#include <QPixmap>
#include <QAction>
#include <QButtonGroup>
#include <QCheckBox>
#include <QGraphicsOpacityEffect>
#include <QParallelAnimationGroup>
#include <QPropertyAnimation>
#include <QComboBox>
#include <QDesktopServices>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QFileDialog>
#include <QFormLayout>
#include <QFrame>
#include <QLabel>
#include <QLineEdit>
#include <QLocale>
#include <QMessageBox>
#include <QListWidget>
#include <QPushButton>
#include <QScreen>
#include <QScrollArea>
#include <QSettings>
#include <QSignalBlocker>
#include <QStackedWidget>
#include <QTimer>
#include <QJsonDocument>
#include <QStyle>
#include "WorkspaceIcons.h"
#include "WorkspaceTheme.h"
#include <QToolButton>
#include <QUrl>
#include <QVBoxLayout>

namespace {
QLabel *label(const QString &text, const QString &name = "settingsCaption") {
    auto *l = new QLabel(text);
    l->setObjectName(name);
    l->setWordWrap(true);
    l->setTextFormat(Qt::PlainText);
    return l;
}
QPushButton *action(const QString &text, QBoxLayout *layout, std::function<void()> callback) {
    auto *b = new QPushButton(text);
    layout->addWidget(b);
    QObject::connect(b, &QPushButton::clicked, std::move(callback));
    return b;
}
QVBoxLayout *card(QVBoxLayout *parent, const QString &title) {
    auto *frame = new QFrame;
    frame->setObjectName("settingsCard");
    auto *layout = new QVBoxLayout(frame);
    layout->setContentsMargins(0, 24, 0, 24);
    layout->setSpacing(16);
    layout->addWidget(label(title, "settingsCardTitle"));
    parent->addWidget(frame);
    return layout;
}
void repolish(QWidget *widget) {
    widget->style()->unpolish(widget);
    widget->style()->polish(widget);
}
struct ProviderCopy { const char *id, *name, *tagline, *detail; };
const ProviderCopy providerCopy[] = {
    {"codex", "Codex", "OpenAI · Sign in with ChatGPT",
     "Uses your ChatGPT plan allowance. Requires the Codex CLI on this PC."},
    {"claude", "Claude", "Anthropic · API key",
     "Billed per token by Anthropic. Requires Claude Code on this PC."},
};
// A selectable card: labels ignore the mouse so the whole surface acts as one button.
QPushButton *providerCard(const ProviderCopy &copy, QButtonGroup *group) {
    auto *button = new QPushButton;
    button->setObjectName("providerCard");
    button->setProperty("providerId", copy.id);
    button->setCheckable(true);
    button->setAccessibleName(QString(copy.name) + " · " + copy.tagline);
    button->setMinimumHeight(128);
    button->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
    auto *layout = new QVBoxLayout(button);
    layout->setContentsMargins(18, 16, 18, 16);
    layout->setSpacing(6);
    auto *header = new QHBoxLayout;
    auto *name = label(copy.name, "providerName");
    header->addWidget(name, 1);
    auto *badge = label({}, "providerBadge");
    badge->setWordWrap(false);
    header->addWidget(badge);
    layout->addLayout(header);
    layout->addWidget(label(copy.tagline, "providerTagline"));
    layout->addStretch();
    layout->addWidget(label(copy.detail, "providerDetail"));
    for (auto *child : button->findChildren<QLabel *>()) child->setAttribute(Qt::WA_TransparentForMouseEvents);
    group->addButton(button);
    return button;
}
void setProviderBadge(QWidget *scope, const QString &provider, const QString &text) {
    for (auto *card : scope->findChildren<QPushButton *>("providerCard"))
        if (card->property("providerId").toString() == provider)
            if (auto *badge = card->findChild<QLabel *>("providerBadge")) badge->setText(text);
}
// Entering a slide: brief fade with a short horizontal travel in the direction of navigation.
void revealPage(QWidget *page, int direction) {
    auto *effect = new QGraphicsOpacityEffect(page);
    page->setGraphicsEffect(effect);
    auto *motion = new QParallelAnimationGroup(page);
    auto *fade = new QPropertyAnimation(effect, "opacity", motion);
    fade->setDuration(220); fade->setStartValue(0.0); fade->setEndValue(1.0);
    fade->setEasingCurve(QEasingCurve::OutCubic);
    auto *travel = new QPropertyAnimation(page, "pos", motion);
    const auto end = page->pos();
    travel->setDuration(220); travel->setStartValue(end + QPoint(24 * direction, 0)); travel->setEndValue(end);
    travel->setEasingCurve(QEasingCurve::OutCubic);
    motion->addAnimation(fade); motion->addAnimation(travel);
    QObject::connect(motion, &QAbstractAnimation::finished, page, [page, end] { page->move(end); page->setGraphicsEffect(nullptr); });
    motion->start(QAbstractAnimation::DeleteWhenStopped);
}
} // namespace

void WorkspaceWindow::refreshConnectionControls() {
    refreshEffortControl();
    ensureModelDiscovery();
    auto connection = state.value("provider").toObject();
    auto active = connection.value("active").toObject();
    const bool ready = connection.value("state") == "ready";
    const bool signingIn = connection.value("signing_in").toBool();
    const auto providerId = connection.value("provider_id").toString("codex");
    const auto providers = connection.value("providers").toObject();
    const bool codexReady = ready && providerId == "codex";
    const bool claudeReady = ready && providerId == "claude";
    const auto claudeExecutable = state.value("runtime").toObject().value("executables").toObject().value("claude").toString();
    const auto claudeRuntimeText = claudeExecutable.isEmpty()
        ? QString("Not found yet. Install it, or set its path in Settings → Advanced.")
        : "Detected · " + QDir::toNativeSeparators(claudeExecutable);
    if (onboardingDialog) {
        if (auto *start = onboardingDialog->findChild<QPushButton *>("onboardingConnect")) start->setEnabled(!busy && !signingIn);
        if (auto *start = onboardingDialog->findChild<QPushButton *>("onboardingClaudeConnect")) start->setEnabled(!busy && !signingIn);
        if (auto *runtime = onboardingDialog->findChild<QLabel *>("onboardingClaudeRuntime")) runtime->setText(claudeRuntimeText);
        if (auto *status = onboardingDialog->findChild<QLabel *>("onboardingStatus")) status->setText(signingIn ? "Finish authorization in your browser." : connection.value("error").toString());
        if (ready) onboardingDialog->accept();
    }
    const bool canRefresh = ready && !busy && !loading && !modelsLoading && !imagePreflight;
    if (auto *refresh = findChild<QAction *>("refreshModelsAction")) refresh->setEnabled(canRefresh);
    if (!settingsDialog) return;
    auto shown = settingsDialog->property("providerShown").toString();
    if (shown.isEmpty()) shown = providerId;
    for (auto *card : settingsDialog->findChildren<QPushButton *>("providerCard")) {
        const auto id = card->property("providerId").toString();
        QSignalBlocker block(card);
        card->setChecked(id == shown);
        card->setEnabled(!busy || id == shown);
        const bool hasSaved = providers.value(id).toObject().value("saved").toBool();
        setProviderBadge(settingsDialog, id, id == providerId && ready ? "●  Active"
                                           : id == providerId ? "Selected · not connected"
                                           : hasSaved ? "Saved" : "Not connected");
    }
    if (auto *panel = settingsDialog->findChild<QWidget *>("codexPanel")) panel->setVisible(shown == "codex");
    if (auto *panel = settingsDialog->findChild<QWidget *>("claudePanel")) panel->setVisible(shown == "claude");
    if (auto *info = settingsDialog->findChild<QLabel *>("claudeInfo")) {
        const bool hasSaved = providers.value("claude").toObject().value("saved").toBool();
        info->setText(claudeReady ? "✓  Connected" : hasSaved ? "Saved · select to use" : "Not connected");
        info->setStyleSheet("color:" + (claudeReady ? workspaceColors().success : workspaceColors().secondary).name());
    }
    if (auto *keyState = settingsDialog->findChild<QLabel *>("claudeKeyState")) {
        QString text = "Not added";
        for (const auto &value : connection.value("accounts").toArray()) {
            const auto item = value.toObject();
            if (item.value("connection") == "anthropic" && item.value("connected").toBool())
                text = (claudeReady && item.value("id") == active.value("id") ? "In use · " : "Saved · ") + item.value("label").toString();
        }
        keyState->setText(text);
    }
    if (auto *runtimeState = settingsDialog->findChild<QLabel *>("claudeRuntimeState")) runtimeState->setText(claudeRuntimeText);
    if (auto *billing = settingsDialog->findChild<QLabel *>("claudeBilling"))
        billing->setText("Anthropic API · per token, separate from any ChatGPT or Claude.ai plan");
    if (auto *entry = settingsDialog->findChild<QWidget *>("claudeKeyEntry")) entry->setVisible(!claudeReady);
    if (auto *button = settingsDialog->findChild<QPushButton *>("claudeConnect")) button->setEnabled(!busy);
    if (auto *button = settingsDialog->findChild<QPushButton *>("claudeDisconnect")) button->setVisible(claudeReady);
    if (auto *button = settingsDialog->findChild<QPushButton *>("installClaude")) button->setVisible(claudeExecutable.isEmpty());
    if (auto *refresh = settingsDialog->findChild<QPushButton *>("refreshModelsButton")) {
        refresh->setEnabled(canRefresh);
        refresh->setText(modelsLoading ? "Loading models…" : "Refresh models");
        refresh->setToolTip(!ready ? "Connect a provider to refresh models."
                           : !canRefresh ? "Wait for the current operation to finish." : "Refresh the reported model catalogue");
    }
    if (auto *create = settingsDialog->findChild<QPushButton *>("newChatGPTRegistration"))create->setEnabled(!busy&&!signingIn);
    if (auto *start = settingsDialog->findChild<QPushButton *>("connectChatGPT")) {
        start->setVisible(!codexReady || active.value("connection") != "chatgpt");
        start->setText(codexReady && active.value("connection") == "chatgpt" ? "Reconnect ChatGPT" : "Continue with ChatGPT");
        start->setEnabled(!busy && !signingIn);
    }
    if (auto *info = settingsDialog->findChild<QLabel *>("connectionInfo")) {
        QString text = signingIn ? "Waiting for browser authorization"
                       : codexReady ? "✓  Connected"
                       : providerId != "codex" && providers.value("codex").toObject().value("saved").toBool() ? "Saved · select to use"
                       : connection.value("error").toString().isEmpty() ? "Not connected" : "Reconnect needed";
        const auto tint = codexReady ? workspaceColors().success : connection.value("error").toString().isEmpty()
            ? workspaceColors().secondary : workspaceColors().danger;
        info->setStyleSheet("color:" + tint.name());
        info->setText(text);
    }
    if (auto *error = settingsDialog->findChild<QLabel *>("connectionError")) {
        const auto message = connection.value("error").toString();
        error->setText(message.isEmpty() ? QString() : "⚠  Your saved connection needs attention. " + message);
        error->setVisible(!message.isEmpty());
    }
    if (auto *guidance = settingsDialog->findChild<QLabel *>("connectionGuidance"))
        guidance->setVisible(!codexReady && connection.value("error").toString().isEmpty());
    auto setDetail = [this](const QString &name, const QString &value) {
        if (auto *item = settingsDialog->findChild<QLabel *>(name)) item->setText(value);
    };
    setDetail("connectionAccount", active.value("name").toString(active.isEmpty() ? "No account connected" : "Connected account"));
    setDetail("connectionEmail", active.value("email").toString("Not reported"));
    const auto workspaceName = active.value("workspace").toString();
    setDetail("connectionWorkspace", workspaceName.isEmpty() || workspaceName.startsWith("Workspace name not reported")
        ? "Not reported by provider" : workspaceName);
    setDetail("connectionBilling", connection.value("billing").toString("No billing connection"));
    if (auto *identity = settingsDialog->findChild<QWidget *>("connectionIdentity")) identity->setVisible(codexReady);
    if (auto *summary = settingsDialog->findChild<QLabel *>("catalogueSummary")) {
        const auto failure = models->property("effortCatalogueFailure").toString();
        summary->setText(modelsLoading ? "Loading model catalogue…"
            : !ready ? "Connect an account to discover models."
            : !failure.isEmpty() ? "Model discovery failed. Refresh to retry."
            : QString::number(models->count()) + " model(s) listed · access is checked when a request runs.");
    }
    if (auto *usage = settingsDialog->findChild<QWidget *>("reportedUsageRows")) {
        auto *rows = qobject_cast<QFormLayout *>(usage->layout());
        while (rows->rowCount()) rows->removeRow(0);
        const auto tokens = state.value("conversation").toObject().value("token_usage").toObject();
        bool reported = false;
        if (auto *total = settingsDialog->findChild<QLabel *>("usageTotal")) {
            total->setText(tokens.contains("totalTokens") ? QLocale().toString(tokens.value("totalTokens").toInteger()) : QString());
            total->setVisible(tokens.contains("totalTokens"));
        }
        if (auto *caption = settingsDialog->findChild<QLabel *>("usageTotalCaption"))
            caption->setText(tokens.contains("totalTokens") ? "Reported conversation tokens"
                : ready ? "Usage appears when the provider reports it." : "Provider usage is unavailable while disconnected.");
        for (const auto &field : {qMakePair("inputTokens", "Input"), qMakePair("cachedInputTokens", "Cached input"),
                                 qMakePair("outputTokens", "Output")})
            if (tokens.contains(field.first)) {
                auto *count = label(QLocale().toString(tokens.value(field.first).toInteger()), "usageValue");
                count->setAlignment(Qt::AlignRight); rows->addRow(field.second, count); reported = true;
            }
        for (const auto &value : connection.value("usage").toObject().value("windows").toArray()) {
            const auto window = value.toObject();
            if (!window.contains("remaining_percent")) continue;
            rows->addRow(window.value("label").toString("Provider allowance"),
                         label(QString::number(qRound(window.value("remaining_percent").toDouble())) + "% remaining"));
            reported = true;
        }
        usage->setVisible(reported);
    }
    if (auto *cancel = settingsDialog->findChild<QPushButton *>("cancelSignIn"))
        cancel->setVisible(signingIn);
    if (auto *disconnect = settingsDialog->findChild<QPushButton *>("disconnectAccount"))
        disconnect->setVisible(codexReady && active.value("connected").toBool());
    if(auto *panel=settingsDialog->findChild<QWidget *>("previousRegistrations")) {
        const auto signature=QJsonDocument(connection).toJson(QJsonDocument::Compact);
        if(panel->property("signature").toByteArray()!=signature) {
            panel->setProperty("signature",signature);
            auto *layout=qobject_cast<QVBoxLayout *>(panel->layout());
            while(auto *item=layout->takeAt(0)){delete item->widget();delete item;}
            int count=0;
            for(auto value:connection.value("accounts").toArray()) {
                auto item=value.toObject();const auto id=item.value("id").toString();
                if(item.value("connection")!="chatgpt"||item.value("id")==connection.value("preferred")||item.value("id")==active.value("id"))continue;
                ++count;auto *row=new QWidget;auto *line=new QHBoxLayout(row);line->setContentsMargins(0,4,0,4);auto *name=label(item.value("label").toString());line->addWidget(name,1);
                auto *use=new QPushButton("Use");line->addWidget(use);connect(use,&QPushButton::clicked,this,[this,id]{call("provider.select",{{"account_id",id}},[this](auto){call("v2.state");});});
                auto *remove=new QPushButton;setWorkspaceIcon(remove, "trash");remove->setFixedSize(32,32);remove->setProperty("workspaceIconOnly",true);remove->setAccessibleName("Remove saved connection "+item.value("label").toString());remove->setToolTip("Remove saved connection");line->addWidget(remove);
                connect(remove,&QPushButton::clicked,this,[this,id,label=item.value("label").toString()]{
                    if(busy)return;
                    if(QMessageBox::question(settingsDialog,"Remove saved connection","Remove “"+label+"” from this application? We will attempt to revoke its session. The registered app must be removed separately in ChatGPT Settings.")!=QMessageBox::Yes)return;
                    call("provider.forget",{{"account_id",id}},[this](auto result){state["provider"]=result;updateUsage();notify(result.value("message").toString(),result.value("remote_revocation_confirmed").toBool()?"info":"warning");});
                });
                layout->addWidget(row);
            }
            if(!count)layout->addWidget(label("No previous connections saved."));
        }
    }
    if (auto *usage = settingsDialog->findChild<QLabel *>("usageInfo"))
        usage->setText(usageBadge->toolTip().isEmpty()
                           ? "Token usage appears after a model request reports it."
                           : usageBadge->toolTip());
}

void WorkspaceWindow::account() {
    if (settingsDialog) {
        settingsDialog->showNormal();
        settingsDialog->raise();
        settingsDialog->activateWindow();
        return;
    }
    if (focusOpenDialog()) return;
    auto *dialog = new QDialog(this);
    settingsDialog = dialog;
    dialog->setObjectName("workspaceSettings");
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowTitle("Settings · Prompt to CAD");
    dialog->resize(qMin(1280, dialog->screen()->availableGeometry().width() - 64),
                   qBound(500, dialog->screen()->availableGeometry().height() - 80, 880));
    dialog->setMinimumSize(660, 500);
    auto *outer = new QVBoxLayout(dialog);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);
    auto *header = new QFrame;
    header->setObjectName("settingsHeader");
    auto *headerLayout = new QHBoxLayout(header);
    headerLayout->setContentsMargins(24, 14, 24, 14);
    headerLayout->addWidget(label("Settings", "sectionTitle"));
    outer->addWidget(header);
    auto *body = new QHBoxLayout;
    body->setSpacing(0);
    auto *sections = new QListWidget;
    sections->setObjectName("settingsNavigation");
    sections->addItems({"AI connection", "Appearance", "Projects", "CAD display", "Advanced"});
    auto *sidebar = new QWidget;
    sidebar->setObjectName("settingsSidebar");
    sidebar->setFixedWidth(224);
    auto *settingsNav = new QVBoxLayout(sidebar);
    settingsNav->setContentsMargins(16, 20, 16, 24);
    settingsNav->setSpacing(12);
    settingsNav->addWidget(sections, 1);
    auto *brand = new QLabel; brand->setPixmap(QPixmap(":/brand/app-icon.png").scaled(36, 36, Qt::KeepAspectRatio, Qt::SmoothTransformation));
    brand->setAccessibleName("Prompt to CAD logo"); settingsNav->addWidget(brand);
    settingsNav->addWidget(label("Prompt to CAD", "settingsAccountName"));
    settingsNav->addWidget(label("Version " + QCoreApplication::applicationVersion()));
    body->addWidget(sidebar);
    auto *pages = new QStackedWidget;
    body->addWidget(pages, 1);
    outer->addLayout(body, 1);
    auto page = [&](const QString &title, const QString &description) {
        auto *scroll = new QScrollArea;
        scroll->setObjectName("settingsPage");
        scroll->setFrameShape(QFrame::NoFrame);
        scroll->setWidgetResizable(true);
        scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
        auto *contents = new QWidget;
        auto *layout = new QVBoxLayout(contents);
        layout->setContentsMargins(48, 32, 48, 24);
        layout->setSpacing(12);
        layout->addWidget(label(title, "pageTitle"));
        layout->addWidget(label(description));
        scroll->setWidget(contents);
        pages->addWidget(scroll);
        return layout;
    };
    auto connection = state.value("provider").toObject();
    auto *ai = page("AI connection", "Choose the agent that models with you, then connect your own account. "
                                     "Each provider keeps its saved connection, so you can switch back at any time.");
    auto *providerGroup = new QButtonGroup(dialog);
    providerGroup->setExclusive(true);
    auto *chooser = new QHBoxLayout;
    chooser->setSpacing(16);
    for (const auto &copy : providerCopy) chooser->addWidget(providerCard(copy, providerGroup));
    ai->addSpacing(8);
    ai->addLayout(chooser);
    dialog->setProperty("providerShown", connection.value("provider_id").toString("codex"));
    connect(providerGroup, &QButtonGroup::buttonClicked, dialog, [this, dialog](QAbstractButton *button) {
        const auto provider = button->property("providerId").toString();
        dialog->setProperty("providerShown", provider);
        const auto current = state.value("provider").toObject();
        const bool saved = current.value("providers").toObject().value(provider).toObject().value("saved").toBool();
        if (!busy && saved && provider != current.value("provider_id").toString())
            call("provider.use", {{"provider_id", provider}}, [this](auto) { call("v2.state"); });
        refreshConnectionControls();
    });
    auto *codexPanel = new QWidget;
    codexPanel->setObjectName("codexPanel");
    auto *codexLayout = new QVBoxLayout(codexPanel);
    codexLayout->setContentsMargins(0, 0, 0, 0);
    codexLayout->setSpacing(12);
    ai->addWidget(codexPanel);
    auto *claudePanel = new QWidget;
    claudePanel->setObjectName("claudePanel");
    auto *claudeLayout = new QVBoxLayout(claudePanel);
    claudeLayout->setContentsMargins(0, 32, 0, 24);
    claudeLayout->setSpacing(20);
    ai->addWidget(claudePanel);
    {
        auto *claudeHeader = new QHBoxLayout;
        claudeHeader->addWidget(label("Claude", "settingsCardTitle"), 1);
        auto *status = label({}, "claudeInfo");
        status->setWordWrap(false);
        claudeHeader->addWidget(status);
        claudeLayout->addLayout(claudeHeader);
        claudeLayout->addWidget(label("Runs through Claude Code on this PC with your own Anthropic API key. Usage is billed "
                                      "per token by Anthropic; a Claude.ai subscription is not used."));
        auto *divider = new QFrame;
        divider->setObjectName("sectionRule");
        divider->setFrameShape(QFrame::HLine);
        claudeLayout->addWidget(divider);
        auto *facts = new QFormLayout;
        facts->setContentsMargins(0, 0, 0, 0);
        facts->setRowWrapPolicy(QFormLayout::WrapLongRows);
        facts->setVerticalSpacing(20);
        facts->setHorizontalSpacing(24);
        for (const auto &row : {qMakePair("API key", "claudeKeyState"), qMakePair("Claude Code", "claudeRuntimeState"),
                                qMakePair("Billing", "claudeBilling")}) {
            auto *caption = label(row.first);
            caption->setMinimumWidth(144);
            auto *value = label({}, row.second);
            value->setTextInteractionFlags(Qt::TextSelectableByMouse | Qt::TextSelectableByKeyboard);
            facts->addRow(caption, value);
        }
        claudeLayout->addLayout(facts);
        auto *entry = new QWidget;
        entry->setObjectName("claudeKeyEntry");
        auto *entryLayout = new QVBoxLayout(entry);
        entryLayout->setContentsMargins(0, 0, 0, 0);
        entryLayout->setSpacing(12);
        auto *claudeKey = new QLineEdit;
        claudeKey->setObjectName("claudeKey");
        claudeKey->setEchoMode(QLineEdit::Password);
        claudeKey->setPlaceholderText("sk-ant-…");
        claudeKey->setAccessibleName("Anthropic API key");
        entryLayout->addWidget(claudeKey);
        auto *entryRow = new QHBoxLayout;
        auto *validate = action("Validate and connect", entryRow, [this, claudeKey, dialog] {
            const auto value = claudeKey->text().trimmed();
            if (value.isEmpty()) { claudeKey->setFocus(); return; }
            claudeKey->clear();
            dialog->setProperty("providerShown", "claude");
            call("provider.anthropic_key", {{"key", value}}, [this](auto) { call("v2.state"); });
        });
        validate->setObjectName("claudeConnect");
        connect(claudeKey, &QLineEdit::returnPressed, validate, &QPushButton::click);
        action("Get an API key ↗", entryRow, [] { QDesktopServices::openUrl(QUrl("https://console.anthropic.com/settings/keys")); })
            ->setObjectName("quietButton");
        entryRow->addStretch();
        entryLayout->addLayout(entryRow);
        entryLayout->addWidget(label("The key is checked without running a model and stored in Windows-protected storage, "
                                     "outside your projects."));
        claudeLayout->addWidget(entry);
        auto *claudeActions = new QHBoxLayout;
        action("Install Claude Code ↗", claudeActions, [] { QDesktopServices::openUrl(QUrl("https://code.claude.com/docs/en/setup")); })
            ->setObjectName("installClaude");
        action("Disconnect", claudeActions, [this] {
            call("provider.disconnect", {}, [this](auto r) {
                const auto message = r.value("message").toString();
                call("v2.state", {}, [this, message](auto) { activity->setText(message); });
            });
        })->setObjectName("claudeDisconnect");
        claudeActions->addStretch();
        claudeLayout->addLayout(claudeActions);
    }
    auto *mode = new QComboBox(dialog);
    mode->setObjectName("connectionMode");
    mode->addItem("ChatGPT plan · Codex", "chatgpt");
    mode->addItem("OpenAI API key · separate billing", "api");
    mode->hide();
    auto *connectionSection = new QFrame;
    auto *accountCard = new QVBoxLayout(connectionSection);
    accountCard->setContentsMargins(0, 32, 0, 24);
    accountCard->setSpacing(20);
    codexLayout->addWidget(connectionSection);
    auto *connectionHeader = new QHBoxLayout;
    connectionHeader->addWidget(label("Codex", "settingsCardTitle"), 1);
    auto *info = label({}, "connectionInfo");
    info->setTextInteractionFlags(Qt::TextSelectableByMouse);
    connectionHeader->addWidget(info);
    accountCard->addLayout(connectionHeader);
    accountCard->addWidget(label("Uses the installed Codex App Server runtime."));
    auto *rule = new QFrame;
    rule->setObjectName("sectionRule");
    rule->setFrameShape(QFrame::HLine);
    accountCard->addWidget(rule);
    auto *connectionError = label({}, "connectionError");
    connectionError->hide();
    accountCard->addWidget(connectionError);
    auto *guidance = label("Connect Codex to use the CAD agent. Authorize your eligible ChatGPT account in your browser. You can inspect local CAD without connecting.", "connectionGuidance");
    guidance->hide();
    accountCard->addWidget(guidance);
    auto *identityRows = new QWidget;
    identityRows->setObjectName("connectionIdentity");
    auto *details = new QFormLayout(identityRows);
    details->setContentsMargins(0, 0, 0, 0);
    details->setRowWrapPolicy(QFormLayout::WrapLongRows);
    details->setVerticalSpacing(24);
    details->setHorizontalSpacing(24);
    auto *identity = new QWidget;
    auto *identityLayout = new QVBoxLayout(identity);
    identityLayout->setContentsMargins(0, 0, 0, 0);
    identityLayout->setSpacing(4);
    auto *accountName = label({}, "connectionAccount");
    accountName->setStyleSheet("font-weight:600");
    accountName->setTextInteractionFlags(Qt::TextSelectableByMouse | Qt::TextSelectableByKeyboard);
    identityLayout->addWidget(accountName);
    auto *email = label({}, "connectionEmail");
    email->setTextInteractionFlags(Qt::TextSelectableByMouse | Qt::TextSelectableByKeyboard);
    identityLayout->addWidget(email);
    auto *accountLabel = label("Account");
    accountLabel->setMinimumWidth(144);
    details->addRow(accountLabel, identity);
    for (const auto &entry : {qMakePair("Workspace", "connectionWorkspace"), qMakePair("Billing", "connectionBilling")}) {
        auto *value = label({}, entry.second); value->setTextFormat(Qt::PlainText);
        value->setTextInteractionFlags(Qt::TextSelectableByMouse | Qt::TextSelectableByKeyboard);
        details->addRow(entry.first, value);
    }
    accountCard->addWidget(identityRows);
    auto *plan = new QWidget;
    auto *planLayout = new QVBoxLayout(plan);
    planLayout->setContentsMargins(0, 0, 0, 0);
    auto *connectRow = new QHBoxLayout;
    action("Continue with ChatGPT", connectRow, [this] { beginSignIn(); })->setObjectName("connectChatGPT");
    auto *cancelSignIn = action("Cancel sign-in", connectRow, [this] {
        call("provider.cancel_login", {}, [this](auto) { call("v2.state"); });
    });
    cancelSignIn->setObjectName("cancelSignIn");
    action("Connect a different account", connectRow, [this] {
        if(QMessageBox::question(settingsDialog,"Connect a new account","Create a new Prompt to CAD registration? Your current connection remains active until authorization succeeds. Old registered apps can be removed in ChatGPT Settings.") == QMessageBox::Yes)beginSignIn({},true);
    })->setObjectName("newChatGPTRegistration");
    connectRow->addStretch();
    planLayout->addLayout(connectRow);
    auto *accountActions = new QHBoxLayout;
    accountActions->addWidget(plan, 1);
    accountActions->addStretch();
    accountCard->addLayout(accountActions);
    auto *api = new QWidget;
    auto *apiLayout = new QVBoxLayout(api);
    apiLayout->setContentsMargins(0, 0, 0, 0);
    auto *key = new QLineEdit;
    key->setEchoMode(QLineEdit::Password);
    key->setPlaceholderText("Your API key");
    apiLayout->addWidget(key);
    auto *apiRow = new QHBoxLayout;
    action("Validate and connect", apiRow, [this, key] {
        auto value = key->text();
        key->clear();
        call("provider.api_key", {{"key", value}},
             [this](auto) { call("v2.state", {}, [this](auto) { discoverModels(); }); });
    })->setObjectName("primaryButton");
    apiRow->addStretch();
    apiLayout->addLayout(apiRow);
    apiLayout->addWidget(
        label("API usage is billed separately by OpenAI. It does not use your ChatGPT allowance."));
    auto *apiDisclosure = new QToolButton;
    apiDisclosure->setText("API access · separately billed"); apiDisclosure->setCheckable(true);
    apiDisclosure->setToolButtonStyle(Qt::ToolButtonTextBesideIcon); apiDisclosure->setArrowType(Qt::RightArrow);
    apiDisclosure->setObjectName("apiAccessDisclosure");
    auto *apiSection = new QFrame(codexPanel); apiSection->setObjectName("settingsCard");
    auto *apiSectionLayout = new QVBoxLayout(apiSection); apiSectionLayout->addWidget(api);
    connect(apiDisclosure, &QToolButton::toggled, dialog, [mode, apiDisclosure](bool open) {
        apiDisclosure->setArrowType(open ? Qt::DownArrow : Qt::RightArrow); mode->setCurrentIndex(open ? 1 : 0);
    });
    connect(mode, &QComboBox::currentIndexChanged, dialog, [plan, api, apiSection, apiDisclosure](int index) {
        plan->setVisible(index == 0);
        api->setVisible(index == 1);
        apiSection->setVisible(index == 1);
        apiDisclosure->setChecked(index == 1);
    });
    mode->setCurrentIndex(connection.value("active").toObject().value("connection") == "api" ? 1 : 0);
    plan->setVisible(mode->currentIndex() == 0);
    api->setVisible(mode->currentIndex() == 1);
    apiSection->setVisible(mode->currentIndex() == 1); apiDisclosure->setChecked(mode->currentIndex() == 1);
    action("Disconnect", accountActions, [this] {
        call("provider.disconnect", {}, [this](auto r) {
            const auto message = r.value("message").toString();
            call("v2.state", {}, [this, message](auto) { activity->setText(message); });
        });
    })->setObjectName("disconnectAccount");
    auto *usage = card(ai, "Usage & models");
    auto *usageHeader = new QHBoxLayout;
    usageHeader->addWidget(label({}, "usageTotal"));
    usageHeader->addWidget(label({}, "usageTotalCaption"), 1);
    usage->addLayout(usageHeader);
    auto *reportedRows = new QWidget; reportedRows->setObjectName("reportedUsageRows");
    auto *reportedLayout = new QFormLayout(reportedRows); reportedLayout->setContentsMargins(0, 0, 0, 0);
    reportedLayout->setRowWrapPolicy(QFormLayout::WrapLongRows); usage->addWidget(reportedRows);
    usage->addWidget(label("Reported tokens are separate from provider allowance and API cost."));
    action("Manage provider usage ↗", usageHeader, [this] {
        QDesktopServices::openUrl(QUrl(state.value("provider").toObject().value("usage_url").toString("https://chatgpt.com/settings/usage")));
    });
    auto *modelRow = new QHBoxLayout;
    auto *modelDescription = new QVBoxLayout;
    modelDescription->addWidget(label("Model catalogue", "settingsAccountName"));
    modelDescription->addWidget(label({}, "catalogueSummary"));
    modelRow->addLayout(modelDescription, 1);
    action("Refresh models", modelRow, [this] { discoverModels(true); })->setObjectName("refreshModelsButton");
    usage->addLayout(modelRow);
    ai->addWidget(
        label("Tasks consume allowance or API credits. Long tasks can use more. A limit stops the request; "
              "billing never switches automatically. Connection actions take effect immediately."));
    codexLayout->addWidget(apiDisclosure);
    codexLayout->addWidget(apiSection);
    ai->addStretch();
    QSettings prefs;
    auto *appearance = page("Appearance", "Choose a comfortable workspace for inspecting your models.");
    auto *appearanceCard = card(appearance, "Interface");
    auto *form = new QFormLayout;
    form->setSpacing(18);
    auto *theme = new QComboBox;
    theme->setObjectName("appearanceTheme");
    theme->addItem("Dark", "dark");
    theme->addItem("Light", "light");
    theme->setCurrentIndex(prefs.value("v2/theme", "dark") == "light" ? 1 : 0);
    form->addRow("Color theme", theme);
    auto *textSize = new QComboBox;
    textSize->addItem("Compact", 12);
    textSize->addItem("Standard", 14);
    textSize->addItem("Larger", 16);
    textSize->setCurrentIndex(qMax(0, textSize->findData(prefs.value("v2/textSize", 14).toInt())));
    form->addRow("Text size", textSize);
    auto *navVisible = new QCheckBox("Show projects and conversations");
    navVisible->setChecked(navigationPreferred);
    form->addRow(navVisible);
    appearanceCard->addLayout(form);
    appearance->addWidget(
        label("The theme also changes the viewport background. Model materials and colors are preserved."));
    appearance->addStretch();
    auto *storage =
        page("Project storage", "Projects stay beside the application and are excluded from Git.");
    auto *storageCard = card(storage, "Projects folder");
    auto path = state.value("projects_root").toString(workspace + "/Projects");
    auto *pathLabel = label(QDir::toNativeSeparators(path));
    pathLabel->setTextInteractionFlags(Qt::TextSelectableByMouse);
    storageCard->addWidget(pathLabel);
    auto *folderRow = new QHBoxLayout;
    action("Open folder ↗", folderRow, [path] { QDesktopServices::openUrl(QUrl::fromLocalFile(path)); });
    folderRow->addStretch();
    storageCard->addLayout(folderRow);
    storage->addWidget(label(
        "New project folders use the name you enter. Duplicate names receive a number. Models, revisions and "
        "conversations are stored together; account credentials are protected separately by Windows."));
    for (auto value : state.value("catalog").toObject().value("diagnostics").toArray()) {
        auto diagnostic = value.toObject();
        storage->addWidget(label(diagnostic.value("name").toString() + ": " + diagnostic.value("reason").toString()));
    }
    storage->addStretch();
    auto *display = page("CAD display", "Adjust the model workspace without changing the design.");
    auto *displayCard = card(display, "Viewport");
    auto *edges = new QCheckBox("Show solid edges");
    edges->setObjectName("showEdges");
    edges->setChecked(prefs.value("v2/edges", true).toBool());
    displayCard->addWidget(edges);
    auto *modelVisible = new QCheckBox("Show CAD manager");
    modelVisible->setChecked(managerPreferred);
    displayCard->addWidget(modelVisible);
    display->addWidget(label(
        "Units: millimetres. Imported solids retain geometry; original feature history may be unavailable."));
    display->addStretch();
    auto *advanced = page("Advanced", "Local agent runtime and connection diagnostics.");
    auto *runtimeCard = card(advanced, "Codex App Server");
    const auto executables = state.value("runtime").toObject().value("executables").toObject();
    auto *runtime = new QLineEdit(executables.value("codex").toString());
    runtime->setPlaceholderText("Automatic executable discovery");
    auto *runtimeRow = new QHBoxLayout;
    runtimeRow->addWidget(runtime, 1);
    action("Browse…", runtimeRow, [this, runtime] {
        auto path = QFileDialog::getOpenFileName(this, "Codex executable", {}, "Codex (codex.exe)");
        if (!path.isEmpty())
            runtime->setText(path);
    });
    runtimeCard->addLayout(runtimeRow);
    auto *probeInfo = label("A runtime check does not run a model or consume model tokens.");
    runtimeCard->addWidget(probeInfo);
    QPointer<QLabel> probeLabel(probeInfo);
    auto *probeRow = new QHBoxLayout;
    action("Check runtime", probeRow, [this, probeLabel] {
        call("provider.probe", {{"provider_id", "codex"}}, [probeLabel](auto r) {
            if (probeLabel)
                probeLabel->setText(r.value("message").toString());
        });
    });
    probeRow->addStretch();
    runtimeCard->addLayout(probeRow);
    auto *claudeCard = card(advanced, "Claude Code");
    auto *claudeRuntime = new QLineEdit(executables.value("claude").toString());
    claudeRuntime->setObjectName("claudeRuntimePath");
    claudeRuntime->setPlaceholderText("Automatic executable discovery");
    auto *claudeRuntimeRow = new QHBoxLayout;
    claudeRuntimeRow->addWidget(claudeRuntime, 1);
    action("Browse…", claudeRuntimeRow, [this, claudeRuntime] {
        auto path = QFileDialog::getOpenFileName(this, "Claude Code executable", {}, "Claude Code (claude.exe claude.cmd)");
        if (!path.isEmpty()) claudeRuntime->setText(path);
    });
    claudeCard->addLayout(claudeRuntimeRow);
    auto *claudeProbeInfo = label("Checks that Claude Code starts. It does not run a model or use your API key.");
    claudeCard->addWidget(claudeProbeInfo);
    QPointer<QLabel> claudeProbeLabel(claudeProbeInfo);
    auto *claudeProbeRow = new QHBoxLayout;
    action("Check runtime", claudeProbeRow, [this, claudeProbeLabel] {
        call("provider.probe", {{"provider_id", "claude"}}, [claudeProbeLabel](auto r) {
            if (claudeProbeLabel) claudeProbeLabel->setText(r.value("message").toString());
        });
    });
    claudeProbeRow->addStretch();
    claudeCard->addLayout(claudeProbeRow);
    auto *registrations = card(advanced, "Previous account registrations");
    registrations->addWidget(label("Older sign-ins are kept separately to protect their credentials. Reconnecting reuses the primary registration. Revoking a session does not delete the app registration in ChatGPT."));
    auto *previous = new QWidget;
    previous->setObjectName("previousRegistrations");
    auto *previousLayout = new QVBoxLayout(previous);previousLayout->setContentsMargins(0,0,0,0);
    registrations->addWidget(previous);
    auto *accessActions = new QHBoxLayout;
    action("Manage ChatGPT access ↗", accessActions, [] { QDesktopServices::openUrl(QUrl("https://chatgpt.com/settings")); });
    registrations->addLayout(accessActions);
    advanced->addWidget(label("Prompt to CAD · Local OpenCascade geometry"));
    advanced->addStretch();
    connect(sections, &QListWidget::currentRowChanged, pages, &QStackedWidget::setCurrentIndex);
    sections->setCurrentRow(0);
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Save | QDialogButtonBox::Cancel);
    buttons->setObjectName("settingsActions");
    buttons->setContentsMargins(24, 12, 24, 16);
    buttons->button(QDialogButtonBox::Save)->setObjectName("primaryButton");
    outer->addWidget(buttons);
    connect(buttons, &QDialogButtonBox::rejected, dialog, &QDialog::reject);
    connect(buttons, &QDialogButtonBox::accepted, dialog,
            [this, dialog, buttons, runtime, claudeRuntime, theme, textSize, navVisible, modelVisible, edges] {
                if (busy)
                    return;
                busy = true;
                sendButton->setEnabled(false);
                buttons->button(QDialogButtonBox::Save)->setEnabled(false);
                ++settingsSaves;
                QPointer<QDialog> guard(dialog);
                const auto choice = theme->currentData().toString();
                const int size = textSize->currentData().toInt();
                const bool showNav = navVisible->isChecked(), showModel = modelVisible->isChecked(),
                           showEdges = edges->isChecked();
                rpc->call(
                    "provider.configure", {{"codex_path", runtime->text()}, {"claude_path", claudeRuntime->text()}},
                    [this, guard, choice, size, showNav, showModel, showEdges](auto r, auto e) {
                        busy = false;
                        updateSendControl();
                        if (!e.isEmpty()) {
                            if (guard)
                                guard->findChild<QDialogButtonBox *>("settingsActions")
                                    ->button(QDialogButtonBox::Save)
                                    ->setEnabled(true);
                            showError(e);
                            return;
                        }
                        QSettings p;
                        p.setValue("v2/theme", choice);
                        p.setValue("v2/textSize", size);
                        p.setValue("v2/edges", showEdges);
                        p.sync();
                        if (p.status() != QSettings::NoError) {
                            if (guard)
                                guard->findChild<QDialogButtonBox *>("settingsActions")
                                    ->button(QDialogButtonBox::Save)
                                    ->setEnabled(true);
                            showError(
                                "Preferences could not be saved. Check access to application settings.");
                            return;
                        }
                        navigationPreferred = showNav; managerPreferred = showModel;
                        priorityPanel.clear(); updateWorkspaceLayout(); saveWorkspaceLayout();
                        viewer->setShading(showEdges);
                        applyAppearance();
                        showState(r);
                        if (guard)
                            guard->accept();
                    });
            });
    refreshConnectionControls();
    dialog->show();
}

void WorkspaceWindow::beginSignIn(const QString &registration, bool newRegistration) {
    if (busy || state.value("provider").toObject().value("signing_in").toBool()) return;
    QJsonObject args;
    if (!registration.isEmpty()) args["account_id"] = registration;
    if (newRegistration) args["new_registration"] = true;
    call("provider.login", args, [this](auto result) {
        auto connection = state.value("provider").toObject();
        connection["signing_in"] = true;
        state["provider"] = connection;
        refreshConnectionControls();
        if (!QDesktopServices::openUrl(QUrl(result.value("authorization_url").toString()))) {
            activity->setText("Could not open the browser. Cancel sign-in and try again.");
        }
    });
}

void WorkspaceWindow::showOnboarding() {
    QSettings preferences;
    if (preferences.value("v2/onboardingDone", false).toBool()) return;
    if (state.value("provider").toObject().value("state") == "ready") {
        preferences.setValue("v2/onboardingDone", true);
        return;
    }
    if (onboardingDialog) { onboardingDialog->raise(); return; }
    auto *dialog = new QDialog(this);
    onboardingDialog = dialog;
    dialog->setObjectName("providerOnboarding");
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowModality(Qt::WindowModal);
    dialog->setWindowTitle("Welcome to Prompt to CAD");
    dialog->resize(640, 560);
    dialog->setMinimumSize(560, 520);
    auto *layout = new QVBoxLayout(dialog);
    layout->setContentsMargins(32, 28, 32, 24);
    layout->setSpacing(20);
    auto *slides = new QStackedWidget;
    slides->setObjectName("onboardingSlides");
    layout->addWidget(slides, 1);

    // Slide 1 · choose the agent.
    auto *welcome = new QWidget;
    auto *welcomeLayout = new QVBoxLayout(welcome);
    welcomeLayout->setContentsMargins(0, 0, 0, 0);
    welcomeLayout->setSpacing(16);
    auto *brandRow = new QHBoxLayout;
    auto *brand = new QLabel;
    brand->setPixmap(QPixmap(":/brand/app-icon.png").scaled(32, 32, Qt::KeepAspectRatio, Qt::SmoothTransformation));
    brand->setAccessibleName("Prompt to CAD logo");
    brandRow->addWidget(brand);
    brandRow->addWidget(label("Prompt to CAD", "settingsAccountName"), 1);
    welcomeLayout->addLayout(brandRow);
    welcomeLayout->addWidget(label("Choose your CAD agent", "pageTitle"));
    welcomeLayout->addWidget(label("The agent inspects your document and uses CAD tools to create and refine designs. "
                                   "Pick the one you have an account for. You can switch any time in Settings → AI connection."));
    auto *choices = new QButtonGroup(dialog);
    choices->setExclusive(true);
    auto *cards = new QHBoxLayout;
    cards->setSpacing(16);
    for (const auto &copy : providerCopy) cards->addWidget(providerCard(copy, choices));
    welcomeLayout->addSpacing(4);
    welcomeLayout->addLayout(cards);
    welcomeLayout->addStretch();
    welcomeLayout->addWidget(label("You can also skip setup to inspect and edit local CAD files without an agent."));
    slides->addWidget(welcome);

    // Slide 2 · connect the chosen agent.
    auto *connectPages = new QStackedWidget;
    connectPages->setObjectName("onboardingConnectPages");
    auto *codex = new QWidget;
    auto *codexLayout = new QVBoxLayout(codex);
    codexLayout->setContentsMargins(0, 0, 0, 0);
    codexLayout->setSpacing(16);
    codexLayout->addWidget(label("Connect Codex", "pageTitle"));
    codexLayout->addWidget(label("Codex is OpenAI’s coding agent. Authorize your own eligible ChatGPT plan in your browser; "
                                 "Prompt to CAD never sees your password."));
    auto *codexDetails = card(codexLayout, "What you need");
    codexDetails->addWidget(label("1   A ChatGPT plan that includes Codex. Tasks use its allowance or authorized credits."));
    codexDetails->addWidget(label("2   The Codex CLI installed on this PC. Prompt to CAD finds it automatically."));
    codexDetails->addWidget(label("Credentials stay in Windows-protected storage, outside your projects. "
                                  "OpenAI API keys, billed separately, are available in Settings."));
    codexLayout->addStretch();
    auto *codexRow = new QHBoxLayout;
    auto *start = action("Continue with ChatGPT", codexRow, [this] { beginSignIn(); });
    start->setObjectName("onboardingConnect");
    codexRow->addStretch();
    codexLayout->addLayout(codexRow);
    connectPages->addWidget(codex);

    auto *claude = new QWidget;
    auto *claudeLayout = new QVBoxLayout(claude);
    claudeLayout->setContentsMargins(0, 0, 0, 0);
    claudeLayout->setSpacing(16);
    claudeLayout->addWidget(label("Connect Claude", "pageTitle"));
    claudeLayout->addWidget(label("Claude works through Claude Code on this PC, using your own Anthropic API key. "
                                  "Usage is billed per token by Anthropic; a Claude.ai subscription is not used."));
    auto *claudeDetails = card(claudeLayout, "What you need");
    auto *keyNeed = new QHBoxLayout;
    keyNeed->addWidget(label("1   An Anthropic API key with credits."), 1);
    action("Get a key ↗", keyNeed, [] { QDesktopServices::openUrl(QUrl("https://console.anthropic.com/settings/keys")); })
        ->setObjectName("quietButton");
    claudeDetails->addLayout(keyNeed);
    auto *runtimeNeed = new QHBoxLayout;
    runtimeNeed->addWidget(label("2   Claude Code installed on this PC."), 1);
    action("Install guide ↗", runtimeNeed, [] { QDesktopServices::openUrl(QUrl("https://code.claude.com/docs/en/setup")); })
        ->setObjectName("quietButton");
    claudeDetails->addLayout(runtimeNeed);
    auto *runtimeState = label({}, "onboardingClaudeRuntime");
    runtimeState->setContentsMargins(22, 0, 0, 0);
    claudeDetails->addWidget(runtimeState);
    auto *key = new QLineEdit;
    key->setObjectName("onboardingClaudeKey");
    key->setEchoMode(QLineEdit::Password);
    key->setPlaceholderText("Paste your API key (sk-ant-…)");
    key->setAccessibleName("Anthropic API key");
    claudeLayout->addWidget(key);
    claudeLayout->addWidget(label("The key is checked without running a model and stored in Windows-protected storage."));
    claudeLayout->addStretch();
    auto *claudeRow = new QHBoxLayout;
    auto *validate = action("Validate and connect", claudeRow, [this, key] {
        const auto value = key->text().trimmed();
        if (value.isEmpty()) { key->setFocus(); return; }
        key->clear();
        if (auto *status = onboardingDialog ? onboardingDialog->findChild<QLabel *>("onboardingStatus") : nullptr)
            status->setText("Checking the key with Anthropic…");
        call("provider.anthropic_key", {{"key", value}}, [this](auto) { call("v2.state"); });
    });
    validate->setObjectName("onboardingClaudeConnect");
    connect(key, &QLineEdit::returnPressed, validate, &QPushButton::click);
    claudeRow->addStretch();
    claudeLayout->addLayout(claudeRow);
    connectPages->addWidget(claude);
    slides->addWidget(connectPages);

    auto *status = label({}, "onboardingStatus");
    layout->addWidget(status);

    // Footer · back, progress dots, skip and continue.
    auto *footer = new QHBoxLayout;
    footer->setSpacing(12);
    auto *back = action("Back", footer, [] {});
    back->setObjectName("onboardingBack");
    footer->addStretch();
    QList<QLabel *> dots;
    for (int index = 0; index < 2; ++index) {
        auto *dot = new QLabel;
        dot->setObjectName("onboardingDot");
        dot->setAccessibleName(QString("Step %1 of 2").arg(index + 1));
        footer->addWidget(dot, 0, Qt::AlignVCenter);
        dots << dot;
    }
    footer->addStretch();
    action("Skip for now", footer, [dialog] { dialog->reject(); })->setObjectName("onboardingSkip");
    auto *next = action("Continue", footer, [] {});
    next->setObjectName("onboardingNext");
    next->setDefault(true);
    for (auto *button : {back, next}) {  // Keep the progress dots still while buttons swap.
        auto policy = button->sizePolicy();
        policy.setRetainSizeWhenHidden(true);
        button->setSizePolicy(policy);
    }
    layout->addLayout(footer);

    auto show = [slides, connectPages, back, next, dots, choices, key, start, status](int index) {
        const int direction = index > slides->currentIndex() ? 1 : -1;
        const bool changed = index != slides->currentIndex();
        const auto chosen = choices->checkedButton() ? choices->checkedButton()->property("providerId").toString() : QString("codex");
        connectPages->setCurrentIndex(chosen == "claude" ? 1 : 0);
        slides->setCurrentIndex(index);
        back->setVisible(index == 1);
        next->setVisible(index == 0);
        next->setEnabled(choices->checkedButton());
        status->clear();
        for (int dot = 0; dot < dots.size(); ++dot) {
            dots[dot]->setProperty("active", dot == index);
            repolish(dots[dot]);
        }
        if (changed) revealPage(slides->currentWidget(), direction);
        if (index == 1) (chosen == "claude" ? static_cast<QWidget *>(key) : start)->setFocus();
    };
    connect(next, &QPushButton::clicked, dialog, [show] { show(1); });
    connect(back, &QPushButton::clicked, dialog, [show] { show(0); });
    connect(choices, &QButtonGroup::buttonClicked, dialog, [next](QAbstractButton *) { next->setEnabled(true); });
    // Preselect the provider already chosen in this installation, otherwise Codex.
    const auto preferred = state.value("provider").toObject().value("provider_id").toString("codex");
    for (auto *button : choices->buttons())
        if (button->property("providerId").toString() == preferred) button->setChecked(true);
    show(0);
    connect(dialog, &QDialog::finished, this, [](int) { QSettings().setValue("v2/onboardingDone", true); });
    refreshConnectionControls();
    dialog->show();
}
