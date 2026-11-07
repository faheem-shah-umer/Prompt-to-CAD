#pragma once
#include <QJsonArray>
#include <QJsonObject>
#include <QScrollArea>
#include <QSet>
#include <QHash>
#include <QUrl>
class QVBoxLayout;
class QToolButton;
class ConversationView : public QScrollArea {
    Q_OBJECT
  public:
    explicit ConversationView(QWidget *parent = nullptr);
    void setMessages(const QJsonArray &messages, const QString &conversation);
    void scrollToLatest();
    void setDocumentContext(const QJsonObject &document);
    void setDraft(const QJsonObject &draft);
    QString plainText() const;
  Q_SIGNALS:
    void anchorClicked(const QUrl &url);
    void attachmentRequested(const QJsonObject &reference);
  protected:
    void resizeEvent(QResizeEvent *event) override;
    void wheelEvent(QWheelEvent *) override;
    void keyPressEvent(QKeyEvent *) override;
  private:
    void rebuild();
    bool updateWorkingMessages(const QJsonArray &messages);
    QJsonArray entries;
    QJsonArray designNotes;
    QJsonObject draft;
    QToolButton *latest;
    bool following = true, restoring = false;
    unsigned scrollGeneration = 0;
    QSet<QString> expanded;
    QHash<QString, qint64> copiedUntil;
    QString cachedTheme, context;
    QHash<QString, QString> componentNames;
    QSet<QString> workingTasks;
    QHash<int, QWidget *> messageTurns;
};
