# Job Application Tracker

Local-first job application tracker that can be run manually whenever you want.
It reads recent emails over IMAP, uses a local Ollama model to extract job
application updates, and writes the result to an Excel workbook.

The workbook has two sheets:

- `Applications`: one row per company/role with the latest known status.
- `Events`: every email-derived update, so you can audit where a status came from.

## Why This Shape

This is designed to avoid recurring API costs:

- Email is read directly from your mailbox through IMAP.
- AI extraction uses Ollama on your machine.
- The output is a normal `.xlsx` file in `data/job_applications.xlsx`.
- Nothing runs in the background unless you schedule it yourself.

If Ollama is not running, the app falls back to simple local rules so you can
still test the flow.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m job_tracker.cli init
```

Then edit `.env` with your email provider settings. For Gmail or Outlook, use an
app password rather than your normal login password.

Install and start Ollama separately, then pull a model:

```powershell
ollama pull llama3.1:8b
```

## Run A Sync

```powershell
python -m job_tracker.cli sync
```

Useful options:

```powershell
python -m job_tracker.cli sync --dry-run
python -m job_tracker.cli sync --since 2026-06-01
python -m job_tracker.cli sync --no-ollama
python -m job_tracker.cli sync --include-all
```

The default run fetches recent emails, filters them with job-related keywords,
asks Ollama to extract structured updates, writes new events to Excel, and saves
processed message IDs in `data/state.json`.

## Analyze A Saved Email Or Text File

```powershell
python -m job_tracker.cli analyze-file sample.eml
python -m job_tracker.cli analyze-file sample.txt --subject "Application update" --write
python -m job_tracker.cli analyze-file samples/rejection.txt --subject "Application update" --no-ollama
```

This is useful for testing extraction before connecting your real mailbox.

## Scheduling

For your preferred "run it certain days" workflow, keep it manual or create a
Windows Task Scheduler task that runs:

```powershell
C:\path\to\repo\.venv\Scripts\python.exe -m job_tracker.cli sync
```

Run it daily, every few days, or only when you want an updated sheet.
