#include "WorkspaceIcons.h"
#include "WorkspaceWindow.h"
#include <QApplication>
#include <QItemSelectionModel>
#include <QDesktopServices>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QFormLayout>
#include <QFrame>
#include <QInputDialog>
#include <QLabel>
#include <QLineEdit>
#include <QLocale>
#include <QMenuBar>
#include <QMessageBox>
#include <QPushButton>
#include <QScreen>
#include <QScrollBar>
#include <QSettings>
#include <QSignalBlocker>
#include <QStyle>
#include <QTabWidget>
#include <QTimer>
#include <QTreeWidget>
#include <QTreeWidgetItemIterator>
#include <QVBoxLayout>
#include "CadView.h"
#include <algorithm>
namespace {
QLabel *text(const QString &value) {
  auto *label = new QLabel(value);
  label->setWordWrap(true);
  label->setTextFormat(Qt::PlainText);
  return label;
}
QFrame *popover(WorkspaceWindow *window, QWidget *anchor, const QString &name) {
  if (auto *existing = window->findChild<QFrame *>(name)) {
    existing->close();
    return nullptr;
  }
  auto *frame = new QFrame(window, Qt::Popup);
  frame->setObjectName(name);
  frame->setAttribute(Qt::WA_DeleteOnClose);
  frame->setFixedWidth(330);
  auto point = anchor->mapToGlobal(QPoint(anchor->width() + 8, 0));
  auto bounds = window->screen()->availableGeometry();
  point.setX(qMin(point.x(), bounds.right() - frame->width() - 12));
  point.setY(qMax(bounds.top() + 12, point.y() - 200));
  frame->move(point);
  return frame;
}
} // namespace
void WorkspaceWindow::refreshProjectTree() {
  const QSignalBlocker blocker(projects);
  QHash<QString, bool> expanded;
  QSet<QString> selectedRows;
  QString currentRow;
  auto rowKey = [](QTreeWidgetItem *item) {
    return item->data(0, Qt::UserRole).toString() + "/" +
           item->data(0, Qt::UserRole + 1).toString();
  };
  for (int i = 0; i < projects->topLevelItemCount(); ++i) {
    auto *item = projects->topLevelItem(i);
    expanded.insert(item->data(0, Qt::UserRole).toString(), item->isExpanded());
  }
  for (auto *item : projects->selectedItems()) selectedRows.insert(rowKey(item));
  if (projects->currentItem()) currentRow = rowKey(projects->currentItem());
  const int scroll = projects->verticalScrollBar()->value();
  const auto active = state.value("project").toObject().value("project_id").toString();
  const auto chatId = state.value("conversation").toObject().value("conversation_id").toString();
  const bool opened = projects->property("activeProject").toString() != active ||
                      projects->property("activeConversation").toString() != chatId;
  if (opened && !active.isEmpty()) {
    currentRow = active + "/" + chatId;
    selectedRows = {currentRow};
  }
  projects->setProperty("activeProject", active);
  projects->setProperty("activeConversation", chatId);
  QList<QJsonObject> entries;
  for (auto value : state.value("catalog").toObject().value("projects").toArray()) {
    auto project = value.toObject();
    if (!project.value("archived").toBool() && !project.value("trashed").toBool()) entries << project;
  }
  const auto order = QSettings().value("v2/projectSort", "changed").toString();
  std::sort(entries.begin(), entries.end(), [order](const QJsonObject& a, const QJsonObject& b) {
    const QString field = order == "created" ? "created_at" : order == "opened" ? "last_opened_at" : "content_modified_at";
    if (order != "name" && order != "name_desc") {
      const double first = a.value(field).toDouble(), second = b.value(field).toDouble();
      if (first != second) return first > second;
    }
    const int names = QString::compare(a.value("name").toString(), b.value("name").toString(), Qt::CaseInsensitive);
    if (names) return order == "name_desc" ? names > 0 : names < 0;
    return a.value("project_id").toString() < b.value("project_id").toString();
  });
  projects->clear();
  QTreeWidgetItem *current = nullptr;
  auto restoreRow = [&](QTreeWidgetItem *item) {
    const auto key = rowKey(item);
    item->setSelected(selectedRows.contains(key));
    if (key == currentRow) current = item;
  };
  for (const auto& project : entries) {
    const auto id = project.value("project_id").toString();
    auto *item = new QTreeWidgetItem(projects, {project.value("name").toString()});
    item->setData(0, Qt::UserRole, id);
    restoreRow(item);
    for (auto value : project.value("conversation_summaries").toArray()) {
      auto chat = value.toObject();
      if (chat.value("archived").toBool() || chat.value("trashed").toBool()) continue;
      auto *child = new QTreeWidgetItem(item, {chat.value("title").toString()});
      child->setData(0, Qt::UserRole, id);
      child->setData(0, Qt::UserRole + 1, chat.value("conversation_id"));
      restoreRow(child);
    }
    item->setExpanded(opened && id == active ? true : expanded.value(id, id == active));
  }
  if (current) projects->setCurrentItem(current, 0, QItemSelectionModel::NoUpdate);
  filterProjects();
  if (opened && current) projects->scrollToItem(current);
  else projects->verticalScrollBar()->setValue(scroll);
}

