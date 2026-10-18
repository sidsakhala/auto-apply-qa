"""Compile a per-job PDF from the Overleaf project without changing that project.

The Overleaf tree is a read-only mirror. Tailoring is applied to a copy under
``resume/generated/.build``, then compiled. Nothing is pushed back to Overleaf.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from pathlib import Path

from src.exceptions import ConfigurationError, ResumeIntegrityError
from src.resume.generator import assert_safe_destination
from src.resume.models import Resume
from src.utils.config import AppConfig
from src.utils.logger import get_logger

logger = get_logger("overleaf")

_PROJECT_ID = re.compile(r"/project/([0-9a-fA-F]{24})")
_SECTION = re.compile(
    r"\\(?:cvsection|rSection|section\*?|subsection\*?)\{([^}]*)\}",
    re.IGNORECASE,
)
_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_warned = False
_sync_done = False
_sync_result: Path | None = None


def project_id_from_url(url: str) -> str:
    match = _PROJECT_ID.search(url or "")
    if not match:
        raise ConfigurationError(f"Not an Overleaf project URL: {url}")
    return match.group(1)


def latex_escape(text: str) -> str:
    return "".join(_SPECIAL.get(char, char) for char in text)


def _plain_pattern(plain: str) -> str:
    parts: list[str] = []
    for char in plain:
        if char in _SPECIAL and char != "\\":
            parts.append(r"\\?" + re.escape(char))
        elif char == "\\":
            parts.append(r"(?:\\textbackslash\{\}|\\)")
        elif char.isspace():
            parts.append(r"\s+")
        else:
            parts.append(re.escape(char))
    return r"(?<![A-Za-z0-9])" + "".join(parts) + r"(?![A-Za-z0-9])"


def find_span(tex: str, plain: str, start: int = 0, end: int | None = None) -> tuple[int, int] | None:
    """Locate plain resume text inside LaTeX, allowing escapes such as \\%."""
    if not plain.strip():
        return None
    region = tex[start:end]
    match = re.search(_plain_pattern(plain), region)
    if not match:
        return None
    return start + match.start(), start + match.end()


def _replace_span(tex: str, span: tuple[int, int], replacement: str) -> str:
    start, end = span
    return tex[:start] + latex_escape(replacement) + tex[end:]


def _skills_region(tex: str) -> tuple[int, int] | None:
    for match in _SECTION.finditer(tex):
        if "skill" in match.group(1).lower():
            nxt = _SECTION.search(tex, match.end())
            end = nxt.start() if nxt else len(tex)
            return match.end(), end
    return None


def _spans_overlap(spans: list[tuple[int, int]]) -> bool:
    ordered = sorted(spans)
    return any(left[1] > right[0] for left, right in zip(ordered, ordered[1:]))


def _reorder_skills(tex: str, before: list[str], after: list[str]) -> str:
    region = _skills_region(tex)
    if region is None:
        return tex
    start, end = region
    spans: list[tuple[int, int]] = []
    for skill in before:
        span = find_span(tex, skill, start, end)
        if span is None:
            return tex
        spans.append(span)
    if len(set(spans)) != len(spans) or _spans_overlap(spans):
        return tex
    present = set(before)
    ordered = [skill for skill in after if skill in present]
    if len(ordered) != len(spans):
        return tex
    for span, skill in zip(reversed(sorted(spans)), reversed(ordered)):
        tex = _replace_span(tex, span, skill)
    return tex


def _rewrite_bullets(tex: str, original: list[str], updated: list[str]) -> str:
    spans: list[tuple[int, int]] = []
    for bullet in original:
        span = find_span(tex, bullet)
        if span is None:
            return tex
        spans.append(span)
    if len(set(spans)) != len(spans) or _spans_overlap(spans) or len(updated) != len(spans):
        return tex
    for span, bullet in zip(reversed(sorted(spans)), reversed(updated)):
        tex = _replace_span(tex, span, bullet)
    return tex


def _plain_tex(tex: str) -> str:
    plain = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", tex)
    return plain.replace(r"\&", "&")


def _skill_label(canonical: str, plain: str) -> str:
    from src.utils.skills import ALIASES

    options = [alias for alias, name in ALIASES.items() if name == canonical]
    options.append(canonical.lower())
    options.sort(key=len, reverse=True)
    for alias in options:
        match = re.search(rf"(?<![A-Za-z0-9+#]){re.escape(alias)}(?![A-Za-z0-9+#])", plain, re.IGNORECASE)
        if not match:
            continue
        found = match.group(0)
        if found.isupper() or len(found) <= 4:
            return found
        return canonical
    return canonical


def key_skills_for_jd(tex: str, jd_skills: list[str], *, limit: int = 12) -> list[str]:
    """JD skills that already appear in the Overleaf resume, in JD order."""
    from src.utils.skills import canonicalize, find_skills

    plain = _plain_tex(tex)
    owned = set(find_skills(plain))
    chosen: list[str] = []
    seen: set[str] = set()
    for skill in jd_skills:
        canonical = canonicalize(str(skill))
        if not canonical or canonical in seen or canonical not in owned:
            continue
        seen.add(canonical)
        chosen.append(_skill_label(canonical, plain))
        if len(chosen) >= limit:
            break
    return chosen


_CATEGORY_LINE = re.compile(
    r"(\\item\s+\\textbf\{[^}]*\}\s*)([^\n]*)",
)


def _split_skill_items(body: str) -> list[str]:
    """Split a category list on commas that are outside parentheses."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue
        buf.append(char)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _item_rank(item: str, jd_skills: list[str]) -> int | None:
    from src.utils.skills import canonicalize, find_skills

    present = set(find_skills(item))
    best: int | None = None
    for index, skill in enumerate(jd_skills):
        canonical = canonicalize(str(skill))
        matched = canonical in present
        if not matched and not present:
            matched = bool(
                re.search(rf"(?<![A-Za-z0-9+#]){re.escape(str(skill))}(?![A-Za-z0-9+#])", item, re.IGNORECASE)
            )
        if matched and (best is None or index < best):
            best = index
    return best


