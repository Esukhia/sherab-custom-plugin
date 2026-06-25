"""
Read and edit a SINGLE section (chapter) of a course for the per-section
"Edit with SherabAI" sidebar.

Runs inside the CMS process and talks to the modulestore directly, mirroring
``course_builder.py``. Two entry points:

- ``read_section`` serializes one chapter subtree to a JSON tree (with usage
  keys + content) so the LLM can see what's there.
- ``apply_section_edits`` applies an operation list (rename / editContent / add /
  delete / reorder) produced by the LLM, strictly scoped to that one chapter.

The operation-list approach (rather than a full desired-tree diff) is deliberate:
the model only ever touches the nodes it explicitly names, so a forgotten node
can never be silently deleted. Every usage key the model supplies is validated
against the chapter's own descendant set before anything is mutated, which is
what guarantees edits stay inside the chosen section.

Edits land as draft (DIRECT_ONLY containers aside); set ``publish=True`` to
publish the chapter subtree after applying.
"""

import logging
from xml.sax.saxutils import escape

from .course_builder import user_can_author

log = logging.getLogger(__name__)

CONTAINER_TYPES = {"chapter", "sequential", "vertical"}
# Leaf types whose ``data`` field is the editable OLX/HTML content.
LEAF_CONTENT_TYPES = {"html", "problem", "video"}
# What each container type may hold (used to validate "add" operations).
ALLOWED_CHILD_TYPES = {
    "chapter": {"sequential"},
    "sequential": {"vertical"},
    "vertical": {"html", "problem", "video", "discussion"},
}


class SectionEditError(Exception):
    """Raised when a section cannot be read or edited."""


# --------------------------------------------------------------------------- #
# Key helpers
# --------------------------------------------------------------------------- #
def _coerce_course_key(course_key):
    from opaque_keys import InvalidKeyError
    from opaque_keys.edx.keys import CourseKey

    if isinstance(course_key, str):
        try:
            return CourseKey.from_string(course_key)
        except InvalidKeyError as exc:
            raise SectionEditError(f"Invalid course id: {course_key}") from exc
    return course_key


def _coerce_usage_key(locator):
    from opaque_keys import InvalidKeyError
    from opaque_keys.edx.keys import UsageKey

    try:
        return UsageKey.from_string(str(locator))
    except InvalidKeyError as exc:
        raise SectionEditError(f"Invalid block id: {locator}") from exc


def _load_chapter(store, course_key, section_locator):
    """Load the chapter subtree and validate it belongs to this course."""
    from xmodule.modulestore.exceptions import ItemNotFoundError

    usage_key = _coerce_usage_key(section_locator)
    try:
        chapter = store.get_item(usage_key, depth=None)
    except ItemNotFoundError as exc:
        raise SectionEditError("That section no longer exists.") from exc
    if chapter.location.course_key != course_key:
        raise SectionEditError("That section is not part of this course.")
    if chapter.category != "chapter":
        raise SectionEditError("That block is not a section.")
    return chapter


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
def _serialize_block(block):
    """Recursively serialize a block to the section-tree JSON shape."""
    node = {
        "usageKey": str(block.location),
        "type": block.category,
        "displayName": block.display_name_with_default,
    }
    if block.category in CONTAINER_TYPES:
        node["children"] = [_serialize_block(child) for child in block.get_children()]
    else:
        node["content"] = getattr(block, "data", "") or ""
        if block.category not in LEAF_CONTENT_TYPES:
            # We can show it but won't try to edit its raw data.
            node["editable"] = False
    return node


def read_section(course_key, user, section_locator):
    """
    Serialize one chapter (section) subtree to a JSON tree.

    Returns a dict: {usageKey, type:"chapter", displayName, children:[...]}.
    Read-only; raises SectionEditError on bad input or missing permission.
    """
    from xmodule.modulestore.django import modulestore

    course_key = _coerce_course_key(course_key)
    if not user_can_author(user, course_key):
        raise SectionEditError("You do not have permission to edit this course.")

    store = modulestore()
    chapter = _load_chapter(store, course_key, section_locator)
    return _serialize_block(chapter)


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #
def _collect_descendant_keys(block, acc):
    """Add this block's key and all descendant keys (as strings) to ``acc``."""
    acc.add(str(block.location))
    if block.category in CONTAINER_TYPES:
        for child in block.get_children():
            _collect_descendant_keys(child, acc)


