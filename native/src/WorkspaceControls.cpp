#include "WorkspaceControls.h"
#include <QAbstractButton>
#include <QApplication>
#include <QFrame>
#include <QInputMethodEvent>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMenu>
#include <QMouseEvent>
#include <QPushButton>
#include <QScreen>
#include <QTabBar>
#include <QTreeWidget>
#include <QVBoxLayout>
void ComposerEdit::inputMethodEvent(QInputMethodEvent *event) {
  composing = !event->preeditString().isEmpty();
  QPlainTextEdit::inputMethodEvent(event);
}
void ComposerEdit::keyPressEvent(QKeyEvent *event) {
  if ((event->key() == Qt::Key_Return || event->key() == Qt::Key_Enter) &&
      !(event->modifiers() & Qt::ShiftModifier) && !composing) {
    if (!event->isAutoRepeat())
      Q_EMIT sendRequested();
    event->accept();
    return;
  }
  QPlainTextEdit::keyPressEvent(event);
}
void ModelPicker::hidePopup() {
  if (popup)
    popup->close();
  QComboBox::hidePopup();
}
void ModelPicker::showPopup() {
  if (popup) {
    popup->raise();
    return;
  }
  auto *panel = new QFrame(this, Qt::Popup);
  popup = panel;
  panel->setObjectName("modelPopover");
  panel->setAttribute(Qt::WA_DeleteOnClose);
  auto *layout = new QVBoxLayout(panel);
  layout->setContentsMargins(12, 12, 12, 12);
  layout->setSpacing(8);
  auto *search = new QLineEdit;
  search->setPlaceholderText("Search models");
  search->setObjectName("modelSearch");
  layout->addWidget(search);
  auto *list = new QListWidget;
  list->setObjectName("modelOptions");
  for (int index = 0; index < count(); ++index) {
    auto *item = new QListWidgetItem(itemText(index), list);
    item->setData(Qt::UserRole, index);
    item->setToolTip(itemData(index, Qt::ToolTipRole).toString());
    if (index == currentIndex())
      list->setCurrentItem(item);
  }
  list->setMinimumHeight(100);
  list->setMaximumHeight(260);
  layout->addWidget(list);
  auto *status =
      new QLabel(count() ? "Model access is checked when a request runs."
                 : property("catalogState").toString().isEmpty()
                     ? "Connect your account, then refresh models."
                     : property("catalogState").toString());
  status->setObjectName("muted");
  status->setWordWrap(true);
  layout->addWidget(status);
  auto *refresh = new QPushButton("Refresh models");
  layout->addWidget(refresh);
  connect(refresh, &QPushButton::clicked, panel, [this, panel] {
    panel->close();
    Q_EMIT refreshRequested();
  });
  connect(search, &QLineEdit::textChanged, panel, [list](const QString &text) {
    QListWidgetItem *first = nullptr;
    for (int i = 0; i < list->count(); ++i) {
      auto *item = list->item(i);
      item->setHidden(!item->text().contains(text, Qt::CaseInsensitive));
      if (!item->isHidden() && !first)
        first = item;
    }
    if (first)
      list->setCurrentItem(first);
  });
  auto choose = [this, panel](QListWidgetItem *item) {
    if (item && !item->isHidden()) {
      setCurrentIndex(item->data(Qt::UserRole).toInt());
      panel->close();
    }
  };
  connect(list, &QListWidget::itemClicked, panel, choose);
  connect(list, &QListWidget::itemActivated, panel, choose);
  connect(search, &QLineEdit::returnPressed, panel,
          [choose, list] { choose(list->currentItem()); });
  panel->setFixedWidth(qBound(260, width() + 80, 380));
  panel->adjustSize();
  auto position = mapToGlobal(QPoint(0, 0));
  const auto screenRect = screen()->availableGeometry();
  position.setX(qBound(screenRect.left(), position.x(),
                       screenRect.right() - panel->width()));
  position.setY(qMax(screenRect.top(), position.y() - panel->height() - 6));
  panel->move(position);
  panel->show();
  search->setFocus();
}
namespace {
class Interaction : public QObject {
public:
  using QObject::QObject;
  bool eventFilter(QObject *object, QEvent *event) override {
    auto *widget = qobject_cast<QWidget *>(object);
    if (!widget)
      return false;
    if (event->type() == QEvent::Polish ||
        event->type() == QEvent::EnabledChange) {
      if (qobject_cast<QAbstractButton *>(widget) ||
          qobject_cast<QComboBox *>(widget))
        widget->setCursor(widget->isEnabled() ? Qt::PointingHandCursor
                                              : Qt::ArrowCursor);
      if (qobject_cast<QTabBar *>(widget) ||
          qobject_cast<QAbstractItemView *>(widget))
        widget->setMouseTracking(true);
    }
    if (event->type() == QEvent::MouseMove) {
      auto point = static_cast<QMouseEvent *>(event)->position().toPoint();
      if (auto *tabs = qobject_cast<QTabBar *>(widget)) {
        int i = tabs->tabAt(point);
        tabs->setCursor(i >= 0 && tabs->isTabEnabled(i) ? Qt::PointingHandCursor
                                                        : Qt::ArrowCursor);
      }
      if (auto *menu = qobject_cast<QMenu *>(widget)) {
        auto *action = menu->actionAt(point);
        menu->setCursor(action && action->isEnabled() && !action->isSeparator()
                            ? Qt::PointingHandCursor
                            : Qt::ArrowCursor);
      }
      if (auto *view =
              qobject_cast<QAbstractItemView *>(widget->parentWidget());
          view && widget == view->viewport()) {
        auto index = view->indexAt(point);
        widget->setCursor(index.isValid() && (index.flags() & Qt::ItemIsEnabled)
                              ? Qt::PointingHandCursor
                              : Qt::ArrowCursor);
      }
    }
    return false;
  }
};
} // namespace
void installWorkspaceInteraction() {
  qApp->installEventFilter(new Interaction(qApp));
}
