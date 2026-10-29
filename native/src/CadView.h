#pragma once
#include <QWidget>
#include <QJsonObject>
#include <QJsonArray>
#include <QMap>
#include <AIS_InteractiveContext.hxx>
#include <AIS_Shape.hxx>
#include <V3d_View.hxx>
#include <MeshVS_Mesh.hxx>

class CadView : public QWidget {
    Q_OBJECT
public:
    explicit CadView(QWidget* parent = nullptr);
    QPaintEngine* paintEngine() const override { return nullptr; }
    void setDocument(const QJsonObject& document, bool fit = true);
    void fitAll();
    void standardView(const QString& view);
    void setSelectionMode(const QString& kind);
    void selectInstance(const QString& id);
    void isolateInstance(const QString& id);
    void showAll();
    void setShading(bool edges);
    void setLightTheme(bool light);
    void setVisibleInstance(const QString& id, bool visible);
    QJsonArray selectedEdges(const QString& instanceId) const;
    QJsonObject selection() const { return currentSelection; }
    int bodyCount() const { return shapes.size()+meshes.size(); }
    QJsonObject topologyReport() const;
    bool smokeSelectFace();
    bool saveViewport(const QString& path);
    double benchmarkOrbit();
Q_SIGNALS:
    void selectionChanged(const QJsonObject& selection);
    void viewerError(const QString& message);
protected:
    void showEvent(QShowEvent*) override;
    void paintEvent(QPaintEvent*) override;
    void resizeEvent(QResizeEvent*) override;
    void mousePressEvent(QMouseEvent*) override;
    void mouseMoveEvent(QMouseEvent*) override;
    void mouseReleaseEvent(QMouseEvent*) override;
    void wheelEvent(QWheelEvent*) override;
private:
    void initialize();
    void updateSelection();
    Handle(AIS_InteractiveContext) context;
    Handle(V3d_View) view;
    QMap<QString, Handle(AIS_Shape)> shapes;
    QMap<QString, Handle(MeshVS_Mesh)> meshes;
    QJsonObject document;
    QJsonObject currentSelection;
    QString mode = "body";
    QPoint lastPosition, pressedPosition;
    bool pendingDocument = false;
    bool lightTheme = false;
};
