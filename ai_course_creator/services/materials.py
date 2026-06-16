"""
Extract plain text from course materials shared during Phase 3.

Supports uploaded files (PDF / DOCX / PPTX / plain text), pasted text, and a
best-effort fetch of public URLs. The extracted text is stored on
:class:`ai_course_creator.models.UploadedMaterial` and fed to Gemini as context.
"""

import logging

log = logging.getLogger(__name__)

# Cap extracted text *stored* per material so a single huge upload can't blow up
# the database row.
MAX_TEXT_CHARS = 200_000

# Cap the total materials text *sent to the model* in one request. The LLM has a
# hard per-request token budget (Groq returns HTTP 413 above it), and the system
# prompt + conversation already consume part of it. ~16k chars ≈ 4k tokens.
# Overridable via the AI_COURSE_CREATOR_MAX_CONTEXT_CHARS setting.
DEFAULT_MAX_CONTEXT_CHARS = 16_000


def _truncate(text):
    if text and len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS] + "\n\n[...truncated...]"
    return text or ""


def extract_from_pdf(file_obj):
    from pypdf import PdfReader

    reader = PdfReader(file_obj)
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # pylint: disable=broad-except
            log.warning("ai_course_creator: failed to extract a PDF page")
    return _truncate("\n\n".join(pages))


def extract_from_docx(file_obj):
    from docx import Document

    document = Document(file_obj)
    paragraphs = [p.text for p in document.paragraphs if p.text]
    return _truncate("\n".join(paragraphs))


def extract_from_pptx(file_obj):
    from pptx import Presentation

    presentation = Presentation(file_obj)
    chunks = []
    for index, slide in enumerate(presentation.slides, start=1):
        slide_lines = [f"Slide {index}:"]
        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    line = "".join(run.text for run in paragraph.runs)
                    if line:
                        slide_lines.append(line)
        chunks.append("\n".join(slide_lines))
    return _truncate("\n\n".join(chunks))


def extract_from_plain_text(file_obj):
    data = file_obj.read()
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    return _truncate(data)


# Map of lowercased file extension -> extractor function.
_EXTRACTORS = {
    ".pdf": extract_from_pdf,
    ".docx": extract_from_docx,
    ".pptx": extract_from_pptx,
    ".txt": extract_from_plain_text,
    ".md": extract_from_plain_text,
}

SUPPORTED_EXTENSIONS = tuple(_EXTRACTORS.keys())


def extract_from_upload(filename, file_obj):
    """
    Extract text from an uploaded file based on its extension.

    Args:
        filename: original filename (used to detect the type).
        file_obj: a file-like object opened in binary mode.

    Returns:
        Extracted plain text (possibly empty).

    Raises:
        ValueError: if the file type is unsupported.
    """
    lowered = (filename or "").lower()
    for extension, extractor in _EXTRACTORS.items():
        if lowered.endswith(extension):
            return extractor(file_obj)
    raise ValueError(
        f"Unsupported file type for '{filename}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}."
    )


def extract_from_url(url):
    """
    Best-effort fetch + text extraction for a public URL.

    HTML is stripped to readable text. Returns a short note on failure rather
    than raising, so a bad link never breaks the chat flow.
    """
    try:
        import requests

        response = requests.get(url, timeout=15, headers={"User-Agent": "Sherab-CourseCreator/1.0"})
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "html" in content_type:
            return _truncate(_html_to_text(response.text))
        if "pdf" in content_type:
            import io

            return extract_from_pdf(io.BytesIO(response.content))
        return _truncate(response.text)
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("ai_course_creator: failed to fetch URL %s: %s", url, exc)
        return f"[Could not automatically read {url}. The creator may describe it instead.]"


def _html_to_text(html):
    """Very small HTML -> text reduction without heavy dependencies."""
    import re

    # Drop script/style blocks, then tags, then collapse whitespace.
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _max_context_chars():
    try:
        from django.conf import settings

        return int(getattr(settings, "AI_COURSE_CREATOR_MAX_CONTEXT_CHARS", DEFAULT_MAX_CONTEXT_CHARS))
    except Exception:  # pylint: disable=broad-except
        return DEFAULT_MAX_CONTEXT_CHARS


def build_names_summary(materials):
    """
    Build a lightweight, names-only summary of shared materials for the *chat*.

    During the conversation (persona, transformation, assessment) Sherab only
    needs to know *what* the creator uploaded so it can acknowledge it — not the
    full extracted text. The heavy text is sent only at generation time (see
    :func:`build_context`), which keeps every chat request small.
    """
    names = [getattr(m, "name", "material") for m in materials]
    if not names:
        return ""
    return "The creator has uploaded these materials: " + "; ".join(names) + "."


def build_context(materials):
    """
    Build a single plain-text digest from a queryset/iterable of
    :class:`UploadedMaterial` for inclusion in the model prompt.

    The combined text is capped at ``_max_context_chars()`` so the request stays
    within the model's per-request token budget. Each material gets a fair share
    of the budget, so one giant upload can't crowd out the others.
    """
    materials = list(materials)
    with_text = [m for m in materials if getattr(m, "extracted_text", "") or ""]
    if not with_text:
        return ""

    budget = _max_context_chars()
    per_material = max(500, budget // len(with_text))
    blocks = []
    for material in with_text:
        label = getattr(material, "name", "material")
        text = getattr(material, "extracted_text", "") or ""
        if len(text) > per_material:
            text = text[:per_material] + "\n[…trimmed for length…]"
        blocks.append(f"--- {label} ---\n{text}")
    return "\n\n".join(blocks)
