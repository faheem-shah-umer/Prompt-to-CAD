#pragma once
#include <QComboBox>
#include <QFrame>
#include <QPlainTextEdit>
#include <QPointer>
#include <QImage>
class QKeyEvent;
class QWheelEvent;

class WorkspacePopover : public QFrame {
  Q_OBJECT
public:
  WorkspacePopover(QWidget *anchor, const QString &name);
  void showAnchored(QWidget *initialFocus = nullptr, bool beside = false);
  void dismiss(bool restoreFocus = true);
protected:
  void keyPressEvent(QKeyEvent *) override;
private:
  QPointer<QWidget> anchor;
};
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
  void keyPressEvent(QKeyEvent *) override;
  bool eventFilter(QObject *, QEvent *) override;
  void wheelEvent(QWheelEvent *) override;

private:
  QPointer<QFrame> popup;
};
void installWorkspaceInteraction();

class QSplitter;
QSplitter *workspaceSplitter(Qt::Orientation, QWidget *parent = nullptr);

class QTreeWidget;
QTreeWidget *workspaceModelTree(QWidget *parent = nullptr);

class QLabel;
QLabel *workspaceTitle(const QString &text, QWidget *parent = nullptr);