def _promote_category_skills(skills: list[str], jd_skills: list[str]) -> list[str]:
    def sort_key(pair: tuple[int, str]) -> tuple[int, int, int]:
        index, skill = pair
        rank = _item_rank(skill, jd_skills)
        if rank is None:
            return (1, index, 0)
        return (0, rank, index)

    return [skill for _, skill in sorted(enumerate(skills), key=sort_key)]


def upsert_key_skills(tex: str, jd_skills: list[str]) -> str:
    """Move JD skills to the front of the technical category they already belong to.

    Skills that are not already listed under a category stay off the resume.
    """
    if not jd_skills:
        return tex
    region = _skills_region(tex)
    if region is None:
        return tex
    start, end = region
    block = tex[start:end]
    block = re.sub(r"\\item\s+\\textbf\{Key skills:\}[^\n]*\n+", "", block)

    def replace(match: re.Match[str]) -> str:
        prefix, body = match.group(1), match.group(2)
        if "Key skills" in prefix:
            return ""
        skills = _split_skill_items(body)
        if not skills:
            return match.group(0)
        promoted = _promote_category_skills(skills, jd_skills)
        return prefix + ", ".join(latex_escape(skill) for skill in promoted)

    block = _CATEGORY_LINE.sub(replace, block)
    return tex[:start] + block + tex[end:]


