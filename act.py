"""
act.py – Actions: Next, Submit, quiz choice, denylist.

Every action clicks through the DOM, never through pixel coordinates.
Includes the certificate/download denylist so those buttons are never pressed.
"""

from __future__ import annotations

import re
import time
import random
from playwright.sync_api import Page, TimeoutError as PwTimeout

# ─── Denylist: never click these ─────────────────────────────────
CLICK_DENY_PATTERNS = [
    "certificate",
    "download",
    "get certificate",
    "claim certificate",
    "download certificate",
    "share",
    "tweet",
]


def _is_denied(text: str) -> bool:
    """Check if button text matches the denylist."""
    lower = text.lower().strip()
    return any(pat in lower for pat in CLICK_DENY_PATTERNS)


def dismiss_popups(page: Page) -> bool:
    """
    Detect and dismiss overlay popups/modals:
    - Badge earned ("You have earned a diamond badge", streak announcements)
    - Achievement & celebration modals
    Clicks OK, Claim, Continue, Got it, Awesome, or Close icon.
    Returns True if a popup was dismissed.
    """
    try:
        res = page.evaluate("""() => {
            const dialogSelectors = [
                '.MuiDialog-root',
                '[role="dialog"]',
                '[role="presentation"].MuiModal-root',
                '[class*="popupBackground"]',
                '[class*="modal" i]',
                '[class*="popup" i]',
            ];
            
            const dialogs = document.querySelectorAll(dialogSelectors.join(', '));
            for (const d of dialogs) {
                const style = window.getComputedStyle(d);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                    continue;
                }

                // Look for clickable elements inside dialog
                const candidates = Array.from(d.querySelectorAll('button, [role="button"], a, span, div[class*="button" i]'));
                
                // Priority 1: Confirmation text (e.g. OK, Claim, Continue, Got it, Awesome)
                for (const el of candidates) {
                    const text = (el.textContent || '').trim().toLowerCase();
                    if (['ok', 'okay', 'claim', 'continue', 'got it', 'awesome', 'great', 'cool', 'close', 'done', 'collect', 'keep going'].includes(text) ||
                        text.startsWith('ok') || text === 'k' || text.includes('claim') || text.includes('continue')) {
                        el.click();
                        return { dismissed: true, target: text };
                    }
                }

                // Priority 2: Close (X) icon or button
                const closeBtn = d.querySelector(
                    '[aria-label*="close" i], button[class*="close" i], [class*="closeBtn" i], [class*="closeIcon" i], [class*="close-icon" i]'
                );
                if (closeBtn) {
                    closeBtn.click();
                    return { dismissed: true, target: 'close icon' };
                }

                // Priority 3: Any primary MUI button inside dialog
                const muiBtn = d.querySelector('.MuiButton-contained, .MuiButton-root');
                if (muiBtn) {
                    const btnText = (muiBtn.textContent || '').trim();
                    muiBtn.click();
                    return { dismissed: true, target: 'mui button: ' + btnText };
                }
            }

            // Check if backdrop is blocking pointer events
            const backdrop = document.querySelector('.MuiBackdrop-root, .MuiDialog-container');
            if (backdrop) {
                const style = window.getComputedStyle(backdrop);
                if (style.display !== 'none' && style.visibility !== 'hidden') {
                    return { dismissed: false, has_blocking_backdrop: true };
                }
            }

            return { dismissed: false };
        }""")

        if res and res.get("dismissed"):
            print(f"[act] Dismissed popup ({res.get('target')})")
            time.sleep(1)
            return True

        if res and res.get("has_blocking_backdrop"):
            print("[act] Modal backdrop detected, pressing Escape...")
            page.keyboard.press("Escape")
            time.sleep(1)
            return True

    except Exception:
        pass

    return False


