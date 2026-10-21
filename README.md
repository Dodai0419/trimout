<div align="center">

# trimout

**Shrink tool output before your agent reads it: diffs, repeated log lines, minified blobs. One stdlib file.**

Headroom and Caveman each ship a safe output compressor the other lacks. trimout runs Caveman's diff and repeated-line passes and Headroom's dense-line pass in one Python file, with the same output byte for byte.

Works with **Claude Code** and **Codex**.

![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg) ![Status: prototype](https://img.shields.io/badge/status-prototype-orange.svg)

</div>

## Quick start
```bash
git clone https://github.com/Dodai0419/trimout && cd trimout
python trimout.py tests/fixtures/build.log --stats
```
```
$ npm ci
downloading dependency... please wait
… caveman: 39 identical lines elided …
src/index.ts(12,5): error TS2322: Type 'string' is not assignable to type 'number'.
build failed
trimout: 1840 -> 377 chars (-79%)
```
Pipe anything through it: `npm ci 2>&1 | python trimout.py`, `git diff | python trimout.py`, `curl -s URL | python trimout.py`. `--type diff|text` overrides detection.

## The problem
- `npm ci`, retries and progress bars repeat the same line dozens of times, and the agent pays for every copy.
- A fetched web page or an encoded attachment arrives as a few lines of minified JS or base64 that no structural compressor can shrink.
- Headroom handles the second (in a Rust-backed package with 10 required dependencies), Caveman handles the first and diffs (in a 32 MB Go engine); using both means two runtimes in front of every tool call.

## The solution
| Pass | From | What it does |
|------|------|--------------|
| **Diff context** | Caveman `diff.go` | keeps every header, every `+`/`-` line and 2 lines of context; folds longer unchanged runs into one marker |
| **Dense lines** | Headroom `dense_line_elider.py` | cuts long, space-free, JSON-free lines (minified JS, base64) to head + marker + tail, only when they add up to 2,000+ chars |
| **Repeated lines** | Caveman `repetition.go` | keeps the first of 3+ identical non-blank lines plus a count marker |

Safety rules kept from both: a changed diff line is never dropped, a single JWT or signed URL is never cut, tab-separated rows and labeled JSON are never touched, invalid UTF-8 passes through unchanged, and a second run changes nothing.

## Use with Claude Code
```bash
/plugin marketplace add Dodai0419/trimout
/plugin install trimout@trimout
```

## Use with Codex (ChatGPT)
```bash
git clone https://github.com/Dodai0419/trimout && cp -r trimout/skills/* ~/.codex/skills/
```
Or copy `AGENTS.md` into your project root.

## Benchmarks
Windows 11, Python 3.11, fresh process per run, median of 9 interleaved runs. Upstream = Headroom's `dense_line_elider` imported on its own (the full `headroom` package imports far more) plus a minimal Go build of Caveman's `diff.go` and `repetition.go` (the shipped Caveman engine binary is 32 MB).

| | original (both tools) | trimout |
|-|-|-|
| `change.diff` (28 KB git diff) | 651 ms | 376 ms |
| `mixed.txt` (9 KB, repeats + minified) | 528 ms | 398 ms |
| `blob.txt` (3 KB base64 attachment) | 501 ms | 360 ms |
| 20,000-line build log (707 KB) | 613 ms | 442 ms |
| lines of code | 81 + 282 Python, 86 + 137 + 57 Go | 221 |
| runtimes / dependencies | Python + Go | Python, 0 dependencies |

Savings on the fixtures: build log -79%, base64 attachment -80%, repeats + minified dump -73%, 20,000-line log -40%, a 28 KB diff with 5 lines of context -1%. Prose, tables, labeled JSON and unique lines are left as they are.

Same output: on all 13 fixtures and on 600 random inputs (diffs with CRLF, renames and `\ No newline` markers; logs with Unicode spaces and repeated markers; dense lines with and without embedded JSON), each pass and the full pipeline are byte-identical to running Caveman's Go code and Headroom's Python code in sequence (`python -m unittest -q`).

## Inspired by
- [headroomlabs-ai/headroom](https://github.com/headroomlabs-ai/headroom): the dense-line elider and the JSON span scan that guards it.
- [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman): the diff and repeated-line compressors and their line-ending rules.

## Roadmap
- [ ] A Claude Code `PostToolUse` hook that trims Bash output automatically.
- [ ] Port Caveman's log and search-result compressors.
- [ ] Report token counts, not just characters.

## License
Apache-2.0 (see `NOTICE` for the ported files)
