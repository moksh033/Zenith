# Zenith

Autonomous CodeChef course solver built with Playwright and LLMs. It steps through reading lessons, solves multiple-choice quizzes with DOM validation, extracts verified instructor solutions from the problem interface, repairs incorrect code submissions, and handles overlay dialogs automatically.

## Quick Start (Release)

For users running the pre-packaged release on Windows:

1. Download `Zenith-v1.0.0.zip` from the [Releases](https://github.com/moksh033/Zenith-/releases) page and extract it.
2. Double-click `run.bat`.
3. If running for the first time, `.env` will open in Notepad. Add an API key from OpenRouter, Groq, or Gemini, then save and close the file.
4. When the browser launches, log in to your CodeChef account.
5. The runner detects your session and begins automatically.

## Quick Start (From Source)

### Requirements
- Python 3.10+
- Chromium (managed by Playwright)

### Setup

```bash
git clone https://github.com/moksh033/Zenith-.git
cd Zenith-
pip install -r requirements.txt
playwright install chromium
```

Copy the example environment configuration:

```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

Add your API key to `.env`:

```env
# Supported providers (specify at least one):
OPENROUTER_API_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=
```

Start the runner:

```bash
python main.py
```

## How It Works

- **Solution Tab Extraction**: Before querying an LLM, the solver checks the problem's Solution tab. If official code exists, it copies and submits it directly to avoid unnecessary API usage.
- **Quiz Verification**: Evaluates DOM feedback directly (border colors, error banners, and score indicators) to verify answers rather than relying on navigation button state. It cycles through all available choices until confirmed.
- **Modal and Popup Handling**: Detects and dismisses overlay dialogs (e.g. badge awards, streak confirmations, celebration popups) that intercept pointer events.
- **Session Persistence**: Browser state and cookies are saved in `.browser-profile/`. You only need to log in once.
- **State Recovery**: Progress is tracked in `progress.json`. Interrupted runs automatically resume from the last active problem.

## CLI Reference

```bash
# Resume from last active problem (default)
python main.py

# Start from a specific lesson URL
python main.py --start-url https://www.codechef.com/learn/course/c/XEIBAYB/problems/CDEVPROB130

# Continue through roadmap courses sequentially
python main.py --roadmap

# Inspect and classify the current page without clicking
python main.py --dry-run

# Output DOM structure, buttons, and detected syllabus
python main.py --probe
```

## Project Structure

```
Zenith/
├── main.py            # Entry point, navigation loop, and layout handlers
├── act.py             # Action execution (clicks, submissions, popup dismissal)
├── classify.py        # Layout classification (quiz, exercise, reading, etc.)
├── editor.py          # Monaco editor interface and language selection
├── observe.py         # DOM state extraction and run logging
├── progress.py        # Persistent progress tracking and resume logic
├── solve.py           # Multi-provider LLM interface (OpenRouter, Groq, Gemini)
├── syllabus.py        # Course outline and problem navigation parsing
├── requirements.txt   # Core Python dependencies
├── run.bat            # Windows bootstrap script
├── .env.example       # Environment configuration template
└── .gitignore         # Excludes credentials, session state, and local runs
```

## Privacy & Security

- `.env` and `.browser-profile/` are excluded by `.gitignore`. Local session cookies and API keys remain on your machine and are never pushed to the remote repository.
