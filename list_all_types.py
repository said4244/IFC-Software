import json
import os
import sys
from typing import Any

import ifcopenshell


FILTER_RULES = [
    {
        "category": "foundations",
        "priority": "highest",
        "matches": ["IfcFooting", "IfcPile", "IfcDeepFoundation"],
        "why": (
            "Foundations are major structural/substructure cost drivers and are "
            "typically among the first items a cost estimator wants to capture."
        ),
    },
    {
        "category": "structural_frame",
        "priority": "highest",
        "matches": ["IfcBeam", "IfcColumn", "IfcMember", "IfcPlate"],
        "why": (
            "Structural frame elements are core load-bearing components with high "
            "cost impact and are central to model-based takeoff."
        ),
    },
    {
        "category": "slabs_floors",
        "priority": "highest",
        "matches": ["IfcSlab"],
        "why": (
            "Slabs and floors are major measurable building elements and strong cost "
            "drivers; some exporters also use IfcSlab for roof plates."
        ),
    },
    {
        "category": "walls_partitions",
        "priority": "highest",
        "matches": ["IfcWall"],
        "why": (
            "Walls and partitions are major envelope and space-separation elements "
            "that heavily influence quantities and cost."
        ),
    },
    {
        "category": "roofs",
        "priority": "highest",
        "matches": ["IfcRoof"],
        "why": (
            "Roofs are major envelope elements that affect weatherproofing, build-up, "
            "and overall building cost."
        ),
    },
    {
        "category": "openings_fenestration",
        "priority": "highest",
        "matches": ["IfcOpeningElement", "IfcDoor", "IfcWindow", "IfcCurtainWall"],
        "why": (
            "Openings, doors, windows, and curtain walls are highly estimator-relevant "
            "because they are specification-driven and materially affect takeoff and deductions."
        ),
    },
    {
        "category": "coverings_finishes",
        "priority": "high",
        "matches": ["IfcCovering"],
        "why": (
            "Coverings represent finishes such as floor finishes, cladding, and ceilings, "
            "which are often large-area and high-value cost items."
        ),
    },
    {
        "category": "mep_major",
        "priority": "high",
        "matches": ["IfcDistributionElement"],
        "why": (
            "Major MEP distribution elements are important cost drivers and often represent "
            "substantial quantity-based scope in building services."
        ),
    },
]


def match_rules_for_instance(inst: Any) -> list[dict[str, Any]]:
    matched_rules = []

    for rule in FILTER_RULES:
        if any(inst.is_a(class_name) for class_name in rule["matches"]):
            matched_rules.append(rule)

    return matched_rules


def extract_priority_types(ifc_path: str) -> dict[str, Any]:
    model = ifcopenshell.open(ifc_path)
    schema = model.schema

    selected_types: dict[str, dict[str, Any]] = {}

    for inst in model:
        matched_rules = match_rules_for_instance(inst)
        if not matched_rules:
            continue

        raw_type = inst.is_a()

        if raw_type not in selected_types:
            selected_types[raw_type] = {
                "ifc_type": raw_type,
                "priorities": set(),
                "categories": set(),
                "why_chosen": set(),
            }

        for rule in matched_rules:
            selected_types[raw_type]["priorities"].add(rule["priority"])
            selected_types[raw_type]["categories"].add(rule["category"])
            selected_types[raw_type]["why_chosen"].add(rule["why"])

    details = []
    for ifc_type in sorted(selected_types.keys()):
        item = selected_types[ifc_type]
        details.append(
            {
                "ifc_type": item["ifc_type"],
                "priorities": sorted(item["priorities"]),
                "categories": sorted(item["categories"]),
                "why_chosen": sorted(item["why_chosen"]),
            }
        )

    return {
        "ifc_schema": schema,
        "object_types": [item["ifc_type"] for item in details],
        "object_type_details": details,
        "count": len(details),
    }


def analyze_ifc(ifc_path: str) -> dict[str, Any]:
    result = extract_priority_types(ifc_path)

    return {
        "script": "list_all_types",
        "file_name": os.path.basename(ifc_path),
        "ifc_schema": result["ifc_schema"],
        "included_priorities": ["highest", "high"],
        "object_types": result["object_types"],
        "object_type_details": result["object_type_details"],
        "count": result["count"],
        "notes": [
            "This script only keeps Highest and High priority estimator-relevant IFC object families.",
            "It intentionally excludes medium/special-handling groups such as furniture, siteworks, and preliminaries.",
            "It returns the raw IFC class names found in the file after filtering, not simplified labels.",
        ],
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python list_all_types.py path/to/model.ifc")
        sys.exit(1)

    ifc_path = sys.argv[1]

    try:
        result = analyze_ifc(ifc_path)
        print(json.dumps(result, indent=2))
    except Exception as e:
        error_result = {
            "script": "list_all_types",
            "file_name": os.path.basename(ifc_path),
            "error": str(e),
        }
        print(json.dumps(error_result, indent=2))
        sys.exit(1)