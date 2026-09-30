"""The writing rules in CLAUDE.md and CONVENTIONS *Comments*, checked.

Docs and source comments: filler phrases are banned outright, and phrases with
real uses are capped per thousand words of a document. Reference docs carry no
narrated history, CLAUDE.md stays under its word cap, and CLAUDE.md and
CONVENTIONS.md carry no dates. Comment shape (block length, dates, measured
figures) is checked on lines added since HEAD, since the conventions cover
touched code only.  Usage: python python/tests/voice.py [--all-lines]
"""

import argparse
import ast
import io
import os
import re
import subprocess
import sys
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPOS = [ROOT, os.path.join(ROOT, "web")]
SKIP_DIRS = {".venv", ".git", "node_modules", "__pycache__", "cb_reference", "archive",
             "analysis_artifacts", "checkpoints", "tb", "logs", "libraries", "legacy_neat"}
SELF = "python/tests/voice.py"
LOGS = {"PROJECT_STATUS.md", "python/autorun/RUNLOG.md"}   # dated by design
UNDATED = {"CLAUDE.md", "CONVENTIONS.md"}
CLAUDE_WORDS = 1500
HEADER_LINES = 10
DOC_LINES = 10
BLOCK_LINES = 2

BANNED = [
    (r"\bgenuinely\b|\bhonestly\b|\bto be honest\b|\bquietly\b", "filler"),
    (r"\bworth (?:noting|knowing|stating|saying|mentioning|emphasi[sz]ing)\b", "worth noting"),
    (r",\s*which is what\b|\bthat is deliberate\b|\bfor good reason\b", "trailing justification"),
    (r"\bthe whole point\b|(?:^|[.:!?]\s+)the point is\b|\bthe key insight\b", "the point"),
    (r"\bnot a small one\b|\bcrucially\b|\bimportantly\b", "dramatized"),
]
# (pattern, name, per thousand words); every doc may use each at least CAP_FLOOR times
CAPPED = [
    (r"\brather than\b", "rather than", 0.5),
    (r"\bnote that\b|\bnotably\b", "note that", 0.5),
    (r"\bdeliberately\b|\bon purpose\b|\bintentionally\b", "deliberately", 0.5),
    (r"\bsimply\b|\bmerely\b|\bjust\b", "simply/just", 1.0),
    (r"—", "em-dash", 3.0),
]
CAP_FLOOR = 2
HISTORY = re.compile(
    r"(?<!\bis )(?<!\bare )(?<!\bwas )(?<!\bwere )(?<!\bbe )(?<!\bbeen )\bused to\b"
    r"|\buntil now\b|\bha(?:s|ve) since\b|\bno longer\b|\bwas tried\b", re.I)
BANNED = [(re.compile(p, re.I), n) for p, n in BANNED]
CAPPED = [(re.compile(p, re.I), n, k) for p, n, k in CAPPED]
DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
MEASURE = re.compile(r"±|\b\d[\d,]*(?:\.\d+)?\s*(?:ms|s|sec|min|h|MB|GB|%|×)(?!\w)"
                     r"|\bp[≈<=]\s*0?\.\d|\b\d+(?:\.\d+)?x(?!\w)")
QUOTED = re.compile(r'"[^"\n]*"|`[^`\n]*`')   # a rule may name what it bans
BANNER = re.compile(r"^\s*[-=#*/]{4,}")
LEAD = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(?:\*\*[^*]+\*\*|[^—]{0,40}?)\s+—\s")


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def files():
    for path, dirs, names in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if os.path.splitext(name)[1] in {".md", ".py", ".js"}:
                yield os.path.join(path, name)


def added_lines():
    """{relative path: set of line numbers added since HEAD}, untracked files whole."""
    out = {}
    for repo in REPOS:
        prefix = "" if repo == ROOT else rel(repo) + "/"
        diff = subprocess.run(["git", "-C", repo, "diff", "HEAD", "-U0", "--no-color"],
                              capture_output=True, text=True, encoding="utf-8").stdout
        name = None
        for line in diff.split("\n"):
            if line.startswith("+++ "):
                name = prefix + line[6:] if line != "+++ /dev/null" else None
            elif line.startswith("@@") and name:
                m = re.search(r"\+(\d+)(?:,(\d+))?", line)
                start, count = int(m.group(1)), int(m.group(2) or 1)
                out.setdefault(name, set()).update(range(start, start + count))
        untracked = subprocess.run(["git", "-C", repo, "ls-files", "--others", "--exclude-standard"],
                                   capture_output=True, text=True).stdout.split()
        for name in untracked:
            out[prefix + name] = ALL
    return out


class _All:
    def __contains__(self, item):
        return True

    def __and__(self, other):
        return set(other)


ALL = _All()


def phrase_hits(lines):
    hits = []
    for number, line in lines:
        clean = QUOTED.sub("", line)
        for pattern, name in BANNED:
            if pattern.search(clean):
                hits.append((number, f"banned: {name}", line))
    return hits


