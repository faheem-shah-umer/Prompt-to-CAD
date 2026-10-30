#pragma once
#include <QElapsedTimer>
#include <QJsonArray>
#include <QJsonObject>
#include <QList>
#include <QHash>
#include <QMainWindow>
#include <QPointer>
class QDialog;
#include "RpcClient.h"
class CadView;
class ConversationView;
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
class QTimer;

class WorkspaceWindow : public QMainWindow {
    Q_OBJECT
  public:
    WorkspaceWindow(const QString &source, const QString &python, const QString &openPath,
                    bool smokeTest = false);
    ~WorkspaceWindow() override;

  Q_SIGNALS:
    void workspaceReady();
    void conversationOpened();

  protected:
    void resizeEvent(QResizeEvent *) override;
    void changeEvent(QEvent *) override;

  private:
    void call(const QString &, QJsonObject = {}, std::function<void(QJsonObject)> done = {});
    void showState(const QJsonObject &, bool fit = false);
    void openFile(const QString &path = {});
    void newProject();
    void newConversation();
    void openConversation(const QString &projectId, const QString &conversationId);
    void revealConversation();
    void manageProjects();
    void account();
    void showAccountDetails();
    void showUsageDetails();
    void saveAs();
    void notify(const QString &, const QString &severity = "error");
    void batchConversations(const QJsonArray &, const QString &action);
    void discoverModels(bool refresh = false);
    void updateSendControl();
    void beginSignIn(const QString &registration = {}, bool newRegistration = false);
    void showOnboarding();
    void submit();
    QString takeComposerText();
    void select(const QJsonObject &);
    void operation(const QString &);
    void applyOperation();
    void showError(const QString &);
    void smokeCheck();
    void renderChat();
    void receiveAssistant(const QJsonObject &event, bool complete);
    void updateTask(const QString &status, const QString &message);
    bool focusOpenDialog();
    void openNativeProject();
    void updateUsage();
    void refreshConnectionControls();
    void refreshProjectTree();
    void filterProjects();
    void filterModels();
    void syncModelVisibility();
    void applyAppearance();
    QJsonObject base() const;
    CadView *viewer;
    RpcClient *rpc;
    QSplitter *split;
    QWidget *navigation, *manager, *conversationPane, *operationPane, *emptyPage;
    QTreeWidget *projects, *modelTree, *revisions;
    QTabBar *documentTabs;
    QTabWidget *managerTabs;
    ConversationView *chat;
    QTextBrowser *properties;
    QPlainTextEdit *composer;
    QPushButton *sendButton, *selectionChip, *accountBadge, *agentButton;
    QPushButton *usageBadge;
    QTimer *taskPulse, *chatRefresh;
    QElapsedTimer taskClock;
    QString pendingUser, liveAnswer, currentTaskState, currentTaskMessage;
    QStringList currentActivity, liveOrder;
    QHash<QString, QString> liveMessages, livePhases;
    QLabel *activity, *title, *saved, *conversationTitle;
    QPointer<QDialog> settingsDialog, onboardingDialog;
    QString activeTaskId;
    QComboBox *models, *selectionMode;
    QLineEdit *search, *treeFilter;
    QFormLayout *operationForm;
    QList<QDoubleSpinBox *> fields;
    QAction *undoAction, *redoAction;
    QJsonObject state, document, selected, operationSelection, taskAgent;
    QString workspace, currentOperation;
    bool polishVerified = false;
    bool settingsVerified = false, conversationsVerified = false, onboardingVerified = false, startupEmpty = false;
    int settingsSaves = 0;
    bool taskRunning = false, modelsLoading = false, refreshScheduled = false;
    bool busy = false, smoke = false, viewerFailed = false, loading = false;
};
