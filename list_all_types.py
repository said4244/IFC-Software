import json
import os
import sys

import ifcopenshell


def extract_types(ifc_path: str) -> list[str]:
    model = ifcopenshell.open(ifc_path)

    # Keep only "real model objects" / physical building elements
    types_found = {
        inst.is_a()
        for inst in model
        if inst.is_a("IfcElement")
    }

    return sorted(types_found)


def analyze_ifc(ifc_path: str) -> dict:
    types_found = extract_types(ifc_path)

    return {
        "script": "list_all_types",
        "file_name": os.path.basename(ifc_path),
        "object_types": types_found,
        "count": len(types_found),
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