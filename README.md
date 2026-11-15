# Invisible Work Detector

A desktop app I built that watches the folders you approve, notices the file routines you keep repeating, and offers to do them for you. The catch: it only ever acts after you look at a preview and explicitly say yes.

Everything runs on your own machine. There's a React dashboard, a FastAPI backend, SQLite for storage, and a Python agent that watches your folders. Monitoring is off until you turn it on, and no folder is approved by default. There's also a clearly labeled sample dataset you can explore without touching any real files.

The original idea is written up in [Executive Summary.pdf](Executive%20Summary.pdf). This repo is the working MVP of it.

## Running it (Windows)

You need Python 3.11+ and Node.js 22.12+.

```powershell
.\scripts\setup.ps1
.\scripts\start.ps1
```

Then open http://127.0.0.1:8000 and paste the pairing token the terminal prints. Keep that terminal open; Ctrl+C stops the API and the agent. `start.ps1 -Demo` also loads the sample history.

If you run `start.ps1` again while the app is already running, it just prints the dashboard address instead of starting a second copy. Options like `-Demo` and `-NoAgent` only apply to a fresh start. If some other program is using port 8000, stop it or pick another port with `start.ps1 -Port 8001`.

If the dependencies are already installed and `frontend/dist` is built, this is enough:

```powershell
python run.py --show-token
```

Your data (database, token, backups) lives in `%LOCALAPPDATA%\InvisibleWorkDetector` on Windows, or `~/.local/share/InvisibleWorkDetector` elsewhere. I kept it out of this folder on purpose so OneDrive doesn't sync my activity database along with the code. `--data-dir` or `IWD_DATA_DIR` overrides the location.

## Trying it on real files

1. In Settings, add the full path of a folder you actually use, tick the consent box, enable monitoring, and save. If your routine moves files between two folders, add both.
2. Do the routine a few times: create a file, rename it, move it into a subfolder. Three repetitions is the default threshold before it counts as a pattern.
3. Open Workflows. Discovery runs every 15 seconds, or press "Discover patterns" to run it now.
4. Click Review on a pattern, pick a source file, and preview the changes. You can edit the destination and the new filename first.
5. Look at exactly what will happen, down to every path and spreadsheet value. "Approve this plan" and "Run automation" are two separate buttons on purpose.
6. Follow it in Run history. Every step is logged, and any workbook it touches gets backed up first.

A few things worth knowing:

- Previews expire after 15 minutes and an approval works exactly once. If the file changed after you previewed it, you need a fresh preview.
- It never overwrites an existing file at the destination.
- If a later step fails, the earlier steps stay done. Check the log before running again.
- The "time saved" numbers are planning estimates (80% of the time between your actions), not measured savings.
- If an approved folder disappears or its drive disconnects, monitoring keeps going in the folders that are still there and picks the missing one back up when it returns.

For invoices there's a "Read invoice fields from this PDF" option. It pulls the invoice number, date, and total out of text PDFs, and you can override any of them by hand. Filenames can use `{stem}`, `{date}`, `{invoice_number}`, `{invoice_date}`, and `{amount}`. `{date}` is filled in when you preview, so the name you approve is exactly the name that runs. Slash dates are read as day/month/year. Characters like `/` in an invoice number become `-` in the filename, but the extracted value and the Excel row keep the original.

It can also append a row to an Excel tracker: number, date, amount, and final file path in columns A–D. Existing trackers get a backup before anything changes, new ones get a header row, and anything that looks like a formula is written as plain text so Excel doesn't execute it.

Destination suggestions learn from where you've moved similar files before. Move a few car photos into `photos\car` and bus photos into `photos\bus`, and it suggests the right folder for the next one. It only looks at filenames and folder names, never image contents, and examples have to come from the same source folder inside your approved locations. Unclear names like `IMG_1234.jpg` just make it ask you to choose. Every file still gets a full preview and approval before it moves.

## The AI part (optional)

The app works fine without any API key. If you want nicer explanations of your patterns, set `OPENAI_API_KEY` in the backend's environment, optionally set `IWD_OPENAI_MODEL`, restart, and enable OpenAI in Settings. Never put a key in the frontend or commit it.

When it's on, only the shape of a pattern gets sent: action types, file extensions, session counts, and timings. Never paths, file contents, PDF text, or spreadsheet rows. The model only writes explanations; it can't produce code or choose files. Requests use the Responses API with a typed output schema and `store=False`. If the provider fails, you get a local explanation instead, clearly labeled as such. The tests stub this boundary, so running them never makes a paid API call.

## Development

```powershell
# Terminal 1, repo root
.\.venv\Scripts\python.exe run.py --show-token

# Terminal 2
cd frontend
npm run dev
```

The dev UI is at http://127.0.0.1:5173 and proxies `/api` to port 8000. In production FastAPI serves the built frontend directly, and the hash-based routes work without a separate web server.

To run the backend and agent as separate processes: `python run.py --no-agent --show-token`, then `python -m agent`. They share the same data directory and token. A second agent is rejected while one already holds the lease.

## Checks

```powershell
python -m pytest -q
python -m ruff check backend agent shared tests run.py
cd frontend
npm run build
npm run test:e2e
```

The browser tests start their own isolated server on port 8765 with temporary folders and databases, use only synthetic files, and leave your real settings alone. On Windows they use the installed Microsoft Edge; elsewhere run `npx playwright install chromium` first. `IWD_BROWSER_CHANNEL` and `IWD_PYTHON` can override the browser and Python used. Screenshots land in a temp directory the runner prints.

## Windows portable build

```powershell
.\scripts\package-windows.ps1
```

This produces `dist/InvisibleWorkDetector/InvisibleWorkDetector.exe` with its dependencies; copy the whole directory. It doesn't install a service, enable monitoring, or sign the executable. The script launcher is the main tested path, so try a packaged build on a clean machine before handing it to anyone.

## What this MVP doesn't do

I'd rather be honest about the limits than have you find them the hard way:

- Local and single-user only. No remote hosting, accounts, cloud sync, or installer.
- File activity only. No app/window tracking, no keyboard or screen capture, no GUI automation.
- Cross-volume moves and files outside the initial index (capped at 50,000 files) can show up as creations instead of moves.
- Runs are one-shot and reviewed. There are no continuous triggers and no generated scripts.
- Text PDFs only, up to 20 pages and 20 MB. No OCR, no exotic invoice layouts, no `.xlsm`.
- The path checks (approved folders, no symlinks or junctions, revocation between steps) are a guard against mistakes, not a security boundary against another program running as your Windows user.
- The agent outbox holds at most 10,000 events and says so if it fills up. Interrupted runs are marked for review and never retried automatically. Backups and run history survive "clear activity"; delete them yourself if you want them gone.

More detail in [docs/architecture.md](docs/architecture.md) and [docs/design.md](docs/design.md).