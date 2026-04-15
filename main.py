import os
import tempfile
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, HTTPException, UploadFile

from list_all_types import analyze_ifc as analyze_list_all_types


app = FastAPI(
    title="IFC Processing Service",
    version="0.1.0",
)


# Route key -> script function
SCRIPT_HANDLERS: dict[str, Callable[[str], dict]] = {
    "types": analyze_list_all_types,
}


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "available_routes": [f"/ifc/{name}" for name in SCRIPT_HANDLERS.keys()],
    }


@app.post("/ifc/{action}")
async def process_ifc(action: str, file: UploadFile = File(...)) -> dict:
    handler = SCRIPT_HANDLERS.get(action)
    if handler is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown action '{action}'. Available actions: {list(SCRIPT_HANDLERS.keys())}",
        )

    original_name = file.filename or "upload.ifc"
    suffix = Path(original_name).suffix.lower()

    if suffix != ".ifc":
        raise HTTPException(status_code=400, detail="Only .ifc files are supported.")

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
            temp_path = tmp.name

            # Save uploaded file in chunks
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)

        result = handler(temp_path)

        return {
            "success": True,
            "route": action,
            "uploaded_file_name": original_name,
            "result": result,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await file.close()

        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)