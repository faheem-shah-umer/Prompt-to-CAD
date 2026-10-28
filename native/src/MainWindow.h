#pragma once
#include <QMainWindow>
#include <QJsonObject>
#include "RpcClient.h"
class CadView;
class QTreeWidget;
class QTextBrowser;
class QPlainTextEdit;
class QPushButton;
class QLabel;
class QAction;

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    MainWindow(const QString& workspace, const QString& python, const QString& openPath, bool smokeTest, QWidget* parent = nullptr);
    ~MainWindow() override;
private:
    void openFile(const QString& path = {});
    void showDocument(const QJsonObject& snapshot, bool fit = true);
    void request(const QString& method, QJsonObject params, RpcClient::Callback callback);
    void edit(QJsonObject command);
    void sendPrompt();
    void manualTool(const QString& tool);
    void inspectSelection(const QJsonObject& selection);
    void setBusy(bool busy);
    void error(const QString& message);
    void completeSmoke();
    QJsonObject baseParams() const;
    CadView* viewer;
    RpcClient* rpc;
    QTreeWidget* tree;
    QTreeWidget* history;
    QTextBrowser* chat;
    QPlainTextEdit* prompt;
    QPlainTextEdit* properties;
    QPushButton* runButton;
    QPushButton* cancelButton;
    QLabel* activity;
    QAction* undoAction;
    QAction* redoAction;
    QList<QAction*> mutationActions;
    QJsonObject document;
    QJsonObject selected;
    bool busy = true;
    bool smoke = false;
    bool viewerFailed = false;
    QString workspace;
};
