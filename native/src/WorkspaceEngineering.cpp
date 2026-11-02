#include "WorkspaceWindow.h"
#include <QColorDialog>
#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QUrl>
#include <QVBoxLayout>

namespace {
QDoubleSpinBox *valueField(double value = 0) {
    auto *field = new QDoubleSpinBox;
    field->setRange(-1e9, 1e9); field->setDecimals(6); field->setValue(value);
    return field;
}
}

void WorkspaceWindow::chooseComponentColour(bool sourceColors) {
    if (busy || focusOpenDialog()) return;
    auto entities = selected.value("entities").toArray();
    if (entities.isEmpty() && !selected.isEmpty()) entities.append(selected);
    QStringList ids;
    for (const auto& value : entities) {
        const auto entry = value.toObject();
        if (entry.value("kind").toString() != "body") {
            notify("Select whole components to change their component colours.", "info"); return;
        }
        const auto id = entry.value("instance_id").toString();
        if (!ids.contains(id)) ids << id;
    }
    if (ids.isEmpty()) { notify("Select one or more components first.", "info"); return; }
    auto params = base(); params["selection"] = selected;
    QJsonArray identities; for (const auto& id : ids) identities.append(id);
    params["instance_ids"] = identities;
    if (sourceColors) {
        QJsonArray meshes;
        for (const auto& value : document.value("components").toArray()) {
            auto part = value.toObject();
            if (part.value("representation") == "mesh" && ids.contains(part.value("instance_id").toString())) meshes.append(part.value("instance_id"));
        }
        if (meshes.isEmpty()) { notify("Select imported mesh components to restore their source colours.", "info"); return; }
        params["instance_ids"] = meshes; params["source_colors"] = true;
    }
    else {
        QColor initial(140, 184, 230);
        for (const auto& value : document.value("components").toArray()) {
            auto part = value.toObject();
            if (part.value("instance_id").toString() == ids.first()) {
                auto rgb = part.value("color").toArray();
                if (rgb.size() == 3) initial = QColor::fromRgbF(rgb[0].toDouble(), rgb[1].toDouble(), rgb[2].toDouble());
                break;
            }
        }
        const auto color = QColorDialog::getColor(initial, this, ids.size() == 1 ? "Component colour" : "Selected component colours");
        if (!color.isValid()) return;
        params["color"] = QJsonArray{color.redF(), color.greenF(), color.blueF()};
    }
    call("v2.appearance", params);
}

QString WorkspaceWindow::engineeringHtml(const QStringList &ids) const {
    if (ids.isEmpty() && document.value("engineering").toArray().isEmpty()) return {};
    QString output;
    if (!ids.isEmpty()) output = "<h4>Appearance</h4><p><a href=\"appearance:colour\">Change component colour</a></p>";
    bool mesh = false;
    for (const auto& value : document.value("components").toArray()) {
        const auto part = value.toObject();
        if (!ids.contains(part.value("instance_id").toString())) continue;
        const auto rgb = part.value("color_override").isArray() ? part.value("color_override").toArray() : part.value("color").toArray();
        if (rgb.size() == 3) output += "<p>" + part.value("name").toString().toHtmlEscaped() + " · " +
            QColor::fromRgbF(rgb[0].toDouble(), rgb[1].toDouble(), rgb[2].toDouble()).name().toHtmlEscaped() + "</p>";
        mesh |= part.value("representation") == "mesh";
    }
    if (mesh) output += "<p><a href=\"appearance:source\">Use source mesh colours</a></p>";
    output += "<h4>Engineering information</h4>";
    if (!ids.isEmpty()) output += "<p><a href=\"engineering:new\">Add dimension, label or note</a></p>";
    for (const auto& value : document.value("engineering").toArray()) {
        const auto record = value.toObject();
        if (!ids.isEmpty() && !ids.contains(record.value("instance_id").toString())) continue;
        if (ids.isEmpty()) output += "<p><b>" + componentName(record.value("instance_id").toString()).toHtmlEscaped() + "</b></p>";
        output += "<p><a href=\"engineering:" + QString::fromLatin1(QUrl::toPercentEncoding(record.value("id").toString())) + "\">" +
            record.value("kind").toString().toHtmlEscaped() + "</a> · " + record.value("text").toString().toHtmlEscaped().replace("\n", "<br>");
        if (record.value("kind") == "dimension") {
            output += "<br>" + QString::number(record.value("nominal").toDouble(), 'g', 10) + " " + record.value("units").toString("mm").toHtmlEscaped() + " · " +
                record.value("verification").toString().replace('_', ' ').toHtmlEscaped();
            const auto tolerance = record.value("tolerance").toObject();
            if (tolerance.value("mode") == "plus_minus")
                output += "<br>+" + QString::number(tolerance.value("plus").toDouble()) + " / −" + QString::number(tolerance.value("minus").toDouble()) + " " + record.value("units").toString("mm").toHtmlEscaped();
            else if (tolerance.value("mode") == "limits")
                output += "<br>Limits: " + QString::number(tolerance.value("lower").toDouble()) + " to " + QString::number(tolerance.value("upper").toDouble()) + " " + record.value("units").toString("mm").toHtmlEscaped();
            if (record.contains("within_limits") && !record.value("within_limits").toBool()) output += "<br><b>Current nominal is outside the recorded limits.</b>";
        }
        if (record.value("status") == "stale") output += "<br><b>Stale anchor — select fresh geometry to reanchor.</b>";
        output += record.value("viewport_visible").toBool(false) ? "<br>Shown in viewport" : "<br>Hidden in viewport";
        output += "</p>";
    }
    return output;
}