def click_keep_learning(page: Page, timeout: int = 10000) -> bool:
    """
    Click 'Keep Learning' / 'Next Module' after completing a module.
    Cleans up confetti canvases and backdrop overlays, supports direct href navigation.
    Returns True if navigation happened.
    """
    try:
        old_url = page.url
        old_heading = _get_heading(page)

        # Clean up any celebration confetti or blocking backdrop overlays
        try:
            page.evaluate("""() => {
                document.querySelectorAll('canvas, [class*="confetti"], [class*="celebration"]').forEach(el => el.remove());
                document.querySelectorAll('.modal-backdrop, [class*="Backdrop-root"]').forEach(el => {
                    if (el.style) el.style.pointerEvents = 'none';
                });
            }""")
        except Exception:
            pass

        candidates = [
            'button:has-text("Keep Learning")',
            'a:has-text("Keep Learning")',
            '[role="button"]:has-text("Keep Learning")',
            'button:has-text("Continue Learning")',
            'a:has-text("Continue Learning")',
            'button:has-text("Next Module")',
            'a:has-text("Next Module")',
            'button:has-text("Start Next Module")',
            'a:has-text("Start Next Module")',
            'button:has-text("Next Course")',
            'a:has-text("Next Course")',
            'button:has-text("Start Next Course")',
            'a:has-text("Start Next Course")',
            'button:has-text("Continue")',
            'a:has-text("Continue")',
            '[role="button"]:has-text("Continue")',
        ]

        target_btn = None
        for sel in candidates:
            try:
                loc = page.locator(sel)
                for i in range(loc.count()):
                    btn = loc.nth(i)
                    if btn.is_visible(timeout=500):
                        text = (btn.text_content() or "").strip().lower()
                        if any(w in text for w in ["share", "review", "retake", "cancel"]):
                            continue
                        target_btn = btn
                        print(f"[act] Found module navigation button: '{(btn.text_content() or '').strip()}'")
                        break
                if target_btn:
                    break
            except Exception:
                continue

        # If not found by explicit text, search for primary contained buttons on completion screen
        if target_btn is None:
            try:
                primary = page.locator('button[class*="contained"], button[class*="primary"], button.btn-primary')
                for i in range(primary.count()):
                    btn = primary.nth(i)
                    if btn.is_visible(timeout=500):
                        text = (btn.text_content() or "").strip().lower()
                        if not any(w in text for w in ["share", "review", "retake", "cancel", "submit", "run"]):
                            target_btn = btn
                            print(f"[act] Found primary module button: '{text}'")
                            break
            except Exception:
                pass

        if target_btn is None:
            return False

        # Extract href if available
        href = None
        try:
            href = target_btn.get_attribute("href")
            if not href:
                parent_a = target_btn.locator('xpath=ancestor-or-self::a')
                if parent_a.count() > 0:
                    href = parent_a.first.get_attribute("href")
        except Exception:
            href = None

        # Scroll into view and click
        try:
            target_btn.scroll_into_view_if_needed(timeout=1000)
        except Exception:
            pass

        try:
            target_btn.click(timeout=2500)
        except Exception:
            try:
                target_btn.click(timeout=2500, force=True)
            except Exception:
                try:
                    page.evaluate("el => el.click()", target_btn.element_handle())
                except Exception:
                    pass

        # Wait for page change
        if _wait_for_page_change(page, old_url, old_heading, timeout=8000):
            return True

        # Fallback to direct href navigation if present
        if href and href.strip() and not href.startswith("#"):
            try:
                import urllib.parse
                target_url = urllib.parse.urljoin(page.url, href)
                if target_url.split("?")[0] != old_url.split("?")[0]:
                    print(f"[act] Direct navigation to module href: {target_url}")
                    page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                    time.sleep(1.5)
                    return True
            except Exception as nav_err:
                print(f"[act] Direct navigation failed: {nav_err}")

        return False

    except Exception as e:
        print(f"[act] click_keep_learning failed: {e}")
        return False