def _create_node(store, user, parent_locator, node):
    """
    Recursively create a new block (and its subtree) under ``parent_locator``.

    Returns the created block. Counts created blocks into ``node["_created"]``
    is not used; callers count via the returned subtree size if needed.
    """
    from cms.djangoapps.contentstore.xblock_storage_handlers.create_xblock import create_xblock

    node_type = (node.get("type") or "html").lower()
    display_name = node.get("displayName") or node_type.capitalize()
    block = create_xblock(parent_locator, user, node_type, display_name)

    if node_type in CONTAINER_TYPES:
        for child in node.get("children", []) or []:
            _create_node(store, user, str(block.location), child)
    elif node_type in ("html", "problem"):
        content = node.get("content") or ""
        if not content and node_type == "html":
            content = "<p></p>"
        block.data = content
        store.update_item(block, user.id)
    # video / discussion: created empty; creator fills them in Studio.
    return block


def _count_subtree(node):
    """Number of blocks a new ``node`` subtree will create (itself + descendants)."""
    total = 1
    for child in node.get("children", []) or []:
        total += _count_subtree(child)
    return total


def _reorder_parent(store, user, parent, ordered_key_strs):
    """Set ``parent``'s child order to ``ordered_key_strs``, keeping any unlisted children last."""
    current = list(parent.children)
    by_str = {str(k): k for k in current}
    new_order = [by_str[s] for s in ordered_key_strs if s in by_str]
    for key in current:
        if key not in new_order:
            new_order.append(key)
    parent.children = new_order
    store.update_item(parent, user.id)


