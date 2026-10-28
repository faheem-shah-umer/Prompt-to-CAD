#include "MainWindow.h"
#include "CadView.h"
#include <QApplication>
#include <QAction>
#include <QComboBox>
#include <QCheckBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDockWidget>
#include <QDoubleSpinBox>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QInputDialog>
#include <QJsonDocument>
#include <QPainter>
#include <QLabel>
#include <QLineEdit>
#include <QMenuBar>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSettings>
#include <QShortcut>
#include <QStatusBar>
#include <QTextBrowser>
#include <QTimer>
#include <QToolBar>
#include <QTreeWidget>
#include <QVBoxLayout>
#include <QDir>
#include <Standard_Version.hxx>
#include <cmath>

namespace {
QDoubleSpinBox* number(QFormLayout* form, const QString& title, double value, double minimum = -10000, double maximum = 10000) {
    auto* input = new QDoubleSpinBox;
    input->setRange(minimum, maximum); input->setDecimals(3); input->setValue(value);
    form->addRow(title, input); return input;
}
QPlainTextEdit* points(QFormLayout* form, const QString& title, const QString& initial) {
    auto* input = new QPlainTextEdit(initial);
    input->setMaximumHeight(110); form->addRow(title, input); return input;
}
QJsonArray parsePoints(QPlainTextEdit* input, int dimensions) {
    QJsonArray output;
    for (auto line : input->toPlainText().split('\n', Qt::SkipEmptyParts)) {
        auto values = line.split(',', Qt::SkipEmptyParts);
        if (values.size() != dimensions) throw std::runtime_error("Enter one comma-separated coordinate pair per line.");
        QJsonArray point;
        for (const auto& value : values) {
            bool ok; double coordinate = value.trimmed().toDouble(&ok);
            if (!ok || !std::isfinite(coordinate)) throw std::runtime_error("Coordinates must be finite numbers.");
            point.append(coordinate);
        }
        output.append(point);
    }
    return output;
}
QDockWidget* dock(QMainWindow* window, const QString& title, const QString& name, QWidget* content, Qt::DockWidgetArea area) {
    auto* widget = new QDockWidget(title, window); widget->setObjectName(name); widget->setWidget(content);
    window->addDockWidget(area, widget); return widget;
}
}

