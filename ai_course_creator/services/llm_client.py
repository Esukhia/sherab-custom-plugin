"""
Thin wrapper around the Gemini API (google-genai SDK) for the Sherab course-creator chatbot.

The bundled skill (``skill/SKILL.md`` + ``skill/references/*.md``) is used as the
system instruction so the model behaves exactly like the "Sherab" persona.

Credentials come from Django settings (``GEMINI_API_KEY`` / ``GEMINI_MODEL``),
which Tutor injects from ``config.yml``. See settings/common.py.

Uses the ``google-genai`` package (the replacement for the deprecated
``google-generativeai`` package).
"""

import logging
import os
import time
from functools import lru_cache

from django.conf import settings

log = logging.getLogger(__name__)

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(PLUGIN_DIR, "skill")

# Legacy markers — kept so existing callers don't break.
COURSE_JSON_START = "===COURSE_JSON_START==="
COURSE_JSON_END = "===COURSE_JSON_END==="

# Section-editor markers: the per-section editor emits the full desired section
# tree between these so the backend can apply it. Mirrors the COURSE_JSON idiom.
SECTION_EDITS_START = "===SECTION_EDITS_START==="
SECTION_EDITS_END = "===SECTION_EDITS_END==="

# Phase marker regex (lazy-initialised).
PHASE_MARKER_RE = None


def _phase_re():
    global PHASE_MARKER_RE  # pylint: disable=global-statement
    if PHASE_MARKER_RE is None:
        import re  # pylint: disable=import-outside-toplevel
        PHASE_MARKER_RE = re.compile(r"===SHERAB_PHASE:(\d+)===")
    return PHASE_MARKER_RE


def extract_phase_marker(text):
    """Return the phase number embedded in text, or None."""
    m = _phase_re().search(text)
    return int(m.group(1)) if m else None


def strip_phase_marker(text):
    """Remove ===SHERAB_PHASE:N=== markers from text."""
    return _phase_re().sub("", text).strip()


class LLMNotConfigured(Exception):
    """Raised when no API key is available."""


class LLMError(Exception):
    """Raised for an LLM API failure, with a user-friendly message."""


@lru_cache(maxsize=8)
def _load_system_instruction(skill_name="skill"):
    """
    Build the system instruction from a bundled skill directory.

    ``skill_name`` selects which skill dir under the plugin to load (e.g. "skill"
    for the 5-phase course creator, "skill_section_editor" for the per-section
    editor). Cached per skill_name for the process lifetime.
    """
    import re as _re  # pylint: disable=import-outside-toplevel
    parts = []
    skill_dir = os.path.join(PLUGIN_DIR, skill_name)
    skill_md = os.path.join(skill_dir, "SKILL.md")
    try:
        with open(skill_md, encoding="utf-8") as handle:
            raw = handle.read()
        stripped = _re.sub(r"^---\n.*?\n---\n", "", raw, flags=_re.DOTALL)
        parts.append(stripped)
    except OSError:
        log.exception("ai_course_creator: could not read SKILL.md at %s", skill_md)
        parts.append(
            "You are Sherab, a warm course-design companion inside Open edX Studio. "
            "Guide the creator through designing a course, one question at a time."
        )

    references_dir = os.path.join(skill_dir, "references")
    if os.path.isdir(references_dir):
        for filename in sorted(os.listdir(references_dir)):
            if not filename.endswith(".md"):
                continue
            try:
                with open(os.path.join(references_dir, filename), encoding="utf-8") as handle:
                    parts.append(f"\n\n# Reference: {filename}\n\n{handle.read()}")
            except OSError:
                log.warning("ai_course_creator: could not read reference %s", filename)

    return "\n".join(parts)


def _get_api_key():
    key = getattr(settings, "GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise LLMNotConfigured(
            "GEMINI_API_KEY is not set. Add it to Tutor config.yml and re-run `tutor config save`."
        )
    return key


def _get_model_name():
    return (
        getattr(settings, "GEMINI_MODEL", "")
        or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    )


def _build_client():
    """Instantiate a google-genai Client (imported lazily so the app loads without the dep)."""
    from google import genai  # pylint: disable=import-outside-toplevel
    return genai.Client(api_key=_get_api_key())


