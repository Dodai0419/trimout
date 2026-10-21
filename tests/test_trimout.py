"""Every stage of trimout must match its upstream byte for byte (caveman diff + repetition, headroom dense lines)."""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import trimout  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")
with open(os.path.join(ROOT, "tests", "upstream.json"), encoding="utf-8") as f:
    UP = json.load(f)


def read(name):
    with open(os.path.join(FIX, name), encoding="utf-8", newline="") as f:
        return f.read()


class MatchesUpstream(unittest.TestCase):
    def test_diff_stage_matches_caveman(self):
        for name, up in UP.items():
            if name.endswith(".diff"):
                self.assertEqual(trimout.compress_diff(read(name)) or read(name), up["diff"], name)

    def test_dense_stage_matches_headroom(self):
        for name, up in UP.items():
            self.assertEqual(trimout.elide_dense_lines(up["diff"]), (up["dense"], up["dense_lines"]), name)

    def test_repetition_stage_matches_caveman(self):
        for name, up in UP.items():
            self.assertEqual(trimout.collapse_repeats(up["dense"]) or up["dense"], up["final"], name)

    def test_cli_output_equals_upstream_chain(self):
        for name, up in UP.items():
            p = subprocess.run([sys.executable, "trimout.py", os.path.join(FIX, name)], cwd=ROOT, capture_output=True)
            self.assertEqual(p.stdout.decode("utf-8"), up["final"], name)


class Behaviour(unittest.TestCase):
    def test_diff_keeps_every_changed_and_header_line(self):
        out = trimout.compress_diff(read("rename.diff"))
        for line in ("rename to b.py", "-  - name: build", "+--verbose", "\\ No newline at end of file"):
            self.assertIn(line + "\n", out)

    def test_idempotent(self):
        once = trimout.trim(read("mixed.txt"))
        self.assertEqual(trimout.trim(once), once)

    def test_invalid_utf8_passes_through(self):
        data = b"\xff\xfe" + b"same line\n" * 50
        p = subprocess.run([sys.executable, "trimout.py"], cwd=ROOT, input=data, capture_output=True)
        self.assertEqual(p.stdout, data)

    def test_stats_go_to_stderr(self):
        p = subprocess.run([sys.executable, "trimout.py", os.path.join(FIX, "build.log"), "--stats"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertIn("1840 -> 377 chars", p.stderr)
        self.assertEqual(p.stdout, UP["build.log"]["final"])


if __name__ == "__main__":
    unittest.main()
