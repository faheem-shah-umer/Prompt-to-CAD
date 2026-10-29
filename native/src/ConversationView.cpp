#include "ConversationView.h"
#include "WorkspaceTheme.h"
#include <QApplication>
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
}
void ConversationView::notice(const QString &text) {
    notices.append(QJsonObject{{"role", "system"}, {"content", text}});
    rebuild();
}
QString ConversationView::plainText() const {
    QStringList result;
    for (auto value : entries)
        result << value.toObject().value("content").toString();
    return result.join('\n');
}
void ConversationView::setMessages(const QJsonArray &messages, const QString &conversation) {
    if (context != conversation) {
        context = conversation;
        notices = {};
        expanded.clear();
        cachedTheme.clear();
    }
    const auto theme = qApp->property("workspaceTheme").toString();
    if (entries == messages && cachedTheme == theme)
        return;
    entries = messages;
    cachedTheme = theme;
    rebuild();
}
void ConversationView::resizeEvent(QResizeEvent *event) {
    QScrollArea::resizeEvent(event);
    for (auto *bubble : widget() ? widget()->findChildren<QFrame *>("messageBubble") : QList<QFrame *>{})
        bubble->setMaximumWidth(bubble->property("user").toBool() ? int(viewport()->width() * 0.87)
                                                                               : viewport()->width() - 12);
}
void ConversationView::rebuild() {
    const int oldScroll = verticalScrollBar()->value();
    const bool follow = oldScroll >= verticalScrollBar()->maximum() - 45;
    auto *content = new QWidget;
    content->setObjectName("chatContents");
    auto *stack = new QVBoxLayout(content);
    stack->setContentsMargins(0, 8, 0, 14);
    stack->setSpacing(22);
    auto messages = entries;
    for (auto entry : notices)
        messages.append(entry);
    if (messages.isEmpty()) {
        auto *welcome = new QLabel("<h3>What would you like to build?</h3><p>Describe a part, include dimensions, "
                                   "or select geometry to focus a change.</p>");
        welcome->setWordWrap(true);
        stack->addWidget(welcome);
    }
    int index = 0;
    for (auto value : messages) {
        const auto message = value.toObject();
        const bool user = message.value("role") == "user";
        const bool assistant = message.value("role") == "assistant";
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
        body->setContentsMargins(14, 12, 14, 12);
        body->setSpacing(10);
        body->setAlignment(Qt::AlignTop);
        auto *author = new QLabel(user ? "You" : assistant ? "Codex" : "Notice");
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
    QTimer::singleShot(0, this, [this, follow, oldScroll] {
        verticalScrollBar()->setValue(follow ? verticalScrollBar()->maximum() : oldScroll);
    });
}
