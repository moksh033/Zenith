"""
editor.py – Monaco / Ace / CodeMirror / textarea adapter.

Probes the page once and locks onto whichever editor object exists.
Handles the "Submit stays disabled after API edit" issue by doing a
read-back + keyboard insert fallback.

Adapter behavior:
1. Set the full program through the editor API.
2. Read the buffer back and require it to match.
3. If Submit is still disabled, focus + select-all + keyboard insert.
4. Read the buffer back again.
5. Set the language dropdown before submit.
"""

import time
from playwright.sync_api import Page, TimeoutError as PwTimeout


def detect_editor(page: Page) -> str:
    """
    Detect which editor is on the page.
    Returns 'monaco', 'ace', 'codemirror', 'textarea', or ''.
    """
    try:
        kind = page.evaluate("""() => {
            if (window.monaco && window.monaco.editor) {
                const eds = window.monaco.editor.getEditors?.() || [];
                const models = window.monaco.editor.getModels?.() || [];
                if (eds.length > 0 || models.length > 0) return 'monaco';
            }
            if (document.querySelector('.monaco-editor')) return 'monaco';
            if (document.querySelector('.ace_editor')) return 'ace';
            if (document.querySelector('.CodeMirror') ||
                document.querySelector('.cm-editor')) return 'codemirror';
            if (document.querySelector('textarea[name*="code"], textarea[id*="code"]'))
                return 'textarea';
            return '';
        }""")
        return kind
    except Exception:
        return ""


def read_editor(page: Page, kind: str = "") -> str:
    """Read the current editor content."""
    if not kind:
        kind = detect_editor(page)

    try:
        if kind == "monaco":
            return page.evaluate("""() => {
                const eds = window.monaco?.editor?.getEditors?.() || [];
                if (eds.length > 0) return eds[0].getValue();
                const models = window.monaco?.editor?.getModels?.() || [];
                if (models.length > 0) return models[0].getValue();
                return '';
            }""") or ""

        elif kind == "ace":
            return page.evaluate("""() => {
                const el = document.querySelector('.ace_editor');
                if (el?.env?.editor) return el.env.editor.getValue();
                return '';
            }""") or ""

        elif kind == "codemirror":
            return page.evaluate("""() => {
                const cm5 = document.querySelector('.CodeMirror');
                if (cm5?.CodeMirror) return cm5.CodeMirror.getValue();
                const cm6 = document.querySelector('.cm-editor');
                if (cm6?.cmView?.view) return cm6.cmView.view.state.doc.toString();
                return '';
            }""") or ""

        elif kind == "textarea":
            return page.evaluate("""() => {
                const ta = document.querySelector(
                    'textarea[name*="code"], textarea[id*="code"], textarea.code-editor'
                );
                return ta ? ta.value : '';
            }""") or ""
    except Exception:
        pass

    return ""


def write_editor_api(page: Page, code: str, kind: str = "") -> bool:
    """
    Write code into the editor via its API.
    Returns True if the write succeeded (read-back matches).
    """
    if not kind:
        kind = detect_editor(page)

    try:
        if kind == "monaco":
            page.evaluate("""(code) => {
                const eds = window.monaco?.editor?.getEditors?.() || [];
                if (eds.length > 0) {
                    const ed = eds[0];
                    const model = ed.getModel();
                    if (model) {
                        const fullRange = model.getFullModelRange();
                        ed.executeEdits('codechef-solver', [{
                            range: fullRange,
                            text: code,
                            forceMoveMarkers: true
                        }]);
                        // Also trigger change events
                        ed.trigger('codechef-solver', 'editor.action.formatDocument', {});
                        return;
                    }
                }
                // Fallback: set via model
                const models = window.monaco?.editor?.getModels?.() || [];
                if (models.length > 0) {
                    models[0].setValue(code);
                }
            }""", code)

        elif kind == "ace":
            page.evaluate("""(code) => {
                const el = document.querySelector('.ace_editor');
                if (el?.env?.editor) {
                    el.env.editor.setValue(code, -1);
                    el.env.editor.clearSelection();
                }
            }""", code)

        elif kind == "codemirror":
            page.evaluate("""(code) => {
                const cm5 = document.querySelector('.CodeMirror');
                if (cm5?.CodeMirror) {
                    cm5.CodeMirror.setValue(code);
                    return;
                }
                const cm6 = document.querySelector('.cm-editor');
                if (cm6?.cmView?.view) {
                    const view = cm6.cmView.view;
                    view.dispatch({
                        changes: {
                            from: 0,
                            to: view.state.doc.length,
                            insert: code
                        }
                    });
                }
            }""", code)

        elif kind == "textarea":
            page.evaluate("""(code) => {
                const ta = document.querySelector(
                    'textarea[name*="code"], textarea[id*="code"], textarea.code-editor'
                );
                if (ta) {
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value'
                    ).set;
                    nativeInputValueSetter.call(ta, code);
                    ta.dispatchEvent(new Event('input', { bubbles: true }));
                    ta.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }""", code)
        else:
            return False

        time.sleep(0.5)
        return True

    except Exception as e:
        print(f"[editor] API write failed: {e}")
        return False


