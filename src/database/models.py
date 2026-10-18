"""SQLite tables for jobs and generated resume versions."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class JobRecord(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    job_title: Mapped[str] = mapped_column(String(300), default="")
    company: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    salary: Mapped[str] = mapped_column(String(200), default="")
    experience: Mapped[str] = mapped_column(String(200), default="")
    job_url: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    job_description_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    dedup_key: Mapped[str] = mapped_column(String(600), default="", index=True)
    normalized_url: Mapped[str] = mapped_column(Text, default="")
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    resume_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_json: Mapped[str] = mapped_column(Text, default="")
    analysis_json: Mapped[str] = mapped_column(Text, default="")
    skill_match_json: Mapped[str] = mapped_column(Text, default="")
    comparison_json: Mapped[str] = mapped_column(Text, default="")
    date_found: Mapped[str] = mapped_column(String(40), default="", index=True)
    date_applied: Mapped[str] = mapped_column(String(40), default="")
    application_status: Mapped[str] = mapped_column(String(48), default="discovered", index=True)
    generated_resume_path: Mapped[str] = mapped_column(Text, default="")
    skip_reason: Mapped[str] = mapped_column(Text, default="")
    unknown_questions: Mapped[str] = mapped_column(Text, default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)


class ResumeVersionRecord(Base):
    __tablename__ = "resume_versions"
    __table_args__ = (UniqueConstraint("job_id", "jd_hash", "master_resume_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), index=True)
    company: Mapped[str] = mapped_column(String(300), default="")
    role: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[str] = mapped_column(String(40), default="")
    master_resume_version: Mapped[str] = mapped_column(String(64), default="")
    jd_hash: Mapped[str] = mapped_column(String(64), default="")
    resume_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_path: Mapped[str] = mapped_column(Text, default="")
    comparison_json: Mapped[str] = mapped_column(Text, default="")
