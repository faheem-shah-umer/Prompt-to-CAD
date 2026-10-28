#pragma once
#include <QObject>
#include <QProcess>
#include <QJsonObject>
#include <QHash>
#include <functional>

class RpcClient : public QObject {
    Q_OBJECT
public:
    using Callback = std::function<void(const QJsonObject&, const QString&)>;
    explicit RpcClient(QObject* parent = nullptr);
    ~RpcClient() override;
    void start(const QString& workspace, const QString& python, const QString& module = "backend.native.service");
    void call(const QString& method, const QJsonObject& params, Callback callback);
    void cancel();
Q_SIGNALS:
    void ready();
    void progress(const QJsonObject& event);
    void stopped(const QString& message);
private:
    void read();
    void failPending(const QString& error);
    QProcess process;
    QByteArray buffer;
    QHash<qint64, Callback> callbacks;
    qint64 nextId = 1;
    void* job = nullptr;
};