def _to_contents(history, materials_context=""):
    """
    Convert our stored chat messages to the google-genai contents format.

    Gemini uses "user" and "model" roles ("assistant" → "model").
    The materials digest is prepended to the last user turn only.
    Gemini requires non-empty content; empty opening triggers become ".".
    """
    result = []
    for i, message in enumerate(history):
        role = message["role"] if isinstance(message, dict) else message.role
        content = message["content"] if isinstance(message, dict) else message.content
        gemini_role = "model" if role == "assistant" else "user"
        if materials_context and i == len(history) - 1 and role == "user":
            content = (
                f"[Course materials the creator has shared so far:\n{materials_context}\n]\n\n{content}"
            )
        result.append({"role": gemini_role, "parts": [{"text": content or "."}]})
    return result


def _is_rate_limit(exc):
    if _is_too_large(exc):
        return False
    try:
        from google.api_core.exceptions import ResourceExhausted  # noqa, pylint: disable=import-outside-toplevel
        if isinstance(exc, ResourceExhausted):
            return True
    except ImportError:
        pass
    name = type(exc).__name__
    text = str(exc).lower()
    return (
        name == "ResourceExhausted"
        or "429" in text
        or "resource_exhausted" in text
        or "quota_exceeded" in text
        or "rate_limit" in text
    )


def _is_server_unavailable(exc):
    """True for transient 503 / high-demand errors that are worth retrying."""
    text = str(exc).lower()
    return (
        "503" in text
        or "service unavailable" in text
        or "high demand" in text
        or "unavailable" in text
    )


def _is_too_large(exc):
    text = str(exc).lower()
    return "413" in text or "too large" in text or "request_too_large" in text or "payload_too_large" in text


