#pragma once
#include <QElapsedTimer>
#include <QTimer>
#include <QWidget>

class LoadingIndicator : public QWidget {
  public:
    explicit LoadingIndicator(QWidget *parent, bool floatingBadge = false);
    ~LoadingIndicator() override;
    // Returns a token; finish(token) ignores a token superseded by a later begin().
    int begin(const QString &message);
    void finish(int token = -1);
    QSize sizeHint() const override;
    // Paint the next spinner frame while the UI thread runs long synchronous work.
    // Repaints only these widgets and processes no events, so callers cannot re-enter.
    static void keepAlive();

  protected:
    void paintEvent(QPaintEvent *) override;
    void showEvent(QShowEvent *) override;
    void hideEvent(QHideEvent *) override;
    bool eventFilter(QObject *, QEvent *) override;

  private:
    void positionBadge();
    void reveal();
    QTimer delay, pulse;
    QElapsedTimer clock, requested, lastFrame;
    QString label;
    int generation = 0;
    bool floating, pending = false, animate = true;
};
