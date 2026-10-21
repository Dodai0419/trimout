#!/usr/bin/env python3
"""trimout: shrink tool output before an agent reads it. Lossy only where it is safe, offline, stdlib only.

Three passes from two token savers, each byte-identical to its source:
  diff context     caveman engine/compressors/diff.go (Julius Brussee, Apache-2.0)
  dense lines      headroom transforms/dense_line_elider.py + recursive_json.py (Headroom Labs, Apache-2.0)
  repeated lines   caveman engine/compressors/repetition.go (Julius Brussee, Apache-2.0)

Usage:
  some-command | python trimout.py [--type auto|diff|text] [--stats]
  python trimout.py FILE [--type ...] [--stats]
"""
import argparse
import json
import re
import sys

ELLIPSIS = chr(0x2026)

# ---------------------------------------------------------------- caveman: unified diff context
DIFF_MARK = re.compile(r"context lines elided \(caveman\)")
DIFF_HEADERS = ("diff --git ", "index ", "--- ", "+++ ", "@@ ", "similarity index ", "dissimilarity index ",
                "rename from ", "rename to ", "copy from ", "copy to ", "old mode ", "new mode ", "new file mode ",
                "deleted file mode ", "Binary files ", "GIT binary patch", "\\")


def majority_crlf(s):
    lf = s.count("\n")
    return lf > 0 and s.count("\r\n") * 2 > lf


def compress_diff(s, keep_context=2, min_lines=12):
    """Keep headers, changed lines and +-2 lines of context; fold longer context runs into one marker. None = no change."""
    trailing = s.endswith("\n")
    lines = (s[:-1] if trailing else s).split("\n")
    if len(lines) < min_lines:
        return None
    cr = "\r" if majority_crlf(s) else ""
    keep = [False] * len(lines)
    for i, line in enumerate(lines):
        if line.startswith(DIFF_HEADERS) or line[:1] in ("+", "-") or DIFF_MARK.search(line):
            for j in range(max(0, i - keep_context), min(len(lines) - 1, i + keep_context) + 1):
                keep[j] = True
    out, dropped = [], 0
    for line, k in zip(lines, keep):
        if k:
            if dropped:
                out.append("%s %d context lines elided (caveman) %s%s" % (ELLIPSIS, dropped, ELLIPSIS, cr))
                dropped = 0
            out.append(line)
        else:
            dropped += 1
    if dropped:
        out.append("%s %d context lines elided (caveman) %s%s" % (ELLIPSIS, dropped, ELLIPSIS, cr))
    if len(out) == len(lines):
        return None
    return "\n".join(out) + ("\n" if trailing else "")


def is_diff(s):
    lines = s.split("\n", 400)[:400]
    return any(l.startswith("diff --git ") or (l.startswith("--- ") and n.startswith("+++ ")) for l, n in zip(lines, lines[1:]))


# ---------------------------------------------------------------- headroom: dense machine-generated lines
MIN_LINE_CHARS, MAX_SPACE_RATIO, MIN_DENSE_TOTAL_CHARS, HEAD_CHARS, TAIL_CHARS = 300, 0.06, 2000, 160, 80
PAIR = {"}": "{", "]": "["}


def scan_from(text, start, known):
    """Walk one bracket span, recording the verdict of every nested bracket; (end or None, chars walked)."""
    stack, in_str, esc = [], False, False
    for j in range(start, len(text)):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "[{":
            stack.append(j)
        elif ch in "]}":
            if not stack or text[stack[-1]] != PAIR[ch]:
                known.update(dict.fromkeys(stack))
                return None, j - start + 1
            known[stack.pop()] = j + 1
            if not stack:
                return j + 1, j - start + 1
    known.update(dict.fromkeys(stack))
    return None, len(text) - start


def json_documents(text):
    """(spans of embedded JSON objects/arrays, complete): headroom's scan_json_documents with its work budgets."""
    known, n = {}, len(text)
    budget, spent, i = 4 * n + 4096, 0, 0
    while i < n:
        if text[i] in "[{":
            if i in known:
                end = known[i]
            elif spent >= budget:
                return [], False
            else:
                end, walked = scan_from(text, i, known)
                spent += walked
            if end is not None:
                i = end
                continue
        i += 1
    out, covered, parsed, parse_budget = [], 0, 0, 4 * n + 4096
    for a in range(n):
        b = known.get(a)
        if b is None or a < covered:
            continue
        if parsed + b - a > parse_budget:
            return out, False
        parsed += b - a
        try:
            doc = json.loads(text[a:b])
        except RecursionError:
            return out, False
        except (ValueError, TypeError):
            continue
        if isinstance(doc, (dict, list)):
            out.append((a, b))
            covered = b
    return out, True


