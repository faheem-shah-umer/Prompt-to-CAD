#include "CadView.h"
#include "MeshSource.h"
#include <QJsonDocument>
#include <MeshVS_SelectionModeFlags.hxx>
#include <MeshVS_DisplayModeFlags.hxx>
#include <MeshVS_MeshEntityOwner.hxx>
#include <QMouseEvent>
#include <QWheelEvent>
#include <QDir>
#include <QFileInfo>
#include <QCryptographicHash>
#include <QFile>
#include <cmath>
#include <stdexcept>
#include <Aspect_DisplayConnection.hxx>
#include <OpenGl_GraphicDriver.hxx>
#include <BRep_Builder.hxx>
#include <BRepTools.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <QCoreApplication>
#include <QElapsedTimer>
#include <WNT_Window.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopExp.hxx>
#include <StdSelect_BRepOwner.hxx>
#include <AIS_SelectionScheme.hxx>
#include <Graphic3d_NameOfMaterial.hxx>
#include <V3d_Viewer.hxx>
#include <gp_Trsf.hxx>
#include <Standard_Failure.hxx>

namespace {
TopAbs_ShapeEnum topologyKind(const QString& kind) {
    if (kind == "face") return TopAbs_FACE;
    if (kind == "edge") return TopAbs_EDGE;
    return TopAbs_VERTEX;
}
QString shapeKind(TopAbs_ShapeEnum type) {
    if (type == TopAbs_FACE) return "face";
    if (type == TopAbs_EDGE) return "edge";
    if (type == TopAbs_VERTEX) return "vertex";
    return "body";
}
}
CadView::CadView(QWidget* parent) : QWidget(parent) {
    setAttribute(Qt::WA_PaintOnScreen);
    setAttribute(Qt::WA_NoSystemBackground);
    setAttribute(Qt::WA_NativeWindow);
    setMouseTracking(true);
    setFocusPolicy(Qt::StrongFocus);
    setMinimumSize(400, 300);
}
void CadView::initialize() {
    if (!view.IsNull()) return;
    Handle(Aspect_DisplayConnection) display = new Aspect_DisplayConnection();
    Handle(OpenGl_GraphicDriver) driver = new OpenGl_GraphicDriver(display);
    Handle(V3d_Viewer) viewer = new V3d_Viewer(driver);
    viewer->SetDefaultLights();
    viewer->SetLightOn();
    context = new AIS_InteractiveContext(viewer);
    context->DefaultDrawer()->SetFaceBoundaryDraw(true);
    view = viewer->CreateView();
    Handle(WNT_Window) window = new WNT_Window(reinterpret_cast<Aspect_Handle>(winId()));
    view->SetWindow(window);
    if (!window->IsMapped()) window->Map();
    view->SetBgGradientColors(Quantity_Color(0.105, 0.125, 0.16, Quantity_TOC_RGB),
                              Quantity_Color(0.055, 0.065, 0.085, Quantity_TOC_RGB), Aspect_GFM_VER, false);
    view->TriedronDisplay(Aspect_TOTP_LEFT_LOWER, Quantity_NOC_GRAY80, 0.08, V3d_ZBUFFER);
    view->SetProj(V3d_XposYnegZpos);
    view->MustBeResized();
}
void CadView::showEvent(QShowEvent*) {
    try { initialize(); if (pendingDocument) setDocument(document); }
    catch (const Standard_Failure& error) { Q_EMIT viewerError(QString::fromUtf8(error.GetMessageString())); }
}
void CadView::paintEvent(QPaintEvent*) { if (!view.IsNull()) view->Redraw(); }
void CadView::resizeEvent(QResizeEvent*) { if (!view.IsNull()) view->MustBeResized(); }

