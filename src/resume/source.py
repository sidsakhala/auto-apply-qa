"""Choose the resume the scorer reads."""

from __future__ import annotations

from pathlib import Path

from src.resume.overleaf_pdf import main_tex
from src.resume.parser import parse_resume
from src.resume.pdf_parser import parse_resume_pdf
from src.resume.tex_parser import parse_overleaf_tex
from src.utils.config import AppConfig


def base_resume_pdf(config: AppConfig) -> Path | None:
    """Static PDF used for Naukri profile upload and job PDFs when Overleaf is off."""
    path = config.base_resume
    if path is None:
        return None
    return path if path.exists() else None


def scoring_resume_path(config: AppConfig) -> Path:
    base = base_resume_pdf(config)
    if base is not None:
        return base
    if config.overleaf_project_url.strip() and config.overleaf_dir.exists():
        try:
            return main_tex(config.overleaf_dir)
        except Exception:
            pass
    if config.master_resume.suffix.lower() == ".pdf" and config.master_resume.exists():
        return config.master_resume
    return config.master_resume


def load_scoring_resume(config: AppConfig):
    path = scoring_resume_path(config)
    if path.suffix.lower() == ".tex":
        return parse_overleaf_tex(path)
    if path.suffix.lower() == ".pdf":
        return parse_resume_pdf(path)
    return parse_resume(path)
