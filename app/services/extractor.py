# app/services/extractor.py
import io
import pymupdf  # PyMuPDF
import pymupdf4llm
from PIL import Image
from fastapi import HTTPException
from rapidocr_onnxruntime import RapidOCR

ocr_engine = RapidOCR()

MAX_FILES_PER_REQUEST = 5
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB per file
MAX_PDF_PAGES = 5                       # Protects 512 MB RAM on Render


def verify_file_safety_and_magic_bytes(filename: str, file_bytes: bytes) -> str:
    """
    Validates file size (<= 10 MB) and inspects actual file magic bytes
    so malicious files renamed as .jpg or .pdf are rejected with HTTP 400.
    """
    if not file_bytes:
        raise HTTPException(status_code=400, detail=f"File '{filename}' is empty.")

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File '{filename}' exceeds the 10 MB size limit.",
        )

    header = file_bytes[:12]
    if header.startswith(b"%PDF-"):
        return "pdf"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported or corrupted file '{filename}'. Please upload a genuine PDF, JPG, PNG, or WEBP file.",
    )


def reconstruct_table_rows(ocr_results) -> str:
    if not ocr_results:
        return ""

    items = []
    for box, text, score in ocr_results:
        x0, y0 = box[0][0], box[0][1]
        y2 = box[2][1]
        height = max(abs(y2 - y0), 8)
        y_center = y0 + (height / 2.0)

        items.append({
            "x": x0,
            "y_center": y_center,
            "height": height,
            "text": text.strip(),
        })

    items.sort(key=lambda item: item["y_center"])

    rows = []
    current_row = [items[0]]
    row_anchor_y = items[0]["y_center"]
    row_tolerance = items[0]["height"] * 0.55

    for item in items[1:]:
        if abs(item["y_center"] - row_anchor_y) <= row_tolerance:
            current_row.append(item)
            row_anchor_y = sum(x["y_center"] for x in current_row) / len(current_row)
        else:
            current_row.sort(key=lambda x: x["x"])
            rows.append(" | ".join([col["text"] for col in current_row]))
            current_row = [item]
            row_anchor_y = item["y_center"]
            row_tolerance = item["height"] * 0.55

    if current_row:
        current_row.sort(key=lambda x: x["x"])
        rows.append(" | ".join([col["text"] for col in current_row]))

    return "\n".join(rows)


def extract_from_image_bytes(image_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    # Cap OCR resolution to 1800px so 12MP phone photos don't spike RAM on Render
    if max(img.size) > 1800:
        scale = 1800 / float(max(img.size))
        img = img.resize((int(img.size[0] * scale), int(img.size[1] * scale)), Image.Resampling.LANCZOS)

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="JPEG", quality=90)
    ocr_result, _ = ocr_engine(img_byte_arr.getvalue())
    return reconstruct_table_rows(ocr_result)


def extract_document_text(file_bytes: bytes, filename: str) -> dict:
    detected_type = verify_file_safety_and_magic_bytes(filename, file_bytes)

    if detected_type == "pdf":
        try:
            doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        except Exception:
            raise HTTPException(status_code=400, detail=f"Could not open PDF '{filename}'.")

        if len(doc) > MAX_PDF_PAGES:
            raise HTTPException(
                status_code=400,
                detail=f"PDF '{filename}' has {len(doc)} pages. Maximum {MAX_PDF_PAGES} pages allowed per PDF.",
            )

        md_text = pymupdf4llm.to_markdown(doc)
        if len(md_text.strip()) > 50:
            return {
                "extraction_method": "digital_pdf_markdown",
                "page_count": len(doc),
                "raw_text": md_text,
            }

        scanned_pages_text = []
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=160)
            page_img_bytes = pix.tobytes("jpeg")
            page_text = extract_from_image_bytes(page_img_bytes)
            scanned_pages_text.append(f"--- Page {page_num + 1} ---\n{page_text}")

        return {
            "extraction_method": "scanned_pdf_ocr",
            "page_count": len(doc),
            "raw_text": "\n\n".join(scanned_pages_text),
        }

    else:
        text = extract_from_image_bytes(file_bytes)
        return {
            "extraction_method": "image_ocr",
            "page_count": 1,
            "raw_text": text,
        }


def extract_multiple_documents(files_data: list) -> dict:
    if len(files_data) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_FILES_PER_REQUEST} files allowed per request.",
        )

    combined_sections = []
    total_pages = 0

    for idx, (filename, file_bytes) in enumerate(files_data, start=1):
        res = extract_document_text(file_bytes, filename)
        total_pages += res["page_count"]
        if total_pages > MAX_PDF_PAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Total pages across uploaded files cannot exceed {MAX_PDF_PAGES}.",
            )
        combined_sections.append(f"=== DOCUMENT {idx} ===\n{res['raw_text']}")

    return {
        "files_processed": len(files_data),
        "total_pages": total_pages,
        "combined_raw_text": "\n\n".join(combined_sections),
    }