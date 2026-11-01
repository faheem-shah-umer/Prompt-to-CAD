#include "StartupSplash.h"
#include "WorkspaceControls.h"
#include "WorkspaceTheme.h"
#include "WorkspaceWindow.h"
#include <QApplication>
#include <QCommandLineParser>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QIcon>
#include <QSettings>
#include <QStandardPaths>
#include <QTimer>
#include <QUuid>
#include <cstdio>
#include <memory>

int main(int argc, char **argv) {
    qInstallMessageHandler([](QtMsgType type, const QMessageLogContext &, const QString &message) {
        auto path = qEnvironmentVariable("CAD_UI_LOG", QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation) + "/logs/ui.log");
        QDir().mkpath(QFileInfo(path).absolutePath());
        QFile log(path);
        if (log.open(QIODevice::Append))
            log.write(message.toUtf8() + '\n');
        fprintf(stderr, "%s\n", message.toUtf8().constData());
        if (type == QtFatalMsg)
            fflush(stderr);
    });
    QApplication app(argc, argv);
    installWorkspaceInteraction();
    app.setWindowIcon(QIcon(":/brand/app-icon.png"));
    QCoreApplication::setOrganizationName("PromptToCAD");
    QCoreApplication::setApplicationName("PromptToCADV2");
    QCoreApplication::setApplicationVersion(PROMPTCAD_VERSION);
    QCommandLineParser parser;
    parser.addHelpOption();
    parser.addVersionOption();
    parser.addOption({"workspace", "Application source/runtime directory.", "directory"});
    parser.addOption({"python", "Bundled Python interpreter.", "executable"});
    parser.addOption({"open", "STEP, editable recipe or native project to open.", "path"});
    parser.addOption({"smoke-test", "Verify real viewer import/selection, write a screenshot, and exit."});
    parser.addOption({"portable-smoke", "Isolated offline distribution check; no account access or inference."});
    parser.addOption({"demo-capture", "Capture a labelled synthetic demo in an isolated session.", "directory"});
    parser.addOption({"smoke-size", "Window size for UI validation (width x height).", "size"});
    parser.process(app);
    const bool distributionCheck = parser.isSet("portable-smoke") || parser.isSet("demo-capture");
    if (distributionCheck) {
        const auto output = parser.isSet("demo-capture") ? parser.value("demo-capture") : qEnvironmentVariable("CAD_CHECK_OUTPUT");
        if (output.isEmpty() || !parser.isSet("open")) return 2;
        const auto isolated = QDir(output).absoluteFilePath("session-" + QUuid::createUuid().toString(QUuid::WithoutBraces));
        qputenv("PROMPTCAD_HOME", (isolated + "/state").toUtf8());
        qputenv("PROMPTCAD_PROJECTS_DIR", (isolated + "/projects").toUtf8());
        qputenv("PROMPTCAD_IDENTITY_HOME", (isolated + "/identity").toUtf8());
        qputenv("CAD_UI_LOG", (isolated + "/ui.log").toUtf8());
        app.setProperty("distributionCaptureDir", QDir(output).absolutePath());
        app.setProperty("publicDemoCapture", parser.isSet("demo-capture"));
    }
    if (parser.isSet("smoke-test") || distributionCheck) {
        QCoreApplication::setApplicationName("PromptToCADV2Validation");
        auto settingsPath =
            qEnvironmentVariable("PROMPTCAD_HOME", QDir::tempPath() + "/promptcad-ui-" +
                                                       QUuid::createUuid().toString(QUuid::WithoutBraces));
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, settingsPath + "/ui-settings");
        QSettings settings;
        settings.clear();
        if (distributionCheck) settings.setValue("v2/onboardingDone", true);
    }
    auto workspace = parser.value("workspace");
    if (workspace.isEmpty()) {
        auto packaged = QDir(QCoreApplication::applicationDirPath()).filePath("../app");
        workspace =
            QFileInfo::exists(packaged + "/backend/v2/service.py") ? packaged : QDir::currentPath();
    }
    workspace = QDir(workspace).absolutePath();
    const auto shaders = QDir(QCoreApplication::applicationDirPath()).filePath("resources/Shaders");
    if (QFileInfo::exists(shaders)) qputenv("CSF_ShadersDirectory", shaders.toUtf8());
    auto python = parser.value("python");
    if (python.isEmpty()) {
        auto bundled = QDir(QCoreApplication::applicationDirPath()).filePath("../python/python.exe");
        python = QFileInfo::exists(bundled) ? bundled : QDir(workspace).filePath(".venv/Scripts/python.exe");
    }
    app.setStyle("Fusion");
    if ((parser.isSet("smoke-test") || distributionCheck) && qEnvironmentVariableIsSet("CAD_UI_THEME"))
        QSettings().setValue("v2/theme", qEnvironmentVariable("CAD_UI_THEME"));
    applyWorkspaceTheme(QSettings().value("v2/theme", "dark").toString(),
                        QSettings().value("v2/textSize", 14).toInt());
    if (parser.isSet("smoke-test") && qEnvironmentVariableIsEmpty("PROMPTCAD_HOME"))
        qputenv(
            "PROMPTCAD_HOME",
            (workspace + "/tmp/ui-" + QUuid::createUuid().toString(QUuid::WithoutBraces).left(8)).toUtf8());
    StartupSplash splash;
    QElapsedTimer startupClock;
    startupClock.start();
    splash.show();
    app.processEvents();
    if (parser.isSet("smoke-test")) {
        QDir().mkpath(workspace + "/tmp");
        QTimer::singleShot(150, &splash, [&splash, workspace] {
            splash.grab().save(workspace + "/tmp/native-startup.png");
        });
    }
    auto window = std::make_unique<WorkspaceWindow>(workspace, python, parser.value("open"),
                                                    parser.isSet("smoke-test"));
    if (parser.isSet("smoke-size")) {
        auto dimensions = parser.value("smoke-size").split('x');
        if (dimensions.size() != 2 || dimensions[0].toInt() < 880 || dimensions[1].toInt() < 600)
            return 2;
        window->resize(dimensions[0].toInt(), dimensions[1].toInt());
    }
    QObject::connect(window.get(), &WorkspaceWindow::workspaceReady, &splash, [&] {
        QTimer::singleShot(int(qMax<qint64>(0, 650 - startupClock.elapsed())), window.get(), [&] {
            window->show();
            splash.hide();
        });
    });
    return app.exec();
}
