#include "ConversationView.h"
#include "WorkspaceTheme.h"
#include "WorkspaceIcons.h"
#include <QApplication>
#include <QClipboard>
#include <QDateTime>
#include <QFrame>
#include <QLabel>
#include <QJsonObject>
#include <QImageReader>
#include <QPixmap>
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
#include <functional>

namespace {
QString duration(double seconds) {
    const auto total = qMax(0, qRound(seconds));
    return total >= 60 ? QString("%1m %2s").arg(total / 60).arg(total % 60)
                       : QString("%1s").arg(total);
}
QString activityText(const QJsonArray &events) {
    QStringList log;
    QString previous;
    for (const auto &event : events) {
        const auto item = event.toObject();
        const auto text = item.value("message").toString();
        if (!text.isEmpty() && text != previous) {
            QString line = text;
            if (item.contains("operations_used")) {
                line += "\nOperations: " +
                    QString::number(item.value("operations_used").toInt()) + "/" +
                    QString::number(item.value("operations_limit").toInt()) +
                    " (" + QString::number(item.value("operations_remaining").toInt()) +
                    " remaining)";
            }
            log << line;
            previous = text;
        }
    }
    return log.join("\n\n");
}
class MessageText : public QTextBrowser {
  public:
    MessageText(const QString &text, QWidget *parent) : QTextBrowser(parent) {
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
                                        "a {color:" + workspaceColors().link.name() + ";}");
        setMessage(text);
    }
    void setMessage(const QString &text) {
        if (source == text) return;
        source = text;
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
        updateHeight();
    }
  protected:
    void resizeEvent(QResizeEvent *event) override {
        QTextBrowser::resizeEvent(event);
        updateHeight();
    }
  private:
    void updateHeight() {
        document()->setTextWidth(viewport()->width());
        const int height = int(std::ceil(document()->size().height())) + 4;
        if (this->height() != height)
            setFixedHeight(height);
    }
    QString source;
};

