#include "WorkspaceWindow.h"
#include "WorkspaceTheme.h"
#include <QApplication>
#include <QDialog>
#include <QDialogButtonBox>
#include <QJsonDocument>
#include <QLabel>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QTextBrowser>
#include <QVBoxLayout>
#include <QUrl>

namespace {
QString row(const QString &name, const QString &value) {
    return "<tr><td style='color:" + workspaceColors().secondary.name() + "'>" +
        name.toHtmlEscaped() + "</td><td>" + value.toHtmlEscaped() + "</td></tr>";
}
QString number(double value) { return QString::number(value, 'g', 8); }
}
QString WorkspaceWindow::componentName(const QString &id) const {
    for (const auto &value : document.value("components").toArray()) {
        const auto part = value.toObject();
        if (part.value("instance_id").toString() == id) return part.value("name").toString("Component");
    }
    return "Removed component";
}
void WorkspaceWindow::showSelectionProperties() {
    auto entities = selected.value("entities").toArray();
    if (entities.isEmpty() && !selected.isEmpty()) entities.append(selected);
    QStringList ids;
    for (const auto &value : entities) {
        const auto id = value.toObject().value("instance_id").toString();
        if (!id.isEmpty() && !ids.contains(id)) ids << id;
    }
    if (ids.isEmpty()) {
        properties->setHtml("<h3>Document properties</h3><p>" +
            QString::number(document.value("components").toArray().size()) +
            " components · mm</p><p>Select a component, face or edge to inspect its dimensions.</p>");
        if (modelSummary) modelSummary->setText("Select geometry to inspect dimensions.");
        return;
    }
    QString output = ids.size() == 1 ? "<h3>" + componentName(ids.first()).toHtmlEscaped() + "</h3>"
                                   : "<h3>" + QString::number(ids.size()) + " selected components</h3>";
    output += "<p>" + QString::number(entities.size()) + " selected entities · mm</p>";
    for (const auto &value : document.value("components").toArray()) {
        const auto part = value.toObject();
        if (!ids.contains(part.value("instance_id").toString())) continue;
        if (ids.size() > 1) output += "<h4>" + part.value("name").toString().toHtmlEscaped() + "</h4>";
        output += "<table cellspacing='8' width='100%'>";
        output += row("Representation", part.value("representation") == "mesh" ? "Visual mesh" : "Engineering solid");
        const auto metrics = part.value("metrics").toObject();
        const auto bounds = metrics.value("bounds_mm").toArray();
        if (bounds.size() == 2) {
            const auto low = bounds[0].toArray(), high = bounds[1].toArray();
            if (low.size() == 3 && high.size() == 3)
                for (int axis = 0; axis < 3; ++axis)
                    output += row(QStringList{"Width (X)", "Depth (Y)", "Height (Z)"}[axis],
                                  number(high[axis].toDouble() - low[axis].toDouble()) + " mm");
        }
        if (metrics.contains("volume_mm3")) output += row("Volume", number(metrics.value("volume_mm3").toDouble()) + " mm³");
        if (metrics.contains("solid_count")) output += row("Solid count", QString::number(metrics.value("solid_count").toInt()));
        const auto matrix = part.value("matrix").toArray();
        if (matrix.size() == 12)
            output += row("World position", "X " + number(matrix[3].toDouble()) + " · Y " +
                number(matrix[7].toDouble()) + " · Z " + number(matrix[11].toDouble()) + " mm");
        output += "</table>";
        const auto parameters = part.value("parameters").toObject();
        if (!parameters.isEmpty()) {
            output += "<h4>Named parameters</h4><table cellspacing='8' width='100%'>";
            for (auto it = parameters.begin(); it != parameters.end(); ++it)
                output += row(it.key(), it.value().isDouble() ? number(it.value().toDouble()) : it.value().toVariant().toString());
            output += "</table><p>Values use the editable definition's units.</p>";
            if (ids.size() == 1) output += "<p><a href='parameters:edit'>Edit named parameters</a></p>";
        } else output += "<p>Original feature history is not available.</p>";
    }
    output += engineeringHtml(ids);
    output += "<p><a href='diagnostic:selection'>Technical diagnostics</a></p>";
    properties->setHtml(output);
    if (modelSummary) modelSummary->setText(ids.size() == 1 ? componentName(ids.first()) + "\n" +
        entities.first().toObject().value("kind").toString() + " · mm\nDimensions and colour in Properties"
        : QString::number(ids.size()) + " components selected\n" + QString::number(entities.size()) + " entities · mm");
}
void WorkspaceWindow::showDiagnostic(const QString &headingText, const QJsonObject &diagnostic) {
    if (focusOpenDialog()) return;
    auto *dialog = new QDialog(this);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowTitle(headingText);
    auto *layout = new QVBoxLayout(dialog);
    auto *heading = new QLabel(headingText); heading->setObjectName("sectionTitle"); layout->addWidget(heading);
    if (diagnostic.contains("first_name")) {
        auto *parts = new QLabel(diagnostic.value("first_name").toString() + " ↔ " + diagnostic.value("second_name").toString());
        parts->setWordWrap(true); layout->addWidget(parts);
    }
    if (diagnostic.contains("minimum_distance_mm")) {
        auto *measurement = new QLabel("Minimum distance: " + number(diagnostic.value("minimum_distance_mm").toDouble()) + " mm");
        measurement->setWordWrap(true); layout->addWidget(measurement);
    }
    auto *toggle = new QPushButton("Show technical data");
    toggle->setCheckable(true); layout->addWidget(toggle);
    auto *raw = new QPlainTextEdit(QJsonDocument(diagnostic).toJson(QJsonDocument::Indented));
    raw->setReadOnly(true); raw->setAccessibleName("Technical JSON data");
    raw->setVisible(false); layout->addWidget(raw, 1);
    connect(toggle, &QPushButton::toggled, raw, &QWidget::setVisible);
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Close); layout->addWidget(buttons);
    connect(buttons, &QDialogButtonBox::rejected, dialog, &QDialog::reject);
    dialog->resize(620, 420); dialog->show();
}
