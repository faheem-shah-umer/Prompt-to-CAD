#include "LoadingIndicator.h"
#include "WorkspaceTheme.h"
#include <QAccessible>
#include <QEvent>
#include <QPainter>
#include <QShowEvent>
#ifdef Q_OS_WIN
#include <windows.h>
#endif

namespace {
bool animationsEnabled() {
#ifdef Q_OS_WIN
    BOOL enabled = TRUE;
    if (SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, &enabled, 0)) return enabled;
#endif
    return true;
}
}

LoadingIndicator::LoadingIndicator(QWidget *parent, bool floatingBadge)
    : QWidget(parent), floating(floatingBadge) {
    setObjectName("loadingIndicator");
    setAttribute(Qt::WA_TransparentForMouseEvents);
    setFocusPolicy(Qt::NoFocus);
    setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Fixed);
    setAccessibleDescription("A background operation is in progress.");
    delay.setSingleShot(true);
    delay.setInterval(200);
    pulse.setInterval(35);
    connect(&delay, &QTimer::timeout, this, [this] {
        if (!pending) return;
        positionBadge();
        show();
        raise();
    });
    connect(&pulse, &QTimer::timeout, this, [this] {
        // The text and surrounding workspace never need a per-frame redraw.
        update(QRect(8, (height() - 18) / 2, 20, 18));
    });
    if (floating) parent->installEventFilter(this);
    hide();
}

void LoadingIndicator::begin(const QString &message) {
    label = message;
    setAccessibleName(message);
    setToolTip(message);
    pending = true;
    positionBadge();
    if (!isHidden()) { update(); return; }
    delay.start();
}

void LoadingIndicator::finish() {
    pending = false;
    delay.stop();
    pulse.stop();
    hide();
}

QSize LoadingIndicator::sizeHint() const {
    return QSize(fontMetrics().horizontalAdvance(label) + 44, floating ? 32 : 24);
}

void LoadingIndicator::positionBadge() {
    auto size = sizeHint();
    if (floating) size.setWidth(qMin(size.width(), qMax(48, parentWidget()->width() - 24)));
    setFixedSize(size);
    if (floating) move((parentWidget()->width() - width()) / 2, 12);
}

bool LoadingIndicator::eventFilter(QObject *object, QEvent *event) {
    if (object == parentWidget() && event->type() == QEvent::Resize) positionBadge();
    return QWidget::eventFilter(object, event);
}

void LoadingIndicator::showEvent(QShowEvent *event) {
    QWidget::showEvent(event);
    animate = animationsEnabled();
    clock.start();
    if (pending && animate) pulse.start();
    QAccessibleEvent announcement(this, QAccessible::NameChanged);
    QAccessible::updateAccessibility(&announcement);
}

void LoadingIndicator::hideEvent(QHideEvent *event) {
    pulse.stop();
    QWidget::hideEvent(event);
}

void LoadingIndicator::paintEvent(QPaintEvent *) {
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);
    const auto colors = workspaceColors();
    if (floating) {
        painter.setPen(colors.border);
        painter.setBrush(colors.raised);
        painter.drawRoundedRect(QRectF(rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                                WorkspaceMetrics::ControlRadius, WorkspaceMetrics::ControlRadius);
    }
    const QRectF ring(10, (height() - 16) / 2.0, 16, 16);
    painter.setBrush(Qt::NoBrush);
    painter.setPen(QPen(colors.border, 2));
    painter.drawEllipse(ring);
    painter.setPen(QPen(colors.action, 2, Qt::SolidLine, Qt::RoundCap));
    // Match the existing startup spinner's 1,050 ms linear rotation.
    const int angle = animate && clock.isValid() ? int((clock.elapsed() % 1050) * 360 / 1050) : 0;
    painter.drawArc(ring, (90 - angle) * 16, -110 * 16);
    painter.setPen(colors.secondary);
    const auto text = fontMetrics().elidedText(label, Qt::ElideRight, qMax(0, width() - 44));
    painter.drawText(QRect(34, 0, width() - 44, height()), Qt::AlignVCenter | Qt::AlignLeft, text);
}
