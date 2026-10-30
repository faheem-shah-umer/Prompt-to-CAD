#include "WorkspaceIcons.h"
#include "WorkspaceTheme.h"
#include <QAbstractButton>
#include <QAction>
#include <QApplication>
#include <QPainter>
#include <QSvgRenderer>
#include <QWidget>

QIcon workspaceIcon(const QString &name, bool inverse) {
    QPixmap image(48, 48);
    image.fill(Qt::transparent);
    QPainter painter(&image);
    if (name == "copy") {
        painter.setRenderHint(QPainter::Antialiasing);
        painter.setPen(QPen(Qt::white, 2.5));
        painter.drawRoundedRect(QRectF(16, 16, 23, 25), 3, 3);
        painter.drawLine(QPointF(11, 31), QPointF(9, 31));
        painter.drawLine(QPointF(9, 31), QPointF(9, 9));
        painter.drawLine(QPointF(9, 9), QPointF(31, 9));
        painter.drawLine(QPointF(31, 9), QPointF(31, 12));
    } else {
        QSvgRenderer renderer(":/icons/" + name + ".svg");
        renderer.render(&painter, QRectF(3, 3, 42, 42));
    }
    painter.setCompositionMode(QPainter::CompositionMode_SourceIn);
    painter.fillRect(image.rect(), QColor(inverse ? (lightWorkspaceTheme() ? "#ffffff" : "#202024")
                                                : (lightWorkspaceTheme() ? "#4b586b" : "#b8bac3")));
    painter.end();
    image.setDevicePixelRatio(2);
    return QIcon(image);
}
void setWorkspaceIcon(QAbstractButton *button, const QString &name, bool inverse) {
    button->setProperty("workspaceIcon", name);
    button->setProperty("inverseIcon", inverse);
    button->setIcon(workspaceIcon(name, inverse));
    button->setIconSize(QSize(18, 18));
}
void refreshWorkspaceIcons(QWidget *root) {
    for (auto *button : root->findChildren<QAbstractButton *>()) {
        const auto name = button->property("workspaceIcon").toString();
        if (!name.isEmpty())
            button->setIcon(workspaceIcon(name, button->property("inverseIcon").toBool()));
    }
    for (auto *action : root->findChildren<QAction *>()) {
        const auto name = action->property("workspaceIcon").toString();
        if (!name.isEmpty())
            action->setIcon(workspaceIcon(name));
    }
}
