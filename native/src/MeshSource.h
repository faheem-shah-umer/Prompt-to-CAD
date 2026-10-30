#pragma once
#include <MeshVS_DataSource.hxx>
#include <MeshVS_Mesh.hxx>
#include <QJsonObject>
#include <vector>
#include <array>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>

class MeshSource : public MeshVS_DataSource {
  public:
    explicit MeshSource(const QJsonObject &);
    Standard_Boolean GetGeom(Standard_Integer, Standard_Boolean, TColStd_Array1OfReal &, Standard_Integer &,
                             MeshVS_EntityType &) const override;
    Standard_Boolean GetGeomType(Standard_Integer, Standard_Boolean, MeshVS_EntityType &) const override;
    Standard_Address GetAddr(Standard_Integer, Standard_Boolean) const override {
        return nullptr;
    }
    Standard_Boolean GetNodesByElement(Standard_Integer, TColStd_Array1OfInteger &,
                                       Standard_Integer &) const override;
    const TColStd_PackedMapOfInteger &GetAllNodes() const override {
        return nodes;
    }
    const TColStd_PackedMapOfInteger &GetAllElements() const override {
        return elements;
    }
    Standard_Boolean GetNodeNormal(Standard_Integer, Standard_Integer, Standard_Real &, Standard_Real &,
                                   Standard_Real &) const override;
    gp_Pnt triangleCentre(int id) const;
    int rayHit(const gp_Pnt &origin, const gp_Vec &direction, double &distance) const;
    int triangleCount() const {
        return int(triangles.size());
    }

  private:
    std::vector<gp_Pnt> points;
    std::vector<gp_Vec> normals;
    std::vector<std::array<int, 3>> triangles;
    TColStd_PackedMapOfInteger nodes, elements;
};
Handle(MeshVS_Mesh) meshPresentation(const QJsonObject &asset);