def click_next(page: Page, timeout: int = 5000) -> bool:
    """
    Click the Next button and wait for the URL or heading to change.
    Returns True if navigation happened.
    """
    # Check and dismiss any popup before clicking
    dismiss_popups(page)

    # If Keep Learning / Next Module button is present, prioritize it
    if click_keep_learning(page, timeout=1500):
        return True

    old_url = page.url
    old_heading = _get_heading(page)

    try:
        def _is_el_disabled(el) -> bool:
            try:
                if el.is_disabled(timeout=100):
                    return True
                classes = el.get_attribute("class") or ""
                if "disabled" in classes.lower() or "mui-disabled" in classes.lower():
                    return True
                if (el.get_attribute("aria-disabled") or "").lower() == "true":
                    return True
                return False
            except Exception:
                return False

        # Find Next button candidates (top navbar Next >, bottom bar Next, links, buttons)
        selectors = [
            'button:has-text("Next")',
            'a:has-text("Next")',
            '[role="button"]:has-text("Next")',
            'span:has-text("Next")',
            'div:has-text("Next")',
            '[class*="next"]:not([class*="prev"])',
        ]
        candidates = []
        for sel in selectors:
            try:
                loc = page.locator(sel)
                for i in range(loc.count()):
                    btn = loc.nth(i)
                    if not btn.is_visible(timeout=100):
                        continue
                    text = (btn.text_content() or "").strip()
                    if _is_denied(text):
                        continue
                    lower_text = text.lower()
                    if "prev" in lower_text or "module" in lower_text:
                        continue
                    if "next" in lower_text or "next" in (btn.get_attribute("class") or "").lower():
                        if len(text) <= 30:
                            candidates.append((btn, text))
            except Exception:
                continue

        next_btn = None
        for cand, t in candidates:
            if not _is_el_disabled(cand):
                next_btn = cand
                print(f"[act] Found active Next button: '{t}'")
                break

        if next_btn is None and candidates:
            next_btn = candidates[0][0]
            print(f"[act] Selected candidate Next button: '{candidates[0][1]}'")

        if next_btn is not None:
            # Quick check if button becomes enabled (up to 1s)
            if _is_el_disabled(next_btn):
                for _ in range(10):
                    time.sleep(0.1)
                    if not _is_el_disabled(next_btn):
                        break

            # Dismiss any celebration/streak popups before clicking
            dismiss_popups(page)
            try:
                next_btn.scroll_into_view_if_needed(timeout=500)
            except Exception:
                pass

            # Click (normal -> force -> DOM dispatch)
            try:
                next_btn.click(timeout=1500)
            except Exception:
                dismiss_popups(page)
                try:
                    next_btn.click(timeout=1500, force=True)
                except Exception:
                    try:
                        page.evaluate("el => { (el.closest('a, button, [role=\"button\"]') || el).click(); }", next_btn.element_handle())
                    except Exception:
                        pass

            # Wait for page change (SPA navigation)
            if _wait_for_page_change(page, old_url, old_heading, timeout=3000):
                return True

        # Fallback 1: CodeChef keyboard shortcut Ctrl+ArrowRight
        try:
            print("[act] Attempting shortcut Control+ArrowRight for Next...")
            page.keyboard.press("Control+ArrowRight")
            if _wait_for_page_change(page, old_url, old_heading, timeout=2000):
                return True
        except Exception:
            pass

        # Fallback 2: Direct href if present on any candidate
        for cand, _ in candidates:
            try:
                href = cand.get_attribute("href")
                if not href:
                    parent_a = cand.locator('xpath=ancestor-or-self::a')
                    if parent_a.count() > 0:
                        href = parent_a.first.get_attribute("href")
                if href and href.strip() and not href.startswith("#"):
                    import urllib.parse
                    target_url = urllib.parse.urljoin(page.url, href)
                    if target_url.split("?")[0] != old_url.split("?")[0]:
                        print(f"[act] Direct navigation to Next href: {target_url}")
                        page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                        return True
            except Exception:
                continue

        return False

    except Exception as e:
        print(f"[act] Next click failed: {e}")
        return False


