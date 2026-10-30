#include "CadView.h"
#include <QSet>
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
#include <limits>
#include <stdexcept>
#include <Aspect_DisplayConnection.hxx>
#include <OpenGl_GraphicDriver.hxx>
#include <BRep_Builder.hxx>
#include <BRepTools.hxx>
#include <BRepGProp.hxx>
#include <BRepBndLib.hxx>
#include <Bnd_Box.hxx>
#include <TCollection_ExtendedString.hxx>
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
    setLightTheme(lightTheme);
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
                auto asset=QJsonDocument::fromJson(file.readAll()).object();auto mesh=meshPresentation(asset, part.value("color_override").toArray());
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
            presentation->SetDisplayMode(AIS_Shaded);
            auto pose = part.value("matrix").toArray();
            if (pose.size() != 12) throw std::runtime_error("The body placement is invalid.");
            gp_Trsf trsf;
            trsf.SetValues(pose[0].toDouble(), pose[1].toDouble(), pose[2].toDouble(), pose[3].toDouble(),
                           pose[4].toDouble(), pose[5].toDouble(), pose[6].toDouble(), pose[7].toDouble(),
                           pose[8].toDouble(), pose[9].toDouble(), pose[10].toDouble(), pose[11].toDouble());
            presentation->SetLocalTransformation(trsf);
            next.insert(id, presentation);
        }
        meshPickOwners.clear();meshHover.Nullify();
        context->RemoveAll(false);
        annotations.clear(); annotationOwners.clear();
        shapes = next;meshes=nextMeshes;
        auto& hidden = hiddenByDocument[document.value("document_id").toString()];
        QSet<QString> existing;
        for (auto it=shapes.cbegin();it!=shapes.cend();++it) existing.insert(it.key());
        for (auto it=meshes.cbegin();it!=meshes.cend();++it) existing.insert(it.key());
        hidden.intersect(existing);
        for (const auto& id : existing) if (!hidden.contains(id)) displayInstance(id);
        buildAnnotations();
        setSelectionMode(mode);
        currentSelection = {};
        Q_EMIT selectionChanged({});
        if (fit) fitAll(); else view->Redraw();
        Q_EMIT visibilityChanged();
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
    if(!meshHover.IsNull()&&!context->IsSelected(meshHover))meshHover->Unhilight(context->MainPrsMgr(),0);meshHover.Nullify();
    context->ClearSelected(false); context->Deactivate();
    const int selectionMode = kind == "body" ? 0 : AIS_Shape::SelectionMode(topologyKind(kind));
    for (const auto& shape : shapes) context->Activate(shape, selectionMode);
    for(const auto& mesh:meshes)context->Activate(mesh,kind=="face"?MeshVS_SMF_Face:MeshVS_SMF_Mesh);
    currentSelection = {};
    Q_EMIT selectionChanged({}); view->Redraw();
}
void CadView::selectInstance(const QString& id) { selectInstances({id}); }
void CadView::selectInstances(const QStringList &ids) {
    if(context.IsNull())return;
    context->ClearSelected(false);
    for(const auto &id:ids) {
        if (!isInstanceVisible(id)) continue;
        if(shapes.contains(id))context->AddOrRemoveSelected(shapes[id],false);
        else if(meshes.contains(id))context->AddOrRemoveSelected(meshes[id],false);
    }
    updateSelection();view->Redraw();
}
void CadView::removeSelectedEntity(int index) {
    if(context.IsNull())return;
    if(index<0)context->ClearSelected(false);
    else if(index<selectedOwners.size())for(const auto &owner:selectedOwners[index])context->AddOrRemoveSelected(owner,false);
    updateSelection();view->Redraw();
}
void CadView::setVisibleInstance(const QString& id, bool visible) {
    setVisibleInstances({id}, visible);
}
bool CadView::isInstanceVisible(const QString& id) const {
    return (shapes.contains(id) || meshes.contains(id)) &&
           !hiddenByDocument.value(document.value("document_id").toString()).contains(id);
}
QStringList CadView::visibleInstances() const {
    QStringList ids;
    for (auto it=shapes.cbegin();it!=shapes.cend();++it) if (isInstanceVisible(it.key())) ids << it.key();
    for (auto it=meshes.cbegin();it!=meshes.cend();++it) if (isInstanceVisible(it.key())) ids << it.key();
    return ids;
}
void CadView::displayInstance(const QString& id) {
    if (shapes.contains(id)) {
        shapes[id]->SetDisplayMode(AIS_Shaded);
        const int selectionMode = mode == "body" ? 0 : AIS_Shape::SelectionMode(topologyKind(mode));
        context->Display(shapes[id], AIS_Shaded, selectionMode, false);
    } else if (meshes.contains(id)) {
        context->Display(meshes[id], MeshVS_DMF_Shading | MeshVS_DMF_ElementalColorDataPrs,
                         mode == "face" ? MeshVS_SMF_Face : MeshVS_SMF_Mesh, false);
    }
}
void CadView::setVisibleInstances(const QStringList& ids, bool visible) {
    if (context.IsNull()) return;
    auto& hidden = hiddenByDocument[document.value("document_id").toString()];
    QList<Handle(SelectMgr_EntityOwner)> remove;
    if (!visible) {
        for (context->InitSelected(); context->MoreSelected(); context->NextSelected()) {
            auto object = context->SelectedInteractive();
            for (const auto& id : ids)
                if ((shapes.contains(id) && object == shapes[id]) ||
                    (meshes.contains(id) && object == meshes[id])) {
                    remove.append(context->SelectedOwner());
                    break;
                }
        }
        for (const auto& owner : remove) context->AddOrRemoveSelected(owner, false);
    }
    for (const auto& id : ids) {
        if (!shapes.contains(id) && !meshes.contains(id)) continue;
        if (visible) {
            hidden.remove(id);
            displayInstance(id);
        } else {
            hidden.insert(id);
            if (shapes.contains(id)) context->Erase(shapes[id], false);
            else context->Erase(meshes[id], false);
        }
        for (auto it=annotations.cbegin();it!=annotations.cend();++it)
            if (annotationOwners.value(it.key()) == id) {
                if (visible) context->Display(it.value(), false);
                else context->Erase(it.value(), false);
                context->Deactivate(it.value());
            }
    }
    if (!meshHover.IsNull()) {
        if (!context->IsSelected(meshHover)) meshHover->Unhilight(context->MainPrsMgr(), 0);
        meshHover.Nullify();
    }
    if (!remove.isEmpty()) updateSelection();
    Q_EMIT visibilityChanged();
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
    else {
        if(!meshHover.IsNull()&&!context->IsSelected(meshHover))meshHover->Unhilight(context->MainPrsMgr(),0);meshHover.Nullify();
        context->MoveTo(point.x(), point.y(), view, true);
        if(!context->HasDetected()&&mode=="face") {meshHover=pickMeshFace(point);if(!meshHover.IsNull()&&!context->IsSelected(meshHover)){meshHover->HilightWithColor(context->MainPrsMgr(),context->HighlightStyle(),0);view->Redraw();}}
    }
    lastPosition = point;
}
void CadView::mouseReleaseEvent(QMouseEvent* event) {
    if (view.IsNull() || event->button() != Qt::LeftButton || (QPoint(qRound(event->position().x() * devicePixelRatioF()), qRound(event->position().y() * devicePixelRatioF())) - pressedPosition).manhattanLength() > 4) return;
    const QPoint point(qRound(event->position().x()*devicePixelRatioF()),qRound(event->position().y()*devicePixelRatioF()));
    context->MoveTo(point.x(), point.y(), view, false);
    if(!context->HasDetected()&&mode=="face") {
        auto owner=pickMeshFace(point);
        if(!owner.IsNull()){if(!(event->modifiers()&Qt::ControlModifier))context->ClearSelected(false);context->AddOrRemoveSelected(owner,false);updateSelection();view->Redraw();return;}
    }
    if((event->modifiers() & Qt::ControlModifier) && !context->HasDetected())return;
    context->SelectDetected(event->modifiers() & Qt::ControlModifier ? AIS_SelectionScheme_XOR : AIS_SelectionScheme_Replace);
    updateSelection(); view->Redraw();
}
void CadView::wheelEvent(QWheelEvent* event) {
    if (view.IsNull()) return;
    view->SetScale(view->Scale() * std::pow(1.0015, event->angleDelta().y())); view->Redraw();
}
Handle(SelectMgr_EntityOwner) CadView::pickMeshFace(const QPoint &point) {
    if(view.IsNull()||meshes.isEmpty())return {};
    double x,y,z,dx,dy,dz;view->ConvertWithProj(point.x(),point.y(),x,y,z,dx,dy,dz);
    gp_Pnt origin(x,y,z);gp_Vec direction(dx,dy,dz);
    if(direction.SquareMagnitude()<1e-20)return {};
    direction.Normalize();if(direction.Dot(gp_Vec(view->Camera()->Direction()))<0)direction.Reverse();
    double span=1;
    for(auto value:document.value("components").toArray()) {
        auto part=value.toObject();auto bounds=part.value("metrics").toObject().value("bounds_mm").toArray();if(bounds.size()!=2)continue;
        auto low=bounds[0].toArray(),high=bounds[1].toArray();auto id=part.value("instance_id").toString();if(!meshes.contains(id))continue;
        for(int corner=0;corner<8;++corner){gp_Pnt p((corner&1?high:low)[0].toDouble(),(corner&2?high:low)[1].toDouble(),(corner&4?high:low)[2].toDouble());p.Transform(meshes[id]->LocalTransformation());span=qMax(span,origin.Distance(p)+1);}
    }
    origin.Translate(direction.Multiplied(-span));
    double nearest=std::numeric_limits<double>::max();QString hitId;int triangle=0;
    for(auto it=meshes.cbegin();it!=meshes.cend();++it) {
        if(!context->IsDisplayed(it.value()))continue;
        auto *source=dynamic_cast<MeshSource *>(it.value()->GetDataSource().get());if(!source)continue;
        const auto inverse=it.value()->LocalTransformation().Inverted();double distance=nearest;
        int face=source->rayHit(origin.Transformed(inverse),direction.Transformed(inverse),distance);
        if(face){nearest=distance;triangle=face;hitId=it.key();}
    }
    if(hitId.isEmpty())return {};
    for(context->InitSelected();context->MoreSelected();context->NextSelected()) {
        auto owner=Handle(MeshVS_MeshEntityOwner)::DownCast(context->SelectedOwner());
        if(context->SelectedInteractive()==meshes[hitId]&&!owner.IsNull()&&owner->Type()==MeshVS_ET_Face&&owner->ID()==triangle)return owner;
    }
    auto key=hitId+":"+QString::number(triangle);
    if(!meshPickOwners.contains(key))meshPickOwners[key]=new MeshVS_MeshEntityOwner(meshes[hitId].get(),triangle,nullptr,MeshVS_ET_Face,5);
    return meshPickOwners[key];
}