def is_dense_line(line):
    """Long, nearly space-free, tab-free and carrying no JSON: minified JS/CSS, base64, RSC payloads."""
    n = len(line)
    if n < MIN_LINE_CHARS or "\t" in line or line.count(" ") / n >= MAX_SPACE_RATIO:
        return False
    stripped = line.strip()
    if stripped[:1] in "{[" and stripped[-1:] in "}]":
        return False
    spans, complete = json_documents(line)
    return complete and not spans


def elide_dense_lines(text):
    """(text with dense lines cut to head + marker + tail, lines elided); unchanged unless they total 2000+ chars."""
    if len(text) < MIN_LINE_CHARS:
        return text, 0
    lines = text.split("\n")
    dense = [is_dense_line(l) for l in lines]
    if sum(len(l) for l, d in zip(lines, dense) if d) < MIN_DENSE_TOTAL_CHARS:
        return text, 0
    out = ["%s ...[%d chars of dense machine-generated content elided]... %s" % (l[:HEAD_CHARS], len(l) - HEAD_CHARS - TAIL_CHARS,
                                                                                  l[-TAIL_CHARS:]) if d else l
           for l, d in zip(lines, dense)]
    return "\n".join(out), sum(dense)


# ---------------------------------------------------------------- caveman: runs of identical lines
REP_PREFIX = ELLIPSIS + " caveman: "
GO_SPACE = "\t\n\x0b\x0c\r \x85\xa0" + "".join(map(chr, [0x1680, *range(0x2000, 0x200b), 0x2028, 0x2029, 0x202f, 0x205f, 0x3000]))


def collapse_repeats(s, min_run=3, min_bytes=200):
    """Keep the first of 3+ identical non-blank lines plus a count marker. None = no change or no saving."""
    size = len(s.encode("utf-8"))
    if size < min_bytes:
        return None
    lines, out, collapsed, i = s.split("\n"), [], False, 0
    while i < len(lines):
        j = i + 1
        while j < len(lines) and lines[j] == lines[i]:
            j += 1
        out.append(lines[i])
        if j - i >= min_run and lines[i].strip(GO_SPACE) and not lines[i].startswith(REP_PREFIX):
            out.append("%s%d identical lines elided %s" % (REP_PREFIX, j - i - 1, ELLIPSIS))
            collapsed = True
        else:
            out.extend(lines[i + 1:j])
        i = j
    result = "\n".join(out)
    return result if collapsed and len(result.encode("utf-8")) < size else None


# ---------------------------------------------------------------- pipeline
def trim(text, kind="auto"):
    """diff context (diffs only) -> dense lines -> repeated lines."""
    if kind == "diff" or (kind == "auto" and is_diff(text)):
        text = compress_diff(text) or text
    text = elide_dense_lines(text)[0]
    return collapse_repeats(text) or text


def main(argv=None):
    ap = argparse.ArgumentParser(description="Shrink tool output before an agent reads it.")
    ap.add_argument("file", nargs="?", help="input file (default: stdin)")
    ap.add_argument("--type", choices=("auto", "diff", "text"), default="auto",
                    help="auto runs the diff pass only on unified diffs")
    ap.add_argument("--stats", action="store_true", help="print sizes to stderr")
    a = ap.parse_args(argv)
    if a.file:
        with open(a.file, "rb") as f:
            data = f.read()
    else:
        data = sys.stdin.buffer.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:  # like caveman: never rewrite bytes that are not valid UTF-8
        sys.stdout.buffer.write(data)
        return 0
    out = trim(text, a.type)
    sys.stdout.buffer.write(out.encode("utf-8"))
    if a.stats:
        saved = 100 * (len(text) - len(out)) // len(text) if text else 0
        print("trimout: %d -> %d chars (-%d%%)" % (len(text), len(out), saved), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