def render_tailored_tex(source: str, resume: Resume, tailored: dict) -> str:
    """Return LaTeX with summary, skill order, and bullets updated.

    A JD skill is moved to the front of its existing technical category. It is not added to a new category.
    """
    tex = source
    summary_span = find_span(tex, resume.summary) if resume.summary else None
    if summary_span and tailored.get("summary") and tailored["summary"] != resume.summary:
        tex = _replace_span(tex, summary_span, tailored["summary"])
    tex = _reorder_skills(tex, list(resume.skills), list(tailored.get("skills") or []))
    for original, updated in zip(resume.experience, tailored.get("experience") or []):
        tex = _rewrite_bullets(tex, original.bullets(), updated.bullets())
    jd_skills = list(tailored.get("jd_skills") or [])
    return upsert_key_skills(tex, jd_skills)


def _auth_args(token: str) -> list[str]:
    basic = base64.b64encode(f"git:{token}".encode()).decode()
    return ["-c", f"http.extraheader=Authorization: Basic {basic}"]


def clone_command(project_id: str, token: str, destination: Path) -> list[str]:
    """Git clone arguments. The token stays in the auth header, not the URL."""
    return [
        "git",
        *_auth_args(token),
        "clone",
        f"https://git.overleaf.com/{project_id}",
        str(destination),
    ]


def _redact(text: str, token: str) -> str:
    if token:
        text = text.replace(token, "***")
    return text


def _run_git(args: list[str], token: str) -> None:
    if "push" in args:
        raise ResumeIntegrityError("Refusing to push to the Overleaf master project")
    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = _redact((completed.stderr or completed.stdout or "").strip(), token)
        raise ConfigurationError(f"Overleaf git failed: {detail[-500:]}")


def _tex_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in root.rglob("*.tex") if ".git" not in path.parts]


