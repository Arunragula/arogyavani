# app/services/extractor.py
import io
import pymupdf  # PyMuPDF
import pymupdf4llm
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

ocr_engine = RapidOCR()


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
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="JPEG", quality=95)
    ocr_result, _ = ocr_engine(img_byte_arr.getvalue())
    return reconstruct_table_rows(ocr_result)


def extract_document_text(file_bytes: bytes, filename: str) -> dict:
    ext = filename.lower().split(".")[-1]

    if ext == "pdf":
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
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
            pix = page.get_pixmap(dpi=200)
            page_img_bytes = pix.tobytes("jpeg")
            page_text = extract_from_image_bytes(page_img_bytes)
            scanned_pages_text.append(f"--- Page {page_num + 1} ---\n{page_text}")

        return {
            "extraction_method": "scanned_pdf_ocr",
            "page_count": len(doc),
            "raw_text": "\n\n".join(scanned_pages_text),
        }

    elif ext in ["jpg", "jpeg", "png", "webp"]:
        text = extract_from_image_bytes(file_bytes)
        return {
            "extraction_method": "image_ocr",
            "page_count": 1,
            "raw_text": text,
        }
    else:
        raise ValueError(f"Unsupported file format in '{filename}'. Upload PDF, JPG, PNG, or WEBP.")


def extract_multiple_documents(files_data: list) -> dict:
    """
    Processes 1 to 10 uploaded images or PDFs and merges them into one combined report.
    files_data is a list of tuples: [(filename, file_bytes), ...]
    """
    combined_sections = []
    total_pages = 0
    methods_used = []

    for idx, (filename, file_bytes) in enumerate(files_data, start=1):
        res = extract_document_text(file_bytes, filename)
        total_pages += res["page_count"]
        methods_used.append(res["extraction_method"])
        combined_sections.append(
            f"=== UPLOADED FILE {idx}: {filename} ===\n{res['raw_text']}"
        )

    return {
        "files_processed": len(files_data),
        "total_pages": total_pages,
        "extraction_methods": list(set(methods_used)),
        "combined_raw_text": "\n\n".join(combined_sections),
    }