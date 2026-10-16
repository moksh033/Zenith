"""
syllabus.py – Ordered lesson URL extraction.

Gets the ordered list of lesson URLs from:
1. The module drawer (hamburger menu on learn pages).
2. JSON responses the page loads (lesson-list API).
3. Roadmap page course links.
"""

import re
import time
import json
from urllib.parse import urljoin
from playwright.sync_api import Page


def get_lesson_urls_from_drawer(page: Page) -> list[str]:
    """
    Open the hamburger / module drawer and extract all lesson URLs in order.
    """
    urls = []
    try:
        # Try to open the drawer / sidebar
        hamburger_selectors = [
            'button[aria-label*="menu"]',
            'button[aria-label*="Menu"]',
            'button[aria-label*="syllabus"]',
            'button[aria-label*="list"]',
            'button[aria-label*="List"]',
            '[class*="hamburger"]',
            '[class*="sidebar-toggle"]',
            '[class*="list-icon"]',
            '.menu-icon',
            'svg[class*="menu"]',
            'svg[class*="list"]',
        ]

        # The CodeChef learn page has a list icon (≡) at the top
        # Try the second icon in the toolbar (list/drawer)
        drawer_opened = False
        for sel in hamburger_selectors:
            try:
                btn = page.locator(sel)
                if btn.count() > 0 and btn.first.is_visible(timeout=1000):
                    btn.first.click()
                    time.sleep(1)
                    drawer_opened = True
                    break
            except Exception:
                continue

        if not drawer_opened:
            # Try clicking the list icon by its position (second icon in toolbar)
            try:
                # CodeChef uses a sidebar list icon
                icons = page.locator('header button, nav button, [class*="toolbar"] button')
                for i in range(icons.count()):
                    icon = icons.nth(i)
                    if icon.is_visible():
                        # Check if this looks like a menu icon
                        aria = icon.get_attribute("aria-label") or ""
                        if any(w in aria.lower() for w in ["menu", "list", "syllabus", "module"]):
                            icon.click()
                            time.sleep(1)
                            drawer_opened = True
                            break
            except Exception:
                pass

        if not drawer_opened:
            return []

        # Extract lesson links from the drawer
        urls = page.evaluate("""() => {
            const result = [];
            const seen = new Set();
            // Look for links in sidebar/drawer/modal that point to lessons
            const containers = document.querySelectorAll(
                '[class*="sidebar"], [class*="drawer"], [class*="modal"], ' +
                '[class*="syllabus"], [class*="module-list"], [role="dialog"], ' +
                '[class*="panel"], [class*="menu"]'
            );
            function extractFromContainer(container) {
                const links = container.querySelectorAll('a[href*="/problems/"], a[href*="/learn/"]');
                for (const a of links) {
                    const href = a.href;
                    if (href && !seen.has(href) && href.includes('/problems/')) {
                        seen.add(href);
                        result.push(href);
                    }
                }
            }
            for (const c of containers) extractFromContainer(c);
            // Also try all visible links if drawer didn't have specific containers
            if (result.length === 0) {
                const allLinks = document.querySelectorAll('a[href*="/problems/"]');
                for (const a of allLinks) {
                    const href = a.href;
                    if (href && !seen.has(href)) {
                        seen.add(href);
                        result.push(href);
                    }
                }
            }
            return result;
        }""")

        # Close the drawer — must be aggressive, it blocks all clicks
        _close_drawer(page)

    except Exception as e:
        print(f"[syllabus] Drawer extraction failed: {e}")

    return urls


def _close_drawer(page: Page) -> None:
    """Aggressively close the sidebar drawer so it doesn't block clicks."""
    # 1. Press Escape
    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except Exception:
        pass

    # 2. Force-hide the sidebar overlay via JS (CodeChef uses _sidebarContainer)
    try:
        page.evaluate("""() => {
            // Hide sidebar container
            const sidebar = document.querySelector('[class*="sidebarContainer"], [class*="sidebar_"]');
            if (sidebar) sidebar.style.display = 'none';
            // Hide any overlay/backdrop
            const overlays = document.querySelectorAll('[class*="overlay"], [class*="backdrop"], [class*="modal-backdrop"]');
            for (const o of overlays) o.style.display = 'none';
            // Click the body to dismiss
            document.body.click();
        }""")
        time.sleep(0.5)
    except Exception:
        pass

    # 3. Verify it's gone
    try:
        still_open = page.evaluate("""() => {
            const sidebar = document.querySelector('[class*="sidebarContainer"][class*="open"]');
            return !!sidebar;
        }""")
        if still_open:
            print("[syllabus] Sidebar still open, clicking hamburger to toggle it off")
            # Re-click the hamburger to toggle
            hamburger = page.locator('button[aria-label*="menu"], button[aria-label*="Menu"], [class*="hamburger"]')
            if hamburger.count() > 0:
                hamburger.first.click()
                time.sleep(0.5)
    except Exception:
        pass


