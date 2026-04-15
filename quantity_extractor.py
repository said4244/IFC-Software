import json
import math
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


OBJECT_EXTRACTION_PROFILES = {
    "IfcWall": {
        "family": "wall",
        "focus": [
            "wall_length",
            "wall_height",
            "wall_thickness",
            "gross_area",
            "net_area",
            "volume",
            "material",
            "type",
            "openings_in_wall",
        ],
    },
    "IfcWallStandardCase": {
        "family": "wall",
        "focus": [
            "wall_length",
            "wall_height",
            "wall_thickness",
            "gross_area",
            "net_area",
            "volume",
            "material",
            "type",
            "openings_in_wall",
        ],
    },
    "IfcSlab": {
        "family": "slab",
        "focus": [
            "plan_area",
            "thickness",
            "volume",
            "material",
            "type",
            "openings_in_slab",
        ],
    },
    "IfcCovering": {
        "family": "covering",
        "focus": [
            "covering_type",
            "area",
            "thickness",
            "volume",
            "material",
            "type",
        ],
    },
    "IfcDoor": {
        "family": "door",
        "focus": [
            "count",
            "width",
            "height",
            "thickness",
            "material",
            "type",
            "opening_relation",
        ],
    },
    "IfcWindow": {
        "family": "window",
        "focus": [
            "count",
            "width",
            "height",
            "thickness",
            "material",
            "type",
            "opening_relation",
        ],
    },
    "IfcFlowTerminal": {
        "family": "flow_terminal",
        "focus": [
            "count",
            "width",
            "depth",
            "height",
            "category",
            "material",
            "type",
            "system_relations",
        ],
    },
    "IfcOpeningElement": {
        "family": "opening",
        "focus": [
            "opening_width",
            "opening_height",
            "opening_depth",
            "opening_area",
            "host_wall",
            "filled_by",
        ],
    },
}


WALL_HOST_CLASSES = (
    "IfcWall",
    "IfcWallStandardCase",
    "IfcWallElementedCase",
    "IfcCurtainWall",
)

SLAB_HOST_CLASSES = (
    "IfcSlab",
    "IfcRoof",
)

RELEVANT_OPENING_HOST_CLASSES = WALL_HOST_CLASSES  # exclude sink/casework cutouts on purpose


def round_if_number(value: Any, digits: int = 6) -> Any:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return round(float(value), digits)
    return value


def safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    if b == 0:
        return None
    return round_if_number(a / b)


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


def flatten_numeric_values(data: Any, prefix: str = "") -> dict[str, float]:
    results = {}

    if isinstance(data, dict):
        for key, value in data.items():
            key_str = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (int, float)):
                results[key_str] = float(value)
            elif isinstance(value, dict):
                results.update(flatten_numeric_values(value, key_str))

    return results


def pick_numeric(source: dict, keyword_groups: list[list[str]]) -> float | None:
    numeric_values = flatten_numeric_values(source)

    for keywords in keyword_groups:
        for key, value in numeric_values.items():
            key_lower = key.lower()
            if all(keyword.lower() in key_lower for keyword in keywords):
                return round_if_number(value)

    return None


