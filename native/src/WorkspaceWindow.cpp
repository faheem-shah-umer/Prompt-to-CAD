#include "WorkspaceWindow.h"
#include "CadView.h"
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
#include <QInputDialog>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QMenu>
#include <QMenuBar>
#include <QMessageBox>
#include <QPainter>
#include <QPlainTextEdit>
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
    p.setPen(QPen(QColor("#b8c4d2"), 1.5, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
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
    auto *brand = new QLabel("P²");
    brand->setAlignment(Qt::AlignCenter);
    brand->setStyleSheet("font-size:21px;font-weight:600;color:#c5b4ee;padding:12px 0");
    railLayout->addWidget(brand);
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
    usage->setStyleSheet("color:#93939e;font-size:11px");
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
    saved->setStyleSheet("color:#8f929d");
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
    conversation->setContentsMargins(14, 14, 14, 12);
    conversationTitle = new QLabel("Design conversation");
    conversationTitle->setWordWrap(true);
    conversationTitle->setStyleSheet("font-size:15px;font-weight:600");
    conversation->addWidget(conversationTitle);
    chat = new QTextBrowser;
    chat->setOpenExternalLinks(false);
    chat->setPlaceholderText("Describe a part and its dimensions, or "
                             "select geometry to focus a change.");
    conversation->addWidget(chat, 1);
    taskActivity = new QLabel("Ready for a design request");
    taskActivity->setWordWrap(true);
    taskActivity->setMaximumHeight(54);
    taskActivity->setObjectName("taskActivity");
    conversation->addWidget(taskActivity);
    auto *details = new QToolButton;
    details->setText("Activity details");
    details->setCheckable(true);
    details->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    details->setArrowType(Qt::RightArrow);
    conversation->addWidget(details);
    taskLog = new QPlainTextEdit;
    taskLog->setReadOnly(true);
    taskLog->setMaximumHeight(140);
    taskLog->hide();
    conversation->addWidget(taskLog);
    connect(details, &QToolButton::toggled, this, [this, details](bool show) {
        taskLog->setVisible(show);
        details->setArrowType(show ? Qt::DownArrow : Qt::RightArrow);
    });

    selectionChip = new QPushButton;
    selectionChip->setObjectName("selectionChip");
    selectionChip->hide();
    selectionChip->setToolTip("Remove selection context from the next task");
    conversation->addWidget(selectionChip);
    composer = new QPlainTextEdit;
    composer->setPlaceholderText("Ask the agent to create or refine…\nCtrl+Enter to send");
    composer->setMinimumHeight(90);
    composer->setMaximumHeight(160);
    conversation->addWidget(composer);
    auto *providerRow = new QHBoxLayout;
    auto *providerName = new QLabel("Codex");
    providerRow->addWidget(providerName);
    models = new QComboBox;
    models->setMinimumContentsLength(8);
    models->setSizeAdjustPolicy(QComboBox::AdjustToMinimumContentsLengthWithIcon);
    models->setPlaceholderText("Connect and discover models");
    providerRow->addWidget(models, 1);
    conversation->addLayout(providerRow);
    auto *sendRow = new QHBoxLayout;
    sendRow->addStretch();
    sendButton = button("Send request", sendRow, [this] { submit(); });
    stopButton = button("Stop", sendRow, [this] {
        rpc->cancel();
        activity->setText("Stopping task; candidate will be discarded…");
    });
    sendButton->setObjectName("primaryButton");
    stopButton->setEnabled(false);
    conversation->addLayout(sendRow);
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
        auto *rename = menu.addAction("Rename…");
        auto *archive = menu.addAction("Archive");
        auto *remove = menu.addAction("Move to trash…");
        auto *chosen = menu.exec(projects->viewport()->mapToGlobal(position));
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
        if (stage != "assistant_delta" && stage != "candidate") {
            auto message = event.value("message").toString();
            auto taskState = event.value("state").toString();
            if (taskState == "completed")
                taskActivity->setText("Completed · geometry verified and saved");
            else if (taskState == "completed_no_change")
                taskActivity->setText("Completed · no geometry change");
            else if (taskState == "cancelled")
                taskActivity->setText("Cancelled · accepted model preserved");
            else if (taskState == "failed")
                taskActivity->setText("Task failed · accepted model preserved");
            else if (taskState == "usage_limit")
                taskActivity->setText("Usage limit reached · manage usage in Settings");
            else
                taskActivity->setText(message.left(180));
            taskLog->appendPlainText(message);
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
            chat->moveCursor(QTextCursor::End);
            chat->insertHtml(html(event.value("message").toString()));
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
    connect(rpc, &RpcClient::stopped, this, &WorkspaceWindow::showError);
    connect(rpc, &RpcClient::ready, this, [this, openPath] {
        call("v2.state", {}, [this, openPath](auto r) {
            showState(r);
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
    setStyleSheet(QString("QWidget { font-size:%1px; }").arg(prefs.value("v2/textSize", 12).toInt()));
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
    stopButton->setEnabled(true);
    undoAction->setEnabled(false);
    redoAction->setEnabled(false);
    rpc->call(method, params, [this, done](const QJsonObject &result, const QString &failure) {
        busy = false;
        sendButton->setEnabled(true);
        stopButton->setEnabled(false);
        if (!failure.isEmpty()) {
            activeTaskId.clear();
            taskActivity->setText(failure);
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
    bool ok;
    auto name = QInputDialog::getText(this, "New project", "Project name", QLineEdit::Normal,
                                      "Untitled project", &ok);
    if (ok)
        call("v2.project.create", {{"name", name}});
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
    chat->clear();
    taskLog->clear();
    for (auto message : value.value("conversation").toObject().value("messages").toArray()) {
        auto m = message.toObject();
        chat->append("<p style='color:#bbaadc'><b>" + html(m.value("role").toString()) + "</b></p><p>" +
                     html(m.value("content").toString()) + "</p>");
        for (auto event : m.value("activity").toArray())
            taskLog->appendPlainText(event.toObject().value("message").toString());
        auto change = m.value("change").toObject();
        if (!change.isEmpty()) {
            QString links;
            for (auto id : change.value("affected_components").toArray())
                links += "<a href='component:" + id.toString().toHtmlEscaped() + "'>" + html(id.toString()) +
                         "</a> ";
            chat->append("<p style='background:#282c32;padding:8px'>Changed: " + links +
                         "<br>Validated geometry and preserved task scope.<br><a "
                         "href='revision:" +
                         change.value("result_revision_id").toString() + "'>Restore revision " +
                         change.value("result_revision_id").toString().left(8) +
                         "</a> · Undo is available in Edit.</p>");
        }
    }
    auto connection = value.value("provider").toObject();
    auto active = connection.value("active").toObject();
    accountBadge->setText(active.isEmpty()
                              ? "Account · disconnected"
                              : active.value("email").toString() + "\n" +
                                    connection.value("billing").toString() + " · Usage unavailable");
    accountBadge->setToolTip("Allowance percentages are shown only when reported by the provider.");
    if (settingsDialog) {
        if (auto *label = settingsDialog->findChild<QLabel *>("connectionInfo"))
            label->setText(connection.value("billing").toString() + "\n" + active.value("email").toString() +
                           "\n" + active.value("workspace").toString());
    }
    activity->setText("mm · " + QString::number(document.value("components").toArray().size()) +
                      " components · " +
                      (active.isEmpty() ? "Agent disconnected" : connection.value("billing").toString()));
    if (!busy && !value.contains("task"))
        taskActivity->setText(connection.value("state") == "ready"
                                  ? "Ready for a design request"
                                  : "Connect in Settings to use the CAD agent");
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
    taskActivity->setText("Connecting to Codex…");
    if (!selected.isEmpty())
        p["selection"] = selected;
    chat->append("<p><b>You</b><br>" + html(composer->toPlainText()) + "</p><p><b>CAD agent</b></p>");
    call("v2.task", p, [this](auto) {
        composer->clear();
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
void WorkspaceWindow::account() {
    if (settingsDialog) {
        settingsDialog->showNormal();
        settingsDialog->raise();
        settingsDialog->activateWindow();
        return;
    }
    auto *dialog = new QDialog(this);
    settingsDialog = dialog;
    dialog->setObjectName("workspaceSettings");
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowTitle("Settings · Prompt to CAD V2");
    dialog->resize(620, 540);
    auto *layout = new QVBoxLayout(dialog);
    auto *tabs = new QTabWidget;
    layout->addWidget(tabs, 1);
    auto *ai = new QWidget;
    auto *connectionLayout = new QVBoxLayout(ai);
    auto *mode = new QComboBox;
    mode->setObjectName("connectionMode");
    mode->addItem("ChatGPT subscription — Codex", "chatgpt");
    mode->addItem("OpenAI API key — separately billed", "api");
    connectionLayout->addWidget(mode);
    auto *info = new QLabel;
    info->setObjectName("connectionInfo");
    info->setWordWrap(true);
    auto connection = state.value("provider").toObject();
    info->setText(connection.value("billing").toString() + "\n" +
                  connection.value("active").toObject().value("email").toString() + "\n" +
                  connection.value("active").toObject().value("workspace").toString());
    connectionLayout->addWidget(info);
    auto *plan = new QWidget;
    auto *planLayout = new QVBoxLayout(plan);
    planLayout->setContentsMargins(0, 0, 0, 0);
    auto *accounts = new QComboBox;
    accounts->setPlaceholderText("Saved ChatGPT registrations");
    for (auto a : connection.value("accounts").toArray()) {
        auto item = a.toObject();
        if (item.value("connection") == "chatgpt")
            accounts->addItem(item.value("email").toString() + " · " + item.value("workspace").toString(),
                              item.value("id"));
    }
    planLayout->addWidget(accounts);
    button("Continue with ChatGPT", planLayout, [this] {
        call("provider.login", {}, [this](auto r) {
            QDesktopServices::openUrl(QUrl(r.value("authorization_url").toString()));
            taskActivity->setText("Complete authorization in your browser. This app "
                                  "needs its own permission.");
        });
    });
    button("Reconnect saved registration", planLayout, [this, accounts] {
        if (accounts->currentIndex() >= 0)
            call("provider.login", {{"account_id", accounts->currentData().toString()}},
                 [](auto r) { QDesktopServices::openUrl(QUrl(r.value("authorization_url").toString())); });
    });
    button("Use saved registration", planLayout, [this, accounts] {
        if (accounts->currentIndex() >= 0)
            call("provider.select", {{"account_id", accounts->currentData().toString()}},
                 [this](auto) { call("v2.state"); });
    });
    button("Cancel pending sign-in", planLayout, [this] { call("provider.cancel_login"); });
    connectionLayout->addWidget(plan);
    auto *api = new QWidget;
    auto *apiLayout = new QVBoxLayout(api);
    apiLayout->setContentsMargins(0, 0, 0, 0);
    auto *key = new QLineEdit;
    key->setEchoMode(QLineEdit::Password);
    key->setPlaceholderText("Your OpenAI API key");
    apiLayout->addWidget(key);
    button("Validate and connect API key", apiLayout, [this, key] {
        auto value = key->text();
        key->clear();
        call("provider.api_key", {{"key", value}},
             [this](auto) { call("v2.state", {}, [this](auto) { discoverModels(); }); });
    });
    connectionLayout->addWidget(api);
    api->hide();
    connect(mode, &QComboBox::currentIndexChanged, dialog, [plan, api](int index) {
        plan->setVisible(index == 0);
        api->setVisible(index == 1);
    });
    mode->setCurrentIndex(connection.value("active").toObject().value("connection") == "api" ? 1 : 0);
    auto *billing = new QLabel("Tasks consume the selected plan allowance or API credits. "
                               "Long tasks may use more. Usage is unavailable from this "
                               "connection. Reaching a limit stops the request; billing "
                               "never switches automatically.\nConnection actions apply "
                               "immediately. Save applies display and runtime preferences.");
    billing->setWordWrap(true);
    billing->setObjectName("muted");
    connectionLayout->addWidget(billing);
    auto *actions = new QHBoxLayout;
    button("Discover models", actions, [this] { discoverModels(); });
    button("Disconnect", actions,
           [this] { call("provider.disconnect", {}, [this](auto) { call("v2.state"); }); });
    button("Manage usage", actions, [mode] {
        QDesktopServices::openUrl(QUrl(mode->currentIndex() == 0 ? "https://chatgpt.com/settings/usage"
                                                                 : "https://platform.openai.com/usage"));
    });
    connectionLayout->addLayout(actions);
    connectionLayout->addStretch();
    tabs->addTab(ai, "AI connection");
    QSettings prefs;
    auto *appearance = new QWidget;
    auto *appearanceLayout = new QFormLayout(appearance);
    auto *textSize = new QComboBox;
    textSize->addItem("Standard", 12);
    textSize->addItem("Larger", 14);
    textSize->setCurrentIndex(prefs.value("v2/textSize", 12).toInt() == 14 ? 1 : 0);
    appearanceLayout->addRow("Interface text", textSize);
    auto *navVisible = new QCheckBox("Show projects and conversations");
    navVisible->setChecked(navigation->isVisible());
    appearanceLayout->addRow(navVisible);
    tabs->addTab(appearance, "Appearance");
    auto *display = new QWidget;
    auto *displayLayout = new QFormLayout(display);
    auto *edges = new QCheckBox("Show solid edges");
    edges->setObjectName("showEdges");
    edges->setChecked(prefs.value("v2/edges", true).toBool());
    displayLayout->addRow(edges);
    auto *modelVisible = new QCheckBox("Show CAD manager");
    modelVisible->setChecked(manager->isVisible());
    displayLayout->addRow(modelVisible);
    displayLayout->addRow(new QLabel("Units: millimetres. Imported solids retain geometry; "
                                     "original feature history may be unavailable."));
    tabs->addTab(display, "CAD / display");
    auto *diagnostics = new QWidget;
    auto *diagnosticLayout = new QVBoxLayout(diagnostics);
    diagnosticLayout->addWidget(new QLabel("Prompt to CAD V2 · 0.4.0\nLocal OpenCascade geometry · Codex "
                                           "App Server"));
    auto *runtime = new QLineEdit(state.value("runtime").toObject().value("executable").toString());
    runtime->setPlaceholderText("Automatic Codex discovery");
    diagnosticLayout->addWidget(runtime);
    button("Choose Codex executable…", diagnosticLayout, [this, runtime] {
        auto path = QFileDialog::getOpenFileName(this, "Installed Codex executable", {}, "Codex (codex.exe)");
        if (!path.isEmpty())
            runtime->setText(path);
    });
    auto *probeInfo = new QLabel("Test checks the local runtime. Successful "
                                 "inference separately verifies model access.");
    probeInfo->setWordWrap(true);
    diagnosticLayout->addWidget(probeInfo);
    QPointer<QLabel> probeLabel(probeInfo);
    button("Test runtime", diagnosticLayout, [this, probeLabel] {
        call("provider.probe", {}, [probeLabel](auto r) {
            if (probeLabel)
                probeLabel->setText(r.value("message").toString());
        });
    });
    diagnosticLayout->addStretch();
    tabs->addTab(diagnostics, "Diagnostics / about");
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Save | QDialogButtonBox::Cancel);
    buttons->setObjectName("settingsActions");
    layout->addWidget(buttons);
    connect(buttons, &QDialogButtonBox::rejected, dialog, &QDialog::reject);
    connect(buttons, &QDialogButtonBox::accepted, dialog,
            [this, dialog, buttons, runtime, textSize, navVisible, modelVisible, edges] {
                if (busy)
                    return;
                busy = true;
                sendButton->setEnabled(false);
                buttons->button(QDialogButtonBox::Save)->setEnabled(false);
                ++settingsSaves;
                QPointer<QDialog> guard(dialog);
                const int fontSize = textSize->currentData().toInt();
                const bool showNavigation = navVisible->isChecked();
                const bool showManager = modelVisible->isChecked();
                const bool showEdges = edges->isChecked();
                rpc->call("provider.configure", {{"codex_path", runtime->text()}},
                          [this, guard, fontSize, showNavigation, showManager, showEdges](auto r, auto e) {
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
                              p.setValue("v2/textSize", fontSize);
                              p.setValue("v2/edges", showEdges);
                              p.sync();
                              if (p.status() != QSettings::NoError) {
                                  if (guard)
                                      guard->findChild<QDialogButtonBox *>("settingsActions")
                                          ->button(QDialogButtonBox::Save)
                                          ->setEnabled(true);
                                  showError("Display preferences could not be saved. Check access to local "
                                            "application settings.");
                                  return;
                              }
                              navigation->setVisible(showNavigation);
                              manager->setVisible(showManager);
                              viewer->setShading(showEdges);
                              setStyleSheet(QString("QWidget { font-size:%1px; }").arg(fontSize));
                              showState(r);
                              if (guard)
                                  guard->accept();
                          });
            });
    dialog->show();
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
    QJsonObject report{{"passed", true},
                       {"product", "Prompt to CAD V2"},
                       {"body_count", viewer->bodyCount()},
                       {"face_selection", true},
                       {"settings_singleton_rapid_clicks", 125},
                       {"settings_close_reopen_cycles", 5},
                       {"settings_save_requests", settingsSaves},
                       {"settings_display_change_saved", true},
                       {"ai_connection_options", 2},
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
