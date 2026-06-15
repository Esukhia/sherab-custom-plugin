"""
Turn a COURSE_JSON outline (produced by the Sherab chatbot in Phase 5) into real
Open edX course structure: Sections (chapter) -> Subsections (sequential) ->
Units (vertical) -> Components (video / html / problem / discussion).

Runs inside the CMS process, so it calls ``contentstore``'s ``create_xblock``
and the modulestore directly rather than going back out over HTTP.

COURSE_JSON schema (see skill/SKILL.md):

    {
      "courseTitle": "...",
      "sections": [
        {"title": "...", "objective": "...", "subsections": [
            {"title": "...", "units": [
                {"title": "...", "components": [
                    {"type": "video", "title": "...", "source": "url"},
                    {"type": "html", "title": "...", "body": "..."},
                    {"type": "problem", "problemType": "multiplechoice|truefalse|shortanswer|scenario",
                     "question": "...", "choices": ["A","B"], "correct": "A"},
                    {"type": "discussion", "prompt": "..."}
                ]}
            ]}
        ]}
      ],
      "finalAssessment": [ {"type": "problem", ...} ]
    }
"""

import logging
import re
from uuid import uuid4
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)


class CourseBuildError(Exception):
    """Raised when the outline cannot be applied to the course."""


# --------------------------------------------------------------------------- #
# Permission helper
# --------------------------------------------------------------------------- #
def user_can_author(user, course_key):
    """Return True if ``user`` may author the given course."""
    from common.djangoapps.student.auth import has_course_author_access

    return has_course_author_access(user, course_key)


# --------------------------------------------------------------------------- #
# Problem OLX builders
# --------------------------------------------------------------------------- #
def _multiple_choice_olx(question, choices, correct):
    correct = (correct or "").strip()
    choice_xml = []
    for choice in choices or []:
        is_correct = "true" if choice.strip() == correct else "false"
        choice_xml.append(f'      <choice correct="{is_correct}">{escape(choice)}</choice>')
    return (
        "<problem>\n"
        "  <multiplechoiceresponse>\n"
        f"    <label>{escape(question)}</label>\n"
        '    <choicegroup type="MultipleChoice">\n'
        + "\n".join(choice_xml)
        + "\n    </choicegroup>\n"
        "  </multiplechoiceresponse>\n"
        "</problem>"
    )


def _true_false_olx(question, correct):
    choices = ["True", "False"]
    # Normalise the correct answer to one of the two labels.
    correct_label = "True"
    if isinstance(correct, str) and correct.strip().lower() in ("false", "f", "no"):
        correct_label = "False"
    return _multiple_choice_olx(question, choices, correct_label)


def _short_answer_olx(question, correct):
    answer = escape(correct) if correct else ""
    return (
        "<problem>\n"
        "  <stringresponse answer=\"" + answer + "\" type=\"ci\">\n"
        f"    <label>{escape(question)}</label>\n"
        '    <textline size="40"/>\n'
        "  </stringresponse>\n"
        "</problem>"
    )


def build_problem_olx(component):
    """Build CAPA OLX for a problem component dict."""
    problem_type = (component.get("problemType") or "multiplechoice").lower()
    question = component.get("question") or component.get("title") or "Question"
    choices = component.get("choices") or []
    correct = component.get("correct")

    if problem_type in ("truefalse", "true_false", "true/false"):
        return _true_false_olx(question, correct)
    if problem_type in ("shortanswer", "short_answer", "stringresponse"):
        return _short_answer_olx(question, correct)
    if problem_type in ("multiplechoice", "multiple_choice", "mcq"):
        return _multiple_choice_olx(question, choices, correct)
    # "scenario" or anything unknown: multiple choice if we have options, else short answer.
    if choices:
        return _multiple_choice_olx(question, choices, correct)
    return _short_answer_olx(question, correct)


# --------------------------------------------------------------------------- #
# YouTube id extraction for video components
# --------------------------------------------------------------------------- #
_YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def _youtube_id(url):
    if not url:
        return None
    match = _YOUTUBE_RE.search(url)
    return match.group(1) if match else None


