#include "WorkspaceWindow.h"
#include <QBuffer>
#include <QCryptographicHash>
#include <QComboBox>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QImage>
#include <QImageReader>
#include <QLabel>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QPixmap>
#include <QScrollArea>
#include <QSaveFile>
#include <QToolButton>
#include <QVBoxLayout>
#include "WorkspaceIcons.h"

namespace {
constexpr qint64 imageBytes = 20LL * 1024 * 1024;
constexpr qint64 totalBytes = 50LL * 1024 * 1024;
}

void WorkspaceWindow::addImageFiles(const QStringList &paths) {
    if (imagePreflight) { notify("Wait for image preparation to finish.", "info"); return; }
    if (state.value("conversation").toObject().isEmpty()) { notify("Open a conversation before attaching images.", "info"); return; }
    for (const auto& path : paths) {
        QFile source(path);
        if (!source.open(QIODevice::ReadOnly) || source.size() > imageBytes) { notify("Choose images of at most 20 MB each.", "info"); continue; }
        const auto data = source.readAll();
        if (data.isEmpty() || data.size() > imageBytes) { notify("The image is empty or exceeds 20 MB.", "info"); continue; }
        QBuffer buffer; buffer.setData(data); buffer.open(QIODevice::ReadOnly);
        QImageReader reader(&buffer);
        const auto kind = reader.format().toLower();
        if (kind != "png" && kind != "jpeg" && kind != "jpg" && kind != "webp") { notify("Use PNG, JPEG or WebP images.", "info"); continue; }
        const auto dimensions = reader.size();
        if (!dimensions.isValid() || qint64(dimensions.width()) * dimensions.height() > 40000000) { notify("Images are limited to 40 million decoded pixels.", "info"); continue; }
        reader.setScaledSize(dimensions.scaled(160, 100, Qt::KeepAspectRatio));
        if (reader.read().isNull()) { notify("The reference image could not be decoded.", "info"); continue; }
        const auto digest = QString::fromLatin1(QCryptographicHash::hash(data, QCryptographicHash::Sha256).toHex());
        const auto directory = workspace + "/.promptcad/draft-images";
        if (!QDir().mkpath(directory)) { notify("Could not create the local image draft folder."); return; }
        const auto saved = directory + "/" + digest + (kind == "jpeg" ? ".jpg" : "." + QString::fromLatin1(kind));
        if (!QFileInfo::exists(saved)) {
            QSaveFile file(saved);
            if (!file.open(QIODevice::WriteOnly) || file.write(data) != data.size() || !file.commit()) { notify("Could not preserve the reference image."); continue; }
        }
        addReferenceAttachment({{"asset_id", digest}, {"sha256", digest}, {"local_path", saved},
            {"name", QFileInfo(path).fileName()}, {"type", "image"}, {"available", true},
            {"size_bytes", qint64(data.size())}, {"width", dimensions.width()}, {"height", dimensions.height()}});
    }
}

void WorkspaceWindow::addPastedImage(const QImage &image) {
    if (imagePreflight || image.isNull()) return;
    if (qint64(image.width()) * image.height() > 40000000) { notify("Images are limited to 40 million decoded pixels.", "info"); return; }
    QByteArray bytes; QBuffer buffer(&bytes); buffer.open(QIODevice::WriteOnly);
    if (!image.save(&buffer, "PNG") || bytes.size() > imageBytes) { notify("The pasted image exceeds the 20 MB image limit.", "info"); return; }
    const auto directory = workspace + "/.promptcad/draft-images";
    if (!QDir().mkpath(directory)) { notify("Could not preserve the pasted image."); return; }
    const auto digest = QString::fromLatin1(QCryptographicHash::hash(bytes, QCryptographicHash::Sha256).toHex());
    const auto path = directory + "/" + digest + ".png";
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size() || !file.commit()) { notify("Could not preserve the pasted image."); return; }
    addReferenceAttachment({{"asset_id", digest}, {"sha256", digest}, {"local_path", path}, {"name", "Pasted image.png"},
                           {"type", "image"}, {"available", true}, {"size_bytes", qint64(bytes.size())}, {"width", image.width()}, {"height", image.height()}});
}

void WorkspaceWindow::addReferenceAttachment(const QJsonObject &reference) {
    if (imagePreflight) return;
    if (state.value("conversation").toObject().isEmpty()) { notify("Open a conversation before attaching images.", "info"); return; }
    qint64 total = reference.value("size_bytes").toInteger();
    for (const auto& value : draftAttachments) {
        auto entry = value.toObject();
        if (entry.value("sha256") == reference.value("sha256")) return;
        total += entry.value("size_bytes").toInteger();
    }
    if (draftAttachments.size() >= 8 || total > totalBytes) { notify("Attach at most eight images and 50 MB combined.", "info"); return; }
    if (!reference.value("available").toBool() || reference.value("local_path").toString().isEmpty()) { notify("This reference image is unavailable.", "info"); return; }
    draftAttachments.append(reference); renderAttachmentDraft(); updateSendControl();
}

