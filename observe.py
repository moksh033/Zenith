"""
observe.py – DOM reading + screenshot capture.

Every step takes two readings and merges them:
1. DOM reading: URL, visible button names, tab names, statement text,
   editor text, language dropdown, disabled state of Next/Submit,
   and output panel text.
2. Screenshot: saved under runs/<timestamp>/ for diagnostics.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from playwright.sync_api import Page, TimeoutError as PwTimeout

RUNS_DIR = Path(__file__).parent / "runs"


def _ensure_run_dir() -> Path:
    """Create and return the run directory for this session."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


# Module-level cache for the run directory so screenshots go to the same folder
_run_dir: Path | None = None


def get_run_dir() -> Path:
    """Return the session run directory, creating it once."""
    global _run_dir
    if _run_dir is None:
        _run_dir = _ensure_run_dir()
    return _run_dir


def take_screenshot(page: Page, label: str = "step") -> str:
    """Save a screenshot and return its path."""
    run_dir = get_run_dir()
    ts = datetime.now().strftime("%H%M%S_%f")
    filename = f"{label}_{ts}.png"
    path = run_dir / filename
    try:
        page.screenshot(path=str(path), full_page=False, timeout=10000)
    except Exception:
        # If screenshot fails, continue without it
        return ""
    return str(path)


def read_dom(page: Page) -> dict:
    """
    Extract a structured summary of the page DOM.
    Returns a dict with keys:
        url, buttons, tabs, statement, editor_text, editor_kind,
        language, submit_disabled, next_disabled, output_text,
        has_editor, has_solution_tab, has_radio_buttons, title,
        has_login_form, has_certificate, page_text
    """
    url = page.url

    # ── Buttons ──────────────────────────────────────────────────
    buttons = _get_buttons(page)

    # ── Tabs (Statement, Solution, AI Help) ──────────────────────
    tabs = _get_tabs(page)

    # ── Statement text ───────────────────────────────────────────
    statement = _get_statement(page)

    # ── Editor ───────────────────────────────────────────────────
    editor_text, editor_kind = _get_editor(page)

    # ── Language dropdown ────────────────────────────────────────
    language = _get_language(page)

    # ── Button disabled states ───────────────────────────────────
    submit_disabled = _is_button_disabled(page, "Submit")
    next_disabled = _is_button_disabled(page, "Next")

    # ── Output panel ─────────────────────────────────────────────
    output_text = _get_output(page)

    # ── Feature flags ────────────────────────────────────────────
    has_editor = bool(editor_kind)
    has_solution_tab = "Solution" in tabs
    has_radio = _has_radio_buttons(page)
    has_login = _has_login_form(page)
    has_cert = _has_certificate_elements(page)

    # ── Title / heading ──────────────────────────────────────────
    title = _get_title(page)

    # ── Full visible text (for roadmap detection) ────────────────
    page_text = _get_page_text(page)

    return {
        "url": url,
        "buttons": buttons,
        "tabs": tabs,
        "statement": statement,
        "editor_text": editor_text,
        "editor_kind": editor_kind,
        "language": language,
        "submit_disabled": submit_disabled,
        "next_disabled": next_disabled,
        "output_text": output_text,
        "has_editor": has_editor,
        "has_solution_tab": has_solution_tab,
        "has_radio_buttons": has_radio,
        "has_login_form": has_login,
        "has_certificate": has_cert,
        "title": title,
        "page_text": page_text,
    }


# ═══════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════

def _get_buttons(page: Page) -> list[str]:
    """Return visible button labels."""
    try:
        btns = page.evaluate("""() => {
            const result = [];
            // <button> elements
            for (const b of document.querySelectorAll('button')) {
                if (b.offsetParent !== null || b.offsetWidth > 0) {
                    const txt = (b.textContent || '').trim();
                    if (txt) result.push(txt);
                }
            }
            // <a> that look like buttons (role=button or common classes)
            for (const a of document.querySelectorAll('a[role="button"], a.btn, a.button')) {
                if (a.offsetParent !== null || a.offsetWidth > 0) {
                    const txt = (a.textContent || '').trim();
                    if (txt) result.push(txt);
                }
            }
            // <input type="submit">
            for (const inp of document.querySelectorAll('input[type="submit"]')) {
                if (inp.offsetParent !== null || inp.offsetWidth > 0) {
                    result.push(inp.value || 'Submit');
                }
            }
            return result;
        }""")
        return btns
    except Exception:
        return []


