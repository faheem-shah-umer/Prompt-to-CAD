#pragma once
#include <QColor>
#include <QString>

// Native mapping of the approved OpenDesigner roles; see docs/ui-design-system.md.
struct WorkspaceColors {
    QColor base, navigation, raised, overlay, canvas;
    QColor text, secondary, disabled, border, strongBorder;
    QColor hover, pressed, selected, focus, link;
    QColor action, actionHover, actionPressed, onAction;
    QColor selection, success, warning, danger;
};
WorkspaceColors workspaceColors(bool light);
WorkspaceColors workspaceColors();
namespace WorkspaceMetrics {
inline constexpr int ControlRadius = 8;
inline constexpr int PopupRadius = 12;
inline constexpr int Icon = 16;
inline constexpr int CompactControl = 32;
inline constexpr int Target = 44;
inline constexpr int PopupGap = 8;
}
void applyWorkspaceTheme(const QString &name, int textSize = 14);
bool lightWorkspaceTheme();
