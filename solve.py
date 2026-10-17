"""
solve.py – Solution generation for exercise pages.

Solver chain for an exercise, in order:
1. Editor already holds a finished program → submit that text.
2. Solution tab contains a fenced or full program → copy that text.
3. Otherwise call Gemini with the statement + current buffer + language.

Provider: Google Gemini (GEMINI_API_KEY, OpenAI-compatible endpoint).
Model: gemini-2.5-flash (fast, free-tier friendly).

Verdict repair: if wrong answer / compile error / runtime error, call the
model once more with the statement, submitted program, and panel text.
"""

from __future__ import annotations

import os
import re
import time
from playwright.sync_api import Page

from classify import is_code_written

# LLM models & endpoints
OPENROUTER_MODEL = "deepseek/deepseek-chat"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

_client = None
_model_name = OPENROUTER_MODEL


def _get_client():
    """Lazy-init the OpenAI client (prefers OpenRouter > Groq > Gemini)."""
    global _client, _model_name
    if _client is not None:
        return _client

    from dotenv import load_dotenv
    load_dotenv()
    from openai import OpenAI

    # 1. Prefer OpenRouter (verified active)
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip('"\' \t\r\n')
    if openrouter_key:
        _client = OpenAI(api_key=openrouter_key, base_url=OPENROUTER_BASE_URL)
        _model_name = OPENROUTER_MODEL
        print(f"[solve] AI initialized: OpenRouter ({_model_name})")
        return _client

    # 2. Groq fallback (fast inference)
    groq_key = os.environ.get("GROQ_API_KEY", "").strip('"\' \t\r\n')
    if groq_key:
        _client = OpenAI(api_key=groq_key, base_url=GROQ_BASE_URL)
        _model_name = GROQ_MODEL
        print(f"[solve] AI initialized: Groq ({_model_name})")
        return _client

    # 3. Fall back to Gemini
    api_key = os.environ.get("GEMINI_API_KEY", "").strip('"\' \t\r\n')
    if api_key:
        _client = OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)
        _model_name = GEMINI_MODEL
        print(f"[solve] AI initialized: Gemini ({_model_name})")
        return _client

    print("[solve] No AI key set – AI solver disabled")
    return None


def _get_model() -> str:
    global _model_name
    if _client is None:
        _get_client()
    return _model_name



def get_solution_from_tab(page: Page) -> str:
    """
    Click the Solution tab, extract the code, and return it.
    The tab can unmount the editor, so copy happens before writing.
    Returns empty string if no solution found.
    """
    try:
        # Find and click the Solution tab
        solution_tab = page.locator("text='Solution'").first
        if not solution_tab.is_visible(timeout=2000):
            return ""

        solution_tab.click()
        time.sleep(1.5)  # Wait for content to load

        # Extract code from the solution tab content
        code = page.evaluate("""() => {
            // Look for code blocks in the solution panel
            const codeBlocks = document.querySelectorAll('pre code, code, .solution-code, [class*="solution"] pre, [class*="Solution"] pre');
            let bestCode = '';
            for (const block of codeBlocks) {
                const text = (block.textContent || '').trim();
                // Prefer blocks that look like complete programs
                if (text.includes('#include') || text.includes('int main') ||
                    text.includes('def ') || text.includes('import ') ||
                    text.includes('class ') || text.includes('public static void main')) {
                    if (text.length > bestCode.length) bestCode = text;
                }
            }
            if (bestCode) return bestCode;

            // Fallback: look for any preformatted content in the solution area
            const solutionArea = document.querySelector('[class*="solution"], [class*="Solution"]');
            if (solutionArea) {
                const pre = solutionArea.querySelector('pre');
                if (pre) return (pre.textContent || '').trim();
                const text = (solutionArea.textContent || '').trim();
                return text;
            }
            return '';
        }""")

        # Switch back to Statement tab
        try:
            stmt_tab = page.locator("text='Statement'").first
            if stmt_tab.is_visible(timeout=2000):
                stmt_tab.click()
                time.sleep(1)
        except Exception:
            pass

        if code and len(code.strip()) > 10:
            return code.strip()

        return ""

    except Exception as e:
        print(f"[solve] Solution tab read failed: {e}")
        # Try to get back to Statement tab
        try:
            page.locator("text='Statement'").first.click()
            time.sleep(0.5)
        except Exception:
            pass
        return ""


def is_cpp_code(code: str) -> bool:
    """Check if code contains C++ specific headers, syntax, or standard libraries."""
    cpp_markers = [
        "<iostream>", "<vector>", "<string>", "<algorithm>", "<map>", "<set>",
        "<bits/stdc++.h>", "using namespace std", "std::", "cout", "cin",
        "endl", "template<", "class ", "nullptr", "public:", "private:"
    ]
    return any(marker in code for marker in cpp_markers)


