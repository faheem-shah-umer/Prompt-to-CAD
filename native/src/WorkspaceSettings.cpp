#include "CadView.h"
#include "WorkspaceWindow.h"
#include <QApplication>
#include <QCheckBox>
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
#include <QListWidget>
#include <QPushButton>
#include <QScreen>
#include <QScrollArea>
#include <QSettings>
#include <QSignalBlocker>
#include <QStackedWidget>
#include <QTimer>
#include <QToolButton>
#include <QUrl>
#include <QVBoxLayout>

namespace {
QLabel *label(const QString &text, const QString &name = "settingsCaption") {
    auto *l = new QLabel(text);
    l->setObjectName(name);
    l->setWordWrap(true);
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
    layout->setContentsMargins(18, 16, 18, 16);
    layout->setSpacing(12);
    layout->addWidget(label(title, "sectionTitle"));
    parent->addWidget(frame);
    return layout;
}
} // namespace

void WorkspaceWindow::refreshConnectionControls() {
    if (!settingsDialog)
        return;
    auto connection = state.value("provider").toObject();
    auto active = connection.value("active").toObject();
    const bool ready = connection.value("state") == "ready";
    const bool signingIn = connection.value("signing_in").toBool();
    if (auto *info = settingsDialog->findChild<QLabel *>("connectionInfo")) {
        QString text = signingIn ? "Waiting for browser authorization"
                       : ready   ? "Connected"
                                 : "Not connected";
        auto workspaceName = active.value("workspace").toString();
        if (workspaceName.startsWith("Workspace name not reported"))
            workspaceName = "Workspace not reported";
        if (!active.isEmpty())
            text += "\n" + active.value("email").toString() + "\n" + connection.value("billing").toString() +
                    "\n" + workspaceName;
        info->setText(text);
    }
    if (auto *cancel = settingsDialog->findChild<QPushButton *>("cancelSignIn"))
        cancel->setVisible(signingIn);
    if (auto *disconnect = settingsDialog->findChild<QPushButton *>("disconnectAccount"))
        disconnect->setVisible(active.value("connected").toBool());
    if (auto *accounts = settingsDialog->findChild<QComboBox *>("savedAccounts")) {
        const auto previous = accounts->currentData();
        QSignalBlocker blocker(accounts);
        accounts->clear();
        for (auto a : connection.value("accounts").toArray()) {
            auto item = a.toObject();
            if (item.value("connection") == "chatgpt")
                accounts->addItem(item.value("email").toString(), item.value("id"));
        }
        const int at = accounts->findData(previous);
        if (at >= 0)
            accounts->setCurrentIndex(at);
        if (auto *toggle = settingsDialog->findChild<QToolButton *>("savedAccountsToggle"))
            toggle->setVisible(accounts->count() > 0);
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
    dialog->setWindowTitle("Settings · Prompt to CAD V2");
    dialog->resize(820, qBound(500, dialog->screen()->availableGeometry().height() - 90, 680));
    dialog->setMinimumSize(660, 500);
    auto *outer = new QVBoxLayout(dialog);
    outer->setContentsMargins(20, 20, 20, 16);
    outer->setSpacing(18);
    outer->addWidget(label("Settings", "pageTitle"));
    auto *body = new QHBoxLayout;
    body->setSpacing(24);
    auto *sections = new QListWidget;
    sections->setObjectName("settingsNavigation");
    sections->setFixedWidth(148);
    sections->addItems({"AI connection", "Appearance", "Projects", "CAD display", "Advanced"});
    body->addWidget(sections);
    auto *pages = new QStackedWidget;
    body->addWidget(pages, 1);
    outer->addLayout(body, 1);
    auto page = [&](const QString &title, const QString &description) {
        auto *scroll = new QScrollArea;
        scroll->setFrameShape(QFrame::NoFrame);
        scroll->setWidgetResizable(true);
        scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOn);
        auto *contents = new QWidget;
        auto *layout = new QVBoxLayout(contents);
        layout->setContentsMargins(0, 0, 10, 8);
        layout->setSpacing(16);
        layout->addWidget(label(title, "sectionTitle"));
        layout->addWidget(label(description));
        scroll->setWidget(contents);
        pages->addWidget(scroll);
        return layout;
    };
    auto connection = state.value("provider").toObject();
    auto *ai = page("Connect your CAD agent", "Use your own account. Choose how requests are billed.");
    auto *mode = new QComboBox;
    mode->setObjectName("connectionMode");
    mode->addItem("ChatGPT plan · Codex", "chatgpt");
    mode->addItem("OpenAI API key · separate billing", "api");
    ai->addWidget(mode);
    auto *accountCard = card(ai, "Account");
    auto *info = label({}, "connectionInfo");
    info->setTextInteractionFlags(Qt::TextSelectableByMouse);
    accountCard->addWidget(info);
    auto *plan = new QWidget;
    auto *planLayout = new QVBoxLayout(plan);
    planLayout->setContentsMargins(0, 0, 0, 0);
    auto *connectRow = new QHBoxLayout;
    auto signIn = [this](const QString &registration) {
        QJsonObject args;
        if (!registration.isEmpty())
            args["account_id"] = registration;
        call("provider.login", args, [this](auto r) {
            auto provider = state.value("provider").toObject();
            provider["signing_in"] = true;
            state["provider"] = provider;
            refreshConnectionControls();
            QDesktopServices::openUrl(QUrl(r.value("authorization_url").toString()));
        });
    };
    action("Continue with ChatGPT", connectRow, [signIn] { signIn({}); })->setObjectName("primaryButton");
    auto *cancelSignIn = action("Cancel sign-in", connectRow, [this] {
        call("provider.cancel_login", {}, [this](auto) { call("v2.state"); });
    });
    cancelSignIn->setObjectName("cancelSignIn");
    connectRow->addStretch();
    planLayout->addLayout(connectRow);
    auto *savedToggle = new QToolButton;
    savedToggle->setText("Saved accounts");
    savedToggle->setObjectName("savedAccountsToggle");
    savedToggle->setCheckable(true);
    savedToggle->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    savedToggle->setArrowType(Qt::RightArrow);
    planLayout->addWidget(savedToggle);
    auto *savedPanel = new QWidget;
    auto *savedLayout = new QVBoxLayout(savedPanel);
    savedLayout->setContentsMargins(0, 4, 0, 0);
    auto *accounts = new QComboBox;
    accounts->setObjectName("savedAccounts");
    accounts->setPlaceholderText("No saved registrations");
    savedLayout->addWidget(accounts);
    auto *savedActions = new QHBoxLayout;
    action("Use selected", savedActions, [this, accounts] {
        if (accounts->currentIndex() >= 0)
            call("provider.select", {{"account_id", accounts->currentData().toString()}},
                 [this](auto) { call("v2.state"); });
    });
    action("Reconnect", savedActions, [accounts, signIn] {
        if (accounts->currentIndex() >= 0)
            signIn(accounts->currentData().toString());
    });
    savedActions->addStretch();
    savedLayout->addLayout(savedActions);
    savedPanel->hide();
    planLayout->addWidget(savedPanel);
    connect(savedToggle, &QToolButton::toggled, dialog, [savedPanel, savedToggle](bool show) {
        savedPanel->setVisible(show);
        savedToggle->setArrowType(show ? Qt::DownArrow : Qt::RightArrow);
    });
    accountCard->addWidget(plan);
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
    accountCard->addWidget(api);
    connect(mode, &QComboBox::currentIndexChanged, dialog, [plan, api](int index) {
        plan->setVisible(index == 0);
        api->setVisible(index == 1);
    });
    mode->setCurrentIndex(connection.value("active").toObject().value("connection") == "api" ? 1 : 0);
    plan->setVisible(mode->currentIndex() == 0);
    api->setVisible(mode->currentIndex() == 1);
    auto *accountActions = new QHBoxLayout;
    action("Disconnect", accountActions, [this] {
        call("provider.disconnect", {}, [this](auto) { call("v2.state"); });
    })->setObjectName("disconnectAccount");
    accountActions->addStretch();
    accountCard->addLayout(accountActions);
    auto *usage = card(ai, "Token usage & models");
    usage->addWidget(label({}, "usageInfo"));
    auto *usageActions = new QHBoxLayout;
    action("Manage usage ↗", usageActions, [mode] {
        QDesktopServices::openUrl(QUrl(mode->currentIndex() == 0 ? "https://chatgpt.com/settings/usage"
                                                                 : "https://platform.openai.com/usage"));
    });
    usageActions->addStretch();
    usage->addLayout(usageActions);
    auto *modelRow = new QHBoxLayout;
    modelRow->addWidget(label("Choose a model in the conversation panel."), 1);
    action("Discover models", modelRow, [this] { discoverModels(); });
    usage->addLayout(modelRow);
    ai->addWidget(
        label("Tasks consume allowance or API credits. Long tasks can use more. A limit stops the request; "
              "billing never switches automatically. Connection actions take effect immediately."));
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
    textSize->addItem("Standard", 12);
    textSize->addItem("Larger", 14);
    textSize->setCurrentIndex(prefs.value("v2/textSize", 12).toInt() == 14 ? 1 : 0);
    form->addRow("Text size", textSize);
    auto *navVisible = new QCheckBox("Show projects and conversations");
    navVisible->setChecked(this->navigation->isVisible());
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
    storage->addStretch();
    auto *display = page("CAD display", "Adjust the model workspace without changing the design.");
    auto *displayCard = card(display, "Viewport");
    auto *edges = new QCheckBox("Show solid edges");
    edges->setObjectName("showEdges");
    edges->setChecked(prefs.value("v2/edges", true).toBool());
    displayCard->addWidget(edges);
    auto *modelVisible = new QCheckBox("Show CAD manager");
    modelVisible->setChecked(manager->isVisible());
    displayCard->addWidget(modelVisible);
    display->addWidget(label(
        "Units: millimetres. Imported solids retain geometry; original feature history may be unavailable."));
    display->addStretch();
    auto *advanced = page("Advanced", "Local agent runtime and connection diagnostics.");
    auto *runtimeCard = card(advanced, "Codex App Server");
    auto *runtime = new QLineEdit(state.value("runtime").toObject().value("executable").toString());
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
        call("provider.probe", {}, [probeLabel](auto r) {
            if (probeLabel)
                probeLabel->setText(r.value("message").toString());
        });
    });
    probeRow->addStretch();
    runtimeCard->addLayout(probeRow);
    advanced->addWidget(label("Prompt to CAD V2 · Local OpenCascade geometry"));
    advanced->addStretch();
    connect(sections, &QListWidget::currentRowChanged, pages, &QStackedWidget::setCurrentIndex);
    sections->setCurrentRow(0);
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Save | QDialogButtonBox::Cancel);
    buttons->setObjectName("settingsActions");
    buttons->button(QDialogButtonBox::Save)->setObjectName("primaryButton");
    outer->addWidget(buttons);
    connect(buttons, &QDialogButtonBox::rejected, dialog, &QDialog::reject);
    connect(buttons, &QDialogButtonBox::accepted, dialog,
            [this, dialog, buttons, runtime, theme, textSize, navVisible, modelVisible, edges] {
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
                    "provider.configure", {{"codex_path", runtime->text()}},
                    [this, guard, choice, size, showNav, showModel, showEdges](auto r, auto e) {
                        busy = false;
                        sendButton->setEnabled(true);
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
                        this->navigation->setVisible(showNav);
                        manager->setVisible(showModel);
                        viewer->setShading(showEdges);
                        applyAppearance();
                        showState(r);
                        if (guard)
                            guard->accept();
                    });
            });
    auto *poll = new QTimer(dialog);
    poll->setInterval(2500);
    connect(poll, &QTimer::timeout, dialog, [this, guard = QPointer<QDialog>(dialog)] {
        if (busy || !guard || !state.value("provider").toObject().value("signing_in").toBool())
            return;
        rpc->call("provider.status", {}, [this, guard](auto r, auto e) {
            if (!guard || !e.isEmpty())
                return;
            state["provider"] = r;
            updateUsage();
            refreshConnectionControls();
            if (r.value("state") == "ready")
                discoverModels();
        });
    });
    poll->start();
    refreshConnectionControls();
    dialog->show();
}
