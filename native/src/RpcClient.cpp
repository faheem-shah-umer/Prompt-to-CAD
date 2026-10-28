#include "RpcClient.h"
#include <QJsonDocument>
#include <QProcessEnvironment>
#include <QDir>
#ifdef Q_OS_WIN
#include <windows.h>
#endif

RpcClient::RpcClient(QObject* parent) : QObject(parent) {
    connect(&process, &QProcess::readyReadStandardOutput, this, &RpcClient::read);
    connect(&process, &QProcess::readyReadStandardError, this, [this] {
        const auto bytes = process.readAllStandardError();
        if (!bytes.isEmpty()) qWarning().noquote() << QString::fromUtf8(bytes).trimmed();
    });
    connect(&process, &QProcess::started, this, [this] {
#ifdef Q_OS_WIN
        job = CreateJobObjectW(nullptr, nullptr);
        if (job) {
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits));
            HANDLE child = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, FALSE, DWORD(process.processId()));
            if (child) {
                if (!AssignProcessToJobObject(job, child)) qWarning("Could not attach the service to the application job.");
                CloseHandle(child);
            }
        }
#endif
        Q_EMIT ready();
    });
    connect(&process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            const auto message = "Could not start the document service: " + process.errorString();
            failPending(message);
            Q_EMIT stopped(message);
        }
    });
    connect(&process, &QProcess::finished, this, [this](int, QProcess::ExitStatus) {
        const QString message = "The document service stopped. Reopen the application to recover the last accepted revision.";
        failPending(message);
        Q_EMIT stopped(message);
    });
}

RpcClient::~RpcClient() {
    process.disconnect(this);
    if (process.state() != QProcess::NotRunning) {
        call("workspace.shutdown", {}, [](auto, auto) {});
        process.closeWriteChannel();
        if (!process.waitForFinished(2000)) { process.kill(); process.waitForFinished(2000); }
    }
#ifdef Q_OS_WIN
    if (job) CloseHandle(job);
#endif
}

void RpcClient::start(const QString& workspace, const QString& python, const QString& module) {
    auto env = QProcessEnvironment::systemEnvironment();
    env.insert("PYTHONUNBUFFERED", "1");
    env.insert("PYTHONIOENCODING", "utf-8");
    process.setProcessEnvironment(env);
    process.setWorkingDirectory(workspace);
    process.setProgram(python);
    process.setArguments({"-B", "-m", module});
    process.start();
}

void RpcClient::call(const QString& method, const QJsonObject& params, Callback callback) {
    if (process.state() != QProcess::Running) { callback({}, "The document service is not running."); return; }
    const qint64 id = nextId++;
    callbacks.insert(id, std::move(callback));
    process.write(QJsonDocument(QJsonObject{{"jsonrpc", "2.0"}, {"id", id}, {"method", method}, {"params", params}})
                  .toJson(QJsonDocument::Compact) + '\n');
}
void RpcClient::cancel() { call("workspace.cancel", {}, [](auto, auto) {}); }

void RpcClient::read() {
    buffer += process.readAllStandardOutput();
    if (buffer.size() > 64 * 1024 * 1024) { process.kill(); failPending("The service response exceeded the protocol limit."); return; }
    qsizetype end;
    while ((end = buffer.indexOf('\n')) >= 0) {
        const auto line = buffer.left(end);
        buffer.remove(0, end + 1);
        QJsonParseError error;
        const auto message = QJsonDocument::fromJson(line, &error);
        if (error.error != QJsonParseError::NoError || !message.isObject()) {
            process.kill(); failPending("The service returned malformed JSON."); return;
        }
        const auto object = message.object();
        if (object.value("method") == "progress") { Q_EMIT progress(object.value("params").toObject()); continue; }
        const auto id = object.value("id").toInteger(-1);
        if (!callbacks.contains(id)) continue;
        auto callback = callbacks.take(id);
        callback(object.value("result").toObject(), object.value("error").toObject().value("message").toString());
    }
}
void RpcClient::failPending(const QString& error) {
    auto pending = std::move(callbacks);
    callbacks.clear();
    for (auto& callback : pending) callback({}, error);
}
