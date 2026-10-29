#include "WorkspaceTheme.h"
#include <QApplication>
#include <QFont>
#include <QPalette>

bool lightWorkspaceTheme() { return qApp->property("workspaceTheme").toString() == "light"; }

void applyWorkspaceTheme(const QString &name, int textSize) {
    const bool light = name == "light";
    qApp->setProperty("workspaceTheme", light ? "light" : "dark");
    const QString bg = light ? "#f7f7f8" : "#1b1b1d";
    const QString panel = light ? "#ffffff" : "#222224";
    const QString text = light ? "#242428" : "#ececee";
    const QString muted = light ? "#67676f" : "#a1a1aa";
    const QString line = light ? "#dedee3" : "#38383c";
    const QString hover = light ? "#ededf0" : "#303033";
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
        #navigation, #conversationPane { background:@bg@; }
        #navigation QPushButton { text-align:left; }
        QPushButton, QToolButton { background:transparent; border:1px solid @line@; border-radius:7px; padding:7px 12px; }
        QPushButton:hover, QToolButton:hover { background:@hover@; }
        QPushButton:disabled { color:@muted@; border-color:@line@; }
        QPushButton#primaryButton { color:@primaryText@; background:@primary@; border-color:@primary@; font-weight:600; }
        QPushButton#primaryButton:disabled { color:@muted@; background:@hover@; border-color:@line@; }
        QPushButton#quietButton { border:0; color:@muted@; }
        QPushButton#usageBadge { border:1px solid @line@; padding:4px 9px; font-size:11px; text-align:left; }
        QPushButton#accountBadge { border:0; color:@muted@; padding:8px 2px; }
        QTreeWidget, QListWidget, QTextBrowser, QPlainTextEdit, QLineEdit { background:@panel@; border:1px solid @line@; border-radius:7px; padding:7px; selection-background-color:@selected@; }
        QTextBrowser#conversationHistory { background:transparent; border:0; padding:4px 0; }
        QFrame#composerFrame, QFrame#taskCard, QFrame#settingsCard { background:@panel@; border:1px solid @line@; border-radius:10px; }
        QFrame#composerFrame QPlainTextEdit { background:transparent; border:0; padding:4px; }
        QFrame#composerFrame QComboBox { background:transparent; border:0; padding:4px; }
        QFrame#composerFrame QPushButton#primaryButton { border-radius:15px; padding:0; font-size:17px; }
        QLabel#taskTitle { font-weight:600; }
        QLabel#taskActivity { color:@muted@; }
        QProgressBar#taskProgress { border:0; border-radius:2px; background:@hover@; max-height:3px; }
        QProgressBar#taskProgress::chunk { background:#82a995; border-radius:2px; }
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
         {qMakePair("@bg@", bg), qMakePair("@panel@", panel), qMakePair("@text@", text),
          qMakePair("@muted@", muted), qMakePair("@line@", line), qMakePair("@hover@", hover),
          qMakePair("@selected@", selected), qMakePair("@primary@", primary),
          qMakePair("@primaryText@", primaryText), qMakePair("@size@", QString::number(textSize))})
        css.replace(entry.first, entry.second);
    qApp->setStyleSheet(css);
}