def apply_section_edits(course_key, user, section_locator, edits, publish=False):
    """
    Apply an operation-list of edits to ONE chapter (section).

    ``edits`` shape (all keys optional)::

        {
          "rename":      [{"usageKey": "...", "displayName": "..."}],
          "editContent": [{"usageKey": "...", "content": "<olx/html>"}],
          "add":         [{"parentUsageKey": "...", "afterUsageKey": "...|null",
                           "node": {...new subtree...}}],
          "delete":      ["usageKey", ...],
          "reorder":     [{"parentUsageKey": "...", "orderedChildKeys": ["...", ...]}]
        }

    Returns a summary dict::

        {"updated": int, "created": int, "deleted": int, "reordered": int,
         "sectionName": str, "rejected": [{"target","reason"}], "errors": [...]}

    Raises SectionEditError on bad input / permission failure / missing section.
    Individual bad operations are skipped and recorded, never aborting the batch.
    """
    from xmodule.modulestore.django import modulestore

    if not isinstance(edits, dict):
        raise SectionEditError("No edits to apply.")

    course_key = _coerce_course_key(course_key)
    if not user_can_author(user, course_key):
        raise SectionEditError("You do not have permission to edit this course.")

    store = modulestore()
    summary = {
        "updated": 0, "created": 0, "deleted": 0, "reordered": 0,
        "rejected": [], "errors": [],
    }

    with store.bulk_operations(course_key):
        chapter = _load_chapter(store, course_key, section_locator)
        chapter_key = str(chapter.location)
        summary["sectionName"] = chapter.display_name_with_default

        # Containment set: every usage key the model may reference must be here.
        allowed = set()
        _collect_descendant_keys(chapter, allowed)

        def in_section(key):
            return key in allowed

        # 1. delete (remove nodes first so later ops see a clean tree)
        for key in edits.get("delete", []) or []:
            key = str(key)
            if key == chapter_key:
                summary["rejected"].append({"target": key, "reason": "cannot delete the section itself"})
                continue
            if not in_section(key):
                summary["rejected"].append({"target": key, "reason": "outside this section"})
                continue
            try:
                store.delete_item(_coerce_usage_key(key), user.id)
                allowed.discard(key)
                summary["deleted"] += 1
            except Exception as exc:  # pylint: disable=broad-except
                log.exception("section_editor: delete failed for %s", key)
                summary["errors"].append({"target": key, "reason": str(exc)})

        # 2. add (create new subtrees under existing parents)
        for op in edits.get("add", []) or []:
            parent_key = str(op.get("parentUsageKey") or "")
            node = op.get("node") or {}
            after_key = op.get("afterUsageKey")
            if not in_section(parent_key):
                summary["rejected"].append({"target": parent_key, "reason": "parent outside this section"})
                continue
            try:
                parent = store.get_item(_coerce_usage_key(parent_key))
                child_type = (node.get("type") or "").lower()
                allowed_children = ALLOWED_CHILD_TYPES.get(parent.category, set())
                if child_type not in allowed_children:
                    summary["rejected"].append({
                        "target": parent_key,
                        "reason": f"a {parent.category} cannot contain a {child_type or 'block'}",
                    })
                    continue
                new_block = _create_node(store, user, parent_key, node)
                summary["created"] += _count_subtree(node)
                allowed.add(str(new_block.location))
                # Position after a given sibling, if requested.
                if after_key:
                    parent = store.get_item(_coerce_usage_key(parent_key))
                    children = list(parent.children)
                    if new_block.location in children:
                        children.remove(new_block.location)
                    insert_idx = len(children)
                    for i, key in enumerate(children):
                        if str(key) == str(after_key):
                            insert_idx = i + 1
                            break
                    children.insert(insert_idx, new_block.location)
                    parent.children = children
                    store.update_item(parent, user.id)
            except Exception as exc:  # pylint: disable=broad-except
                log.exception("section_editor: add failed under %s", parent_key)
                summary["errors"].append({"target": parent_key, "reason": str(exc)})

        # 3. rename (displayName on any node, including the chapter)
        for op in edits.get("rename", []) or []:
            key = str(op.get("usageKey") or "")
            name = op.get("displayName")
            if not in_section(key):
                summary["rejected"].append({"target": key, "reason": "outside this section"})
                continue
            if not name:
                continue
            try:
                block = store.get_item(_coerce_usage_key(key))
                block.display_name = name
                store.update_item(block, user.id)
                summary["updated"] += 1
            except Exception as exc:  # pylint: disable=broad-except
                log.exception("section_editor: rename failed for %s", key)
                summary["errors"].append({"target": key, "reason": str(exc)})

        # 4. editContent (replace a leaf's OLX/HTML)
        for op in edits.get("editContent", []) or []:
            key = str(op.get("usageKey") or "")
            content = op.get("content")
            if not in_section(key):
                summary["rejected"].append({"target": key, "reason": "outside this section"})
                continue
            if content is None:
                continue
            try:
                block = store.get_item(_coerce_usage_key(key))
                if block.category in CONTAINER_TYPES:
                    summary["rejected"].append({"target": key, "reason": "not an editable component"})
                    continue
                # Wrap plain text in a paragraph for html, mirroring course_builder.
                if block.category == "html" and content.strip() and not content.strip().startswith("<"):
                    content = f"<p>{escape(content)}</p>"
                block.data = content
                store.update_item(block, user.id)
                summary["updated"] += 1
            except Exception as exc:  # pylint: disable=broad-except
                log.exception("section_editor: editContent failed for %s", key)
                summary["errors"].append({"target": key, "reason": str(exc)})

        # 5. reorder (set a container's child order)
        for op in edits.get("reorder", []) or []:
            parent_key = str(op.get("parentUsageKey") or "")
            ordered = [str(k) for k in (op.get("orderedChildKeys") or [])]
            if not in_section(parent_key):
                summary["rejected"].append({"target": parent_key, "reason": "outside this section"})
                continue
            try:
                parent = store.get_item(_coerce_usage_key(parent_key))
                if parent.category not in CONTAINER_TYPES:
                    summary["rejected"].append({"target": parent_key, "reason": "not a container"})
                    continue
                _reorder_parent(store, user, parent, ordered)
                summary["reordered"] += 1
            except Exception as exc:  # pylint: disable=broad-except
                log.exception("section_editor: reorder failed for %s", parent_key)
                summary["errors"].append({"target": parent_key, "reason": str(exc)})

        if publish:
            try:
                store.publish(chapter.location, user.id)
            except Exception:  # pylint: disable=broad-except
                log.exception("section_editor: publish failed for %s", chapter_key)

    log.info("section_editor: applied edits to %s -> %s", section_locator, {
        k: summary[k] for k in ("updated", "created", "deleted", "reordered")
    })
    return summary