void CadView::updateSelection() {
    currentSelection = {}; selectedOwners.clear();
    QJsonArray entities;
    QMap<QString,int> regions;
    for(context->InitSelected();context->MoreSelected();context->NextSelected()) {
        auto selectedOwner=context->SelectedOwner();
        auto object=Handle(AIS_Shape)::DownCast(context->SelectedInteractive());
        QString id;
        for(auto it=shapes.cbegin();it!=shapes.cend();++it)if(it.value()==object&&!object.IsNull()){id=it.key();break;}
        if(!id.isEmpty()) {
            int index=0;QString kind="body";
            auto owner=Handle(StdSelect_BRepOwner)::DownCast(selectedOwner);
            if(!owner.IsNull()&&owner->HasShape()&&mode!="body") {
                auto subshape=owner->Shape();kind=shapeKind(subshape.ShapeType());
                if(kind!="body") { TopTools_IndexedMapOfShape map;TopExp::MapShapes(object->Shape(),subshape.ShapeType(),map);index=map.FindIndex(subshape); }
            }
            if(kind=="body"||index>0) {
                entities.append(QJsonObject{{"instance_id",id},{"kind",kind},{"index",index}});
                selectedOwners.append(QList<Handle(SelectMgr_EntityOwner)>{selectedOwner});
            }
            continue;
        }
        auto mesh=Handle(MeshVS_Mesh)::DownCast(context->SelectedInteractive());
        for(auto it=meshes.cbegin();it!=meshes.cend();++it)if(it.value()==mesh&&!mesh.IsNull()){id=it.key();break;}
        if(id.isEmpty())continue;
        auto owner=Handle(MeshVS_MeshEntityOwner)::DownCast(selectedOwner);
        const bool face=!owner.IsNull()&&owner->Type()==MeshVS_ET_Face;
        if(face&&regions.contains(id)) {
            int position=regions[id];auto entry=entities[position].toObject();auto triangles=entry["triangle_indices"].toArray();triangles.append(owner->ID());entry["triangle_indices"]=triangles;entities[position]=entry;selectedOwners[position].append(selectedOwner);
        } else {
            QJsonObject entry{{"instance_id",id},{"kind",face?"region":"body"},{"index",face?owner->ID():0}};
            if(face){entry["triangle_indices"]=QJsonArray{owner->ID()};regions[id]=entities.size();}
            entities.append(entry);selectedOwners.append(QList<Handle(SelectMgr_EntityOwner)>{selectedOwner});
        }
    }
    if(!entities.isEmpty()) {
        currentSelection=entities.first().toObject();
        currentSelection["version"]=2;currentSelection["revision_id"]=document.value("revision_id");currentSelection["document_id"]=document.value("document_id");currentSelection["entities"]=entities;
        if(entities.size()==1&&currentSelection["kind"]=="edge")currentSelection["edge_indices"]=selectedEdges(currentSelection["instance_id"].toString());
    }
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

bool CadView::smokeSelectMultipleFaces() {
    setSelectionMode("face");
    auto pick=[this](const gp_Pnt &point) {
        int x,y;view->Convert(point.X(),point.Y(),point.Z(),x,y);
        QPointF position(x/devicePixelRatioF(),y/devicePixelRatioF());
        QMouseEvent press(QEvent::MouseButtonPress,position,position,Qt::LeftButton,Qt::LeftButton,Qt::ControlModifier);
        QMouseEvent release(QEvent::MouseButtonRelease,position,position,Qt::LeftButton,Qt::NoButton,Qt::ControlModifier);
        QCoreApplication::sendEvent(this,&press);QCoreApplication::sendEvent(this,&release);
        QSet<QString> ids;for(auto value:currentSelection.value("entities").toArray())ids.insert(value.toObject().value("instance_id").toString());
        return ids.size()>1;
    };
    for(const auto &object:shapes) {
        TopTools_IndexedMapOfShape faces;TopExp::MapShapes(object->Shape(),TopAbs_FACE,faces);
        for(int index=1;index<=faces.Extent();++index){GProp_GProps properties;BRepGProp::SurfaceProperties(faces(index),properties);if(pick(properties.CentreOfMass().Transformed(object->LocalTransformation())))return true;bool found=false;for(auto value:currentSelection.value("entities").toArray())if(value.toObject().value("instance_id").toString()==shapes.key(object))found=true;if(found)break;}
    }
    for(const auto &mesh:meshes) {
        auto *source=dynamic_cast<MeshSource *>(mesh->GetDataSource().get());if(!source)continue;
        for(int index=1;index<=source->triangleCount();++index){if(pick(source->triangleCentre(index).Transformed(mesh->LocalTransformation())))return true;bool found=false;for(auto value:currentSelection.value("entities").toArray())if(value.toObject().value("instance_id").toString()==meshes.key(mesh))found=true;if(found)break;}
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

void CadView::isolateInstance(const QString& id) {
    isolateInstances({id});
}
void CadView::isolateInstances(const QStringList& ids) {
    if (context.IsNull()) return;
    QStringList others;
    bool found = false;
    auto& hidden = hiddenByDocument[document.value("document_id").toString()];
    for (const auto& id : shapes.keys() + meshes.keys()) {
        if (ids.contains(id)) {
            found = true;
            hidden.remove(id);
            displayInstance(id);
            for (auto it=annotations.cbegin();it!=annotations.cend();++it)
                if (annotationOwners.value(it.key()) == id) {
                    context->Display(it.value(), false);
                    context->Deactivate(it.value());
                }
        } else others << id;
    }
    if (found) setVisibleInstances(others, false);
}
void CadView::showAll(){setVisibleInstances(shapes.keys() + meshes.keys(), true);}
void CadView::hideAll(){setVisibleInstances(shapes.keys() + meshes.keys(), false);}
void CadView::setShading(bool edges){if(context.IsNull())return;context->DefaultDrawer()->SetFaceBoundaryDraw(edges);for(const auto& shape:shapes)context->Redisplay(shape,false);view->Redraw();}

void CadView::setLightTheme(bool light) {
    lightTheme = light;
    if (view.IsNull()) return;
    for (const auto& label : annotations) {
        label->SetColor(light ? Quantity_NOC_GRAY20 : Quantity_NOC_GRAY90);
        context->Redisplay(label, false);
    }
    view->SetBgGradientColors(light ? Quantity_Color(0.95, 0.95, 0.96, Quantity_TOC_RGB) : Quantity_Color(0.14, 0.14, 0.16, Quantity_TOC_RGB),
                              light ? Quantity_Color(0.85, 0.87, 0.90, Quantity_TOC_RGB) : Quantity_Color(0.09, 0.09, 0.11, Quantity_TOC_RGB), Aspect_GFM_VER, false);
    view->TriedronDisplay(Aspect_TOTP_LEFT_LOWER, light ? Quantity_NOC_GRAY40 : Quantity_NOC_GRAY80, 0.08, V3d_ZBUFFER);
    view->Redraw();
}

void CadView::buildAnnotations() {
    for (const auto& value : document.value("engineering").toArray()) {
        const auto record = value.toObject();
        if (record.value("status").toString() != "current") continue;
        const auto owner = record.value("instance_id").toString();
        QJsonObject part;
        for (const auto& entry : document.value("components").toArray())
            if (entry.toObject().value("instance_id").toString() == owner) { part = entry.toObject(); break; }
        if (part.isEmpty()) continue;
        const auto anchor = record.value("anchor").toObject();
        const auto kind = anchor.value("kind").toString("body");
        gp_Pnt point;
        const auto position = anchor.value("position").toArray();
        if (kind != "body" && anchor.value("asset_hash") != part.value("asset_hash")) continue;
        if (position.size() == 3) point.SetCoord(position[0].toDouble(), position[1].toDouble(), position[2].toDouble());
        else if (kind != "body" && shapes.contains(owner)) {
            TopTools_IndexedMapOfShape map;
            TopExp::MapShapes(shapes[owner]->Shape(), topologyKind(kind), map);
            const int index = anchor.value("index").toInt();
            if (index < 1 || index > map.Extent()) continue;
            Bnd_Box box; BRepBndLib::Add(map(index), box);
            if (box.IsVoid()) continue;
            double x1,y1,z1,x2,y2,z2; box.Get(x1,y1,z1,x2,y2,z2);
            point.SetCoord((x1+x2)/2, (y1+y2)/2, (z1+z2)/2);
        } else {
            const auto bounds = part.value("metrics").toObject().value("bounds_mm").toArray();
            if (bounds.size() != 2) continue;
            auto low = bounds[0].toArray(), high = bounds[1].toArray();
            point.SetCoord((low[0].toDouble()+high[0].toDouble())/2, (low[1].toDouble()+high[1].toDouble())/2,
                           (low[2].toDouble()+high[2].toDouble())/2);
        }
        const auto pose = part.value("matrix").toArray();
        if (pose.size() != 12) continue;
        gp_Trsf transform;
        transform.SetValues(pose[0].toDouble(),pose[1].toDouble(),pose[2].toDouble(),pose[3].toDouble(),
                            pose[4].toDouble(),pose[5].toDouble(),pose[6].toDouble(),pose[7].toDouble(),
                            pose[8].toDouble(),pose[9].toDouble(),pose[10].toDouble(),pose[11].toDouble());
        point.Transform(transform);
        QString text = record.value("text").toString();
        if (record.value("kind") == "dimension") {
            text += (text.isEmpty() ? "" : ": ") + QString::number(record.value("nominal").toDouble(), 'g', 8);
            const auto tolerance = record.value("tolerance").toObject();
            if (tolerance.value("mode") == "plus_minus")
                text += " +" + QString::number(tolerance.value("plus").toDouble()) + " / −" + QString::number(tolerance.value("minus").toDouble());
            else if (tolerance.value("mode") == "limits")
                text += " [" + QString::number(tolerance.value("lower").toDouble()) + ", " + QString::number(tolerance.value("upper").toDouble()) + "]";
            if (record.value("units").toString("mm") != "unitless") text += " " + record.value("units").toString("mm");
            if (record.value("verification") == "declared_unverified") text += " (declared)";
        }
        if (text.isEmpty()) continue;
        Handle(AIS_TextLabel) label = new AIS_TextLabel;
        label->SetText(TCollection_ExtendedString(text.left(160).toUtf8().constData(), true));
        label->SetPosition(point); label->SetHeight(13);
        label->SetColor(lightTheme ? Quantity_NOC_GRAY20 : Quantity_NOC_GRAY90);
        const auto identity = record.value("id").toString();
        annotations[identity] = label; annotationOwners[identity] = owner;
        if (isInstanceVisible(owner)) { context->Display(label, false); context->Deactivate(label); }
    }
}
