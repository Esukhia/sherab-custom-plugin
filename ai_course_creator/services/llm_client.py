"""
Thin wrapper around the LLM API for the Sherab course-creator chatbot.

The bundled skill (``skill/SKILL.md`` + ``skill/references/*.md``) is used as the
system instruction so the model behaves exactly like the "Sherab" persona, runs
the 5-phase flow, and emits a ``===COURSE_JSON_START===...===COURSE_JSON_END===``
block in Phase 5.

Credentials come from Django settings (``GROQ_API_KEY`` / ``GROQ_MODEL``),
which Tutor injects from ``config.yml``. See settings/common.py.
"""

import logging
import os
import time
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


# Keep original exception names so views.py needs no changes.
class LLMNotConfigured(Exception):
    """Raised when no API key is available."""


class LLMError(Exception):
    """Raised for an LLM API failure, with a user-friendly message."""


@lru_cache(maxsize=1)
def _load_system_instruction():
    """
    Build the system instruction from the bundled skill files.

    Cached for the process lifetime; the skill content is static.
    """
    import re as _re  # pylint: disable=import-outside-toplevel
    parts = []
    skill_md = os.path.join(SKILL_DIR, "SKILL.md")
    try:
        with open(skill_md, encoding="utf-8") as handle:
            raw = handle.read()
        # Strip YAML frontmatter (--- ... ---) before sending to the model.
        stripped = _re.sub(r"^---\n.*?\n---\n", "", raw, flags=_re.DOTALL)
        parts.append(stripped)
    except OSError:
        log.exception("ai_course_creator: could not read SKILL.md at %s", skill_md)
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
    key = getattr(settings, "GROQ_API_KEY", "") or os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise LLMNotConfigured(
            "GROQ_API_KEY is not set. Add it to Tutor config.yml and re-run `tutor config save`."
        )
    return key


def _get_model_name():
    return getattr(settings, "GROQ_MODEL", "") or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


def _build_client():
    """Instantiate a Groq client (imported lazily so the app loads without the dep)."""
    from groq import Groq  # pylint: disable=import-outside-toplevel
    return Groq(api_key=_get_api_key())


def _to_messages(history, materials_context=""):
    """
    Convert our stored chat messages into OpenAI-format messages with the
    system instruction prepended.
    """
    messages = [{"role": "system", "content": _load_system_instruction()}]
    for i, message in enumerate(history):
        role = message["role"] if isinstance(message, dict) else message.role
        content = message["content"] if isinstance(message, dict) else message.content
        # Groq (like OpenAI) uses "assistant", not "model".
        # Prepend materials digest to the final user turn.
        if materials_context and i == len(history) - 1 and role == "user":
            content = (
                f"[Course materials the creator has shared so far:\n{materials_context}\n]\n\n{content}"
            )
        messages.append({"role": role, "content": content})
    return messages


def _is_rate_limit(exc):
    name = type(exc).__name__
    return name == "RateLimitError" or "429" in str(exc) or "rate_limit" in str(exc).lower()


def _start_stream_with_retry(client, messages):
    """Start a streaming request with up to 2 retries on rate limit."""
    delays = [10, 25]
    for delay in delays:
        try:
            return client.chat.completions.create(
                messages=messages,
                model=_get_model_name(),
                stream=True,
                temperature=0.7,
            )
        except Exception as exc:  # pylint: disable=broad-except
            if _is_rate_limit(exc):
                log.warning("ai_course_creator: Groq rate limited, retrying in %ds", delay)
                time.sleep(delay)
            else:
                raise
    # Final attempt — let exceptions propagate to the caller.
    return client.chat.completions.create(
        messages=messages,
        model=_get_model_name(),
        stream=True,
    )


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
    client = _build_client()
    messages = _to_messages(history, materials_context)

    try:
        stream = _start_stream_with_retry(client, messages)
        for chunk in stream:
            text = chunk.choices[0].delta.content or ""
            if text:
                yield text
    except LLMError:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise LLMError(_friendly_llm_error(exc)) from exc


def _friendly_llm_error(exc):
    """Turn a raw API exception into a short, user-facing message."""
    if _is_rate_limit(exc):
        return "Sherab is busy right now — the AI service is rate-limited. Please wait a moment and try again."
    if "401" in str(exc) or "403" in str(exc) or "authentication" in str(exc).lower():
        return "Sherab couldn't connect to the AI service. Please contact your platform administrator."
    if "404" in str(exc):
        return "Sherab couldn't connect to the AI service. Please contact your platform administrator."
    log.exception("ai_course_creator: unexpected LLM error")
    return "Sherab ran into a problem. Please try again in a moment."


def extract_course_json(text):
    """
    Pull the embedded COURSE_JSON block out of an assistant message.

    Returns the parsed dict, or ``None`` if no valid block is present.
    """
    import json  # pylint: disable=import-outside-toplevel

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