def _get_tabs(page: Page) -> list[str]:
    """Return visible tab labels (Statement, Solution, AI Help, etc.)."""
    try:
        tabs = page.evaluate("""() => {
            const result = [];
            // Tab-like elements: role=tab, or nav links near the top
            const candidates = document.querySelectorAll(
                '[role="tab"], .tab, .nav-link, .MuiTab-root'
            );
            for (const el of candidates) {
                if (el.offsetParent !== null || el.offsetWidth > 0) {
                    const txt = (el.textContent || '').trim();
                    if (txt) result.push(txt);
                }
            }
            // Also check for tab-like clickable text in the problem header area
            if (result.length === 0) {
                // CodeChef uses plain divs/spans as tabs sometimes
                const header = document.querySelector('.problem-tab-container, .tabs-container, .problem-tabs');
                if (header) {
                    for (const child of header.children) {
                        const txt = (child.textContent || '').trim();
                        if (txt) result.push(txt);
                    }
                }
            }
            return result;
        }""")
        # Fallback: search for text that looks like tab names
        if not tabs:
            tabs = _find_tab_text(page)
        return tabs
    except Exception:
        return _find_tab_text(page)


def _find_tab_text(page: Page) -> list[str]:
    """Fallback tab detection by looking for known tab names in clickable elements."""
    known_tabs = ["Statement", "Solution", "AI Help", "Submissions", "Discussion", "Editorial"]
    found = []
    for tab_name in known_tabs:
        try:
            el = page.locator(f"text='{tab_name}'").first
            if el.is_visible(timeout=500):
                found.append(tab_name)
        except Exception:
            continue
    return found


def _get_statement(page: Page) -> str:
    """Extract the problem statement text."""
    try:
        text = page.evaluate("""() => {
            // Try common statement containers
            const selectors = [
                '.problem-statement',
                '.problem_content',
                '.statement-content',
                '[class*="statement"]',
                '[class*="problem-body"]',
                '.markdown-body',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.textContent.trim().length > 20) {
                    return el.textContent.trim().substring(0, 3000);
                }
            }
            // Fallback: the main content area (left side on CodeChef learn)
            const main = document.querySelector('main, .main-content, [class*="content"]');
            if (main) return main.textContent.trim().substring(0, 3000);
            return '';
        }""")
        return text
    except Exception:
        return ""


def _get_editor(page: Page) -> tuple[str, str]:
    """
    Return (editor_text, editor_kind) where editor_kind is one of:
    'monaco', 'ace', 'codemirror', 'textarea', or '' if none found.
    """
    # Monaco
    try:
        has_monaco = page.evaluate("""() => {
            return !!(window.monaco ||
                      document.querySelector('.monaco-editor') ||
                      document.querySelector('[data-mode-id]'));
        }""")
        if has_monaco:
            text = page.evaluate("""() => {
                // Try to get Monaco editor instance
                const editors = window.monaco?.editor?.getEditors?.() || [];
                if (editors.length > 0) return editors[0].getValue();
                // Fallback: get from the model
                const models = window.monaco?.editor?.getModels?.() || [];
                if (models.length > 0) return models[0].getValue();
                return null;
            }""")
            if text is not None:
                return (text, "monaco")
    except Exception:
        pass

    # Ace
    try:
        has_ace = page.evaluate("""() => {
            return !!(window.ace ||
                      document.querySelector('.ace_editor') ||
                      document.querySelector('[class*="ace_editor"]'));
        }""")
        if has_ace:
            text = page.evaluate("""() => {
                const el = document.querySelector('.ace_editor');
                if (el && el.env && el.env.editor) {
                    return el.env.editor.getValue();
                }
                // Try global ace instances
                if (window.ace && window.ace.edit) {
                    const editors = document.querySelectorAll('.ace_editor');
                    for (const ed of editors) {
                        if (ed.env && ed.env.editor) return ed.env.editor.getValue();
                    }
                }
                return null;
            }""")
            if text is not None:
                return (text, "ace")
    except Exception:
        pass

    # CodeMirror
    try:
        has_cm = page.evaluate("""() => {
            return !!(document.querySelector('.CodeMirror') ||
                      document.querySelector('.cm-editor'));
        }""")
        if has_cm:
            text = page.evaluate("""() => {
                // CM5
                const cm5 = document.querySelector('.CodeMirror');
                if (cm5 && cm5.CodeMirror) return cm5.CodeMirror.getValue();
                // CM6
                const cm6 = document.querySelector('.cm-editor');
                if (cm6 && cm6.cmView && cm6.cmView.view) {
                    return cm6.cmView.view.state.doc.toString();
                }
                return null;
            }""")
            if text is not None:
                return (text, "codemirror")
    except Exception:
        pass

    # Textarea fallback
    try:
        text = page.evaluate("""() => {
            const ta = document.querySelector('textarea[name*="code"], textarea[id*="code"], textarea.code-editor');
            if (ta) return ta.value;
            return null;
        }""")
        if text is not None:
            return (text, "textarea")
    except Exception:
        pass

    return ("", "")


