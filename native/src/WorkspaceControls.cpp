#include "WorkspaceControls.h"
#include "WorkspaceTheme.h"
#include "WorkspaceIcons.h"
#include <QAbstractButton>
#include <QApplication>
#include <QDragEnterEvent>
#include <QGuiApplication>
#include <QTimer>
#include <QDropEvent>
#include <QImage>
#include <QMimeData>
#include <QUrl>
#include <QFrame>
#include <QFocusEvent>
#include <QInputMethodEvent>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMenu>
#include <QMouseEvent>
#include <QWheelEvent>
#include <QPushButton>
#include <QScreen>
#include <QSplitter>
#include <QSplitterHandle>
#include <QPainter>
#include <QPolygon>
#include <QStyleOptionComboBox>
#include <QStylePainter>
#include <QStyledItemDelegate>
#include <QTabBar>
#include <QTreeWidget>
#include <QVBoxLayout>
namespace {
bool imageInput(const QMimeData *data) {
  if (data->hasImage()) return true;
  if (!data->hasUrls() || data->urls().isEmpty()) return false;
  for (const auto& url : data->urls()) {
    if (!url.isLocalFile()) return false;
    auto path = url.toLocalFile().toLower();
    if (!path.endsWith(".png") && !path.endsWith(".jpg") && !path.endsWith(".jpeg") && !path.endsWith(".webp")) return false;
  }
  return true;
}
}
void ComposerEdit::insertFromMimeData(const QMimeData *data) {
  if (data->hasImage()) { Q_EMIT imageAdded(qvariant_cast<QImage>(data->imageData())); return; }
  if (imageInput(data)) {
    QStringList paths; for (const auto& url : data->urls()) paths << url.toLocalFile();
    Q_EMIT imageFilesAdded(paths); return;
  }
  QPlainTextEdit::insertFromMimeData(data);
}
void ComposerEdit::dragEnterEvent(QDragEnterEvent *event) {
  if (imageInput(event->mimeData())) event->acceptProposedAction();
  else QPlainTextEdit::dragEnterEvent(event);
}
void ComposerEdit::dragMoveEvent(QDragMoveEvent *event) {
  if (imageInput(event->mimeData())) event->acceptProposedAction();
  else QPlainTextEdit::dragMoveEvent(event);
}
void ComposerEdit::dropEvent(QDropEvent *event) {
  if (imageInput(event->mimeData())) { insertFromMimeData(event->mimeData()); event->acceptProposedAction(); }
  else QPlainTextEdit::dropEvent(event);
}
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
WorkspacePopover::WorkspacePopover(QWidget *trigger, const QString &name)
    : QFrame(trigger->window(), Qt::Popup), anchor(trigger) {
  setObjectName(name);
  setAttribute(Qt::WA_DeleteOnClose);
  setFocusPolicy(Qt::StrongFocus);
  setAccessibleName(name == "modelPopover" ? "Available models"
                     : name == "effortPopover" ? "Model and reasoning effort"
                     : name == "usagePopover" ? "Reported usage" : "Account details");
}
void WorkspacePopover::showAnchored(QWidget *initialFocus, bool beside) {
  if (!anchor) return;
  ensurePolished();
  auto *display = anchor->screen();
  if (!display) display = QGuiApplication::primaryScreen();
  const auto bounds = display->availableGeometry().adjusted(
      WorkspaceMetrics::PopupGap, WorkspaceMetrics::PopupGap,
      -WorkspaceMetrics::PopupGap, -WorkspaceMetrics::PopupGap);
  setMinimumSize(qMin(minimumWidth(), bounds.width()),
                 qMin(minimumHeight(), bounds.height()));
  setMaximumSize(bounds.size());
  adjustSize();
  resize(qMin(width(), bounds.width()), qMin(height(), bounds.height()));
  const QRect trigger(anchor->mapToGlobal(QPoint()), anchor->size());
  int x = beside ? trigger.right() + WorkspaceMetrics::PopupGap : trigger.left();
  int y = beside ? trigger.bottom() - height()
                 : trigger.top() - height() - WorkspaceMetrics::PopupGap;
  if (!beside && y < bounds.top() &&
      trigger.bottom() + WorkspaceMetrics::PopupGap + height() <= bounds.bottom())
    y = trigger.bottom() + WorkspaceMetrics::PopupGap;
  x = qBound(bounds.left(), x, bounds.right() - width() + 1);
  y = qBound(bounds.top(), y, bounds.bottom() - height() + 1);
  move(x, y);
  show();
  if (initialFocus && initialFocus->isEnabled())
    initialFocus->setFocus(Qt::PopupFocusReason);
  else
    setFocus(Qt::PopupFocusReason);
}
void WorkspacePopover::dismiss(bool restoreFocus) {
  const QPointer<QWidget> trigger = anchor;
  close();
  if (restoreFocus && trigger)
    QTimer::singleShot(0, trigger, [trigger] {
      if (trigger && trigger->isVisible() && trigger->isEnabled() &&
          trigger->window()->isActiveWindow() && !QApplication::activePopupWidget())
        trigger->setFocus(Qt::PopupFocusReason);
    });
}
void WorkspacePopover::keyPressEvent(QKeyEvent *event) {
  if (event->key() == Qt::Key_Escape) {
    event->accept();
    dismiss();
    return;
  }
  QFrame::keyPressEvent(event);
}

