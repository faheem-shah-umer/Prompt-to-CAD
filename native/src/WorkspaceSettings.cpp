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
    auto connection = state.value("provider").toObject();
    auto active = connection.value("active").toObject();
    const bool ready = connection.value("state") == "ready";
    const bool signingIn = connection.value("signing_in").toBool();
    if (onboardingDialog) {
        if (auto *start = onboardingDialog->findChild<QPushButton *>("onboardingConnect")) start->setEnabled(!busy && !signingIn);
        if (auto *status = onboardingDialog->findChild<QLabel *>("onboardingStatus")) status->setText(signingIn ? "Finish authorization in your browser." : connection.value("error").toString());
        if (ready) onboardingDialog->accept();
    }
    if (!settingsDialog) return;
    if (auto *create = settingsDialog->findChild<QPushButton *>("newChatGPTRegistration"))create->setEnabled(!busy&&!signingIn);
    if (auto *start = settingsDialog->findChild<QPushButton *>("connectChatGPT")) {
        start->setVisible(!ready || active.value("connection") != "chatgpt");
        start->setText(active.value("connection") == "chatgpt" ? "Reconnect ChatGPT" : "Continue with ChatGPT");
        start->setEnabled(!busy && !signingIn);
    }
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
                auto *remove=new QPushButton;remove->setIcon(style()->standardIcon(QStyle::SP_TrashIcon));remove->setFixedSize(30,30);remove->setAccessibleName("Remove saved connection "+item.value("label").toString());remove->setToolTip("Remove saved connection");line->addWidget(remove);
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
    action("Continue with ChatGPT", connectRow, [this] { beginSignIn(); })->setObjectName("connectChatGPT");
    auto *cancelSignIn = action("Cancel sign-in", connectRow, [this] {
        call("provider.cancel_login", {}, [this](auto) { call("v2.state"); });
    });
    cancelSignIn->setObjectName("cancelSignIn");
    action("Connect a new account", connectRow, [this] {
        if(QMessageBox::question(settingsDialog,"Connect a new account","Create a new Prompt to CAD registration? Your current connection remains active until authorization succeeds. Old registered apps can be removed in ChatGPT Settings.") == QMessageBox::Yes)beginSignIn({},true);
    })->setObjectName("newChatGPTRegistration");
    connectRow->addStretch();
    planLayout->addLayout(connectRow);
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
        call("provider.disconnect", {}, [this](auto r) {
            const auto message = r.value("message").toString();
            call("v2.state", {}, [this, message](auto) { activity->setText(message); });
        });
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
    action("Refresh models", modelRow, [this] { discoverModels(true); });
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
                        this->navigation->setVisible(showNav);
                        manager->setVisible(showModel);
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
    dialog->setObjectName("codexOnboarding");
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowModality(Qt::WindowModal);
    dialog->setWindowTitle("Welcome to Prompt to CAD");
    dialog->resize(540, 440);
    auto *layout = new QVBoxLayout(dialog);
    layout->setContentsMargins(28, 26, 28, 24);
    layout->setSpacing(18);
    layout->addWidget(label("Your CAD workspace, with Codex", "pageTitle"));
    layout->addWidget(label("Codex is OpenAI’s coding agent. In Prompt to CAD it inspects your document and uses CAD tools to create and refine designs. Connect your own eligible ChatGPT plan in your browser."));
    auto *details = card(layout, "Your account and usage");
    details->addWidget(label("Agent tasks consume your plan allowance or authorized credits. Longer tasks may use more. Limits stop the task; the app never switches billing automatically."));
    details->addWidget(label("Credentials stay in Windows-protected local storage, outside your projects. Optional API keys are available in Settings and are billed separately by OpenAI."));
    details->addWidget(label("You can skip setup to inspect and edit local CAD files. Connect later from Settings → AI connection to use the agent."));
    layout->addWidget(label({}, "onboardingStatus"));
    auto *actions = new QHBoxLayout;
    action("Skip for now", actions, [dialog] { dialog->reject(); })->setObjectName("onboardingSkip");
    actions->addStretch();
    auto *start = action("Continue with ChatGPT", actions, [this] { beginSignIn(); });
    start->setObjectName("onboardingConnect");
    layout->addLayout(actions);
    connect(dialog, &QDialog::finished, this, [](int) { QSettings().setValue("v2/onboardingDone", true); });
    refreshConnectionControls();
    dialog->show();
}
