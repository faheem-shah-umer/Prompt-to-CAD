#include "WorkspaceWindow.h"
#include "WorkspaceControls.h"
#include "CadView.h"
#include "ConversationView.h"
#include "WorkspaceIcons.h"
#include "WorkspaceTheme.h"
#include <QAction>
#include <QActionGroup>
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
#include <QEvent>
#include <QKeyEvent>
#include <QInputMethodEvent>
#include <QScrollBar>
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
QString html(const QString &value) { return value.toHtmlEscaped().replace("\n", "<br>"); }
} // namespace

WorkspaceWindow::WorkspaceWindow(const QString &source, const QString &python, const QString &openPath,
                                 bool smokeTest)
    : workspace(source), smoke(smokeTest) {
    setWindowTitle("Prompt to CAD");
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
    setWorkspaceIcon(projectsToggle, "folder");
    projectsToggle->setAccessibleName("Projects and conversations");
    projectsToggle->setToolTip("Projects and conversations");
    auto *modelToggle = button("", railLayout, [this] { manager->setVisible(!manager->isVisible()); });
    setWorkspaceIcon(modelToggle, "cube");
    modelToggle->setAccessibleName("CAD manager");
    modelToggle->setToolTip("CAD manager");
    auto *chatToggle =
        button("", railLayout, [this] { conversationPane->setVisible(!conversationPane->isVisible()); });
    setWorkspaceIcon(chatToggle, "comment-alt");
    chatToggle->setAccessibleName("Agent conversation");
    chatToggle->setToolTip("Agent conversation");
    railLayout->addStretch();
    auto *settingsButton = button("", railLayout, [this] { account(); });
    setWorkspaceIcon(settingsButton, "settings");
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
    auto *heading = new QLabel("Prompt to CAD");
    heading->setStyleSheet("font-weight:600;font-size:15px;padding:6px 0 16px");
    nav->addWidget(heading);
    setWorkspaceIcon(button("New project", nav, [this] { newProject(); }), "add");
    setWorkspaceIcon(button("Open project…", nav, [this] { openNativeProject(); }), "folder-open");
    auto *newChat = button("New conversation", nav, [this] { newConversation(); });
    newChat->setObjectName("newConversationButton");
    setWorkspaceIcon(newChat, "comment-alt");
    search = new QLineEdit;
    search->setPlaceholderText("Search projects and conversations");
    search->addAction(workspaceIcon("search"), QLineEdit::LeadingPosition);
    auto *projectSearch = new QHBoxLayout;
    projectSearch->setSpacing(5);
    projectSearch->addWidget(search, 1);
    auto *sort = new QToolButton;
    sort->setObjectName("projectSort");
    sort->setIcon(workspaceIcon("arrows"));
    sort->setProperty("workspaceIcon", "arrows");
    sort->setAccessibleName("Sort projects");
    sort->setFixedSize(32, 32);
    sort->setPopupMode(QToolButton::InstantPopup);
    auto *sortMenu = new QMenu(sort);
    auto *sortGroup = new QActionGroup(sortMenu);
    const auto savedSort = QSettings().value("v2/projectSort", "changed").toString();
    const QList<QPair<QString, QString>> sorting{{"changed", "Recently changed"},
        {"name", "Name A–Z"}, {"name_desc", "Name Z–A"},
        {"created", "Newest created"}, {"opened", "Recently opened"}};
    for (const auto& option : sorting) {
        auto *action = sortMenu->addAction(option.second);
        action->setData(option.first);
        action->setCheckable(true);
        sortGroup->addAction(action);
        action->setChecked(option.first == savedSort);
        if (action->isChecked()) sort->setToolTip("Sort projects: " + option.second);
    }
    if (!sortGroup->checkedAction()) {
        sortGroup->actions().first()->setChecked(true);
        sort->setToolTip("Sort projects: Recently changed");
    }
    connect(sortGroup, &QActionGroup::triggered, this, [this, sort](QAction *action) {
        QSettings().setValue("v2/projectSort", action->data());
        sort->setToolTip("Sort projects: " + action->text());
        refreshProjectTree();
    });
    sort->setMenu(sortMenu);
    projectSearch->addWidget(sort);
    nav->addLayout(projectSearch);
    projects = new QTreeWidget;
    projects->setHeaderHidden(true);
    projects->setIndentation(14);
    nav->addWidget(projects, 1);
    auto *usage = new QLabel("Local workspace · files stay on this PC");
    usage->setWordWrap(true);
    usage->setObjectName("muted");
    nav->addWidget(usage);
    accountBadge = button("", railLayout, [this] { showAccountDetails(); });
    accountBadge->setFixedSize(34, 34);
    accountBadge->setAccessibleName("Account details");
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
    title->setSizePolicy(QSizePolicy::Ignored,QSizePolicy::Preferred);
    saved = new QLabel("Saved locally");
    saved->setObjectName("muted");
    documentHeader->addWidget(title, 1);
    documentHeader->addWidget(saved);
    auto *undoButton = button("", documentHeader, [this] {
        if (undoAction->isEnabled())
            undoAction->trigger();
    });
    undoButton->setObjectName("undoToolbar");
    undoButton->setFixedSize(32,32);
    undoButton->setAccessibleName("Undo");
    undoButton->setToolTip("Undo · Ctrl+Z");
    auto *redoButton = button("", documentHeader, [this] {
        if (redoAction->isEnabled())
            redoAction->trigger();
    });
    redoButton->setObjectName("redoToolbar");
    redoButton->setFixedSize(32,32);
    redoButton->setAccessibleName("Redo");
    redoButton->setToolTip("Redo · Ctrl+Y");
    auto *searchButton = button("", documentHeader, [this] {
        if (auto *a = findChild<QAction *>("commandSearch"))
            a->trigger();
    });

    searchButton->setObjectName("commandSearchButton");
    searchButton->setAccessibleName("Search commands");
    searchButton->setToolTip("Search commands · Ctrl+K");
    setWorkspaceIcon(searchButton, "search");
    setWorkspaceIcon(undoButton, "undo");
    setWorkspaceIcon(redoButton, "redo");
    for (int i = 0; i < documentHeader->count(); ++i)
        if (auto *b = qobject_cast<QPushButton *>(documentHeader->itemAt(i)->widget()))
            b->setMinimumWidth(34);
    searchButton->setFixedWidth(34);
    auto *headerFrame = new QFrame;
    headerFrame->setObjectName("documentHeader");
    headerFrame->setLayout(documentHeader);
    work->addWidget(headerFrame);
    documentTabs = new QTabBar;
    documentTabs->setExpanding(false);
    documentTabs->setDrawBase(false);
    work->addWidget(documentTabs);
    auto *commandGroups = new QTabWidget;
    commandGroups->setObjectName("commandManager");
    auto commandPage = [commandGroups](const QString &label) {
        auto *toolbar = new QToolBar;
        toolbar->setMovable(false);
        toolbar->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
        commandGroups->addTab(toolbar, label);
        return toolbar;
    };
    auto *commands = commandPage("Modify");
    auto add = [this, &commands](const QString &name, const QString &op) {
        auto *a = commands->addAction(name);
        auto icon = op == "block" ? "cube" : op == "move" ? "arrows" : op == "pattern" ? "add" : "edit";
        a->setProperty("workspaceIcon", icon);
        a->setIcon(workspaceIcon(icon));
        connect(a, &QAction::triggered, this, [this, op] { operation(op); });
    };
    add("Thickness", "thickness");
    add("Holes", "holes");
    add("Fillet", "fillet");
    add("Chamfer", "chamfer");
    add("Named parameters", "parameters");
    add("Mesh scale", "mesh_scale");
    add("Separate region", "mesh_separate");
    auto *colour = commands->addAction(workspaceIcon("edit"), "Colour");
    connect(colour, &QAction::triggered, this, [this] { chooseComponentColour(); });
    auto *engineering = commands->addAction(workspaceIcon("edit"), "Engineering information");
    connect(engineering, &QAction::triggered, this, [this] { editEngineeringRecord(); });
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
    manager->setObjectName("cadManager");
    auto *management = new QVBoxLayout(manager);
    management->setContentsMargins(9, 10, 9, 8);
    managerTabs = new QTabWidget;
    auto *modelPane = new QWidget;
    auto *modelLayout = new QVBoxLayout(modelPane);
    modelLayout->setContentsMargins(0, 8, 0, 0);
    treeFilter = new QLineEdit;
    treeFilter->setPlaceholderText("Filter model tree");
    modelLayout->addWidget(treeFilter);
    auto *visibilityControls = new QHBoxLayout;
    visibilityControls->setSpacing(5);
    auto *showModels = button("Show all", visibilityControls, [this] { viewer->showAll(); });
    auto *hideModels = button("Hide all", visibilityControls, [this] { viewer->hideAll(); });
    showModels->setObjectName("showAllModels");
    hideModels->setObjectName("hideAllModels");
    showModels->setToolTip("Show every component, including filtered models");
    hideModels->setToolTip("Hide every component, including filtered models");
    modelLayout->addLayout(visibilityControls);
    auto *selectionControls = new QHBoxLayout;
    selectionControls->setSpacing(5);
    auto *selectModels = button("Select all visible", selectionControls, [this] {
        const auto ids = viewer->visibleInstances();
        if (ids.size() > 256) {
            notify("There are more than 256 visible components. Hide some before selecting all.", "info");
            return;
        }
        selectionMode->setCurrentText("Body");
        viewer->selectInstances(ids);
    });
    selectModels->setObjectName("selectAllModels");
    selectModels->setToolTip("Select all visible components for the next task, including filtered models");
    auto *clearModels = button("Clear selection", selectionControls, [this] { viewer->removeSelectedEntity(-1); });
    clearModels->setObjectName("clearModelSelection");
    modelLayout->addLayout(selectionControls);
    modelTree = new QTreeWidget;
    modelTree->setHeaderHidden(true);
    modelLayout->addWidget(modelTree);
    properties = new QTextBrowser;
    properties->setOpenLinks(false);
    connect(properties, &QTextBrowser::anchorClicked, this, [this](const QUrl& link) {
        if (link.scheme() == "engineering") editEngineeringRecord(link.path() == "new" ? QString() : link.path());
        else if (link.scheme() == "appearance") chooseComponentColour(link.path() == "source");
    });
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
    agentButton = button("Assistant", conversationHeader, [this] { account(); });
    agentButton->setObjectName("quietButton");
    agentButton->setToolTip("Account and agent settings");
    conversation->addLayout(conversationHeader);
    chat = new ConversationView;
    chat->setObjectName("conversationHistory");
    conversation->addWidget(chat, 1);
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
    auto *imageScroll = new QScrollArea;
    imageScroll->setObjectName("attachmentDraftScroll"); imageScroll->setWidgetResizable(true);
    imageScroll->setFrameShape(QFrame::NoFrame); imageScroll->setMaximumHeight(130); imageScroll->hide();
    attachmentStrip = new QWidget;
    auto *imageLayout = new QVBoxLayout(attachmentStrip); imageLayout->setContentsMargins(0, 0, 0, 0); imageLayout->setSpacing(5);
    imageScroll->setWidget(attachmentStrip); compose->addWidget(imageScroll);
    auto *input = new ComposerEdit;
    composer = input;
    composer->setObjectName("conversationComposer");
    connect(input,&ComposerEdit::sendRequested,this,&WorkspaceWindow::submit);
    connect(input, &ComposerEdit::imageFilesAdded, this, &WorkspaceWindow::addImageFiles);
    connect(input, &ComposerEdit::imageAdded, this, &WorkspaceWindow::addPastedImage);
    composer->setPlaceholderText("Describe a design or ask for a change…");
    composer->setFixedHeight(68);
    compose->addWidget(composer);
    auto *providerRow = new QHBoxLayout;
    auto *attach = new QToolButton;
    attach->setObjectName("attachImages"); setWorkspaceIcon(attach, "paperclip"); attach->setFixedSize(28, 28);
    attach->setAccessibleName("Attach reference images"); attach->setToolTip("Attach reference images · paste or drop images into the composer");
    connect(attach, &QToolButton::clicked, this, [this] {
        if (imagePreflight || focusOpenDialog()) return;
        auto paths = QFileDialog::getOpenFileNames(this, "Attach reference images", {}, "Images (*.png *.jpg *.jpeg *.webp)");
        if (!paths.isEmpty()) addImageFiles(paths);
    });
    providerRow->addWidget(attach);
    auto *picker = new ModelPicker;
    models = picker;
    models->setObjectName("modelPicker");
    connect(picker,&ModelPicker::refreshRequested,this,[this] { discoverModels(true); });
    models->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    models->setSizePolicy(QSizePolicy::Maximum, QSizePolicy::Fixed);
    models->setMinimumWidth(0);
    models->setMaximumWidth(240);
    models->setPlaceholderText("Choose model");
    providerRow->addWidget(models);
    providerRow->addStretch(1);
    sendButton = button("", providerRow, [this] {
        if (taskRunning) {
            if (currentTaskState == "cancelling") return;
            rpc->cancel();
            updateTask("cancelling", "Discarding the unaccepted candidate. Your saved design is preserved.");
        } else submit();
    });
    setWorkspaceIcon(sendButton, "arrow-up", true);
    sendButton->setObjectName("primaryButton");
    sendButton->setFixedSize(30, 30);
    sendButton->setAccessibleName("Send request");
    sendButton->setToolTip("Send · Enter (Shift+Enter for a new line)");
    sendButton->setEnabled(false);
    compose->addLayout(providerRow);
    conversation->addWidget(composerFrame);
    auto *usageRow = new QHBoxLayout;
    usageBadge = new QPushButton;
    usageBadge->setObjectName("usageBadge");
    usageRow->addWidget(usageBadge);
    usageRow->addStretch();
    conversation->addLayout(usageRow);
    usageBadge->hide();
    connect(usageBadge, &QPushButton::clicked, this, [this] {
        showUsageDetails();
    });
    taskPulse = new QTimer(this);
    taskPulse->setInterval(1000);
    connect(taskPulse, &QTimer::timeout, this, &WorkspaceWindow::renderChat);
    chatRefresh = new QTimer(this);
    chatRefresh->setSingleShot(true);
    chatRefresh->setInterval(100);
    connect(chatRefresh, &QTimer::timeout, this, &WorkspaceWindow::renderChat);
    connect(composer, &QPlainTextEdit::textChanged, this, [this] {
        composer->setFixedHeight(
            qBound(68, composer->fontMetrics().lineSpacing() * (composer->blockCount() + 1) + 16, 140));
        updateSendControl();
    });
    split->addWidget(conversationPane);
    split->setSizes({245, 915, 360});
    split->setStretchFactor(1, 1);
    navigation->setMinimumWidth(190);
    manager->setMinimumWidth(185);
    conversationPane->setMinimumWidth(290);
    auto *file = menuBar()->addMenu("&File");
    file->addAction("New project…", this, &WorkspaceWindow::newProject, QKeySequence::New);
    file->addAction("New conversation", this, &WorkspaceWindow::newConversation, QKeySequence("Ctrl+Shift+N"));
    file->addAction("Import model…", this, [this] { openFile(); }, QKeySequence::Open);
    file->addAction("Open native project…", this, &WorkspaceWindow::openNativeProject);
    file->addAction(
        "Save", this,
        [this] { call("v2.project.save", {}, [this](auto) { saved->setText("Saved"); notify("Project saved.", "info"); }); },
        QKeySequence::Save);
    file->addAction("Save As…", this, &WorkspaceWindow::saveAs, QKeySequence("Ctrl+Shift+S"));
    file->addAction("Export STEP / STL / GLB…", this, [this] {
        if (busy || focusOpenDialog()) return;
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
        QStringList ids;
        for (const auto& value : selected.value("entities").toArray())
            ids << value.toObject().value("instance_id").toString();
        if (ids.isEmpty()) ids << selected.value("instance_id").toString();
        viewer->setVisibleInstances(ids, false);
    });
    viewMenu->addAction("Isolate selected", this, [this] {
        QStringList ids;
        for (const auto& value : selected.value("entities").toArray())
            ids << value.toObject().value("instance_id").toString();
        if (ids.isEmpty()) ids << selected.value("instance_id").toString();
        viewer->isolateInstances(ids);
    });
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
    toolsMenu->addAction("Archive…", this, [this] { setProperty("librarySection",0); manageProjects(); });
    toolsMenu->addAction("Trash…", this, [this] { setProperty("librarySection",1); manageProjects(); });
    toolsMenu->addAction("Refresh available models", this, [this] { discoverModels(true); });
    toolsMenu->addAction("Restart provider session for this conversation", this,
                         [this] { call("v2.conversation.restart_session"); });
    toolsMenu->addAction("CAD script…", this, [this] {
        if (busy || focusOpenDialog()) return;
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
    help->addAction("Credits", this, [this] {
        if (focusOpenDialog()) return;
        QMessageBox::about(this, "Credits", "<b>Prompt to CAD</b><p>Uicons by <a href='https://www.flaticon.com/uicons'>Flaticon</a>.</p><p>See THIRD_PARTY_NOTICES.md for dependency licenses.</p>");
    });
    help->addAction("Supported capabilities", this, [this] {
        QMessageBox::information(this, "Prompt to CAD",
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
        if (focusOpenDialog()) return;
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

    connect(selectionChip, &QPushButton::clicked, this, [this] {
        const auto entities=selected.value("entities").toArray();
        if(entities.size()<2) { viewer->removeSelectedEntity(-1); return; }
        QMenu menu;
        for(int i=0;i<entities.size();++i) {
            auto entry=entities[i].toObject();auto *action=menu.addAction("Remove " + entry.value("instance_id").toString()+" → "+entry.value("kind").toString()+" "+QString::number(entry.value("index").toInt()));
            connect(action,&QAction::triggered,this,[this,i]{viewer->removeSelectedEntity(i);});
        }
        menu.addSeparator();menu.addAction("Clear selection",this,[this]{viewer->removeSelectedEntity(-1);});
        menu.exec(selectionChip->mapToGlobal(QPoint(0,selectionChip->height())));
    });
    connect(selectionMode, &QComboBox::currentTextChanged, this,
            [this](const QString &kind) { viewer->setSelectionMode(kind.toLower()); });
    connect(viewer, &CadView::selectionChanged, this, &WorkspaceWindow::select);
    connect(viewer, &CadView::selectionChanged, this, [this] { syncModelVisibility(); });
    connect(viewer, &CadView::visibilityChanged, this, &WorkspaceWindow::syncModelVisibility);
    connect(viewer, &CadView::viewerError, this, [this](const QString &e) {
        viewerFailed = true;
        showError(e);
    });
    connect(treeFilter, &QLineEdit::textChanged, this, [this] { filterModels(); });
    connect(search, &QLineEdit::textChanged, this, [this] { filterProjects(); });
    connect(projects, &QTreeWidget::itemClicked, this, [this](QTreeWidgetItem *item, int) {
        if (busy || loading || (QApplication::keyboardModifiers() & (Qt::ControlModifier|Qt::ShiftModifier)))
            return;
        auto pid = item->data(0, Qt::UserRole).toString();
        auto cid = item->data(0, Qt::UserRole + 1).toString();
        if (pid.isEmpty())
            return;
        if (!cid.isEmpty())
            openConversation(pid, cid);
        else if (pid != state.value("project").toObject().value("project_id").toString())
            call("v2.project.open", {{"project_id", pid}});
    });
    projects->setSelectionMode(QAbstractItemView::ExtendedSelection);
    projects->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(projects, &QTreeWidget::customContextMenuRequested, this, [this](QPoint position) {
        auto *item = projects->itemAt(position);
        if (!item || item->isDisabled() || busy)
            return;
        if(projects->selectedItems().size()>1) {
            QJsonArray items;bool onlyChats=true;
            for(auto *row:projects->selectedItems()) { auto cid=row->data(0,Qt::UserRole+1).toString(); if(cid.isEmpty()){onlyChats=false;break;} items.append(QJsonObject{{"project_id",row->data(0,Qt::UserRole).toString()},{"conversation_id",cid}}); }
            QMenu menu;
            if(onlyChats) { auto *archive=menu.addAction("Archive "+QString::number(items.size())+" conversations");auto *trash=menu.addAction("Move "+QString::number(items.size())+" conversations to trash");auto *choice=menu.exec(projects->viewport()->mapToGlobal(position));if(choice)batchConversations(items,choice==archive?"archive":"trash"); Q_UNUSED(trash); }
            else { auto *hint=menu.addAction("Select conversation rows for bulk actions");hint->setEnabled(false);menu.exec(projects->viewport()->mapToGlobal(position)); }
            return;
        }
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
    modelTree->setSelectionMode(QAbstractItemView::ExtendedSelection);
    connect(modelTree, &QTreeWidget::itemClicked, this, [this](QTreeWidgetItem *, int) {
        if(loading)return;QStringList ids;for(auto *item:modelTree->selectedItems()) { auto id=item->data(0,Qt::UserRole).toString();if(!id.isEmpty())ids<<id; }
        viewer->selectInstances(ids);
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
    connect(chat, &ConversationView::anchorClicked, this, [this](const QUrl &link) {
        if (link.scheme() == "revision") {
            auto p = base();
            p["revision_id"] = link.path();
            call("v2.restore", p);
        } else if (link.scheme() == "component")
            viewer->selectInstance(link.path());
    });
    connect(chat, &ConversationView::attachmentRequested, this, &WorkspaceWindow::addReferenceAttachment);
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
        if (stage != "assistant_delta" && stage != "assistant_message" && stage != "candidate" && !taskId.isEmpty()) {
            const auto message = event.value("message").toString();
            updateTask(event.value("state").toString("running"), message);
            if (!message.isEmpty() && (currentActivity.isEmpty() || currentActivity.last() != message))
                currentActivity << message;
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
        } else if (stage == "assistant_delta" || stage == "assistant_message") {
            receiveAssistant(event, stage == "assistant_message");
        } else if (stage == "candidate") {
            viewer->setDocument(event.value("document").toObject(), false);
            saved->setText("Candidate preview · not accepted");
        } else if (stage == "connection") {
            activity->setText(event.value("message").toString());
            if (event.value("provider_status").isObject()) {
                state["provider"] = event.value("provider_status");
                updateUsage();
                if (!busy && state.value("provider").toObject().value("state") == "ready")
                    discoverModels();
            }
        } else
            activity->setText(event.value("message").toString());
    });
    connect(rpc, &RpcClient::stopped, this, [this](const QString &error) {
        Q_EMIT workspaceReady();
        showError(error);
    });
    connect(rpc, &RpcClient::ready, this, [this, openPath] {
        call("v2.state", {}, [this, openPath](auto r) {
            startupEmpty = r.value("project").toObject().isEmpty() && r.value("conversation").toObject().isEmpty();
            showState(r);
            Q_EMIT workspaceReady();
            if (!openPath.isEmpty())
                openFile(openPath);
            else if (smoke)
                showError("Smoke test requires a model.");
            if (!smoke) showOnboarding();
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
    notify(message);
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
    taskRunning = method == "v2.task";
    updateSendControl();
    refreshConnectionControls();
    undoAction->setEnabled(false);
    redoAction->setEnabled(false);
    rpc->call(method, params, [this, done, method, params](const QJsonObject &result, const QString &failure) {
        busy = false;
        taskRunning = false;
        updateSendControl();
        refreshConnectionControls();
        if (!failure.isEmpty()) {
            if (method == "v2.task") {
                if (composer->toPlainText().isEmpty()) composer->setPlainText(params.value("prompt").toString());
                restoreSubmittedAttachments();
            }
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
void WorkspaceWindow::revealConversation() {
    conversationPane->show();
    auto sizes = split->sizes();
    const int index = split->indexOf(conversationPane);
    if (index >= 0 && sizes[index] < conversationPane->minimumWidth()) {
        const int total = split->width() - split->handleWidth() * (split->count() - 1);
        const int chatWidth = qBound(290, total / 3, 400);
        int navigationWidth = navigation->isVisible() ? sizes[0] : 0;
        if (total - navigationWidth - chatWidth < 450) {
            navigation->hide();
            navigationWidth = 0;
        }
        sizes[0] = navigationWidth;
        sizes[1] = qMax(1, total - navigationWidth - chatWidth);
        sizes[index] = chatWidth;
        split->setSizes(sizes);
    }
    composer->setFocus(Qt::OtherFocusReason);
}
void WorkspaceWindow::newConversation() {
    revealConversation();
    if (busy) {
        activity->setText("Wait for the current task, or stop it before starting another conversation.");
        return;
    }
    if (focusOpenDialog()) return;
    if (state.value("project").toObject().isEmpty()) {
        activity->setText("Create or open a project to start a conversation.");
        newProject();
        return;
    }
    call("v2.conversation.new", {}, [this](auto) {
        revealConversation();
        Q_EMIT conversationOpened();
    });
}
void WorkspaceWindow::openConversation(const QString &projectId, const QString &conversationId) {
    if (busy || projectId.isEmpty() || conversationId.isEmpty()) return;
    call("v2.conversation.open", {{"project_id", projectId}, {"conversation_id", conversationId}},
         [this](auto) { revealConversation(); Q_EMIT conversationOpened(); });
}
bool WorkspaceWindow::focusOpenDialog() {
    for (auto *dialog : findChildren<QDialog *>()) {
        if (!dialog->isVisible()) continue;
        dialog->showNormal();
        dialog->raise();
        dialog->activateWindow();
        return true;
    }
    return false;
}
void WorkspaceWindow::openNativeProject() {
    if (busy || focusOpenDialog()) return;
    const auto path = QFileDialog::getExistingDirectory(this, "Open project", state.value("projects_root").toString());
    if (!path.isEmpty()) call("v2.open_native", {{"path", path}});
}
void WorkspaceWindow::newProject() {
    if (busy || focusOpenDialog())
        return;
    auto *dialog = new QDialog(this);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setObjectName("newProjectDialog");
    dialog->setWindowModality(Qt::WindowModal);
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
            revealConversation();
        });
    });
    dialog->show();
    name->setFocus();
}
void WorkspaceWindow::openFile(const QString &supplied) {
    if (supplied.isEmpty() && (busy || focusOpenDialog()))
        return;
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
    changeConversationDraftContext();
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
    title->setText(project.value("name").toString("Create a project to begin"));
    setWindowTitle(project.isEmpty() ? "Prompt to CAD"
                                     : project.value("name").toString() + " · Prompt to CAD");
    saved->setText(document.value("components").toArray().isEmpty()
                       ? "Empty document"
                       : "Saved");
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
    refreshProjectTree();
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
        item->setCheckState(0, viewer->isInstanceVisible(o.value("instance_id").toString()) ? Qt::Checked : Qt::Unchecked);
        item->setToolTip(0, o.value("representation") == "mesh"
                                ? "Visual mesh · explicit triangle regions; no original feature "
                                  "history"
                            : o.value("parameters").toObject().isEmpty()
                                ? "Solid geometry · original feature history unavailable"
                                : "Editable named parameters available in Properties");
    }
    filterModels();
    if (!changed && !selected.isEmpty()) select(selected);
    syncModelVisibility();
    revisions->clear();
    for (auto revision : document.value("history").toArray()) {
        auto o = revision.toObject();
        auto *item = new QTreeWidgetItem(revisions, {o.value("summary").toString().left(90)});
        item->setData(0, Qt::UserRole, o.value("revision_id"));
        item->setToolTip(0, o.value("revision_id").toString() + "\nDouble-click to restore this revision");
        if (o.value("revision_id") == document.value("revision_id"))
            revisions->setCurrentItem(item);
    }
    renderChat();
    auto connection = value.value("provider").toObject();
    auto active = connection.value("active").toObject();
    updateUsage();
    activity->setText("mm · " + QString::number(document.value("components").toArray().size()) +
                      " components · " +
                      (active.isEmpty() ? "Agent disconnected" : connection.value("billing").toString()));
    const auto notice = value.value("startup_notice").toString();
    const auto unavailable = value.value("catalog").toObject().value("diagnostics").toArray().size();
    if (!notice.isEmpty()) activity->setText(notice);
    else if (unavailable) activity->setText(activity->text() + " · " + QString::number(unavailable) + " project issue(s) · see Settings → Projects");
    if (!busy) {
        const auto taskState = value.value("task_state").toString();
        if (QStringList{"completed", "completed_no_change", "failed", "cancelled", "usage_limit"}.contains(
                taskState))
            updateTask(taskState, currentTaskMessage);
        else
            updateTask(connection.value("state") == "ready" ? "idle" : "disconnected",
                       connection.value("state") == "ready" ? "Select geometry or send a design request."
                                                            : "Sign in from Settings to start a CAD task.");
    }
    updateSendControl();
    loading = false;
}
void WorkspaceWindow::select(const QJsonObject &selection) {
    if (selection.isEmpty()) {
        selected = {};
        selectionChip->hide();
        QSignalBlocker blocker(modelTree);
        modelTree->clearSelection();
        properties->clear();
        operationPane->hide();
        return;
    }
    selected = selection;
    selected["document_id"] = document.value("document_id");
    selected["project_id"] = state.value("project").toObject().value("project_id");
    const auto entities = selection.value("entities").toArray();
    if(entities.size()>1) {
        QStringList labels,ids;
        for(auto value:entities){auto entry=value.toObject();auto id=entry.value("instance_id").toString();if(!ids.contains(id))ids<<id;labels<<id+" → "+entry.value("kind").toString()+" "+QString::number(entry.value("index").toInt());}
        selectionChip->setText("Selected: "+QString::number(entities.size())+" entities · "+QString::number(ids.size())+" components  ×");selectionChip->setToolTip(labels.join('\n'));selectionChip->show();
        properties->setHtml("<h3>Selected geometry · mm</h3>" + labels.join('\n').toHtmlEscaped().replace("\n", "<br>") + engineeringHtml(ids));
        QSignalBlocker blocker(modelTree);
        modelTree->clearSelection();for(QTreeWidgetItemIterator it(modelTree);*it;++it)if(ids.contains((*it)->data(0,Qt::UserRole).toString()))(*it)->setSelected(true);
        activity->setText(QString::number(entities.size())+" selected entities · mm");return;
    }
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
        properties->setHtml(body + engineeringHtml({id}));
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
QString WorkspaceWindow::takeComposerText() {
    auto prompt = composer->toPlainText();
    composer->clear();
    return prompt;
}
void WorkspaceWindow::submit() {
    if (busy || (composer->toPlainText().trimmed().isEmpty() && draftAttachments.isEmpty())) return;
    if (state.value("conversation").toObject().isEmpty()) { notify("Create or open a conversation before sending a request.", "info"); return; }
    if (state.value("provider").toObject().value("state") != "ready") { account(); return; }
    if (models->currentData().toString().isEmpty()) { notify("Choose a model before sending a request.", "info"); return; }
    auto params = base();
    const auto capture = QDir::tempPath() + "/promptcad-" + QUuid::createUuid().toString(QUuid::WithoutBraces) + ".png";
    if (viewer->bodyCount() > 0 && viewer->saveViewport(capture)) params["viewport_path"] = capture;
    params["prompt"] = composer->toPlainText(); params["model"] = models->currentData().toString();
    params["task_id"] = QUuid::createUuid().toString(QUuid::WithoutBraces).remove('-');
    if (!selected.isEmpty()) params["selection"] = selected;
    if (!draftAttachments.isEmpty()) prepareImageSubmission(params);
    else { submittedAttachments = {}; submittedDraftAttachments = {}; startAgentTask(params); }
}
void WorkspaceWindow::startAgentTask(QJsonObject params) {
    activeTaskId = params.value("task_id").toString();
    taskAgent = state.value("runtime").toObject().value("agent").toObject();
    currentActivity.clear();
    pendingUser = takeComposerText();
    draftAttachments = {}; renderAttachmentDraft();
    liveOrder.clear(); liveMessages.clear(); livePhases.clear(); liveAnswer.clear();
    taskClock.restart(); updateTask("connecting", "Preparing the document, selection and reference images.");
    QTimer::singleShot(0, this, &WorkspaceWindow::renderChat);
    call("v2.task", params, [this](auto) {
        pendingUser.clear(); liveAnswer.clear(); activeTaskId.clear();
        submittedAttachments = {}; submittedDraftAttachments = {};
    });
}
void WorkspaceWindow::discoverModels(bool refresh) {
    if (modelsLoading || busy) return;
    modelsLoading = true;
    models->setProperty("catalogState","Loading models…");
    busy = true;
    updateSendControl();
    rpc->call("provider.models", {{"refresh", refresh}}, [this](auto r, auto error) {
        modelsLoading = false;
        busy = false;
        updateSendControl();
        refreshConnectionControls();
        if (!error.isEmpty()) { models->setProperty("catalogState",error);showError(error); return; }
        models->setProperty("catalogState",r.value("models").toArray().isEmpty()?"No models were reported. Check your connection or refresh.":"");
        auto old = models->currentData();
        models->clear();
        for (auto value : r.value("models").toArray()) {
            auto model = value.toObject();
            models->addItem(model.value("name").toString(), model.value("id"));
            models->setItemData(models->count() - 1, model.value("access"), Qt::ToolTipRole);
            models->setItemData(models->count() - 1, model, Qt::UserRole + 1);
            models->setItemData(models->count() - 1, model.value("access").toString() + "\nImage input: " + model.value("image_support").toString("unknown"), Qt::ToolTipRole);
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
    const auto entities=selected.value("entities").toArray();
    if(entities.size()>1 && kind!="thickness" && kind!="holes") {
        bool sameEdges=kind=="fillet"||kind=="chamfer";
        for(auto value:entities) { auto entity=value.toObject();sameEdges=sameEdges&&entity.value("kind")=="edge"&&entity.value("instance_id")==selected.value("instance_id"); }
        if(!sameEdges){notify("Use the agent for this multi-component operation, or select one component.","info");return;}
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
    const auto entities=selected.value("entities").toArray();
    if(entities.size()>1 && (currentOperation=="thickness"||currentOperation=="holes")) {
        QJsonArray commands;for(auto value:entities) { auto entity=value.toObject();if(entity.value("kind")!="face"){notify("Select planar faces for a face operation.","warning");return;}auto next=command;next["instance_id"]=entity.value("instance_id");next["face_index"]=entity.value("index");commands.append(next); }
        p["commands"]=commands;call("v2.command_batch",p);
    } else {p["command"] = command;call("v2.command", p);}
}
void WorkspaceWindow::smokeCheck() {
    if (!onboardingVerified) {
        if (!startupEmpty) { showError("Normal startup restored a previous project."); return; }
        QSettings().setValue("v2/onboardingDone", false);
        for (int click = 0; click < 25; ++click) showOnboarding();
        if (!onboardingDialog || findChildren<QDialog *>("codexOnboarding").size() != 1) {
            showError("Onboarding singleton regression failed."); return;
        }
        onboardingDialog->grab().save(workspace + "/tmp/native-onboarding.png");
        onboardingDialog->findChild<QPushButton *>("onboardingSkip")->click();
        QApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
        showOnboarding();
        if (onboardingDialog || !QSettings().value("v2/onboardingDone").toBool()) {
            showError("Skipping onboarding did not persist."); return;
        }
        busy = true;
        taskRunning = true;
        updateTask("running", "Synthetic cancellation control test");
        if (sendButton->accessibleName() != "Stop task" || !sendButton->isEnabled()) {
            showError("Send control did not become Stop."); return;
        }
        sendButton->click();
        if (sendButton->isEnabled() || sendButton->accessibleName() != "Stopping task") {
            showError("Stop control was not disabled during cancellation."); return;
        }
        busy = false;
        taskRunning = false;
        updateTask("idle", {});
        if (sendButton->accessibleName() != "Send request") {
            showError("Stop control did not return to Send."); return;
        }
        onboardingVerified = true;
    }
    if (!polishVerified) {
        busy=true;
        auto *input=qobject_cast<ComposerEdit *>(composer);int sends=0;
        const auto connection=connect(input,&ComposerEdit::sendRequested,this,[&sends]{++sends;});
        composer->setPlainText("Synthetic input");
        QKeyEvent newline(QEvent::KeyPress,Qt::Key_Return,Qt::ShiftModifier);QApplication::sendEvent(input,&newline);
        if(!composer->toPlainText().contains('\n')||sends){showError("Shift+Enter did not insert a newline.");return;}
        QKeyEvent enter(QEvent::KeyPress,Qt::Key_Return,Qt::NoModifier);QApplication::sendEvent(input,&enter);
        QKeyEvent repeated(QEvent::KeyPress,Qt::Key_Return,Qt::NoModifier,QString(),true);QApplication::sendEvent(input,&repeated);
        QInputMethodEvent composition("fixture",{});QApplication::sendEvent(input,&composition);QApplication::sendEvent(input,&enter);
        QInputMethodEvent commit;commit.setCommitString("fixture");QApplication::sendEvent(input,&commit);
        disconnect(connection);
        if(sends!=1){showError("Enter autorepeat or IME composition submitted unexpectedly.");return;}
        composer->clear();busy=false;updateSendControl();
        if(findChild<QPushButton *>("undoToolbar")->text().size()||findChild<QPushButton *>("redoToolbar")->text().size()||title->text().contains(" / ")||saved->text().contains(document.value("revision_id").toString().left(8))){showError("Header naming or icon regression failed.");return;}
        auto original=chat->plainText();notify("Synthetic application notice","info");notify("Synthetic application notice","info");
        if(chat->plainText()!=original||findChildren<QFrame *>("notificationCard").size()!=1){showError("Application notices polluted chat or duplicated.");return;}
        findChild<QFrame *>("notificationHost")->grab().save(workspace+"/tmp/native-notification.png");
        delete findChild<QFrame *>("notificationHost");
        showAccountDetails();if(settingsDialog||!findChild<QFrame *>("accountPopover")){showError("Account icon opened Settings.");return;}
        findChild<QFrame *>("accountPopover")->grab().save(workspace+"/tmp/native-account-details.png");findChild<QFrame *>("accountPopover")->close();QApplication::sendPostedEvents(nullptr,QEvent::DeferredDelete);
        if(!viewer->smokeSelectMultipleFaces()||selected.value("entities").toArray().size()<2){showError("Multi-component viewport selection failed.");return;}
        auto selectedCount=selected.value("entities").toArray().size();viewer->removeSelectedEntity(0);
        if(selected.value("entities").toArray().size()!=selectedCount-1){showError("Removing one selection context did not update the viewport.");return;}
        viewer->smokeSelectFace();
        const int originalModelCount=models->count(),originalModel=models->currentIndex();
        models->addItem("Fixture model A","fixture-a");models->addItem("Fixture model B","fixture-b");
        models->showPopup();QApplication::processEvents();
        auto *modelPanel=findChild<QFrame *>("modelPopover");auto *modelSearch=modelPanel?modelPanel->findChild<QLineEdit *>("modelSearch"):nullptr;
        if(!modelSearch){showError("Searchable model popover did not open.");return;}
        modelSearch->setText("model B");modelPanel->grab().save(workspace+"/tmp/native-model-picker.png");QApplication::sendEvent(modelSearch,&enter);QApplication::sendPostedEvents(nullptr,QEvent::DeferredDelete);
        if(models->currentData().toString()!="fixture-b"){showError("Model search keyboard choice failed.");return;}
        while(models->count()>originalModelCount)models->removeItem(models->count()-1);models->setCurrentIndex(originalModel);
        if(findChild<QPushButton *>("undoToolbar")->isEnabled()&&findChild<QPushButton *>("undoToolbar")->cursor().shape()!=Qt::PointingHandCursor){showError("Clickable button cursor regression failed.");return;}
        manageProjects();auto *library=findChild<QDialog *>("projectCatalogue");auto *libraryTabs=library?library->findChild<QTabWidget *>("libraryTabs"):nullptr;
        if(!libraryTabs||libraryTabs->count()!=2||libraryTabs->tabText(0)!="Archive"||libraryTabs->tabText(1)!="Trash"){showError("Archive and Trash were not separate views.");return;}
        library->grab().save(workspace+"/tmp/native-library.png");library->reject();QApplication::sendPostedEvents(nullptr,QEvent::DeferredDelete);
        polishVerified=true;
    }
    if (!conversationsVerified) {
        auto *trigger = findChild<QPushButton *>("newConversationButton");
        const auto originalState = state;
        state.remove("project");
        for (int click = 0; click < 25; ++click) trigger->click();
        auto dialogs = findChildren<QDialog *>("newProjectDialog");
        if (dialogs.size() != 1) {
            showError("A conversation without a project did not open one project dialog.");
            return;
        }
        dialogs.first()->reject();
        QApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
        showState(originalState);
        const auto originalDocument = document;
        const auto originalChat = state.value("conversation").toObject().value("conversation_id").toString();
        const auto originalProject = state.value("project").toObject().value("project_id").toString();
        const auto count = state.value("conversations").toArray().size();
        conversationPane->hide();
        connect(this, &WorkspaceWindow::conversationOpened, this,
                [this, originalDocument, originalChat, originalProject, count] {
            if (document != originalDocument || state.value("conversations").toArray().size() != count + 1 ||
                state.value("conversation").toObject().value("conversation_id") == originalChat ||
                !conversationPane->isVisible() || conversationPane->width() < 290 || focusWidget() != composer) {
                showError("New conversation did not reveal and focus chat or preserve the document.");
                return;
            }
            auto sizes = split->sizes();
            sizes[2] = 0;
            split->setSizes(sizes);
            connect(this, &WorkspaceWindow::conversationOpened, this,
                    [this, originalDocument, originalChat] {
                if (document != originalDocument ||
                    state.value("conversation").toObject().value("conversation_id") != originalChat ||
                    !conversationPane->isVisible() || conversationPane->width() < 290 || focusWidget() != composer) {
                    showError("Opening an existing conversation did not restore collapsed chat.");
                    return;
                }
                conversationsVerified = true;
                QTimer::singleShot(0, this, &WorkspaceWindow::smokeCheck);
            }, Qt::SingleShotConnection);
            openConversation(originalProject, originalChat);
        }, Qt::SingleShotConnection);
        for (int click = 0; click < 25; ++click) trigger->click();
        QTimer::singleShot(10000, this, [this] {
            if (!conversationsVerified) showError("Conversation opening did not finish.");
        });
        return;
    }
    if (!settingsVerified) {
        for (const auto &name : {QString("newProjectDialog"), QString("projectCatalogue")}) {
            for (int click = 0; click < 25; ++click) {
                if (name == "newProjectDialog") newProject(); else manageProjects();
            }
            auto dialogs = findChildren<QDialog *>(name);
            if (dialogs.size() != 1 || !dialogs.first()->isModal()) {
                showError("Project dialog re-entry regression failed.");
                return;
            }
            dialogs.first()->reject();
            QApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
            if (!findChildren<QDialog *>(name).isEmpty()) {
                showError("Project dialog cleanup regression failed.");
                return;
            }
        }
        composer->setPlainText("Synthetic sent prompt");
        if (takeComposerText() != "Synthetic sent prompt" || !composer->toPlainText().isEmpty()) {
            showError("Composer submission did not clear immediately.");
            return;
        }
        composer->setPlainText("Next draft stays while the task finishes");
        showState(state);
        if (composer->toPlainText() != "Next draft stays while the task finishes") {
            showError("A state refresh erased the next draft.");
            return;
        }
        composer->clear();
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
    if (qEnvironmentVariableIsSet("CAD_UI_MISSING_PROJECT_FIXTURE") &&
        !state.value("catalog").toObject().value("unavailable").toArray().isEmpty()) {
        showError("Missing-project startup recovery regression failed.");
        return;
    }
    QDir().mkpath(workspace + "/tmp");
    QJsonObject report{
        {"passed", true},
        {"workspace_polish_controls",polishVerified},
        {"multi_component_selection",polishVerified},
        {"enter_shift_enter_and_ime",polishVerified},
        {"notifications_outside_chat",polishVerified},
        {"account_details_separate",polishVerified},
        {"separate_archive_trash",polishVerified},
        {"empty_startup", startupEmpty},
        {"onboarding_skip_and_singleton", onboardingVerified},
        {"single_send_stop_control", onboardingVerified},
        {"product", "Prompt to CAD"},
        {"body_count", viewer->bodyCount()},
        {"face_selection", true},
        {"settings_singleton_rapid_clicks", 125},
        {"new_conversation_reveals_hidden_panel", conversationsVerified},
        {"existing_conversation_restores_collapsed_panel", conversationsVerified},
        {"new_conversation_without_project_guides_creation", conversationsVerified},
        {"conversation_rapid_clicks", 25},
        {"conversation_switch_preserves_document", conversationsVerified},
        {"project_dialog_singleton_clicks", 50},
        {"composer_clears_on_submission", true},
        {"next_draft_preserved", true},
        {"settings_close_reopen_cycles", 5},
        {"settings_save_requests", settingsSaves},
        {"settings_display_change_saved", true},
        {"ai_connection_options", 2},
        {"theme", QSettings().value("v2/theme", "dark").toString()},
        {"unavailable_projects", state.value("catalog").toObject().value("unavailable").toArray().size()},
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
    if (file.open(QIODevice::WriteOnly)) {
        file.write(QJsonDocument(report).toJson());
        file.close();
    }
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
    currentActivity = {"Inspecting synthetic fixture", "Checking selected component scope"};
    updateTask("running", "UI fixture · inspecting the selected component");
    taskRunning = true;
    updateSendControl();
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
    taskRunning = false;
    pendingUser.clear();
    liveAnswer.clear();
    updateTask("completed_no_change", {});
    auto originalConversation = state.value("conversation").toObject();
    auto fixtureConversation = originalConversation;
    fixtureConversation["messages"] = QJsonArray{
        QJsonObject{{"role", "user"}, {"content", "Move the selected fixture 5 mm along X."}},
        QJsonObject{{"role", "assistant"}, {"task_id", "ui-fixture"}, {"elapsed_seconds", 76.0},
                    {"activity", QJsonArray{QJsonObject{{"message", "Inspected the selection"}}, QJsonObject{{"message", "Validated the candidate geometry"}}}},
                    {"content", "Moved the selected fixture **5 mm along X**.\n\nThe other components remain unchanged.\n\n- Geometry validation passed.\n- The accepted revision is saved."}}
    };
    fixtureConversation["token_usage"] = QJsonObject{{"totalTokens", 145041}, {"inputTokens", 144266}, {"outputTokens", 775}};
    state["conversation"] = fixtureConversation;
    state["provider"] = originalProvider;
    renderChat();
    updateUsage();
    QApplication::processEvents();
    auto disclosures = chat->findChildren<QToolButton *>("workDisclosure");
    if (disclosures.size() != 1 || disclosures.first()->isChecked() ||
        disclosures.first()->text() != "Worked for 1m 16s") {
        showError("Completed work disclosure regression failed.");
        return;
    }
    disclosures.first()->click();
    if (chat->findChildren<QLabel *>("activitySummary").first()->isHidden()) {
        showError("Completed activity did not expand.");
        return;
    }
    disclosures.first()->click();
    QApplication::processEvents();
    const auto bubbles = chat->findChildren<QFrame *>("messageBubble");
    if (bubbles.size() != 2 || bubbles.first()->mapTo(chat, QPoint(0, 0)).x() <= bubbles.last()->mapTo(chat, QPoint(0, 0)).x()) {
        showError("Conversation alignment regression failed.");
        return;
    }
    auto *reply = bubbles.last()->findChild<QTextBrowser *>("messageText");
    auto *disclosure = disclosures.first();
    if (reply->y() - disclosure->geometry().bottom() > 30) {
        showError("Collapsed activity left an empty gap before the reply.");
        return;
    }
    if (!usageBadge->isVisible() || !usageBadge->text().contains("tokens")) {
        showError("Reported-token badge regression failed.");
        return;
    }
    auto completed = grab();
    QPainter completedPainter(&completed);
    completedPainter.drawImage(QRect(viewer->mapTo(this, QPoint(0, 0)), viewer->size()), QImage(path));
    completedPainter.end();
    completed.save(workspace + "/tmp/native-agent-completed.png");
    showUsageDetails();
    if(auto *usagePanel=findChild<QFrame *>("usagePopover")){usagePanel->grab().save(workspace+"/tmp/native-usage.png");usagePanel->close();QApplication::sendPostedEvents(nullptr,QEvent::DeferredDelete);}else{showError("Usage information card did not open.");return;}
    chatRefresh->stop();
    QJsonArray longHistory;for(int i=0;i<40;++i)longHistory.append(QJsonObject{{"role","assistant"},{"content","Synthetic scroll entry "+QString::number(i)+"\n\nAdditional context for the scrolling fixture."}});
    chat->setMessages(longHistory,"scroll-fixture");QApplication::processEvents();QApplication::processEvents();chat->scrollToLatest();chat->verticalScrollBar()->triggerAction(QAbstractSlider::SliderToMinimum);
    longHistory.append(QJsonObject{{"role","assistant"},{"content","New synthetic streamed response."}});chat->setMessages(longHistory,"scroll-fixture");QApplication::processEvents();QApplication::processEvents();
    auto *latest=chat->findChild<QToolButton *>("latestMessage");
    if(!latest||!latest->isVisible()||chat->verticalScrollBar()->value()>5){showError(QString("Streaming scroll regression: position=%1 maximum=%2 latest=%3").arg(chat->verticalScrollBar()->value()).arg(chat->verticalScrollBar()->maximum()).arg(latest&&latest->isVisible()));return;}
    latest->click();if(chat->verticalScrollBar()->value()!=chat->verticalScrollBar()->maximum()){showError("Go to latest message failed.");return;}
    report["scroll_follow_and_latest_button"]=true;report["searchable_model_popover"]=true;report["usage_information_card"]=true;
    state["conversation"] = originalConversation;
    renderChat();
    updateUsage();
    if (!usageBadge->isHidden()) {
        showError("An unreported allowance badge must stay hidden.");
        return;
    }
    report["completed_work_collapses"] = true;
    report["conversation_alignment_and_spacing"] = true;
    report["reported_tokens_only_badge"] = true;
    if (file.open(QIODevice::WriteOnly | QIODevice::Truncate)) file.write(QJsonDocument(report).toJson());
    QApplication::exit(0);
}


void WorkspaceWindow::changeEvent(QEvent *event) {
    QMainWindow::changeEvent(event);
    if (event->type() != QEvent::WindowActivate || refreshScheduled || state.isEmpty() || smoke) return;
    refreshScheduled = true;
    QTimer::singleShot(250, this, [this] {
        refreshScheduled = false;
        if (!busy && !loading) call("v2.projects.refresh");
    });
}