class ActivityLog : public QScrollArea {
  public:
    ActivityLog(const QString &text, QWidget *parent, std::function<void()> reading)
        : QScrollArea(parent), onReading(std::move(reading)) {
        setObjectName("workActivityScroll");
        setAccessibleName("Task activity log");
        setFrameShape(QFrame::NoFrame);
        setWidgetResizable(false);
        setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
        setFocusPolicy(Qt::StrongFocus);
        setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
        viewport()->setAutoFillBackground(false);
        activity = new QLabel(this);
        activity->setObjectName("activitySummary");
        activity->setWordWrap(true);
        activity->setTextFormat(Qt::PlainText);
        activity->setTextInteractionFlags(Qt::TextSelectableByMouse);
        setWidget(activity);
        connect(verticalScrollBar(), &QScrollBar::actionTriggered, this, [this](int) { readingActivity(); });
        connect(verticalScrollBar(), &QScrollBar::sliderMoved, this, [this](int) { readingActivity(); });
        setActivity(text);
    }
    void setActivity(const QString &text) {
        if (activity->text() == text) { layoutActivity(); return; }
        const int position = verticalScrollBar()->value();
        const bool follow = verticalScrollBar()->maximum() - position < 24;
        const auto generation = scrollGeneration;
        activity->setText(text);
        layoutActivity();
        QTimer::singleShot(0, this, [this, position, follow, generation] {
            if (generation == scrollGeneration)
                verticalScrollBar()->setValue(follow ? verticalScrollBar()->maximum() : position);
        });
    }
  protected:
    void resizeEvent(QResizeEvent *event) override {
        QScrollArea::resizeEvent(event);
        layoutActivity();
    }
    void wheelEvent(QWheelEvent *event) override {
        readingActivity();
        QScrollArea::wheelEvent(event);
    }
    void keyPressEvent(QKeyEvent *event) override {
        if (event->key() == Qt::Key_Home || event->key() == Qt::Key_End ||
            event->key() == Qt::Key_PageUp || event->key() == Qt::Key_PageDown ||
            event->key() == Qt::Key_Up || event->key() == Qt::Key_Down) readingActivity();
        QScrollArea::keyPressEvent(event);
    }
  private:
    void readingActivity() {
        if (verticalScrollBar()->maximum() <= 0) return;
        ++scrollGeneration;
        onReading();
    }
    void layoutActivity() {
        if (!activity || layingOut) return;
        layingOut = true;
        activity->ensurePolished();
        const int width = qMax(1, viewport()->width());
        const int contentHeight = qMax(activity->fontMetrics().lineSpacing(), activity->heightForWidth(width));
        activity->resize(width, contentHeight);
        const int height = qMin(240, contentHeight);
        if (this->height() != height) setFixedHeight(height);
        layingOut = false;
    }
    QLabel *activity = nullptr;
    std::function<void()> onReading;
    unsigned scrollGeneration = 0;
    bool layingOut = false;
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
void ConversationView::setDocumentContext(const QJsonObject &document) {
    QHash<QString, QString> names;
    for (const auto &value : document.value("components").toArray()) {
        const auto part = value.toObject();
        names[part.value("instance_id").toString()] = part.value("name").toString("Component");
    }
    QJsonArray notes;
    for (const auto &value : document.value("engineering").toArray())
        if (value.toObject().value("kind") == "note") notes.append(value);
    if (componentNames != names || designNotes != notes) {
        componentNames = names;
        designNotes = notes;
        cachedTheme.clear();
    }
}
void ConversationView::setMessages(const QJsonArray &messages, const QString &conversation) {
    if (context != conversation) {
        context = conversation;
        following = true;
        expanded.clear();
        workingTasks.clear();
        copiedUntil.clear();
        cachedTheme.clear();
    }
    const auto theme = qApp->property("workspaceTheme").toString();
    if (entries == messages && cachedTheme == theme)
        return;
    QSet<QString> nextWorking;
    for (const auto &value : messages) {
        const auto message = value.toObject();
        if (message.value("working").toBool()) nextWorking.insert(message.value("task_id").toString());
    }
    for (const auto &id : nextWorking)
        if (!id.isEmpty() && !workingTasks.contains(id)) expanded.insert(id);
    for (const auto &id : workingTasks) if (!nextWorking.contains(id)) expanded.remove(id);
    workingTasks = nextWorking;
    const bool updated = cachedTheme == theme && updateWorkingMessages(messages);
    entries = messages;
    cachedTheme = theme;
    if (!updated) rebuild();
}
bool ConversationView::updateWorkingMessages(const QJsonArray &messages) {
    if (!widget() || messages.size() != entries.size()) return false;
    // Only live fields may change without rebuilding a turn's structure.
    for (int i = 0; i < messages.size(); ++i) {
        auto before = entries[i].toObject();
        auto after = messages[i].toObject();
        if (before == after) continue;
        if (before.value("role") != "assistant" ||
            !before.value("working").toBool() || !after.value("working").toBool() ||
            !messageTurns.contains(i)) return false;
        for (const auto &field : {"content", "activity", "phase", "elapsed_seconds"}) {
            before.remove(field);
            after.remove(field);
        }
        if (before != after) return false;
    }
    for (int i = 0; i < messages.size(); ++i) {
        const auto message = messages[i].toObject();
        if (!message.value("working").toBool() || entries[i] == messages[i]) continue;
        auto *turn = messageTurns.value(i);
        auto *toggle = turn->findChild<QToolButton *>("workDisclosure");
        const auto caption = "Working · " + duration(message.value("elapsed_seconds").toDouble());
        if (toggle->text() != caption) toggle->setText(caption);
        auto *activity = static_cast<ActivityLog *>(turn->findChild<QScrollArea *>("workActivityScroll"));
        const auto log = activityText(message.value("activity").toArray());
        activity->setActivity(log);
        auto *phase = turn->findChild<QLabel *>("livePhase");
        const auto phaseText = message.value("phase").toString();
        if (phase->text() != phaseText) phase->setText(phaseText);
        auto *reply = static_cast<MessageText *>(turn->findChild<QTextBrowser *>("messageText"));
        const auto text = message.value("content").toString();
        reply->setMessage(text);
        reply->setVisible(!text.isEmpty());
        auto *copy = turn->findChild<QToolButton *>("messageCopy");
        copy->setProperty("messageText", text);
        copy->setVisible(!text.isEmpty());
    }
    return true;
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
    for (auto *turn : widget() ? widget()->findChildren<QWidget *>("messageTurn") : QList<QWidget *>{})
        turn->setMaximumWidth(turn->property("user").toBool() ? int(viewport()->width() * 0.94)
                                                                               : viewport()->width() - 12);
}
void ConversationView::rebuild() {
    const int oldScroll = verticalScrollBar()->value();
    const bool follow = following;
    const auto generation=scrollGeneration;
    restoring = true;
    messageTurns.clear();
    auto *content = new QWidget(viewport());
    content->setObjectName("chatContents");
    auto *stack = new QVBoxLayout(content);
    stack->setContentsMargins(0, 8, 0, 14);
    stack->setSpacing(22);
    auto messages = entries;

    if (messages.isEmpty()) {
        auto *welcome = new QLabel("<h3>What would you like to build?</h3><p>Describe a part, include dimensions, "
                                   "or select geometry to focus a change.</p>", content);
        welcome->setWordWrap(true);
        stack->addWidget(welcome);
    }
    int index = -1;
    for (auto value : messages) {
        ++index;
        const auto message = value.toObject();
        if (message.value("role") != "user" && message.value("role") != "assistant") continue;
        const bool user = message.value("role") == "user";
        // Visibility may be set while building a turn. Keep the full parent chain
        // attached so no chat control can briefly appear as a desktop window.
        auto *row = new QWidget(content);
        row->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Maximum);
        auto *horizontal = new QHBoxLayout(row);
        horizontal->setContentsMargins(0, 0, 0, 0);
        if (user)
            horizontal->addStretch(1);
        auto *turn = new QWidget(row);
        messageTurns.insert(index, turn);
        turn->setObjectName("messageTurn");
        turn->setProperty("user", user);
        turn->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Maximum);
        turn->setMaximumWidth(user ? int(viewport()->width() * 0.94) : viewport()->width() - 12);
        auto *turnLayout = new QVBoxLayout(turn);
        turnLayout->setContentsMargins(0, 0, 0, 0);
        turnLayout->setSpacing(4);
        auto *bubble = new QFrame(turn);
        bubble->setObjectName("messageBubble");
        bubble->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Maximum);
        bubble->setProperty("user", user);
        turnLayout->addWidget(bubble);
        auto *body = new QVBoxLayout(bubble);
        body->setContentsMargins(user ? 14 : 0, user ? 12 : 0, user ? 14 : 0, user ? 12 : 0);
        body->setSpacing(10);
        body->setAlignment(Qt::AlignTop);
        const auto agent = message.value("agent").toObject();
        const auto reportedName = agent.value("display_name").toString().trimmed();
        const auto assistantName = !message.contains("agent") ? QString("Codex")
                                    : reportedName.isEmpty() ? QString("Assistant") : reportedName;
        if (!user) {
            auto *author = new QLabel(assistantName, bubble);
            author->setObjectName("messageAuthor");
            body->addWidget(author);
        }
        const auto events = message.value("activity").toArray();
        if (message.value("working").toBool() || !events.isEmpty() || message.contains("elapsed_seconds")) {
            const auto key = message.value("task_id").toString(QString::number(index));
            auto *toggle = new QToolButton(bubble);
            toggle->setObjectName("workDisclosure");
            toggle->setText(message.value("working").toBool()
                                ? "Working · " + duration(message.value("elapsed_seconds").toDouble())
                                : message.contains("elapsed_seconds")
                                      ? "Worked for " + duration(message.value("elapsed_seconds").toDouble())
                                      : "View activity");
            toggle->setAccessibleName(message.value("working").toBool() ? "Current task activity" : "Completed task activity");
            toggle->setToolTip("Expand or collapse observable tool activity");
            toggle->setCheckable(true);
            toggle->setChecked(expanded.contains(key));
            toggle->setArrowType(toggle->isChecked() ? Qt::DownArrow : Qt::RightArrow);
            toggle->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
            auto *activity = new ActivityLog(activityText(events), bubble, [this] {
                ++scrollGeneration;
                following = false;
                latest->show();
                latest->raise();
            });
            activity->setVisible(toggle->isChecked());
            connect(toggle, &QToolButton::toggled, this, [this, key, activity, toggle](bool open) {
                if (open) expanded.insert(key); else expanded.remove(key);
                toggle->setArrowType(open ? Qt::DownArrow : Qt::RightArrow);
                activity->setVisible(open);
            });
            body->addWidget(toggle, 0, Qt::AlignLeft);
            body->addWidget(activity);
            if (message.value("working").toBool()) {
                auto *phase = new QLabel(message.value("phase").toString(), bubble);
                phase->setObjectName("livePhase");
                phase->setTextFormat(Qt::PlainText);
                phase->setWordWrap(true);
                body->addWidget(phase);
            }
        }
        const auto text = message.value("content").toString();
        if (!text.isEmpty() || message.value("working").toBool()) {
            auto *reply = new MessageText(text, bubble);
            reply->setVisible(!text.isEmpty());
            connect(reply, &QTextBrowser::anchorClicked, this, &ConversationView::anchorClicked);
            body->addWidget(reply);
        }
        for (const auto& value : message.value("attachments").toArray()) {
            const auto reference = value.toObject();
            if (!reference.value("available").toBool() || reference.value("local_path").toString().isEmpty()) {
                auto *missing = new QLabel("⚠ " + reference.value("name").toString() + " · image unavailable", bubble);
                missing->setTextFormat(Qt::PlainText); missing->setWordWrap(true); body->addWidget(missing); continue;
            }
            auto *image = new QToolButton(bubble);
            image->setObjectName("referenceImage"); image->setToolButtonStyle(Qt::ToolButtonTextUnderIcon);
            QImageReader reader(reference.value("local_path").toString()); reader.setScaledSize(reader.size().scaled(160, 100, Qt::KeepAspectRatio));
            const auto preview = reader.read();
            if (preview.isNull()) { image->setText("Image unavailable"); image->setEnabled(false); }
            else { image->setIcon(QPixmap::fromImage(preview)); image->setIconSize(preview.size()); image->setText(reference.value("name").toString().left(30)); }
            image->setToolTip("Attach this preserved image to a new request"); image->setAccessibleName("Reuse reference " + reference.value("name").toString());
            connect(image, &QToolButton::clicked, this, [this, reference] { Q_EMIT attachmentRequested(reference); });
            body->addWidget(image, 0, Qt::AlignLeft);
        }
        const auto change = message.value("change").toObject();
        if (!change.isEmpty()) {
            auto *card = new QFrame(bubble);
            card->setObjectName("changeCard");
            auto *cardLayout = new QVBoxLayout(card);
            auto *links = new QLabel(card);
            links->setWordWrap(true);
            links->setTextFormat(Qt::RichText);
            const auto revision = change.value("result_revision_id").toString();
            auto names = [this](const QJsonArray &components, bool link) {
                QStringList labels;
                for (const auto &value : components) {
                    const auto id = value.toString();
                    const auto name = componentNames.value(id);
                    if (name.isEmpty()) continue;
                    labels << (link ? "<a href='component:" + QString::fromLatin1(QUrl::toPercentEncoding(id)) +
                        "'>" + name.toHtmlEscaped() + "</a>" : name.toHtmlEscaped());
                }
                return labels.join(", ");
            };
            QString changes = "<b>Design updated</b>";
            const auto affected = change.value("affected_components").toArray();
            if (!affected.isEmpty()) changes += "<p>" + names(affected, true) + "</p>";
            for (const auto &field : {qMakePair("created_components", "Created"),
                                     qMakePair("replaced_components", "Updated"),
                                     qMakePair("consumed_components", "Removed")}) {
                const auto items = change.value(field.first).toArray();
                if (!items.isEmpty()) changes += "<p>" + QString(field.second) + " · " +
                    QString::number(items.size()) + " component(s)" +
                    (names(items, false).isEmpty() ? QString() : " · " + names(items, false)) + "</p>";
            }
            const auto validation = change.value("validation").toObject();
            const auto geometry = validation.value("geometry").toObject();
            const auto scope = validation.value("scope").toObject();
            const auto engineering = validation.value("engineering").toObject();
            if (geometry.contains("passed")) changes += "<p>Geometry · " +
                QString(geometry.value("passed").toBool() ? "passed" : "check failed") + "</p>";
            if (scope.contains("passed")) changes += "<p>Task scope · " +
                QString(scope.value("passed").toBool() ? "passed" : "check failed") + "</p>";
            if (scope.contains("unrelated_components_checked")) changes += "<p>" +
                QString::number(scope.value("unrelated_components_checked").toInt()) + " unrelated component(s) checked</p>";
            if (engineering.contains("records")) changes += "<p>" +
                QString::number(engineering.value("records").toInt()) + " engineering record(s) checked</p>";
            if (validation.isEmpty()) changes += "<p>Validation details were not retained for this older turn.</p>";
            if (!revision.isEmpty()) changes += "<p><a href='revision:" +
                QString::fromLatin1(QUrl::toPercentEncoding(revision)) + "'>Restore this revision</a></p>";
            links->setText(changes);
            connect(links, &QLabel::linkActivated, this, [this](const QString &url) { Q_EMIT anchorClicked(QUrl(url)); });
            cardLayout->addWidget(links);
            body->addWidget(card);
        }
        if (!text.isEmpty() || message.value("working").toBool()) {
            const auto copyKey = context + "/" + message.value("task_id").toString(QString::number(index)) +
                                 "/" + message.value("role").toString();
            auto *copy = new QToolButton(turn);
            copy->setObjectName("messageCopy");
            copy->setProperty("copyKey", copyKey);
            copy->setProperty("messageText", text);
            copy->setVisible(!text.isEmpty());
            copy->setFixedSize(26, 26);
            copy->setAccessibleName(user ? "Copy your message" : "Copy " + assistantName + " response");
            const bool copied = copiedUntil.value(copyKey) > QDateTime::currentMSecsSinceEpoch();
            setWorkspaceIcon(copy, copied ? "check" : "copy");
            copy->setToolTip(copied ? "Copied" : "Copy message");
            connect(copy, &QToolButton::clicked, this, [this, copyKey, copy] {
                QApplication::clipboard()->setText(copy->property("messageText").toString());
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
            turnLayout->addWidget(copy, 0, user ? Qt::AlignRight : Qt::AlignLeft);
        }
        horizontal->addWidget(turn, user ? 0 : 1);
        if (!user)
            horizontal->addSpacing(10);
        stack->addWidget(row);
    }
    if (!designNotes.isEmpty()) {
        auto *notes = new QWidget(content);
        notes->setObjectName("savedDesignNotes");
        auto *notesLayout = new QVBoxLayout(notes);
        notesLayout->setContentsMargins(0, 0, 10, 0);
        auto *heading = new QLabel("Saved design notes", notes);
        notesLayout->addWidget(heading);
        for (const auto &value : designNotes) {
            const auto record = value.toObject();
            auto *owner = new QLabel(componentNames.value(record.value("instance_id").toString(), "Removed component"), notes);
            owner->setTextFormat(Qt::PlainText);
            if (record.value("status") == "stale") owner->setText(owner->text() + " · Stale anchor");
            owner->setWordWrap(true);
            notesLayout->addWidget(owner);
            auto *text = new QLabel(record.value("text").toString(), notes);
            text->setTextFormat(Qt::PlainText);
            text->setWordWrap(true);
            text->setTextInteractionFlags(Qt::TextSelectableByMouse | Qt::TextSelectableByKeyboard);
            notesLayout->addWidget(text);
            auto *edit = new QToolButton(notes);
            edit->setText("Edit note");
            edit->setAccessibleName("Edit saved design note for " + owner->text());
            const auto identity = record.value("id").toString();
            connect(edit, &QToolButton::clicked, this, [this, identity] {
                Q_EMIT anchorClicked(QUrl("engineering:" + QString::fromLatin1(QUrl::toPercentEncoding(identity))));
            });
            notesLayout->addWidget(edit, 0, Qt::AlignLeft);
        }
        stack->addWidget(notes);
    }
    stack->addStretch(1);
    // setWidget deletes the previous contents without detaching a native widget.
    setWidget(content);
    QTimer::singleShot(0, this, [this, follow, oldScroll, generation] {
        if(generation==scrollGeneration) { verticalScrollBar()->setValue(follow ? verticalScrollBar()->maximum() : oldScroll);following=follow; }
        else if(following)verticalScrollBar()->setValue(verticalScrollBar()->maximum());
        restoring = false;
        latest->setVisible(!following && verticalScrollBar()->maximum()-verticalScrollBar()->value()>45);
        latest->raise();
    });
}
