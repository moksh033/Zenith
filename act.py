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


def click_next(page: Page, timeout: int = 10000) -> bool:
    """
    Click the Next button and wait for the URL or heading to change.
    Returns True if navigation happened.
    """
    # Check and dismiss any popup before clicking
    dismiss_popups(page)

    old_url = page.url
    old_heading = _get_heading(page)

    try:
        # Find the Next button — try several selectors
        next_btn = None

        # Priority 0: "Keep Learning" / "Next Course" (module / course completion screens)
        try:
            keep_btn = page.locator('button:has-text("Keep Learning"), a:has-text("Keep Learning"), button:has-text("Next Course"), a:has-text("Next Course"), button:has-text("Start Next Course"), a:has-text("Start Next Course")')
            if keep_btn.count() > 0 and keep_btn.first.is_visible(timeout=1000):
                next_btn = keep_btn.first
                btn_name = (next_btn.text_content() or "Next").strip()
                print(f"[act] Found navigation button: '{btn_name}'")
        except Exception:
            pass

        # Priority 1: the bottom-right button-styled Next (screenshots 2-4)
        if next_btn is None:
            selectors = [
                'button:text-is("Next")',
                'button:has-text("Next")',
                'a:has-text("Next")',
                '[class*="next"] button',
            ]
            for sel in selectors:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        for i in range(loc.count()):
                            btn = loc.nth(i)
                            if btn.is_visible(timeout=1000):
                                text = (btn.text_content() or "").strip()
                                if _is_denied(text):
                                    continue
                                # Skip "Prev module" / "Next module" if a plain
                                # "Next" button exists later
                                if "module" in text.lower():
                                    continue
                                next_btn = btn
                                break
                    if next_btn:
                        break
                except Exception:
                    continue

        if next_btn is None:
            # Priority 2: top-right nav-bar "Next >" (visible in screenshots)
            try:
                top_next = page.locator('a:text-is("Next"), span:text-is("Next")')
                for i in range(top_next.count()):
                    btn = top_next.nth(i)
                    if btn.is_visible(timeout=1000):
                        text = (btn.text_content() or "").strip()
                        if not _is_denied(text):
                            next_btn = btn
                            break
            except Exception:
                pass

        if next_btn is None:
            # Priority 3: any remaining element with the word "Next"
            try:
                nav_next = page.locator('text="Next"').last
                if nav_next.is_visible(timeout=1000):
                    text = (nav_next.text_content() or "").strip()
                    if not _is_denied(text):
                        next_btn = nav_next
            except Exception:
                pass

        if next_btn is None:
            print("[act] No Next button found")
            return False

        # Helper to check if element is disabled or has disabled class
        def _is_el_disabled(el) -> bool:
            try:
                if el.is_disabled(timeout=300):
                    return True
                classes = el.get_attribute("class") or ""
                if "disabled" in classes.lower() or "mui-disabled" in classes.lower():
                    return True
                if (el.get_attribute("aria-disabled") or "").lower() == "true":
                    return True
                return False
            except Exception:
                return False

        # Wait up to 3 seconds for Next button to become enabled after verdict animation
        is_disabled = True
        for _ in range(6):
            if not _is_el_disabled(next_btn):
                is_disabled = False
                break
            time.sleep(0.5)

        if is_disabled:
            print("[act] Primary Next button disabled, checking alternative Next elements...")
            try:
                alternatives = page.locator('button:has-text("Next"), a:has-text("Next")')
                for i in range(alternatives.count()):
                    cand = alternatives.nth(i)
                    if cand.is_visible(timeout=500) and not _is_el_disabled(cand):
                        text = (cand.text_content() or "").strip()
                        if not _is_denied(text) and "prev" not in text.lower():
                            next_btn = cand
                            is_disabled = False
                            break
            except Exception:
                pass

        if is_disabled:
            print("[act] All Next buttons are currently disabled")
            return False

        # Check if Next button is a link or inside a link with an href
        href = None
        try:
            href = next_btn.get_attribute("href")
            if not href:
                parent_a = next_btn.locator('xpath=ancestor-or-self::a')
                if parent_a.count() > 0:
                    href = parent_a.first.get_attribute("href")
        except Exception:
            href = None

        # Dismiss any celebration/streak popups before clicking
        dismiss_popups(page)
        try:
            next_btn.scroll_into_view_if_needed(timeout=1000)
        except Exception:
            pass

        # Perform click (normal -> force -> DOM dispatch)
        try:
            next_btn.click(timeout=2500)
        except Exception:
            dismiss_popups(page)
            try:
                next_btn.click(timeout=2500, force=True)
            except Exception:
                try:
                    page.evaluate("el => el.click()", next_btn.element_handle())
                except Exception:
                    pass

        # Wait for page change (SPA navigation)
        changed = _wait_for_page_change(page, old_url, old_heading, timeout=6000)
        if changed:
            return True

        # If click did not trigger SPA route change but href is present, navigate directly
        if href and href.strip() and not href.startswith("#"):
            try:
                import urllib.parse
                target_url = urllib.parse.urljoin(page.url, href)
                if target_url.split("?")[0] != old_url.split("?")[0]:
                    print(f"[act] Direct navigation to Next href: {target_url}")
                    page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
                    time.sleep(1.5)
                    return True
            except Exception as nav_err:
                print(f"[act] Direct href navigation failed: {nav_err}")

        return False

    except Exception as e:
        print(f"[act] Next click failed: {e}")
        return False