MainWindow::MainWindow(const QString& source, const QString& python, const QString& openPath, bool smokeTest, QWidget* parent)
    : QMainWindow(parent), smoke(smokeTest), workspace(source) {
    setWindowTitle("Prompt to CAD — Native Workspace");
    resize(1500, 940);
    viewer = new CadView(this); setCentralWidget(viewer);
    rpc = new RpcClient(this);
    tree = new QTreeWidget; tree->setHeaderLabels({"Model"}); tree->setMinimumWidth(210);
    dock(this, "Assembly", "assembly", tree, Qt::LeftDockWidgetArea);
    history = new QTreeWidget; history->setHeaderLabels({"Accepted revisions"});
    dock(this, "History", "history", history, Qt::LeftDockWidgetArea);
    properties = new QPlainTextEdit; properties->setReadOnly(true);
    properties->setPlaceholderText("Select a body, face or edge to inspect its geometry.");
    dock(this, "Properties · mm", "properties", properties, Qt::BottomDockWidgetArea);
    auto* chatPanel = new QWidget;
    auto* chatLayout = new QVBoxLayout(chatPanel);
    auto* heading = new QLabel("CAD Copilot"); heading->setStyleSheet("font-size:20px;font-weight:600;padding:8px 0");
    chatLayout->addWidget(heading);
    chat = new QTextBrowser; chat->setOpenExternalLinks(false); chatLayout->addWidget(chat, 1);
    prompt = new QPlainTextEdit; prompt->setPlaceholderText("Describe a design, or ask for a change to the selected geometry…\nCtrl+Enter to send");
    prompt->setMaximumHeight(150); chatLayout->addWidget(prompt);
    auto* buttons = new QHBoxLayout;
    runButton = new QPushButton("Run"); cancelButton = new QPushButton("Stop");
    buttons->addWidget(runButton, 1); buttons->addWidget(cancelButton); chatLayout->addLayout(buttons);
    auto* chatDock = dock(this, "Conversation", "conversation", chatPanel, Qt::RightDockWidgetArea);
    chatDock->setMinimumWidth(340);
    chat->setHtml("<p style='color:#b6a7e8'><b>Design, inspect, refine.</b></p><p>Open a STEP model or describe a new design. Select geometry to focus a change. Completed edits are saved automatically.</p>");
    activity = new QLabel("Starting the document service…");
    statusBar()->addWidget(activity, 1);

    auto* file = menuBar()->addMenu("&File");
    auto* open = file->addAction("Open STEP / editable CAD…");
    open->setShortcut(QKeySequence::Open); mutationActions.append(open);
    connect(open, &QAction::triggered, this, [this] { openFile(); });
    auto* openProject = file->addAction("Open native project directory…"); mutationActions.append(openProject);
    connect(openProject, &QAction::triggered, this, [this] {
        auto folder = QFileDialog::getExistingDirectory(this, "Open a native CAD project");
        if (!folder.isEmpty()) openFile(folder);
    });
    auto* generate = file->addAction("New design from prompt…"); mutationActions.append(generate);
    connect(generate, &QAction::triggered, this, [this] {
        bool ok; auto text = QInputDialog::getMultiLineText(this, "New design", "Parts, dimensions and relationships", {}, &ok);
        if (ok && !text.trimmed().isEmpty()) request("document.generate", {{"prompt", text}}, [this](auto result, auto failure) {
            if (!failure.isEmpty()) { error(failure); return; }
            if (result.contains("document")) showDocument(result.value("document").toObject());
            else chat->append(result.value("message").toString().toHtmlEscaped());
        });
    });
    auto* saveAs = file->addAction("Save project copy…"); mutationActions.append(saveAs);
    connect(saveAs, &QAction::triggered, this, [this] {
        if (document.isEmpty()) return;
        auto folder = QFileDialog::getSaveFileName(this, "New project directory", QDir::homePath() + "/Design.cadproj", "Native project directory (*.cadproj)");
        if (folder.isEmpty()) return;
        auto params = baseParams(); params["destination"] = folder;
        request("document.save_as", params, [this](auto result, auto failure) { if (failure.isEmpty()) showDocument(result, false); else error(failure); });
    });
    auto* exportAction = file->addAction("Export STEP / STL…"); mutationActions.append(exportAction);
    connect(exportAction, &QAction::triggered, this, [this] {
        if (document.isEmpty()) return;
        auto path = QFileDialog::getSaveFileName(this, "Export CAD", QDir::homePath() + "/Design.step", "STEP (*.step);;STL (*.stl)");
        if (path.isEmpty()) return;
        auto params = baseParams(); params["path"] = path;
        request("document.export", params, [this](auto result, auto failure) {
            if (!failure.isEmpty()) error(failure);
            else activity->setText("Exported " + result.value("path").toString());
        });
    });
    file->addSeparator(); file->addAction("Exit", this, &QWidget::close);
    auto* editMenu = menuBar()->addMenu("&Edit");
    undoAction = editMenu->addAction("Undo"); undoAction->setShortcut(QKeySequence::Undo);
    redoAction = editMenu->addAction("Redo"); redoAction->setShortcut(QKeySequence::Redo);
    for (auto* action : {undoAction, redoAction}) {
        connect(action, &QAction::triggered, this, [this, action] {
            request(action == undoAction ? "document.undo" : "document.redo", baseParams(), [this](auto result, auto failure) {
                if (failure.isEmpty()) showDocument(result, false); else error(failure);
            });
        });
    }
    auto* tools = menuBar()->addMenu("&Model");
    for (const auto& pair : QList<QPair<QString, QString>>{
         {"Hole / hole centres…", "hole"}, {"Fillet selected edges…", "fillet"}, {"Chamfer selected edges…", "chamfer"},
         {"Extrude / cut profile…", "extrude"}, {"Pattern holes…", "pattern"}, {"Boolean with another body…", "boolean"},
         {"Transform instance…", "transform"}, {"Edit named parameters…", "parameters"}}) {
        auto* action = tools->addAction(pair.first); mutationActions.append(action);
        connect(action, &QAction::triggered, this, [this, tool = pair.second] { manualTool(tool); });
    }
    auto* settingsMenu = menuBar()->addMenu("&Settings");
    auto* modelSettings = settingsMenu->addAction("Model connection…"); mutationActions.append(modelSettings);
    connect(modelSettings, &QAction::triggered, this, [this] {
        request("workspace.model", {}, [this](auto current, auto failure) {
            if (!failure.isEmpty()) { error(failure); return; }
            QDialog dialog(this); dialog.setWindowTitle("Copilot model connection");
            auto* form = new QFormLayout(&dialog);
            auto* endpoint = new QLineEdit(current.value("base_url").toString()); form->addRow("API base URL", endpoint);
            auto* model = new QLineEdit(current.value("model").toString()); form->addRow("Model", model);
            auto* key = new QLineEdit; key->setEchoMode(QLineEdit::Password);
            key->setPlaceholderText(current.value("has_api_key").toBool() ? "Leave blank to keep the key for this endpoint" : "Optional for a local server");
            form->addRow("API key", key);
            auto* timeout = number(form, "Request timeout (seconds)", current.value("timeout").toDouble(90), 1, 600);
            auto* jsonMode = new QCheckBox("Provider supports JSON-object responses"); jsonMode->setChecked(current.value("json_mode").toBool()); form->addRow(jsonMode);
            auto* buttons = new QDialogButtonBox(QDialogButtonBox::Save | QDialogButtonBox::Cancel); form->addRow(buttons);
            connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
            connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
            if (dialog.exec() != QDialog::Accepted) return;
            request("workspace.configure", {{"base_url", endpoint->text().trimmed()}, {"model", model->text().trimmed()},
                    {"api_key", key->text()}, {"timeout", timeout->value()}, {"json_mode", jsonMode->isChecked()}},
                    [this](auto saved, auto message) {
                        if (!message.isEmpty()) error(message); else activity->setText("Copilot connected · " + saved.value("model").toString());
                    });
        });
    });
    auto* viewMenu = menuBar()->addMenu("&View");
    viewMenu->addAction("Fit all", QKeySequence("F"), viewer, &CadView::fitAll);
    for (const auto& direction : {"isometric", "top", "front"})
        connect(viewMenu->addAction(direction), &QAction::triggered, this, [this, direction] { viewer->standardView(direction); });
    connect(viewMenu->addAction("Isolate selected body"), &QAction::triggered, this, [this] {
        const auto id = selected.value("instance_id").toString();
        if (id.isEmpty()) return;
        for (const auto& item : document.value("components").toArray()) {
            auto part = item.toObject(); viewer->setVisibleInstance(part["instance_id"].toString(), part["instance_id"].toString() == id);
        }
    });
    connect(viewMenu->addAction("Show all"), &QAction::triggered, this, [this] {
        for (const auto& item : document.value("components").toArray()) viewer->setVisibleInstance(item.toObject()["instance_id"].toString(), true);
    });
    auto* toolbar = addToolBar("Workspace"); toolbar->setObjectName("workspace-toolbar"); toolbar->setMovable(false);
    toolbar->addAction(open); toolbar->addSeparator(); toolbar->addAction(undoAction); toolbar->addAction(redoAction);
    toolbar->addSeparator(); toolbar->addAction("Fit", viewer, &CadView::fitAll);
    toolbar->addWidget(new QLabel("  Select "));
    auto* selectionMode = new QComboBox; selectionMode->addItems({"Body", "Face", "Edge", "Vertex"});
    toolbar->addWidget(selectionMode);
    connect(selectionMode, &QComboBox::currentTextChanged, this, [this](auto text) { viewer->setSelectionMode(text.toLower()); });
    auto* hint = new QLabel("   Drag: orbit  ·  Middle/Shift-drag: pan  ·  Wheel: zoom  ·  Ctrl-click: multi-select");
    hint->setStyleSheet("color:#98a4b5;font-size:11px"); toolbar->addWidget(hint);
    connect(tree, &QTreeWidget::itemClicked, this, [this](auto* item, int) {
        auto id = item->data(0, Qt::UserRole).toString(); if (!id.isEmpty()) viewer->selectInstance(id);
    });
    connect(tree, &QTreeWidget::itemChanged, this, [this](auto* item, int) {
        auto id = item->data(0, Qt::UserRole).toString();
        if (!id.isEmpty()) viewer->setVisibleInstance(id, item->checkState(0) == Qt::Checked);
    });
    connect(viewer, &CadView::selectionChanged, this, &MainWindow::inspectSelection);
    connect(viewer, &CadView::viewerError, this, [this](auto message) { viewerFailed = true; error(message); });
    connect(runButton, &QPushButton::clicked, this, &MainWindow::sendPrompt);
    connect(cancelButton, &QPushButton::clicked, rpc, &RpcClient::cancel);
    auto* sendShortcut = new QShortcut(QKeySequence("Ctrl+Return"), prompt);
    connect(sendShortcut, &QShortcut::activated, this, &MainWindow::sendPrompt);
    connect(rpc, &RpcClient::progress, this, [this](auto event) {
        activity->setText(event.value("message").toString());
    });
    connect(rpc, &RpcClient::stopped, this, [this](auto message) { setBusy(true); error(message); });
    connect(rpc, &RpcClient::ready, this, [this, openPath] {
        rpc->call("workspace.hello", {}, [this, openPath](auto hello, auto failure) {
            if (!failure.isEmpty()) { error(failure); return; }
            auto kernel = hello.value("occt_version").toString().split('.');
            auto viewerVersion = QString(OCC_VERSION_COMPLETE).split('.');
            if (kernel.mid(0, 2) != viewerVersion.mid(0, 2)) { error("Viewer and geometry worker use different OCCT versions."); return; }
            setBusy(false);
            const auto model = hello.value("model").toObject();
            activity->setText(model.value("configured").toBool() ? "Ready · " + model.value("model").toString() : "Ready · open Settings → Model connection to use Copilot");
            if (!openPath.isEmpty()) openFile(openPath);
            else if (!smoke) {
                auto last = QSettings().value("lastProject").toString();
                if (QFileInfo::exists(last + "/project.json")) openFile(last);
            }
        });
    });
    QSettings settings;
    if (!smoke) { restoreGeometry(settings.value("windowGeometry").toByteArray()); restoreState(settings.value("windowState").toByteArray()); }
    setBusy(true);
    rpc->start(source, python);
    if (smoke) QTimer::singleShot(150000, this, [] { qCritical("Native smoke test timed out."); QApplication::exit(3); });
}
MainWindow::~MainWindow() {
    if (!smoke) { QSettings settings; settings.setValue("windowGeometry", saveGeometry()); settings.setValue("windowState", saveState()); }
}
void MainWindow::setBusy(bool active) {
    busy = active;
    for (auto* action : mutationActions) action->setEnabled(!active);
    undoAction->setEnabled(!active && document.value("can_undo").toBool());
    redoAction->setEnabled(!active && document.value("can_redo").toBool());
    runButton->setEnabled(!active); cancelButton->setEnabled(active);
}
QJsonObject MainWindow::baseParams() const { return {{"base_revision_id", document.value("revision_id")}}; }
void MainWindow::request(const QString& method, QJsonObject params, RpcClient::Callback callback) {
    if (busy) return;
    setBusy(true);
    rpc->call(method, params, [this, callback = std::move(callback)](auto result, auto failure) {
        setBusy(false); activity->setText("Ready");
        callback(result, failure);
    });
}
void MainWindow::error(const QString& message) {
    activity->setText(message);
    chat->append("<p style='color:#e9a49f'>" + message.toHtmlEscaped() + "</p>");
    if (smoke) { qCritical().noquote() << message; QTimer::singleShot(0, [] { QApplication::exit(2); }); }
}
void MainWindow::openFile(const QString& supplied) {
    auto path = supplied;
    if (path.isEmpty()) path = QFileDialog::getOpenFileName(this, "Open CAD", {}, "CAD files (*.step *.stp *.cad.json project.json)");
    if (path.isEmpty()) return;
    const bool native = QFileInfo(path).isDir() || QFileInfo(path).fileName() == "project.json";
    request(native ? "document.open" : "document.import", {{"path", path}}, [this](auto snapshot, auto failure) {
        if (!failure.isEmpty()) { error(failure); return; }
        showDocument(snapshot);
        if (!snapshot.value("recovery_message").toString().isEmpty()) activity->setText(snapshot.value("recovery_message").toString());
        if (smoke) QTimer::singleShot(500, this, &MainWindow::completeSmoke);
    });
}
void MainWindow::showDocument(const QJsonObject& snapshot, bool fit) {
    document = snapshot; selected = {};
    setWindowTitle(document.value("name").toString() + " — Prompt to CAD");
    tree->blockSignals(true); tree->clear();
    QMap<QString, QTreeWidgetItem*> groups;
    for (const auto& item : document.value("assembly_nodes").toArray()) {
        auto node = item.toObject();
        auto* group = new QTreeWidgetItem(QStringList{node.value("name").toString()});
        auto parent = groups.value(node.value("parent_id").toString());
        if (parent) parent->addChild(group); else tree->addTopLevelItem(group);
        groups.insert(node.value("id").toString(), group);
    }
    for (const auto& item : document.value("components").toArray()) {
        auto part = item.toObject();
        auto* row = new QTreeWidgetItem(QStringList{part.value("name").toString()});
        row->setData(0, Qt::UserRole, part.value("instance_id").toString());
        row->setCheckState(0, Qt::Checked);
        auto* group = groups.value(part.value("parent_id").toString());
        if (group) group->addChild(row); else tree->addTopLevelItem(row);
    }
    tree->expandAll(); tree->blockSignals(false); history->clear();
    for (const auto& item : document.value("history").toArray()) {
        auto revision = item.toObject();
        auto* row = new QTreeWidgetItem(history, {revision.value("summary").toString()});
        if (revision.value("revision_id") == document.value("revision_id")) row->setSelected(true);
    }
    if (document.contains("conversation")) {
        chat->clear();
        for (const auto& item : document.value("conversation").toArray()) {
            auto message = item.toObject();
            chat->append("<b>" + message.value("role").toString().toHtmlEscaped() + "</b><p>" +
                         message.value("content").toString().toHtmlEscaped().replace('\n', "<br>") + "</p>");
        }
    }
    properties->setPlainText(QString("%1\n%2 solid components · millimetres\nChanges are saved automatically. Select geometry to inspect or edit it.")
        .arg(document.value("name").toString()).arg(document.value("components").toArray().size()));
    viewer->setDocument(document, fit); setBusy(false);
    if (!smoke) QSettings().setValue("lastProject", document.value("project_dir").toString());
}
void MainWindow::inspectSelection(const QJsonObject& selection) {
    selected = selection;
    if (selected.isEmpty() || busy || smoke) return;
    auto params = baseParams(); params["instance_id"] = selected.value("instance_id");
    auto reference = selected;
    request("document.inspect", params, [this, reference](auto result, auto failure) {
        if (!failure.isEmpty()) { error(failure); return; }
        if (reference != selected) return;
        auto parts = result.value("components").toArray();
        if (parts.isEmpty()) return;
        auto part = parts.first().toObject();
        QJsonObject details{{"name", part.value("name")}, {"selection", reference}, {"metrics", part.value("metrics")}};
        auto kind = reference.value("kind").toString();
        if (kind == "edge" || kind == "face") {
            for (const auto& item : part.value(kind + "s").toArray())
                if (item.toObject().value("index") == reference.value("index")) details["geometry"] = item;
        }
        auto dimensions = part.value("metrics").toObject().value("dimensions_mm").toArray();
        QString description = part.value("name").toString() + "\n" + kind + " selection";
        if (reference.value("index").toInt() > 0) description += " " + QString::number(reference.value("index").toInt());
        if (dimensions.size() == 3) description += QString("\nBody size: %1 × %2 × %3 mm").arg(dimensions[0].toDouble(), 0, 'f', 3).arg(dimensions[1].toDouble(), 0, 'f', 3).arg(dimensions[2].toDouble(), 0, 'f', 3);
        description += QString("\nVolume: %1 mm³").arg(part.value("metrics").toObject().value("volume_mm3").toDouble(), 0, 'f', 3);
        auto geometry = details.value("geometry").toObject();
        if (geometry.contains("length_mm")) description += QString("\nEdge length: %1 mm").arg(geometry.value("length_mm").toDouble(), 0, 'f', 3);
        if (geometry.contains("area_mm2")) description += QString("\nFace area: %1 mm²").arg(geometry.value("area_mm2").toDouble(), 0, 'f', 3);
        if (geometry.contains("type")) description += "\nGeometry: " + geometry.value("type").toString();
        properties->setPlainText(description);
    });
}
void MainWindow::edit(QJsonObject command) {
    auto params = baseParams(); params["command"] = command;
    if (!selected.isEmpty()) params["selection"] = selected;
    request("document.command", params, [this](auto result, auto failure) {
        if (!failure.isEmpty()) { error(failure); return; }
        showDocument(result.value("document").toObject(), false);
    });
}
void MainWindow::sendPrompt() {
    if (busy || prompt->toPlainText().trimmed().isEmpty()) return;
    auto text = prompt->toPlainText().trimmed(); prompt->clear();
    chat->append("<b>You</b><p>" + text.toHtmlEscaped().replace('\n', "<br>") + "</p>");
    auto params = document.isEmpty() ? QJsonObject{} : baseParams();
    params["prompt"] = text;
    if (!selected.isEmpty()) params["selection"] = selected;
    request(document.isEmpty() ? "document.generate" : "agent.run", params, [this](auto result, auto failure) {
        if (!failure.isEmpty()) { error(failure); return; }
        if (result.contains("document")) showDocument(result.value("document").toObject(), false);
        else chat->append(result.value("message").toString().toHtmlEscaped());
    });
}
void MainWindow::manualTool(const QString& tool) {
    auto id = selected.value("instance_id").toString();
    if (id.isEmpty()) { activity->setText("Select a body, face or edge first."); return; }
    QDialog dialog(this); dialog.setWindowTitle(tool + " · millimetres");
    auto* layout = new QFormLayout(&dialog);
    QJsonObject command{{"type", tool}, {"instance_id", id}};
    QList<QDoubleSpinBox*> coordinates;
    QDoubleSpinBox *size = nullptr, *depth = nullptr, *count = nullptr;
    QComboBox *axis = nullptr, *mode = nullptr, *operation = nullptr, *other = nullptr;
    QPlainTextEdit* centres = nullptr;
    QMap<QString, QDoubleSpinBox*> parameters;
    if (tool == "hole" || tool == "pattern") {
        size = number(layout, "Diameter", 6, 0.001, 2000); depth = number(layout, "Depth (0 = through)", 0, 0);
        axis = new QComboBox; axis->addItems({"Z", "X", "Y"}); layout->addRow("Axis", axis);
        centres = points(layout, "Centres (x,y / y,z / x,z)", "-30,-20\n-30,20\n30,-20\n30,20");
        if (tool == "pattern") {
            centres->setPlainText("0,0"); count = number(layout, "Count including seed", 4, 2, 100); count->setDecimals(0);
            mode = new QComboBox; mode->addItems({"linear", "circular"}); layout->addRow("Pattern", mode);
            for (auto label : {"Step X / axis X", "Step Y / axis Y", "Step Z / axis Z"}) coordinates.append(number(layout, label, coordinates.isEmpty() ? 10 : 0));
            layout->addRow(new QLabel("Circular pattern axis passes through the local origin."));
        }
    } else if (tool == "fillet" || tool == "chamfer") {
        if (viewer->selectedEdges(id).isEmpty()) { activity->setText("Choose Edge selection and Ctrl-click the edges to treat."); return; }
        size = number(layout, tool == "fillet" ? "Radius" : "Distance", 2, 0.001, 2000);
    } else if (tool == "transform") {
        for (auto label : {"Translate X", "Translate Y", "Translate Z", "Rotate X (degrees)", "Rotate Y (degrees)", "Rotate Z (degrees)"})
            coordinates.append(number(layout, label, 0));
    } else if (tool == "extrude") {
        centres = points(layout, "Closed profile points (x,y)", "-10,-5\n10,-5\n10,5\n-10,5");
        for (auto label : {"Origin X", "Origin Y", "Origin Z"}) coordinates.append(number(layout, label, 0));
        size = number(layout, "Distance along local +Z", 10);
        operation = new QComboBox; operation->addItems({"cut", "add", "intersect"}); layout->addRow("Operation", operation);
    } else if (tool == "boolean") {
        other = new QComboBox;
        for (const auto& item : document.value("components").toArray()) {
            auto part = item.toObject(); if (part.value("instance_id") != id) other->addItem(part.value("name").toString(), part.value("instance_id").toString());
        }
        layout->addRow("Tool body (retained)", other);
        operation = new QComboBox; operation->addItems({"cut", "add", "intersect"}); layout->addRow("Operation", operation);
    } else if (tool == "parameters") {
        for (const auto& item : document.value("components").toArray()) {
            auto part = item.toObject(); if (part.value("instance_id") != id) continue;
            auto values = part.value("parameters").toObject();
            for (auto it = values.begin(); it != values.end(); ++it)
                if (it.value().isDouble()) parameters[it.key()] = number(layout, it.key(), it.value().toDouble());
        }
        if (parameters.isEmpty() || document.value("direct_edits").toBool()) { activity->setText("Named parameters require a generated recipe without downstream direct edits."); return; }
    }
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel);
    layout->addRow(buttons);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() != QDialog::Accepted) return;
    try {
        if (tool == "hole" || tool == "pattern") {
            QJsonObject hole{{"type", "hole"}, {"instance_id", id}, {"diameter", size->value()},
                             {"centres", parsePoints(centres, 2)}, {"axis", axis->currentText()},
                             {"depth", depth->value() == 0 ? QJsonValue(QJsonValue::Null) : QJsonValue(depth->value())}};
            if (tool == "hole") command = hole;
            else {
                command["seed"] = hole; command["mode"] = mode->currentText(); command["count"] = int(count->value());
                QJsonArray values; for (auto* coordinate : coordinates) values.append(coordinate->value());
                if (mode->currentText() == "linear") command["step"] = values;
                else { command["axis_direction"] = values; command["angle"] = 360; }
            }
        } else if (tool == "fillet" || tool == "chamfer") {
            command["edge_indices"] = viewer->selectedEdges(id); command["size"] = size->value();
        } else if (tool == "transform") {
            QJsonArray translation, rotation;
            for (int i = 0; i < 3; ++i) { translation.append(coordinates[i]->value()); rotation.append(coordinates[i+3]->value()); }
            command["translation"] = translation; command["rotation"] = rotation;
        } else if (tool == "extrude") {
            QJsonArray origin; for (auto* coordinate : coordinates) origin.append(coordinate->value());
            command["origin"] = origin; command["profile"] = parsePoints(centres, 2); command["distance"] = size->value();
            command["operation"] = operation->currentText();
        } else if (tool == "boolean") {
            command["tool_instance_id"] = other->currentData().toString(); command["operation"] = operation->currentText();
        } else if (tool == "parameters") {
            QJsonObject values; for (auto it = parameters.begin(); it != parameters.end(); ++it) values[it.key()] = it.value()->value();
            command["values"] = values;
        }
        edit(command);
    } catch (const std::exception& exception) { error(QString::fromUtf8(exception.what())); }
}
void MainWindow::completeSmoke() {
    if (viewerFailed || document.isEmpty() || viewer->bodyCount() != document.value("components").toArray().size()) {
        error("Native viewport did not display all imported instances."); return;
    }
    const bool selectedFace = viewer->smokeSelectFace();
    if (!selectedFace) { error("Native topology selection did not produce the expected face reference."); return; }
    auto report = QJsonObject{{"passed", true}, {"body_count", viewer->bodyCount()},
        {"face_selection", selectedFace}, {"topology", viewer->topologyReport()}, {"occt_viewer", OCC_VERSION_COMPLETE},
        {"qt_version", QT_VERSION_STR}, {"synthetic_orbit_fps", viewer->benchmarkOrbit()}};
    QDir().mkpath(QDir(workspace).filePath("tmp"));
    auto output = QDir(workspace).filePath("tmp/native-smoke-report.json");
    QFile file(output); if (file.open(QIODevice::WriteOnly)) file.write(QJsonDocument(report).toJson());
    viewer->setSelectionMode("body");
    QTimer::singleShot(400, this, [this] {
        const auto renderPath = QDir(workspace).filePath("tmp/native-viewport.png");
        if (!viewer->saveViewport(renderPath)) { error("Could not capture the native OpenGL viewport."); return; }
        auto screenshot = grab();
        QPainter painter(&screenshot);
        painter.drawImage(QRect(viewer->mapTo(this, QPoint(0, 0)), viewer->size()), QImage(renderPath));
        painter.end();
        screenshot.save(QDir(workspace).filePath("tmp/native-workspace.png"));
        QApplication::exit(0);
    });
}