ModelPicker::ModelPicker(QWidget *parent) : QComboBox(parent) {
  setAccessibleName("Choose model");
  setToolTip("Choose model");
  connect(this, &QComboBox::currentTextChanged, this, [this](const QString& name) {
    if (!property("combinedEffort").toBool()) {
      setToolTip(name);
      setAccessibleName(name.isEmpty() ? "Choose model" : "Model: " + name);
    }
    updateGeometry();
    update();
  });
}
QSize ModelPicker::sizeHint() const {
  const auto label = currentText().isEmpty() ? placeholderText() : currentText();
  const auto effort = property("effortCaption").toString();
  const int extra = effort.isEmpty() ? 0 : fontMetrics().horizontalAdvance(effort) + 8;
  return {qMin(240, fontMetrics().horizontalAdvance(label) + extra + 38), qMax(32, fontMetrics().height() + 12)};
}
QSize ModelPicker::minimumSizeHint() const { return {38, sizeHint().height()}; }
void ModelPicker::paintEvent(QPaintEvent *) {
  QStyleOptionComboBox option;
  initStyleOption(&option);
  option.currentText.clear();
  QStylePainter painter(this);
  painter.drawComplexControl(QStyle::CC_ComboBox, option);
  auto area = rect().adjusted(8, 0, -26, 0);
  const auto chevronColor = isEnabled() ? workspaceColors().secondary : workspaceColors().disabled;
  painter.setPen(QPen(chevronColor, 1.5));
  const int right = width() - 10, middle = height() / 2;
  painter.drawPolyline(QPolygon{QPoint(right - 8, middle - 2), QPoint(right - 4, middle + 2), QPoint(right, middle - 2)});
  const auto label = currentText().isEmpty() ? placeholderText() : currentText();
  const auto effort = property("effortCaption").toString();
  const auto suffixWidth = effort.isEmpty() ? 0 : qMin(fontMetrics().horizontalAdvance(effort), area.width() / 2);
  auto modelArea = area;
  if (suffixWidth) modelArea.setRight(area.right() - suffixWidth - 8);
  painter.setPen(palette().color(isEnabled() ? QPalette::Active : QPalette::Disabled, QPalette::ButtonText));
  painter.drawText(modelArea, Qt::AlignVCenter | Qt::AlignLeft, fontMetrics().elidedText(label, Qt::ElideRight, modelArea.width()));
  if (suffixWidth) {
    painter.setPen(palette().color(isEnabled() ? QPalette::Active : QPalette::Disabled, QPalette::PlaceholderText));
    painter.drawText(QRect(area.right() - suffixWidth + 1, area.top(), suffixWidth, area.height()),
                     Qt::AlignVCenter | Qt::AlignLeft, fontMetrics().elidedText(effort, Qt::ElideRight, suffixWidth));
  }
}
void ModelPicker::hidePopup() {
  if (popup)
    popup->close();
  QComboBox::hidePopup();
}
void ModelPicker::showPopup() {
  if (!isEnabled()) return;
  if (property("combinedEffort").toBool()) {
    Q_EMIT configurationRequested();
    return;
  }
  showModelPopup();
}
void ModelPicker::showModelPopup() {
  if (!isEnabled()) return;
  if (popup && popup->isVisible()) {
    popup->raise();
    if (auto *search = popup->findChild<QLineEdit *>("modelSearch")) search->setFocus();
    return;
  }
  auto *panel = new WorkspacePopover(this, "modelPopover");
  popup = panel;
  panel->setObjectName("modelPopover");
  panel->setAttribute(Qt::WA_DeleteOnClose);
  auto *layout = new QVBoxLayout(panel);
  layout->setContentsMargins(12, 12, 12, 12);
  layout->setSpacing(8);
  auto *search = new QLineEdit;
  search->setPlaceholderText("Search models");
  search->setObjectName("modelSearch");
  search->setAccessibleName("Search available models");
  search->installEventFilter(this);
  layout->addWidget(search);
  auto *list = new QListWidget;
  list->setObjectName("modelOptions");
  list->setAccessibleName("Available models");
  list->installEventFilter(this);
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
  auto *empty = new QLabel(count() ? "No models match your search." : "No models available.", panel);
  empty->setObjectName("modelSearchEmpty");
  empty->setWordWrap(true);
  empty->setVisible(count() == 0);
  layout->addWidget(empty);
  auto *status =
      new QLabel(count() ? "Model access is checked when a request runs."
                 : property("catalogState").toString().isEmpty()
                     ? "Connect your account, then refresh models."
                     : property("catalogState").toString());
  status->setObjectName("muted");
  status->setWordWrap(true);
  layout->addWidget(status);
  auto *refresh = new QPushButton("Refresh models");
  refresh->setObjectName("refreshModelCatalogue");
  refresh->setEnabled(property("refreshAvailable").toBool());
  refresh->setToolTip(refresh->isEnabled() ? "Refresh the reported model catalogue"
                      : "Connect a provider and wait for the current task or model discovery to finish.");
  layout->addWidget(refresh);
  connect(refresh, &QPushButton::clicked, panel, [this, panel] {
    panel->dismiss();
    Q_EMIT refreshRequested();
  });
  connect(search, &QLineEdit::textChanged, panel, [list, empty](const QString &text) {
    QListWidgetItem *first = nullptr;
    for (int i = 0; i < list->count(); ++i) {
      auto *item = list->item(i);
      item->setHidden(!item->text().contains(text, Qt::CaseInsensitive));
      if (!item->isHidden() && !first)
        first = item;
    }
    list->setCurrentItem(first);
    empty->setVisible(!first);
  });
  auto choose = [this, panel](QListWidgetItem *item) {
    if (item && !item->isHidden()) {
      setCurrentIndex(item->data(Qt::UserRole).toInt());
      panel->dismiss();
    }
  };
  connect(list, &QListWidget::itemClicked, panel, choose);
  connect(list, &QListWidget::itemActivated, panel, choose);
  connect(search, &QLineEdit::returnPressed, panel,
          [choose, list] { choose(list->currentItem()); });
  panel->setFixedWidth(qBound(260, width() + 80, 380));
  panel->adjustSize();
  panel->showAnchored(search);
}
void ModelPicker::wheelEvent(QWheelEvent *event) { event->ignore(); }
void ModelPicker::keyPressEvent(QKeyEvent *event) {
  if (event->key() == Qt::Key_Return || event->key() == Qt::Key_Enter ||
      event->key() == Qt::Key_Space || event->key() == Qt::Key_Down ||
      event->key() == Qt::Key_Up || event->key() == Qt::Key_F4) {
    if (!event->isAutoRepeat()) showPopup();
    event->accept();
    return;
  }
  // Choosing a model belongs to the explicit catalogue, not hidden combo-box type-ahead.
  if (event->key() == Qt::Key_Tab || event->key() == Qt::Key_Backtab ||
      event->key() == Qt::Key_Escape)
    QComboBox::keyPressEvent(event);
  else
    event->ignore();
}
bool ModelPicker::eventFilter(QObject *object, QEvent *event) {
  if (event->type() == QEvent::KeyPress && popup &&
      object->objectName() == "modelSearch") {
    const auto key = static_cast<QKeyEvent *>(event)->key();
    if (key == Qt::Key_Down || key == Qt::Key_Up) {
      auto *list = popup->findChild<QListWidget *>("modelOptions");
      for (int i = key == Qt::Key_Up ? list->count() - 1 : 0;
           i >= 0 && i < list->count(); i += key == Qt::Key_Up ? -1 : 1) {
        if (!list->item(i)->isHidden()) {
          list->setCurrentRow(i);
          list->setFocus(Qt::TabFocusReason);
          return true;
        }
      }
      return true;
    }
  }
  return QComboBox::eventFilter(object, event);
}