def click_submit(page: Page, timeout: int = 10000) -> bool:
    """
    Click the Submit button.
    Marks old output elements with data-zenith-old to prevent stale verdict reads.
    Returns True if clicked successfully.
    """
    try:
        dismiss_popups(page)

        # Mark all current verdict/output elements as stale before submit
        try:
            page.evaluate("""() => {
                window._zenith_submit_epoch = Date.now();
                document.querySelectorAll(
                    '.output-panel, .judge-output, [class*="output"], [class*="verdict"], ' +
                    '[class*="result"], [class*="banner"], [class*="alert"], [class*="test-result"]'
                ).forEach(el => el.setAttribute('data-zenith-old', 'true'));
            }""")
        except Exception:
            pass

        submit_btn = None
        selectors = [
            'button:text-is("Submit")',
            'button:has-text("Submit")',
            '[data-testid*="submit" i]',
            'input[type="submit"]',
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                for i in range(loc.count()):
                    btn = loc.nth(i)
                    if btn.is_visible(timeout=500):
                        text = (btn.text_content() or btn.get_attribute("value") or "").strip()
                        if _is_denied(text):
                            continue
                        submit_btn = btn
                        break
                if submit_btn:
                    break
            except Exception:
                continue

        if submit_btn is None:
            # Fallback DOM search for any button containing Submit
            try:
                submit_handle = page.evaluate_handle("""() => {
                    const btns = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"]'));
                    return btns.find(b => (b.innerText || b.value || '').trim().toLowerCase() === 'submit') || null;
                }""")
                if submit_handle and submit_handle.as_element():
                    submit_btn = submit_handle.as_element()
            except Exception:
                pass

        if submit_btn is None:
            print("[act] No Submit button found")
            return False

        # Attempt click (normal -> force -> DOM dispatch)
        dismiss_popups(page)
        clicked = False
        try:
            submit_btn.click(timeout=3000)
            clicked = True
        except Exception:
            try:
                submit_btn.click(timeout=3000, force=True)
                clicked = True
            except Exception:
                try:
                    page.evaluate("el => el.click()", submit_btn)
                    clicked = True
                except Exception:
                    pass

        if not clicked:
            print("[act] Failed to dispatch click on Submit button")
            return False

        print("[act] Submit clicked, tracking evaluation...")
        return True

    except Exception as e:
        print(f"[act] Submit click failed: {e}")
        return False


def wait_for_verdict(page: Page, timeout: int = 15000) -> str:
    """
    Rapid-poll the page every 150ms until a definite verdict appears or timeout.
    Returns: 'accepted', 'wrong_answer', 'compile_error', 'runtime_error', 'time_limit', or 'timeout'.
    NEVER assumes a timeout is accepted.
    """
    start = time.time()
    poll_interval = 0.15  # 150ms for instant feedback
    last_log_sec = 0

    while (time.time() - start) * 1000 < timeout:
        verdict = _read_verdict(page)
        if verdict in ("accepted", "wrong_answer", "compile_error", "runtime_error", "time_limit"):
            elapsed_ms = int((time.time() - start) * 1000)
            print(f"[act] Verdict '{verdict}' detected in {elapsed_ms}ms")
            return verdict

        elapsed = int(time.time() - start)
        if elapsed > 0 and elapsed % 3 == 0 and elapsed != last_log_sec:
            last_log_sec = elapsed
            status_text = verdict if verdict else "evaluating"
            print(f"[act] Still evaluating submission... ({elapsed}s, state: {status_text})")

        time.sleep(poll_interval)

    print("[act] Verdict timeout — no definite verdict reached within time limit")
    return "timeout"


def _read_verdict(page: Page) -> str:
    """
    Ultra-fast single-pass verdict detector (<2ms execution).
    Checks body text and non-stale judge containers for immediate verdicts.
    """
    try:
        verdict = page.evaluate(r"""() => {
            const body = document.body ? document.body.innerText : '';
            const lowerBody = body.toLowerCase();

            // 1. Completion / Celebration modals or buttons (highest confidence Accepted)
            const hasKeepLearning = Array.from(document.querySelectorAll('button, a, [role="button"]')).some(b => {
                const txt = (b.textContent || '').trim().toLowerCase();
                return txt === 'keep learning' || txt === 'next module' || txt === 'start next module' || txt === 'continue learning';
            });
            if (hasKeepLearning) {
                return 'accepted';
            }

            // 2. Positive verdict phrases
            const positivePhrases = [
                "well done, it's correct",
                "well done, its correct",
                "well done",
                "it's correct",
                "its correct",
                "correct answer",
                "all test cases passed",
                "passed all test cases",
                "100% score"
            ];

            const wrongPhrases = [
                "wrong answer",
                "failed on a hidden test case",
                "test case failed"
            ];

            const cePhrases = [
                "compilation error",
                "compile error",
                "fatal error:",
                "sol.c:",
                "compilation terminated"
            ];

            const rePhrases = [
                "runtime error",
                "sigsegv",
                "nzec",
                "segmentation fault"
            ];

            const tlePhrases = [
                "time limit exceeded"
            ];

            // 3. Inspect updated or fresh verdict/output elements (excluding data-zenith-old)
            const feedbackEls = document.querySelectorAll(
                '[class*="verdict"], [class*="output"], [class*="test-result"], ' +
                '[class*="judge-output"], [class*="alert"], [class*="banner"], [class*="feedback"], [class*="result"]'
            );
            for (const el of feedbackEls) {
                if (el.getAttribute('data-zenith-old') === 'true') continue;
                const txt = (el.innerText || el.textContent || '').toLowerCase();
                if (positivePhrases.some(p => txt.includes(p))) {
                    return 'accepted';
                }
                if (cePhrases.some(p => txt.includes(p))) {
                    return 'compile_error';
                }
                if (rePhrases.some(p => txt.includes(p))) {
                    return 'runtime_error';
                }
                if (tlePhrases.some(p => txt.includes(p))) {
                    return 'time_limit';
                }
                if (wrongPhrases.some(p => txt.includes(p)) || txt.includes('find error')) {
                    return 'wrong_answer';
                }
            }

            // 4. Check for 'Find Error?' button (unique to Wrong Answer on CodeChef Learn)
            const buttons = Array.from(document.querySelectorAll('button, a, [role="button"]'));
            const hasFindError = buttons.some(b => {
                if (b.getAttribute('data-zenith-old') === 'true') return false;
                return (b.textContent || '').toLowerCase().includes('find error');
            });

            // 5. Check if currently evaluating/running
            const isEvaluating = (
                lowerBody.includes('evaluating...') ||
                lowerBody.includes('running...') ||
                lowerBody.includes('compiling...') ||
                lowerBody.includes('judging...') ||
                lowerBody.includes('submitting...')
            );
            if (isEvaluating) {
                return 'running';
            }

            // 6. Fast body-level checks
            for (const p of positivePhrases) {
                if (lowerBody.includes(p)) {
                    return 'accepted';
                }
            }

            if (hasFindError) {
                return 'wrong_answer';
            }

            for (const p of cePhrases) {
                if (lowerBody.includes(p)) return 'compile_error';
            }
            for (const p of rePhrases) {
                if (lowerBody.includes(p)) return 'runtime_error';
            }
            for (const p of tlePhrases) {
                if (lowerBody.includes(p)) return 'time_limit';
            }
            for (const p of wrongPhrases) {
                if (lowerBody.includes(p)) return 'wrong_answer';
            }

            return '';
        }""")

        return verdict or ""

    except Exception:
        return ""


def get_verdict_detail(page: Page) -> str:
    """Get the full text from the output/verdict panel for repair context."""
    try:
        return page.evaluate("""() => {
            const selectors = [
                '.output-panel', '.judge-output', '[class*="output"]',
                '[class*="verdict"]', '[class*="result"]', '.console-output',
                '[class*="test-result"]', '[class*="submission-result"]',
                '[class*="status"]', '[class*="error"]',
            ];
            let combined = '';
            for (const sel of selectors) {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    if (el.offsetParent !== null && el.textContent.trim().length > 0) {
                        combined += '\n' + el.textContent.trim();
                        if (combined.length > 2500) break;
                    }
                }
                if (combined.length > 2500) break;
            }
            return combined.substring(0, 2500);
        }""") or ""
    except Exception:
        return ""


def click_quiz_option(page: Page, option_index: int) -> bool:
    """
    Click a quiz option by index (0-based).
    Handles both radio buttons and choice cards.
    """
    try:
        # Try radio buttons
        radios = page.locator('input[type="radio"]')
        if radios.count() > option_index:
            radio = radios.nth(option_index)
            # Click the label or the radio itself
            radio_id = radio.get_attribute("id") or ""
            if radio_id:
                label = page.locator(f'label[for="{radio_id}"]')
                if label.count() > 0 and label.first.is_visible(timeout=1000):
                    label.first.click()
                    return True
            radio.click(force=True)
            return True

        # Try choice cards
        choices = page.locator('[class*="choice"], [class*="option-card"], [class*="quiz-option"]')
        if choices.count() > option_index:
            choices.nth(option_index).click()
            return True

        # Try any clickable option-like elements
        options = page.locator('[class*="option"], [class*="answer"]')
        if options.count() > option_index:
            options.nth(option_index).click()
            return True

        print(f"[act] Could not find quiz option {option_index}")
        return False

    except Exception as e:
        print(f"[act] Quiz option click failed: {e}")
        return False


def get_quiz_data(page: Page) -> dict:
    """
    Extract quiz question and options from the page.
    Returns {"question": str, "options": list[str]}.
    """
    try:
        data = page.evaluate("""() => {
            let question = '';
            let options = [];

            // Get question text
            const qSelectors = [
                '.question', '[class*="question"]', '.quiz-question',
                'h2', 'h3', '.problem-statement', '[class*="statement"]',
            ];
            for (const sel of qSelectors) {
                const el = document.querySelector(sel);
                if (el) {
                    question = el.textContent.trim();
                    if (question.length > 10) break;
                }
            }

            // Get options from radio button labels
            const radios = document.querySelectorAll('input[type="radio"]');
            for (const r of radios) {
                const id = r.id || '';
                let label = '';
                if (id) {
                    const lbl = document.querySelector(`label[for="${id}"]`);
                    if (lbl) label = lbl.textContent.trim();
                }
                if (!label) {
                    const parent = r.closest('label, [class*="option"], [class*="choice"]');
                    if (parent) label = parent.textContent.trim();
                }
                if (label) options.push(label);
            }

            // Fallback: choice cards
            if (options.length === 0) {
                const cards = document.querySelectorAll(
                    '[class*="choice"], [class*="option-card"], [class*="quiz-option"]'
                );
                for (const c of cards) {
                    const text = c.textContent.trim();
                    if (text) options.push(text);
                }
            }

            return { question, options };
        }""")
        return data
    except Exception:
        return {"question": "", "options": []}


def click_start_roadmap(page: Page) -> bool:
    """Click the 'Start Roadmap Now' button."""
    try:
        btn = page.locator('text="Start Roadmap Now"').first
        if btn.is_visible(timeout=3000):
            btn.click()
            time.sleep(2)
            return True
    except Exception:
        pass

    try:
        btn = page.locator('button:has-text("Start Roadmap"), a:has-text("Start Roadmap")').first
        if btn.is_visible(timeout=3000):
            btn.click()
            time.sleep(2)
            return True
    except Exception:
        pass

    return False


def seek_video_to_end(page: Page) -> bool:
    """
    If a same-origin video is on the page, seek it to the end.
    Cross-origin (YouTube) embeds are left alone.
    """
    try:
        seeked = page.evaluate("""() => {
            const videos = document.querySelectorAll('video');
            let found = false;
            for (const v of videos) {
                // Skip cross-origin iframes
                if (v.closest('iframe')) continue;
                if (v.duration && isFinite(v.duration)) {
                    v.currentTime = v.duration - 0.1;
                    found = true;
                }
            }
            return found;
        }""")
        if seeked:
            time.sleep(1)
        return seeked
    except Exception:
        return False


def jitter_delay(min_sec: float = 1.0, max_sec: float = 3.0) -> None:
    """Random delay between actions to avoid rate limiting."""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


def _wait_for_page_change(page: Page, old_url: str, old_heading: str,
                          timeout: int = 15000) -> bool:
    """Wait until the URL or heading changes (SPA navigation)."""
    start = time.time()
    old_base = old_url.split("?")[0]
    while (time.time() - start) * 1000 < timeout:
        new_base = page.url.split("?")[0]
        if new_base != old_base:
            time.sleep(0.2)  # Let the page settle briefly
            return True
        new_heading = _get_heading(page)
        if new_heading and new_heading != old_heading:
            time.sleep(0.2)
            return True
        time.sleep(0.1)
    return False


def _get_heading(page: Page) -> str:
    """Get the first heading on the page."""
    try:
        return page.evaluate("""() => {
            const h = document.querySelector('h1, h2, h3');
            return h ? h.textContent.trim() : '';
        }""") or ""
    except Exception:
        return ""
