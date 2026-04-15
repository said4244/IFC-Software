import os
import tempfile
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request

from list_all_types import analyze_ifc as analyze_list_all_types

from quantity_extractor import analyze_ifc as analyze_quantity_ifc



app = FastAPI(
    title="IFC Processing Service",
    version="0.1.0",
)

SCRIPT_HANDLERS: dict[str, Callable[[str], dict]] = {
    "types": analyze_list_all_types,
}


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "available_routes": [f"/ifc/{name}" for name in SCRIPT_HANDLERS.keys()],
    }

@app.post("/ifc/object-quantity-extraction")
async def object_quantity_extraction(request: Request, object_type: str) -> dict:
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        raise HTTPException(
            status_code=400,
            detail="This endpoint expects raw binary IFC upload, not multipart/form-data.",
        )

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body.")

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
            temp_path = tmp.name
            tmp.write(body)

        result = analyze_quantity_ifc(temp_path, object_type)

        return {
            "success": True,
            "route": "object-quantity-extraction",
            "content_type": content_type,
            "result": result,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

@app.post("/ifc/{action}")
async def process_ifc(action: str, request: Request) -> dict:
    handler = SCRIPT_HANDLERS.get(action)
    if handler is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown action '{action}'. Available actions: {list(SCRIPT_HANDLERS.keys())}",
        )

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        raise HTTPException(
            status_code=400,
            detail="This endpoint expects raw binary IFC upload, not multipart/form-data.",
        )

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body.")

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
            temp_path = tmp.name
            tmp.write(body)

        result = handler(temp_path)

        return {
            "success": True,
            "route": action,
            "content_type": content_type,
            "result": result,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)