def sync_overleaf(config: AppConfig) -> Path | None:
    """Pull the Overleaf project when a token is configured. Never pushes."""
    global _warned, _sync_done, _sync_result
    if _sync_done:
        return _sync_result
    url = config.overleaf_project_url
    if not url:
        _sync_done = True
        _sync_result = None
        return None
    destination = config.overleaf_dir
    token = os.getenv("OVERLEAF_GIT_TOKEN", "").strip()
    project_id = project_id_from_url(url)
    if token and not _tex_files(destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and any(destination.iterdir()):
            raise ConfigurationError(
                f"{destination} is not an empty Overleaf checkout. Move it aside or clear it, then run again."
            )
        logger.info("Cloning Overleaf project %s", project_id)
        _run_git(clone_command(project_id, token, destination), token)
    elif token and (destination / ".git").exists():
        logger.info("Updating Overleaf project %s", project_id)
        _run_git(
            ["git", "-C", str(destination), *_auth_args(token), "pull", "--ff-only"],
            token,
        )
    if _tex_files(destination):
        _sync_done = True
        _sync_result = destination
        return destination
    _sync_done = True
    _sync_result = None
    if not _warned:
        _warned = True
        logger.warning(
            "Overleaf project %s is private. Add OVERLEAF_GIT_TOKEN to .env "
            "(Account Settings, Git), or unzip the project into %s. "
            "Tailored DOCX files will still be written. The Overleaf project is not modified.",
            project_id,
            destination,
        )
    return None


def main_tex(root: Path) -> Path:
    files = _tex_files(root)
    for name in ("main.tex", "resume.tex"):
        for path in files:
            if path.name == name:
                return path
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if r"\documentclass" in text:
            return path
    if len(files) == 1:
        return files[0]
    raise ResumeIntegrityError(f"No main TeX file under {root}")


def escape_prose_ampersands(tex: str) -> str:
    """Escape & in prose lines. Tabular rows that end with \\\\ keep their alignment tabs."""
    lines: list[str] = []
    for line in tex.splitlines(keepends=True):
        if r"\\" in line:
            lines.append(line)
            continue
        lines.append(re.sub(r"(?<!\\)&", r"\\&", line))
    return "".join(lines)


def _compiler(root: Path) -> list[str] | None:
    bundled = root / ".tools" / "tectonic"
    tectonic = shutil.which("tectonic") or (str(bundled) if bundled.exists() else "")
    if tectonic:
        # Overleaf keeps going after recoverable errors such as a bare &. Tectonic stops unless asked.
        return [tectonic, "-Z", "continue-on-errors"]
    pdflatex = shutil.which("pdflatex")
    if pdflatex:
        return [pdflatex, "-interaction=nonstopmode"]
    return None


def _compile(tex_path: Path, compiler: list[str]) -> Path | None:
    outdir = tex_path.parent
    if compiler[0].endswith("pdflatex") or Path(compiler[0]).name == "pdflatex":
        command = [*compiler, "-output-directory", str(outdir), tex_path.name]
    else:
        command = [*compiler, "--outdir", str(outdir), tex_path.name]
    try:
        completed = subprocess.run(
            command,
            cwd=outdir,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Overleaf PDF compile timed out for %s", tex_path.name)
        return None
    pdf = tex_path.with_suffix(".pdf")
    detail = ((completed.stdout or "") + (completed.stderr or "")).strip()
    if pdf.exists() and pdf.stat().st_size > 1000:
        if completed.returncode != 0:
            logger.warning("Overleaf PDF compiled with TeX warnings: %s", detail[-500:])
        return pdf
    logger.warning("Overleaf PDF compile failed: %s", detail[-500:])
    return None


def compile_base_pdf(config: AppConfig, destination: Path) -> Path | None:
    """Compile the Overleaf master with no job-specific edits."""
    if destination.exists() and destination.stat().st_size > 1000:
        return destination
    source_root = sync_overleaf(config)
    if source_root is None:
        return None
    if destination.resolve().is_relative_to(source_root.resolve()):
        raise ResumeIntegrityError("Refusing to write the base PDF inside the Overleaf project")
    compiler = _compiler(config.root)
    if compiler is None:
        logger.warning("Neither tectonic nor pdflatex is installed, so the base PDF was not compiled.")
        return None

    before = {path: path.read_bytes() for path in _tex_files(source_root)}
    build = destination.parent / ".build" / destination.stem
    if build.exists():
        shutil.rmtree(build)
    shutil.copytree(source_root, build, ignore=shutil.ignore_patterns(".git"))
    tex_path = main_tex(build)
    tex_path.write_text(escape_prose_ampersands(tex_path.read_text(encoding="utf-8")), encoding="utf-8")
    pdf = _compile(tex_path, compiler)
    if pdf is None:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf, destination)
    for path, payload in before.items():
        if path.read_bytes() != payload:
            raise ResumeIntegrityError(f"Overleaf source was modified: {path}")
    return destination


def generate_overleaf_pdf(
    config: AppConfig,
    resume: Resume,
    tailored: dict,
    destination: Path,
) -> Path | None:
    """Write one tailored PDF. Returns None when the Overleaf source is unavailable."""
    source_root = sync_overleaf(config)
    if source_root is None:
        return None
    destination = assert_safe_destination(destination, config.master_resume, config.generated_dir)
    if destination.resolve().is_relative_to(source_root.resolve()):
        raise ResumeIntegrityError("Refusing to write a tailored PDF inside the Overleaf project")
    compiler = _compiler(config.root)
    if compiler is None:
        logger.warning("Neither tectonic nor pdflatex is installed, so the Overleaf PDF was not compiled.")
        return None

    before = {path: path.read_bytes() for path in _tex_files(source_root)}
    build = config.generated_dir / ".build" / destination.stem
    if build.exists():
        shutil.rmtree(build)
    shutil.copytree(source_root, build, ignore=shutil.ignore_patterns(".git"))
    tex_path = main_tex(build)
    original = tex_path.read_text(encoding="utf-8")
    rendered = escape_prose_ampersands(render_tailored_tex(original, resume, tailored))
    tex_path.write_text(rendered, encoding="utf-8")
    pdf = _compile(tex_path, compiler)
    if pdf is None:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf, destination)
    for path, payload in before.items():
        if path.read_bytes() != payload:
            raise ResumeIntegrityError(f"Overleaf source was modified: {path}")
    return destination