def convert_to_c(cpp_code: str, statement: str = "") -> str:
    """Convert C++ code into clean, standard C (C99/C11) code."""
    client = _get_client()
    if client is None:
        return cpp_code

    prompt = f"""Convert this C++ program into valid, clean, pure standard C (C99/C11) code.

PROBLEM STATEMENT:
{statement[:2000]}

C++ CODE:
{cpp_code[:2000]}

INSTRUCTIONS:
- Write ONLY pure standard C code.
- Use #include <stdio.h>, #include <stdlib.h>, #include <string.h>, #include <math.h>, etc.
- Replace all cin/cout with scanf/printf.
- Replace vector/string with standard C arrays, char arrays, or malloc pointers.
- Ensure the code compiles cleanly with gcc (sol.c) with zero warnings/errors.
- Return ONLY the complete C code. No markdown fences, no explanations.
"""

    try:
        model = _get_model()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are an expert C programmer. Convert C++ code to pure, bug-free C (C99). Return only C code."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        c_code = response.choices[0].message.content.strip()
        c_code = _strip_fences(c_code)
        if c_code and len(c_code) > 10:
            return c_code
        return cpp_code
    except Exception as e:
        print(f"[solve] C++ to C conversion failed: {e}")
        return cpp_code


def generate_solution(statement: str, current_code: str, language: str = "C") -> str:
    """
    Call AI to generate a complete program in pure C.
    Returns the full program text, or empty string on failure.
    """
    client = _get_client()
    if client is None:
        return ""

    prompt = f"""You are solving a CodeChef competitive programming problem. Write a complete, working {language} program.

PROBLEM STATEMENT:
{statement[:3000]}

CURRENT EDITOR CODE (may be a skeleton):
{current_code[:1500]}

INSTRUCTIONS:
- Return ONLY the complete {language} program, nothing else.
- Must be pure {language} (standard C99/C11): use #include <stdio.h>, #include <stdlib.h>, #include <string.h>, etc.
- DO NOT use any C++ headers or syntax (NO <iostream>, NO cin/cout, NO namespace std, NO class, NO new/delete).
- Use standard C input/output: scanf, printf, getchar, fgets.
- Ensure the program compiles cleanly with gcc (sol.c) without warnings or errors.
- Match exact requested output formatting and casing.
- No explanations, no markdown fences.
"""

    try:
        model = _get_model()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"You are a competitive programmer writing pure {language} code. Return only valid, bug-free {language} code. No markdown, no explanations."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2000,
        )
        code = response.choices[0].message.content.strip()
        code = _strip_fences(code)
        if language == "C" and is_cpp_code(code):
            print("[solve] Generated code contained C++ markers — converting to pure C...")
            code = convert_to_c(code, statement)
        return code

    except Exception as e:
        print(f"[solve] AI generation call failed: {e}")
        return ""


def repair_solution(statement: str, submitted_code: str, verdict_text: str,
                    language: str = "C") -> str:
    """
    Call AI with the statement, submitted program, and verdict panel text.
    Returns the repaired program in pure C, or empty string on failure.
    """
    client = _get_client()
    if client is None:
        return ""

    prompt = f"""You submitted a {language} program to the CodeChef judge (gcc sol.c) and it was REJECTED.

PROBLEM STATEMENT:
{statement[:3000]}

SUBMITTED CODE:
{submitted_code[:2000]}

JUDGE VERDICT / COMPILER / ERROR OUTPUT:
{verdict_text[:2000]}

Carefully analyze the compiler error or failed test case above.
Fix the code so it compiles cleanly with gcc without warnings/errors and passes all test cases.
Must be pure {language} code (use stdio.h, printf, scanf. No C++ headers or features).
Return ONLY the corrected {language} code. No explanations, no markdown fences.
"""

    try:
        model = _get_model()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"You are a competitive programmer fixing a rejected {language} solution. Return only valid, working {language} code."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2000,
        )
        code = response.choices[0].message.content.strip()
        code = _strip_fences(code)
        if language == "C" and is_cpp_code(code):
            print("[solve] Repaired code contained C++ markers — converting to pure C...")
            code = convert_to_c(code, statement)
        return code

    except Exception as e:
        print(f"[solve] AI repair call failed: {e}")
        return ""


