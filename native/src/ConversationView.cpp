#include "ConversationView.h"
#include "WorkspaceTheme.h"
#include "WorkspaceIcons.h"
#include <QApplication>
#include <QClipboard>
#include <QDateTime>
#include <QFrame>
#include <QLabel>
#include <QJsonObject>
#include <QResizeEvent>
#include <QScrollBar>
#include <QTextBrowser>
#include <QTextBlock>
#include <QTextCursor>
#include <QTextDocument>
#include <QTimer>
#include <QToolButton>
#include <QWheelEvent>
#include <QKeyEvent>
#include <QVBoxLayout>
#include <cmath>

namespace {
QString duration(double seconds) {
    const auto total = qMax(0, qRound(seconds));
    return total >= 60 ? QString("%1m %2s").arg(total / 60).arg(total % 60)
                       : QString("%1s").arg(total);
}
class MessageText : public QTextBrowser {
  public:
    explicit MessageText(const QString &text) {
        setObjectName("messageText");
        setOpenLinks(false);
        setOpenExternalLinks(false);
        setFrameShape(QFrame::NoFrame);
        setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
        document()->setDocumentMargin(0);
        document()->setDefaultFont(qApp->font());
        document()->setDefaultStyleSheet("p {margin-top:0; margin-bottom:12px; line-height:150%;} "
                                        "li {margin-bottom:7px;} pre,code {font-family:Consolas;} "
                                        "a {color:" + QString(lightWorkspaceTheme() ? "#216650" : "#abd9c6") + ";}");
        auto safe = text;
        safe.replace("![", "\\![");
        auto features = QTextDocument::MarkdownFeatures(QTextDocument::MarkdownDialectGitHub);
        features.setFlag(QTextDocument::MarkdownNoHTML);
        document()->setMarkdown(safe, features);
        for (auto block = document()->begin(); block.isValid(); block = block.next()) {
            QTextCursor cursor(block);
            auto format = block.blockFormat();
            format.setLineHeight(145, QTextBlockFormat::ProportionalHeight);
            format.setTopMargin(0);
            format.setBottomMargin(block.textList() ? 5 : 12);
            cursor.setBlockFormat(format);
        }
    }
  protected:
    void resizeEvent(QResizeEvent *event) override {
        QTextBrowser::resizeEvent(event);
        document()->setTextWidth(viewport()->width());
        const int height = int(std::ceil(document()->size().height())) + 4;
        if (this->height() != height)
            setFixedHeight(height);
    }
};
} // namespace