def get_lesson_urls_from_api(page: Page) -> list[str]:
    """
    Intercept or check for lesson-list JSON responses the page loads.
    Falls back to examining inline script data.
    """
    urls = []
    try:
        # Check for inline JSON data containing lesson info
        data = page.evaluate("""() => {
            // Check window/global variables for lesson data
            const candidates = [
                window.__NEXT_DATA__,
                window.__NUXT__,
                window.__APP_DATA__,
                window.pageData,
                window.courseData,
            ];
            for (const d of candidates) {
                if (d) return JSON.stringify(d).substring(0, 50000);
            }
            // Check script tags with JSON content
            const scripts = document.querySelectorAll('script[type="application/json"], script[id*="data"]');
            for (const s of scripts) {
                const text = s.textContent || '';
                if (text.includes('problems') || text.includes('lessons')) {
                    return text.substring(0, 50000);
                }
            }
            return '';
        }""")

        if data:
            # Parse and extract problem URLs
            urls = _extract_urls_from_json(data)

    except Exception as e:
        print(f"[syllabus] API data extraction failed: {e}")

    return urls


def _extract_urls_from_json(json_str: str) -> list[str]:
    """Extract lesson/problem URLs from a JSON string."""
    urls = []
    try:
        # Find all problem code patterns
        codes = re.findall(r'"(CDEV\w+)"', json_str)
        # Also try other course prefixes
        codes += re.findall(r'"([A-Z]{2,10}\d{3,}[A-Z]?)"', json_str)
        seen = set()
        for code in codes:
            if code not in seen:
                seen.add(code)
                # We don't know the exact URL pattern yet, store just the codes
                urls.append(code)
    except Exception:
        pass
    return urls


def get_lesson_urls_from_page(page: Page) -> list[str]:
    """
    Extract lesson URLs directly from visible links on the page.
    Used for outline/module pages.
    """
    try:
        urls = page.evaluate("""() => {
            const result = [];
            const seen = new Set();
            const links = document.querySelectorAll('a[href*="/problems/"]');
            for (const a of links) {
                const href = a.href;
                if (href && !seen.has(href)) {
                    seen.add(href);
                    result.push(href);
                }
            }
            return result;
        }""")
        return urls
    except Exception:
        return []


def get_course_urls_from_roadmap(page: Page) -> list[str]:
    """
    Extract course URLs from the roadmap page.
    Returns ordered list of course start URLs.
    """
    try:
        urls = page.evaluate("""() => {
            const result = [];
            const seen = new Set();
            const links = document.querySelectorAll('a[href*="/learn/course/"]');
            for (const a of links) {
                const href = a.href;
                if (href && !seen.has(href)) {
                    // Skip certificate links
                    const text = (a.textContent || '').toLowerCase();
                    if (text.includes('certificate') || text.includes('download')) continue;
                    seen.add(href);
                    result.push(href);
                }
            }
            return result;
        }""")
        return urls
    except Exception:
        return []


def get_syllabus(page: Page) -> list[str]:
    """
    Best-effort ordered lesson list.
    Tries drawer first, then API data, then page links.
    """
    # Try drawer
    urls = get_lesson_urls_from_drawer(page)
    if urls:
        print(f"[syllabus] Got {len(urls)} lessons from drawer")
        return urls

    # Try API data
    urls = get_lesson_urls_from_api(page)
    if urls:
        print(f"[syllabus] Got {len(urls)} lesson codes from API data")
        return urls

    # Try page links
    urls = get_lesson_urls_from_page(page)
    if urls:
        print(f"[syllabus] Got {len(urls)} lessons from page links")
        return urls

    print("[syllabus] No lesson URLs found")
    return []


def get_next_lesson_url(page: Page, current_url: str, syllabus: list[str]) -> str | None:
    """
    Return the next lesson URL after current_url in the syllabus.
    Returns None if current_url is the last lesson or not found.
    """
    if not syllabus:
        return None

    # Try exact match first
    for i, url in enumerate(syllabus):
        if url == current_url or current_url.endswith(url):
            if i + 1 < len(syllabus):
                return syllabus[i + 1]
            return None  # Last lesson

    # Try partial match (problem code)
    current_code = _extract_problem_code(current_url)
    if current_code:
        for i, url in enumerate(syllabus):
            code = _extract_problem_code(url) or url
            if code == current_code:
                if i + 1 < len(syllabus):
                    return syllabus[i + 1]
                return None

    return None


def _extract_problem_code(url: str) -> str:
    """Extract the problem code from a CodeChef URL."""
    match = re.search(r'/problems/([A-Z0-9]+)', url)
    if match:
        return match.group(1)
    return ""


def extract_course_id(url: str) -> str:
    """Extract the course ID from a CodeChef learn URL."""
    match = re.search(r'/course/\w+/(\w+)', url)
    if match:
        return match.group(1)
    return ""
