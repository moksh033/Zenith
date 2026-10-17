"""
progress.py – Persistent lesson progress tracker.

Writes to progress.json after every lesson so a crash resumes at the next
unfinished URL.  Each entry tracks: url, status (done | blocked | running),
submit count, action count, and an optional note.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone

PROGRESS_FILE = Path(__file__).parent / "progress.json"


def _load() -> dict:
    """Load progress dict from disk."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"lessons": {}, "courses": {}, "meta": {}}


def _save(data: dict) -> None:
    """Write progress dict to disk atomically."""
    tmp = PROGRESS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(PROGRESS_FILE)


def mark_lesson(url: str, status: str, note: str = "") -> None:
    """
    Mark a lesson URL with a status: 'done', 'blocked', or 'running'.
    """
    data = _load()
    entry = data["lessons"].get(url, {
        "status": "unknown",
        "submits": 0,
        "actions": 0,
        "note": "",
        "updated": "",
    })
    entry["status"] = status
    if note:
        entry["note"] = note
    entry["updated"] = datetime.now(timezone.utc).isoformat()
    data["lessons"][url] = entry
    _save(data)


def increment_submits(url: str) -> int:
    """Increment and return the submit count for a lesson."""
    data = _load()
    entry = data["lessons"].setdefault(url, {
        "status": "running",
        "submits": 0,
        "actions": 0,
        "note": "",
        "updated": "",
    })
    entry["submits"] = entry.get("submits", 0) + 1
    entry["updated"] = datetime.now(timezone.utc).isoformat()
    _save(data)
    return entry["submits"]


def increment_actions(url: str) -> int:
    """Increment and return the action count for a lesson."""
    data = _load()
    entry = data["lessons"].setdefault(url, {
        "status": "running",
        "submits": 0,
        "actions": 0,
        "note": "",
        "updated": "",
    })
    entry["actions"] = entry.get("actions", 0) + 1
    entry["updated"] = datetime.now(timezone.utc).isoformat()
    _save(data)
    return entry["actions"]


def get_lesson_status(url: str) -> str:
    """Return the status of a lesson: 'done', 'blocked', 'running', or 'unknown'."""
    data = _load()
    return data["lessons"].get(url, {}).get("status", "unknown")


def get_submit_count(url: str) -> int:
    """Return the number of submits made for this lesson."""
    data = _load()
    return data["lessons"].get(url, {}).get("submits", 0)


def get_action_count(url: str) -> int:
    """Return the number of actions taken on this lesson."""
    data = _load()
    return data["lessons"].get(url, {}).get("actions", 0)


def is_done(url: str) -> bool:
    """True if lesson is marked done."""
    return get_lesson_status(url) == "done"


def is_blocked(url: str) -> bool:
    """True if lesson is marked blocked."""
    return get_lesson_status(url) == "blocked"


def mark_course_done(course_id: str) -> None:
    """Mark a course as completed."""
    data = _load()
    data["courses"][course_id] = {
        "status": "done",
        "completed": datetime.now(timezone.utc).isoformat(),
    }
    _save(data)


def is_course_done(course_id: str) -> bool:
    """Check if a course is already completed."""
    data = _load()
    return data["courses"].get(course_id, {}).get("status") == "done"


def get_all_lessons() -> dict:
    """Return the full lessons dict."""
    return _load().get("lessons", {})


def get_last_active_url() -> str:
    """Return the most recently active lesson URL."""
    lessons = get_all_lessons()
    if not lessons:
        return ""
    # Sort by timestamp descending
    sorted_lessons = sorted(
        lessons.items(),
        key=lambda x: x[1].get("updated", ""),
        reverse=True
    )
    # Prefer lessons that were completed or active (exclude accidental blocked clicks)
    for url, info in sorted_lessons:
        if info.get("status") in ("done", "running") and "CDEVINTRO/problems/CDEV004B" not in url:
            return url
    return sorted_lessons[0][0] if sorted_lessons else ""