void WorkspaceWindow::editEngineeringRecord(const QString &identity) {
    if (busy || focusOpenDialog()) return;
    QJsonObject existing;
    if (!identity.isEmpty()) for (const auto& value : document.value("engineering").toArray())
        if (value.toObject().value("id").toString() == identity) { existing = value.toObject(); break; }
    const auto entities = selected.value("entities").toArray();
    if (existing.isEmpty() && (selected.isEmpty() || entities.size() > 1)) {
        notify("Select one component or entity to annotate.", "info"); return;
    }
    const auto target = existing.isEmpty() ? selected.value("instance_id").toString() : existing.value("instance_id").toString();
    QJsonObject part;
    for (const auto& value : document.value("components").toArray())
        if (value.toObject().value("instance_id").toString() == target) { part = value.toObject(); break; }
    if (part.isEmpty()) { notify("The annotation's component is no longer present.", "info"); return; }
    auto *dialog = new QDialog(this);
    dialog->setAttribute(Qt::WA_DeleteOnClose); dialog->setWindowModality(Qt::WindowModal);
    dialog->setObjectName("engineeringEditor"); dialog->setWindowTitle(existing.isEmpty() ? "Engineering information" : "Edit engineering information");
    dialog->resize(510, 460);
    auto *layout = new QVBoxLayout(dialog);
    auto *caption = new QLabel("Dimensions and tolerances here are metadata. Use modelling tools or named parameters to resize geometry.");
    caption->setWordWrap(true); layout->addWidget(caption);
    auto *ownerLabel = new QLabel(part.value("name").toString()); ownerLabel->setTextFormat(Qt::PlainText);
    layout->addWidget(ownerLabel);
    auto *form = new QFormLayout;
    auto *kind = new QComboBox; kind->addItems({"note", "label", "dimension"});
    kind->setCurrentText(existing.value("kind").toString("note")); form->addRow("Type", kind);
    auto *text = new QLineEdit(existing.value("text").toString()); text->setMaxLength(2000); form->addRow("Text", text);
    auto *viewportVisible = new QCheckBox("Show in viewport");
    viewportVisible->setObjectName("annotationViewportVisible");
    viewportVisible->setChecked(existing.value("viewport_visible").toBool(false));
    form->addRow("Display", viewportVisible);
    auto *anchors = new QComboBox;
    bool bodyScope = (!existing.isEmpty() && selected.isEmpty()) ||
        (selected.value("instance_id").toString() == target && selected.value("kind") == "body");
    for (const auto& value : entities) {
        const auto entry = value.toObject();
        bodyScope |= entry.value("instance_id").toString() == target && entry.value("kind") == "body";
    }
    if (bodyScope) anchors->addItem("Component", QJsonObject{{"kind", "body"}});
    if (selected.value("instance_id").toString() == target && selected.value("kind").toString() != "body") {
        anchors->addItem("Selected " + selected.value("kind").toString() + " " + QString::number(selected.value("index").toInt()),
                         QJsonObject{{"kind", selected.value("kind")}, {"index", selected.value("index")}});
        anchors->setCurrentIndex(anchors->count()-1);
    } else if (bodyScope && !existing.isEmpty() && existing.value("status") != "stale" && existing.value("anchor").toObject().value("kind") != "body") {
        anchors->addItem("Existing entity anchor", existing.value("anchor").toObject()); anchors->setCurrentIndex(anchors->count()-1);
    }
    if (!anchors->count()) { dialog->deleteLater(); notify("Select this record's current component or entity before editing it.", "info"); return; }
    form->addRow("Anchor", anchors);
    auto *parameter = new QComboBox; parameter->addItem("Declared value (unverified)", "");
    const auto parameters = part.value("parameters").toObject();
    for (auto it=parameters.begin();it!=parameters.end();++it) parameter->addItem(it.key(), it.key());
    parameter->setCurrentIndex(qMax(0, parameter->findData(existing.value("parameter").toString())));
    if (existing.contains("measurement") && existing.value("status") != "stale") {
        parameter->addItem("Measured entity distance", ""); parameter->setItemData(parameter->count()-1, true, Qt::UserRole+1);
        parameter->setCurrentIndex(parameter->count()-1);
    }
    form->addRow("Dimension binding", parameter);
    auto *units = new QComboBox; units->addItems({"mm", "deg", "unitless"}); units->setCurrentText(existing.value("units").toString("mm"));
    form->addRow("Dimension units", units);
    auto *nominal = valueField(existing.value("nominal").toDouble()); form->addRow("Nominal", nominal);
    auto *mode = new QComboBox; mode->addItem("None", "none"); mode->addItem("Plus / minus", "plus_minus"); mode->addItem("Limits", "limits");
    const auto tolerance = existing.value("tolerance").toObject(); mode->setCurrentIndex(qMax(0, mode->findData(tolerance.value("mode").toString())));
    form->addRow("Tolerance", mode);
    auto *first = valueField(), *second = valueField();
    first->setValue(tolerance.value(mode->currentData() == "limits" ? "lower" : "minus").toDouble());
    second->setValue(tolerance.value(mode->currentData() == "limits" ? "upper" : "plus").toDouble());
    auto *firstLabel = new QLabel, *secondLabel = new QLabel;
    form->addRow(firstLabel, first); form->addRow(secondLabel, second);
    auto updateFields = [=] {
        const bool dimension = kind->currentText() == "dimension";
        const bool measured = parameter->itemData(parameter->currentIndex(), Qt::UserRole+1).toBool();
        parameter->setEnabled(dimension); mode->setEnabled(dimension); units->setEnabled(dimension && !measured);
        nominal->setEnabled(dimension && !measured && parameter->currentData().toString().isEmpty());
        if (measured) { nominal->setValue(existing.value("nominal").toDouble()); units->setCurrentText("mm"); }
        if (!parameter->currentData().toString().isEmpty()) nominal->setValue(parameters.value(parameter->currentData().toString()).toDouble());
        const bool limits = mode->currentData() == "limits";
        firstLabel->setText(limits ? "Lower" : "Minus"); secondLabel->setText(limits ? "Upper" : "Plus");
        first->setMinimum(limits ? -1e9 : 0); second->setMinimum(limits ? -1e9 : 0);
        first->setEnabled(dimension && mode->currentData() != "none"); second->setEnabled(first->isEnabled());
    };
    connect(kind, &QComboBox::currentTextChanged, dialog, [=] { updateFields(); });
    connect(parameter, &QComboBox::currentIndexChanged, dialog, [=] { updateFields(); });
    connect(mode, &QComboBox::currentIndexChanged, dialog, [=] { updateFields(); }); updateFields();
    layout->addLayout(form);
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Save | QDialogButtonBox::Cancel);
    layout->addWidget(buttons); connect(buttons, &QDialogButtonBox::rejected, dialog, &QDialog::reject);
    const auto frozen = selected;
    connect(buttons, &QDialogButtonBox::accepted, dialog, [=, this] {
        if (kind->currentText() != "dimension" && text->text().trimmed().isEmpty()) { notify("Enter text for the label or note.", "info"); return; }
        QJsonObject record{{"instance_id", target}, {"kind", kind->currentText()}, {"text", text->text()},
            {"viewport_visible", viewportVisible->isChecked()}, {"anchor", anchors->currentData().toJsonObject()}};
        if (!identity.isEmpty()) record["id"] = identity;
        if (kind->currentText() == "dimension") {
            record["units"] = units->currentText();
            record["nominal"] = nominal->value();
            if (!parameter->currentData().toString().isEmpty()) record["parameter"] = parameter->currentData().toString();
            else if (parameter->itemData(parameter->currentIndex(), Qt::UserRole+1).toBool()) record["measurement"] = existing.value("measurement");
            if (mode->currentData() == "plus_minus") record["tolerance"] = QJsonObject{{"mode", "plus_minus"}, {"minus", first->value()}, {"plus", second->value()}};
            else if (mode->currentData() == "limits") {
                if (first->value() > second->value()) { notify("The lower tolerance limit exceeds the upper limit.", "info"); return; }
                record["tolerance"] = QJsonObject{{"mode", "limits"}, {"lower", first->value()}, {"upper", second->value()}};
            }
        }
        auto params = base(); params["selection"] = frozen; params["record"] = record;
        dialog->accept(); call("v2.engineering", params);
    });
    if (!existing.isEmpty()) {
        auto *remove = buttons->addButton("Remove", QDialogButtonBox::DestructiveRole);
        connect(remove, &QPushButton::clicked, dialog, [=, this] {
            auto params = base(); params["selection"] = frozen; params["action"] = "remove"; params["record"] = existing;
            dialog->accept(); call("v2.engineering", params);
        });
    }
    dialog->show();
}
