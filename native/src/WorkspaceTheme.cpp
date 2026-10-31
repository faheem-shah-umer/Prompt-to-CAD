#include "WorkspaceTheme.h"
#include <QApplication>
#include <QFont>
#include <QPalette>

bool lightWorkspaceTheme() { return qApp->property("workspaceTheme").toString() == "light"; }

WorkspaceColors workspaceColors(bool light) {
    if (light)
        return {QColor("#f7f8fa"), QColor("#edf0f4"), QColor("#ffffff"), QColor("#ffffff"), QColor("#dce2e9"),
                QColor("#242424"), QColor("#575757"), QColor("#868686"), QColor("#c9c9c9"), QColor("#868686"),
                QColor("#e3e3e3"), QColor("#dadada"), QColor("#ebebeb"), QColor("#81509d"), QColor("#81509d"),
                QColor("#704094"), QColor("#633685"), QColor("#5b2e7c"), QColor("#ffffff"),
                QColor("#006cab"), QColor("#00652c"), QColor("#845d00"), QColor("#9e302b")};
    return {QColor("#1d1d1d"), QColor("#151515"), QColor("#252525"), QColor("#2d2d2d"), QColor("#28313a"),
            QColor("#e9e9e9"), QColor("#ababab"), QColor("#828282"), QColor("#484848"), QColor("#808080"),
            QColor("#363636"), QColor("#3f3f3f"), QColor("#363636"), QColor("#cf96f1"), QColor("#cf96f1"),
            QColor("#bd80e1"), QColor("#cb8ef0"), QColor("#d799fc"), QColor("#151515"),
            QColor("#59c6ff"), QColor("#60c078"), QColor("#fdcf82"), QColor("#f98f83")};
}
WorkspaceColors workspaceColors() { return workspaceColors(lightWorkspaceTheme()); }

