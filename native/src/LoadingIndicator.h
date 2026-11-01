#pragma once
#include <QElapsedTimer>
#include <QTimer>
#include <QWidget>

class LoadingIndicator : public QWidget {
  public:
    explicit LoadingIndicator(QWidget *parent, bool floatingBadge = false);
    void begin(const QString &message);
    void finish();
    QSize sizeHint() const override;

  protected:
    void paintEvent(QPaintEvent *) override;
    void showEvent(QShowEvent *) override;
    void hideEvent(QHideEvent *) override;
    bool eventFilter(QObject *, QEvent *) override;

  private:
    void positionBadge();
    QTimer delay, pulse;
    QElapsedTimer clock;
    QString label;
    bool floating, pending = false, animate = true;
};