def click_submit(page: Page, timeout: int = 10000) -> bool:
    """
    Click the Submit button.
    Returns True if clicked successfully.
    """
    try:
        submit_btn = None
        selectors = [
            'button:text-is("Submit")',
            'button:has-text("Submit")',
            'input[type="submit"]',
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    for i in range(loc.count()):
                        btn = loc.nth(i)
                        if btn.is_visible(timeout=1000):
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
            print("[act] No Submit button found")
            return False

        # Check if disabled
        try:
            if submit_btn.is_disabled(timeout=1000):
                print("[act] Submit button is disabled")
                return False
        except Exception:
            pass

        dismiss_popups(page)
        try:
            submit_btn.click(timeout=timeout)
        except Exception as click_err:
            if "intercepts pointer events" in str(click_err) or "Timeout" in str(click_err):
                print("[act] Submit intercepted by popup, dismissing...")
                dismiss_popups(page)
                try:
                    submit_btn.click(timeout=3000)
                except Exception:
                    print("[act] Retrying submit with force=True...")
                    submit_btn.click(timeout=3000, force=True)
            else:
                raise click_err

        return True

    except Exception as e:
        print(f"[act] Submit click failed: {e}")
        return False


def wait_for_verdict(page: Page, timeout: int = 30000) -> str:
    """
    Poll the output panel until a definite verdict appears or timeout.
    Returns: 'accepted', 'wrong_answer', 'compile_error', 'runtime_error', 'time_limit', or 'timeout'.
    NEVER assumes a timeout is accepted.
    """
    start = time.time()
    poll_interval = 1.0

    while (time.time() - start) * 1000 < timeout:
        verdict = _read_verdict(page)
        if verdict in ("accepted", "wrong_answer", "compile_error", "runtime_error", "time_limit"):
            return verdict
        time.sleep(poll_interval)

    print("[act] Verdict timeout — no definite verdict reached")
    return "timeout"


def _read_verdict(page: Page) -> str:
    """
    Read and parse the current verdict from CodeChef's output/judge panel.
    Strictly distinguishes compilation errors, wrong answers, and accepted submissions.
    """
    try:
        # Step 1: Query DOM for CodeChef's Status line and verdict text
        text = page.evaluate(r"""() => {
            // First check for explicit Status block (e.g. "Status : Compilation error", "Status : Correct Answer")
            const allNodes = document.querySelectorAll('*');
            for (const el of allNodes) {
                if (el.children.length <= 2 && el.offsetParent !== null) {
                    const t = (el.innerText || el.textContent || '').trim();
                    if (/^Status\s*:\s*[A-Za-z ]+/i.test(t)) {
                        return t;
                    }
                }
            }

            // Next check output/judge/verdict containers
            const selectors = [
                '[class*="verdict"]',
                '[class*="submission-status"]',
                '[class*="judge-output"]',
                '[class*="output-panel"]',
                '[class*="console-output"]',
                '[class*="test-result"]',
                '[class*="status"]',
                '.judge-output',
                '.output-panel',
                '.console-output',
            ];
            for (const sel of selectors) {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    if (el.offsetParent === null) continue;
                    const t = (el.innerText || el.textContent || '').trim();
                    if (t.length > 0 && t.length < 3000) {
                        const lower = t.toLowerCase();
                        if (lower.includes('compilation error') || lower.includes('fatal error') ||
                            lower.includes('wrong answer') || lower.includes('correct answer') ||
                            lower.includes('accepted') || lower.includes('runtime error') ||
                            lower.includes('time limit') || lower.includes('status :') ||
                            lower.includes('status:')) {
                            return t;
                        }
                    }
                }
            }

            // Next check compiler/error boxes directly
            const errBox = document.querySelector('.error, [class*="error-container"], [class*="errorMessage"]');
            if (errBox && errBox.offsetParent !== null) {
                const t = (errBox.innerText || errBox.textContent || '').trim();
                if (t.length > 0) return 'Compilation error: ' + t;
            }

            return '';
        }""")

        if not text:
            return ""

        lower = text.lower()

        # PRIORITY 1: Compilation Errors (e.g. gcc/g++ errors, fatal error, syntax error)
        if any(w in lower for w in [
            "compilation error", "compile error", "fatal error:", "fatal error",
            "compilation terminated", "sol.c:", "sol.cpp:", "sol.py:",
            "no such file or directory", "undefined reference"
        ]):
            return "compile_error"

        # PRIORITY 2: Runtime Errors (e.g. SIGSEGV, NZEC, Exception)
        if any(w in lower for w in [
            "runtime error", "sigsegv", "sigfpe", "nzec", "segmentation fault",
            "traceback (most recent call last)"
        ]):
            return "runtime_error"

        # PRIORITY 3: Time Limit Exceeded
        if any(w in lower for w in [
            "time limit exceeded", "tle", "timed out"
        ]):
            return "time_limit"

        # PRIORITY 4: Wrong Answer & Failed Test Cases
        # Check explicit failure terms
        if any(w in lower for w in [
            "wrong answer", "incorrect", "test case failed", "failed test case",
            "status : wrong", "did not match expected", "test case 1: failed"
        ]):
            return "wrong_answer"

        # Check fractional pass counts: e.g. "0/2 passed", "1/2 test cases passed"
        import re
        match_fraction = re.search(r'(\d+)\s*/\s*(\d+)', lower)
        if match_fraction:
            passed_cnt = int(match_fraction.group(1))
            total_cnt = int(match_fraction.group(2))
            if passed_cnt < total_cnt:
                return "wrong_answer"

        # PRIORITY 5: Evaluating / Running (in progress)
        if any(w in lower for w in ["running", "evaluating", "judging", "compiling", "submitting", "pending"]):
            if not any(w in lower for w in ["correct answer", "accepted"]):
                return "running"

        # PRIORITY 6: Explicit Accepted / Correct Answer
        # MUST have explicit confirmation AND zero failure keywords
        if any(w in lower for w in [
            "correct answer", "accepted", "all test cases passed", "100% score",
            "status : correct", "status: correct", "status : accepted"
        ]):
            # Safety safeguard: ensure no error words are present
            if not any(w in lower for w in ["compilation", "error", "wrong", "fail", "incorrect", "fatal"]):
                return "accepted"

        return ""

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
            time.sleep(1.0)  # Let the page settle
            return True
        new_heading = _get_heading(page)
        if new_heading and new_heading != old_heading:
            time.sleep(1.0)
            return True
        time.sleep(0.5)
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