namespace {
class Interaction : public QObject {
public:
  using QObject::QObject;
  void focusState(QWidget *widget, bool visible) {
    if (!widget || widget->property("keyboardFocus").toBool() == visible) return;
    widget->setProperty("keyboardFocus", visible);
    widget->style()->unpolish(widget);
    widget->style()->polish(widget);
    widget->update();
  }
  bool eventFilter(QObject *object, QEvent *event) override {
    auto *widget = qobject_cast<QWidget *>(object);
    if (!widget)
      return false;
    if (event->type() == QEvent::KeyPress) {
      keyboardNavigation = true;
      focusState(QApplication::focusWidget(), true);
    } else if (event->type() == QEvent::MouseButtonPress) {
      keyboardNavigation = false;
      focusState(QApplication::focusWidget(), false);
      focusState(widget, false);
    } else if (event->type() == QEvent::FocusIn) {
      const auto reason = static_cast<QFocusEvent *>(event)->reason();
      focusState(widget, keyboardNavigation || reason == Qt::TabFocusReason ||
                 reason == Qt::BacktabFocusReason || reason == Qt::ShortcutFocusReason);
    }
    if (event->type() == QEvent::Polish ||
        event->type() == QEvent::EnabledChange) {
      if (qobject_cast<QAbstractButton *>(widget) ||
          qobject_cast<QComboBox *>(widget))
        widget->setCursor(widget->isEnabled() ? Qt::PointingHandCursor
                                              : Qt::ArrowCursor);
      if (auto *button = qobject_cast<QAbstractButton *>(widget)) {
        button->setFocusPolicy(Qt::StrongFocus);
        if (button->accessibleName().isEmpty() && !button->text().isEmpty()) {
          auto name = button->text(); name.remove('&');
          button->setAccessibleName(name);
        }
      }
      if (qobject_cast<QMenu *>(widget)) widget->setMouseTracking(true);
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
        widget->setCursor(view->isEnabled() && index.isValid() && (index.flags() & Qt::ItemIsEnabled)
                              ? Qt::PointingHandCursor
                              : Qt::ArrowCursor);
      }
    }
    return false;
  }
private:
  bool keyboardNavigation = false;
};
} // namespace
void installWorkspaceInteraction() {
  // Frequent controls and keyboard actions must not wait for platform fade/slide effects.
  for (auto effect : {Qt::UI_AnimateMenu, Qt::UI_FadeMenu, Qt::UI_AnimateCombo,
                      Qt::UI_AnimateTooltip, Qt::UI_FadeTooltip})
    QApplication::setEffectEnabled(effect, false);
  qApp->installEventFilter(new Interaction(qApp));
}