void applyWorkspaceTheme(const QString &name, int textSize) {
    qApp->setProperty("workspaceTheme", name == "light" ? "light" : "dark");
    const auto c = workspaceColors();
    QPalette p;
    for (auto group : {QPalette::Active, QPalette::Inactive, QPalette::Disabled}) {
        const bool disabled = group == QPalette::Disabled;
        p.setColor(group, QPalette::Window, c.base);
        p.setColor(group, QPalette::Base, c.raised);
        p.setColor(group, QPalette::AlternateBase, c.hover);
        p.setColor(group, QPalette::WindowText, disabled ? c.disabled : c.text);
        p.setColor(group, QPalette::Text, disabled ? c.disabled : c.text);
        p.setColor(group, QPalette::ButtonText, disabled ? c.disabled : c.text);
        p.setColor(group, QPalette::Button, c.raised);
        p.setColor(group, QPalette::Highlight, c.selected);
        p.setColor(group, QPalette::HighlightedText, disabled ? c.disabled : c.text);
        p.setColor(group, QPalette::PlaceholderText, disabled ? c.disabled : c.secondary);
        p.setColor(group, QPalette::Link, c.link);
        p.setColor(group, QPalette::LinkVisited, c.link);
        p.setColor(group, QPalette::ToolTipBase, c.overlay);
        p.setColor(group, QPalette::ToolTipText, c.text);
    }
    qApp->setPalette(p);
    QFont font("Segoe UI");
    font.setPixelSize(qMax(12, textSize));
    qApp->setFont(font);
    auto css = QString(R"(
        QWidget { color:@text@; font-family:'Segoe UI'; font-size:@size@px; }
        QMainWindow, QDialog { background:@base@; }
        QLabel { background:transparent; }
        QLabel#muted, QLabel#settingsCaption { color:@secondary@; }
        QLabel#panelTitle { font-weight:600; padding:4px 0; }
        QLabel#managerSummary { color:@secondary@; padding:12px 4px; border-top:1px solid @border@; font-size:12px; }
        QTextBrowser#selectionProperties { background:transparent; border:0; }
        QTabBar#documentTabs::tab { min-height:24px; padding:6px 12px; }
        QLabel#pageTitle { font-size:24px; font-weight:600; }
        QLabel#sectionTitle { font-size:17px; font-weight:600; }
        QMenuBar, QToolBar, QStatusBar { background:@base@; border:0; padding:4px; }
        QMenuBar::item { padding:6px 8px; border-radius:4px; }
        QMenuBar::item:selected { background:@hover@; }
        QMenuBar::item:pressed { background:@pressed@; }
        QMenu { background:@overlay@; border:1px solid @border@; padding:4px; }
        QMenu::item { padding:8px 28px 8px 12px; border-radius:4px; }
        QMenu::item:selected:enabled { background:@hover@; }
        QMenu::item:disabled { color:@disabled@; }
        QMenu::separator { height:1px; background:@border@; margin:4px 8px; }
        #navigation, #rail { background:@navigation@; }
        QWidget#rail { border-right:1px solid @border@; }
        #rail QPushButton { border:2px solid transparent; background:transparent; padding:6px 0; }
        #rail QPushButton:hover:enabled { background:@hover@; }
        #rail QPushButton:pressed:enabled { background:@pressed@; }
        #rail QPushButton:focus { border-color:@focus@; }
        #conversationPane { background:@base@; border-left:1px solid @border@; }
        #cadManager { background:@base@; border-right:1px solid @border@; }
        #documentHeader { background:@base@; border-bottom:1px solid @border@; }
        QTabWidget#commandManager, #commandManager QToolBar { background:@base@; }
        #commandManager::pane { border-bottom:1px solid @border@; }
        #navigation QPushButton { text-align:left; }
        QPushButton { padding:6px 10px; }
        QToolButton { padding:4px; }
        QPushButton, QToolButton { background:transparent; border:2px solid transparent; border-radius:@controlRadius@px; }
        QPushButton[workspaceIconOnly="true"], QToolButton[workspaceIconOnly="true"] { padding:4px; }
        QPushButton:hover:enabled, QToolButton:hover:enabled { background:@hover@; }
        QPushButton:pressed:enabled, QToolButton:pressed:enabled { background:@pressed@; }
        QPushButton:checked, QToolButton:checked { background:@selected@; }
        QPushButton:focus, QToolButton:focus { border-color:@focus@; }
        QPushButton:disabled, QToolButton:disabled { color:@disabled@; background:transparent; border-color:transparent; }
        QPushButton#primaryButton, QPushButton#connectChatGPT, QPushButton#onboardingConnect { color:@onAction@; background:@action@; font-weight:600; }
        QPushButton#primaryButton:hover:enabled, QPushButton#connectChatGPT:hover:enabled, QPushButton#onboardingConnect:hover:enabled { background:@actionHover@; }
        QPushButton#primaryButton:pressed:enabled, QPushButton#connectChatGPT:pressed:enabled, QPushButton#onboardingConnect:pressed:enabled { background:@actionPressed@; }
        QPushButton#primaryButton:disabled, QPushButton#connectChatGPT:disabled, QPushButton#onboardingConnect:disabled { color:@disabled@; background:@selected@; }
        QPushButton#commandSearchButton { padding:4px; }
        QPushButton#quietButton { color:@secondary@; }
        QPushButton#quietButton:disabled { color:@disabled@; }
        QPushButton#usageBadge { padding:4px 8px; font-size:12px; text-align:left; }
        #rail QPushButton#accountBadge { color:@text@; background:@raised@; border-radius:16px; padding:0; font-weight:600; }
        #rail QPushButton#accountBadge:hover:enabled { background:@hover@; }
        #rail QPushButton#accountBadge:pressed:enabled { background:@pressed@; }
        #rail QPushButton#accountBadge:focus { border-color:@focus@; }
        QTreeWidget, QListWidget, QTextBrowser, QPlainTextEdit, QLineEdit { background:@raised@; border:2px solid @border@; border-radius:8px; padding:6px; selection-background-color:@selected@; selection-color:@text@; }
        QTreeWidget:focus, QListWidget:focus, QPlainTextEdit:focus, QLineEdit:focus { border-color:@focus@; }
        QTreeWidget:disabled, QListWidget:disabled, QPlainTextEdit:disabled, QLineEdit:disabled { color:@disabled@; }
        QTreeWidget#modelTree, QTreeWidget#projectTree { background:transparent; border:2px solid transparent; }
        QTreeWidget#modelTree:focus, QTreeWidget#projectTree:focus { border-color:@focus@; }
        QScrollArea#conversationHistory, #chatContents { background:transparent; border:0; }
        QFrame#messageBubble { background:transparent; border:0; }
        QFrame#messageBubble[user="true"] { background:@selected@; border:0; border-radius:16px; }
        QTextBrowser#messageText { background:transparent; border:0; border-radius:0; padding:0; }
        QLabel#messageAuthor { color:@secondary@; font-size:12px; font-weight:600; }
        QToolButton#messageCopy { padding:3px; }
        QToolButton#attachImages { padding:4px; }
        QFrame#effortPopover, QFrame#accountPopover, QFrame#usagePopover, QFrame#modelPopover, QFrame#notificationCard { background:@overlay@; border:1px solid @border@; border-radius:@popupRadius@px; }
        QLabel#currentEffort { color:@link@; font-size:20px; font-weight:600; }
        QToolButton#effortModelLink { padding:4px 6px; color:@secondary@; }
        QToolButton#resetEffort { padding:4px; }
        QSlider#effortSlider { min-height:32px; }
        QSlider#effortSlider::groove:horizontal { height:8px; border-radius:4px; background:@hover@; }
        QSlider#effortSlider::sub-page:horizontal { background:@action@; border-radius:4px; }
        QSlider#effortSlider::handle:horizontal { width:20px; margin:-6px 0; border-radius:10px; background:@text@; border:2px solid transparent; }
        QSlider#effortSlider::handle:horizontal:focus { border-color:@focus@; }
        QSlider#effortSlider::sub-page:horizontal:disabled { background:@border@; }
        QSlider#effortSlider::handle:horizontal:disabled { background:@disabled@; }
        QToolButton#projectSort { padding:4px; }
        QToolButton#projectSort::menu-indicator { image:none; }
        QPushButton#showAllModels, QPushButton#hideAllModels, QPushButton#selectAllModels, QPushButton#clearModelSelection { padding:4px 6px; font-size:12px; }
        QToolButton#workDisclosure { padding:3px 0; color:@secondary@; }
        QLabel#activitySummary, QLabel#livePhase { color:@secondary@; }
        QFrame#changeCard { background:transparent; border:0; border-top:1px solid @border@; border-radius:0; padding:4px; }
        QFrame#notificationHost { background:transparent; }
        QFrame#notificationCard[severity="error"] { border-left:2px solid @danger@; }
        QFrame#notificationCard[severity="warning"] { border-left:2px solid @warning@; }
        QToolButton#latestMessage { background:@raised@; border-radius:16px; padding:4px; }
        QListWidget#modelOptions { border:2px solid transparent; padding:0; }
        QListWidget#modelOptions:focus { border-color:@focus@; }
        QListWidget#modelOptions::item { padding:8px 10px; border-radius:8px; }
        QListWidget#modelOptions::item:selected { background:@selected@; }
        QListWidget#modelOptions::item:hover { background:@hover@; }
        QLabel#modelSearchEmpty { color:@secondary@; padding:8px; }
        QFrame#composerFrame { background:@raised@; border:1px solid @border@; border-radius:12px; }
        QFrame#settingsCard { background:transparent; border:0; border-top:1px solid @border@; border-radius:0; }
        QFrame#composerFrame QPlainTextEdit { background:transparent; border:2px solid transparent; padding:4px; }
        QFrame#composerFrame QPlainTextEdit:focus { border-color:@focus@; }
        QFrame#composerFrame QComboBox { background:transparent; padding:4px; }
        QFrame#composerFrame QPushButton#primaryButton { border-radius:8px; padding:4px; }
        QListWidget#settingsNavigation { background:transparent; border:2px solid transparent; padding:0; }
        QListWidget#settingsNavigation:focus { border-color:@focus@; }
        QListWidget#settingsNavigation::item { padding:10px 12px; margin:2px 0; border-radius:8px; }
        QListWidget#settingsNavigation::item:selected { background:@selected@; color:@text@; }
        QListWidget#settingsNavigation::item:hover { background:@hover@; }
        QTreeWidget::item { padding:6px 4px; border-left:2px solid transparent; }
        QTreeWidget::item:selected { background:@selected@; color:@text@; }
        QTreeWidget::item:hover { background:@hover@; }
        QTreeWidget#modelTree::item:selected { border-left-color:@selection@; }
        QComboBox, QDoubleSpinBox { background:@raised@; border:2px solid @border@; border-radius:8px; padding:4px 6px; }
        QComboBox:focus, QDoubleSpinBox:focus { border-color:@focus@; }
        QComboBox:hover:enabled, QDoubleSpinBox:hover:enabled { background:@hover@; }
        QComboBox:disabled, QDoubleSpinBox:disabled { color:@disabled@; background:@base@; }
        QComboBox::drop-down { border:0; width:20px; }
        QComboBox QAbstractItemView { background:@overlay@; color:@text@; selection-background-color:@selected@; }
        QTabWidget::pane { border:0; border-top:1px solid @border@; }
        QTabBar::tab { background:transparent; padding:8px 10px; color:@secondary@; border-bottom:2px solid transparent; }
        QTabBar::tab:hover:enabled { background:@hover@; }
        QTabBar::tab:selected { color:@text@; border-bottom-color:@focus@; }
        QTabBar::tab:disabled { color:@disabled@; }
        QHeaderView::section { background:@base@; border:0; padding:6px; }
        QSplitter::handle { background:@base@; }
        QSplitter::handle:hover { background:@border@; }
        QSplitter::handle:pressed { background:@focus@; }
        QScrollBar:vertical { background:transparent; width:8px; }
        QScrollBar::handle:vertical { background:@border@; border-radius:4px; min-height:24px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        QToolTip { color:@text@; background:@overlay@; border:1px solid @border@; padding:6px 8px; }
    )");
    for (const auto &entry : {
             qMakePair("@base@", c.base), qMakePair("@navigation@", c.navigation),
             qMakePair("@raised@", c.raised), qMakePair("@overlay@", c.overlay),
             qMakePair("@text@", c.text), qMakePair("@secondary@", c.secondary),
             qMakePair("@disabled@", c.disabled), qMakePair("@border@", c.border),
             qMakePair("@hover@", c.hover), qMakePair("@pressed@", c.pressed),
             qMakePair("@selected@", c.selected), qMakePair("@focus@", c.focus),
             qMakePair("@link@", c.link), qMakePair("@action@", c.action),
             qMakePair("@actionHover@", c.actionHover), qMakePair("@actionPressed@", c.actionPressed),
             qMakePair("@onAction@", c.onAction), qMakePair("@selection@", c.selection),
             qMakePair("@danger@", c.danger), qMakePair("@warning@", c.warning)})
        css.replace(entry.first, entry.second.name());
    css.replace("@size@", QString::number(qMax(12, textSize)));
    css.replace("@controlRadius@", QString::number(WorkspaceMetrics::ControlRadius));
    css.replace("@popupRadius@", QString::number(WorkspaceMetrics::PopupRadius));
    qApp->setStyleSheet(css);
}
