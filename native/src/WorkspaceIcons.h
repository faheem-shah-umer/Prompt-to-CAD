#pragma once
#include <QIcon>
class QAbstractButton;
class QWidget;
QIcon workspaceIcon(const QString &name, bool inverse = false);
void setWorkspaceIcon(QAbstractButton *button, const QString &name, bool inverse = false);
void refreshWorkspaceIcons(QWidget *root);
