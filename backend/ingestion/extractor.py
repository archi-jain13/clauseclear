import os
import io
import re
from pathlib import Path
from typing import Tuple, Dict, Any

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None

try:
    from PIL import Image
except ImportError:
    Image = None


def clean_extracted_text(text: str) -> str:
    """Sanitizes extracted document text, normalizes line breaks and whitespace."""
    if not text:
        return ""
    # Normalize carriage returns
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Remove multiple continuous blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove excessive horizontal spaces
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def extract_text_from_pdf(pdf_bytes: bytes) -> Tuple[str, Dict[str, Any]]:
    """
    Extracts text from PDF bytes using PyMuPDF.
    Returns (full_text, metadata).
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is not installed. Run `pip install pymupdf`.")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_texts = []
    metadata = {
        "page_count": len(doc),
        "title": doc.metadata.get("title", ""),
        "author": doc.metadata.get("author", ""),
        "pages": []
    }

    for page_num in range(len(doc)):
        page = doc[page_num]
        p_text = page.get_text("text")
        cleaned_page = clean_extracted_text(p_text)
        page_texts.append(cleaned_page)
        metadata["pages"].append({
            "page_number": page_num + 1,
            "char_count": len(cleaned_page)
        })

    full_text = "\n\n".join(page_texts)
    doc.close()
    return clean_extracted_text(full_text), metadata


def extract_text_from_image(image_bytes: bytes) -> Tuple[str, Dict[str, Any]]:
    """
    Fallback image extraction (placeholder / basic OCR support).
    """
    metadata = {"type": "image", "status": "processed"}
    try:
        import pytesseract
        if Image:
            img = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(img)
            return clean_extracted_text(text), metadata
    except Exception:
        pass
    
    return "Image OCR requires Tesseract installation on system.", metadata


def extract_text_from_file(filename: str, file_bytes: bytes) -> Tuple[str, Dict[str, Any]]:
    """
    Routes file based on extension and extracts text.
    Supports .pdf, .txt, .md, .png, .jpg, .jpeg
    """
    ext = Path(filename).suffix.lower()
    
    if ext == ".pdf":
        return extract_text_from_pdf(file_bytes)
    elif ext in [".txt", ".md", ".json", ".csv"]:
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1", errors="replace")
        return clean_extracted_text(text), {"type": "text", "filename": filename}
    elif ext in [".png", ".jpg", ".jpeg", ".tiff", ".bmp"]:
        return extract_text_from_image(file_bytes)
    else:
        # Attempt utf-8 decode
        try:
            text = file_bytes.decode("utf-8")
            return clean_extracted_text(text), {"type": "unknown", "filename": filename}
        except Exception as e:
            raise ValueError(f"Unsupported file format: {ext}. Error: {str(e)}")
