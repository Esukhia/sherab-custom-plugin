"""
Orchestrate full course generation from a finished Sherab conversation.

Generating an entire course (with real lesson text and assessments) in one LLM
call would overflow the model's output limit and fail all-or-nothing. Instead we
run a two-stage, resumable flow:

    1. Skeleton  — one call produces the outline (section/subsection/unit titles,
       objectives, and a light component plan). Small and reliable.
    2. Content   — one call per section fills in the full lesson HTML and the
       assessment questions for that section only.

Each stage is JSON-validated (Groq JSON mode + a parse/retry guard). The caller
(views.GenerateCourseView) consumes the progress events this module yields, then
hands the assembled outline to ``course_builder.apply_course_json``.
"""

import json
import logging

from . import llm_client, materials

log = logging.getLogger(__name__)


class GenerationError(Exception):
    """Raised when the model cannot produce a usable outline."""


# Generation calls don't need Sherab's conversational coaching skill (~4k tokens)
# — the design decisions are already in the chat history we send. A short task
# prompt replaces it, saving ~4k tokens on every one of the N+1 generation calls.
GENERATION_SYSTEM = (
    "You are an expert instructional designer. Using the course-design "
    "conversation provided (learner persona, zero-to-hero transformation, "
    "assessment plan, and any uploaded materials), produce open edX course "
    "structure and content. Always respond with a single valid JSON object and "
    "nothing else — no prose, no markdown fences."
)

# Completion caps — gemini-2.5-flash-lite supports up to 65,536 output tokens.
SKELETON_MAX_TOKENS = 8192
SECTION_MAX_TOKENS = 32768


SKELETON_INSTRUCTION = """\
The discovery conversation is complete. Using everything established above — the \
learner persona, the zero-to-hero transformation, the assessment plan, and any \
uploaded materials — design the COMPLETE course OUTLINE. Structure only; do NOT \
write lesson text yet.

Return ONLY a JSON object (no prose, no markdown fences) with this exact shape:
{
  "courseTitle": "string",
  "sections": [
    {
      "title": "string",
      "objective": "one-sentence learning objective tied to the transformation",
      "subsections": [
        {
          "title": "string",
          "units": [
            {
              "title": "string",
              "componentPlan": [
                {"type": "html",    "topic": "what this text teaches"},
                {"type": "video",   "topic": "what the video should show"},
                {"type": "problem", "problemType": "multiplechoice", "topic": "what it assesses"}
              ]
            }
          ]
        }
      ]
    }
  ]
}

Rules:
- 3 to 6 sections. Each section has 1-3 subsections. Each subsection has 1-3 units.
- Use ONLY these component types: "html", "video", "problem".
- Use ONLY these problemType values: multiplechoice, truefalse, multiselect, dropdown, shortanswer, numerical.
- Every section must include at least one "problem", matching the assessment plan.
- Base the whole structure on the conversation above; do not invent an unrelated topic.
"""


def _section_instruction(skeleton, index, total):
    section = skeleton["sections"][index]
    skeleton_outline = json.dumps(
        {
            "courseTitle": skeleton.get("courseTitle"),
            "sections": [
                {"title": s.get("title"), "objective": s.get("objective")}
                for s in skeleton.get("sections", [])
            ],
        },
        ensure_ascii=False,
    )
    return f"""\
Here is the course outline you designed (titles only, for context):
{skeleton_outline}

Now write the FULL content for SECTION {index + 1} of {total} ONLY — the section \
titled "{section.get('title')}". Follow its planned subsections and units.

Return ONLY a JSON object (no prose, no markdown fences) for that ONE section:
{{
  "title": "{section.get('title')}",
  "objective": "{section.get('objective', '')}",
  "subsections": [
    {{
      "title": "string",
      "units": [
        {{
          "title": "string",
          "components": [
            {{"type": "html", "title": "short title", "body": "<p>full HTML lesson content — real paragraphs, headings and lists as needed</p>"}},
            {{"type": "video", "title": "short title", "description": "specific guidance: what the video should cover, rough length, and how to find or record it"}},
            {{"type": "problem", "problemType": "multiplechoice", "question": "full question text", "choices": ["A", "B", "C", "D"], "correct": ["exact text of the correct choice"], "explanation": "why that answer is correct"}}
          ]
        }}
      ]
    }}
  ]
}}

Rules:
- Write REAL, complete lesson content in "body" as HTML. No placeholders like "TODO" or "Lorem ipsum".
- For "video" components NEVER invent a URL — only describe what video is needed.
- For "problem" components: include "choices" for multiplechoice/truefalse/multiselect/dropdown; "correct" is a LIST of the exact correct choice strings (for shortanswer/numerical it is the accepted answer(s)); always include an "explanation".
- Draw on the uploaded materials where relevant.
"""