void WorkspaceWindow::filterProjects() {
  const auto filter = search->text();
  for (int i = 0; i < projects->topLevelItemCount(); ++i) {
    auto *item = projects->topLevelItem(i);
    const bool parentMatch = item->text(0).contains(filter, Qt::CaseInsensitive);
    bool found = parentMatch;
    for (int j = 0; j < item->childCount(); ++j) {
      const bool match = parentMatch || item->child(j)->text(0).contains(filter, Qt::CaseInsensitive);
      item->child(j)->setHidden(!match);
      found |= match;
    }
    item->setHidden(!found);
  }
}

void WorkspaceWindow::filterModels() {
  const auto filter = treeFilter->text();
  std::function<bool(QTreeWidgetItem*)> include = [&](QTreeWidgetItem *item) {
    bool found = item->text(0).contains(filter, Qt::CaseInsensitive);
    for (int i=0;i<item->childCount();++i) found = include(item->child(i)) || found;
    item->setHidden(!found);
    if (!filter.isEmpty() && found) item->setExpanded(true);
    return found;
  };
  for (int i=0;i<modelTree->topLevelItemCount();++i) include(modelTree->topLevelItem(i));
}

void WorkspaceWindow::syncModelVisibility() {
  const QSignalBlocker blocker(modelTree);
  for (QTreeWidgetItemIterator it(modelTree); *it; ++it) {
    const auto id = (*it)->data(0, Qt::UserRole).toString();
    if (!id.isEmpty()) (*it)->setCheckState(0, viewer->isInstanceVisible(id) ? Qt::Checked : Qt::Unchecked);
  }
  const bool any = !document.value("components").toArray().isEmpty();
  for (const auto& name : {"showAllModels", "hideAllModels", "selectAllModels"})
    if (auto *control = findChild<QPushButton*>(name)) control->setEnabled(any);
  if (auto *control = findChild<QPushButton*>("clearModelSelection")) control->setEnabled(!selected.isEmpty());
}

