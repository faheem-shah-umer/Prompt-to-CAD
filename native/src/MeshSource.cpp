#include "MeshSource.h"
#include <QJsonArray>
#include <MeshVS_MeshPrsBuilder.hxx>
#include <MeshVS_ElementalColorPrsBuilder.hxx>
#include <MeshVS_Drawer.hxx>
#include <MeshVS_DrawerAttribute.hxx>
#include <MeshVS_DisplayModeFlags.hxx>
#include <Quantity_Color.hxx>
#include <cmath>
#include <stdexcept>

MeshSource::MeshSource(const QJsonObject &asset) {
    auto vertices = asset.value("vertices").toArray();
    auto faces = asset.value("triangles").toArray();
    if (vertices.isEmpty() || vertices.size() > 600000 || faces.isEmpty() || faces.size() > 200000)
        throw std::runtime_error("Mesh exceeds supported size limits.");
    for (auto v : vertices) {
        auto a = v.toArray();
        if (a.size() != 3)
            throw std::runtime_error("Invalid mesh vertex.");
        for (auto x : a)
            if (!x.isDouble() || !std::isfinite(x.toDouble()) || std::abs(x.toDouble()) > 1e8)
                throw std::runtime_error("Invalid mesh coordinates.");
        points.emplace_back(a[0].toDouble(), a[1].toDouble(), a[2].toDouble());
        nodes.Add(int(points.size()));
    }
    for (auto f : faces) {
        auto a = f.toArray();
        if (a.size() != 3)
            throw std::runtime_error("Only triangular meshes are supported.");
        std::array<int, 3> face{};
        for (int i = 0; i < 3; ++i) {
            int n = a[i].toInt(-1);
            if (n < 0 || n >= int(points.size()))
                throw std::runtime_error("Mesh node reference is invalid.");
            face[i] = n;
        }
        triangles.push_back(face);
        elements.Add(int(triangles.size()));
    }
    normals.resize(points.size(), gp_Vec(0, 0, 0));
    for (const auto &triangle : triangles) {
        auto normal = gp_Vec(points[triangle[0]], points[triangle[1]])
                          .Crossed(gp_Vec(points[triangle[0]], points[triangle[2]]));
        if (normal.SquareMagnitude() < 1e-24)
            throw std::runtime_error("Mesh contains a degenerate triangle.");
        for (auto vertex : triangle)
            normals[vertex] += normal;
    }
    for (auto &normal : normals)
        if (normal.SquareMagnitude() > 1e-24)
            normal.Normalize();
}
Standard_Boolean MeshSource::GetGeom(Standard_Integer id, Standard_Boolean element,
                                     TColStd_Array1OfReal &coordinates, Standard_Integer &count,
                                     MeshVS_EntityType &type) const {
    if (!GetGeomType(id, element, type))
        return false;
    count = element ? 3 : 1;
    if (coordinates.Length() < 3 * count)
        return false;
    for (int i = 0; i < count; ++i) {
        auto p = points[element ? triangles[id - 1][i] : id - 1];
        int n = coordinates.Lower() + 3 * i;
        coordinates(n) = p.X();
        coordinates(n + 1) = p.Y();
        coordinates(n + 2) = p.Z();
    }
    return true;
}
Standard_Boolean MeshSource::GetGeomType(Standard_Integer id, Standard_Boolean element,
                                         MeshVS_EntityType &type) const {
    if (id < 1 || id > (element ? int(triangles.size()) : int(points.size())))
        return false;
    type = element ? MeshVS_ET_Face : MeshVS_ET_Node;
    return true;
}
Standard_Boolean MeshSource::GetNodesByElement(Standard_Integer id, TColStd_Array1OfInteger &ids,
                                               Standard_Integer &count) const {
    if (id < 1 || id > int(triangles.size()) || ids.Length() < 3)
        return false;
    count = 3;
    for (int i = 0; i < 3; ++i)
        ids(ids.Lower() + i) = triangles[id - 1][i] + 1;
    return true;
}
gp_Pnt MeshSource::triangleCentre(int id) const {
    auto f = triangles.at(id - 1);
    auto a = points[f[0]], b = points[f[1]], c = points[f[2]];
    return gp_Pnt((a.X() + b.X() + c.X()) / 3, (a.Y() + b.Y() + c.Y()) / 3, (a.Z() + b.Z() + c.Z()) / 3);
}
int MeshSource::rayHit(const gp_Pnt &origin, const gp_Vec &direction, double &distance) const {
    int result=0;
    for(int i=0;i<int(triangles.size());++i) {
        const auto &face=triangles[i];const auto &a=points[face[0]];
        gp_Vec edge1(a,points[face[1]]),edge2(a,points[face[2]]);
        const auto cross=direction.Crossed(edge2);const double determinant=edge1.Dot(cross);
        if(std::abs(determinant)<1e-12)continue;
        gp_Vec offset(a,origin);const double u=offset.Dot(cross)/determinant;
        if(u<0||u>1)continue;
        const auto q=offset.Crossed(edge1);const double v=direction.Dot(q)/determinant;
        if(v<0||u+v>1)continue;
        const double hit=edge2.Dot(q)/determinant;
        if(hit>=0&&hit<distance){distance=hit;result=i+1;}
    }
    return result;
}

Handle(MeshVS_Mesh) meshPresentation(const QJsonObject &asset, const QJsonArray &overrideColor) {
    Handle(MeshSource) source = new MeshSource(asset);
    Handle(MeshVS_Mesh) mesh = new MeshVS_Mesh;
    mesh->SetDataSource(source);
    mesh->GetDrawer()->SetBoolean(MeshVS_DA_DisplayNodes, false);
    mesh->GetDrawer()->SetBoolean(MeshVS_DA_Reflection, true);
    mesh->GetDrawer()->SetBoolean(MeshVS_DA_ColorReflection, true);
    mesh->GetDrawer()->SetBoolean(MeshVS_DA_SmoothShading, true);
    mesh->GetDrawer()->SetBoolean(MeshVS_DA_ShowEdges, false);
    mesh->GetDrawer()->SetInteger(MeshVS_DA_MaxFaceNodes, 3);
    mesh->AddBuilder(new MeshVS_MeshPrsBuilder(mesh), true);
    auto colors = asset.value("colors").toArray();
    if (overrideColor.size() == 3 || colors.size() == source->triangleCount()) {
        Handle(MeshVS_ElementalColorPrsBuilder) color = new MeshVS_ElementalColorPrsBuilder(mesh);
        for (int i = 0; i < source->triangleCount(); ++i) {
            auto rgb = overrideColor.size() == 3 ? overrideColor : colors[i].toArray();
            const double scale = overrideColor.size() == 3 ? 1.0 : 255.0;
            if (rgb.size() == 3)
                color->SetColor1(i + 1, Quantity_Color(rgb[0].toDouble() / scale, rgb[1].toDouble() / scale,
                                                       rgb[2].toDouble() / scale, Quantity_TOC_sRGB));
        }
        mesh->AddBuilder(color, false);
    }
    return mesh;
}

Standard_Boolean MeshSource::GetNodeNormal(Standard_Integer rank, Standard_Integer element, Standard_Real &x,
                                           Standard_Real &y, Standard_Real &z) const {
    if (rank < 1 || rank > 3 || element < 1 || element > int(triangles.size()))
        return false;
    const auto &normal = normals[triangles[element - 1][rank - 1]];
    x = normal.X();
    y = normal.Y();
    z = normal.Z();
    return true;
}