namespace {
class WorkspaceHandle : public QSplitterHandle {
public:
  WorkspaceHandle(Qt::Orientation orientation, QSplitter *splitter)
      : QSplitterHandle(orientation, splitter) {
    setFocusPolicy(Qt::StrongFocus);
    setAccessibleName("Resize workspace panels");
    setToolTip("Drag to resize · arrow keys resize when focused");
  }
protected:
  void keyPressEvent(QKeyEvent *event) override {
    const bool horizontal = orientation() == Qt::Horizontal;
    const bool backward = event->key() == (horizontal ? Qt::Key_Left : Qt::Key_Up);
    const bool forward = event->key() == (horizontal ? Qt::Key_Right : Qt::Key_Down);
    if (backward || forward) {
      moveSplitter((horizontal ? pos().x() : pos().y()) + (forward ? 16 : -16));
      event->accept();
      return;
    }
    QSplitterHandle::keyPressEvent(event);
  }
  void paintEvent(QPaintEvent *event) override {
    QSplitterHandle::paintEvent(event);
    QPainter painter(this);
    painter.setPen(QPen(hasFocus() ? workspaceColors().focus : workspaceColors().border,
                        hasFocus() ? 2 : 1));
    if (orientation() == Qt::Horizontal)
      painter.drawLine(width() / 2, 0, width() / 2, height());
    else
      painter.drawLine(0, height() / 2, width(), height() / 2);
  }
};
class WorkspaceSplitter : public QSplitter {
public:
  WorkspaceSplitter(Qt::Orientation orientation, QWidget *parent) : QSplitter(orientation, parent) {
    setHandleWidth(8);
    setChildrenCollapsible(false);
  }
protected:
  QSplitterHandle *createHandle() override { return new WorkspaceHandle(orientation(), this); }
};
}
QSplitter *workspaceSplitter(Qt::Orientation orientation, QWidget *parent) {
  return new WorkspaceSplitter(orientation, parent);
}