void WorkspaceWindow::changeAttachmentContext() {
    const auto context = state.value("project").toObject().value("project_id").toString() + "/" +
                         state.value("conversation").toObject().value("conversation_id").toString();
    if (context == attachmentContext) return;
    attachmentDrafts[attachmentContext] = draftAttachments;
    attachmentContext = context; draftAttachments = attachmentDrafts.value(context);
    renderAttachmentDraft();
}

void WorkspaceWindow::renderAttachmentDraft() {
    if (!attachmentStrip) return;
    auto *layout = attachmentStrip->layout();
    while (auto *item = layout->takeAt(0)) { delete item->widget(); delete item; }
    for (int i=0;i<draftAttachments.size();++i) {
        const auto reference = draftAttachments[i].toObject();
        auto *row = new QWidget; auto *line = new QHBoxLayout(row); line->setContentsMargins(0, 0, 0, 0);
        auto *preview = new QLabel;
        QImageReader reader(reference.value("local_path").toString()); reader.setScaledSize(reader.size().scaled(72, 44, Qt::KeepAspectRatio));
        preview->setPixmap(QPixmap::fromImage(reader.read())); line->addWidget(preview);
        auto *name = new QLabel(reference.value("name").toString()); name->setTextFormat(Qt::PlainText); name->setWordWrap(true); line->addWidget(name, 1);
        auto *remove = new QToolButton; setWorkspaceIcon(remove, "cross");
        remove->setToolTip("Remove image from this draft"); remove->setAccessibleName("Remove " + reference.value("name").toString());
        remove->setEnabled(!imagePreflight);
        connect(remove, &QToolButton::clicked, this, [this, i] { draftAttachments.removeAt(i); renderAttachmentDraft(); updateSendControl(); });
        line->addWidget(remove); layout->addWidget(row);
    }
    if (!failedAttachmentDrafts.value(attachmentContext).isEmpty()) {
        auto *restore = new QPushButton("Restore images from failed request");
        connect(restore, &QPushButton::clicked, this, [this] {
            auto pending = failedAttachmentDrafts.take(attachmentContext);
            for (auto value : pending) {
                const auto image = value.toObject(); addReferenceAttachment(image);
                bool added = false; for (auto active : draftAttachments) added |= active.toObject().value("sha256") == image.value("sha256");
                if (!added) failedAttachmentDrafts[attachmentContext].append(image);
            }
            renderAttachmentDraft();
        });
        restore->setEnabled(!imagePreflight); layout->addWidget(restore);
    }
    attachmentStrip->setVisible(layout->count() > 0);
    if (auto *scroll = findChild<QScrollArea*>("attachmentDraftScroll")) scroll->setVisible(layout->count() > 0);
}

void WorkspaceWindow::prepareImageSubmission(QJsonObject params) {
    imagePreflight = true; busy = true; composer->setEnabled(false); models->setEnabled(false);
    renderAttachmentDraft(); updateSendControl(); refreshConnectionControls();
    const auto inputs = draftAttachments;
    rpc->call("provider.image_support", {{"model", params.value("model")}}, [this, inputs, params](auto, auto error) {
        if (!error.isEmpty()) { finishImagePreflight(); notify(error); return; }
        stageNextAttachment(0, inputs, {}, params);
    });
}

void WorkspaceWindow::finishImagePreflight() {
    imagePreflight = false; busy = false; composer->setEnabled(true); models->setEnabled(true);
    renderAttachmentDraft(); updateSendControl(); refreshConnectionControls();
}

void WorkspaceWindow::stageNextAttachment(int index, QJsonArray inputs, QJsonArray prepared, QJsonObject params) {
    if (index >= inputs.size()) {
        params["attachments"] = prepared;
        submittedDraftAttachments = inputs; submittedAttachments = prepared;
        finishImagePreflight(); startAgentTask(params); return;
    }
    const auto source = inputs[index].toObject();
    rpc->call("v2.attachment.add", {{"path", source.value("local_path")}}, [this, index, inputs, prepared, params, source](auto result, auto error) mutable {
        if (!error.isEmpty()) { finishImagePreflight(); notify(error); return; }
        auto reference = result.value("attachment").toObject(); reference["name"] = source.value("name");
        if (reference.value("sha256") != source.value("sha256")) { finishImagePreflight(); notify("A reference image changed before submission. Reattach it."); return; }
        prepared.append(reference); stageNextAttachment(index + 1, inputs, prepared, params);
    });
}

void WorkspaceWindow::restoreSubmittedAttachments() {
    if (submittedDraftAttachments.isEmpty()) return;
    if (draftAttachments.isEmpty()) draftAttachments = submittedDraftAttachments;
    else for (auto image : submittedDraftAttachments) failedAttachmentDrafts[attachmentContext].append(image);
    submittedDraftAttachments = {}; submittedAttachments = {};
    renderAttachmentDraft(); updateSendControl();
}