def write_editor_keyboard(page: Page, code: str, kind: str = "") -> bool:
    """
    Write code via keyboard input (select-all, then type).
    This triggers the page's input handlers so Submit enables.
    """
    if not kind:
        kind = detect_editor(page)

    try:
        # Focus the editor
        if kind == "monaco":
            # Click into the Monaco editor area
            editor_el = page.locator('.monaco-editor .view-lines, .monaco-editor textarea')
            if editor_el.count() > 0:
                editor_el.first.click(timeout=3000)
            else:
                page.locator('.monaco-editor').first.click(timeout=3000)

        elif kind == "ace":
            page.locator('.ace_editor .ace_text-input, .ace_editor').first.click(timeout=3000)

        elif kind == "codemirror":
            cm = page.locator('.CodeMirror, .cm-editor')
            if cm.count() > 0:
                cm.first.click(timeout=3000)

        elif kind == "textarea":
            page.locator(
                'textarea[name*="code"], textarea[id*="code"], textarea.code-editor'
            ).first.click(timeout=3000)

        time.sleep(0.3)

        # Select all and delete
        page.keyboard.press("Control+a")
        time.sleep(0.1)
        page.keyboard.press("Delete")
        time.sleep(0.2)

        # Type the code using insert_text for speed
        page.keyboard.insert_text(code)
        time.sleep(0.5)

        return True

    except Exception as e:
        print(f"[editor] Keyboard write failed: {e}")
        return False


def write_code(page: Page, code: str) -> bool:
    """
    Full write sequence with read-back verification and fallback.

    1. API write → read-back check
    2. If Submit still disabled → keyboard fallback → read-back check

    Returns True if the code was successfully written.
    """
    kind = detect_editor(page)
    if not kind:
        print("[editor] No editor detected on page")
        return False

    original = read_editor(page, kind)

    # Step 1: API write (fast, instant)
    api_ok = write_editor_api(page, code, kind)
    if api_ok:
        readback = read_editor(page, kind)
        if _code_matches(code, readback) or _code_close_enough(code, readback):
            return True
        print("[editor] Read-back mismatch after API write, trying keyboard")

    # Step 2: Keyboard fallback (only if API write didn't put code in editor)
    kb_ok = write_editor_keyboard(page, code, kind)
    if kb_ok:
        readback = read_editor(page, kind)
        if _code_matches(code, readback) or _code_close_enough(code, readback):
            return True

    # Step 3: Restore original if write completely failed
    print("[editor] Write failed, restoring original")
    write_editor_api(page, original, kind)
    return False


def detect_code_language(code: str) -> str:
    """
    Detect the programming language of a code snippet.
    Returns 'C++', 'Python3', 'Java', or 'C'.
    Defaults to 'C++' for C-family code because C++ compiler on CodeChef
    compiles C code seamlessly, whereas C compiler fails on C++ code.
    """
    if not code or not code.strip():
        return "C++"

    # Python indicators
    py_indicators = ["def ", "print(", "import sys", "sys.stdin", ":\n", "elif "]
    if any(ind in code for ind in py_indicators) and "#include" not in code:
        return "Python3"

    # Java indicators
    if "public class" in code or "System.out.print" in code or "import java." in code:
        return "Java"

    # C++ indicators
    cpp_indicators = [
        "<iostream>", "<vector>", "<string>", "<algorithm>", "<map>", "<set>",
        "<bits/stdc++.h>", "using namespace std", "std::", "cout", "cin",
        "endl", "vector<", "string ", "nullptr", "bool ", "class "
    ]
    if any(ind in code for ind in cpp_indicators):
        return "C++"

    # Default to C++ because on competitive programming platforms like CodeChef,
    # the C++ compiler safely compiles standard C code (printf, scanf, malloc, etc.)
    # without compilation errors.
    return "C++"


