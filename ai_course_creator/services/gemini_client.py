"""
Thin wrapper around the Google Gemini API for the Sherab course-creator chatbot.

The bundled skill (``skill/SKILL.md`` + ``skill/references/*.md``) is used as the
system instruction so the model behaves exactly like the "Sherab" persona, runs
the 5-phase flow, and emits a ``===COURSE_JSON_START===...===COURSE_JSON_END===``
block in Phase 5.

Credentials come from Django settings (``GEMINI_API_KEY`` / ``GEMINI_MODEL``),
which Tutor injects from ``config.yml``. See settings/common.py.
"""

import logging
import os
from functools import lru_cache

from django.conf import settings

log = logging.getLogger(__name__)

SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skill")

# Marker the assistant wraps the machine-readable course outline in (Phase 5).
COURSE_JSON_START = "===COURSE_JSON_START==="
COURSE_JSON_END = "===COURSE_JSON_END==="

# Marker the assistant emits when it moves to a new display phase.
# N maps to: 1=Learner, 2=Transformation, 3=Assessment, 4=Generate
PHASE_MARKER_RE = None  # lazy init to avoid re import at module level


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


class GeminiNotConfigured(Exception):
    """Raised when no Gemini API key is available."""


class GeminiError(Exception):
    """Raised for a Gemini API failure, with a user-friendly message."""


@lru_cache(maxsize=1)
def _load_system_instruction():
    """
    Build the system instruction from the bundled skill files.

    Cached for the process lifetime; the skill content is static.
    """
    parts = []
    skill_md = os.path.join(SKILL_DIR, "SKILL.md")
    try:
        with open(skill_md, encoding="utf-8") as handle:
            parts.append(handle.read())
    except OSError:
        log.exception("ai_course_creator: could not read SKILL.md at %s", skill_md)
        # Minimal fallback so the assistant is still usable.
        parts.append(
            "You are Sherab, a warm course-design companion inside Open edX Studio. "
            "Guide the creator through designing a course, one question at a time."
        )

    references_dir = os.path.join(SKILL_DIR, "references")
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
        raise GeminiNotConfigured(
            "GEMINI_API_KEY is not set. Add it to Tutor config.yml and re-run `tutor config save`."
        )
    return key


def _get_model_name():
    return getattr(settings, "GEMINI_MODEL", "") or os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")


def _build_model():
    """Instantiate a configured ``GenerativeModel`` with the skill system prompt."""
    import google.generativeai as genai  # imported lazily so the app loads without the dep

    genai.configure(api_key=_get_api_key())
    return genai.GenerativeModel(
        model_name=_get_model_name(),
        system_instruction=_load_system_instruction(),
    )


def _to_gemini_history(messages):
    """
    Convert our stored chat messages into Gemini's ``contents`` format.

    ``messages`` is an iterable of dicts/objects with ``role`` ("user" |
    "assistant") and ``content``. Gemini uses the role name "model" for the
    assistant.
    """
    history = []
    for message in messages:
        role = message["role"] if isinstance(message, dict) else message.role
        content = message["content"] if isinstance(message, dict) else message.content
        gemini_role = "model" if role == "assistant" else "user"
        history.append({"role": gemini_role, "parts": [content]})
    return history


def stream_reply(history, materials_context=""):
    """
    Stream the assistant's reply token-by-token.

    Args:
        history: ordered list of prior messages (dicts or ChatMessage), where
            the final entry is the latest user turn.
        materials_context: optional plain-text digest of uploaded materials to
            give the model during Phase 3.

    Yields:
        str chunks of assistant text.
    """
    model = _build_model()
    contents = _to_gemini_history(history)

    if materials_context and contents:
        # Prepend the materials digest to the final user turn so the model can
        # use it without us inventing a fake conversation turn.
        contents[-1]["parts"].insert(
            0,
            f"[Course materials the creator has shared so far:\n{materials_context}\n]\n\n",
        )

    try:
        response = model.generate_content(contents, stream=True)
        for chunk in response:
            # Pull text from the candidate parts directly. We avoid the
            # ``chunk.text`` quick accessor because it RAISES (rather than
            # returning empty) for chunks that carry no Part — which happens
            # routinely on the final chunk (finish_reason=STOP) and on
            # safety-filtered responses.
            for candidate in (getattr(chunk, "candidates", None) or []):
                content = getattr(candidate, "content", None)
                for part in (getattr(content, "parts", None) or []):
                    text = getattr(part, "text", "")
                    if text:
                        yield text
    except GeminiError:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise GeminiError(_friendly_gemini_error(exc)) from exc


def _friendly_gemini_error(exc):
    """Turn a raw Gemini/Google API exception into a short, user-facing message."""
    name = type(exc).__name__
    if name in ("ResourceExhausted",) or "429" in str(exc):
        return "Sherab is busy right now — the AI service is rate-limited. Please wait a moment and try again."
    if name in ("PermissionDenied", "Unauthenticated") or "401" in str(exc) or "403" in str(exc):
        return "Sherab couldn't connect to the AI service. Please contact your platform administrator."
    if name in ("NotFound",) or "404" in str(exc):
        return "Sherab couldn't connect to the AI service. Please contact your platform administrator."
    log.exception("ai_course_creator: unexpected Gemini error")
    return "Sherab ran into a problem. Please try again in a moment."


def extract_course_json(text):
    """
    Pull the embedded COURSE_JSON block out of an assistant message.

    Returns the parsed dict, or ``None`` if no valid block is present.
    """
    import json

    if COURSE_JSON_START not in text or COURSE_JSON_END not in text:
        return None
    try:
        raw = text.split(COURSE_JSON_START, 1)[1].split(COURSE_JSON_END, 1)[0].strip()
        # The model sometimes wraps the JSON in a ```json fence.
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0]
        return json.loads(raw.strip())
    except (IndexError, ValueError):
        log.warning("ai_course_creator: failed to parse COURSE_JSON block")
        return None


def strip_course_json(text):
    """Remove the COURSE_JSON block so it is never shown to the user."""
    if COURSE_JSON_START not in text:
        return text
    before = text.split(COURSE_JSON_START, 1)[0]
    after = ""
    if COURSE_JSON_END in text:
        after = text.split(COURSE_JSON_END, 1)[1]
    return (before + after).strip()
