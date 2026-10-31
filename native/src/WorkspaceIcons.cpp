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
    const auto colors = workspaceColors();
    painter.fillRect(image.rect(), inverse ? colors.onAction : colors.secondary);
    painter.end();
    image.setDevicePixelRatio(2);
    QIcon icon(image);
    auto disabled = image;
    QPainter muted(&disabled);
    muted.setCompositionMode(QPainter::CompositionMode_SourceIn);
    muted.fillRect(disabled.rect(), colors.disabled);
    muted.end();
    icon.addPixmap(disabled, QIcon::Disabled);
    return icon;
}
void setWorkspaceIcon(QAbstractButton *button, const QString &name, bool inverse) {
    button->setProperty("workspaceIcon", name);
    button->setProperty("inverseIcon", inverse);
    button->setIcon(workspaceIcon(name, inverse));
    button->setIconSize(QSize(WorkspaceMetrics::Icon, WorkspaceMetrics::Icon));
    button->setProperty("workspaceIconOnly", button->text().isEmpty());
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
