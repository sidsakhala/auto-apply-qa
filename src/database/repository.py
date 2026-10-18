"""Persistence for jobs, applications, and generated resumes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base, JobRecord, ResumeVersionRecord

APPLIED_STATUSES = ("successful", "applied")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dump(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _row_dict(row: object) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}  # type: ignore[attr-defined]


class Repository:
    def __init__(self, db_path: Path | str) -> None:
        from sqlalchemy import create_engine

        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.path}", future=True)
        Base.metadata.create_all(self.engine)
        self._session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def session(self) -> Session:
        return self._session()

    def find_duplicate(self, *, job_id: str = "", url: str = "", jd_hash: str = "", dedup_key: str = "") -> dict | None:
        with self.session() as session:
            checks = []
            if job_id:
                checks.append(JobRecord.job_id == job_id)
            if url:
                checks.append(JobRecord.normalized_url == url)
            if jd_hash:
                checks.append(JobRecord.job_description_hash == jd_hash)
            if dedup_key and dedup_key != "||":
                checks.append(JobRecord.dedup_key == dedup_key)
            for clause in checks:
                row = session.scalar(select(JobRecord).where(clause))
                if row is not None:
                    return _row_dict(row)
        return None

    def get_job(self, job_id: str) -> dict | None:
        with self.session() as session:
            row = session.scalar(select(JobRecord).where(JobRecord.job_id == job_id))
            return _row_dict(row) if row else None

    def upsert_job(self, fields: dict) -> dict:
        with self.session() as session:
            row = session.scalar(select(JobRecord).where(JobRecord.job_id == fields["job_id"]))
            if row is None:
                row = JobRecord(job_id=fields["job_id"], date_found=fields.get("date_found") or _now())
                session.add(row)
            for key, value in fields.items():
                if key in {"score_json", "analysis_json", "skill_match_json", "comparison_json", "unknown_questions"}:
                    value = _dump(value)
                if hasattr(row, key) and key != "id":
                    setattr(row, key, value)
            session.commit()
            session.refresh(row)
            return _row_dict(row)

    def update_job(self, job_id: str, **fields: object) -> dict | None:
        with self.session() as session:
            row = session.scalar(select(JobRecord).where(JobRecord.job_id == job_id))
            if row is None:
                return None
            for key, value in fields.items():
                if key in {"score_json", "analysis_json", "skill_match_json", "comparison_json", "unknown_questions"}:
                    value = _dump(value)
                if hasattr(row, key) and key != "id":
                    setattr(row, key, value)
            session.commit()
            session.refresh(row)
            return _row_dict(row)

    def list_jobs(self) -> list[dict]:
        with self.session() as session:
            rows = session.scalars(select(JobRecord).order_by(JobRecord.id.desc())).all()
            return [_row_dict(row) for row in rows]

    def count_applied_on(self, day: str) -> int:
        with self.session() as session:
            rows = session.scalars(
                select(JobRecord).where(JobRecord.application_status.in_(APPLIED_STATUSES))
            ).all()
            return sum(1 for row in rows if (row.date_applied or "").startswith(day))

    def find_resume_version(self, job_id: str, jd_hash: str, master_version: str) -> dict | None:
        with self.session() as session:
            row = session.scalar(
                select(ResumeVersionRecord).where(
                    ResumeVersionRecord.job_id == job_id,
                    ResumeVersionRecord.jd_hash == jd_hash,
                    ResumeVersionRecord.master_resume_version == master_version,
                )
            )
            return _row_dict(row) if row else None

    def add_resume_version(self, fields: dict) -> dict:
        existing = self.find_resume_version(
            fields["job_id"], fields["jd_hash"], fields["master_resume_version"]
        )
        with self.session() as session:
            if existing:
                row = session.get(ResumeVersionRecord, existing["id"])
                assert row is not None
            else:
                row = ResumeVersionRecord(job_id=fields["job_id"], created_at=fields.get("created_at") or _now())
                session.add(row)
            for key, value in fields.items():
                if key == "comparison_json":
                    value = _dump(value)
                if hasattr(row, key) and key != "id":
                    setattr(row, key, value)
            session.commit()
            session.refresh(row)
            return _row_dict(row)

    def stats(self, minimum: float = 70) -> dict:
        jobs = self.list_jobs()
        scores = [job["match_score"] for job in jobs if job["match_score"] is not None]
        rejected = {"rejected_score", "rejected_salary", "rejected_experience", "rejected_location", "skipped"}

        def count(predicate) -> int:
            return sum(1 for job in jobs if predicate(job))

        return {
            "jobs_found": len(jobs),
            "qualified": count(
                lambda job: job["match_score"] is not None
                and job["match_score"] >= minimum
                and not str(job["application_status"]).startswith("rejected")
            ),
            "applications": count(lambda job: job["application_status"] in {"successful", "applied", "failed"}),
            "successful": count(lambda job: job["application_status"] == "successful"),
            "failed": count(lambda job: job["application_status"] == "failed"),
            "skipped": count(lambda job: job["application_status"] in rejected),
            "pending_approval": count(lambda job: job["application_status"] == "pending_approval"),
            "average_match_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        }

    def average(self) -> float:
        with self.session() as session:
            value = session.scalar(select(func.avg(JobRecord.match_score)))
            return float(value or 0)
