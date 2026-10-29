#include "WorkspaceWindow.h"
#include "CadView.h"
#include "WorkspaceTheme.h"
#include <QAction>
#include <QApplication>
#include <QCheckBox>
#include <QComboBox>
#include <QDateTime>
#include <QDesktopServices>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QDoubleSpinBox>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QFrame>
#include <QInputDialog>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMenu>
#include <QMenuBar>
#include <QMessageBox>
#include <QPainter>
#include <QPlainTextEdit>
#include <QProgressBar>
#include <QPushButton>
#include <QResizeEvent>
#include <QScrollArea>
#include <QSettings>
#include <QShortcut>
#include <QSignalBlocker>
#include <QSplitter>
#include <QStandardPaths>
#include <QStatusBar>
#include <QStyle>
#include <QTabBar>
#include <QTabWidget>
#include <QTextBrowser>
#include <QTextCursor>
#include <QTimer>
#include <QToolBar>
#include <QToolButton>
#include <QTreeWidget>
#include <QTreeWidgetItemIterator>
#include <QUrl>
#include <QUuid>
#include <QVBoxLayout>
#include <Standard_Version.hxx>

namespace {
QPushButton *button(const QString &text, QBoxLayout *layout, std::function<void()> clicked) {
    auto *b = new QPushButton(text);
    layout->addWidget(b);
    QObject::connect(b, &QPushButton::clicked, std::move(clicked));
    return b;
}
QIcon lineIcon(const QString &name) {
    QPixmap pixmap(24, 24);
    pixmap.fill(Qt::transparent);
    QPainter p(&pixmap);
    p.setRenderHint(QPainter::Antialiasing);
    p.setPen(QPen(QColor("#85858d"), 1.5, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
    if (name == "projects") {
        p.drawPolyline(QPolygonF{{3, 7}, {3, 20}, {21, 20}, {21, 7}, {11, 7}, {9, 4}, {3, 4}, {3, 7}});
    } else if (name == "model") {
        p.drawPolygon(QPolygonF{{12, 3}, {21, 8}, {21, 17}, {12, 22}, {3, 17}, {3, 8}});
        p.drawLine(3, 8, 12, 13);
        p.drawLine(12, 13, 21, 8);
        p.drawLine(12, 13, 12, 22);
    } else if (name == "chat") {
        p.drawRoundedRect(3, 4, 18, 14, 3, 3);
        p.drawPolyline(QPolygonF{{7, 18}, {7, 22}, {12, 18}});
        p.drawLine(7, 9, 17, 9);
        p.drawLine(7, 13, 14, 13);
    } else {
        p.drawEllipse(QPointF(12, 12), 6, 6);
        p.drawEllipse(QPointF(12, 12), 2, 2);
        p.translate(12, 12);
        for (int i = 0; i < 8; ++i) {
            p.drawLine(0, -7, 0, -10);
            p.rotate(45);
        }
    }
    return QIcon(pixmap);
}
QString html(const QString &value) { return value.toHtmlEscaped().replace("\n", "<br>"); }
} // namespace

WorkspaceWindow::WorkspaceWindow(const QString &source, const QString &python, const QString &openPath,
                                 bool smokeTest)
    : workspace(source), smoke(smokeTest) {
    setWindowTitle("Prompt to CAD V2");
    resize(1560, 940);
    setMinimumSize(880, 600);
    rpc = new RpcClient(this);
    auto *central = new QWidget;
    auto *root = new QHBoxLayout(central);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *rail = new QWidget;
    rail->setObjectName("rail");
    rail->setFixedWidth(46);
    auto *railLayout = new QVBoxLayout(rail);
    railLayout->setContentsMargins(3, 10, 3, 8);
    auto *projectsToggle =
        button("", railLayout, [this] { navigation->setVisible(!navigation->isVisible()); });
    projectsToggle->setIcon(lineIcon("projects"));
    projectsToggle->setAccessibleName("Projects and conversations");
    projectsToggle->setToolTip("Projects and conversations");
    auto *modelToggle = button("", railLayout, [this] { manager->setVisible(!manager->isVisible()); });
    modelToggle->setIcon(lineIcon("model"));
    modelToggle->setAccessibleName("CAD manager");
    modelToggle->setToolTip("CAD manager");
    auto *chatToggle =
        button("", railLayout, [this] { conversationPane->setVisible(!conversationPane->isVisible()); });
    chatToggle->setIcon(lineIcon("chat"));
    chatToggle->setAccessibleName("Agent conversation");
    chatToggle->setToolTip("Agent conversation");
    railLayout->addStretch();
    auto *settingsButton = button("", railLayout, [this] { account(); });
    settingsButton->setIcon(lineIcon("settings"));
    settingsButton->setAccessibleName("Settings");
    settingsButton->setObjectName("settingsButton");
    settingsButton->setToolTip("Settings");
    root->addWidget(rail);
    split = new QSplitter(Qt::Horizontal);
    root->addWidget(split, 1);
    setCentralWidget(central);
    navigation = new QWidget;
    navigation->setObjectName("navigation");
    auto *nav = new QVBoxLayout(navigation);
    nav->setContentsMargins(12, 14, 12, 12);
    auto *heading = new QLabel("Prompt to CAD V2");
    heading->setStyleSheet("font-weight:600;font-size:15px;padding:6px 0 16px");
    nav->addWidget(heading);
    button("＋  New project", nav, [this] { newProject(); });
    button("Open project…", nav, [this] {
        auto p = QFileDialog::getExistingDirectory(this, "Open native project");
        if (!p.isEmpty())
            call("v2.open_native", {{"path", p}});
    });
    button("＋  New conversation", nav, [this] { call("v2.conversation.new"); });
    search = new QLineEdit;
    search->setPlaceholderText("Search projects and conversations");
    nav->addWidget(search);
    projects = new QTreeWidget;
    projects->setHeaderHidden(true);
    projects->setIndentation(14);
    nav->addWidget(projects, 1);
    auto *usage = new QLabel("Local workspace · files stay on this PC");
    usage->setWordWrap(true);
    usage->setObjectName("muted");
    nav->addWidget(usage);
    accountBadge = button("Account · disconnected", nav, [this] { account(); });
    accountBadge->setObjectName("accountBadge");
    split->addWidget(navigation);
    auto *workspacePane = new QWidget;
    auto *work = new QVBoxLayout(workspacePane);
    work->setContentsMargins(0, 0, 0, 0);
    work->setSpacing(0);
    auto *documentHeader = new QHBoxLayout;
    documentHeader->setContentsMargins(12, 8, 12, 8);
    title = new QLabel("Create a project to begin");
    title->setStyleSheet("font-weight:600");
    title->setMaximumWidth(320);
    saved = new QLabel("Saved locally");
    saved->setObjectName("muted");
    documentHeader->addWidget(title, 1);
    documentHeader->addWidget(saved);
    button("Save", documentHeader,
           [this] { call("v2.state", {}, [this](auto) { saved->setText("All changes saved locally"); }); });
    button("Undo", documentHeader, [this] {
        if (undoAction->isEnabled())
            undoAction->trigger();
    })->setObjectName("undoToolbar");
    button("Redo", documentHeader, [this] {
        if (redoAction->isEnabled())
            redoAction->trigger();
    })->setObjectName("redoToolbar");
    button("Search", documentHeader, [this] {
        if (auto *a = findChild<QAction *>("commandSearch"))
            a->trigger();
    });

    for (int i = 0; i < documentHeader->count(); ++i)
        if (auto *b = qobject_cast<QPushButton *>(documentHeader->itemAt(i)->widget()))
            b->setFixedWidth(58);
    work->addLayout(documentHeader);
    documentTabs = new QTabBar;
    documentTabs->setExpanding(false);
    documentTabs->setDrawBase(false);
    work->addWidget(documentTabs);
    auto *commandGroups = new QTabWidget;
    commandGroups->setObjectName("commandManager");
    auto commandPage = [commandGroups](const QString &label) {
        auto *toolbar = new QToolBar;
        toolbar->setMovable(false);
        commandGroups->addTab(toolbar, label);
        return toolbar;
    };
    auto *commands = commandPage("Create");
    auto add = [this, &commands](const QString &name, const QString &op) {
        auto *a = commands->addAction(name);
        connect(a, &QAction::triggered, this, [this, op] { operation(op); });
    };
    add("Create block", "block");
    auto *fromText = commands->addAction("Create with agent");
    connect(fromText, &QAction::triggered, this, [this] {
        conversationPane->show();
        composer->setFocus();
    });
    commands = commandPage("Modify");
    add("Thickness", "thickness");
    add("Holes", "holes");
    add("Fillet", "fillet");
    add("Chamfer", "chamfer");
    add("Named parameters", "parameters");
    add("Mesh scale", "mesh_scale");
    add("Separate region", "mesh_separate");
    commands = commandPage("Assembly");
    add("Move", "move");
    commands = commandPage("Inspect");
    auto *inspect = commands->addAction("Inspect");
    connect(inspect, &QAction::triggered, this, [this] {
        if (!selected.isEmpty()) {
            auto p = base();
            p["instance_id"] = selected.value("instance_id");
            call("v2.inspect", p, [this](auto r) {
                properties->setPlainText(QJsonDocument(r).toJson(QJsonDocument::Indented));
                managerTabs->setCurrentWidget(properties);
            });
        }
    });
    auto *clearance = commands->addAction("Clearance");
    connect(clearance, &QAction::triggered, this, [this] {
        if (selected.isEmpty()) {
            showError("Select the first body to measure.");
            return;
        }
        QStringList labels, ids;
        for (auto p : document.value("components").toArray()) {
            auto part = p.toObject();
            if (part.value("instance_id") != selected.value("instance_id")) {
                labels << part.value("name").toString();
                ids << part.value("instance_id").toString();
            }
        }
        if (ids.isEmpty()) {
            showError("Clearance measurement needs another component.");
            return;
        }
        bool ok;
        auto name = QInputDialog::getItem(this, "Measure clearance", "Second body", labels, 0, false, &ok);
        if (!ok)
            return;
        auto p = base();
        p["first"] = QJsonObject{{"instance_id", selected.value("instance_id")}, {"kind", "body"}};
        p["second"] = QJsonObject{{"instance_id", ids[labels.indexOf(name)]}, {"kind", "body"}};
        call("v2.measure", p, [this](auto r) {
            properties->setPlainText(QJsonDocument(r).toJson(QJsonDocument::Indented));
            managerTabs->setCurrentWidget(properties);
            manager->show();
        });
    });
    auto *viewCommands = commandPage("View");
    commandGroups->setMaximumHeight(86);
    work->addWidget(commandGroups);
    auto *inner = new QSplitter(Qt::Horizontal);
    inner->setObjectName("modelSplit");
    manager = new QWidget;
    auto *management = new QVBoxLayout(manager);
    management->setContentsMargins(9, 10, 9, 8);
    managerTabs = new QTabWidget;
    auto *modelPane = new QWidget;
    auto *modelLayout = new QVBoxLayout(modelPane);
    modelLayout->setContentsMargins(0, 8, 0, 0);
    treeFilter = new QLineEdit;
    treeFilter->setPlaceholderText("Filter model tree");
    modelLayout->addWidget(treeFilter);
    modelTree = new QTreeWidget;
    modelTree->setHeaderHidden(true);
    modelLayout->addWidget(modelTree);
    properties = new QTextBrowser;
    properties->setPlaceholderText("Select a component, face or edge to inspect "
                                   "dimensions and named parameters.");
    revisions = new QTreeWidget;
    revisions->setHeaderLabels({"Accepted revisions"});
    managerTabs->addTab(modelPane, "Model");
    managerTabs->addTab(properties, "Properties");
    managerTabs->addTab(revisions, "Revisions");
    management->addWidget(managerTabs, 1);
    operationPane = new QWidget;
    operationForm = new QFormLayout(operationPane);
    operationPane->hide();
    management->addWidget(operationPane);
    inner->addWidget(manager);
    auto *viewportPane = new QWidget;
    auto *vp = new QVBoxLayout(viewportPane);
    vp->setContentsMargins(0, 0, 0, 0);
    vp->setSpacing(0);
    auto *views = new QHBoxLayout;
    views->setContentsMargins(8, 5, 8, 5);
    selectionMode = new QComboBox;
    selectionMode->addItems({"Body", "Face", "Edge", "Vertex"});
    views->addWidget(selectionMode);
    for (const auto &name : {"Fit", "Isometric", "Front", "Top", "Right"})
        button(name, views, [this, name] {
            if (QString(name) == "Fit")
                viewer->fitAll();
            else
                viewer->standardView(QString(name).toLower());
        });
    views->addStretch();
    vp->addLayout(views);
    emptyPage = new QWidget;
    auto *emptyLayout = new QVBoxLayout(emptyPage);
    emptyLayout->setContentsMargins(35, 35, 35, 35);
    emptyLayout->addStretch();
    auto *emptyTitle = new QLabel("A workspace for your next design");
    emptyTitle->setStyleSheet("font-size:22px;font-weight:600;");
    emptyTitle->setWordWrap(true);
    emptyLayout->addWidget(emptyTitle);
    auto *emptyNote = new QLabel("Create a project, import engineering geometry or a visual mesh, then "
                                 "refine it with the "
                                 "CAD agent. Describe a part and its dimensions to get started.");
    emptyNote->setWordWrap(true);
    emptyLayout->addWidget(emptyNote);
    button("New project", emptyLayout, [this] { newProject(); });
    button("Import supported model", emptyLayout, [this] { openFile(); });
    button("Describe a design", emptyLayout, [this] {
        conversationPane->show();
        composer->setFocus();
    });
    emptyLayout->addStretch();
    emptyPage->hide();
    vp->addWidget(emptyPage, 1);
    viewer = new CadView;
    vp->addWidget(viewer, 1);
    inner->addWidget(viewportPane);
    inner->setStretchFactor(1, 1);
    inner->setSizes({245, 760});
    work->addWidget(inner, 1);
    split->addWidget(workspacePane);
    conversationPane = new QWidget;
    conversationPane->setObjectName("conversationPane");
    auto *conversation = new QVBoxLayout(conversationPane);
    conversation->setContentsMargins(18, 16, 18, 12);
    conversation->setSpacing(12);
    auto *conversationHeader = new QHBoxLayout;
    conversationTitle = new QLabel("Design conversation");
    conversationTitle->setWordWrap(true);
    conversationTitle->setStyleSheet("font-size:14px;font-weight:600");
    conversationHeader->addWidget(conversationTitle, 1);
    auto *connectionButton = button("Codex", conversationHeader, [this] { account(); });
    connectionButton->setObjectName("quietButton");
    connectionButton->setToolTip("Account and agent settings");
    conversation->addLayout(conversationHeader);
    chat = new QTextBrowser;
    chat->setObjectName("conversationHistory");
    chat->setOpenExternalLinks(false);
    chat->setOpenLinks(false);
    conversation->addWidget(chat, 1);
    auto *taskCard = new QFrame;
    taskCard->setObjectName("taskCard");
    auto *taskLayout = new QVBoxLayout(taskCard);
    taskLayout->setContentsMargins(12, 10, 12, 10);
    taskLayout->setSpacing(7);
    auto *taskHeader = new QHBoxLayout;
    taskTitle = new QLabel("Starting workspace");
    taskTitle->setObjectName("taskTitle");
    taskHeader->addWidget(taskTitle, 1);
    taskElapsed = new QLabel;
    taskElapsed->setObjectName("muted");
    taskHeader->addWidget(taskElapsed);
    taskLayout->addLayout(taskHeader);
    taskActivity = new QLabel("Opening the local CAD service…");
    taskActivity->setObjectName("taskActivity");
    taskActivity->setWordWrap(true);
    taskLayout->addWidget(taskActivity);
    taskProgress = new QProgressBar;
    taskProgress->setObjectName("taskProgress");
    taskProgress->setRange(0, 0);
    taskProgress->setTextVisible(false);
    taskProgress->setFixedHeight(3);
    taskProgress->hide();
    taskLayout->addWidget(taskProgress);
    auto *details = new QToolButton;
    details->setObjectName("activityDetails");
    details->setText("Activity");
    details->hide();
    details->setCheckable(true);
    details->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    details->setArrowType(Qt::RightArrow);
    details->setStyleSheet("text-align:left;border:0;padding:0;");
    taskLayout->addWidget(details, 0, Qt::AlignLeft);
    taskLog = new QPlainTextEdit;
    taskLog->setReadOnly(true);
    taskLog->setMaximumHeight(125);
    taskLog->hide();
    taskLayout->addWidget(taskLog);
    connect(details, &QToolButton::toggled, this, [this, details](bool show) {
        taskLog->setVisible(show);
        details->setArrowType(show ? Qt::DownArrow : Qt::RightArrow);
    });
    conversation->addWidget(taskCard);
    auto *composerFrame = new QFrame;
    composerFrame->setObjectName("composerFrame");
    auto *compose = new QVBoxLayout(composerFrame);
    compose->setContentsMargins(10, 8, 10, 8);
    compose->setSpacing(7);
    selectionChip = new QPushButton;
    selectionChip->setObjectName("selectionChip");
    selectionChip->hide();
    selectionChip->setToolTip("Remove selection context from the next task");
    compose->addWidget(selectionChip);
    composer = new QPlainTextEdit;
    composer->setPlaceholderText("Describe a design or ask for a change…");
    composer->setFixedHeight(68);
    compose->addWidget(composer);
    auto *providerRow = new QHBoxLayout;
    models = new QComboBox;
    models->setMinimumContentsLength(7);
    models->setSizeAdjustPolicy(QComboBox::AdjustToMinimumContentsLengthWithIcon);
    models->setPlaceholderText("Choose model");
    providerRow->addWidget(models, 1);
    stopButton = button("Stop", providerRow, [this] {
        rpc->cancel();
        updateTask("cancelling", "Discarding the unaccepted candidate. Your saved design is preserved.");
        stopButton->setEnabled(false);
    });
    stopButton->hide();
    sendButton = button("↑", providerRow, [this] { submit(); });
    sendButton->setObjectName("primaryButton");
    sendButton->setFixedSize(30, 30);
    sendButton->setAccessibleName("Send request");
    sendButton->setToolTip("Send · Ctrl+Enter");
    sendButton->setEnabled(false);
    compose->addLayout(providerRow);
    conversation->addWidget(composerFrame);
    auto *usageRow = new QHBoxLayout;
    usageBadge = new QPushButton("Usage unavailable");
    usageBadge->setObjectName("usageBadge");
    usageRow->addWidget(usageBadge);
    tokenUsageLabel = new QLabel;
    tokenUsageLabel->setObjectName("muted");
    usageRow->addWidget(tokenUsageLabel, 1, Qt::AlignRight);
    conversation->addLayout(usageRow);
    connect(usageBadge, &QPushButton::clicked, this, [this] {
        if (!state.value("provider").toObject().value("active").toObject().value("connected").toBool()) {
            account();
            return;
        }
        QMenu menu;
        for (auto line : usageBadge->toolTip().split('\n'))
            menu.addAction(line)->setEnabled(false);
        menu.addSeparator();
        auto *refresh = menu.addAction("Refresh allowance");
        refresh->setEnabled(!busy);
        auto *manage = menu.addAction("Manage provider usage ↗");
        auto *choice = menu.exec(usageBadge->mapToGlobal(QPoint(0, 0)));
        if (choice == refresh)
            refreshUsage();
        if (choice == manage) {
            const bool api =
                state.value("provider").toObject().value("active").toObject().value("connection") == "api";
            QDesktopServices::openUrl(
                QUrl(api ? "https://platform.openai.com/usage" : "https://chatgpt.com/settings/usage"));
        }
    });
    taskPulse = new QTimer(this);
    taskPulse->setInterval(1000);
    connect(taskPulse, &QTimer::timeout, this, [this] {
        const qint64 seconds = taskClock.isValid() ? taskClock.elapsed() / 1000 : 0;
        taskElapsed->setText(QString("%1:%2").arg(seconds / 60).arg(seconds % 60, 2, 10, QChar('0')));
    });
    chatRefresh = new QTimer(this);
    chatRefresh->setSingleShot(true);
    chatRefresh->setInterval(100);
    connect(chatRefresh, &QTimer::timeout, this, &WorkspaceWindow::renderChat);
    connect(composer, &QPlainTextEdit::textChanged, this, [this] {
        composer->setFixedHeight(
            qBound(68, composer->fontMetrics().lineSpacing() * (composer->blockCount() + 1) + 16, 140));
        sendButton->setEnabled(!busy && !state.value("project").toObject().isEmpty() &&
                               !composer->toPlainText().trimmed().isEmpty());
    });
    split->addWidget(conversationPane);
    split->setSizes({245, 915, 360});
    split->setStretchFactor(1, 1);
    navigation->setMinimumWidth(190);
    manager->setMinimumWidth(185);
    conversationPane->setMinimumWidth(290);
    auto *file = menuBar()->addMenu("&File");
    file->addAction("New project…", this, &WorkspaceWindow::newProject, QKeySequence::New);
    file->addAction("Import model…", this, [this] { openFile(); }, QKeySequence::Open);
    file->addAction("Open native project…", this, [this] {
        auto p = QFileDialog::getExistingDirectory(this, "Open native CAD document");
        if (!p.isEmpty())
            call("v2.open_native", {{"path", p}});
    });
    file->addAction(
        "Save", this,
        [this] { activity->setText("All accepted revisions and conversations are saved atomically."); },
        QKeySequence::Save);
    file->addAction("Export STEP / STL / GLB…", this, [this] {
        auto p = QFileDialog::getSaveFileName(this, "Export model", QDir::homePath() + "/Design.step",
                                              "STEP (*.step);;STL (*.stl);;GLB (*.glb)");
        if (!p.isEmpty()) {
            auto args = base();
            args["path"] = p;
            call("v2.export", args,
                 [this](auto r) { activity->setText("Exported " + r.value("path").toString()); });
        }
    });
    file->addSeparator();
    file->addAction("Exit", this, &QWidget::close);
    auto *edit = menuBar()->addMenu("&Edit");
    undoAction =
        edit->addAction("Undo revision", this, [this] { call("v2.undo", base()); }, QKeySequence::Undo);
    redoAction =
        edit->addAction("Redo revision", this, [this] { call("v2.redo", base()); }, QKeySequence::Redo);
    connect(undoAction, &QAction::changed, this,
            [this] { findChild<QPushButton *>("undoToolbar")->setEnabled(undoAction->isEnabled()); });
    connect(redoAction, &QAction::changed, this,
            [this] { findChild<QPushButton *>("redoToolbar")->setEnabled(redoAction->isEnabled()); });
    auto *viewMenu = menuBar()->addMenu("&View");
    for (auto pair : QList<QPair<QString, QWidget *>>{{"Projects and conversations", navigation},
                                                      {"CAD manager", manager},
                                                      {"Agent panel", conversationPane}}) {
        auto *a = viewMenu->addAction(pair.first);
        connect(a, &QAction::triggered, this, [pair] { pair.second->setVisible(!pair.second->isVisible()); });
    }
    viewMenu->addAction("Fit model", viewer, &CadView::fitAll);
    viewMenu->addAction("Hide selected", this, [this] {
        viewer->setVisibleInstance(selected.value("instance_id").toString(), false);
    });
    viewMenu->addAction("Isolate selected", this,
                        [this] { viewer->isolateInstance(selected.value("instance_id").toString()); });
    viewMenu->addAction("Show all", viewer, &CadView::showAll);
    auto *edgesAction = viewMenu->addAction("Show solid edges");
    edgesAction->setCheckable(true);
    edgesAction->setChecked(true);
    connect(edgesAction, &QAction::toggled, viewer, &CadView::setShading);
    for (auto *action : viewMenu->actions())
        if (QStringList{"Fit model", "Hide selected", "Isolate selected", "Show all", "Show solid edges"}
                .contains(action->text()))
            viewCommands->addAction(action);
    auto *toolsMenu = menuBar()->addMenu("&Tools");
    toolsMenu->addAction("Settings…", this, &WorkspaceWindow::account);
    toolsMenu->addAction("Manage archived and deleted items…", this, &WorkspaceWindow::manageProjects);
    toolsMenu->addAction("Discover available models", this, &WorkspaceWindow::discoverModels);
    toolsMenu->addAction("Restart provider session for this conversation", this,
                         [this] { call("v2.conversation.restart_session"); });
    toolsMenu->addAction("CAD script…", this, [this] {
        bool ok;
        auto script = QInputDialog::getMultiLineText(
            this, "Restricted CAD script",
            "Use cq.Workplane and assign parts={name: solid}. Files, imports and "
            "shell are unavailable.",
            "parts = {'block': cq.Workplane('XY').box(40, 30, 10)}", &ok);
        if (ok && !script.trimmed().isEmpty()) {
            auto p = base();
            p["source"] = script;
            p["parameters"] = QJsonObject{};
            if (!selected.isEmpty()) {
                p["selection"] = selected;
                p["instance_id"] = selected.value("instance_id");
            }
            call("v2.script", p);
        }
    });
    auto *help = menuBar()->addMenu("&Help");
    help->addAction("Supported capabilities", this, [this] {
        QMessageBox::information(this, "Prompt to CAD V2",
                                 "Engineering: STEP and editable CAD recipes; precise solids, local "
                                 "face/edge operations and "
                                 "restricted CAD scripts.\nAccepted changes are verified and undoable. "
                                 "Imported solids do not "
                                 "contain original feature history.\nMeasurement reports are "
                                 "available through Inspect. Interactive sections are future "
                                 "scope.\nAgent tasks consume your "
                                 "connected allowance; long tasks can consume more usage. API keys are "
                                 "billed separately.");
    });
    auto *commandSearch = new QAction("Command search", this);
    commandSearch->setObjectName("commandSearch");
    commandSearch->setShortcut(QKeySequence("Ctrl+K"));
    addAction(commandSearch);
    connect(commandSearch, &QAction::triggered, this, [this] {
        QStringList names;
        QList<QAction *> choices;
        for (auto *m : menuBar()->actions())
            if (m->menu())
                for (auto *a : m->menu()->actions())
                    if (!a->isSeparator()) {
                        names << a->text().remove('&');
                        choices << a;
                    }
        bool ok;
        auto name = QInputDialog::getItem(this, "Command search", "Command", names, 0, true, &ok);
        if (ok) {
            auto i = names.indexOf(name);
            if (i >= 0)
                choices[i]->trigger();
        }
    });
    activity = new QLabel("Starting local CAD service…");
    statusBar()->addWidget(activity, 1);
    auto *units = new QLabel("mm  ·  Local workspace");
    statusBar()->addPermanentWidget(units);
    connect(new QShortcut(QKeySequence("Ctrl+Return"), this), &QShortcut::activated, this,
            &WorkspaceWindow::submit);
    connect(selectionChip, &QPushButton::clicked, this, [this] {
        selected = {};
        selectionChip->hide();
    });
    connect(selectionMode, &QComboBox::currentTextChanged, this,
            [this](const QString &kind) { viewer->setSelectionMode(kind.toLower()); });
    connect(viewer, &CadView::selectionChanged, this, &WorkspaceWindow::select);
    connect(viewer, &CadView::viewerError, this, [this](const QString &e) {
        viewerFailed = true;
        showError(e);
    });
    connect(treeFilter, &QLineEdit::textChanged, this, [this](const QString &filter) {
        std::function<bool(QTreeWidgetItem *)> include = [&](QTreeWidgetItem *item) {
            bool visible = item->text(0).contains(filter, Qt::CaseInsensitive);
            for (int i = 0; i < item->childCount(); ++i)
                visible = include(item->child(i)) || visible;
            item->setHidden(!visible);
            if (!filter.isEmpty() && visible)
                item->setExpanded(true);
            return visible;
        };
        for (int i = 0; i < modelTree->topLevelItemCount(); ++i)
            include(modelTree->topLevelItem(i));
    });
    connect(search, &QLineEdit::textChanged, this, [this](const QString &filter) {
        for (int i = 0; i < projects->topLevelItemCount(); ++i) {
            auto *p = projects->topLevelItem(i);
            bool found = p->text(0).contains(filter, Qt::CaseInsensitive);
            for (int j = 0; j < p->childCount(); ++j) {
                bool match = p->child(j)->text(0).contains(filter, Qt::CaseInsensitive);
                p->child(j)->setHidden(!match && !found);
                found |= match;
            }
            p->setHidden(!found);
        }
    });
    connect(projects, &QTreeWidget::itemClicked, this, [this](QTreeWidgetItem *item, int) {
        if (busy || loading)
            return;
        auto pid = item->data(0, Qt::UserRole).toString();
        auto cid = item->data(0, Qt::UserRole + 1).toString();
        if (!cid.isEmpty())
            call("v2.conversation.open", {{"project_id", pid}, {"conversation_id", cid}});
        else if (pid != state.value("project").toObject().value("project_id").toString())
            call("v2.project.open", {{"project_id", pid}});
    });
    projects->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(projects, &QTreeWidget::customContextMenuRequested, this, [this](QPoint position) {
        auto *item = projects->itemAt(position);
        if (!item || busy)
            return;
        auto cid = item->data(0, Qt::UserRole + 1).toString();
        auto pid = item->data(0, Qt::UserRole).toString();
        QMenu menu;
        auto *openFolder = menu.addAction("Open project folder ↗");
        menu.addSeparator();
        auto *rename = menu.addAction("Rename…");
        auto *archive = menu.addAction("Archive");
        auto *remove = menu.addAction("Move to trash…");
        auto *chosen = menu.exec(projects->viewport()->mapToGlobal(position));
        if (chosen == openFolder) {
            for (auto value : state.value("catalog").toObject().value("projects").toArray()) {
                auto p = value.toObject();
                if (p.value("project_id") == pid)
                    QDesktopServices::openUrl(QUrl::fromLocalFile(p.value("folder_path").toString()));
            }
            return;
        }
        QJsonObject args{{"project_id", pid}};
        QString method = cid.isEmpty() ? "v2.project.update" : "v2.conversation.update";
        args[cid.isEmpty() ? "project_id" : "conversation_id"] = cid.isEmpty() ? pid : cid;
        if (chosen == rename) {
            bool ok;
            auto text = QInputDialog::getText(this, "Rename", "Name", QLineEdit::Normal, item->text(0), &ok);
            if (!ok)
                return;
            args[cid.isEmpty() ? "name" : "title"] = text;
        } else if (chosen == archive)
            args["archived"] = true;
        else if (chosen == remove) {
            if (QMessageBox::question(this, "Move to trash",
                                      "Keep the files on disk and hide this "
                                      "item? It can be restored from "
                                      "the project catalogue.") != QMessageBox::Yes)
                return;
            args["trashed"] = true;
        } else
            return;
        call(method, args);
    });
    connect(modelTree, &QTreeWidget::itemClicked, this, [this](QTreeWidgetItem *item, int) {
        if (!loading)
            viewer->selectInstance(item->data(0, Qt::UserRole).toString());
    });
    connect(modelTree, &QTreeWidget::itemChanged, this, [this](QTreeWidgetItem *item, int) {
        if (!loading)
            viewer->setVisibleInstance(item->data(0, Qt::UserRole).toString(),
                                       item->checkState(0) == Qt::Checked);
    });
    connect(revisions, &QTreeWidget::itemDoubleClicked, this, [this](QTreeWidgetItem *item, int) {
        auto p = base();
        p["revision_id"] = item->data(0, Qt::UserRole).toString();
        call("v2.restore", p);
    });
    connect(documentTabs, &QTabBar::currentChanged, this, [this](int index) {
        if (!loading && index >= 0)
            call("v2.document.open", {{"document_id", documentTabs->tabData(index).toString()}});
    });
    connect(chat, &QTextBrowser::anchorClicked, this, [this](const QUrl &link) {
        if (link.scheme() == "revision") {
            auto p = base();
            p["revision_id"] = link.path();
            call("v2.restore", p);
        } else if (link.scheme() == "component")
            viewer->selectInstance(link.path());
    });
    connect(rpc, &RpcClient::progress, this, [this](const QJsonObject &event) {
        auto stage = event.value("stage").toString();
        auto taskId = event.value("task_id").toString();
        if (!taskId.isEmpty() && taskId != activeTaskId)
            return;
        if (!taskId.isEmpty() &&
            event.value("conversation_id") != state.value("conversation").toObject().value("conversation_id"))
            return;
        if (stage == "usage") {
            if (event.contains("tokens")) {
                auto c = state.value("conversation").toObject();
                c["token_usage"] = event.value("tokens");
                state["conversation"] = c;
            }
            if (event.contains("usage")) {
                auto p = state.value("provider").toObject();
                p["usage"] = event.value("usage");
                state["provider"] = p;
            }
            updateUsage();
            return;
        }
        if (stage != "assistant_delta" && stage != "candidate" && !taskId.isEmpty()) {
            const auto message = event.value("message").toString();
            updateTask(event.value("state").toString("running"), message);
            taskLog->appendPlainText(message);
            findChild<QToolButton *>("activityDetails")->show();
        }
        if (stage == "clarification") {
            QJsonObject answers;
            for (auto value : event.value("questions").toArray()) {
                auto q = value.toObject();
                QStringList options;
                for (auto option : q.value("options").toArray())
                    options << option.toObject().value("label").toString();
                bool ok;
                QString answer =
                    options.isEmpty()
                        ? QInputDialog::getText(this, q.value("header").toString(),
                                                q.value("question").toString(), QLineEdit::Normal, {}, &ok)
                        : QInputDialog::getItem(this, q.value("header").toString(),
                                                q.value("question").toString(), options, 0, true, &ok);
                if (!ok) {
                    rpc->cancel();
                    return;
                }
                answers[q.value("id").toString()] = QJsonObject{{"answers", QJsonArray{answer}}};
            }
            rpc->call("provider.respond", {{"request_id", event.value("request_id")}, {"answers", answers}},
                      [this](auto, auto e) {
                          if (!e.isEmpty())
                              showError(e);
                      });
        } else if (stage == "assistant_delta") {
            liveAnswer += event.value("message").toString();
            if (!chatRefresh->isActive())
                chatRefresh->start();
        } else if (stage == "candidate") {
            viewer->setDocument(event.value("document").toObject(), false);
            saved->setText("Candidate preview · not accepted");
        } else if (stage == "connection") {
            activity->setText(event.value("message").toString());
            if (!busy)
                call("v2.state", {}, [this](auto r) {
                    if (r.value("provider").toObject().value("state") == "ready")
                        discoverModels();
                });
        } else
            activity->setText(event.value("message").toString());
    });
    connect(rpc, &RpcClient::stopped, this, [this](const QString &error) {
        Q_EMIT workspaceReady();
        showError(error);
    });
    connect(rpc, &RpcClient::ready, this, [this, openPath] {
        call("v2.state", {}, [this, openPath](auto r) {
            showState(r);
            Q_EMIT workspaceReady();
            if (!openPath.isEmpty())
                openFile(openPath);
            else if (smoke)
                showError("Smoke test requires a model.");
        });
    });
    QSettings prefs;
    auto savedModel = prefs.value("v2/model").toString();
    if (!savedModel.isEmpty())
        models->addItem(savedModel + " (saved; unverified)", savedModel);
    restoreGeometry(prefs.value("v2/geometry").toByteArray());
    split->restoreState(prefs.value("v2/panels").toByteArray());
    inner->restoreState(prefs.value("v2/modelPanels").toByteArray());
    navigation->setVisible(prefs.value("v2/navigationVisible", false).toBool());
    manager->setVisible(prefs.value("v2/managerVisible", true).toBool());
    conversationPane->setVisible(prefs.value("v2/conversationVisible", true).toBool());
    viewer->setShading(prefs.value("v2/edges", true).toBool());
    applyAppearance();
    rpc->start(workspace, python, "backend.v2.service");
}

WorkspaceWindow::~WorkspaceWindow() {
    QSettings p;
    p.setValue("v2/model", models->currentData().toString());
    p.setValue("v2/navigationVisible", navigation->isVisible());
    p.setValue("v2/managerVisible", manager->isVisible());
    p.setValue("v2/conversationVisible", conversationPane->isVisible());
    p.setValue("v2/geometry", saveGeometry());
    p.setValue("v2/panels", split->saveState());
    auto *inner = findChild<QSplitter *>("modelSplit");
    if (inner)
        p.setValue("v2/modelPanels", inner->saveState());
}
void WorkspaceWindow::resizeEvent(QResizeEvent *e) {
    QMainWindow::resizeEvent(e);
    if (width() < 1400)
        navigation->hide();
    if (width() < 1150)
        manager->hide();
}
QJsonObject WorkspaceWindow::base() const { return {{"base_revision_id", document.value("revision_id")}}; }
void WorkspaceWindow::showError(const QString &message) {
    qWarning().noquote() << message;
    activity->setText(message);
    chat->append("<p style='color:#efb6aa'>" + html(message) + "</p>");
    if (smoke)
        QApplication::exit(2);
}
void WorkspaceWindow::call(const QString &method, QJsonObject params, std::function<void(QJsonObject)> done) {
    if (busy) {
        showError("A task is running. Stop it before changing the document or "
                  "conversation.");
        return;
    }
    busy = true;
    sendButton->setEnabled(false);
    stopButton->setEnabled(method == "v2.task");
    stopButton->setVisible(method == "v2.task");
    undoAction->setEnabled(false);
    redoAction->setEnabled(false);
    rpc->call(method, params, [this, done](const QJsonObject &result, const QString &failure) {
        busy = false;
        sendButton->setEnabled(!composer->toPlainText().trimmed().isEmpty());
        stopButton->setEnabled(false);
        stopButton->hide();
        if (!failure.isEmpty()) {
            activeTaskId.clear();
            pendingUser.clear();
            liveAnswer.clear();
            Q_EMIT workspaceReady();
            updateTask("failed", failure);
            showError(failure);
            viewer->setDocument(document, false);
            saved->setText("Accepted document preserved");
            rpc->call("v2.state", {}, [this](auto r, auto e) {
                if (e.isEmpty())
                    showState(r);
            });
            return;
        }
        if (result.contains("catalog"))
            showState(result);
        if (done)
            done(result);
    });
}
void WorkspaceWindow::newProject() {
    auto *dialog = new QDialog(this);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setObjectName("newProjectDialog");
    dialog->setWindowTitle("New project");
    dialog->resize(500, 260);
    auto *layout = new QVBoxLayout(dialog);
    layout->setContentsMargins(24, 22, 24, 20);
    layout->setSpacing(14);
    auto *heading = new QLabel("New project");
    heading->setObjectName("pageTitle");
    layout->addWidget(heading);
    layout->addWidget(new QLabel("Project name"));
    auto *name = new QLineEdit;
    name->setObjectName("newProjectName");
    name->setPlaceholderText("e.g. Motor mounting bracket");
    layout->addWidget(name);
    auto *location =
        new QLabel("Saved in " +
                   QDir::toNativeSeparators(state.value("projects_root").toString(workspace + "/Projects")) +
                   "\nA folder is created using your project name.");
    location->setWordWrap(true);
    location->setObjectName("muted");
    layout->addWidget(location);
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel);
    buttons->button(QDialogButtonBox::Ok)->setText("Create project");
    buttons->button(QDialogButtonBox::Ok)->setObjectName("primaryButton");
    buttons->button(QDialogButtonBox::Ok)->setEnabled(false);
    layout->addWidget(buttons);
    connect(name, &QLineEdit::textChanged, dialog, [buttons](const QString &text) {
        buttons->button(QDialogButtonBox::Ok)->setEnabled(!text.trimmed().isEmpty());
    });
    connect(buttons, &QDialogButtonBox::rejected, dialog, &QDialog::reject);
    connect(buttons, &QDialogButtonBox::accepted, dialog, [this, name, dialog] {
        const auto title = name->text().trimmed();
        dialog->accept();
        call("v2.project.create", {{"name", title}}, [this](auto r) {
            activity->setText(
                "Created " +
                QDir::toNativeSeparators(r.value("project").toObject().value("folder_path").toString()));
        });
    });
    dialog->show();
    name->setFocus();
}
void WorkspaceWindow::openFile(const QString &supplied) {
    auto path = supplied;
    if (path.isEmpty())
        path = QFileDialog::getOpenFileName(this, "Import model", {},
                                            "CAD models (*.step *.stp *.json *.glb *.stl *.obj *.ply)");
    if (path.isEmpty())
        return;
    auto method = QFileInfo(path).isDir() || QFileInfo(path).fileName() == "project.json" ? "v2.open_native"
                                                                                          : "v2.import";
    QJsonObject args{{"path", path}};
    auto extension = QFileInfo(path).suffix().toLower();
    if (QStringList{"glb", "stl", "obj", "ply"}.contains(extension)) {
        bool ok;
        double scale =
            QInputDialog::getDouble(this, "Mesh units",
                                    "Millimetres per source unit (GLB commonly uses metres = 1000). "
                                    "Confirm the intended scale.",
                                    extension == "glb" ? 1000 : 1, 0.000001, 1000000, 6, &ok);
        if (!ok)
            return;
        args["mm_per_unit"] = scale;
    }
    call(method, args, [this](auto r) {
        showState(r, true);
        if (smoke)
            QTimer::singleShot(1200, this, &WorkspaceWindow::smokeCheck);
    });
}
void WorkspaceWindow::showState(const QJsonObject &value, bool fit) {
    loading = true;
    state = value;
    auto next = value.value("document").toObject();
    bool changed = next.value("revision_id") != document.value("revision_id") ||
                   next.value("document_id") != document.value("document_id");
    document = next;
    if (changed || fit) {
        viewer->setDocument(document, fit || changed);
        selected = {};
        selectionChip->hide();
        properties->clear();
        operationPane->hide();
    }
    const bool empty = document.value("components").toArray().isEmpty();
    emptyPage->setVisible(empty);
    viewer->setVisible(!empty);
    auto project = value.value("project").toObject();
    conversationTitle->setText(
        value.value("conversation").toObject().value("title").toString("Design conversation"));
    title->setText(project.value("name").toString("Create a project to begin") + "  /  " +
                   document.value("name").toString());
    setWindowTitle(project.isEmpty() ? "Prompt to CAD V2"
                                     : project.value("name").toString() + " · Prompt to CAD V2");
    saved->setText(document.value("components").toArray().isEmpty()
                       ? "Empty document"
                       : "Saved · " + document.value("revision_id").toString().left(8));
    undoAction->setEnabled(document.value("can_undo").toBool());
    redoAction->setEnabled(document.value("can_redo").toBool());
    auto previousDoc = project.value("active_document_id").toString();
    while (documentTabs->count())
        documentTabs->removeTab(0);
    for (auto d : project.value("documents").toArray()) {
        auto o = d.toObject();
        int i = documentTabs->addTab(o.value("name").toString());
        documentTabs->setTabData(i, o.value("document_id"));
        if (o.value("document_id").toString() == previousDoc)
            documentTabs->setCurrentIndex(i);
    }
    projects->clear();
    for (auto p : value.value("catalog").toObject().value("projects").toArray()) {
        auto o = p.toObject();
        if (o.value("archived").toBool() || o.value("trashed").toBool())
            continue;
        auto *item = new QTreeWidgetItem(projects, {o.value("name").toString()});
        item->setData(0, Qt::UserRole, o.value("project_id"));
        item->setExpanded(o.value("project_id") == project.value("project_id"));
        for (auto c : o.value("conversation_summaries").toArray()) {
            auto chatItem = c.toObject();
            if (chatItem.value("archived").toBool() || chatItem.value("trashed").toBool())
                continue;
            auto *child = new QTreeWidgetItem(item, {chatItem.value("title").toString()});
            child->setData(0, Qt::UserRole, o.value("project_id"));
            child->setData(0, Qt::UserRole + 1, chatItem.value("conversation_id"));
            if (chatItem.value("conversation_id") ==
                value.value("conversation").toObject().value("conversation_id"))
                projects->setCurrentItem(child);
        }
    }
    modelTree->clear();
    QMap<QString, QTreeWidgetItem *> groups;
    for (auto node : document.value("assembly_nodes").toArray()) {
        auto o = node.toObject();
        auto *item = new QTreeWidgetItem({o.value("name").toString()});
        auto *parent = groups.value(o.value("parent_id").toString(), nullptr);
        if (parent)
            parent->addChild(item);
        else
            modelTree->addTopLevelItem(item);
        item->setExpanded(true);
        groups.insert(o.value("id").toString(), item);
    }
    for (auto part : document.value("components").toArray()) {
        auto o = part.toObject();
        auto *item = new QTreeWidgetItem({o.value("name").toString()});
        auto *parent = groups.value(o.value("parent_id").toString(), nullptr);
        if (parent)
            parent->addChild(item);
        else
            modelTree->addTopLevelItem(item);
        item->setData(0, Qt::UserRole, o.value("instance_id"));
        item->setCheckState(0, Qt::Checked);
        item->setToolTip(0, o.value("representation") == "mesh"
                                ? "Visual mesh · explicit triangle regions; no original feature "
                                  "history"
                            : o.value("parameters").toObject().isEmpty()
                                ? "Solid geometry · original feature history unavailable"
                                : "Editable named parameters available in Properties");
    }
    revisions->clear();
    for (auto revision : document.value("history").toArray()) {
        auto o = revision.toObject();
        auto *item = new QTreeWidgetItem(revisions, {o.value("summary").toString().left(90)});
        item->setData(0, Qt::UserRole, o.value("revision_id"));
        item->setToolTip(0, o.value("revision_id").toString() + "\nDouble-click to restore this revision");
        if (o.value("revision_id") == document.value("revision_id"))
            revisions->setCurrentItem(item);
    }
    taskLog->clear();
    for (auto item : value.value("conversation").toObject().value("messages").toArray())
        for (auto event : item.toObject().value("activity").toArray())
            taskLog->appendPlainText(event.toObject().value("message").toString());
    findChild<QToolButton *>("activityDetails")->setVisible(!taskLog->toPlainText().isEmpty());
    renderChat();
    auto connection = value.value("provider").toObject();
    auto active = connection.value("active").toObject();
    accountBadge->setText(active.isEmpty() ? "Account · sign in" : active.value("email").toString());
    accountBadge->setToolTip(connection.value("billing").toString());
    updateUsage();
    activity->setText("mm · " + QString::number(document.value("components").toArray().size()) +
                      " components · " +
                      (active.isEmpty() ? "Agent disconnected" : connection.value("billing").toString()));
    if (!busy) {
        const auto taskState = value.value("task_state").toString();
        if (QStringList{"completed", "completed_no_change", "failed", "cancelled", "usage_limit"}.contains(
                taskState))
            updateTask(taskState, taskActivity->text());
        else
            updateTask(connection.value("state") == "ready" ? "idle" : "disconnected",
                       connection.value("state") == "ready" ? "Select geometry or send a design request."
                                                            : "Sign in from Settings to start a CAD task.");
    }
    sendButton->setEnabled(!busy && !project.isEmpty() && !composer->toPlainText().trimmed().isEmpty());
    loading = false;
}
void WorkspaceWindow::select(const QJsonObject &selection) {
    if (selection.isEmpty()) {
        selected = {};
        selectionChip->hide();
        return;
    }
    selected = selection;
    selected["document_id"] = document.value("document_id");
    selected["project_id"] = state.value("project").toObject().value("project_id");
    auto id = selection.value("instance_id").toString();
    for (auto p : document.value("components").toArray()) {
        auto part = p.toObject();
        if (part.value("instance_id").toString() != id)
            continue;
        auto name = part.value("name").toString();
        selectionChip->setText("Selected: " + name + " → " + selection.value("kind").toString() + " " +
                               QString::number(selection.value("index").toInt()) + "  ×");
        selectionChip->show();
        auto metrics = part.value("metrics").toObject();
        auto bounds = metrics.value("bounds_mm").toArray();
        QString body = "<h3>" + html(name) + "</h3><p>" + html(selection.value("kind").toString()) +
                       " · mm · revision " + html(document.value("revision_id").toString().left(8)) + "</p>";
        if (bounds.size() == 2) {
            auto low = bounds[0].toArray(), high = bounds[1].toArray();
            body += "<table cellspacing='8'><tr><th "
                    "align='left'>Dimensions</th><th>mm</th></tr>";
            for (int axis = 0; axis < 3; ++axis)
                body += "<tr><td>" + QStringList{"X", "Y", "Z"}[axis] + "</td><td>" +
                        QString::number(high[axis].toDouble() - low[axis].toDouble(), 'f', 3) + "</td></tr>";
            body += "</table>";
        }
        if (metrics.contains("volume_mm3"))
            body +=
                "<p>Volume · " + QString::number(metrics.value("volume_mm3").toDouble(), 'f', 3) + " mm³</p>";
        auto parameters = part.value("parameters").toObject();
        if (!parameters.isEmpty()) {
            body += "<h4>Editable parameters</h4><table cellspacing='8'>";
            for (auto it = parameters.begin(); it != parameters.end(); ++it)
                body += "<tr><td>" + html(it.key()) + "</td><td>" + QString::number(it.value().toDouble()) +
                        "</td></tr>";
            body += "</table><p>Modify → Named parameters</p>";
        } else
            body += "<p>Original feature history unavailable.</p>";
        auto matrix = part.value("matrix").toArray();
        if (matrix.size() == 12)
            body += "<h4>World placement / mm</h4><p>X " + QString::number(matrix[3].toDouble()) + " · Y " +
                    QString::number(matrix[7].toDouble()) + " · Z " + QString::number(matrix[11].toDouble()) +
                    "</p>";
        properties->setHtml(body);
        for (QTreeWidgetItemIterator it(modelTree); *it; ++it)
            if ((*it)->data(0, Qt::UserRole).toString() == id) {
                QSignalBlocker block(modelTree);
                modelTree->setCurrentItem(*it);
                for (auto *parent = (*it)->parent(); parent; parent = parent->parent())
                    parent->setExpanded(true);
                break;
            }
    }
    activity->setText("Selected " + id + " · " + selection.value("kind").toString() + " · mm");
}
void WorkspaceWindow::submit() {
    if (busy || composer->toPlainText().trimmed().isEmpty())
        return;
    auto p = base();
    auto capture =
        QDir::tempPath() + "/promptcad-" + QUuid::createUuid().toString(QUuid::WithoutBraces) + ".png";
    if (viewer->bodyCount() > 0 && viewer->saveViewport(capture))
        p["viewport_path"] = capture;
    p["prompt"] = composer->toPlainText();
    p["model"] = models->currentData().toString();
    activeTaskId = QUuid::createUuid().toString(QUuid::WithoutBraces).remove('-');
    p["task_id"] = activeTaskId;
    taskLog->clear();
    findChild<QToolButton *>("activityDetails")->hide();
    pendingUser = composer->toPlainText();
    liveAnswer.clear();
    taskClock.restart();
    taskElapsed->setText("0:00");
    updateTask("connecting", "Preparing the current document and selected geometry.");
    if (!selected.isEmpty())
        p["selection"] = selected;
    QTimer::singleShot(0, this, &WorkspaceWindow::renderChat);
    call("v2.task", p, [this](auto) {
        composer->clear();
        pendingUser.clear();
        liveAnswer.clear();
        activeTaskId.clear();
    });
}
void WorkspaceWindow::discoverModels() {
    call("provider.models", {}, [this](auto r) {
        auto old = models->currentData();
        models->clear();
        for (auto value : r.value("models").toArray()) {
            auto model = value.toObject();
            models->addItem(model.value("name").toString(), model.value("id"));
            models->setItemData(models->count() - 1, model.value("access"), Qt::ToolTipRole);
        }
        int i = models->findData(old);
        if (i >= 0)
            models->setCurrentIndex(i);
        activity->setText("Models discovered. Availability is verified only by "
                          "successful inference.");
    });
}
void WorkspaceWindow::operation(const QString &kind) {
    if (busy)
        return;
    if (kind != "block" && selected.isEmpty()) {
        showError("Select the component or face to modify.");
        return;
    }
    currentOperation = kind;
    operationSelection = selected;
    fields.clear();
    while (operationForm->count()) {
        auto *item = operationForm->takeAt(0);
        if (item->widget())
            delete item->widget();
        delete item;
    }
    operationForm->addRow(new QLabel(kind == "block" ? "Create · editable block" : "Modify · " + kind));
    auto field = [this](const QString &label, double value, double minimum = -10000) {
        auto *input = new QDoubleSpinBox;
        input->setRange(minimum, 10000);
        input->setDecimals(3);
        input->setValue(value);
        fields << input;
        operationForm->addRow(label, input);
    };
    if (kind == "block") {
        field("Width / mm", 40, 0.01);
        field("Depth / mm", 30, 0.01);
        field("Height / mm", 10, 0.01);
    } else if (kind == "parameters") {
        for (auto p : document.value("components").toArray()) {
            auto part = p.toObject();
            if (part.value("instance_id") == selected.value("instance_id")) {
                auto parameters = part.value("parameters").toObject();
                for (auto it = parameters.begin(); it != parameters.end(); ++it) {
                    field(it.key(), it.value().toDouble());
                    fields.last()->setProperty("parameter", it.key());
                }
            }
        }
        if (fields.isEmpty()) {
            showError("This component has no editable named parameters.");
            operationPane->hide();
            return;
        }
    } else if (kind == "move") {
        field("World X / mm", 20);
        field("World Y / mm", 0);
        field("World Z / mm", 0);
    } else if (kind == "mesh_scale")
        field("Uniform scale", 1.1, 0.001);
    else if (kind == "mesh_separate")
        operationForm->addRow(
            new QLabel("Separate explicitly selected triangles into another mesh component."));
    else if (kind == "thickness")
        field("Face offset / mm", 4);
    else if (kind == "holes") {
        field("Diameter / mm", 5, 0.01);
        field("Face local X / mm", 0);
        field("Face local Y / mm", 0);
        field("Depth / mm", 100, 0.01);
    } else
        field("Size / mm", 1, 0.01);
    auto *apply = new QPushButton("Apply and validate");
    operationForm->addRow(apply);
    connect(apply, &QPushButton::clicked, this, &WorkspaceWindow::applyOperation);
    auto *close = new QPushButton("Close");
    operationForm->addRow(close);
    connect(close, &QPushButton::clicked, operationPane, &QWidget::hide);
    manager->show();
    operationPane->show();
}
void WorkspaceWindow::applyOperation() {
    if (currentOperation != "block" && selected != operationSelection) {
        showError("The selection changed. Reopen the operation for the current target.");
        return;
    }
    auto p = base();
    if (currentOperation == "block") {
        p["source"] = QString("parts = {'block_%1': cq.Workplane('XY').box(params['width'], "
                              "params['depth'], "
                              "params['height'])}")
                          .arg(QDateTime::currentMSecsSinceEpoch());
        p["parameters"] = QJsonObject{
            {"width", fields[0]->value()}, {"depth", fields[1]->value()}, {"height", fields[2]->value()}};
        call("v2.script", p);
        return;
    }
    p["selection"] = selected;
    QJsonObject command{{"instance_id", selected.value("instance_id")}};
    if (currentOperation == "parameters") {
        QJsonObject values;
        for (auto *field : fields)
            values[field->property("parameter").toString()] = field->value();
        command["type"] = "parameters";
        command["values"] = values;
    } else if (currentOperation == "mesh_scale") {
        command["type"] = "mesh_scale";
        command["factor"] = fields[0]->value();
    } else if (currentOperation == "mesh_separate") {
        if (selected.value("kind") != "region") {
            showError("Choose Face mode and Ctrl-select mesh triangles to separate.");
            return;
        }
        command["type"] = "mesh_separate";
        command["triangle_indices"] = selected.value("triangle_indices");
    } else if (currentOperation == "move") {
        command["type"] = "transform";
        command["translation"] = QJsonArray{fields[0]->value(), fields[1]->value(), fields[2]->value()};
    } else if (currentOperation == "thickness" || currentOperation == "holes") {
        if (selected.value("kind").toString() != "face") {
            showError("Select a planar face in Face selection mode.");
            return;
        }
        command["face_index"] = selected.value("index");
        if (currentOperation == "thickness") {
            command["type"] = "offset_face";
            command["distance"] = fields[0]->value();
        } else {
            command["type"] = "face_holes";
            command["diameter"] = fields[0]->value();
            command["centres"] = QJsonArray{QJsonArray{fields[1]->value(), fields[2]->value()}};
            command["depth"] = fields[3]->value();
        }
    } else {
        auto edges = viewer->selectedEdges(selected.value("instance_id").toString());
        if (edges.isEmpty()) {
            showError("Select one or more edges (Ctrl adds edges).");
            return;
        }
        command["type"] = currentOperation;
        command["size"] = fields[0]->value();
        command["edge_indices"] = edges;
    }
    p["command"] = command;
    call("v2.command", p);
}
void WorkspaceWindow::smokeCheck() {
    if (!settingsVerified) {
        auto *trigger = findChild<QPushButton *>("settingsButton");
        for (int cycle = 0; cycle < 5; ++cycle) {
            for (int click = 0; click < 25; ++click)
                trigger->click();
            if (!settingsDialog || findChildren<QDialog *>("workspaceSettings").size() != 1) {
                showError("Settings singleton regression failed.");
                return;
            }
            auto *mode = settingsDialog->findChild<QComboBox *>("connectionMode");
            if (!mode || mode->count() != 2) {
                showError("Expected exactly two AI connections.");
                return;
            }
            auto before = QSettings().value("v2/edges", true).toBool();
            settingsDialog->findChild<QCheckBox *>("showEdges")->setChecked(!before);
            settingsDialog->reject();
            QApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
            if (settingsDialog || QSettings().value("v2/edges", true).toBool() != before) {
                showError("Settings cleanup or Cancel failed.");
                return;
            }
        }
        trigger->click();
        auto *dialog = settingsDialog.data();
        dialog->findChild<QCheckBox *>("showEdges")->setChecked(false);
        connect(dialog, &QDialog::accepted, this, [this] {
            QTimer::singleShot(0, this, [this] {
                if (settingsSaves != 1 || QSettings().value("v2/edges", true).toBool()) {
                    showError(QString("Settings Save regression: requests=%1, edges=%2")
                                  .arg(settingsSaves)
                                  .arg(QSettings().value("v2/edges", true).toBool()));
                    return;
                }
                settingsVerified = true;
                smokeCheck();
            });
        });
        dialog->grab().save(workspace + "/tmp/native-settings.png");
        if (auto *pages = dialog->findChild<QListWidget *>("settingsNavigation")) {
            pages->setCurrentRow(1);
            dialog->grab().save(workspace + "/tmp/native-appearance.png");
            pages->setCurrentRow(0);
        }
        auto *save = dialog->findChild<QDialogButtonBox *>("settingsActions")->button(QDialogButtonBox::Save);
        save->click();
        save->click();
        QTimer::singleShot(10000, this, [this] {
            if (!settingsVerified)
                showError("Settings save did not complete.");
        });
        return;
    }

    if (viewerFailed || viewer->bodyCount() != document.value("components").toArray().size() ||
        !viewer->smokeSelectFace()) {
        showError("Native V2 viewer import or topology selection failed.");
        return;
    }
    QDir().mkpath(workspace + "/tmp");
    QJsonObject report{
        {"passed", true},
        {"product", "Prompt to CAD V2"},
        {"body_count", viewer->bodyCount()},
        {"face_selection", true},
        {"settings_singleton_rapid_clicks", 125},
        {"settings_close_reopen_cycles", 5},
        {"settings_save_requests", settingsSaves},
        {"settings_display_change_saved", true},
        {"ai_connection_options", 2},
        {"theme", QSettings().value("v2/theme", "dark").toString()},
        {"named_project_folder",
         QFileInfo(state.value("project").toObject().value("folder_path").toString()).fileName() ==
             state.value("project").toObject().value("name").toString()},
        {"startup_logo_captured", QFileInfo::exists(workspace + "/tmp/native-startup.png")},
        {"usage_and_working_preview_are_fixtures", true},
        {"topology", viewer->topologyReport()},
        {"occt_viewer", OCC_VERSION_COMPLETE},
        {"qt_version", QT_VERSION_STR},
        {"synthetic_orbit_fps", viewer->benchmarkOrbit()},
        {"agent_inference_verified", false},
        {"window_size", QJsonArray{width(), height()}},
        {"viewport_size", QJsonArray{viewer->width(), viewer->height()}},
        {"device_pixel_ratio", viewer->devicePixelRatioF()}};
    QFile file(workspace + "/tmp/native-smoke-report.json");
    if (file.open(QIODevice::WriteOnly))
        file.write(QJsonDocument(report).toJson());
    auto path = workspace + "/tmp/native-viewport.png";
    if (!viewer->saveViewport(path)) {
        showError("Viewport capture failed.");
        return;
    }
    auto shot = grab();
    QPainter painter(&shot);
    painter.drawImage(QRect(viewer->mapTo(this, QPoint(0, 0)), viewer->size()), QImage(path));
    painter.end();
    shot.save(workspace + "/tmp/native-workspace.png");
    auto originalProvider = state.value("provider").toObject();
    auto fixtureProvider = originalProvider;
    fixtureProvider["active"] =
        QJsonObject{{"connected", true}, {"connection", "chatgpt"}, {"email", "UI fixture"}};
    fixtureProvider["usage"] = QJsonObject{
        {"available", true},
        {"windows",
         QJsonArray{QJsonObject{{"label", "5-hour"}, {"remaining_percent", 86}, {"duration_minutes", 300}}}}};
    state["provider"] = fixtureProvider;
    busy = true;
    pendingUser = "Inspect the selected synthetic fixture.";
    liveAnswer = "This is a UI validation preview, not live agent inference.";
    updateTask("running", "UI test · synthetic activity and allowance.");
    stopButton->show();
    stopButton->setEnabled(true);
    taskClock.restart();
    renderChat();
    updateUsage();
    QApplication::processEvents();
    auto working = grab();
    QPainter workingPainter(&working);
    workingPainter.drawImage(QRect(viewer->mapTo(this, QPoint(0, 0)), viewer->size()), QImage(path));
    workingPainter.end();
    working.save(workspace + "/tmp/native-agent-working.png");
    busy = false;
    pendingUser.clear();
    liveAnswer.clear();
    state["provider"] = originalProvider;
    QApplication::exit(0);
}

void WorkspaceWindow::manageProjects() {
    auto *dialog = new QDialog(this);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowTitle("Project catalogue · restore archived or deleted items");
    auto *layout = new QVBoxLayout(dialog);
    auto *tree = new QTreeWidget;
    tree->setHeaderLabels({"Project / conversation", "State"});
    layout->addWidget(tree);
    for (auto projectValue : state.value("catalog").toObject().value("projects").toArray()) {
        auto p = projectValue.toObject();
        auto *project = new QTreeWidgetItem(
            tree, {p.value("name").toString(), p.value("trashed").toBool()    ? "Trash"
                                               : p.value("archived").toBool() ? "Archived"
                                                                              : "Active"});
        project->setData(0, Qt::UserRole, p.value("project_id"));
        for (auto conversationValue : p.value("conversation_summaries").toArray()) {
            auto c = conversationValue.toObject();
            auto *conversationItem = new QTreeWidgetItem(
                project, {c.value("title").toString(), c.value("trashed").toBool()    ? "Trash"
                                                       : c.value("archived").toBool() ? "Archived"
                                                                                      : "Active"});
            conversationItem->setData(0, Qt::UserRole, p.value("project_id"));
            conversationItem->setData(0, Qt::UserRole + 1, c.value("conversation_id"));
        }
        project->setExpanded(true);
    }
    auto *note = new QLabel("Trash is recoverable. Project files and accepted "
                            "revisions remain on disk.");
    note->setWordWrap(true);
    layout->addWidget(note);
    button("Restore selected item", layout, [this, tree, dialog] {
        auto *item = tree->currentItem();
        if (!item)
            return;
        QJsonObject p{
            {"project_id", item->data(0, Qt::UserRole).toString()}, {"archived", false}, {"trashed", false}};
        auto cid = item->data(0, Qt::UserRole + 1).toString();
        if (!cid.isEmpty())
            p["conversation_id"] = cid;
        call(cid.isEmpty() ? "v2.project.update" : "v2.conversation.update", p);
        dialog->close();
    });
    dialog->resize(600, 440);
    dialog->show();
}
