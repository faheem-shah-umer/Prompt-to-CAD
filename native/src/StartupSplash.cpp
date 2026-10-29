#include "StartupSplash.h"
#include "WorkspaceTheme.h"
#include <QPainter>
#include <QPixmap>

StartupSplash::StartupSplash() : QDialog(nullptr, Qt::SplashScreen | Qt::FramelessWindowHint) {
    setFixedSize(390, 310);
    setAttribute(Qt::WA_TranslucentBackground);
    connect(&pulse, &QTimer::timeout, this, [this] {
        angle = (angle + 12) % 360;
        update();
    });
    pulse.start(35);
}

void StartupSplash::paintEvent(QPaintEvent *) {
    QPainter p(this);
    p.setRenderHint(QPainter::Antialiasing);
    const bool light = lightWorkspaceTheme();
    p.setPen(QColor(light ? "#dcdce0" : "#3b3b40"));
    p.setBrush(QColor(light ? "#fafafa" : "#202022"));
    p.drawRoundedRect(rect().adjusted(1, 1, -1, -1), 18, 18);
    const auto logo =
        QPixmap(":/brand/app-icon.png").scaled(72, 72, Qt::KeepAspectRatio, Qt::SmoothTransformation);
    p.drawPixmap((width() - logo.width()) / 2, 42, logo);
    p.setPen(QColor(light ? "#242428" : "#eeeeef"));
    p.setFont(QFont("Segoe UI", 17, QFont::DemiBold));
    p.drawText(QRect(0, 137, width(), 34), Qt::AlignCenter, "Prompt to CAD");
    p.setPen(QColor(light ? "#71717a" : "#a1a1aa"));
    p.setFont(QFont("Segoe UI", 10));
    p.drawText(QRect(0, 176, width(), 28), Qt::AlignCenter, "Opening your design workspace");
    p.setPen(QPen(QColor(light ? "#dfdfe4" : "#3d3d42"), 2));
    p.drawEllipse(QRectF(184, 231, 22, 22));
    p.setPen(QPen(QColor("#bfa1d9"), 2.5, Qt::SolidLine, Qt::RoundCap));
    p.drawArc(QRectF(184, 231, 22, 22), -angle * 16, 110 * 16);
}
