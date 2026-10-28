#include <QApplication>
#include <QCommandLineParser>
#include <QDir>
#include <QFileInfo>
#include <QFile>
#include <QUuid>
#include <QSettings>
#include <cstdio>
#include "MainWindow.h"
#include "WorkspaceWindow.h"
#include <memory>

int main(int argc, char** argv) {
    qInstallMessageHandler([](QtMsgType type, const QMessageLogContext&, const QString& message) {
        auto path = qEnvironmentVariable("CAD_UI_LOG", QString(CAD_SOURCE_ROOT) + "/tmp/native-ui.log");
        QFile log(path);
        if (log.open(QIODevice::Append)) log.write(message.toUtf8() + '\n');
        fprintf(stderr, "%s\n", message.toUtf8().constData());
        if (type == QtFatalMsg) fflush(stderr);
    });
    QApplication app(argc, argv);
    QCoreApplication::setOrganizationName("PromptToCAD");
    QCoreApplication::setApplicationName("PromptToCADV2");
    QCoreApplication::setApplicationVersion("0.3.0");
    QCommandLineParser parser; parser.addHelpOption(); parser.addVersionOption();
    parser.addOption({"workspace", "Application source/runtime directory.", "directory"});
    parser.addOption({"python", "Bundled Python interpreter.", "executable"});
    parser.addOption({"open", "STEP, editable recipe or native project to open.", "path"});
    parser.addOption({"smoke-test", "Verify real viewer import/selection, write a screenshot, and exit."});
    parser.addOption({"legacy-native", "Open the earlier native workspace for compatibility."});
    parser.addOption({"smoke-size", "Window size for UI validation (width x height).", "size"});
    parser.process(app);
    if(parser.isSet("smoke-test")){QCoreApplication::setApplicationName("PromptToCADV2Validation");QSettings settings;settings.clear();}
    auto workspace = parser.value("workspace");
    if (workspace.isEmpty()) {
        auto packaged = QDir(QCoreApplication::applicationDirPath()).filePath("../app");
        workspace = QFileInfo::exists(packaged + "/backend/native/service.py") ? packaged : QString(CAD_SOURCE_ROOT);
    }
    workspace = QDir(workspace).absolutePath();
    auto python = parser.value("python");
    if (python.isEmpty()) {
        auto bundled = QDir(QCoreApplication::applicationDirPath()).filePath("../python/python.exe");
        python = QFileInfo::exists(bundled) ? bundled : QDir(workspace).filePath(".venv/Scripts/python.exe");
    }
    app.setStyle("Fusion");
    app.setStyleSheet(R"(
        QWidget { background:#202123; color:#e2e8f2; font-family:'Segoe UI'; font-size:12px; }
        QMenuBar, QToolBar, QStatusBar { background:#242527; padding:5px; }
        #rail QPushButton { padding:8px 0; border:0; background:transparent; font-size:18px; }
        #navigation QPushButton { background:#26272b; border-color:#3b3c42; padding:7px 9px; text-align:left; }
        #accountBadge { font-size:11px; }
        QMenu { background:#242c39; } QMenu::item:selected { background:#3c4660; }
        QDockWidget { font-weight:600; } QDockWidget::title { padding:8px; background:#222a36; }
        QTreeWidget, QTextBrowser, QPlainTextEdit, QLineEdit { background:#1b1c1e; border:1px solid #353638; border-radius:4px; padding:6px; }
        QTreeWidget::item { padding:5px; } QTreeWidget::item:selected { background:#383459; }
        QPushButton { background:#34324d; border:1px solid #5d547b; border-radius:5px; padding:9px 18px; }
        QPushButton:hover { background:#484263; } QPushButton:disabled { color:#77808f; background:#242a35; border-color:#303744; }
        QComboBox, QDoubleSpinBox { padding:5px; background:#252d3a; border:1px solid #46516a; }
        QHeaderView::section { background:#252d3a; padding:7px; border:0; }
        QSplitter::handle { background:#30394a; }
    )");
    if (parser.isSet("smoke-test") && !parser.isSet("legacy-native") && qEnvironmentVariableIsEmpty("PROMPTCAD_HOME")) qputenv("PROMPTCAD_HOME", (workspace + "/tmp/ui-" + QUuid::createUuid().toString(QUuid::WithoutBraces).left(8)).toUtf8());
    std::unique_ptr<QMainWindow> window;
    if (parser.isSet("legacy-native")) window = std::make_unique<MainWindow>(workspace, python, parser.value("open"), parser.isSet("smoke-test"));
    else window = std::make_unique<WorkspaceWindow>(workspace, python, parser.value("open"), parser.isSet("smoke-test"));
    if (parser.isSet("smoke-size")) {
        auto dimensions=parser.value("smoke-size").split('x');
        if(dimensions.size()!=2 || dimensions[0].toInt()<880 || dimensions[1].toInt()<600)return 2;
        window->resize(dimensions[0].toInt(),dimensions[1].toInt());
    }
    window->show();
    return app.exec();
}