def _get_current_language(page: Page) -> str:
    """Get the currently selected language from CodeChef's editor header."""
    try:
        return page.evaluate("""() => {
            // Check CodeChef's MUI combobox (id="language-select")
            const sel = document.querySelector('#language-select');
            if (sel) {
                return (sel.innerText || sel.textContent || '').trim();
            }
            // Check native <select>
            const nativeSel = document.querySelector('select[class*="lang"], select[id*="lang"]');
            if (nativeSel) return nativeSel.value || nativeSel.options[nativeSel.selectedIndex]?.text || '';

            // Check header buttons
            const btns = document.querySelectorAll('button, [class*="lang"], [class*="select"]');
            for (const b of btns) {
                const t = b.textContent.trim();
                if (['C', 'C++', 'Python', 'Python3', 'Java'].includes(t)) return t;
            }
            return '';
        }""") or ""
    except Exception:
        return ""


def set_language(page: Page, language: str = "C++") -> bool:
    """
    Set the language dropdown to the specified language (e.g. 'C++', 'C', 'Python3', 'Java').
    Checks first if already set.
    """
    try:
        lang_target = (language or "C++").strip()
        if lang_target.lower() in ("cpp", "c++", "c++14", "c++17", "c++20"):
            target_names = ["C++"]
            target_values = ["C++"]
        elif lang_target.lower() in ("c",):
            target_names = ["C"]
            target_values = ["C"]
        elif lang_target.lower() in ("python", "python3", "py"):
            target_names = ["Python3", "Python"]
            target_values = ["PYTH 3", "Python3", "PYTHON"]
        elif lang_target.lower() in ("java",):
            target_names = ["Java"]
            target_values = ["JAVA"]
        else:
            target_names = [lang_target]
            target_values = [lang_target]

        # Step 0: Check if language is already set
        current = _get_current_language(page)
        for tn in target_names:
            if current.upper() == tn.upper():
                return True

        # Step 1: CodeChef Material-UI Select (id="language-select")
        try:
            sel = page.locator('#language-select')
            if sel.count() > 0 and sel.first.is_visible(timeout=1000):
                sel.first.click(timeout=1500)
                time.sleep(0.3)
                for val in target_values:
                    opt = page.locator(f'li[data-value="{val}"]').first
                    if opt.count() > 0 and opt.is_visible(timeout=500):
                        opt.click(timeout=1000)
                        time.sleep(0.3)
                        print(f"[editor] Language set to {val}")
                        return True
                for tn in target_names:
                    opt = page.locator(f'li[role="option"]:has-text("{tn}")').first
                    if opt.count() > 0 and opt.is_visible(timeout=500):
                        opt.click(timeout=1000)
                        time.sleep(0.3)
                        print(f"[editor] Language set to {tn}")
                        return True
                # Close listbox if not matched
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
        except Exception:
            pass

        # Step 2: Custom dropdown buttons / generic selectors
        dropdown_selectors = [
            '[class*="language"] button',
            '[class*="lang-dropdown"]',
            'button:has-text("C")',
        ]
        for sel_name in dropdown_selectors:
            try:
                el = page.locator(sel_name)
                if el.count() > 0 and el.first.is_visible(timeout=500):
                    text = (el.first.text_content() or "").strip()
                    for tn in target_names:
                        if text.upper() == tn.upper():
                            return True
                    el.first.click(timeout=1000)
                    time.sleep(0.2)
                    for tn in target_names:
                        option = page.locator(f'text="{tn}"').first
                        if option.is_visible(timeout=500):
                            option.click(timeout=500)
                            time.sleep(0.2)
                            return True
            except Exception:
                continue

        return False

    except Exception as e:
        print(f"[editor] Failed to set language: {e}")
        return False


def _is_submit_disabled(page: Page) -> bool:
    """Check if the Submit button is disabled."""
    try:
        return page.evaluate("""() => {
            const buttons = document.querySelectorAll('button');
            for (const b of buttons) {
                if (b.textContent.trim() === 'Submit') {
                    return b.disabled || b.getAttribute('aria-disabled') === 'true';
                }
            }
            return true;
        }""")
    except Exception:
        return True


def _code_matches(expected: str, actual: str) -> bool:
    """Check if expected and actual code match (normalizing whitespace)."""
    return _normalize(expected) == _normalize(actual)


def _code_close_enough(expected: str, actual: str) -> bool:
    """Check if code is close enough (ignoring trailing whitespace/newlines)."""
    e = expected.strip()
    a = actual.strip()
    # Allow minor trailing whitespace differences
    return e == a or e.replace('\r\n', '\n') == a.replace('\r\n', '\n')


def _normalize(text: str) -> str:
    """Normalize code for comparison."""
    return text.replace('\r\n', '\n').replace('\r', '\n').strip()