def check_doc(name, text):
    hits, lines, in_fence = [], [], False
    for number, line in enumerate(text.split("\n"), 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            lines.append((number, line))
    hits += phrase_hits(lines)
    prose = [QUOTED.sub("", l) for _, l in lines if not l.lstrip().startswith(("|", "#"))]
    words = sum(len(l.split()) for l in prose)
    for pattern, cap_name, per_k in CAPPED:
        # a list item's "**term** — description" dash is structure, not voice
        count = sum(len(pattern.findall(LEAD.sub("", l) if cap_name == "em-dash" else l))
                    for l in prose)
        limit = max(CAP_FLOOR, int(per_k * words / 1000))
        if count > limit:
            hits.append((1, f"{count} × {cap_name}, cap {limit} for {words:,} words", ""))
    if name not in LOGS:
        hits += [(n, "history in a reference doc", l) for n, l in lines
                 if HISTORY.search(QUOTED.sub("", l))]
    if name in UNDATED:
        hits += [(n, "date", l) for n, l in lines if DATE.search(l)]
    if name == "CLAUDE.md" and len(text.split()) > CLAUDE_WORDS:
        hits.append((1, f"{len(text.split()):,} words, cap {CLAUDE_WORDS:,}", ""))
    return hits


def python_comments(text):
    """(comment lines, docstrings as (start, end, is_module), prose lines)."""
    comments, prose = set(), []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            prose.append((tok.start[0], tok.string))
            if tok.line.strip().startswith("#") and not BANNER.match(tok.string):
                comments.add(tok.start[0])
    docs = []
    tree = ast.parse(text)
    for node in [tree] + [n for n in ast.walk(tree) if isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]:
        if ast.get_docstring(node, clean=False) is not None:
            first = node.body[0]
            docs.append((first.lineno, first.end_lineno, node is tree))
            for k, line in enumerate(ast.get_docstring(node, clean=False).split("\n")):
                prose.append((first.lineno + k, line))
    return comments, docs, prose


def js_comments(text):
    comments, prose, docs, in_block, start = set(), [], [], False, 0
    for number, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        if in_block or s.startswith("/*"):
            prose.append((number, s))
            if not in_block:
                start = number
            in_block = "*/" not in s or (s.startswith("/*") and s.count("*/") == 0)
            if "*/" in s:
                in_block = False
                docs.append((start, number, start == 1))
            continue
        if s.startswith("//"):
            prose.append((number, s[2:]))
            if not BANNER.match(s[2:]):
                comments.add(number)
            continue
        m = re.search(r"(?<![:\w\\'\"])//(.*)$", line)
        if m:
            prose.append((number, m.group(1)))
    return comments, docs, prose


def runs(numbers):
    out, run = [], []
    for n in sorted(numbers):
        if run and n == run[-1] + 1:
            run.append(n)
        else:
            if run:
                out.append(run)
            run = [n]
    return out + ([run] if run else [])


def check_source(name, text, added):
    try:
        comments, docs, prose = (python_comments if name.endswith(".py") else js_comments)(text)
    except (SyntaxError, tokenize.TokenError):
        return [(1, "could not parse", "")]
    hits = phrase_hits(prose)
    for number, line in prose:
        if number in added:
            clean = QUOTED.sub("", line)
            if DATE.search(clean):
                hits.append((number, "date in a comment", line))
            if MEASURE.search(clean):
                hits.append((number, "measured figure in a comment", line))
    for run in runs(comments):
        is_header = run[0] == 1 or (run[0] <= 3 and name.endswith(".js"))
        limit = HEADER_LINES if is_header else BLOCK_LINES
        if len(run) > limit and any(n in added for n in run):
            hits.append((run[0], f"comment block of {len(run)} lines, limit {limit}", ""))
    for start, end, is_module in docs:
        length = end - start + 1
        if length > (HEADER_LINES if is_module else DOC_LINES) and any(n in added for n in range(start, end + 1)):
            hits.append((start, f"docstring of {length} lines, limit "
                                f"{HEADER_LINES if is_module else DOC_LINES}", ""))
    return hits


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all-lines", action="store_true",
                        help="apply the comment-shape rules to every line, not only new ones")
    args = parser.parse_args()
    added = {} if args.all_lines else added_lines()
    total = 0
    for path in files():
        name = rel(path)
        if name == SELF:
            continue
        text = open(path, encoding="utf-8").read()
        if name.endswith(".md"):
            hits = check_doc(name, text)
        else:
            hits = check_source(name, text, ALL if args.all_lines else added.get(name, set()))
        for number, rule, line in hits:
            print(f"  {name}:{number:<5} {rule}" + (f"   {line.strip()[:70]}" if line else ""))
        total += len(hits)
    print(f"{total} hits")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
