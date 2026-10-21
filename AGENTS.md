# AGENTS.md: trimout

Use when a command you are about to run (or just ran) prints a lot: `npm ci`, `pip install`, test runners with progress output, `git diff` of a large change, `curl` of a web page or API that returns minified or encoded content.

## How to use
1. Pipe the command through it from the repo root: `<command> 2>&1 | python trimout.py`
   - a saved file: `python trimout.py output.txt`
   - force a pass: `--type diff` for a diff without a `diff --git` header, `--type text` to skip the diff pass
   - add `--stats` to see the size change on stderr
2. Read the trimmed output. Markers tell you what was cut:
   - `… caveman: N identical lines elided …` means the line above repeated N more times
   - `… N context lines elided (caveman) …` means unchanged diff context was folded; every `+`/`-` line is still there
   - `...[N chars of dense machine-generated content elided]...` means the middle of a minified or encoded line was cut
3. If you need what a marker hides (for example the full minified line), rerun the command without trimout for that one piece.

## Rules
- Never use trimout on output you must copy verbatim into a file (patches you will apply, keys, encoded payloads).
- Changed diff lines, unique lines, tab-separated rows and JSON are never removed.
- Exit code is always 0; invalid UTF-8 input is printed unchanged.
