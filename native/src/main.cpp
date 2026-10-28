#include <QApplication>
#include <QCommandLineParser>
#include <QDir>
#include <QFileInfo>
#include <QFile>
#include <cstdio>
#include "MainWindow.h"

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
    QCoreApplication::setApplicationName("NativeWorkspace");
    QCoreApplication::setApplicationVersion("0.2.0");
    QCommandLineParser parser; parser.addHelpOption(); parser.addVersionOption();
    parser.addOption({"workspace", "Application source/runtime directory.", "directory"});
    parser.addOption({"python", "Bundled Python interpreter.", "executable"});
    parser.addOption({"open", "STEP, editable recipe or native project to open.", "path"});
    parser.addOption({"smoke-test", "Verify real viewer import/selection, write a screenshot, and exit."});
    parser.process(app);
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
        QWidget { background:#171c24; color:#e2e8f2; font-family:'Segoe UI'; font-size:12px; }
        QMenuBar, QToolBar, QStatusBar { background:#1f2631; padding:5px; }
        QMenu { background:#242c39; } QMenu::item:selected { background:#3c4660; }
        QDockWidget { font-weight:600; } QDockWidget::title { padding:8px; background:#222a36; }
        QTreeWidget, QTextBrowser, QPlainTextEdit, QLineEdit { background:#11161e; border:1px solid #313b4b; border-radius:4px; padding:6px; }
        QTreeWidget::item { padding:5px; } QTreeWidget::item:selected { background:#383459; }
        QPushButton { background:#34324d; border:1px solid #5d547b; border-radius:5px; padding:9px 18px; }
        QPushButton:hover { background:#484263; } QPushButton:disabled { color:#77808f; background:#242a35; border-color:#303744; }
        QComboBox, QDoubleSpinBox { padding:5px; background:#252d3a; border:1px solid #46516a; }
        QHeaderView::section { background:#252d3a; padding:7px; border:0; }
        QSplitter::handle { background:#30394a; }
    )");
    MainWindow window(workspace, python, parser.value("open"), parser.isSet("smoke-test"));
    window.show();
    return app.exec();
}