def pick_quiz_answer(question: str, options: list[str]) -> int:
    """
    Call Gemini to pick the correct quiz option.
    
    On CodeChef, the 'question' is actually the full statement text which
    includes both the question and the code snippets for each option 
    (labeled Option 1:, Option 2:, etc.). The 'options' list from the 
    radio buttons may just say "Option 1", "Option 2", etc.
    
    Returns the 0-based index of the best option, or 0 on failure.
    """
    client = _get_client()
    if client is None:
        return 0  # Default to first option

    # If options just say "Option 1", "Option 2" etc., the real content
    # is in the question/statement text
    options_are_labels = all(
        re.match(r'^option\s*\d+$', opt.strip(), re.IGNORECASE)
        for opt in options if opt.strip()
    )

    if options_are_labels or not options:
        # The statement contains everything — send it all to Gemini
        num_opts = len(options) if options else 4
        prompt = f"""This is a multiple choice question from a C programming course.
The full question and all options are shown below:

{question[:3000]}

There are {num_opts} options labeled Option 1 through Option {num_opts}.
Reply with ONLY the number (1-{num_opts}) of the correct answer. Nothing else.
"""
    else:
        options_text = "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(options))
        num_opts = len(options)
        prompt = f"""Multiple choice question from a C programming course:

QUESTION:
{question[:2000]}

OPTIONS:
{options_text}

Reply with ONLY the number (1-{num_opts}) of the correct answer. Nothing else.
"""

    try:
        model = _get_model()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are answering a programming quiz. Reply with only the option number (e.g. '2'). No explanations."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=10,
        )
        answer = response.choices[0].message.content.strip()
        print(f"[solve] AI quiz answer: {answer}")
        # Parse the number
        match = re.search(r'\d+', answer)
        if match:
            idx = int(match.group()) - 1
            if 0 <= idx < num_opts:
                return idx
        return 0

    except Exception as e:
        print(f"[solve] AI quiz call failed: {e}")
        return 0


def classify_with_vision(screenshot_path: str, dom_summary: str) -> dict:
    """
    Vision fallback: send screenshot + DOM summary to the model.
    Returns {"layout": str, "code_written": bool}.
    """
    client = _get_client()
    if client is None:
        return {"layout": "unknown", "code_written": False}

    import base64
    try:
        with open(screenshot_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return {"layout": "unknown", "code_written": False}

    prompt = f"""Look at this CodeChef page screenshot and the DOM summary below.

DOM SUMMARY:
{dom_summary[:2000]}

Which layout is this page? Choose exactly one:
- roadmap (course listing / roadmap page)
- reading (reading lesson, no editor, has Next button)
- guided (has editor with pre-filled working code, just needs Submit)
- exercise (has editor with empty/placeholder code, needs code to be written)
- quiz (multiple choice question)
- auth (login / verify wall)
- done (course completed screen)
- outline (module listing)
- running (submission still evaluating)
- unknown

Also answer: Is the editor already a finished program? (yes/no)

Reply in this exact format:
layout: <name>
code_written: <yes|no>
"""

    try:
        model = _get_model()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ]},
            ],
            temperature=0.0,
            max_tokens=50,
        )
        text = response.choices[0].message.content.strip().lower()
        layout = "unknown"
        code_written = False

        for line in text.split("\n"):
            if line.startswith("layout:"):
                layout = line.split(":", 1)[1].strip()
            elif line.startswith("code_written:"):
                code_written = "yes" in line.lower()

        valid_layouts = {"roadmap", "reading", "guided", "exercise", "quiz",
                         "auth", "done", "outline", "running", "unknown"}
        if layout not in valid_layouts:
            layout = "unknown"

        return {"layout": layout, "code_written": code_written}

    except Exception as e:
        print(f"[solve] AI vision failed: {e}")
        return {"layout": "unknown", "code_written": False}


def resolve_code(page: Page, obs: dict, language: str = "C") -> str:
    """
    Full solver chain for an exercise page:
    1. Check if editor already has a finished program → return it.
    2. Try the Solution tab → return that code (auto-converted to C if C++).
    3. Call AI → return generated pure C code.
    Returns the code to write, or empty string if all fail.
    """
    editor_text = obs.get("editor_text", "")
    statement = obs.get("statement", "")

    # 1. Solution tab has the verified instructor solution
    if obs.get("has_solution_tab", False) or "Solution" in obs.get("tabs", []):
        print("[solve] Fetching verified code from Solution tab...")
        solution = get_solution_from_tab(page)
        if solution:
            print("[solve] Successfully extracted solution from Solution tab")
            if is_cpp_code(solution):
                print("[solve] Solution tab contains C++ code — converting to pure C...")
                solution = convert_to_c(solution, statement)
            return solution

    # 2. Check if editor already has a finished program
    if is_code_written(editor_text, statement):
        print("[solve] Editor already has finished code")
        if is_cpp_code(editor_text):
            print("[solve] Editor code is C++ — converting to pure C...")
            return convert_to_c(editor_text, statement)
        return editor_text

    # 3. AI generation fallback
    print("[solve] Generating solution with AI in pure C...")
    generated = generate_solution(statement, editor_text, language)
    if generated:
        print("[solve] Got generated solution from AI")
        return generated

    print("[solve] All solver methods failed")
    return ""


def _strip_fences(code: str) -> str:
    """Remove markdown code fences if present."""
    code = (code or "").strip()
    if code.startswith("```"):
        code = re.sub(r'^```[^\n]*\n', '', code)
        code = re.sub(r'\n```[^\n]*$', '', code)
    return code.strip()