ConversationView::ConversationView(QWidget *parent) : QScrollArea(parent) {
    setObjectName("conversationHistory");
    setWidgetResizable(true);
    setFrameShape(QFrame::NoFrame);
    setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    latest = new QToolButton(this);
    latest->setObjectName("latestMessage");
    latest->setArrowType(Qt::DownArrow);
    latest->setToolTip("Go to latest message");
    latest->setAccessibleName("Go to latest message");
    latest->setFixedSize(32,32);
    latest->hide();
    connect(latest,&QToolButton::clicked,this,&ConversationView::scrollToLatest);
    connect(verticalScrollBar(),&QScrollBar::valueChanged,this,[this] {

        latest->setVisible(!following); latest->raise();
    });
    connect(verticalScrollBar(),&QScrollBar::actionTriggered,this,[this](int action) {
        ++scrollGeneration;following=action==QAbstractSlider::SliderToMaximum;
        latest->setVisible(!following);
    });
    connect(verticalScrollBar(),&QScrollBar::sliderMoved,this,[this](int position) { ++scrollGeneration;following=verticalScrollBar()->maximum()-position<45;latest->setVisible(!following); });
    connect(verticalScrollBar(),&QScrollBar::rangeChanged,this,[this] {
        if(!restoring&&following) verticalScrollBar()->setValue(verticalScrollBar()->maximum());
    });
}
void ConversationView::scrollToLatest() { ++scrollGeneration;following=true;verticalScrollBar()->setValue(verticalScrollBar()->maximum());latest->hide(); }
QString ConversationView::plainText() const {
    QStringList result;
    for (auto value : entries)
        result << value.toObject().value("content").toString();
    return result.join('\n');
}
void ConversationView::setMessages(const QJsonArray &messages, const QString &conversation) {
    if (context != conversation) {
        context = conversation;
        following = true;
        expanded.clear();
        copiedUntil.clear();
        cachedTheme.clear();
    }
    const auto theme = qApp->property("workspaceTheme").toString();
    if (entries == messages && cachedTheme == theme)
        return;
    entries = messages;
    cachedTheme = theme;
    rebuild();
}
void ConversationView::wheelEvent(QWheelEvent *event) {
    ++scrollGeneration;
    const bool upward=event->angleDelta().y()>0||event->pixelDelta().y()>0;
    if(upward)following=false;
    QScrollArea::wheelEvent(event);
    if(!upward&&verticalScrollBar()->maximum()-verticalScrollBar()->value()<45)following=true;
    latest->setVisible(!following);
}
void ConversationView::keyPressEvent(QKeyEvent *event) {
    ++scrollGeneration;
    const bool upward=event->key()==Qt::Key_Home||event->key()==Qt::Key_PageUp||event->key()==Qt::Key_Up;
    if(upward)following=false;
    QScrollArea::keyPressEvent(event);
    if(event->key()==Qt::Key_End||(!upward&&verticalScrollBar()->maximum()-verticalScrollBar()->value()<45))following=true;
    latest->setVisible(!following);
}
void ConversationView::resizeEvent(QResizeEvent *event) {
    QScrollArea::resizeEvent(event);
    latest->move(width()/2-16,height()-44);
    for (auto *bubble : widget() ? widget()->findChildren<QFrame *>("messageBubble") : QList<QFrame *>{})
        bubble->setMaximumWidth(bubble->property("user").toBool() ? int(viewport()->width() * 0.87)
                                                                               : viewport()->width() - 12);
}
void ConversationView::rebuild() {
    const int oldScroll = verticalScrollBar()->value();
    const bool follow = following;
    const auto generation=scrollGeneration;
    restoring = true;
    auto *content = new QWidget;
    content->setObjectName("chatContents");
    auto *stack = new QVBoxLayout(content);
    stack->setContentsMargins(0, 8, 0, 14);
    stack->setSpacing(22);
    auto messages = entries;

    if (messages.isEmpty()) {
        auto *welcome = new QLabel("<h3>What would you like to build?</h3><p>Describe a part, include dimensions, "
                                   "or select geometry to focus a change.</p>");
        welcome->setWordWrap(true);
        stack->addWidget(welcome);
    }
    int index = 0;
    for (auto value : messages) {
        const auto message = value.toObject();
        if (message.value("role") != "user" && message.value("role") != "assistant") continue;
        const bool user = message.value("role") == "user";
        auto *row = new QWidget;
        row->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Maximum);
        auto *horizontal = new QHBoxLayout(row);
        horizontal->setContentsMargins(0, 0, 0, 0);
        if (user)
            horizontal->addStretch(1);
        auto *bubble = new QFrame;
        bubble->setObjectName("messageBubble");
        bubble->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Maximum);
        bubble->setProperty("user", user);
        bubble->setMaximumWidth(user ? int(viewport()->width() * 0.87) : viewport()->width() - 12);
        auto *body = new QVBoxLayout(bubble);
        body->setContentsMargins(user ? 14 : 0, user ? 12 : 0, user ? 14 : 0, user ? 12 : 0);
        body->setSpacing(10);
        body->setAlignment(Qt::AlignTop);
        const auto agent = message.value("agent").toObject();
        const auto reportedName = agent.value("display_name").toString().trimmed();
        const auto assistantName = !message.contains("agent") ? QString("Codex")
                                    : reportedName.isEmpty() ? QString("Assistant") : reportedName;
        auto *author = new QLabel(user ? "You" : assistantName);
        author->setObjectName("messageAuthor");
        body->addWidget(author);
        const auto events = message.value("activity").toArray();
        if (message.value("working").toBool() || !events.isEmpty() || message.contains("elapsed_seconds")) {
            const auto key = message.value("task_id").toString(QString::number(index));
            auto *toggle = new QToolButton;
            toggle->setObjectName("workDisclosure");
            toggle->setText(message.value("working").toBool()
                                ? "Working · " + duration(message.value("elapsed_seconds").toDouble())
                                : message.contains("elapsed_seconds")
                                      ? "Worked for " + duration(message.value("elapsed_seconds").toDouble())
                                      : "View activity");
            toggle->setCheckable(true);
            toggle->setChecked(expanded.contains(key));
            toggle->setArrowType(toggle->isChecked() ? Qt::DownArrow : Qt::RightArrow);
            toggle->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
            auto *activity = new QLabel;
            activity->setObjectName("activitySummary");
            activity->setWordWrap(true);
            activity->setTextFormat(Qt::PlainText);
            QStringList log;
            for (auto event : events) {
                const auto text = event.toObject().value("message").toString();
                if (!text.isEmpty())
                    log << text;
            }
            activity->setText(log.join("\n\n"));
            activity->setVisible(toggle->isChecked());
            connect(toggle, &QToolButton::toggled, this, [this, key, activity, toggle](bool open) {
                if (open) expanded.insert(key); else expanded.remove(key);
                toggle->setArrowType(open ? Qt::DownArrow : Qt::RightArrow);
                activity->setVisible(open);
            });
            body->addWidget(toggle, 0, Qt::AlignLeft);
            body->addWidget(activity);
            if (message.value("working").toBool()) {
                auto *phase = new QLabel(message.value("phase").toString());
                phase->setObjectName("livePhase");
                phase->setTextFormat(Qt::PlainText);
                phase->setWordWrap(true);
                body->addWidget(phase);
            }
        }
        const auto text = message.value("content").toString();
        if (!text.isEmpty()) {
            auto *reply = new MessageText(text);
            connect(reply, &QTextBrowser::anchorClicked, this, &ConversationView::anchorClicked);
            body->addWidget(reply);
        }
        const auto change = message.value("change").toObject();
        if (!change.isEmpty()) {
            auto *card = new QFrame;
            card->setObjectName("changeCard");
            auto *cardLayout = new QVBoxLayout(card);
            auto *links = new QLabel;
            links->setWordWrap(true);
            links->setTextFormat(Qt::RichText);
            const auto revision = change.value("result_revision_id").toString();
            QString parts;
            for (auto component : change.value("affected_components").toArray()) {
                const auto id = component.toString().toHtmlEscaped();
                parts += "<a href='component:" + id + "'>" + id + "</a>  ";
            }
            links->setText("<b>Design updated</b><p>" + parts + "</p><p>Geometry and task scope verified.</p>"
                           "<a href='revision:" + revision.toHtmlEscaped() + "'>Restore revision " +
                           revision.left(8).toHtmlEscaped() + "</a>");
            connect(links, &QLabel::linkActivated, this, [this](const QString &url) { Q_EMIT anchorClicked(QUrl(url)); });
            cardLayout->addWidget(links);
            body->addWidget(card);
        }
        if (!text.isEmpty()) {
            const auto copyKey = context + "/" + message.value("task_id").toString(QString::number(index)) +
                                 "/" + message.value("role").toString();
            auto *copy = new QToolButton;
            copy->setObjectName("messageCopy");
            copy->setProperty("copyKey", copyKey);
            copy->setFixedSize(26, 26);
            copy->setAccessibleName(user ? "Copy your message" : "Copy " + assistantName + " response");
            const bool copied = copiedUntil.value(copyKey) > QDateTime::currentMSecsSinceEpoch();
            setWorkspaceIcon(copy, copied ? "check" : "copy");
            copy->setToolTip(copied ? "Copied" : "Copy message");
            connect(copy, &QToolButton::clicked, this, [this, text, copyKey, copy] {
                QApplication::clipboard()->setText(text);
                copiedUntil[copyKey] = QDateTime::currentMSecsSinceEpoch() + 1500;
                setWorkspaceIcon(copy, "check");
                copy->setToolTip("Copied");
                QTimer::singleShot(1500, this, [this, copyKey] {
                    if (copiedUntil.value(copyKey) > QDateTime::currentMSecsSinceEpoch()) return;
                    copiedUntil.remove(copyKey);
                    for (auto *control : findChildren<QToolButton*>("messageCopy"))
                        if (control->property("copyKey").toString() == copyKey) {
                            setWorkspaceIcon(control, "copy");
                            control->setToolTip("Copy message");
                        }
                });
            });
            body->addWidget(copy, 0, user ? Qt::AlignRight : Qt::AlignLeft);
        }
        horizontal->addWidget(bubble, user ? 0 : 1);
        if (!user)
            horizontal->addSpacing(10);
        stack->addWidget(row);
        ++index;
    }
    stack->addStretch(1);
    auto *old = takeWidget();
    setWidget(content);
    delete old;
    QTimer::singleShot(0, this, [this, follow, oldScroll, generation] {
        if(generation==scrollGeneration) { verticalScrollBar()->setValue(follow ? verticalScrollBar()->maximum() : oldScroll);following=follow; }
        else if(following)verticalScrollBar()->setValue(verticalScrollBar()->maximum());
        restoring = false;
        latest->setVisible(!following && verticalScrollBar()->maximum()-verticalScrollBar()->value()>45);
        latest->raise();
    });
}
