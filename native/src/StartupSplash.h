#pragma once
#include <QDialog>
#include <QTimer>

class StartupSplash : public QDialog {
  public:
    StartupSplash();

  protected:
    void paintEvent(QPaintEvent *) override;

  private:
    QTimer pulse;
    int angle = 0;
};
