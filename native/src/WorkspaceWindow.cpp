#include "WorkspaceWindow.h"
#include "CadView.h"
#include <QAction>
#include <QApplication>
#include <QComboBox>
#include <QCheckBox>
#include <QDesktopServices>
#include <QDateTime>
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
#include <QStandardPaths>
#include <QUuid>
#include <QSplitter>
#include <QStatusBar>
#include <QTabBar>
#include <QTabWidget>
#include <QTextBrowser>
#include <QTextCursor>
#include <QTimer>
#include <QToolBar>
#include <QTreeWidget>
#include <QTreeWidgetItemIterator>
#include <QUrl>
#include <QVBoxLayout>
#include <Standard_Version.hxx>

namespace {
QPushButton *button(const QString &text, QBoxLayout *layout, std::function<void()> clicked) {
    auto *b = new QPushButton(text);
    layout->addWidget(b);
    QObject::connect(b, &QPushButton::clicked, std::move(clicked));
    return b;
}
QString html(const QString &value) {
    return value.toHtmlEscaped().replace("\n", "<br>");
}
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
    button("☰", railLayout, [this] {
        navigation->setVisible(!navigation->isVisible());
    })->setToolTip("Projects and conversations");
    button("◇", railLayout, [this] {
        manager->setVisible(!manager->isVisible());
    })->setToolTip("CAD manager");
    button("◫", railLayout, [this] {
        conversationPane->setVisible(!conversationPane->isVisible());
    })->setToolTip("Agent conversation");
    railLayout->addStretch();
    button("⚙", railLayout, [this] { account(); })->setToolTip("Account, usage and runtime");
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
    saved = new QLabel("Saved locally");
    saved->setStyleSheet("color:#8f929d");
    documentHeader->addWidget(title, 1);
    documentHeader->addWidget(saved);
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
    auto *imageModel = commands->addAction("Image → mesh");
    connect(imageModel, &QAction::triggered, this, [this] {
        if (attachments.isEmpty()) {
            showError("Attach a reference image first, then choose Image → mesh.");
            return;
        }
        bool ok;
        double size = QInputDialog::getDouble(
            this, "Image reconstruction · separate Tripo credits",
            "Longest model dimension / mm. Other dimensions are inferred from the photograph.", 100, 0.1,
            100000, 2, &ok);
        if (!ok)
            return;
        if (QMessageBox::question(this, "Use Tripo API credits",
                                  "Send the attached image to Tripo and use its separate API credits? This "
                                  "creates an approximate visual mesh. Codex plan usage does not pay for "
                                  "reconstruction. The remote job may continue after local cancellation.") !=
            QMessageBox::Yes)
            return;
        auto p = base();
        p["reference"] = attachments[0];
        p["target_size_mm"] = size;
        p["authorize_separate_billing"] = true;
        call("v2.image_generate", p);
    });
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
    properties->setPlaceholderText(
        "Select a component, face or edge to inspect dimensions and named parameters.");
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
    auto *emptyNote =
        new QLabel("Create a project, import engineering geometry or a visual mesh, then refine it with the "
                   "CAD agent. Reference images can guide an editable approximation.");
    emptyNote->setWordWrap(true);
    emptyLayout->addWidget(emptyNote);
    button("New project", emptyLayout, [this] { newProject(); });
    button("Import supported model", emptyLayout, [this] { openFile(); });
    button("Describe a design", emptyLayout, [this] {
        conversationPane->show();
        composer->setFocus();
    });
    button("Attach reference image", emptyLayout, [this] { attach(); });
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
    auto *chatTitle = new QLabel("CAD agent");
    chatTitle->setStyleSheet("font-size:17px;font-weight:600");
    conversation->addWidget(chatTitle);
    chat = new QTextBrowser;
    chat->setOpenExternalLinks(false);
    chat->setPlaceholderText("Describe the design and essential dimensions. Attach images as references, or "
                             "select geometry to focus a change.");
    conversation->addWidget(chat, 1);
    attachmentLabel = new QLabel;
    attachmentLabel->setWordWrap(true);
    attachmentLabel->hide();
    conversation->addWidget(attachmentLabel);
    imageBilling = new QCheckBox("Allow Tripo reconstruction · separate credits");
    imageBilling->setToolTip("Authorize at most one image reconstruction in the next agent task. This does "
                             "not use Codex plan credits.");
    conversation->addWidget(imageBilling);
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
    button("Attach image", sendRow, [this] { attach(); });
    button("Clear", sendRow, [this] {
        attachments = {};
        attachmentLabel->hide();
    });
    sendButton = button("Send", sendRow, [this] { submit(); });
    stopButton = button("Stop", sendRow, [this] {
        rpc->cancel();
        activity->setText("Stopping task; candidate will be discarded…");
    });
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
    toolsMenu->addAction("Account and runtime…", this, &WorkspaceWindow::account);
    toolsMenu->addAction("Manage archived and deleted items…", this, &WorkspaceWindow::manageProjects);
    toolsMenu->addAction("Discover available models", this, &WorkspaceWindow::discoverModels);
    toolsMenu->addAction("Restart provider session for this conversation", this,
                         [this] { call("v2.conversation.restart_session"); });
    toolsMenu->addAction("CAD script…", this, [this] {
        bool ok;
        auto script = QInputDialog::getMultiLineText(
            this, "Restricted CAD script",
            "Use cq.Workplane and assign parts={name: solid}. Files, imports and shell are unavailable.",
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
        QMessageBox::information(
            this, "Prompt to CAD V2",
            "Engineering: STEP and editable CAD recipes; precise solids, local face/edge operations and "
            "restricted CAD scripts.\nAccepted changes are verified and undoable. Imported solids do not "
            "contain original feature history.\nReference images guide approximate CAD. Image-to-mesh "
            "service and region editing depend on their configured backend.\nMeasurement reports are "
            "available through Inspect. Interactive sections are future scope.\nAgent tasks consume your "
            "connected allowance; long tasks can consume more usage. API keys are billed separately.");
    });
    auto *commandSearch = new QAction("Command search", this);
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
                                      "Keep the files on disk and hide this item? It can be restored from "
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
                call("v2.state");
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
    navigation->setVisible(prefs.value("v2/navigationVisible", true).toBool());
    manager->setVisible(prefs.value("v2/managerVisible", true).toBool());
    conversationPane->setVisible(prefs.value("v2/conversationVisible", true).toBool());
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
QJsonObject WorkspaceWindow::base() const {
    return {{"base_revision_id", document.value("revision_id")}};
}
void WorkspaceWindow::showError(const QString &message) {
    qWarning().noquote() << message;
    activity->setText(message);
    chat->append("<p style='color:#efb6aa'>" + html(message) + "</p>");
    if (smoke)
        QApplication::exit(2);
}
void WorkspaceWindow::call(const QString &method, QJsonObject params, std::function<void(QJsonObject)> done) {
    if (busy) {
        showError("A task is running. Stop it before changing the document or conversation.");
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
        double scale = QInputDialog::getDouble(
            this, "Mesh units",
            "Millimetres per source unit (GLB commonly uses metres = 1000). Confirm the intended scale.",
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
                                ? "Visual mesh · explicit triangle regions; no original feature history"
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
    for (auto message : value.value("conversation").toObject().value("messages").toArray()) {
        auto m = message.toObject();
        chat->append("<p style='color:#bbaadc'><b>" + html(m.value("role").toString()) + "</b></p><p>" +
                     html(m.value("content").toString()) + "</p>");
        auto change = m.value("change").toObject();
        if (!change.isEmpty()) {
            QString links;
            for (auto id : change.value("affected_components").toArray())
                links += "<a href='component:" + id.toString().toHtmlEscaped() + "'>" + html(id.toString()) +
                         "</a> ";
            chat->append("<p style='background:#282c32;padding:8px'>Changed: " + links +
                         "<br>Validated geometry and preserved task scope.<br><a href='revision:" +
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
    activity->setText("mm · " + QString::number(document.value("components").toArray().size()) +
                      " components · " +
                      (active.isEmpty() ? "Agent disconnected" : connection.value("billing").toString()));
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
        properties->setPlainText(
            "Component: " + name + "\nUnits: mm\nRevision: " + document.value("revision_id").toString() +
            "\nSelection: " + selection.value("kind").toString() + " " +
            QString::number(selection.value("index").toInt()) + "\n\nDimensions and measurements\n" +
            QString::fromUtf8(
                QJsonDocument(part.value("metrics").toObject()).toJson(QJsonDocument::Indented)) +
            "\nNamed parameters\n" +
            QString::fromUtf8(
                QJsonDocument(part.value("parameters").toObject()).toJson(QJsonDocument::Indented)) +
            "\nLocal-to-world placement\n" +
            QString::fromUtf8(QJsonDocument(part.value("matrix").toArray()).toJson()));
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
void WorkspaceWindow::attach() {
    auto path = QFileDialog::getOpenFileName(this, "Attach reference image", {},
                                             "Images (*.png *.jpg *.jpeg *.webp)");
    if (path.isEmpty())
        return;
    call("v2.reference.add", {{"path", path}}, [this](auto r) {
        attachments.append(r);
        attachmentLabel->setText(QString::number(attachments.size()) +
                                 " reference image(s) attached · inferred geometry needs dimensions");
        attachmentLabel->show();
    });
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
    p["attachments"] = attachments;
    p["authorize_image_billing"] = imageBilling->isChecked();
    if (!selected.isEmpty())
        p["selection"] = selected;
    chat->append("<p><b>You</b><br>" + html(composer->toPlainText()) + "</p><p><b>CAD agent</b></p>");
    call("v2.task", p, [this](auto) {
        composer->clear();
        imageBilling->setChecked(false);
        attachments = {};
        attachmentLabel->hide();
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
        activity->setText("Models discovered. Availability is verified only by successful inference.");
    });
}
void WorkspaceWindow::account() {
    auto *dialog = new QDialog(this);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowTitle("Account and usage · Prompt to CAD V2");
    auto *layout = new QVBoxLayout(dialog);
    auto connection = state.value("provider").toObject();
    auto *info = new QLabel(connection.value("billing").toString() + "\n" +
                            connection.value("active").toObject().value("workspace").toString() +
                            "\nAllowance unavailable. No percentage is inferred.\nTasks consume allowance or "
                            "authorized credits. Long tasks can use more.\nLimits stop requests; API billing "
                            "requires an explicit connection choice.");
    info->setWordWrap(true);
    layout->addWidget(info);
    auto *accounts = new QComboBox;
    for (auto a : connection.value("accounts").toArray()) {
        auto item = a.toObject();
        accounts->addItem(item.value("email").toString() + " · " + item.value("workspace").toString(),
                          item.value("id"));
    }
    layout->addWidget(accounts);
    button("Use selected registration", layout, [this, accounts, dialog] {
        if (accounts->currentIndex() >= 0) {
            call("provider.select", {{"account_id", accounts->currentData().toString()}});
            dialog->close();
        }
    });
    button("Continue with ChatGPT", layout, [this, dialog] {
        call("provider.login", {}, [this](auto r) {
            QDesktopServices::openUrl(QUrl(r.value("authorization_url").toString()));
            activity->setText("Complete authorization in your system browser, then discover models.");
        });
        dialog->close();
    });
    button("Cancel pending sign-in", layout, [this, dialog] {
        call("provider.cancel_login");
        dialog->close();
    });
    button("Reconnect selected ChatGPT registration", layout, [this, accounts, dialog] {
        if (accounts->currentIndex() >= 0)
            call("provider.login", {{"account_id", accounts->currentData().toString()}},
                 [](auto r) { QDesktopServices::openUrl(QUrl(r.value("authorization_url").toString())); });
        dialog->close();
    });
    auto *key = new QLineEdit;
    key->setEchoMode(QLineEdit::Password);
    key->setPlaceholderText("Optional user API key · separately billed");
    layout->addWidget(key);
    button("Connect API key (separate billing)", layout, [this, key, dialog] {
        call("provider.api_key", {{"key", key->text()}}, [this](auto) { call("v2.state"); });
        key->clear();
        dialog->close();
    });
    auto *imageKey = new QLineEdit;
    imageKey->setEchoMode(QLineEdit::Password);
    imageKey->setPlaceholderText("Optional Tripo API key · separate image-service credits");
    layout->addWidget(imageKey);
    button("Connect image service (Tripo credits)", layout, [this, imageKey, dialog] {
        call("image.configure", {{"key", imageKey->text()}}, [this](auto r) {
            activity->setText(r.value("connected").toBool()
                                  ? "Tripo key saved. Live image generation remains unverified."
                                  : "Image service disconnected.");
        });
        imageKey->clear();
        dialog->close();
    });
    button("Tripo pricing and usage", layout,
           [] { QDesktopServices::openUrl(QUrl("https://developers.tripo3d.ai/en/pricing")); });
    button("Manage ChatGPT usage and access", layout,
           [] { QDesktopServices::openUrl(QUrl("https://chatgpt.com/settings/usage")); });
    button("Discover models", layout, [this, dialog] {
        dialog->close();
        discoverModels();
    });
    button("Select Codex executable…", layout, [this, dialog] {
        auto path = QFileDialog::getOpenFileName(this, "Installed Codex executable", {}, "Codex (codex.exe)");
        if (!path.isEmpty())
            call("provider.configure", {{"codex_path", path}});
        dialog->close();
    });
    button("Test App Server connection (no inference)", layout, [this, dialog] {
        call("provider.probe", {}, [this](auto r) {
            QMessageBox::information(this, "Runtime connection", r.value("message").toString());
        });
        dialog->close();
    });
    button("Disconnect active account", layout, [this, dialog] {
        call("provider.disconnect", {}, [this](auto r) {
            QMessageBox::information(this, "Disconnected", r.value("message").toString());
            call("v2.state");
        });
        dialog->close();
    });
    dialog->resize(510, 500);
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
    while (auto *item = operationForm->takeAt(0)) {
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
        p["source"] = QString("parts = {'block_%1': cq.Workplane('XY').box(params['width'], params['depth'], "
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
    auto *note = new QLabel("Trash is recoverable. Project files and accepted revisions remain on disk.");
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
