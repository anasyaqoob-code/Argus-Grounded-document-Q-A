"""Finding #1 (Critical): no secrets in version control or shipped files.

Regression guard for the assessment's top finding — a `.env` file with a
real GROQ_API_KEY ended up inside a submitted archive.

The two git-dependent tests skip cleanly when ``backend/`` is not inside
a git working tree, so this file is safe to run from a plain directory.
The file-scanning tests always run.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

# Patterns that look like leaked Groq keys.
GROQ_KEY_RE = re.compile(r"gsk_[A-Za-z0-9]{20,}")


def _run_git(*args: str) -> tuple[int, str]:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.returncode, (out.stdout + out.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""


def _has_git_repo() -> bool:
    """True if REPO is inside a git working tree."""
    code, _ = _run_git("rev-parse", "--show-toplevel")
    return code == 0


requires_git = pytest.mark.skipif(
    not _has_git_repo(),
    reason="not a git working tree — secrets-in-vcs checks skipped",
)


# ---------------------------------------------------------------------------
# .env.example — always run (file-only checks, no git needed)
# ---------------------------------------------------------------------------
def test_env_example_exists():
    p = BACKEND / ".env.example"
    assert p.exists(), ".env.example is missing — it must be committed"


def test_env_example_has_no_real_key():
    p = BACKEND / ".env.example"
    if not p.exists():
        pytest.skip(".env.example missing")
    text = p.read_text()
    matches = GROQ_KEY_RE.findall(text)
    assert not matches, (
        f".env.example contains what looks like a real Groq key: {matches[:1]}. "
        "Scrub it immediately."
    )


def test_env_example_groq_key_is_empty_or_placeholder():
    p = BACKEND / ".env.example"
    if not p.exists():
        pytest.skip(".env.example missing")
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("GROQ_API_KEY="):
            value = line.split("=", 1)[1].strip()
            assert value in ("", "<your-groq-key>", "gsk_..."), (
                f"GROQ_API_KEY in .env.example must be a placeholder, "
                f"got: {value!r}"
            )
            return


# ---------------------------------------------------------------------------
# .env — git-dependent checks. Skip when not in a repo.
# ---------------------------------------------------------------------------
@requires_git
def test_env_is_gitignored_when_present():
    env = BACKEND / ".env"
    if not env.exists():
        pytest.skip(".env not present (fine for CI)")
    code, out = _run_git("check-ignore", "-v", "backend/.env")
    assert code == 0, (
        f".env exists but is not git-ignored.\n"
        f"  git check-ignore -v backend/.env\n"
        f"  → {out}"
    )


@requires_git
def test_env_is_not_tracked():
    code, out = _run_git("ls-files", "backend/.env")
    assert out.strip() == "", (
        ".env is tracked by git. Run:\n"
        "  git rm --cached backend/.env\n"
        "then rotate the key — it's already in history."
    )


# ---------------------------------------------------------------------------
# Source tree — no hard-coded keys anywhere under app/
# Always run.
# ---------------------------------------------------------------------------
def test_no_hardcoded_groq_keys_in_source():
    app_dir = BACKEND / "app"
    offenders: list[str] = []
    for py in app_dir.rglob("*.py"):
        text = py.read_text()
        if GROQ_KEY_RE.search(text):
            offenders.append(str(py.relative_to(BACKEND)))
    assert not offenders, (
        f"Hard-coded Groq keys found in: {offenders}. "
        "Keys must come from environment variables, never from source."
    )


# ---------------------------------------------------------------------------
# .gitignore coverage — the file itself is required regardless of git
# ---------------------------------------------------------------------------
def test_gitignore_covers_sensitive_paths():
    gi = BACKEND / ".gitignore"
    assert gi.exists(), ".gitignore missing"
    text = gi.read_text()
    required_patterns = [".env", "data", "venv"]
    missing = [p for p in required_patterns if p not in text]
    assert not missing, f".gitignore missing patterns: {missing}"