def _retry_after_seconds(exc, default):
    """Extract the suggested wait time from a Gemini 429 error."""
    import re  # pylint: disable=import-outside-toplevel

    details_fn = getattr(exc, "details", None)
    if callable(details_fn):
        try:
            for detail in details_fn():
                delay = getattr(detail, "retry_delay", None)
                if delay is not None:
                    return delay.seconds + delay.nanos / 1e9
        except Exception:  # pylint: disable=broad-except
            pass

    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) or {}
    try:
        ra = headers.get("retry-after")
        if ra:
            return float(ra)
    except (TypeError, ValueError):
        pass

    match = re.search(r"(?:retry after|try again in|wait)\s*([\d.]+)\s*s", str(exc), re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    return default


CHAT_MAX_TOKENS = 1024
# Section editor embeds a SECTION_EDITS JSON block; 8192 is generous without
# reserving a huge compute slot that triggers 503 high-demand errors.
SECTION_CHAT_MAX_TOKENS = 8192
RATE_LIMIT_MAX_WAIT = 65
JSON_MAX_RETRIES = 6
CHAT_MAX_RETRIES = 5
CHAT_RATE_LIMIT_MAX_WAIT = 30


def stream_reply(history, materials_context="", skill_name="skill", max_tokens=CHAT_MAX_TOKENS):
    """
    Stream the assistant's reply token-by-token using the Gemini streaming API.

    ``skill_name`` selects the system instruction (skill dir) to use.
    ``max_tokens`` caps the output (larger for the section editor, which embeds
    a desired section tree in its reply).

    Yields:
        str chunks of assistant text.
    """
    from google.genai import types  # pylint: disable=import-outside-toplevel

    client = _build_client()
    contents = _to_contents(history, materials_context)

    config = types.GenerateContentConfig(
        system_instruction=_load_system_instruction(skill_name),
        temperature=0.7,
        max_output_tokens=max_tokens,
    )

    last_exc = None
    for attempt in range(CHAT_MAX_RETRIES):
        try:
            response = client.models.generate_content_stream(
                model=_get_model_name(),
                contents=contents,
                config=config,
            )
            for chunk in response:
                text = getattr(chunk, "text", "") or ""
                if text:
                    yield text
            return
        except LLMError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            last_exc = exc
            if _is_too_large(exc):
                raise LLMError(
                    "There's too much material for one request. Remove or shorten some "
                    "uploaded materials and try again."
                ) from exc
            if attempt < CHAT_MAX_RETRIES - 1:
                if _is_rate_limit(exc):
                    wait = min(_retry_after_seconds(exc, default=8 * (attempt + 1)) + 1, CHAT_RATE_LIMIT_MAX_WAIT)
                    log.warning(
                        "ai_course_creator: Gemini rate limited (chat), waiting %.1fs (attempt %d/%d)",
                        wait, attempt + 1, CHAT_MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                if _is_server_unavailable(exc):
                    wait = min(4 * (attempt + 1), 20)
                    log.warning(
                        "ai_course_creator: Gemini unavailable (503), retrying in %.1fs (attempt %d/%d)",
                        wait, attempt + 1, CHAT_MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
            raise LLMError(_friendly_llm_error(exc)) from exc
    raise LLMError(_friendly_llm_error(last_exc))


def complete_json(
    history, instruction, materials_context="", temperature=0.4,
    system_instruction=None, max_tokens=None,
):
    """
    Make a single non-streaming call that must return a JSON object.

    Used by the course generator. ``system_instruction`` overrides the skill
    prompt for generation calls. ``max_tokens`` caps the completion size.

    Returns:
        str: the raw JSON text from the model.
    """
    from google.genai import types  # pylint: disable=import-outside-toplevel

    client = _build_client()
    sys_instr = system_instruction if system_instruction is not None else _load_system_instruction()

    contents = _to_contents(history, materials_context)
    contents.append({"role": "user", "parts": [{"text": instruction}]})

    config_kwargs = {
        "system_instruction": sys_instr,
        "temperature": temperature,
        "response_mime_type": "application/json",
    }
    if max_tokens:
        config_kwargs["max_output_tokens"] = max_tokens

    config = types.GenerateContentConfig(**config_kwargs)

    last_exc = None
    for attempt in range(JSON_MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=_get_model_name(),
                contents=contents,
                config=config,
            )
            return response.text or ""
        except Exception as exc:  # pylint: disable=broad-except
            last_exc = exc
            if _is_too_large(exc):
                raise LLMError(_friendly_llm_error(exc)) from exc
            if _is_rate_limit(exc) and attempt < JSON_MAX_RETRIES - 1:
                wait = min(_retry_after_seconds(exc, default=10 * (attempt + 1)) + 1, RATE_LIMIT_MAX_WAIT)
                log.warning(
                    "ai_course_creator: Gemini rate limited (json), waiting %.1fs (attempt %d/%d)",
                    wait, attempt + 1, JSON_MAX_RETRIES,
                )
                time.sleep(wait)
                continue
            raise LLMError(_friendly_llm_error(exc)) from exc
    raise LLMError(_friendly_llm_error(last_exc))


def _friendly_llm_error(exc):
    """Turn a raw API exception into a short, user-facing message."""
    if _is_too_large(exc):
        return (
            "There's too much material for one request. Remove or shorten some "
            "uploaded materials and try again."
        )
    if _is_rate_limit(exc):
        return "Sherab is busy right now — the AI service is rate-limited. Please wait a moment and try again."
    text = str(exc).lower()
    if "401" in text or "403" in text or "api_key" in text or "authentication" in text or "invalid_api_key" in text:
        return "Sherab couldn't connect to the AI service. Please contact your platform administrator."
    if "404" in text:
        return "Sherab couldn't connect to the AI service. Please contact your platform administrator."
    log.exception("ai_course_creator: unexpected LLM error")
    return "Sherab ran into a problem. Please try again in a moment."


def _extract_json_block(text, start, end, label):
    """Pull a fenced JSON block delimited by ``start``/``end`` out of a message."""
    import json  # pylint: disable=import-outside-toplevel

    if start not in text or end not in text:
        return None
    try:
        raw = text.split(start, 1)[1].split(end, 1)[0].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0]
        return json.loads(raw.strip())
    except (IndexError, ValueError):
        log.warning("ai_course_creator: failed to parse %s block", label)
        return None


def _strip_block(text, start, end):
    """Remove a block delimited by ``start``/``end`` so it is never shown to the user."""
    if start not in text:
        return text
    before = text.split(start, 1)[0]
    after = ""
    if end in text:
        after = text.split(end, 1)[1]
    return (before + after).strip()


def extract_course_json(text):
    """Pull the embedded COURSE_JSON block out of an assistant message."""
    return _extract_json_block(text, COURSE_JSON_START, COURSE_JSON_END, "COURSE_JSON")


def strip_course_json(text):
    """Remove the COURSE_JSON block so it is never shown to the user."""
    return _strip_block(text, COURSE_JSON_START, COURSE_JSON_END)


def extract_section_edits(text):
    """Pull the embedded SECTION_EDITS desired-tree block out of an assistant message."""
    return _extract_json_block(text, SECTION_EDITS_START, SECTION_EDITS_END, "SECTION_EDITS")


def strip_section_edits(text):
    """Remove the SECTION_EDITS block so it is never shown to the user."""
    return _strip_block(text, SECTION_EDITS_START, SECTION_EDITS_END)
