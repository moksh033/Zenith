# ⚡ Zenith – CodeChef Autonomous Course Solver

An intelligent, autonomous bot built with **Playwright** and **LLM inference** to complete CodeChef courses seamlessly. It navigates reading lessons, automatically answers multiple-choice quizzes, fetches instructor solutions, fixes compilation/runtime errors, and dismisses reward popups—all in real-time.

---

## 📦 Download & Run (No Git Required)

If you downloaded a **Release ZIP** (`Zenith.zip`):
1. **Extract the ZIP file** to a folder on your computer.
2. Double-click **`run.bat`**.
   - If it's your first time, it will automatically open `.env` in Notepad. Paste your free API key (Groq, OpenRouter, or Gemini) and save.
   - It will install dependencies and launch the browser.
3. **Log in to CodeChef** in the browser window that opens.
4. **That's it!** The bot starts solving courses automatically.

---

## ✨ Features

- 🧠 **Multi-Tier AI Brain**: Supports **OpenRouter**, **Groq** (free tier), and **Google Gemini** for intelligent code generation, error repair, and quiz answering.
- 🎯 **Solution-Tab Priority**: Automatically copies verified instructor code whenever available before querying AI, minimizing token consumption and ensuring 100% acceptance.
- ✅ **Verified Quiz Answering**: Checks DOM verdict styles and banners to ensure quiz questions are never skipped or marked done prematurely.
- 🏆 **Auto-Dismiss Badges & Popups**: Automatically detects and dismisses "You've earned a diamond badge", streak celebrations, and modal overlays.
- 💾 **Persistent Auto-Resume**: Tracks progress in `progress.json`. If you stop or restart, the runner automatically resumes exactly where you left off.
- 🔒 **Safe Local Authentication**: You log in directly in the browser on first run. Your credentials are never stored or touched by the bot.

---

## 🚀 Quick Start Guide (Developers)

### 1. Prerequisites
- **Python 3.10+** installed
- Git installed

### 2. Clone the Repository
```bash
git clone https://github.com/moksh033/Zenith-.git
cd Zenith-
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure Your API Key
Copy the example environment file:
```bash
# On Linux / macOS:
cp .env.example .env

# On Windows (PowerShell or Command Prompt):
copy .env.example .env
```

Open `.env` in any text editor and add at least **one** of the following:

```env
# Option 1: OpenRouter (Recommended) - https://openrouter.ai/keys
OPENROUTER_API_KEY=your_key_here

# Option 2: Groq (Fast & Free Tier available) - https://console.groq.com/keys
GROQ_API_KEY=your_key_here

# Option 3: Google Gemini (Free tier available) - https://aistudio.google.com/apikey
GEMINI_API_KEY=your_key_here
```

### 5. Launch the Solver
```bash
python main.py
```

---

## 🔑 How Login Works

1. On your very first run, a visible Chromium browser window will launch.
2. If you are not logged in, the terminal will display:
   ```
   FIRST LAUNCH – Please log in to CodeChef in the browser.
   The runner will continue automatically after login.
   ```
3. Log into your own CodeChef account manually (via Email, Google, GitHub, etc.).
4. The solver automatically detects your login and starts solving immediately!
5. Your session cookies are stored locally in `.browser-profile/` (which is git-ignored), so you will **never** have to log in again on future runs.

---

## 🛠️ CLI Options

| Command | Description |
|---|---|
| `python main.py` | Auto-resumes from your last active lesson or default course. |
| `python main.py --start-url <URL>` | Start solving from a specific problem/lesson URL. |
| `python main.py --roadmap` | Automatically continue through all courses in the roadmap. |
| `python main.py --dry-run` | Inspect and classify the current page without clicking anything. |
| `python main.py --probe` | Dump DOM elements, buttons, and syllabus links for debugging. |

### Example: Starting a Specific Problem
```bash
python main.py --start-url https://www.codechef.com/learn/course/c/XEIBAYB/problems/CDEVPROB130
```

---

## 📂 Project Architecture

```
CodeChef Solver/
├── main.py            # CLI entry point, navigation loop, and event handlers
├── act.py             # Browser interaction: clicks, submits, popup dismissals
├── classify.py        # DOM layout classification (quiz, exercise, reading, etc.)
├── editor.py          # Monaco editor interaction and language detection
├── observe.py         # Page DOM observation and screenshot management
├── progress.py        # Persistent progress tracking & resume engine
├── solve.py           # Multi-tier LLM solver (OpenRouter, Groq, Gemini)
├── syllabus.py        # Course outline & lesson URL extraction
├── requirements.txt   # Python package dependencies
├── .env.example       # Template for environment configuration
└── .gitignore         # Ignores local session cookies, progress, and keys
```

---

## 🛡️ Safety & Disclaimer

- **Session Privacy**: The `.browser-profile/` directory and `.env` file are explicitly included in `.gitignore`. Your login cookies and API keys will never be accidentally committed to GitHub.
- **Educational Use**: This project was developed for educational purposes to demonstrate browser automation with Playwright and LLM reasoning. Use responsibly.
