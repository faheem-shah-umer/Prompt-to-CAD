#pragma once
#include <QMainWindow>
#include <QJsonObject>
#include <QJsonArray>
#include <QList>
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

class WorkspaceWindow : public QMainWindow {
    Q_OBJECT
  public:
    WorkspaceWindow(const QString &source, const QString &python, const QString &openPath,
                    bool smokeTest = false);
    ~WorkspaceWindow() override;

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
    void attach();
    void select(const QJsonObject &);
    void operation(const QString &);
    void applyOperation();
    void showError(const QString &);
    void smokeCheck();
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
    QLabel *activity, *title, *saved, *attachmentLabel;
    QComboBox *models, *selectionMode;
    QCheckBox *imageBilling;
    QLineEdit *search, *treeFilter;
    QFormLayout *operationForm;
    QList<QDoubleSpinBox *> fields;
    QAction *undoAction, *redoAction;
    QJsonObject state, document, selected, operationSelection;
    QJsonArray attachments;
    QString workspace, currentOperation;
    bool busy = false, smoke = false, viewerFailed = false, loading = false;
};
