#pragma once
#include <QJsonArray>
#include <QScrollArea>
#include <QSet>
#include <QUrl>
class QVBoxLayout;
class ConversationView : public QScrollArea {
    Q_OBJECT
  public:
    explicit ConversationView(QWidget *parent = nullptr);
    void setMessages(const QJsonArray &messages, const QString &conversation);
    void notice(const QString &text);
    QString plainText() const;
  Q_SIGNALS:
    void anchorClicked(const QUrl &url);
  protected:
    void resizeEvent(QResizeEvent *event) override;
  private:
    void rebuild();
    QJsonArray entries, notices;
    QSet<QString> expanded;
    QString cachedTheme, context;
};
