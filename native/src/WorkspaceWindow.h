#pragma once
#include <QElapsedTimer>
#include <QJsonArray>
#include <QJsonObject>
#include <QList>
#include <QMainWindow>
#include <QPointer>
class QDialog;
#include "RpcClient.h"
class CadView;
class QSplitter;
class QTreeWidget;
class QTabBar;
class QTabWidget;
class QTextBrowser;
class QPlainTextEdit;
class QPushButton;
class QLabel;
class QComboBox;
class QCheckBox;
class QLineEdit;
class QFormLayout;
class QDoubleSpinBox;
class QResizeEvent;
class QProgressBar;
class QTimer;

class WorkspaceWindow : public QMainWindow {
    Q_OBJECT
  public:
    WorkspaceWindow(const QString &source, const QString &python, const QString &openPath,
                    bool smokeTest = false);
    ~WorkspaceWindow() override;

  Q_SIGNALS:
    void workspaceReady();

  protected:
    void resizeEvent(QResizeEvent *) override;

  private:
    void call(const QString &, QJsonObject = {}, std::function<void(QJsonObject)> done = {});
    void showState(const QJsonObject &, bool fit = false);
    void openFile(const QString &path = {});
    void newProject();
    void manageProjects();
    void account();
    void discoverModels();
    void submit();
    void select(const QJsonObject &);
    void operation(const QString &);
    void applyOperation();
    void showError(const QString &);
    void smokeCheck();
    void renderChat();
    void updateTask(const QString &status, const QString &message);
    void refreshUsage();
    void updateUsage();
    void refreshConnectionControls();
    void applyAppearance();
    QJsonObject base() const;
    CadView *viewer;
    RpcClient *rpc;
    QSplitter *split;
    QWidget *navigation, *manager, *conversationPane, *operationPane, *emptyPage;
    QTreeWidget *projects, *modelTree, *revisions;
    QTabBar *documentTabs;
    QTabWidget *managerTabs;
    QTextBrowser *chat, *properties;
    QPlainTextEdit *composer;
    QPushButton *sendButton, *stopButton, *selectionChip, *accountBadge;
    QPushButton *usageBadge;
    QLabel *taskTitle, *taskElapsed, *tokenUsageLabel;
    QProgressBar *taskProgress;
    QTimer *taskPulse, *chatRefresh;
    QElapsedTimer taskClock;
    QString pendingUser, liveAnswer, currentTaskState;
    QLabel *activity, *title, *saved, *conversationTitle, *taskActivity;
    QPlainTextEdit *taskLog;
    QPointer<QDialog> settingsDialog;
    QString activeTaskId;
    QComboBox *models, *selectionMode;
    QLineEdit *search, *treeFilter;
    QFormLayout *operationForm;
    QList<QDoubleSpinBox *> fields;
    QAction *undoAction, *redoAction;
    QJsonObject state, document, selected, operationSelection;
    QString workspace, currentOperation;
    bool settingsVerified = false;
    int settingsSaves = 0;
    bool busy = false, smoke = false, viewerFailed = false, loading = false;
};
