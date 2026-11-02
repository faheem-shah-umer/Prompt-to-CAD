#include "CadView.h"
#include <QApplication>
#include <QFile>
#include <QJsonDocument>
#include <QTimer>
#include <cstdio>

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    if (argc != 3) return 2;
    QFile file(QString::fromLocal8Bit(argv[1]));
    if (!file.open(QIODevice::ReadOnly)) return 3;
    const auto document = QJsonDocument::fromJson(file.readAll()).object();
    const auto parts = document.value("components").toArray();
    if (parts.size() != 1 || parts.first().toObject().value("metrics").toObject().value("solid_count").toInt() < 2) return 4;
    const auto id = parts.first().toObject().value("instance_id").toString();
    CadView view;
    view.resize(1000, 700);
    QObject::connect(&view, &CadView::viewerError, &app, [&](const QString &message) {
        std::fprintf(stderr, "%s\n", message.toUtf8().constData()); app.exit(5);
    });
    view.show();
    view.setDocument(document);
    QTimer::singleShot(1500, &app, [&] {
        if (view.bodyCount() != 1 || !view.smokeSelectFace() || view.selection().value("instance_id").toString() != id) {
            app.exit(6); return;
        }
        view.setSelectionMode("body");
        view.selectInstance(id);
        const auto selection = view.selection();
        if (selection.value("instance_id").toString() != id || selection.value("entities").toArray().size() != 1 || !view.saveViewport(QString::fromLocal8Bit(argv[2]))) {
            app.exit(7); return;
        }
        std::puts("One logical component: native rendering, face selection and whole-body selection passed.");
        app.exit(0);
    });
    QTimer::singleShot(30000, &app, [&] { app.exit(8); });
    return app.exec();
}