void WorkspaceWindow::showAccountDetails() {
  auto *panel = popover(this, accountBadge, "accountPopover");
  if (!panel)
    return;
  auto *layout = new QVBoxLayout(panel);
  layout->setContentsMargins(18, 18, 18, 18);
  layout->setSpacing(12);
  auto *heading = text("Account");
  heading->setObjectName("sectionTitle");
  layout->addWidget(heading);
  const auto provider = state.value("provider").toObject(),
             active = provider.value("active").toObject();
  if (active.isEmpty())
    layout->addWidget(text("No account connected."));
  else {
    if (!active.value("name").toString().isEmpty())
      layout->addWidget(text(active.value("name").toString()));
    auto *email = text(active.value("email").toString());
    email->setTextInteractionFlags(Qt::TextSelectableByMouse);
    layout->addWidget(email);
    layout->addWidget(text(provider.value("state") == "ready"
                               ? "Connected"
                               : "Reconnect required"));
    layout->addWidget(text(provider.value("billing").toString()));
    auto workspaceName = active.value("workspace").toString();
    if (!workspaceName.startsWith("Workspace") && !workspaceName.isEmpty())
      layout->addWidget(text(workspaceName));
  }
  panel->adjustSize();
  auto bounds = screen()->availableGeometry();
  panel->move(qBound(bounds.left() + 8, panel->x(),
                     bounds.right() - panel->width() - 8),
              qBound(bounds.top() + 8, panel->y(),
                     bounds.bottom() - panel->height() - 8));
  panel->show();
}
void WorkspaceWindow::showUsageDetails() {
  auto *panel = popover(this, usageBadge, "usagePopover");
  if (!panel)
    return;
  auto *layout = new QVBoxLayout(panel);
  layout->setContentsMargins(16, 16, 16, 16);
  layout->setSpacing(12);
  auto *heading = text("Reported usage");
  heading->setObjectName("sectionTitle");
  layout->addWidget(heading);
  const auto usage =
      state.value("conversation").toObject().value("token_usage").toObject();
  auto *rows = new QFormLayout;
  rows->setSpacing(10);
  for (const auto &field : {qMakePair("totalTokens", "Total tokens"),
                            qMakePair("inputTokens", "Input"),
                            qMakePair("cachedInputTokens", "Cached input"),
                            qMakePair("outputTokens", "Output")})
    if (usage.contains(field.first)) {
      auto *number =
          text(QLocale().toString(usage.value(field.first).toInteger()));
      number->setAlignment(Qt::AlignRight);
      rows->addRow(field.second, number);
    }
  layout->addLayout(rows);
  for (auto value : state.value("provider")
                        .toObject()
                        .value("usage")
                        .toObject()
                        .value("windows")
                        .toArray()) {
    auto window = value.toObject();
    layout->addWidget(text(
        window.value("label").toString() + " · " +
        QString::number(qRound(window.value("remaining_percent").toDouble())) +
        "% remaining"));
  }
  layout->addWidget(
      text("Cached input is included in input tokens. Token counts are "
           "separate from plan allowance and API cost."));
  panel->adjustSize();
  auto bounds=screen()->availableGeometry();
  panel->move(qBound(bounds.left()+8,panel->x(),bounds.right()-panel->width()-8),qBound(bounds.top()+8,panel->y(),bounds.bottom()-panel->height()-8));
  panel->show();
}
void WorkspaceWindow::notify(const QString &message, const QString &severity) {
  auto *host = findChild<QFrame *>("notificationHost");
  if (!host) {
    host = new QFrame(this);
    host->setObjectName("notificationHost");
    auto *layout = new QVBoxLayout(host);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(8);
  }
  for (auto *frame : host->findChildren<QFrame *>("notificationCard"))
    if (frame->property("message").toString() == message) {
      host->raise();
      return;
    }
  auto *layout = qobject_cast<QVBoxLayout *>(host->layout());
  while (layout->count() >= 3) {
    auto *item = layout->takeAt(0);
    delete item->widget();
    delete item;
  }
  auto *card = new QFrame;
  card->setObjectName("notificationCard");
  card->setProperty("message", message);
  auto *row = new QHBoxLayout(card);
  row->setContentsMargins(14, 12, 10, 12);
  auto *icon = new QLabel;
  icon->setPixmap(style()
                      ->standardIcon(severity == "error"
                                         ? QStyle::SP_MessageBoxCritical
                                     : severity == "warning"
                                         ? QStyle::SP_MessageBoxWarning
                                         : QStyle::SP_MessageBoxInformation)
                      .pixmap(22, 22));
  row->addWidget(icon, 0, Qt::AlignTop);
  row->addWidget(text(message), 1);
  auto *close = new QPushButton;
  close->setFixedSize(26, 26);
  setWorkspaceIcon(close, "cross");
  close->setAccessibleName("Dismiss notification");
  row->addWidget(close, 0, Qt::AlignTop);
  connect(close, &QPushButton::clicked, card, &QWidget::deleteLater);
  if (severity == "error") {
    auto *details = new QPushButton("Details");
    row->addWidget(details, 0, Qt::AlignTop);
    connect(details, &QPushButton::clicked, this, [this, message] {
      QMessageBox::information(this, "Application notice", message);
    });
  } else
    QTimer::singleShot(5500, card, &QWidget::deleteLater);
  connect(card,&QObject::destroyed,host,[host] { QTimer::singleShot(0,host,[host] { host->adjustSize();if(host->layout()->count()==0)host->hide(); }); });
  layout->addWidget(card);
  host->setFixedWidth(qMin(440, width() - 32));
  host->adjustSize();
  host->move(width() - host->width() - 16, menuBar()->height() + 62);
  host->show();
  host->raise();
}
void WorkspaceWindow::saveAs() {
  if (busy || focusOpenDialog())
    return;
  if (state.value("project").toObject().isEmpty()) {
    notify("Open a project before saving a copy.", "info");
    return;
  }
  bool accepted = false;
  auto name = QInputDialog::getText(
      this, "Save project as", "New project name", QLineEdit::Normal,
      state.value("project").toObject().value("name").toString() + " copy",
      &accepted);
  if (accepted && !name.trimmed().isEmpty())
    call("v2.project.save_as", {{"name", name}}, [this](auto) {
      notify("Project copy saved. You are now working in the copy.", "info");
    });
}
void WorkspaceWindow::batchConversations(const QJsonArray &items,
                                         const QString &action) {
  if (items.isEmpty() || busy)
    return;
  const bool confirmed = property("purgeConfirmed").toBool();
  setProperty("purgeConfirmed", false);
  if (action == "purge" && !confirmed &&
      QMessageBox::question(
          this, "Delete conversations permanently",
          "Permanently delete " + QString::number(items.size()) +
              " selected conversation(s)? CAD documents and revisions are "
              "kept. This cannot be undone.") != QMessageBox::Yes)
    return;
  call("v2.conversations.batch", {{"items", items}, {"action", action}},
       [this](auto result) {
         QStringList failed;
         int passed = 0;
         for (auto value : result.value("results").toArray()) {
           auto item = value.toObject();
           if (item.value("passed").toBool())
             ++passed;
           else
             failed << item.value("error").toString();
         }
         notify(QString::number(passed) + " conversation(s) updated." +
                    (failed.isEmpty() ? QString()
                                      : " Failed: " + failed.join("; ")),
                failed.isEmpty() ? "info" : "error");
         if (property("reopenLibrary").toBool()) {
           setProperty("reopenLibrary", false);
           manageProjects();
         }
       });
}
void WorkspaceWindow::manageProjects() {
  if (busy || focusOpenDialog())
    return;
  auto *dialog = new QDialog(this);
  dialog->setAttribute(Qt::WA_DeleteOnClose);
  dialog->setObjectName("projectCatalogue");
  dialog->setWindowModality(Qt::WindowModal);
  dialog->setWindowTitle("Conversation library");
  auto *layout = new QVBoxLayout(dialog);
  auto *tabs = new QTabWidget;
  tabs->setObjectName("libraryTabs");
  layout->addWidget(tabs);
  for (int section = 0; section < 2; ++section) {
    const bool trash = section == 1;
    auto *page = new QWidget;
    auto *body = new QVBoxLayout(page);
    auto *tree = new QTreeWidget;
    tree->setObjectName(trash ? "trashTree" : "archiveTree");
    tree->setHeaderLabels({"Project / conversation"});
    tree->setSelectionMode(QAbstractItemView::ExtendedSelection);
    body->addWidget(tree);
    for (auto value :
         state.value("catalog").toObject().value("projects").toArray()) {
      auto project = value.toObject();
      const bool projectMatch = trash ? project.value("trashed").toBool()
                                      : project.value("archived").toBool() &&
                                            !project.value("trashed").toBool();
      QTreeWidgetItem *parent = nullptr;
      for (auto entry : project.value("conversation_summaries").toArray()) {
        auto conversation = entry.toObject();
        const bool match = trash ? conversation.value("trashed").toBool()
                                 : conversation.value("archived").toBool() &&
                                       !conversation.value("trashed").toBool();
        if (!match && !projectMatch)
          continue;
        if (!parent) {
          parent =
              new QTreeWidgetItem(tree, {project.value("name").toString()});
          parent->setData(0, Qt::UserRole, project.value("project_id"));
          if (!projectMatch)
            parent->setFlags(parent->flags() & ~Qt::ItemIsSelectable);
        }
        auto *item = new QTreeWidgetItem(
            parent, {conversation.value("title").toString()});
        item->setData(0, Qt::UserRole, project.value("project_id"));
        item->setData(0, Qt::UserRole + 1,
                      conversation.value("conversation_id"));
        if (projectMatch && !match)
          item->setFlags(item->flags() & ~Qt::ItemIsSelectable);
      }
      if (projectMatch && !parent) {
        parent = new QTreeWidgetItem(tree, {project.value("name").toString()});
        parent->setData(0, Qt::UserRole, project.value("project_id"));
      }
      if (parent)
        parent->setExpanded(true);
    }
    body->addWidget(
        text(trash ? "Restore conversations or permanently remove their local "
                     "records. Shared CAD geometry is kept."
                   : "Archived conversations stay saved and can be returned to "
                     "active navigation."));
    auto *actions = new QHBoxLayout;
    auto perform = [this, tree, dialog, trash](const QString &action) {
      auto rows = tree->selectedItems();
      if (rows.isEmpty() || busy)
        return;
      QJsonArray items;
      QString projectId;
      QString projectName;
      for (auto *row : rows) {
        auto cid = row->data(0, Qt::UserRole + 1).toString();
        if (cid.isEmpty()) {
          if (rows.size() != 1) {
            notify("Select a single project or multiple conversations.",
                   "warning");
            return;
          }
          projectId = row->data(0, Qt::UserRole).toString();
          projectName = row->text(0);
        } else
          items.append(
              QJsonObject{{"project_id", row->data(0, Qt::UserRole).toString()},
                          {"conversation_id", cid}});
      }
      if (!projectId.isEmpty()) {
        if (action == "purge" &&
            QMessageBox::question(dialog, "Delete project permanently",
                                  "Delete “" + projectName +
                                      "” and its entire local project folder? "
                                      "This cannot be undone.") !=
                QMessageBox::Yes)
          return;
        QJsonObject args{{"project_id", projectId}};
        QString method = "v2.project.update";
        if (action == "purge")
          method = "v2.project.purge";
        else if (action == "trash")
          args["trashed"] = true;
        else
          args[trash ? "trashed" : "archived"] = false;
        dialog->close();
        call(method, args);
        return;
      }
      if (action == "purge" &&
          QMessageBox::question(
              dialog, "Delete conversations permanently",
              "Delete " + QString::number(items.size()) +
                  " selected conversation(s)? Documents and revisions are "
                  "kept. This cannot be undone.") != QMessageBox::Yes)
        return;
      if (action == "purge")
        setProperty("purgeConfirmed", true);
      setProperty("reopenLibrary", true);
      setProperty("librarySection", trash ? 1 : 0);
      dialog->close();
      batchConversations(items,
                         action == "restore" && !trash ? "unarchive" : action);
    };
    auto *restore = new QPushButton("Restore selected");
    restore->setObjectName("restoreTrashItem");
    actions->addWidget(restore);
    connect(restore, &QPushButton::clicked, dialog,
            [perform] { perform("restore"); });
    auto *remove =
        new QPushButton(trash ? "Delete permanently…" : "Move to trash");
    remove->setObjectName(trash ? "purgeTrashItem" : "archiveToTrash");
    actions->addWidget(remove);
    connect(remove, &QPushButton::clicked, dialog,
            [perform, trash] { perform(trash ? "purge" : "trash"); });
    restore->setEnabled(false);
    remove->setEnabled(false);
    connect(
        tree, &QTreeWidget::itemSelectionChanged, dialog,
        [tree, restore, remove, trash] {
          const auto count = tree->selectedItems().size();
          bool enabled = count > 0;
          restore->setEnabled(enabled);
          remove->setEnabled(enabled);
          restore->setText("Restore selected (" + QString::number(count) + ")");
          remove->setText((trash ? "Delete permanently (" : "Move to trash (") +
                          QString::number(count) + ")");
        });
    body->addLayout(actions);
    tabs->addTab(page, trash ? "Trash" : "Archive");
  }
  tabs->setCurrentIndex(property("librarySection").toInt());
  auto *close = new QDialogButtonBox(QDialogButtonBox::Close);
  layout->addWidget(close);
  connect(close, &QDialogButtonBox::rejected, dialog, &QDialog::reject);
  dialog->resize(680, 480);
  dialog->show();
}
