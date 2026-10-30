#include "WorkspaceTheme.h"
#include <QApplication>
#include <QFont>
#include <QPalette>

bool lightWorkspaceTheme() { return qApp->property("workspaceTheme").toString() == "light"; }

void applyWorkspaceTheme(const QString &name, int textSize) {
    const bool light = name == "light";
    qApp->setProperty("workspaceTheme", light ? "light" : "dark");
    const QString bg = light ? "#e9edf3" : "#1b1b1d";
    const QString sidebar = light ? "#dde4ee" : "#202023";
    const QString toolbar = light ? "#f3f5f8" : "#242427";
    const QString userBubble = light ? "#dae6f3" : "#303843";
    const QString panel = light ? "#ffffff" : "#222224";
    const QString text = light ? "#242428" : "#ececee";
    const QString muted = light ? "#67676f" : "#a1a1aa";
    const QString line = light ? "#c7cfdb" : "#38383c";
    const QString hover = light ? "#e0e6ef" : "#303033";
    const QString selected = light ? "#e4eeec" : "#2c3c38";
    const QString primary = light ? "#242428" : "#eeeeef";
    const QString primaryText = light ? "#ffffff" : "#202024";
    QPalette p;
    p.setColor(QPalette::Window, QColor(bg));
    p.setColor(QPalette::Base, QColor(panel));
    p.setColor(QPalette::AlternateBase, QColor(hover));
    p.setColor(QPalette::WindowText, QColor(text));
    p.setColor(QPalette::Text, QColor(text));
    p.setColor(QPalette::ButtonText, QColor(text));
    p.setColor(QPalette::Button, QColor(panel));
    p.setColor(QPalette::Highlight, QColor(selected));
    p.setColor(QPalette::HighlightedText, QColor(text));
    p.setColor(QPalette::PlaceholderText, QColor(muted));
    p.setColor(QPalette::Link, QColor(light ? "#286654" : "#a5cebf"));
    p.setColor(QPalette::Disabled, QPalette::Text, QColor(muted));
    p.setColor(QPalette::Disabled, QPalette::ButtonText, QColor(muted));
    qApp->setPalette(p);
    QFont font("Segoe UI");
    font.setPixelSize(textSize);
    qApp->setFont(font);
    auto css = QString(R"(
        QWidget { color:@text@; font-family:'Segoe UI'; font-size:@size@px; }
        QMainWindow, QDialog { background:@bg@; }
        QLabel { background:transparent; }
        QLabel#muted, QLabel#settingsCaption { color:@muted@; }
        QLabel#pageTitle { font-size:23px; font-weight:600; }
        QLabel#sectionTitle { font-size:14px; font-weight:600; }
        QMenuBar, QToolBar, QStatusBar { background:@bg@; border:0; padding:5px; }
        QMenu { background:@panel@; border:1px solid @line@; padding:5px; }
        QMenu::item { padding:6px 24px 6px 10px; }
        QMenu::item:selected { background:@hover@; border-radius:4px; }
        QWidget#rail { background:@bg@; border-right:1px solid @line@; }
        #rail QPushButton { border:0; background:transparent; padding:10px 0; }
        #navigation, #rail { background:@sidebar@; }
        #conversationPane { background:@bg@; border-left:1px solid @line@; }
        #cadManager { background:@toolbar@; border-right:1px solid @line@; }
        #documentHeader { background:@panel@; border-bottom:1px solid @line@; }
        QTabWidget#commandManager, #commandManager QToolBar { background:@toolbar@; }
        #commandManager::pane { border-bottom:1px solid @line@; }
        #navigation QPushButton { text-align:left; }
        QPushButton, QToolButton { background:transparent; border:1px solid @line@; border-radius:7px; padding:7px 12px; }
        QPushButton:hover, QToolButton:hover { background:@hover@; }
        QPushButton:disabled { color:@muted@; border-color:@line@; }
        QPushButton#primaryButton, QPushButton#connectChatGPT, QPushButton#onboardingConnect { color:@primaryText@; background:@primary@; border-color:@primary@; font-weight:600; }
        QPushButton#primaryButton:disabled, QPushButton#connectChatGPT:disabled, QPushButton#onboardingConnect:disabled { color:@muted@; background:@hover@; border-color:@line@; }
        QPushButton#commandSearchButton { padding:0; }
        QPushButton#quietButton { border:0; color:@muted@; }
        QPushButton#usageBadge { border:1px solid @line@; padding:4px 9px; font-size:11px; text-align:left; }
        #rail QPushButton#accountBadge { border:1px solid @line@; color:@text@; background:@panel@; border-radius:17px; padding:0; font-weight:600; }
        #rail QPushButton#accountBadge[connected="true"] { background:#d39b38; color:#ffffff; border:0; }
        QTreeWidget, QListWidget, QTextBrowser, QPlainTextEdit, QLineEdit { background:@panel@; border:1px solid @line@; border-radius:7px; padding:7px; selection-background-color:@selected@; }
        QScrollArea#conversationHistory, #chatContents { background:transparent; border:0; }
        QFrame#messageBubble { background:transparent; border:0; }
        QFrame#messageBubble[user="true"] { background:@userBubble@; border:0; border-radius:14px; }
        QTextBrowser#messageText { background:transparent; border:0; border-radius:0; padding:0; }
        QLabel#messageAuthor { color:@muted@; font-size:11px; font-weight:600; }
        QToolButton#messageCopy { border:0; border-radius:5px; padding:3px; }
        QToolButton#projectSort { padding:4px; }
        QToolButton#projectSort::menu-indicator { image:none; }
        QPushButton#showAllModels, QPushButton#hideAllModels, QPushButton#selectAllModels, QPushButton#clearModelSelection { padding:5px 6px; font-size:11px; }
        QToolButton#workDisclosure { border:0; background:transparent; padding:3px 0; color:@muted@; }
        QLabel#activitySummary, QLabel#livePhase { color:@muted@; }
        QFrame#changeCard { background:@selected@; border:0; border-radius:9px; padding:3px; }

        QFrame#accountPopover, QFrame#usagePopover, QFrame#modelPopover, QFrame#notificationCard { background:@panel@; border:1px solid @line@; border-radius:12px; }
        QFrame#notificationHost { background:transparent; }
        QToolButton#latestMessage { background:@panel@; border:1px solid @line@; border-radius:16px; padding:4px; }
        QListWidget#modelOptions { border:0; padding:0; }
        QListWidget#modelOptions::item { padding:9px 10px; border-radius:6px; }
        QFrame#composerFrame, QFrame#settingsCard { background:@panel@; border:1px solid @line@; border-radius:14px; }
        QFrame#composerFrame QPlainTextEdit { background:transparent; border:0; padding:4px; }
        QFrame#composerFrame QComboBox { background:transparent; border:0; padding:4px; }
        QFrame#composerFrame QPushButton#primaryButton { border-radius:15px; padding:0; font-size:17px; }
        QListWidget#settingsNavigation { background:transparent; border:0; padding:0; }
        QListWidget#settingsNavigation::item { padding:10px 12px; margin:2px 0; border-radius:6px; }
        QListWidget#settingsNavigation::item:selected { background:@hover@; color:@text@; }
        QListWidget#settingsNavigation::item:hover { background:@hover@; }
        QTreeWidget::item { padding:6px 3px; }
        QTreeWidget::item:selected { background:@selected@; color:@text@; }
        QComboBox, QDoubleSpinBox { background:@panel@; border:1px solid @line@; border-radius:6px; padding:6px; }
        QComboBox QAbstractItemView { background:@panel@; color:@text@; selection-background-color:@selected@; }
        QTabWidget::pane { border:0; border-top:1px solid @line@; }
        QTabBar::tab { background:transparent; padding:8px 10px; color:@muted@; border-bottom:2px solid transparent; }
        QTabBar::tab:selected { color:@text@; border-bottom-color:#88ab9c; }
        QHeaderView::section { background:@bg@; border:0; padding:7px; }
        QSplitter::handle { background:@line@; width:2px; }
        QScrollBar:vertical { background:transparent; width:8px; }
        QScrollBar::handle:vertical { background:@line@; border-radius:4px; min-height:25px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        QToolTip { color:@text@; background:@panel@; border:1px solid @line@; padding:6px; }
    )");
    for (const auto &entry :
         {qMakePair("@bg@", bg), qMakePair("@sidebar@", sidebar), qMakePair("@toolbar@", toolbar),
          qMakePair("@userBubble@", userBubble), qMakePair("@panel@", panel), qMakePair("@text@", text),
          qMakePair("@muted@", muted), qMakePair("@line@", line), qMakePair("@hover@", hover),
          qMakePair("@selected@", selected), qMakePair("@primary@", primary),
          qMakePair("@primaryText@", primaryText), qMakePair("@size@", QString::number(textSize))})
        css.replace(entry.first, entry.second);
    qApp->setStyleSheet(css);
}
