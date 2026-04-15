import json
import os
import sys
from typing import Any

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as element_utils
import ifcopenshell.util.shape as shape_utils

try:
    import ifcopenshell.util.system as system_utils
except Exception:
    system_utils = None


def entity_ref(entity: Any) -> dict | None:
    if not entity:
        return None

    result = {
        "id": entity.id() if hasattr(entity, "id") else None,
        "ifc_type": entity.is_a() if hasattr(entity, "is_a") else type(entity).__name__,
    }

    if hasattr(entity, "GlobalId"):
        result["global_id"] = getattr(entity, "GlobalId", None)
    if hasattr(entity, "Name"):
        result["name"] = getattr(entity, "Name", None)

    return result


def make_json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(v) for v in value]
    if hasattr(value, "is_a"):
        return entity_ref(value)
    return str(value)


def round_if_number(value: Any, digits: int = 6) -> Any:
    if isinstance(value, (int, float)):
        return round(float(value), digits)
    return value


def flatten_numeric_values(data: Any, prefix: str = "") -> dict[str, float]:
    results = {}

    if isinstance(data, dict):
        for key, value in data.items():
            key_str = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (int, float)):
                results[key_str] = float(value)
            elif isinstance(value, dict):
                results.update(flatten_numeric_values(value, key_str))
            elif isinstance(value, list):
                continue

    return results


def pick_measure(qtos: dict, keywords: list[str]) -> float | None:
    numeric_values = flatten_numeric_values(qtos)

    for key, value in numeric_values.items():
        key_lower = key.lower()
        if all(keyword.lower() in key_lower for keyword in keywords):
            return round(float(value), 6)

    return None


def get_preferred_measures(qtos: dict, geometry: dict) -> dict:
    qto_length = (
        pick_measure(qtos, ["length"])
        or pick_measure(qtos, ["width"])
        or pick_measure(qtos, ["perimeter"])
    )
    qto_area = (
        pick_measure(qtos, ["net", "area"])
        or pick_measure(qtos, ["gross", "area"])
        or pick_measure(qtos, ["area"])
    )
    qto_volume = (
        pick_measure(qtos, ["net", "volume"])
        or pick_measure(qtos, ["gross", "volume"])
        or pick_measure(qtos, ["volume"])
    )

    return {
        "length": qto_length if qto_length is not None else geometry.get("total_edge_length"),
        "area": qto_area if qto_area is not None else geometry.get("surface_area"),
        "volume": qto_volume if qto_volume is not None else geometry.get("volume"),
    }


def get_material_info(element: Any) -> dict:
    material_info = {
        "primary_material": None,
        "all_materials": [],
    }

    try:
        primary = element_utils.get_material(
            element,
            should_skip_usage=True,
            should_inherit=True,
        )
        material_info["primary_material"] = entity_ref(primary)
    except Exception:
        material_info["primary_material"] = None

    try:
        materials = element_utils.get_materials(element, should_inherit=True)
        material_info["all_materials"] = [entity_ref(m) for m in materials]
    except Exception:
        material_info["all_materials"] = []

    return material_info


def get_container_info(element: Any) -> dict:
    result = {
        "container": None,
        "storey": None,
        "referenced_structures": [],
        "parent": None,
    }

    try:
        result["container"] = entity_ref(
            element_utils.get_container(element, should_get_direct=False)
        )
    except Exception:
        result["container"] = None

    try:
        result["storey"] = entity_ref(
            element_utils.get_container(
                element,
                should_get_direct=False,
                ifc_class="IfcBuildingStorey",
            )
        )
    except Exception:
        result["storey"] = None

    try:
        refs = element_utils.get_referenced_structures(element)
        result["referenced_structures"] = [entity_ref(x) for x in refs]
    except Exception:
        result["referenced_structures"] = []

    try:
        result["parent"] = entity_ref(element_utils.get_parent(element))
    except Exception:
        result["parent"] = None

    return result


def get_relationships_info(element: Any) -> dict:
    result = {
        "fills_void": None,
        "voids": [],
        "parts": [],
        "connected_to": [],
        "connected_from": [],
        "systems": [],
    }

    try:
        result["fills_void"] = entity_ref(element_utils.get_filled_void(element))
    except Exception:
        result["fills_void"] = None

    try:
        voids = []
        for rel in element_utils.get_openings(element):
            opening = getattr(rel, "RelatedOpeningElement", None)
            if opening:
                voids.append(entity_ref(opening))
        result["voids"] = voids
    except Exception:
        result["voids"] = []

    try:
        parts = element_utils.get_parts(element)
        result["parts"] = [entity_ref(x) for x in parts]
    except Exception:
        result["parts"] = []

    if system_utils is not None:
        try:
            result["connected_to"] = [
                entity_ref(x) for x in system_utils.get_connected_to(element)
            ]
        except Exception:
            result["connected_to"] = []

        try:
            result["connected_from"] = [
                entity_ref(x) for x in system_utils.get_connected_from(element)
            ]
        except Exception:
            result["connected_from"] = []

        try:
            result["systems"] = [
                entity_ref(x) for x in system_utils.get_element_systems(element)
            ]
        except Exception:
            result["systems"] = []

    return result


