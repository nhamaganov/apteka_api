from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.pharmeconom_client import PharmeconomClient, PharmeconomClientError
from app.utils.xls import extract_product_codes_from_excel

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/product-info/by-excel")
async def get_product_info_by_excel(file: UploadFile = File(...)):
    """Принимает Excel, извлекает столбец 'Код товара' и возвращает информацию по каждому товару."""
    ext = Path(file.filename or "upload.xlsx").suffix.lower()
    if ext not in {".xls", ".xlsx", ".ods"}:
        raise HTTPException(status_code=400, detail="Upload .xls, .xlsx or .ods file")

    content = await file.read()
    tmp_path: Path | None = None
    with NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        try:
            rows = extract_product_codes_from_excel(str(tmp_path))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to parse excel: {exc}") from exc

        try:
            client = PharmeconomClient()
        except PharmeconomClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        items: list[dict] = []
        ok_count = 0
        error_count = 0

        for row in rows:
            product_code = row["product_code"]
            try:
                api_response = client.get_product_info(product_code)
                items.append({
                    **row,
                    "status": "ok",
                    "api_response": api_response,
                    "products": api_response.get("data", []),
                })
                ok_count += 1
            except PharmeconomClientError as exc:
                items.append({
                    **row,
                    "status": "error",
                    "error": str(exc),
                    "products": [],
                })
                error_count += 1

        return {
            "status": "ok",
            "filename": file.filename,
            "total": len(rows),
            "success": ok_count,
            "errors": error_count,
            "items": items,
        }
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
