"""
classify.py – Layout classification and editor completeness check.

Rules classify the page first using DOM signals (buttons, tabs, editor text).
When the rules disagree, a vision model is called as tiebreaker.

Layouts:
    roadmap  – Start Roadmap Now or the roadmap title
    reading  – No editor, no Submit; just a Next button
    guided   – Submit present, no Solution tab, editor has real code, statement says run
    exercise – Solution tab present, or editor body is empty/placeholder
    quiz     – Radio buttons or choice cards, no editor
    auth     – Login form, captcha, or verify wall
    done     – Certificate / course completed screen
    module_done – Module summary with 'Keep Learning' button
    outline  – Module outline / hamburger syllabus
    running  – Submission still evaluating
    unknown  – None of the above
"""

from __future__ import annotations

import re


# ─── Placeholder patterns ────────────────────────────────────────────
PLACEHOLDER_PATTERNS = [
    r"write\s+your\s+code\s+here",
    r"todo",
    r"your\s+code\s+here",
    r"write\s+code\s+here",
    r"// Write your code here",
    r"// your code here",
    r"// TODO",
]

BOILERPLATE_ONLY_RE = re.compile(
    r"^\s*"
    r"(#include\s*<[^>]+>\s*)*"  # optional #include lines
    r"(//[^\n]*\n\s*)*"          # optional comment lines
    r"(int\s+main\s*\(\s*\)\s*\{)?"  # optional main signature
    r"\s*"
    r"(//[^\n]*\n\s*)*"          # optional comments inside main
    r"(return\s+0\s*;)?"         # optional return 0
    r"\s*"
    r"(\})?"                     # optional closing brace
    r"\s*$",
    re.IGNORECASE | re.DOTALL,
)

RUN_STATEMENT_KEYWORDS = [
    "run the code",
    "try running",
    "go ahead and try running",
    "run it",
    "execute the code",
    "compile and run",
    "compiles and executes",
    "run the sample",
    "submit the code",
    "submit it",
]

EXERCISE_STATEMENT_KEYWORDS = [
    "complete the code",
    "write the code",
    "write a program",
    "write the program",
    "complete the program",
    "modify the code",
    "fill in",
    "implement",
    "your task",
    "you need to",
    "print",
]

CERT_DENY = [
    "certificate",
    "download",
    "get certificate",
    "claim certificate",
    "download certificate",
]


def is_code_written(editor_text: str, statement: str = "") -> bool:
    """
    Determine if the editor already contains a finished program.

    A guided page whose statement says to run the sample, and whose main
    already has a call such as printf, is written. Submit it as-is.

    Rules:
    - Strip comments. If main has only whitespace left, not written.
    - Boilerplate (#include, empty main, return 0) is not written.
    - Placeholder text → not written.
    """
    if not editor_text or not editor_text.strip():
        return False

    text = editor_text.strip()

    # Check for placeholder patterns
    text_lower = text.lower()
    for pat in PLACEHOLDER_PATTERNS:
        if re.search(pat, text_lower):
            # Has placeholder → not fully written
            # But we need to check: is this ONLY a placeholder inside boilerplate?
            stripped = _strip_comments(text)
            body = _extract_main_body(stripped)
            if not body or not body.strip():
                return False
            # If the body only has placeholder content, not written
            body_clean = re.sub(r'\s+', ' ', body).strip()
            if not body_clean or all(
                re.search(pat, body_clean, re.IGNORECASE) for pat in PLACEHOLDER_PATTERNS
                if re.search(pat, text_lower)
            ):
                return False

    # Strip comments and check if main has real statements
    stripped = _strip_comments(text)
    body = _extract_main_body(stripped)

    if body is None:
        # No main function found – if there's substantial code, consider it written
        return len(stripped.strip()) > 50

    # Remove whitespace
    body_clean = body.strip()
    if not body_clean:
        return False

    # Remove just 'return 0;' – that's boilerplate
    body_no_return = re.sub(r'return\s+0\s*;', '', body_clean).strip()
    if not body_no_return:
        return False

    # Check for boilerplate-only match on the full text
    if BOILERPLATE_ONLY_RE.fullmatch(text):
        return False

    # Has real statements in main → code is written
    return True


def _strip_comments(text: str) -> str:
    """Remove C-style comments (// and /* */)."""
    # Remove block comments
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    # Remove line comments
    text = re.sub(r'//[^\n]*', '', text)
    return text


def _extract_main_body(text: str) -> str | None:
    """Extract the body of main() from C source code."""
    match = re.search(r'int\s+main\s*\([^)]*\)\s*\{', text)
    if not match:
        return None
    start = match.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
        i += 1
    if depth == 0:
        return text[start:i - 1]
    return text[start:]


