"""
main.py – CLI entry point, main runner loop, and resume logic.

Usage:
    python main.py --start-url <URL>
    python main.py --probe          # dump DOM info, click nothing
    python main.py --dry-run        # print decisions, click nothing
    python main.py --roadmap        # continue across roadmap courses

Loop: observe → classify → act → confirm page changed → record
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

import observe
import classify
import editor
import solve
import act
import syllabus
import progress

load_dotenv()

# ─── Constants ────────────────────────────────────────────────────
MAX_SUBMITS_PER_LESSON = 3
MAX_ACTIONS_PER_LESSON = 15
BROWSER_PROFILE_DIR = Path(__file__).parent / ".browser-profile"
DEFAULT_START_URL = "https://www.codechef.com/learn/course/c/CDEVINTRO/problems/CDEV004B"


def parse_args():
    parser = argparse.ArgumentParser(description="CodeChef Course Runner")
    parser.add_argument(
        "--start-url",
        default=None,
        help="Lesson URL to start from (prompts interactively if omitted)",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Dump buttons, editor kind, syllabus links; click nothing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print decision for current page; click nothing",
    )
    parser.add_argument(
        "--roadmap",
        action="store_true",
        help="After this course, continue with all roadmap courses",
    )
    return parser.parse_args()


def get_starting_url(cli_url: str | None) -> str:
    """Prompt the user for the CodeChef problem/course URL or use CLI/resume."""
    if cli_url:
        print(f"[main] Using start URL from CLI: {cli_url}")
        return cli_url

    resume_url = progress.get_last_active_url()
    default_url = resume_url if resume_url else DEFAULT_START_URL

    print("\n" + "=" * 62)
    print("           CodeChef Autonomous Course Solver")
    print("=" * 62)
    if resume_url:
        print(f"  [Resume available]: {resume_url}")
    else:
        print(f"  [Default]: {DEFAULT_START_URL}")
    print("=" * 62)

    prompt = (
        "\nEnter CodeChef problem/course URL to start with\n"
        f"(Press Enter to {'resume last problem' if resume_url else 'use default'}): "
    )
    try:
        user_input = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[main] Exiting.")
        sys.exit(0)

    if user_input:
        user_input = user_input.strip('"\'')
        if not user_input.startswith("http"):
            user_input = "https://" + user_input
        return user_input

    return default_url


def is_logged_in(page, context=None) -> bool:
    """Check if the user is authenticated on CodeChef."""
    current_url = page.url.lower()
    if "/login" in current_url or "/signup" in current_url or "/register" in current_url:
        return False

    try:
        dom_status = page.evaluate("""() => {
            // Check for explicit login/signup button or link
            const loginBtn = Array.from(document.querySelectorAll('a, button, [role="button"]')).some(el => {
                const href = (el.getAttribute('href') || '').toLowerCase();
                const text = (el.textContent || '').trim().toLowerCase();
                if (href.includes('/login') || href.includes('/signup')) {
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }
                if (text === 'log in' || text === 'login' || text === 'sign in') {
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }
                return false;
            });
            if (loginBtn) return false;

            // Check for profile or user handle link
            const userLink = document.querySelector('a[href^="/users/"], a[href*="codechef.com/users/"]');
            if (userLink) return true;

            // Check for logout link
            const logoutLink = document.querySelector('a[href*="/logout"], button[class*="logout"]');
            if (logoutLink) return true;

            // Check for user-menu or avatar element
            const userMenu = document.querySelector('[class*="user-menu"], [class*="profile-menu"], [class*="avatar-dropdown"], [id*="user-dropdown"]');
            if (userMenu) return true;

            return null;
        }""")
        if dom_status is True:
            return True
        if dom_status is False:
            return False
    except Exception:
        pass

    # Check cookies in context
    if context:
        try:
            cookies = context.cookies()
            auth_cookie_names = {'remember_user_token', 'cc_auth', 'session_id', 'access_token'}
            for c in cookies:
                if 'codechef.com' in c.get('domain', '') and c.get('name') in auth_cookie_names:
                    if len(c.get('value', '')) > 10:
                        return True
        except Exception:
            pass

    return False


def wait_for_login(page, context=None):
    """Wait for human user to complete login in the browser."""
    print("\n" + "=" * 60)
    print("  [ACTION REQUIRED] Please log into CodeChef in Chromium.")
    print("  The runner will automatically detect login and continue.")
    print("=" * 60 + "\n")

    dots = 0
    while True:
        time.sleep(2)
        try:
            if is_logged_in(page, context):
                print("\n[login] Logged in successfully!")
                return True
        except Exception:
            pass
        dots += 1
        if dots % 5 == 0:
            print("  Waiting for login in browser window...")


def setup_user_session(page, context, cli_start_url: str | None = None) -> str:
    """
    Implements the user workflow:
    1. Opens the browser window (login page if not logged in).
    2. Lets the user manually log in and navigate to their starting problem.
    3. User presses ENTER in console to fire up Zenith.
    """
    try:
        page.bring_to_front()
    except Exception:
        pass

    # If CLI explicitly passed a start URL, check login and navigate there directly
    if cli_start_url:
        print(f"[main] Navigating to starting URL: {cli_start_url}")
        try:
            page.goto(cli_start_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(2)
        except Exception:
            pass
        if not is_logged_in(page, context):
            print("\n[auth] Please log into CodeChef in the open browser...")
            while not is_logged_in(page, context):
                time.sleep(2)
            print("[auth] Login confirmed!")
            page.goto(cli_start_url, wait_until="domcontentloaded", timeout=60000)
        return cli_start_url

    # Check if user is already logged in
    logged_in = is_logged_in(page, context)
    curr_url = page.url.lower()

    if not logged_in:
        print("\n" + "=" * 65)
        print("                   Zenith - CodeChef Solver")
        print("=" * 65)
        print("  Opening CodeChef login in Chromium...")
        print("  1. [LOGIN]    Log into your CodeChef account in the browser.")
        print("  2. [NAVIGATE] Open the problem or course where you want to start.")
        print("  3. [FIRE UP]  Press [ENTER] here in the console to start solving!")
        print("=" * 65 + "\n")
        try:
            page.goto("https://www.codechef.com/login", wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
    else:
        print("\n" + "=" * 65)
        print("                   Zenith - CodeChef Solver")
        print("=" * 65)
        print("  [SESSION ACTIVE] Logged into CodeChef!")
        print("  1. [NAVIGATE] In Chromium, open the problem or course to start.")
        print("  2. [FIRE UP]  Press [ENTER] here in the console to start solving!")
        print("=" * 65 + "\n")
        if "codechef.com" not in curr_url or "/login" in curr_url:
            try:
                page.goto("https://www.codechef.com/practice", wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass

    # Wait for the user to press Enter to fire up
    while True:
        try:
            input(">> Press [ENTER] once you are on your starting problem to fire up Zenith: ")
        except (EOFError, KeyboardInterrupt):
            print("\n[main] Exiting.")
            sys.exit(0)

        chosen_url = page.url.split("?")[0]
        if "/login" in chosen_url or "/signup" in chosen_url:
            print("[main] You are still on the login page! Please log in and open a problem first.")
            continue
        if "codechef.com" not in chosen_url:
            print(f"[main] Browser is on {chosen_url}. Please navigate to CodeChef first.")
            continue

        print(f"\n[main] Firing up on starting problem: {page.url}\n")
        return page.url


def run_probe(page):
    """Probe mode: dump DOM info without clicking anything."""
    obs = observe.observe(page, "probe")
    kind = editor.detect_editor(page)
    syl = syllabus.get_syllabus(page)

    print("\n" + "=" * 60)
    print("  PROBE RESULTS")
    print("=" * 60)
    print(f"URL:           {obs['url']}")
    print(f"Title:         {obs['title']}")
    print(f"Buttons:       {obs['buttons']}")
    print(f"Tabs:          {obs['tabs']}")
    print(f"Editor kind:   {kind}")
    print(f"Has editor:    {obs['has_editor']}")
    print(f"Language:      {obs['language']}")
    print(f"Submit disabled: {obs['submit_disabled']}")
    print(f"Next disabled:   {obs['next_disabled']}")
    print(f"Has Solution tab: {obs['has_solution_tab']}")
    print(f"Has radio:     {obs['has_radio_buttons']}")
    print(f"Has login:     {obs['has_login_form']}")
    print(f"Has certificate: {obs['has_certificate']}")
    print(f"Screenshot:    {obs['screenshot']}")
    print(f"\nEditor text ({len(obs['editor_text'])} chars):")
    if obs['editor_text']:
        print(obs['editor_text'][:500])
    print(f"\nStatement ({len(obs['statement'])} chars):")
    if obs['statement']:
        print(obs['statement'][:500])
    print(f"\nOutput panel:")
    if obs['output_text']:
        print(obs['output_text'][:300])
    print(f"\nSyllabus ({len(syl)} URLs):")
    for i, url in enumerate(syl[:20]):
        print(f"  {i+1}. {url}")
    if len(syl) > 20:
        print(f"  ... and {len(syl) - 20} more")
    print("=" * 60)


def run_dry_run(page):
    """Dry-run mode: print what the runner would do without clicking."""
    obs = observe.observe(page, "dry_run")
    layout = classify.classify(obs)
    summary = classify.get_decision_summary(obs, layout)

    print("\n" + "=" * 60)
    print("  DRY RUN")
    print("=" * 60)
    print(summary)
    print("=" * 60)


# ═══════════════════════════════════════════════════════════════════
# Handler functions for each layout
# ═══════════════════════════════════════════════════════════════════

def handle_reading(page, obs):
    """Handle a reading page: click Next."""
    url = obs["url"]
    print(f"[reading] {obs['title'][:60]}")

    # If Next is disabled and there's a same-origin video, seek to end
    if obs["next_disabled"]:
        print("[reading] Next is disabled, checking for video...")
        if act.seek_video_to_end(page):
            print("[reading] Seeked video to end, rechecking Next...")
            time.sleep(2)
            # Re-observe
            obs = observe.read_dom(page)
            if obs.get("next_disabled", True):
                print("[reading] Next still disabled after video seek")
                return False

    if act.click_next(page):
        print("[reading] → Next clicked, page changed")
        progress.mark_lesson(url, "done")
        return True
    else:
        # Check if a badge / streak popup was blocking Next
        if act.dismiss_popups(page):
            print("[reading] Dismissed popup blocking reading page, retrying Next...")
            time.sleep(1)
            if act.click_next(page):
                print("[reading] → Next clicked after dismissing popup")
                progress.mark_lesson(url, "done")
                return True
        print("[reading] → Next failed")
        return False


def handle_guided(page, obs):
    """Handle a guided page: submit existing code, then Next."""
    url = obs["url"].split("?")[0]
    print(f"[guided] {obs['title'][:60]}")

    # Detect language from current editor code
    current_code = obs.get("editor_text", "")
    target_lang = editor.detect_code_language(current_code)
    print(f"[guided] Code language: {target_lang}")
    editor.set_language(page, target_lang)

    # Submit existing code
    submit_count = progress.increment_submits(url)
    if submit_count > MAX_SUBMITS_PER_LESSON:
        print(f"[guided] Max submits ({MAX_SUBMITS_PER_LESSON}) reached, blocking")
        progress.mark_lesson(url, "blocked", "max submits reached")
        return False

    if not act.click_submit(page):
        print("[guided] Submit click failed")
        return False

    print("[guided] Submitted, waiting for verdict...")
    verdict = act.wait_for_verdict(page, timeout=30000)
    print(f"[guided] Verdict: {verdict}")

    if verdict == "accepted":
        act.jitter_delay(1, 2)
        if act.click_next(page):
            progress.mark_lesson(url, "done")
            return True
        progress.mark_lesson(url, "done")
        return True

    # If compilation error and language was C, try C++
    if verdict == "compile_error" and target_lang == "C":
        print("[guided] Compilation error in C — switching to C++ and re-submitting...")
        editor.set_language(page, "C++")
        time.sleep(1)
        if act.click_submit(page):
            verdict = act.wait_for_verdict(page, timeout=30000)
            print(f"[guided] Re-submit verdict: {verdict}")
            if verdict == "accepted":
                act.jitter_delay(1, 2)
                act.click_next(page)
                progress.mark_lesson(url, "done")
                return True

    # Verdict not accepted → try AI repair once
    if submit_count < MAX_SUBMITS_PER_LESSON:
        print("[guided] Attempting AI repair with compiler/error feedback...")
        verdict_detail = act.get_verdict_detail(page)
        repaired = solve.repair_solution(
            obs.get("statement", ""), current_code, verdict_detail, "C++"
        )
        if repaired:
            if editor.write_code(page, repaired):
                editor.set_language(page, editor.detect_code_language(repaired))
                act.jitter_delay()
                progress.increment_submits(url)
                if act.click_submit(page):
                    verdict2 = act.wait_for_verdict(page, timeout=30000)
                    print(f"[guided] Repair verdict: {verdict2}")
                    if verdict2 == "accepted":
                        act.jitter_delay(1, 2)
                        act.click_next(page)
                        progress.mark_lesson(url, "done")
                        return True

    # All attempts failed — DO NOT skip or click Next
    print(f"[guided] Could not complete guided lesson at {url}. Halting so question is not skipped.")
    progress.mark_lesson(url, "blocked", f"verdict: {verdict}")
    return False


def handle_exercise(page, obs):
    """Handle an exercise page: write code, submit, then Next.
    
    Strategy:
    1. Solution tab code or pre-filled code → submit (auto-detects C++/Python)
    2. If wrong / CE: AI generates fresh solution (in C++) → submit
    3. If wrong / CE: AI repairs with error feedback → submit
    """
    url = obs["url"].split("?")[0]
    print(f"[exercise] {obs['title'][:60]}")
    statement = obs.get("statement", "")

    # Attempt 1: Solution tab or existing code
    code = solve.resolve_code(page, obs, "C++")
    if code:
        result = _submit_code(page, url, obs, code, "solution_tab")
        if result == "accepted":
            return True
    else:
        print("[exercise] No code from Solution tab")

    # Attempt 2: Ask AI to generate from scratch
    print("[exercise] Generating fresh solution with AI...")
    current_code = editor.read_editor(page) or ""
    ai_code = solve.generate_solution(statement, current_code, "C++")
    if ai_code:
        result = _submit_code(page, url, obs, ai_code, "ai_generate")
        if result == "accepted":
            return True

    # Attempt 3: Repair last submission with error details
    print("[exercise] Attempting AI repair with compiler/judge output...")
    verdict_detail = act.get_verdict_detail(page)
    submitted_code = editor.read_editor(page) or current_code
    repaired = solve.repair_solution(statement, submitted_code, verdict_detail, "C++")
    if repaired:
        result = _submit_code(page, url, obs, repaired, "ai_repair")
        if result == "accepted":
            return True

    # All attempts failed — DO NOT skip or click Next
    print(f"[exercise] All attempts failed for {url}. Halting so problem is NOT skipped.")
    progress.mark_lesson(url, "blocked", "all attempts failed")
    return False


def _submit_code(page, url, obs, code, source):
    """Write code, submit, wait for verdict. Returns 'accepted', 'compile_error', 'wrong_answer', or 'no_submit'."""
    # Detect code language and set editor dropdown
    target_lang = editor.detect_code_language(code)
    print(f"[exercise] Target code language: {target_lang}")
    editor.set_language(page, target_lang)

    # Write the code
    if not classify.is_code_written(editor.read_editor(page) or "", obs.get("statement", "")):
        if not editor.write_code(page, code):
            print(f"[exercise] Editor write failed ({source})")
            return "no_submit"
    elif source != "solution_tab":
        # Force-write for AI attempts
        if not editor.write_code(page, code):
            print(f"[exercise] Editor write failed ({source})")
            return "no_submit"

    # Re-verify language
    editor.set_language(page, target_lang)

    # Submit
    progress.increment_submits(url)
    if not act.click_submit(page):
        print(f"[exercise] Submit click failed ({source})")
        return "no_submit"

    print(f"[exercise] Submitted ({source}), waiting for verdict...")
    verdict = act.wait_for_verdict(page, timeout=45000)
    print(f"[exercise] Verdict: {verdict}")

    if verdict == "accepted":
        act.jitter_delay(0.5, 1.5)
        act.click_next(page)
        progress.mark_lesson(url, "done")
        return "accepted"

    # If compilation error and language was C, try auto-switching to C++!
    if verdict == "compile_error" and target_lang == "C":
        print("[exercise] Compilation error in C — auto-switching to C++ and re-submitting...")
        editor.set_language(page, "C++")
        time.sleep(1)
        if act.click_submit(page):
            verdict_cpp = act.wait_for_verdict(page, timeout=45000)
            print(f"[exercise] C++ re-submission verdict: {verdict_cpp}")
            if verdict_cpp == "accepted":
                act.jitter_delay(0.5, 1.5)
                act.click_next(page)
                progress.mark_lesson(url, "done")
                return "accepted"

    # Strictly do NOT advance or mark as done on failure or timeout!
    return verdict


def handle_quiz(page, obs):
    """Handle a quiz page: try options, verify verdict, never skip.
    
    Tries Gemini's pick first (if available), then brute-forces all options.
    Polls the DOM for confirmed 'correct' or 'wrong' feedback.
    NEVER clicks Next or marks as done unless confirmed CORRECT.
    """
    url = obs["url"].split("?")[0]
    print(f"[quiz] {obs['title'][:60]}")

    statement = obs.get("statement", "")
    quiz_data = act.get_quiz_data(page)
    num_options = len(quiz_data["options"]) if quiz_data["options"] else 0

    if num_options == 0:
        # Try counting radio buttons directly
        num_options = page.locator('input[type="radio"]').count()
        if num_options == 0:
            num_options = page.locator('[class*="option"], [class*="choice"]').count()

    if num_options == 0:
        print("[quiz] No options found, stopping to avoid skip")
        progress.mark_lesson(url, "blocked", "no quiz options found")
        return False

    print(f"[quiz] Found {num_options} options")
    option_texts = quiz_data.get("options", [])

    # Strategy 1: Ask Gemini to pick the right answer
    gemini_pick = solve.pick_quiz_answer(statement, option_texts)
    print(f"[quiz] Gemini initial pick: option {gemini_pick + 1}")

    # Build order: Gemini pick first, then the remaining options
    order = [gemini_pick] + [i for i in range(num_options) if i != gemini_pick]

    # Try up to 2 full passes (in case first pass missed verdict due to UI delay)
    max_passes = 2
    for pass_num in range(1, max_passes + 1):
        if pass_num > 1:
            print(f"[quiz] ── Starting pass {pass_num}/{max_passes} across options ──")

        for attempt_idx, idx in enumerate(order):
            print(f"[quiz] [Pass {pass_num}] Trying option {idx + 1}/{num_options}...")

            # Click the option
            if not act.click_quiz_option(page, idx):
                print(f"[quiz] Option {idx + 1} click failed, trying next")
                continue

            time.sleep(1.0)  # Ensure selection registers in DOM

            # Click Submit
            if not act.click_submit(page):
                print("[quiz] Submit click failed, retrying once...")
                time.sleep(1.0)
                if not act.click_submit(page):
                    print("[quiz] Submit click failed, moving to next option")
                    continue

            # Wait and poll for verdict (up to 8 seconds)
            print(f"[quiz] Waiting for quiz verdict...")
            verdict = wait_for_quiz_verdict(page, timeout=8.0)
            print(f"[quiz] Verdict for option {idx + 1}: {verdict}")

            if verdict == "correct":
                print(f"[quiz] ✓ Option {idx + 1} is CONFIRMED CORRECT! Problem solved.")
                act.jitter_delay(1.5, 2.5)
                # Click Next only now, after confirmed correct
                act.click_next(page)
                time.sleep(1.5)
                progress.mark_lesson(url, "done")
                return True
            elif verdict == "wrong":
                print(f"[quiz] ✗ Option {idx + 1} was WRONG. Continuing to next option...")
                time.sleep(1.0)
            else:
                print(f"[quiz] Verdict timed out for option {idx + 1}. Continuing to next option...")
                time.sleep(1.0)

    # If all passes failed, DO NOT SKIP!
    print(f"[quiz] ✗ All {num_options} options attempted across {max_passes} passes without confirmed correct answer.")
    print("[quiz] NOT clicking Next — stopping so question is not skipped.")
    progress.mark_lesson(url, "blocked", "all quiz options failed")
    return False


def wait_for_quiz_verdict(page, timeout: float = 8.0) -> str:
    """
    Poll the page for up to `timeout` seconds to determine quiz outcome.
    Returns 'correct', 'wrong', or 'timeout'.
    """
    start = time.time()
    while time.time() - start < timeout:
        v = _check_quiz_verdict(page)
        if v in ("correct", "wrong"):
            return v
        time.sleep(0.5)
    return "timeout"


def _check_quiz_verdict(page) -> str:
    """
    Examine DOM for explicit feedback banner and card styles.
    Returns 'correct', 'wrong', or 'pending'.
    """
    try:
        return page.evaluate(r"""() => {
            const bodyText = document.body ? document.body.innerText : '';

            // 1. Check for CodeChef's 'Find Error?' button (ONLY appears on wrong answer)
            const allButtons = Array.from(document.querySelectorAll('button, a, [role="button"]'));
            const hasFindError = allButtons.some(b => b.textContent && b.textContent.includes('Find Error'));
            if (hasFindError) {
                return 'wrong';
            }

            // 2. Check dedicated feedback / banner elements
            const feedbackEls = document.querySelectorAll(
                '[class*="banner"], [class*="alert"], [class*="result"], ' +
                '[class*="verdict"], [class*="feedback"], [class*="message"]'
            );
            for (const el of feedbackEls) {
                if (el.offsetParent === null) continue;
                const t = el.innerText.trim().toLowerCase();
                if (t.includes('wrong answer') || t.includes('incorrect') || t.includes('try again')) {
                    return 'wrong';
                }
                if (t.includes('correct answer') || t.includes('right answer') || t.includes('well done')) {
                    return 'correct';
                }
            }

            // 3. Check selected option card border and background color
            const selectedRadios = document.querySelectorAll('input[type="radio"]:checked');
            let cards = [];
            selectedRadios.forEach(r => {
                const c = r.closest('[class*="option"], [class*="choice"], label, div');
                if (c) cards.push(c);
            });
            if (cards.length === 0) {
                document.querySelectorAll('[class*="selected"], [class*="active"]').forEach(c => {
                    if (c.offsetParent !== null) cards.push(c);
                });
            }

            function parseRgb(color) {
                const m = (color || '').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
                return m ? [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])] : null;
            }

            for (const card of cards) {
                const style = window.getComputedStyle(card);
                const bg = parseRgb(style.backgroundColor);
                const border = parseRgb(style.borderColor);

                // Red indicator (wrong answer)
                const isRedBg = bg && bg[0] > 60 && bg[0] > bg[1] * 1.4 && bg[0] > bg[2] * 1.4;
                const isRedBorder = border && border[0] > 100 && border[0] > border[1] * 1.4 && border[0] > border[2] * 1.4;
                if (isRedBg || isRedBorder) return 'wrong';

                // Green indicator (correct answer)
                const isGreenBg = bg && bg[1] > 50 && bg[1] > bg[0] * 1.3;
                const isGreenBorder = border && border[1] > 80 && border[1] > border[0] * 1.3;
                if (isGreenBg || isGreenBorder) return 'correct';
            }

            // 4. Broad check for exact phrases in body text
            if (/wrong\s*answer/i.test(bodyText)) return 'wrong';
            if (/correct\s*answer/i.test(bodyText)) return 'correct';

            return 'pending';
        }""") or "pending"
    except Exception as e:
        print(f"[quiz] _check_quiz_verdict error: {e}")
        return "pending"


def handle_roadmap(page, obs, continue_roadmap: bool = False):
    """
    Handle the roadmap page: collect course URLs.
    Returns the list of course URLs.
    """
    print("[roadmap] On roadmap page")

    # Click Start Roadmap Now if needed
    if "Start Roadmap Now" in " ".join(obs["buttons"]):
        act.click_start_roadmap(page)
        time.sleep(2)

    # Collect course URLs
    courses = syllabus.get_course_urls_from_roadmap(page)
    print(f"[roadmap] Found {len(courses)} courses")
    for i, url in enumerate(courses):
        print(f"  {i+1}. {url}")

    return courses


def handle_outline(page, obs, lesson_urls):
    """Handle an outline/module page: open first unfinished lesson."""
    print("[outline] On module outline page")

    # Get lesson URLs from this page
    page_urls = syllabus.get_lesson_urls_from_page(page)
    if page_urls:
        lesson_urls.extend(page_urls)

    # Find first unfinished
    for url in page_urls:
        if not progress.is_done(url) and not progress.is_blocked(url):
            print(f"[outline] Opening: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            return True

    print("[outline] All lessons done or blocked")
    return False


def handle_auth(page):
    """Handle auth wall: wait for human login."""
    print("[auth] Login/verify wall detected – waiting for human...")
    wait_for_login(page, page.context)
    time.sleep(2)
    return True


def handle_running(page, obs):
    """Handle running/evaluating state: wait for verdict."""
    print("[running] Submission still evaluating...")
    verdict = act.wait_for_verdict(page, timeout=60000)
    print(f"[running] Verdict: {verdict}")
    return verdict


def handle_done(page, obs, continue_roadmap: bool = False):
    """Handle course-done screen."""
    url = obs["url"]
    course_id = syllabus.extract_course_id(url)
    print(f"[done] Course {course_id} completed!")
    if course_id:
        progress.mark_course_done(course_id)
    return not continue_roadmap  # True = stop, unless roadmap mode


def handle_unknown(page, obs):
    """Handle unknown layout: try to advance before blocking."""
    url = obs["url"].split("?")[0]
    screenshot = obs.get("screenshot", "")

    print(f"[unknown] Unrecognized layout at {url}")

    # Safety safeguard 1: If there's an editor or submit button, treat as exercise/guided
    if obs.get("has_editor", False) or obs.get("has_submit", False):
        print("[unknown] Has editor or submit button — treating as exercise")
        return "exercise"

    # Safety safeguard 2: If there are radio buttons, treat as quiz
    if obs.get("has_radio_buttons", False):
        print("[unknown] Has radio buttons — treating as quiz")
        return "quiz"

    # Strategy 1: Try clicking Next or Keep Learning ONLY if no editor/quiz
    if act.click_next(page):
        time.sleep(1.5)
        new_url = page.url.split("?")[0]
        if new_url != url:
            print("[unknown] Clicked Next and page changed — success!")
            progress.mark_lesson(url, "done", "advanced from unknown layout")
            return "done"

    # Strategy 2: Vision classification
    if screenshot and os.path.exists(screenshot):
        dom_summary = classify.get_decision_summary(obs, "unknown")
        result = solve.classify_with_vision(screenshot, dom_summary)
        print(f"[unknown] Vision says: {result}")
        if result["layout"] != "unknown":
            return result["layout"]

    # Strategy 4: Try clicking any prominent button on the page
    try:
        buttons = page.locator('button:visible, a.btn:visible, [role="button"]:visible')
        for i in range(min(buttons.count(), 5)):
            btn = buttons.nth(i)
            text = (btn.text_content() or "").strip().lower()
            # Skip denied/dangerous buttons
            if any(w in text for w in ["certificate", "download", "delete", "logout", "sign out"]):
                continue
            if text and len(text) < 30:
                print(f"[unknown] Trying button: '{text}'")
                btn.click()
                time.sleep(1.5)
                new_url = page.url.split("?")[0]
                if new_url != url:
                    print(f"[unknown] Button '{text}' advanced the page!")
                    progress.mark_lesson(url, "done", f"clicked '{text}'")
                    return "done"
    except Exception:
        pass

    progress.mark_lesson(url, "blocked", "unknown layout")
    return None


# ═══════════════════════════════════════════════════════════════════
# Main runner loop
# ═══════════════════════════════════════════════════════════════════

def run_lesson_loop(page, lesson_urls: list[str], continue_roadmap: bool = False):
    """
    Main loop: process one lesson at a time.
    observe → classify → act → confirm → record
    """
    consecutive_unknown = 0
    first_lesson = True

    while True:
        # Automatically dismiss any overlay badge/celebration/streak popups
        act.dismiss_popups(page)

        url = page.url.split("?")[0]  # Strip query params like ?tab=statement
        print(f"\n{'─' * 60}")
        print(f"[loop] Current URL: {url}")

        # If user explicitly navigated to a previously blocked lesson to retry it, reset it
        if first_lesson:
            first_lesson = False
            if progress.is_blocked(url):
                print(f"[loop] Starting URL was previously marked blocked ({url}); resetting to retry.")
                progress.mark_lesson(url, "running")

        # Check stuck guards
        action_count = progress.get_action_count(url)
        if action_count >= MAX_ACTIONS_PER_LESSON:
            print(f"[loop] Max actions ({MAX_ACTIONS_PER_LESSON}) on {url}, skipping")
            progress.mark_lesson(url, "blocked", "max actions reached")
            if not _advance_to_next(page, url, lesson_urls):
                print("[loop] No more lessons to advance to")
                break
            continue

        progress.increment_actions(url)

        # Skip already done/blocked
        if progress.is_done(url):
            print(f"[loop] Already done: {url}")
            if not _advance_to_next(page, url, lesson_urls):
                break
            continue

        if progress.is_blocked(url):
            print(f"[loop] Already blocked: {url}")
            if not _advance_to_next(page, url, lesson_urls):
                break
            continue

        # Wait briefly for page to fully load before observing
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        time.sleep(1)

        # Observe
        obs = observe.observe(page, "step")

        # Classify
        layout = classify.classify(obs)
        print(f"[loop] Layout: {layout}")

        # Act based on layout
        if layout == "reading":
            if handle_reading(page, obs):
                consecutive_unknown = 0
            else:
                if not _advance_to_next(page, url, lesson_urls):
                    break

        elif layout == "guided":
            if handle_guided(page, obs):
                consecutive_unknown = 0
            else:
                print(f"[loop] Guided lesson at {url} was not completed. Stopping so question is not skipped.")
                break

        elif layout == "exercise":
            if handle_exercise(page, obs):
                consecutive_unknown = 0
            else:
                print(f"[loop] Exercise at {url} was not solved. Stopping so question is not skipped.")
                break

        elif layout == "quiz":
            if handle_quiz(page, obs):
                consecutive_unknown = 0
            else:
                print(f"[loop] Quiz at {url} was not completed. Stopping so question is not skipped.")
                break

        elif layout == "roadmap":
            courses = handle_roadmap(page, obs, continue_roadmap)
            if courses:
                # Navigate to first course
                page.goto(courses[0], wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
            consecutive_unknown = 0

        elif layout == "outline":
            if not handle_outline(page, obs, lesson_urls):
                # All lessons done in this outline
                if not _advance_to_next(page, url, lesson_urls):
                    break
            consecutive_unknown = 0

        elif layout == "auth":
            handle_auth(page)
            consecutive_unknown = 0

        elif layout == "running":
            verdict = handle_running(page, obs)
            # After running finishes, the loop will re-observe
            consecutive_unknown = 0

        elif layout == "done":
            should_stop = handle_done(page, obs, continue_roadmap)
            if should_stop:
                print("[loop] Course complete, stopping.")
                break
            else:
                # Roadmap mode: go back to roadmap
                print("[loop] Course done, returning to roadmap...")
                # Navigate back or to next course
                if not _advance_to_next(page, url, lesson_urls):
                    break
            consecutive_unknown = 0

        elif layout == "module_done":
            print("[module_done] Module completion screen — clicking Keep Learning")
            if act.click_next(page):
                print("[module_done] Proceeding to next module")
                progress.mark_lesson(url, "done")
            else:
                print("[module_done] Could not click Keep Learning, advancing")
                if not _advance_to_next(page, url, lesson_urls):
                    break
            consecutive_unknown = 0

        elif layout == "unknown":
            result = handle_unknown(page, obs)
            if result and result != "unknown":
                # Re-dispatch with the detected layout
                consecutive_unknown = 0
                continue  # Will re-observe and re-classify
            else:
                consecutive_unknown += 1
                if consecutive_unknown >= 3:
                    print("[loop] Too many consecutive unknowns, advancing")
                    if not _advance_to_next(page, url, lesson_urls):
                        break
                    consecutive_unknown = 0

        # Small pause between iterations
        time.sleep(1)


def _advance_to_next(page, current_url: str, lesson_urls: list[str]) -> bool:
    """
    Try to advance to the next lesson in the syllabus.
    Returns True if navigation happened.
    """
    # First try the syllabus order
    next_url = syllabus.get_next_lesson_url(page, current_url, lesson_urls)
    if next_url:
        # Skip if already done or blocked
        while next_url and (progress.is_done(next_url) or progress.is_blocked(next_url)):
            next_url = syllabus.get_next_lesson_url(page, next_url, lesson_urls)

        if next_url:
            print(f"[advance] → {next_url}")
            page.goto(next_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            return True

    # Try clicking Next button directly
    old_url = page.url
    if act.click_next(page):
        if page.url != old_url:
            return True

    # Try re-opening the syllabus to find more lessons
    new_urls = syllabus.get_syllabus(page)
    if new_urls:
        lesson_urls.clear()
        lesson_urls.extend(new_urls)
        for url in new_urls:
            if not progress.is_done(url) and not progress.is_blocked(url):
                print(f"[advance] Syllabus refresh → {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                return True

    # Try clicking Next Course button if end of course is reached
    try:
        next_course = page.locator('button:has-text("Next Course"), a:has-text("Next Course"), button:has-text("Start Next Course"), a:has-text("Start Next Course")')
        if next_course.count() > 0 and next_course.first.is_visible(timeout=1000):
            print("[advance] End of course reached, clicking Next Course...")
            next_course.first.click()
            time.sleep(3)
            return True
    except Exception:
        pass

    return False


# ═══════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════

def main():
    args = parse_args()

    # Fix Windows console encoding for Unicode
    import io
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        # Launch Playwright Chromium — visible, on top, positioned at screen top-left
        # slow_mo=100 so every action is visible to the user
        browser_context = pw.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=False,
            slow_mo=100,
            viewport={"width": 1300, "height": 800},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-position=50,50",
                "--window-size=1300,800",
            ],
        )
        page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()

        # Close any extra blank tabs Chrome opened, keep only the CodeChef one
        for p in browser_context.pages:
            if p != page:
                try:
                    p.close()
                except Exception:
                    pass

        # Bring our page to front so the user can see it
        try:
            page.bring_to_front()
        except Exception:
            pass

        # Open browser, verify/wait for login, user navigates to problem, then fires up
        args.start_url = setup_user_session(page, browser_context, args.start_url)

        print("+----------------------------------------------------------+")
        print("|                          Zenith                          |")
        print("+----------------------------------------------------------+")
        print(f"  Start URL: {args.start_url}")
        print(f"  Mode:      {'probe' if args.probe else 'dry-run' if args.dry_run else 'roadmap' if args.roadmap else 'single course'}")
        print()

        # ── Probe mode ───────────────────────────────────────────
        if args.probe:
            run_probe(page)
            input("\nPress Enter to close the browser...")
            browser_context.close()
            return

        # ── Dry-run mode ─────────────────────────────────────────
        if args.dry_run:
            run_dry_run(page)
            input("\nPress Enter to close the browser...")
            browser_context.close()
            return

        # ── Full run ─────────────────────────────────────────────
        # Collect initial syllabus
        print("[main] Collecting syllabus...")
        lesson_urls = syllabus.get_syllabus(page)
        if lesson_urls:
            print(f"[main] Found {len(lesson_urls)} lesson URLs")
        else:
            print("[main] No syllabus found, will navigate via Next buttons")

        # Start the lesson loop
        try:
            run_lesson_loop(page, lesson_urls, continue_roadmap=args.roadmap)
        except KeyboardInterrupt:
            print("\n[main] Interrupted by user")
        except Exception as e:
            print(f"\n[main] Error: {e}")
            import traceback
            traceback.print_exc()
            # Save state
            observe.take_screenshot(page, "crash")

        print("\n[main] Run complete.")
        print(f"  Progress file: {progress.PROGRESS_FILE}")
        print(f"  Screenshots:   {observe.get_run_dir()}")

        # Summary
        all_lessons = progress.get_all_lessons()
        done = sum(1 for v in all_lessons.values() if v.get("status") == "done")
        blocked = sum(1 for v in all_lessons.values() if v.get("status") == "blocked")
        print(f"  Lessons done:    {done}")
        print(f"  Lessons blocked: {blocked}")
        print(f"  Total tracked:   {len(all_lessons)}")

        input("\nPress Enter to close the browser...")
        browser_context.close()


if __name__ == "__main__":
    main()
