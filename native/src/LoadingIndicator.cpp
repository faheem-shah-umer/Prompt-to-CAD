#include "LoadingIndicator.h"
#include "WorkspaceTheme.h"
#include <QAccessible>
#include <QEvent>
#include <QPainter>
#include <QShowEvent>
#include <QSet>
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
QSet<LoadingIndicator *> &indicators() {
    static QSet<LoadingIndicator *> live;
    return live;
}
constexpr int RevealDelay = 200;
constexpr int FrameInterval = 33;
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
    connect(&delay, &QTimer::timeout, this, [this] { if (pending) reveal(); });
    connect(&pulse, &QTimer::timeout, this, [this] {
        // The text and surrounding workspace never need a per-frame redraw.
        update(QRect(8, (height() - 18) / 2, 20, 18));
    });
    if (floating) parent->installEventFilter(this);
    indicators().insert(this);
    hide();
}

LoadingIndicator::~LoadingIndicator() { indicators().remove(this); }

void LoadingIndicator::reveal() {
    positionBadge();
    show();
    raise();
}

int LoadingIndicator::begin(const QString &message) {
    label = message;
    setAccessibleName(message);
    setToolTip(message);
    pending = true;
    requested.start();
    positionBadge();
    if (!isHidden()) { update(); return ++generation; }
    delay.start();
    return ++generation;
}

void LoadingIndicator::keepAlive() {
    for (auto *indicator : indicators()) {
        if (!indicator->pending || !indicator->parentWidget() || !indicator->parentWidget()->isVisible()) continue;
        if (indicator->isHidden()) {
            // The reveal timer cannot fire while the UI thread is busy, so honour it here.
            if (!indicator->requested.isValid() || indicator->requested.elapsed() < RevealDelay) continue;
            indicator->delay.stop();
            indicator->reveal();
            indicator->repaint();
            continue;
        }
        if (!indicator->animate || (indicator->lastFrame.isValid() && indicator->lastFrame.elapsed() < FrameInterval)) continue;
        indicator->raise();
        indicator->repaint(QRect(8, (indicator->height() - 18) / 2, 20, 18));
    }
}

void LoadingIndicator::finish(int token) {
    if (token >= 0 && token != generation) return;
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
    lastFrame.start();
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