def _get_language(page: Page) -> str:
    """Get the selected language from the dropdown."""
    try:
        lang = page.evaluate("""() => {
            // Try <select> element
            const sel = document.querySelector('select[class*="lang"], select[id*="lang"], select[name*="lang"]');
            if (sel) return sel.value || sel.options[sel.selectedIndex]?.text || '';
            // Try custom dropdown showing current language
            const custom = document.querySelector('[class*="language"] [class*="selected"], [class*="lang-select"]');
            if (custom) return custom.textContent.trim();
            // Try the language indicator near the editor (CodeChef pattern)
            const indicator = document.querySelector('.language-selector, [class*="language-dropdown"]');
            if (indicator) return indicator.textContent.trim();
            return '';
        }""")
        return lang.strip()
    except Exception:
        return ""


def _is_button_disabled(page: Page, button_text: str) -> bool:
    """Check if a button with the given text is disabled."""
    try:
        return page.evaluate(f"""(text) => {{
            const buttons = document.querySelectorAll('button');
            for (const b of buttons) {{
                if (b.textContent.trim() === text) {{
                    return b.disabled || b.getAttribute('aria-disabled') === 'true'
                           || b.classList.contains('disabled');
                }}
            }}
            return true;  // Not found = effectively disabled
        }}""", button_text)
    except Exception:
        return True


def _get_output(page: Page) -> str:
    """Read the output/verdict panel below the editor."""
    try:
        text = page.evaluate("""() => {
            const selectors = [
                '.output-panel',
                '.judge-output',
                '[class*="output"]',
                '[class*="verdict"]',
                '[class*="result"]',
                '.console-output',
                '[class*="test-result"]',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.textContent.trim().length > 0) {
                    return el.textContent.trim().substring(0, 2000);
                }
            }
            return '';
        }""")
        return text
    except Exception:
        return ""


def _has_radio_buttons(page: Page) -> bool:
    """Check if there are visible radio buttons or choice cards (quiz)."""
    try:
        return page.evaluate("""() => {
            const radios = document.querySelectorAll('input[type="radio"]');
            if (radios.length > 0) return true;
            // Choice cards pattern
            const choices = document.querySelectorAll('[class*="choice"], [class*="option-card"], [class*="quiz-option"]');
            return choices.length >= 2;
        }""")
    except Exception:
        return False


def _has_login_form(page: Page) -> bool:
    """Check if there's a login form, captcha, or verify wall."""
    try:
        return page.evaluate("""() => {
            const loginForm = document.querySelector('form[action*="login"], form[class*="login"], #login-form');
            if (loginForm) return true;
            const captcha = document.querySelector('[class*="captcha"], [id*="captcha"], .g-recaptcha, .h-captcha');
            if (captcha) return true;
            const verify = document.querySelector('[class*="verify"], [class*="Verify"]');
            if (verify && verify.textContent.includes('erify')) return true;
            return false;
        }""")
    except Exception:
        return False


def _has_certificate_elements(page: Page) -> bool:
    """Check for certificate or course-completed controls."""
    try:
        return page.evaluate("""() => {
            const text = document.body.textContent || '';
            const lower = text.toLowerCase();
            // Check for completion / certificate language
            if (lower.includes('course completed') || lower.includes('congratulations')) {
                // Check for certificate buttons
                const buttons = document.querySelectorAll('button, a');
                for (const b of buttons) {
                    const bt = (b.textContent || '').toLowerCase();
                    if (bt.includes('certificate') || bt.includes('download')) return true;
                }
                // Even without buttons, if the page says completed, return true
                if (lower.includes('course completed') || lower.includes('you have completed'))
                    return true;
            }
            return false;
        }""")
    except Exception:
        return False


def _get_title(page: Page) -> str:
    """Get the page title or main heading."""
    try:
        title = page.evaluate("""() => {
            const h1 = document.querySelector('h1');
            if (h1) return h1.textContent.trim();
            const h2 = document.querySelector('h2');
            if (h2) return h2.textContent.trim();
            return document.title || '';
        }""")
        return title
    except Exception:
        return ""


def _get_page_text(page: Page) -> str:
    """Get truncated full visible page text for roadmap / layout detection."""
    try:
        return page.evaluate("""() => {
            return (document.body?.innerText || '').substring(0, 5000);
        }""")
    except Exception:
        return ""


def observe(page: Page, label: str = "step") -> dict:
    """
    Full observation: DOM reading + screenshot.
    Returns the DOM dict with an added 'screenshot' key.
    """
    dom = read_dom(page)
    screenshot_path = take_screenshot(page, label)
    dom["screenshot"] = screenshot_path
    return dom