def classify(obs: dict) -> str:
    """
    Classify the page layout from an observation dict.

    Returns one of:
        roadmap, reading, guided, exercise, quiz, auth, done,
        outline, running, unknown
    """
    url = obs.get("url", "")
    buttons = obs.get("buttons", [])
    tabs = obs.get("tabs", [])
    statement = obs.get("statement", "")
    editor_text = obs.get("editor_text", "")
    editor_kind = obs.get("editor_kind", "")
    has_editor = obs.get("has_editor", False)
    has_solution_tab = obs.get("has_solution_tab", False)
    has_radio = obs.get("has_radio_buttons", False)
    has_login = obs.get("has_login_form", False)
    has_cert = obs.get("has_certificate", False)
    output_text = obs.get("output_text", "")
    page_text = obs.get("page_text", "")
    title = obs.get("title", "")

    buttons_lower = [b.lower().strip() for b in buttons]
    buttons_text = " ".join(buttons_lower)
    statement_lower = statement.lower()
    page_lower = page_text.lower()
    title_lower = title.lower()

    has_submit = any("submit" in b for b in buttons_lower)
    has_next = any("next" in b for b in buttons_lower)

    # ── Auth wall ────────────────────────────────────────────────
    if has_login:
        return "auth"

    # ── Certificate / course done ────────────────────────────────
    if has_cert:
        return "done"
    if "course completed" in page_lower or "you have completed" in page_lower:
        return "done"
    if "congratulations" in page_lower and any(
        w in page_lower for w in ["all modules", "completed the course", "finished the course"]
    ):
        return "done"

    # ── Roadmap ──────────────────────────────────────────────────
    if "start roadmap now" in buttons_text or "start roadmap now" in page_lower:
        return "roadmap"
    if "roadmap" in title_lower and ("courses" in page_lower or "level" in page_lower):
        return "roadmap"
    if "/learn/course/" not in url and "/problems/" not in url:
        if "c language with beginner dsa" in page_lower or "roadmap" in page_lower:
            return "roadmap"

    # ── Running (submission still evaluating) ────────────────────
    if output_text:
        output_lower = output_text.lower()
        if any(w in output_lower for w in ["running", "evaluating", "judging", "compiling", "pending"]):
            if not any(w in output_lower for w in ["accepted", "wrong answer", "error", "time limit"]):
                return "running"

    # ── Quiz ─────────────────────────────────────────────────────
    if has_radio and not has_editor:
        return "quiz"

    # ── Module completion summary ("Keep Learning") ───────────────
    if any("keep learning" in b for b in buttons_lower):
        return "module_done"
    if "xp gained" in page_lower or "concepts learned" in page_lower:
        if "keep learning" in page_lower:
            return "module_done"

    # ── Reading page ─────────────────────────────────────────────
    if not has_submit and not has_editor:
        if has_next or any("keep learning" in b for b in buttons_lower):
            return "reading"
        # Could be an outline page
        if "module" in page_lower or "syllabus" in page_lower:
            return "outline"
        # Still a reading page if we have statement content
        if statement.strip():
            return "reading"

    # ── Exercise vs Guided ───────────────────────────────────────
    if has_editor or has_submit:
        code_written = is_code_written(editor_text, statement)

        # Exercise indicators
        if has_solution_tab:
            return "exercise"

        if not code_written:
            return "exercise"

        # Check if statement says to run/submit existing code → guided
        if any(kw in statement_lower for kw in RUN_STATEMENT_KEYWORDS):
            return "guided"

        # If code is written and no Solution tab, likely guided
        if code_written:
            return "guided"

        return "exercise"

    # ── Outline ──────────────────────────────────────────────────
    if "module" in page_lower and not has_submit and not has_next:
        return "outline"

    # ── Fallback ─────────────────────────────────────────────────
    return "unknown"


def get_decision_summary(obs: dict, layout: str) -> str:
    """Return a human-readable summary of what the classifier decided and why."""
    lines = [
        f"URL: {obs.get('url', '?')}",
        f"Layout: {layout}",
        f"Buttons: {obs.get('buttons', [])}",
        f"Tabs: {obs.get('tabs', [])}",
        f"Has editor: {obs.get('has_editor', False)} ({obs.get('editor_kind', 'none')})",
        f"Has Solution tab: {obs.get('has_solution_tab', False)}",
        f"Has radio: {obs.get('has_radio_buttons', False)}",
        f"Editor written: {is_code_written(obs.get('editor_text', ''), obs.get('statement', ''))}",
        f"Title: {obs.get('title', '?')[:80]}",
    ]

    action_map = {
        "reading": "→ Click Next",
        "guided": "→ Submit existing code, then Next",
        "exercise": "→ Write code, submit, then Next",
        "roadmap": "→ Collect lesson URLs",
        "quiz": "→ Pick answer, submit, then Next",
        "auth": "→ Wait for human login",
        "done": "→ Course complete, exit",
        "outline": "→ Open first unfinished lesson",
        "running": "→ Wait for verdict",
        "unknown": "→ Vision fallback or skip",
    }
    lines.append(action_map.get(layout, "→ ???"))

    return "\n".join(lines)
