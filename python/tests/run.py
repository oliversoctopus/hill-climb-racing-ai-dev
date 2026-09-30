"""Every test and doc check, in one go.

    python\\.venv\\Scripts\\python.exe python\\tests\\run.py

Each file also runs on its own and says more when it does.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

CHECKS = [
    ("terrain parity", "test_vectorized_ground.py"),
    ("save/restore fidelity", "test_saverestore.py"),
    ("Python and JS obs agree", "test_obs_parity.py"),
    ("Markdown is one line per paragraph", os.path.join("..", "unwrap_md.py")),
    ("doc pointers resolve", "doc_refs.py"),
    ("writing rules hold", "voice.py"),
]


def main():
    failed = []
    for label, script in CHECKS:
        # flush so our label prints above the child's output, not after it
        print(f"---- {label}", flush=True)
        result = subprocess.run([sys.executable, os.path.join(HERE, script)], cwd=ROOT)
        print(flush=True)
        if result.returncode:
            failed.append(label)
    for label in failed:
        print(f"failed   {label}")
    if not failed:
        print(f"passed   {len(CHECKS)} of {len(CHECKS)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
