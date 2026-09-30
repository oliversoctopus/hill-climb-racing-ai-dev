"""Every pointer into the docs resolves, and none cites a rule by number.

A pointer names a heading in italics, `CONVENTIONS *Comments*`, and matches any
heading containing that text. Code never points at CLAUDE.md. Backticked paths
in the reference docs name files or directories that exist.
Usage: python python/tests/doc_refs.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP_DIRS = {".venv", ".git", "node_modules", "__pycache__", "cb_reference", "archive",
             "analysis_artifacts", "checkpoints", "tb", "logs", "libraries"}
LOGS = {"PROJECT_STATUS.md", "python/autorun/RUNLOG.md"}   # may name deleted files
DOC_CHECKS = {"python/tests/doc_refs.py", "python/tests/voice.py", "python/tests/run.py"}
TARGETS = {"CLAUDE": "CLAUDE.md", "CONVENTIONS": "CONVENTIONS.md",
           "PROJECT_STATUS": "PROJECT_STATUS.md"}

POINTER = re.compile(r"\b(CLAUDE|CONVENTIONS|PROJECT_STATUS)(?:\.md)?,?\s+\*([^*\n]{3,90})\*")
NUMBERED = re.compile(r"\bCONVENTIONS(?:\.md)?\s*#\s*\d|\bgotcha\s*#?\s*\d", re.I)
PATH = re.compile(r"`([\w.\-]+/[\w.\-/]*)`")
BASES = ["", "python", "web"]
EXAMPLES = {"python/sample_track.json"}   # files a doc tells the reader to create


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def files():
    for path, dirs, names in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if os.path.splitext(name)[1] in {".md", ".py", ".js", ".html"}:
                yield os.path.join(path, name)


def headings(doc):
    text = open(os.path.join(ROOT, doc), encoding="utf-8").read()
    return [re.sub(r"[*`]", "", l.lstrip("#")).strip().lower()
            for l in text.split("\n") if re.match(r"#{1,6}\s", l)]


def exists(ref, doc_dir):
    """False only for a path whose first directory exists and whose file does not;
    `Car/Wheel.js` shorthand, TensorBoard tags and MIME types pass."""
    ref = ref.rstrip("/")
    bases = [os.path.join(ROOT, base) for base in BASES + [doc_dir]]
    if not any(os.path.isdir(os.path.join(b, ref.split("/")[0])) for b in bases):
        return True
    return any(os.path.exists(os.path.join(b, ref)) for b in bases)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    heads = {k: headings(v) for k, v in TARGETS.items()}
    hits = []
    for path in files():
        name = rel(path)
        text = open(path, encoding="utf-8").read()
        is_code = not name.endswith(".md")
        for number, line in enumerate(text.split("\n"), 1):
            where = f"{name}:{number}"
            if name != "python/autorun/RUNLOG.md" and NUMBERED.search(line):
                hits.append((where, "cites a rule by number", line))
            if is_code and "CLAUDE.md" in line and name not in DOC_CHECKS:
                hits.append((where, "code points at CLAUDE.md", line))
            for target, title in POINTER.findall(line):
                wanted = re.sub(r"[*`]", "", title).strip().lower()
                if not any(wanted in h for h in heads[target]):
                    hits.append((where, f"no {TARGETS[target]} heading contains *{title}*", ""))
            if name.endswith(".md") and name not in LOGS:
                for ref in PATH.findall(line):
                    if ref not in EXAMPLES and not exists(ref, os.path.dirname(name)):
                        hits.append((where, f"no such path `{ref}`", ""))
    for where, rule, line in hits:
        print(f"  {where:40s} {rule}" + (f"   {line.strip()[:60]}" if line else ""))
    print(f"{len(hits)} hits")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
