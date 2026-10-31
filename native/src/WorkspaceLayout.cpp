#include "WorkspaceWindow.h"
#include "CadView.h"
#include <QAction>
#include <QJsonArray>
#include <QSettings>
#include <QSignalBlocker>
#include <QSplitter>
#include <QToolButton>
#include <QPushButton>

void WorkspaceWindow::setPanelVisible(const QString &panel, bool visible) {
    if (panel == "navigation") navigationPreferred = visible;
    else if (panel == "manager") managerPreferred = visible;
    else if (panel == "conversation") conversationPreferred = visible;
    priorityPanel = visible ? panel : QString();
    updateWorkspaceLayout();
}
void WorkspaceWindow::updateWorkspaceLayout() {
    if (!layoutReady || adjustingLayout) return;
    adjustingLayout = true;
    const int available = qMax(0, centralWidget()->width() - 48);
    bool nav = navigationPreferred, model = managerPreferred, conversation = conversationPreferred;
    int chatWidth = conversationWidth;
    auto required = [&] {
        return 640 + (nav ? navigationWidth + 8 : 0) +
            (model ? managerWidth + 8 : 0) + (conversation ? chatWidth + 8 : 0);
    };
    if (required() > available && nav && priorityPanel != "navigation") nav = false;
    if (required() > available && model && priorityPanel != "manager") model = false;
    const int reserved = (nav ? navigationWidth + 8 : 0) + (model ? managerWidth + 8 : 0);
    if (conversation) chatWidth = qBound(320, available - reserved - 480 - 8, conversationWidth);
    if (available - reserved - (conversation ? chatWidth + 8 : 0) < 480) {
        if (conversation && priorityPanel != "conversation") conversation = false;
        else if (model) model = false;
        else if (nav) nav = false;
    }
    navigation->setVisible(nav);
    manager->setVisible(model);
    conversationPane->setVisible(conversation);
    split->setSizes({nav ? navigationWidth : 0,
                     qMax(480, available - (nav ? navigationWidth + 8 : 0) -
                                     (conversation ? chatWidth + 8 : 0)),
                     conversation ? chatWidth : 0});
    const int innerWidth = split->sizes().value(1);
    modelSplit->setSizes({model ? managerWidth : 0, qMax(480, innerWidth - (model ? managerWidth + 8 : 0))});
    for (const auto &entry : {qMakePair(navigationAction, nav), qMakePair(managerAction, model),
                              qMakePair(conversationAction, conversation)})
        if (entry.first) {
            const QSignalBlocker blocker(entry.first);
            entry.first->setChecked(entry.second);
        }
    for (const auto &entry : {qMakePair("navigationToggle", nav), qMakePair("managerToggle", model),
                              qMakePair("conversationToggle", conversation)})
        if (auto *button = findChild<QPushButton *>(entry.first)) {
            const QSignalBlocker blocker(button);
            button->setChecked(entry.second);
        }
    adjustingLayout = false;
    positionNotifications();
}
void WorkspaceWindow::saveWorkspaceLayout() {
    if (!layoutReady) return;
    QSettings settings;
    settings.setValue("v2/navigationVisible", navigationPreferred);
    settings.setValue("v2/managerVisible", managerPreferred);
    settings.setValue("v2/conversationVisible", conversationPreferred);
    settings.setValue("v2/navigationWidth", navigationWidth);
    settings.setValue("v2/managerWidth", managerWidth);
    settings.setValue("v2/conversationWidth", conversationWidth);
    settings.setValue("v2/geometry", saveGeometry());
    settings.setValue("v2/panels", split->saveState());
    settings.setValue("v2/modelPanels", modelSplit->saveState());
}
void WorkspaceWindow::refreshDocumentControls() {
    if (auto *apply = findChild<QPushButton *>("applyCADOperation")) apply->setEnabled(!busy);
    const bool hasDocument = !document.value("document_id").toString().isEmpty();
    auto entities = selected.value("entities").toArray();
    if (entities.isEmpty() && !selected.isEmpty()) entities.append(selected);
    auto allKind = [&](const QString &kind) {
        if (entities.isEmpty()) return false;
        for (const auto &value : entities)
            if (value.toObject().value("kind").toString() != kind) return false;
        return true;
    };
    for (auto *action : findChildren<QAction *>()) {
        const auto operation = action->property("cadOperation").toString();
        if (operation.isEmpty()) {
            if (action->property("requiresGeometry").toBool()) action->setEnabled(!document.value("components").toArray().isEmpty() && !busy);
            continue;
        }
        bool enabled = !selected.isEmpty();
        QString hint = "Select geometry to use this command.";
        if (operation == "thickness" || operation == "holes") {
            enabled = allKind("face"); hint = "Select supported planar faces in Face mode.";
        } else if (operation == "fillet" || operation == "chamfer") {
            enabled = allKind("edge"); hint = "Select supported solid edges in Edge mode.";
        } else if (operation == "clearance") {
            enabled = allKind("body") && document.value("components").toArray().size() > 1;
            hint = "Select a body in a document with at least two components.";
        } else if (operation == "parameters") {
            enabled = false;
            for (const auto &entry : document.value("components").toArray())
                if (entry.toObject().value("instance_id") == selected.value("instance_id"))
                    enabled = entities.size() == 1 && allKind("body") && !entry.toObject().value("parameters").toObject().isEmpty();
            hint = "Select a component with editable named parameters.";
        } else if (operation == "colour" || operation == "move") {
            enabled = allKind("body") && (operation != "move" || entities.size() == 1); hint = operation == "move" ? "Select one component, or ask the agent to move a component set." : "Select whole components in Body mode.";
        } else if (operation == "mesh_scale") {
            enabled = entities.size() == 1 && allKind("body");
            for (const auto &part : document.value("components").toArray())
                if (part.toObject().value("instance_id") == selected.value("instance_id"))
                    enabled = enabled && part.toObject().value("representation") == "mesh";
            hint = "Select one visual mesh component in Body mode.";
        } else if (operation == "mesh_separate") {
            enabled = allKind("region"); hint = "Select an explicit mesh region in Face mode.";
        }
        action->setEnabled(hasDocument && enabled && !busy);
        action->setToolTip(action->isEnabled() ? action->text() : hint);
    }
}
