#include "WorkspaceWindow.h"
#include <QApplication>
#include <QCommandLineParser>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QSettings>
#include <QUuid>
#include <cstdio>
#include <memory>

int main(int argc, char **argv) {
    qInstallMessageHandler([](QtMsgType type, const QMessageLogContext &, const QString &message) {
        auto path = qEnvironmentVariable("CAD_UI_LOG", QString(CAD_SOURCE_ROOT) + "/tmp/native-ui.log");
        QFile log(path);
        if (log.open(QIODevice::Append))
            log.write(message.toUtf8() + '\n');
        fprintf(stderr, "%s\n", message.toUtf8().constData());
        if (type == QtFatalMsg)
            fflush(stderr);
    });
    QApplication app(argc, argv);
    QCoreApplication::setOrganizationName("PromptToCAD");
    QCoreApplication::setApplicationName("PromptToCADV2");
    QCoreApplication::setApplicationVersion("0.4.0");
    QCommandLineParser parser;
    parser.addHelpOption();
    parser.addVersionOption();
    parser.addOption({"workspace", "Application source/runtime directory.", "directory"});
    parser.addOption({"python", "Bundled Python interpreter.", "executable"});
    parser.addOption({"open", "STEP, editable recipe or native project to open.", "path"});
    parser.addOption({"smoke-test", "Verify real viewer import/selection, write a screenshot, and exit."});
    parser.addOption({"smoke-size", "Window size for UI validation (width x height).", "size"});
    parser.process(app);
    if (parser.isSet("smoke-test")) {
        QCoreApplication::setApplicationName("PromptToCADV2Validation");
        auto settingsPath =
            qEnvironmentVariable("PROMPTCAD_HOME", QDir::tempPath() + "/promptcad-ui-" +
                                                       QUuid::createUuid().toString(QUuid::WithoutBraces));
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, settingsPath + "/ui-settings");
        QSettings settings;
        settings.clear();
    }
    auto workspace = parser.value("workspace");
    if (workspace.isEmpty()) {
        auto packaged = QDir(QCoreApplication::applicationDirPath()).filePath("../app");
        workspace =
            QFileInfo::exists(packaged + "/backend/v2/service.py") ? packaged : QString(CAD_SOURCE_ROOT);
    }
    workspace = QDir(workspace).absolutePath();
    auto python = parser.value("python");
    if (python.isEmpty()) {
        auto bundled = QDir(QCoreApplication::applicationDirPath()).filePath("../python/python.exe");
        python = QFileInfo::exists(bundled) ? bundled : QDir(workspace).filePath(".venv/Scripts/python.exe");
    }
    app.setStyle("Fusion");
    app.setStyleSheet(R"(
        QWidget { background:#181b20; color:#dce2eb; font-family:'Segoe UI'; font-size:12px; }
        QMenuBar, QToolBar, QStatusBar { background:#1e2228; padding:4px; border:0; }
        #rail { background:#13161a; border-right:1px solid #2c323b; }
        #rail QPushButton { padding:9px 0; border:0; background:transparent; font-size:17px; }
        #navigation, #conversationPane { background:#1b1f25; }
        #navigation QPushButton { padding:7px 9px; text-align:left; }
        #accountBadge, #muted { color:#94a0b2; font-size:11px; }
        #taskActivity { color:#8bd0c7; padding:6px 0; }
        QMenu { background:#232932; border:1px solid #37404d; } QMenu::item:selected { background:#34424c; }
        QTreeWidget, QTextBrowser, QPlainTextEdit, QLineEdit { background:#181c22; border:1px solid #303844; border-radius:6px; padding:7px; }
        #conversationHistory { border:0; background:transparent; }
        QTreeWidget::item { padding:6px 3px; } QTreeWidget::item:selected { background:#2c4649; color:#e8f7f4; }
        QPushButton { background:#272e37; border:1px solid #3a4553; border-radius:5px; padding:6px 10px; }
        QPushButton:hover, QToolButton:hover { background:#35414d; }
        #primaryButton { background:#427d73; border-color:#52958a; color:#ffffff; font-weight:600; }
        QPushButton:disabled { color:#626d7c; background:#20262e; border-color:#2d3540; }
        QComboBox, QDoubleSpinBox { padding:5px; background:#232a33; border:1px solid #3c4858; border-radius:4px; }
        QTabWidget::pane { border:0; border-top:1px solid #303844; }
        QTabBar::tab { padding:7px 10px; background:#20262e; color:#9eabba; border-bottom:2px solid transparent; }
        QTabBar::tab:selected { color:#e6f2f0; border-bottom:2px solid #68b4a7; background:#283139; }
        QToolButton { background:transparent; border:0; padding:6px; color:#b5c1cf; }
        QHeaderView::section { background:#252c35; padding:7px; border:0; }
        QSplitter::handle { background:#2c3440; width:3px; }
        QScrollBar:vertical { background:#1b2027; width:9px; } QScrollBar::handle:vertical { background:#414c5c; border-radius:4px; min-height:25px; }

    )");
    if (parser.isSet("smoke-test") &&
        qEnvironmentVariableIsEmpty("PROMPTCAD_HOME"))
        qputenv(
            "PROMPTCAD_HOME",
            (workspace + "/tmp/ui-" + QUuid::createUuid().toString(QUuid::WithoutBraces).left(8)).toUtf8());
    auto window = std::make_unique<WorkspaceWindow>(workspace, python, parser.value("open"), parser.isSet("smoke-test"));
    if (parser.isSet("smoke-size")) {
        auto dimensions = parser.value("smoke-size").split('x');
        if (dimensions.size() != 2 || dimensions[0].toInt() < 880 || dimensions[1].toInt() < 600)
            return 2;
        window->resize(dimensions[0].toInt(), dimensions[1].toInt());
    }
    window->show();
    return app.exec();
}
