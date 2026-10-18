"""Streamlit view of tracked jobs, scores, and resume comparisons."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from src.database.repository import Repository
from src.utils.config import load_config

ROOT = Path(__file__).resolve().parents[1]


def _load_json(value: str | None) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _passes(job: dict, filters: dict) -> bool:
    if filters["location"] != "All" and filters["location"].lower() not in (job.get("location") or "").lower():
        return False
    if filters["status"] != "All" and job.get("application_status") != filters["status"]:
        return False
    if filters["role"] and filters["role"].lower() not in (job.get("job_title") or "").lower():
        return False
    if filters["salary"] and filters["salary"].lower() not in (job.get("salary") or "").lower():
        return False
    score = job.get("match_score")
    if score is None or score < filters["min_score"]:
        return False
    found = job.get("date_found") or ""
    if filters["start"] and found[:10] < filters["start"]:
        return False
    if filters["end"] and found[:10] > filters["end"]:
        return False
    return True


def main() -> None:
    st.set_page_config(page_title="Naukri job agent", layout="wide")
    config = load_config(ROOT)
    config.ensure_dirs()
    repo = Repository(config.database)
    stats = repo.stats(config.minimum_match_score)
    jobs = repo.list_jobs()

    st.title("Naukri job agent")
    st.caption("Master resume stays unchanged. Tailored files live in resume/generated.")

    columns = st.columns(7)
    columns[0].metric("Jobs found", stats["jobs_found"])
    columns[1].metric("Qualified", stats["qualified"])
    columns[2].metric("Applications", stats["applications"])
    columns[3].metric("Successful", stats["successful"])
    columns[4].metric("Failed", stats["failed"])
    columns[5].metric("Skipped", stats["skipped"])
    columns[6].metric("Average match", f"{stats['average_match_score']}%")

    st.caption(f"Waiting for approval: {stats['pending_approval']}")

    locations = ["All", *sorted({job["location"] for job in jobs if job.get("location")})]
    statuses = ["All", *sorted({job["application_status"] for job in jobs if job.get("application_status")})]
    with st.sidebar:
        st.header("Filters")
        location = st.selectbox("Location", locations)
        status = st.selectbox("Application status", statuses)
        role = st.text_input("Role contains")
        salary = st.text_input("Salary contains")
        min_score = st.slider("Minimum job match score", 0, 100, 0)
        start = st.text_input("Found on or after (YYYY-MM-DD)")
        end = st.text_input("Found on or before (YYYY-MM-DD)")

    filters = {
        "location": location,
        "status": status,
        "role": role.strip(),
        "salary": salary.strip(),
        "min_score": min_score,
        "start": start.strip(),
        "end": end.strip(),
    }
    visible = [job for job in jobs if _passes(job, filters)]
    st.subheader(f"Applications ({len(visible)})")
    st.dataframe(
        [
            {
                "Company": job.get("company"),
                "Role": job.get("job_title"),
                "Location": job.get("location"),
                "Salary": job.get("salary"),
                "Job match": job.get("match_score"),
                "Resume match": job.get("resume_match_score"),
                "Applied": job.get("date_applied") or "",
                "Status": job.get("application_status"),
                "Generated resume": job.get("generated_resume_path") or "",
                "Job URL": job.get("job_url") or "",
            }
            for job in visible
        ],
        use_container_width=True,
        hide_index=True,
    )

    if not visible:
        st.info("No jobs match these filters yet. Run a search or import a sample JD.")
        return

    labels = [f"{job['company']} — {job['job_title']} ({job['job_id']})" for job in visible]
    selected = st.selectbox("Resume comparison", labels)
    job = visible[labels.index(selected)]
    comparison = _load_json(job.get("comparison_json"))
    scores = _load_json(job.get("score_json"))

    st.subheader("Master resume vs tailored resume")
    left, right = st.columns(2)
    left.text_area("Master summary", comparison.get("summary_before") or "", height=160, disabled=True)
    right.text_area("Tailored summary", comparison.get("summary_after") or "", height=160, disabled=True)

    skill_rows = comparison.get("jd_skills") or []
    if skill_rows:
        st.markdown("**JD skill status**")
        st.dataframe(
            [{"JD skill": row.get("skill"), "Resume status": row.get("status")} for row in skill_rows],
            use_container_width=True,
            hide_index=True,
        )
    missing = comparison.get("missing_skills") or []
    if missing:
        st.warning("Missing skills (not added to the resume): " + ", ".join(missing))

    skill_left, skill_right = st.columns(2)
    skill_left.markdown("**Original skill order**")
    skill_left.write(", ".join(comparison.get("skills_before") or []) or "—")
    skill_right.markdown("**Reordered skills**")
    skill_right.write(", ".join(comparison.get("skills_after") or []) or "—")

    st.markdown("**Relevant experience**")
    for item in comparison.get("experience_highlights") or []:
        st.markdown(f"**{item.get('role')} — {item.get('company')}** ({item.get('duration')})")
        for bullet in item.get("bullets") or []:
            st.write(f"- {bullet}")

    keywords = comparison.get("ats_keywords") or []
    st.markdown("**ATS keywords that already appear in the tailored resume**")
    st.write(", ".join(keywords) if keywords else "None recorded.")

    if scores:
        st.markdown("**Job score breakdown**")
        st.json(
            {
                "overall": scores.get("total"),
                "role": scores.get("role_relevance"),
                "skills": scores.get("skills_match"),
                "experience": scores.get("experience_match"),
                "salary": scores.get("salary"),
                "location": scores.get("location"),
                "cloud_ai": scores.get("cloud_ai"),
                "other": scores.get("other"),
                "reason": scores.get("reject_reason") or job.get("skip_reason") or "",
            }
        )

    resume_path = job.get("generated_resume_path") or ""
    if resume_path and Path(resume_path).exists():
        st.download_button(
            "Download tailored resume",
            data=Path(resume_path).read_bytes(),
            file_name=Path(resume_path).name,
        )
    if job.get("job_url"):
        st.link_button("Open job", job["job_url"])


if __name__ == "__main__":
    main()