def _parse_json(raw, what):
    """
    Parse a JSON object from the model response.

    Tolerates markdown code fences in any format, and preamble text before the
    opening brace (e.g. "Here is the JSON:\n{...}"). Logs the raw response on
    failure so we can see exactly what the model returned.
    """
    import re  # pylint: disable=import-outside-toplevel

    text = (raw or "").strip()

    if not text:
        log.warning("ai_course_creator: empty %s response from model", what)
        raise GenerationError(f"The AI returned an empty {what}. Please try again.")

    # Strip markdown code fences: ```json\n{...}\n``` or ```\n{...}\n```
    fence_match = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n```", text)
    if fence_match:
        text = fence_match.group(1).strip()
    elif text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

    # Try to parse the (possibly fence-stripped) text directly.
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass

    # Gemini sometimes adds a preamble sentence before the JSON object.
    # Find the first "{" and try parsing from there.
    start = text.find("{")
    if start != -1:
        try:
            return json.loads(text[start:])
        except (ValueError, TypeError):
            pass

    log.warning(
        "ai_course_creator: could not parse %s (len=%d). Raw (first 500): %.500s",
        what, len(text), text,
    )
    raise GenerationError(f"The AI returned an unreadable {what}. Please try again.")


def _history_from_session(session):
    return [{"role": m.role, "content": m.content} for m in session.messages.all()]


def iter_generate(session):
    """
    Run the two-stage generation, yielding progress dicts as it goes.

    Yields:
        {"type": "progress", "message": str}
        {"type": "outline",  "course": dict}   # final event, once
    """
    history = _history_from_session(session)
    materials_context = materials.build_context(session.materials.all())

    yield {"type": "progress", "message": "Designing the course outline…"}
    # The skeleton call doesn't need the (heavy) uploaded-material text — only the
    # design conversation. Material text is sent with the per-section calls.
    skeleton_raw = llm_client.complete_json(
        history, SKELETON_INSTRUCTION,
        system_instruction=GENERATION_SYSTEM, max_tokens=SKELETON_MAX_TOKENS,
    )
    skeleton = _parse_json(skeleton_raw, "course outline")
    sections = skeleton.get("sections")
    if not isinstance(sections, list) or not sections:
        raise GenerationError("The AI did not produce any sections. Please try again.")

    total = len(sections)
    full_sections = []
    for index in range(total):
        title = sections[index].get("title") or f"Section {index + 1}"
        yield {"type": "progress", "message": f"Writing section {index + 1} of {total}: {title}"}
        section_raw = llm_client.complete_json(
            history, _section_instruction(skeleton, index, total), materials_context,
            system_instruction=GENERATION_SYSTEM, max_tokens=SECTION_MAX_TOKENS,
        )
        section = _parse_json(section_raw, f"section {index + 1}")
        # Carry the outline title/objective if the content call dropped them.
        section.setdefault("title", sections[index].get("title"))
        section.setdefault("objective", sections[index].get("objective"))
        full_sections.append(section)

    course = {
        "courseTitle": skeleton.get("courseTitle") or "Untitled course",
        "sections": full_sections,
    }
    yield {"type": "outline", "course": course}