def first_non_null(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def get_type_info(element: Any) -> dict:
    type_obj = None
    try:
        type_obj = element_utils.get_type(element)
    except Exception:
        type_obj = None

    return {
        "type_object": entity_ref(type_obj),
        "type_name": getattr(type_obj, "Name", None) if type_obj else None,
        "object_type_label": getattr(element, "ObjectType", None),
    }


def get_material_info(element: Any) -> dict:
    primary_material = None
    all_materials = []

    try:
        primary_material = element_utils.get_material(
            element,
            should_skip_usage=True,
            should_inherit=True,
        )
    except Exception:
        primary_material = None

    try:
        mats = element_utils.get_materials(element, should_inherit=True)
        all_materials = [entity_ref(m) for m in mats]
    except Exception:
        all_materials = []

    material_names = [m.get("name") for m in all_materials if isinstance(m, dict) and m.get("name")]

    primary_material_name = None
    if primary_material and getattr(primary_material, "Name", None):
        primary_material_name = getattr(primary_material, "Name", None)
    elif material_names:
        primary_material_name = material_names[0]

    return {
        "primary_material": entity_ref(primary_material),
        "primary_material_name": primary_material_name,
        "all_materials": all_materials,
        "material_names": material_names,
    }


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


def get_geometry_info(element: Any) -> dict:
    geometry = {
        "bbox_x": None,
        "bbox_y": None,
        "bbox_z": None,
        "surface_area": None,
        "volume": None,
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
    except Exception as e:
        geometry["geometry_error"] = str(e)

    return geometry


def get_psets_qtos(element: Any) -> tuple[dict, dict]:
    try:
        psets = element_utils.get_psets(element, psets_only=True)
    except Exception:
        psets = {}

    try:
        qtos = element_utils.get_psets(element, qtos_only=True)
    except Exception:
        qtos = {}

    return psets, qtos


def get_predefined_type(element: Any) -> Any:
    try:
        return element_utils.get_predefined_type(element)
    except Exception:
        return None


def get_parent_element(element: Any) -> Any:
    try:
        return element_utils.get_parent(element)
    except Exception:
        return None


def get_fills_opening(element: Any) -> dict | None:
    try:
        return entity_ref(element_utils.get_filled_void(element))
    except Exception:
        return None


def get_opening_fillers(opening: Any) -> list[dict]:
    fillers = []
    for rel in getattr(opening, "HasFillings", []) or []:
        filled = getattr(rel, "RelatedBuildingElement", None)
        if filled:
            fillers.append(entity_ref(filled))
    return fillers


def is_relevant_opening(opening: Any) -> bool:
    parent = get_parent_element(opening)
    fillers = get_opening_fillers(opening)

    if parent and any(parent.is_a(cls) for cls in RELEVANT_OPENING_HOST_CLASSES):
        return True

    for filler in fillers:
        filler_type = filler.get("ifc_type")
        if filler_type in ("IfcDoor", "IfcWindow"):
            return True

    return False


def opening_semantics(opening: Any) -> dict:
    geometry = get_geometry_info(opening)
    parent = get_parent_element(opening)
    fillers = get_opening_fillers(opening)

    x = geometry.get("bbox_x")
    y = geometry.get("bbox_y")
    z = geometry.get("bbox_z")
    volume = geometry.get("volume")

    width = None
    depth = None
    height = None

    if parent and any(parent.is_a(cls) for cls in WALL_HOST_CLASSES):
        horizontal_dims = [v for v in [x, y] if isinstance(v, (int, float))]
        if horizontal_dims:
            width = round_if_number(max(horizontal_dims))
            depth = round_if_number(min(horizontal_dims))
        height = z
    else:
        width = x
        depth = y
        height = z

    opening_area = None
    if width is not None and height is not None:
        opening_area = round_if_number(width * height)

    return {
        "global_id": getattr(opening, "GlobalId", None),
        "step_id": opening.id(),
        "ifc_type": opening.is_a(),
        "name": getattr(opening, "Name", None),
        "tag": getattr(opening, "Tag", None),
        "host_element": entity_ref(parent),
        "filled_by": fillers,
        "dimensions": {
            "width": round_if_number(width),
            "height": round_if_number(height),
            "depth": round_if_number(depth),
        },
        "estimator_values": {
            "opening_width": round_if_number(width),
            "opening_height": round_if_number(height),
            "opening_depth": round_if_number(depth),
            "opening_area": round_if_number(opening_area),
            "opening_volume": round_if_number(volume),
        },
        "geometry": geometry,
    }


def get_openings_for_host(element: Any, relevant_only: bool = False) -> list[dict]:
    results = []

    try:
        rels = element_utils.get_openings(element)
    except Exception:
        rels = []

    for rel in rels:
        opening = getattr(rel, "RelatedOpeningElement", None)
        if not opening:
            continue

        if relevant_only and not is_relevant_opening(opening):
            continue

        results.append(opening_semantics(opening))

    return results


def get_system_info(element: Any) -> dict:
    result = {
        "connected_to": [],
        "connected_from": [],
        "systems": [],
    }

    if system_utils is None:
        return result

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


def get_category_from_psets(psets: dict) -> Any:
    for group_name, group_values in psets.items():
        if isinstance(group_values, dict):
            if "Category" in group_values:
                return group_values["Category"]
    return None


def profile_for_element(element: Any) -> dict:
    for ifc_type, profile in OBJECT_EXTRACTION_PROFILES.items():
        if element.is_a(ifc_type):
            return {
                "requested_type": ifc_type,
                **profile,
            }

    return {
        "requested_type": element.is_a(),
        "family": "generic",
        "focus": [
            "dimensions",
            "volume",
            "material",
            "type",
            "relations",
        ],
    }


def extract_wall_data(element: Any, geometry: dict, psets: dict, qtos: dict) -> dict:
    x = geometry.get("bbox_x")
    y = geometry.get("bbox_y")
    z = geometry.get("bbox_z")
    volume = geometry.get("volume")

    horizontal = [v for v in [x, y] if isinstance(v, (int, float))]
    wall_length = max(horizontal) if horizontal else None
    wall_thickness = min(horizontal) if horizontal else None
    wall_height = z

    qto_wall_length = pick_numeric(qtos, [["length"]])
    qto_wall_height = pick_numeric(qtos, [["height"]])
    qto_wall_thickness = pick_numeric(qtos, [["width"], ["thickness"]])
    qto_gross_area = pick_numeric(qtos, [["gross", "area"], ["area"]])
    qto_net_area = pick_numeric(qtos, [["net", "area"]])
    qto_volume = pick_numeric(qtos, [["net", "volume"], ["gross", "volume"], ["volume"]])

    wall_length = first_non_null(qto_wall_length, round_if_number(wall_length))
    wall_height = first_non_null(qto_wall_height, round_if_number(wall_height))
    wall_thickness = first_non_null(qto_wall_thickness, round_if_number(wall_thickness))
    volume = first_non_null(qto_volume, round_if_number(volume))

    gross_area = first_non_null(
        qto_gross_area,
        round_if_number(wall_length * wall_height) if wall_length is not None and wall_height is not None else None,
    )

    net_area = first_non_null(
        qto_net_area,
        safe_div(volume, wall_thickness),
    )

    openings_in_wall = get_openings_for_host(element, relevant_only=True)
    opening_area_total = round_if_number(
        sum(
            op.get("estimator_values", {}).get("opening_area") or 0
            for op in openings_in_wall
        )
    )

    if net_area is None and gross_area is not None:
        net_area = round_if_number(gross_area - opening_area_total)

    return {
        "estimator_values": {
            "wall_length": wall_length,
            "wall_height": wall_height,
            "wall_thickness": wall_thickness,
            "gross_area": gross_area,
            "net_area": net_area,
            "volume": volume,
            "opening_count": len(openings_in_wall),
            "opening_area_total": opening_area_total,
        },
        "openings_in_wall": openings_in_wall,
    }


def extract_slab_data(element: Any, geometry: dict, qtos: dict) -> dict:
    x = geometry.get("bbox_x")
    y = geometry.get("bbox_y")
    z = geometry.get("bbox_z")
    volume = first_non_null(
        pick_numeric(qtos, [["net", "volume"], ["gross", "volume"], ["volume"]]),
        geometry.get("volume"),
    )

    thickness = first_non_null(
        pick_numeric(qtos, [["thickness"], ["depth"]]),
        round_if_number(z),
    )

    gross_plan_area_approx = None
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        gross_plan_area_approx = round_if_number(x * y)

    net_plan_area = first_non_null(
        pick_numeric(qtos, [["net", "area"], ["gross", "area"], ["area"]]),
        safe_div(volume, thickness),
    )

    openings_in_slab = get_openings_for_host(element, relevant_only=False)

    return {
        "estimator_values": {
            "plan_length": round_if_number(x),
            "plan_width": round_if_number(y),
            "thickness": round_if_number(thickness),
            "gross_plan_area_approx": gross_plan_area_approx,
            "net_plan_area": round_if_number(net_plan_area),
            "volume": round_if_number(volume),
            "opening_count": len(openings_in_slab),
        },
        "openings_in_slab": openings_in_slab,
    }


def extract_covering_data(element: Any, geometry: dict, qtos: dict, predefined_type: Any) -> dict:
    x = geometry.get("bbox_x")
    y = geometry.get("bbox_y")
    z = geometry.get("bbox_z")
    volume = first_non_null(
        pick_numeric(qtos, [["net", "volume"], ["gross", "volume"], ["volume"]]),
        geometry.get("volume"),
    )

    thickness = first_non_null(
        pick_numeric(qtos, [["thickness"], ["depth"], ["width"]]),
        round_if_number(z),
    )

    gross_area_approx = None
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        gross_area_approx = round_if_number(x * y)

    net_area = first_non_null(
        pick_numeric(qtos, [["net", "area"], ["gross", "area"], ["area"]]),
        safe_div(volume, thickness),
    )

    return {
        "estimator_values": {
            "covering_type": predefined_type,
            "covering_length": round_if_number(x),
            "covering_width": round_if_number(y),
            "thickness": round_if_number(thickness),
            "gross_area_approx": gross_area_approx,
            "net_area": round_if_number(net_area),
            "volume": round_if_number(volume),
        }
    }


def extract_door_window_data(element: Any, geometry: dict, kind: str) -> dict:
    x = geometry.get("bbox_x")
    y = geometry.get("bbox_y")
    z = geometry.get("bbox_z")

    opening = None
    host_element = None
    try:
        opening_obj = element_utils.get_filled_void(element)
        opening = entity_ref(opening_obj)
        if opening_obj:
            host_element = entity_ref(get_parent_element(opening_obj))
    except Exception:
        opening = None
        host_element = None

    return {
        "estimator_values": {
            "count": 1,
            "width": round_if_number(x),
            "height": round_if_number(z),
            "thickness": round_if_number(y),
            "gross_face_area": round_if_number(x * z) if x is not None and z is not None else None,
            "volume": round_if_number(geometry.get("volume")),
        },
        "opening_relation": {
            "fills_opening": opening,
            "host_element": host_element,
        },
        "element_kind": kind,
    }


def extract_flow_terminal_data(element: Any, geometry: dict, psets: dict) -> dict:
    x = geometry.get("bbox_x")
    y = geometry.get("bbox_y")
    z = geometry.get("bbox_z")

    manufacturer = None
    for group_values in psets.values():
        if isinstance(group_values, dict) and "Manufacturer" in group_values:
            manufacturer = group_values.get("Manufacturer")
            break

    return {
        "estimator_values": {
            "count": 1,
            "width": round_if_number(x),
            "depth": round_if_number(y),
            "height": round_if_number(z),
            "gross_face_area": round_if_number(x * z) if x is not None and z is not None else None,
            "volume": round_if_number(geometry.get("volume")),
            "category": get_category_from_psets(psets),
            "manufacturer": manufacturer,
        },
        "system_relations": get_system_info(element),
    }


def extract_opening_data(element: Any, geometry: dict) -> dict:
    parent = get_parent_element(element)
    fillers = get_opening_fillers(element)

    x = geometry.get("bbox_x")
    y = geometry.get("bbox_y")
    z = geometry.get("bbox_z")

    horizontal = [v for v in [x, y] if isinstance(v, (int, float))]
    opening_width = max(horizontal) if horizontal else None
    opening_depth = min(horizontal) if horizontal else None
    opening_height = z

    return {
        "estimator_values": {
            "opening_width": round_if_number(opening_width),
            "opening_height": round_if_number(opening_height),
            "opening_depth": round_if_number(opening_depth),
            "opening_area": round_if_number(opening_width * opening_height)
            if opening_width is not None and opening_height is not None
            else None,
            "opening_volume": round_if_number(geometry.get("volume")),
        },
        "opening_relation": {
            "host_element": entity_ref(parent),
            "filled_by": fillers,
        },
    }


def extract_generic_data(element: Any, geometry: dict) -> dict:
    return {
        "estimator_values": {
            "bbox_x": round_if_number(geometry.get("bbox_x")),
            "bbox_y": round_if_number(geometry.get("bbox_y")),
            "bbox_z": round_if_number(geometry.get("bbox_z")),
            "surface_area": round_if_number(geometry.get("surface_area")),
            "volume": round_if_number(geometry.get("volume")),
        }
    }


def enrich_element(element: Any) -> dict:
    geometry = get_geometry_info(element)
    psets, qtos = get_psets_qtos(element)
    predefined_type = get_predefined_type(element)
    profile = profile_for_element(element)

    base = {
        "global_id": getattr(element, "GlobalId", None),
        "step_id": element.id(),
        "ifc_type": element.is_a(),
        "name": getattr(element, "Name", None),
        "description": getattr(element, "Description", None),
        "tag": getattr(element, "Tag", None),
        "predefined_type": predefined_type,
        "profile_used": profile,
        "type_info": get_type_info(element),
        "container_info": get_container_info(element),
        "material_info": get_material_info(element),
        "geometry_bbox": {
            "x": round_if_number(geometry.get("bbox_x")),
            "y": round_if_number(geometry.get("bbox_y")),
            "z": round_if_number(geometry.get("bbox_z")),
        },
        "raw_geometry": {
            "surface_area": round_if_number(geometry.get("surface_area")),
            "volume": round_if_number(geometry.get("volume")),
            "geometry_error": geometry.get("geometry_error"),
        },
        "psets": make_json_safe(psets),
        "qtos": make_json_safe(qtos),
    }

    if element.is_a("IfcWall"):
        base.update(extract_wall_data(element, geometry, psets, qtos))
    elif element.is_a("IfcSlab"):
        base.update(extract_slab_data(element, geometry, qtos))
    elif element.is_a("IfcCovering"):
        base.update(extract_covering_data(element, geometry, qtos, predefined_type))
    elif element.is_a("IfcDoor"):
        base.update(extract_door_window_data(element, geometry, "door"))
    elif element.is_a("IfcWindow"):
        base.update(extract_door_window_data(element, geometry, "window"))
    elif element.is_a("IfcFlowTerminal"):
        base.update(extract_flow_terminal_data(element, geometry, psets))
    elif element.is_a("IfcOpeningElement"):
        base.update(extract_opening_data(element, geometry))
    else:
        base.update(extract_generic_data(element, geometry))

    return make_json_safe(base)


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
        if element.is_a("IfcOpeningElement") and not is_relevant_opening(element):
            continue

        objects.append(enrich_element(element))

    requested_profile = OBJECT_EXTRACTION_PROFILES.get(
        object_type,
        {
            "family": "generic",
            "focus": [
                "dimensions",
                "volume",
                "material",
                "type",
                "relations",
            ],
        },
    )

    notes = [
        "This extractor is type-aware and returns semantic estimator values instead of one generic length field.",
        "Doors and windows return count, width, height, thickness, materials, type data, and opening relation.",
        "Walls return wall_length, wall_height, wall_thickness, gross/net area, volume, and openings_in_wall.",
        "IfcOpeningElement is filtered to relevant wall/window/door openings and excludes sink/casework cutouts.",
        "Some IFC files still will not contain authored quantities or ideal semantics, so geometry is used as fallback.",
    ]

    if object_type == "IfcOpeningElement":
        notes.append(
            "Only openings hosted by wall-like elements or filled by doors/windows are included."
        )

    return {
        "script": "quantity-extractor",
        "file_name": os.path.basename(ifc_path),
        "ifc_schema": schema,
        "requested_object_type": object_type,
        "requested_profile": requested_profile,
        "count": len(objects),
        "objects": objects,
        "notes": notes,
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