void CadView::setDocument(const QJsonObject& incoming, bool fit) {
    document = incoming;
    if (view.IsNull()) { pendingDocument = true; return; }
    pendingDocument = false;
    try {
        QMap<QString, Handle(AIS_Shape)> next;
        QMap<QString, Handle(MeshVS_Mesh)> nextMeshes;
        for (const auto& item : document.value("components").toArray()) {
            const auto part = item.toObject();
            const auto id = part.value("instance_id").toString();
            const auto projectDir = QFileInfo(document.value("project_dir").toString()).canonicalFilePath();
            const auto filename = QFileInfo(QDir(projectDir).filePath(part.value(part.value("representation")=="mesh"?"mesh":"brep").toString())).canonicalFilePath();
            if (filename.isEmpty() || !filename.startsWith(projectDir + '/'))
                throw std::runtime_error("The project contains an invalid body asset path.");
            QFile file(filename);
            if (!file.open(QIODevice::ReadOnly) || QString::fromLatin1(QCryptographicHash::hash(
                    file.readAll(), QCryptographicHash::Sha256).toHex()) != part.value("asset_hash").toString())
                throw std::runtime_error("The geometry asset checksum does not match.");
            if(part.value("representation")=="mesh") {
                file.seek(0);if(file.size()>100*1024*1024)throw std::runtime_error("Mesh asset exceeds the viewer size limit.");
                auto asset=QJsonDocument::fromJson(file.readAll()).object();auto mesh=meshPresentation(asset);
                auto pose=part.value("matrix").toArray();if(pose.size()!=12)throw std::runtime_error("Invalid mesh placement.");
                gp_Trsf trsf;trsf.SetValues(pose[0].toDouble(),pose[1].toDouble(),pose[2].toDouble(),pose[3].toDouble(),pose[4].toDouble(),pose[5].toDouble(),pose[6].toDouble(),pose[7].toDouble(),pose[8].toDouble(),pose[9].toDouble(),pose[10].toDouble(),pose[11].toDouble());
                mesh->SetLocalTransformation(trsf);nextMeshes.insert(id,mesh);continue;
            }
            TopoDS_Shape body;
            BRep_Builder builder;
            if (!BRepTools::Read(body, filename.toUtf8().constData(), builder) || body.IsNull())
                throw std::runtime_error("The native viewer could not read a BREP asset.");
            const auto counts = part.value("topology").toObject();
            for (const auto& kind : {QString("face"), QString("edge"), QString("vertex")}) {
                TopTools_IndexedMapOfShape map;
                TopExp::MapShapes(body, topologyKind(kind), map);
                const auto key = kind == "vertex" ? QString("vertices") : kind + "s";
                if (map.Extent() != counts.value(key).toInt()) throw std::runtime_error("Viewer/worker topology maps disagree.");
            }
            Handle(AIS_Shape) presentation = new AIS_Shape(body);
            auto color = part.value("color").toArray();
            presentation->SetColor(Quantity_Color(color.at(0).toDouble(), color.at(1).toDouble(), color.at(2).toDouble(), Quantity_TOC_RGB));
            presentation->SetMaterial(Graphic3d_NOM_PLASTIC);
            auto pose = part.value("matrix").toArray();
            if (pose.size() != 12) throw std::runtime_error("The body placement is invalid.");
            gp_Trsf trsf;
            trsf.SetValues(pose[0].toDouble(), pose[1].toDouble(), pose[2].toDouble(), pose[3].toDouble(),
                           pose[4].toDouble(), pose[5].toDouble(), pose[6].toDouble(), pose[7].toDouble(),
                           pose[8].toDouble(), pose[9].toDouble(), pose[10].toDouble(), pose[11].toDouble());
            presentation->SetLocalTransformation(trsf);
            next.insert(id, presentation);
        }
        context->RemoveAll(false);
        shapes = next;meshes=nextMeshes;
        for(const auto& mesh:meshes)context->Display(mesh,MeshVS_DMF_Shading|MeshVS_DMF_ElementalColorDataPrs,MeshVS_SMF_Mesh,false);
        for (const auto& shape : shapes) context->Display(shape, AIS_Shaded, 0, false);
        setSelectionMode(mode);
        currentSelection = {};
        Q_EMIT selectionChanged({});
        if (fit) fitAll(); else view->Redraw();
    } catch (const Standard_Failure& error) { Q_EMIT viewerError(QString::fromUtf8(error.GetMessageString())); }
      catch (const std::exception& error) { Q_EMIT viewerError(QString::fromUtf8(error.what())); }
}
void CadView::fitAll() {
    if (view.IsNull()) return;
    view->FitAll(0.06, false); view->ZFitAll(); view->Redraw();
}
void CadView::standardView(const QString& direction) {
    if (view.IsNull()) return;
    view->SetProj(direction == "top" ? V3d_Zpos : direction == "front" ? V3d_Yneg : direction == "right" ? V3d_Xpos : V3d_XposYnegZpos);
    fitAll();
}
void CadView::setSelectionMode(const QString& kind) {
    mode = kind;
    if (context.IsNull()) return;
    context->ClearSelected(false); context->Deactivate();
    const int selectionMode = kind == "body" ? 0 : AIS_Shape::SelectionMode(topologyKind(kind));
    for (const auto& shape : shapes) context->Activate(shape, selectionMode);
    for(const auto& mesh:meshes)context->Activate(mesh,kind=="face"?MeshVS_SMF_Face:MeshVS_SMF_Mesh);
    currentSelection = {};
    Q_EMIT selectionChanged({}); view->Redraw();
}
void CadView::selectInstance(const QString& id) {
    if (context.IsNull() || (!shapes.contains(id)&&!meshes.contains(id))) return;
    context->ClearSelected(false);
    if(shapes.contains(id))context->SetSelected(shapes[id],false);else context->SetSelected(meshes[id],false);
    currentSelection = {{"revision_id", document.value("revision_id")}, {"instance_id", id}, {"kind", "body"}, {"index", 0}};
    Q_EMIT selectionChanged(currentSelection); view->Redraw();
}
void CadView::setVisibleInstance(const QString& id, bool visible) {
    if(context.IsNull())return;
    if(shapes.contains(id)){if(visible)context->Display(shapes[id],false);else context->Erase(shapes[id],false);}
    else if(meshes.contains(id)){if(visible)context->Display(meshes[id],false);else context->Erase(meshes[id],false);}
    view->Redraw();
}
void CadView::mousePressEvent(QMouseEvent* event) {
    setFocus(); lastPosition = pressedPosition = QPoint(qRound(event->position().x() * devicePixelRatioF()), qRound(event->position().y() * devicePixelRatioF()));
    if (!view.IsNull() && event->button() == Qt::LeftButton) view->StartRotation(lastPosition.x(), lastPosition.y());
}
void CadView::mouseMoveEvent(QMouseEvent* event) {
    if (view.IsNull()) return;
    auto point = QPoint(qRound(event->position().x() * devicePixelRatioF()), qRound(event->position().y() * devicePixelRatioF())); auto delta = point - lastPosition;
    if ((event->buttons() & Qt::MiddleButton) || ((event->buttons() & Qt::LeftButton) && (event->modifiers() & Qt::ShiftModifier)))
        view->Pan(delta.x(), -delta.y());
    else if (event->buttons() & Qt::LeftButton) {
        if ((point - pressedPosition).manhattanLength() > 4) view->Rotation(point.x(), point.y());
    } else if (event->buttons() & Qt::RightButton) view->Zoom(lastPosition.x(), lastPosition.y(), point.x(), point.y());
    else context->MoveTo(point.x(), point.y(), view, true);
    lastPosition = point;
}
void CadView::mouseReleaseEvent(QMouseEvent* event) {
    if (view.IsNull() || event->button() != Qt::LeftButton || (QPoint(qRound(event->position().x() * devicePixelRatioF()), qRound(event->position().y() * devicePixelRatioF())) - pressedPosition).manhattanLength() > 4) return;
    context->MoveTo(lastPosition.x(), lastPosition.y(), view, false);
    context->SelectDetected(event->modifiers() & Qt::ControlModifier ? AIS_SelectionScheme_XOR : AIS_SelectionScheme_Replace);
    updateSelection(); view->Redraw();
}
void CadView::wheelEvent(QWheelEvent* event) {
    if (view.IsNull()) return;
    view->SetScale(view->Scale() * std::pow(1.0015, event->angleDelta().y())); view->Redraw();
}
void CadView::updateSelection() {
    currentSelection = {};
    context->InitSelected();
    if (context->MoreSelected()) {
        auto object = Handle(AIS_Shape)::DownCast(context->SelectedInteractive());
        QString id;
        for (auto it = shapes.cbegin(); it != shapes.cend(); ++it) if (it.value() == object) { id = it.key(); break; }
        if (!id.isEmpty()) {
            int index = 0; QString kind = "body";
            auto owner = Handle(StdSelect_BRepOwner)::DownCast(context->SelectedOwner());
            if (!owner.IsNull() && owner->HasShape() && mode != "body") {
                auto subshape = owner->Shape(); kind = shapeKind(subshape.ShapeType());
                TopTools_IndexedMapOfShape map;
                TopExp::MapShapes(object->Shape(), subshape.ShapeType(), map);
                index = map.FindIndex(subshape);
            }
            if (kind == "body" || index > 0) currentSelection = {{"revision_id", document.value("revision_id")},
                {"instance_id", id}, {"kind", kind}, {"index", index}};
        }
    }
    if(currentSelection.isEmpty()) {
        context->InitSelected();if(context->MoreSelected()) {
            auto object=Handle(MeshVS_Mesh)::DownCast(context->SelectedInteractive());QString id;
            for(auto it=meshes.cbegin();it!=meshes.cend();++it)if(it.value()==object){id=it.key();break;}
            if(!id.isEmpty()) {
                QJsonArray triangles;
                for(context->InitSelected();context->MoreSelected();context->NextSelected())if(context->SelectedInteractive()==object){auto owner=Handle(MeshVS_MeshEntityOwner)::DownCast(context->SelectedOwner());if(!owner.IsNull()&&owner->Type()==MeshVS_ET_Face)triangles.append(owner->ID());}
                currentSelection={{"revision_id",document.value("revision_id")},{"instance_id",id},{"kind",triangles.isEmpty()?"body":"region"},{"index",triangles.isEmpty()?0:triangles[0].toInt()},{"triangle_indices",triangles}};
            }
        }
    }
    if(currentSelection.value("kind")=="edge")currentSelection["edge_indices"]=selectedEdges(currentSelection.value("instance_id").toString());
    Q_EMIT selectionChanged(currentSelection);
}
QJsonArray CadView::selectedEdges(const QString& id) const {
    QJsonArray indices;
    if (context.IsNull() || !shapes.contains(id)) return indices;
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(shapes[id]->Shape(), TopAbs_EDGE, edges);
    for (context->InitSelected(); context->MoreSelected(); context->NextSelected()) {
        if (context->SelectedInteractive() != shapes[id]) continue;
        auto owner = Handle(StdSelect_BRepOwner)::DownCast(context->SelectedOwner());
        if (!owner.IsNull() && owner->HasShape() && owner->Shape().ShapeType() == TopAbs_EDGE) {
            int index = edges.FindIndex(owner->Shape()); if (index > 0) indices.append(index);
        }
    }
    return indices;
}
QJsonObject CadView::topologyReport() const {
    QJsonObject report;
    for (auto it = shapes.cbegin(); it != shapes.cend(); ++it) {
        QJsonObject body;
        for (const auto& kind : {QString("face"), QString("edge"), QString("vertex")}) {
            TopTools_IndexedMapOfShape map; TopExp::MapShapes(it.value()->Shape(), topologyKind(kind), map);
            body[kind] = map.Extent();
        }
        report[it.key()] = body;
    }
    for(auto it=meshes.cbegin();it!=meshes.cend();++it)report[it.key()]=QJsonObject{{"triangles",it.value()->GetDataSource()->GetAllElements().Extent()}};
    return report;
}
bool CadView::smokeSelectFace() {
    if(shapes.isEmpty()&&!meshes.isEmpty()) {
        setSelectionMode("face");
        for(const auto& mesh:meshes){auto* source=dynamic_cast<MeshSource*>(mesh->GetDataSource().get());if(!source)continue;for(int id=1;id<=source->triangleCount();++id){auto point=source->triangleCentre(id).Transformed(mesh->LocalTransformation());int x,y;view->Convert(point.X(),point.Y(),point.Z(),x,y);context->MoveTo(x,y,view,false);context->SelectDetected(AIS_SelectionScheme_Replace);updateSelection();if(currentSelection.value("kind")=="region")return true;}}
        return false;
    }
    if (shapes.isEmpty()) return false;
    setSelectionMode("face");
    for (const auto& object : shapes) {
        TopTools_IndexedMapOfShape faces; TopExp::MapShapes(object->Shape(), TopAbs_FACE, faces);
        for (int index = 1; index <= faces.Extent(); ++index) {
            GProp_GProps properties; BRepGProp::SurfaceProperties(faces(index), properties);
            auto centre = properties.CentreOfMass().Transformed(object->LocalTransformation());
            int x, y; view->Convert(centre.X(), centre.Y(), centre.Z(), x, y);
            QPointF position(x / devicePixelRatioF(), y / devicePixelRatioF());
            QMouseEvent press(QEvent::MouseButtonPress, position, position, Qt::LeftButton, Qt::LeftButton, Qt::NoModifier);
            QMouseEvent release(QEvent::MouseButtonRelease, position, position, Qt::LeftButton, Qt::NoButton, Qt::NoModifier);
            QCoreApplication::sendEvent(this, &press);
            QCoreApplication::sendEvent(this, &release);
            if (currentSelection.value("kind") == "face" && currentSelection.value("index").toInt() > 0) return true;
        }
    }
    return false;
}