def get_geometry_info(element: Any) -> dict:
    geometry = {
        "bbox_x": None,
        "bbox_y": None,
        "bbox_z": None,
        "surface_area": None,
        "volume": None,
        "total_edge_length": None,
    }

    try:
        settings = ifcopenshell.geom.settings()
        shape = ifcopenshell.geom.create_shape(
            settings,
            element,
            geometry_library="hybrid-cgal-simple-opencascade",
        )
        geom = shape.geometry

        geometry["bbox_x"] = round_if_number(shape_utils.get_x(geom))
        geometry["bbox_y"] = round_if_number(shape_utils.get_y(geom))
        geometry["bbox_z"] = round_if_number(shape_utils.get_z(geom))
        geometry["surface_area"] = round_if_number(shape_utils.get_area(geom))
        geometry["volume"] = round_if_number(shape_utils.get_volume(geom))
        geometry["total_edge_length"] = round_if_number(
            shape_utils.get_total_edge_length(geom)
        )
    except Exception as e:
        geometry["geometry_error"] = str(e)

    return geometry


def extract_objects_for_type(ifc_path: str, object_type: str) -> dict:
    model = ifcopenshell.open(ifc_path)
    schema = model.schema

    matches = [
        inst
        for inst in model
        if hasattr(inst, "is_a")
        and inst.is_a("IfcElement")
        and inst.is_a(object_type)
    ]

    objects = []

    for element in matches:
        try:
            type_obj = element_utils.get_type(element)
        except Exception:
            type_obj = None

        try:
            psets = element_utils.get_psets(element, psets_only=True)
        except Exception:
            psets = {}

        try:
            qtos = element_utils.get_psets(element, qtos_only=True)
        except Exception:
            qtos = {}

        geometry = get_geometry_info(element)
        preferred = get_preferred_measures(qtos, geometry)

        obj = {
            "global_id": getattr(element, "GlobalId", None),
            "step_id": element.id(),
            "ifc_type": element.is_a(),
            "name": getattr(element, "Name", None),
            "description": getattr(element, "Description", None),
            "object_type_label": getattr(element, "ObjectType", None),
            "tag": getattr(element, "Tag", None),
            "predefined_type": None,
            "type_object": entity_ref(type_obj),
            "container_info": get_container_info(element),
            "material_info": get_material_info(element),
            "dimensions": {
                "x": geometry.get("bbox_x"),
                "y": geometry.get("bbox_y"),
                "z": geometry.get("bbox_z"),
            },
            "measures": {
                "length": preferred.get("length"),
                "area": preferred.get("area"),
                "volume": preferred.get("volume"),
            },
            "geometry": geometry,
            "relationships": get_relationships_info(element),
            "psets": make_json_safe(psets),
            "qtos": make_json_safe(qtos),
        }

        try:
            obj["predefined_type"] = element_utils.get_predefined_type(element)
        except Exception:
            obj["predefined_type"] = None

        objects.append(make_json_safe(obj))

    return {
        "script": "quantity-extractor",
        "file_name": os.path.basename(ifc_path),
        "ifc_schema": schema,
        "requested_object_type": object_type,
        "count": len(objects),
        "objects": objects,
        "notes": [
            "This is a best-effort extractor: not every IFC file contains authored quantities, materials, or connectivity.",
            "Where possible, measures fall back from quantity sets to geometry-derived values.",
            "bbox_x/y/z are geometry bounding-box style dimensions, not always the semantic length/width/height used by an estimator.",
        ],
    }


def analyze_ifc(ifc_path: str, object_type: str) -> dict:
    return extract_objects_for_type(ifc_path, object_type)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python quantity-extractor.py path/to/model.ifc IfcWall")
        sys.exit(1)

    ifc_path = sys.argv[1]
    object_type = sys.argv[2]

    try:
        result = analyze_ifc(ifc_path, object_type)
        print(json.dumps(result, indent=2))
    except Exception as e:
        error_result = {
            "script": "quantity-extractor",
            "file_name": os.path.basename(ifc_path),
            "requested_object_type": object_type,
            "error": str(e),
        }
        print(json.dumps(error_result, indent=2))
        sys.exit(1)