#pragma once
#include <QComboBox>
#include <QPlainTextEdit>
#include <QPointer>
class QFrame;
class ComposerEdit : public QPlainTextEdit {
  Q_OBJECT
public:
  using QPlainTextEdit::QPlainTextEdit;
Q_SIGNALS:
  void sendRequested();

protected:
  void keyPressEvent(QKeyEvent *) override;
  void inputMethodEvent(QInputMethodEvent *) override;

private:
  bool composing = false;
};
class ModelPicker : public QComboBox {
  Q_OBJECT
public:
  explicit ModelPicker(QWidget *parent = nullptr);
  QSize sizeHint() const override;
  QSize minimumSizeHint() const override;
  void showPopup() override;
  void hidePopup() override;
Q_SIGNALS:
  void refreshRequested();

protected:
  void paintEvent(QPaintEvent *) override;

private:
  QPointer<QFrame> popup;
};
void installWorkspaceInteraction();
