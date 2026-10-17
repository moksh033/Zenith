# Zenith

Automated solver for CodeChef courses. Built with Playwright and LLMs to solve quizzes, write code, submit solutions, and navigate learning tracks automatically.

## Highlights

- **Solution extraction**: Grabs official code directly from the problem Solution tab when available to save tokens and guarantee acceptance.
- **Verified quiz solving**: Checks DOM border colors and verdict banners to verify options. Never skips questions blindly.
- **Popup dismissal**: Automatically dismisses diamond badges, streak celebrations, and modal backdrops that block navigation.
- **Session persistence**: Stores cookies in a local browser profile so you only log in once.
- **Resume capability**: Tracks state in `progress.json` to resume right where you left off.

## Quick Start (Release)

If you downloaded `Zenith-v1.1.0.zip` from Releases:

> **Prerequisite**: Python 3.10+ must be installed. When installing Python on Windows, make sure to check the box **"Add python.exe to PATH"** on the first installer screen.

1. Extract the zip file.
2. Double-click `run.bat` (if Python is missing, it will offer to auto-install it via `winget`).
3. On first launch, `.env` will open in Notepad. Paste your API key (Groq, OpenRouter, or Gemini) and save.
4. Log into your CodeChef account in the browser window that opens.
5. In Chromium, navigate directly to the course or problem you want to start on.
6. Press [ENTER] in the console window to fire up Zenith!

## Quick Start (From Source)

### Requirements
- Python 3.10+
- Chromium (`playwright install chromium`)

### Installation

```bash
git clone https://github.com/moksh033/Zenith.git
cd Zenith
pip install -r requirements.txt
playwright install chromium
```

### Configuration

Copy the example environment file:

```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

Add at least one API key to `.env`:

```env
OPENROUTER_API_KEY=your_key_here
# or GROQ_API_KEY=your_key_here
# or GEMINI_API_KEY=your_key_here
```

### Run

```bash
python main.py
```

## CLI Reference

```bash
# Resume from last active problem (default)
python main.py

# Start from a specific URL
python main.py --start-url <problem_url>

# Continue through all roadmap courses
python main.py --roadmap

# Test layout detection without clicking
python main.py --dry-run
```

## Project Structure

```
Zenith/
├── main.py        # Main execution loop and navigation logic
├── act.py         # Browser clicks, submissions, and popup handling
├── classify.py    # Page type detection (quiz, exercise, reading)
├── editor.py      # Monaco editor interaction
├── observe.py     # DOM inspection and screenshot logging
├── progress.py    # Local progress tracking (progress.json)
├── solve.py       # LLM solver (OpenRouter, Groq, Gemini)
├── syllabus.py    # Course lesson extraction
├── run.bat        # Windows 1-click launcher
├── requirements.txt
└── .env.example
```

## Working Demo Clip

https://github.com/user-attachments/assets/0f683962-ad24-45a0-8c13-b8e76e1636a9