namespace {
class VisibilityDelegate : public QStyledItemDelegate {
public:
  using QStyledItemDelegate::QStyledItemDelegate;
  void paint(QPainter *painter, const QStyleOptionViewItem &option, const QModelIndex &index) const override {
    if (index.column() != 1 || !index.data(Qt::CheckStateRole).isValid()) {
      QStyledItemDelegate::paint(painter, option, index);
      return;
    }
    auto cell = option;
    initStyleOption(&cell, index);
    cell.features &= ~QStyleOptionViewItem::HasCheckIndicator;
    cell.text.clear();
    const auto *style = cell.widget ? cell.widget->style() : QApplication::style();
    style->drawControl(QStyle::CE_ItemViewItem, &cell, painter, cell.widget);
    const bool visible = index.data(Qt::CheckStateRole).toInt() == Qt::Checked;
    const auto icon = workspaceIcon(visible ? "eye" : "eye-off");
    icon.paint(painter, QRect(option.rect.center() - QPoint(8, 8), QSize(16, 16)));
  }
};
class ModelTree : public QTreeWidget {
public:
  explicit ModelTree(QWidget *parent) : QTreeWidget(parent) {
    setItemDelegateForColumn(1, new VisibilityDelegate(this));
  }
protected:
  void mousePressEvent(QMouseEvent *event) override {
    auto *item = itemAt(event->position().toPoint());
    if (event->button() == Qt::LeftButton && item && columnAt(event->position().x()) == 1 && !item->data(0, Qt::UserRole).toString().isEmpty()) {
      item->setCheckState(1, item->checkState(1) == Qt::Checked ? Qt::Unchecked : Qt::Checked);
      event->accept(); return;
    }
    QTreeWidget::mousePressEvent(event);
  }
  void mouseReleaseEvent(QMouseEvent *event) override {
    if (columnAt(event->position().x()) == 1) { event->accept(); return; }
    QTreeWidget::mouseReleaseEvent(event);
  }
};
}
QTreeWidget *workspaceModelTree(QWidget *parent) { return new ModelTree(parent); }

namespace {
class ElidedTitle : public QLabel {
public:
  using QLabel::QLabel;
protected:
  void paintEvent(QPaintEvent *) override {
    QPainter painter(this);
    painter.setFont(font());
    painter.setPen(palette().color(QPalette::WindowText));
    painter.drawText(contentsRect(), alignment(),
                     fontMetrics().elidedText(text(), Qt::ElideRight, contentsRect().width()));
  }
};
}
QLabel *workspaceTitle(const QString &text, QWidget *parent) {
  auto *label = new ElidedTitle(text, parent);
  label->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
  label->setMinimumHeight(label->fontMetrics().lineSpacing());
  return label;
}

namespace {
class AccountButton : public QPushButton {
public:
  explicit AccountButton(QWidget *parent) : QPushButton(parent) {
    setFixedSize(40, 40);
    setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Fixed);
  }
protected:
  void paintEvent(QPaintEvent *) override {
    const auto colors = workspaceColors();
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);
    const qreal diameter = qMax(0, qMin(width(), height()) - 8);
    const QRectF circle((width() - diameter) / 2, (height() - diameter) / 2, diameter, diameter);
    painter.setPen(Qt::NoPen);
    painter.setBrush(!isEnabled() ? colors.selected : isDown() ? colors.actionPressed : underMouse() ? colors.actionHover : colors.action);
    painter.drawEllipse(circle);
    if (hasFocus() && property("keyboardFocus").toBool()) {
      painter.setPen(QPen(colors.focus, 1.5));
      painter.setBrush(Qt::NoBrush);
      painter.drawEllipse(circle.adjusted(-2, -2, 2, 2));
    }
    if (text().isEmpty()) workspaceIcon("user", true).paint(&painter, QRect(rect().center() - QPoint(8, 8), QSize(16, 16)), Qt::AlignCenter,
                                       isEnabled() ? QIcon::Normal : QIcon::Disabled);
    else {
      painter.setPen(isEnabled() ? colors.onAction : colors.disabled);
      auto initialsFont = font();
      initialsFont.setWeight(QFont::DemiBold);
      painter.setFont(initialsFont);
      painter.drawText(rect(), Qt::AlignCenter, text());
    }
  }
};
}
QPushButton *workspaceAccountButton(QWidget *parent) { return new AccountButton(parent); }
