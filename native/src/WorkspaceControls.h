#pragma once
#include <QComboBox>
#include <QPlainTextEdit>
#include <QPointer>
#include <QImage>
class QFrame;
class QMimeData;
class ComposerEdit : public QPlainTextEdit {
  Q_OBJECT
public:
  using QPlainTextEdit::QPlainTextEdit;
Q_SIGNALS:
  void sendRequested();
  void imageFilesAdded(const QStringList &paths);
  void imageAdded(const QImage &image);

protected:
  void keyPressEvent(QKeyEvent *) override;
  void inputMethodEvent(QInputMethodEvent *) override;
  void insertFromMimeData(const QMimeData *) override;
  void dragEnterEvent(QDragEnterEvent *) override;
  void dragMoveEvent(QDragMoveEvent *) override;
  void dropEvent(QDropEvent *) override;

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
  void showModelPopup();
  void hidePopup() override;
Q_SIGNALS:
  void refreshRequested();
  void configurationRequested();

protected:
  void paintEvent(QPaintEvent *) override;

private:
  QPointer<QFrame> popup;
};
void installWorkspaceInteraction();