bool CadView::saveViewport(const QString& path) {
    if (view.IsNull()) return false;
    view->Redraw();
    return view->Dump(path.toUtf8().constData());
}

double CadView::benchmarkOrbit() {
    if (view.IsNull()) return 0;
    const int x = qRound(width() * devicePixelRatioF() / 2);
    const int y = qRound(height() * devicePixelRatioF() / 2);
    view->StartRotation(x, y);
    QElapsedTimer timer; timer.start();
    for (int frame = 0; frame < 60; ++frame) {
        const double angle = frame * 0.1;
        view->Rotation(x + int(40 * std::sin(angle)), y + int(40 * std::cos(angle)));
        view->Redraw();
    }
    const double seconds = timer.nsecsElapsed() / 1e9;
    standardView("isometric");
    return seconds > 0 ? 60 / seconds : 0;
}

void CadView::isolateInstance(const QString& id){for(auto it=shapes.cbegin();it!=shapes.cend();++it)setVisibleInstance(it.key(),it.key()==id);for(auto it=meshes.cbegin();it!=meshes.cend();++it)setVisibleInstance(it.key(),it.key()==id);}
void CadView::showAll(){for(auto it=shapes.cbegin();it!=shapes.cend();++it)setVisibleInstance(it.key(),true);for(auto it=meshes.cbegin();it!=meshes.cend();++it)setVisibleInstance(it.key(),true);}
void CadView::setShading(bool edges){if(context.IsNull())return;context->DefaultDrawer()->SetFaceBoundaryDraw(edges);for(const auto& shape:shapes)context->Redisplay(shape,false);view->Redraw();}