# --------------------------------------------------------------------------- #
# Component creation
# --------------------------------------------------------------------------- #
def _create_component(store, user, parent_locator, component):
    """Create a single leaf component under a unit (vertical)."""
    from cms.djangoapps.contentstore.xblock_storage_handlers.create_xblock import create_xblock

    comp_type = (component.get("type") or "html").lower()
    title = component.get("title")
    if not title and comp_type == "problem":
        # Fall back to a trimmed version of the question for a readable name.
        question = component.get("question") or ""
        title = (question[:60] + "…") if len(question) > 60 else question
    title = title or comp_type.capitalize()

    if comp_type == "video":
        block = create_xblock(parent_locator, user, "video", title)
        youtube_id = _youtube_id(component.get("source"))
        if youtube_id:
            block.youtube_id_1_0 = youtube_id
        elif component.get("source"):
            block.html5_sources = [component["source"]]
        store.update_item(block, user.id)
        return "video"

    if comp_type == "problem":
        block = create_xblock(parent_locator, user, "problem", title)
        block.data = build_problem_olx(component)
        store.update_item(block, user.id)
        return "problem"

    if comp_type == "discussion":
        block = create_xblock(parent_locator, user, "discussion", title)
        block.discussion_id = uuid4().hex
        block.discussion_category = component.get("category", "General")
        block.discussion_target = title
        store.update_item(block, user.id)
        return "discussion"

    # Default: HTML/text component.
    block = create_xblock(parent_locator, user, "html", title)
    body = component.get("body") or component.get("summary") or ""
    block.data = body if body.strip().startswith("<") else f"<p>{escape(body)}</p>"
    store.update_item(block, user.id)
    return "html"


def apply_course_json(course_key, user, course_json):
    """
    Build the full course structure described by ``course_json``.

    Args:
        course_key: a CourseKey (or string) for the target course.
        user: the authoring user.
        course_json: the parsed COURSE_JSON dict.

    Returns:
        dict summary: counts of created blocks and the created section locators.

    Raises:
        CourseBuildError: on bad input or permission failure.
    """
    from opaque_keys import InvalidKeyError
    from opaque_keys.edx.keys import CourseKey
    from cms.djangoapps.contentstore.xblock_storage_handlers.create_xblock import create_xblock
    from xmodule.modulestore.django import modulestore

    if isinstance(course_key, str):
        try:
            course_key = CourseKey.from_string(course_key)
        except InvalidKeyError as exc:
            raise CourseBuildError(f"Invalid course id: {course_key}") from exc

    if not user_can_author(user, course_key):
        raise CourseBuildError("You do not have permission to edit this course.")

    if not isinstance(course_json, dict) or not course_json.get("sections"):
        raise CourseBuildError("The generated outline has no sections to create.")

    store = modulestore()
    counts = {"sections": 0, "subsections": 0, "units": 0, "components": 0}
    section_locators = []

    with store.bulk_operations(course_key):
        course = store.get_course(course_key)
        if course is None:
            raise CourseBuildError(f"Course not found: {course_key}")
        course_locator = str(course.location)

        for section in course_json["sections"]:
            chapter = create_xblock(
                course_locator, user, "chapter", section.get("title") or "Section"
            )
            counts["sections"] += 1
            section_locators.append(str(chapter.location))
            chapter_locator = str(chapter.location)

            for subsection in section.get("subsections", []):
                sequential = create_xblock(
                    chapter_locator, user, "sequential", subsection.get("title") or "Subsection"
                )
                counts["subsections"] += 1
                sequential_locator = str(sequential.location)

                for unit in subsection.get("units", []):
                    vertical = create_xblock(
                        sequential_locator, user, "vertical", unit.get("title") or "Unit"
                    )
                    counts["units"] += 1
                    vertical_locator = str(vertical.location)

                    for component in unit.get("components", []):
                        try:
                            _create_component(store, user, vertical_locator, component)
                            counts["components"] += 1
                        except Exception:  # pylint: disable=broad-except
                            log.exception(
                                "ai_course_creator: failed to create component %s", component
                            )

    log.info("ai_course_creator: built course %s -> %s", course_key, counts)
    return {"counts": counts, "sectionLocators": section_locators}
