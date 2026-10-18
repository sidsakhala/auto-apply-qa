"""Job match score. The published number is always computed from the weights."""

from __future__ import annotations

from dataclasses import dataclass

from src.jobs.experience import ExperienceRange, experience_component
from src.jobs.models import JDAnalysis
from src.jobs.relevance import is_ai_related_job_title, role_relevance
from src.resume.matcher import match_skills
from src.resume.models import Resume, ResumeScores, SkillMatch
from src.utils.location import evaluate_location
from src.utils.salary import SalaryInfo, salary_component
from src.utils.skills import CLOUD_AI_SKILLS, canonicalize

DEFAULT_WEIGHTS = {
    "role_relevance": 25.0,
    "skills_match": 25.0,
    "experience_match": 15.0,
    "salary": 15.0,
    "location": 10.0,
    "cloud_ai": 5.0,
    "other": 5.0,
}


@dataclass
class JobScore:
    total: float
    role_relevance: float
    skills_match: float
    experience_match: float
    salary: float
    location: float
    cloud_ai: float
    other: float
    hard_reject: bool = False
    reject_status: str = ""
    reject_reason: str = ""
    salary_band: str = ""
    location_reason: str = ""
    experience_within_limit: bool = False
    ai_related_title: bool = False

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "role_relevance": self.role_relevance,
            "skills_match": self.skills_match,
            "experience_match": self.experience_match,
            "salary": self.salary,
            "location": self.location,
            "cloud_ai": self.cloud_ai,
            "other": self.other,
            "hard_reject": self.hard_reject,
            "reject_status": self.reject_status,
            "reject_reason": self.reject_reason,
            "salary_band": self.salary_band,
            "location_reason": self.location_reason,
            "experience_within_limit": self.experience_within_limit,
            "ai_related_title": self.ai_related_title,
        }


@dataclass
class Decision:
    status: str
    reason: str
    proceed_to_resume: bool
    proceed_to_apply: bool


def score_job(
    analysis: JDAnalysis,
    skill_match: SkillMatch,
    resume: Resume,
    profile: dict,
    *,
    weights: dict[str, float] | None = None,
    resume_scores: ResumeScores | None = None,
    role_score: float | None = None,
) -> JobScore:
    weights = weights or DEFAULT_WEIGHTS
    candidate = profile.get("candidate") or {}
    targets = list(profile.get("target_roles") or [])
    if role_score is None:
        role, _signals = role_relevance(
            analysis.job_title,
            " ".join([analysis.job_title, *analysis.ai_signals, *analysis.keywords, *analysis.required_skills]),
            targets,
        )
    else:
        role = role_score

    def adjusted(skills: list[str]) -> float | None:
        if not skills:
            return None
        statuses = {pair["skill"].lower(): pair["status"] for pair in skill_match.pairs}
        total = 0.0
        for skill in skills:
            status = statuses.get(skill.lower())
            if status == "MATCH":
                total += 1.0
            elif status == "PARTIAL":
                total += 0.5
        return 100.0 * total / len(skills)

    required_score = adjusted(analysis.required_skills)
    preferred_score = adjusted(analysis.preferred_skills)
    if required_score is None and preferred_score is None:
        skills = 70.0
    elif preferred_score is None:
        skills = required_score or 0.0
    elif required_score is None:
        skills = preferred_score or 0.0
    else:
        skills = 0.8 * required_score + 0.2 * preferred_score

    experience = experience_component(
        ExperienceRange(
            text=analysis.experience_required,
            minimum=analysis.experience_min,
            maximum=analysis.experience_max,
        ),
        candidate_min=float(candidate.get("experience_min_years", 2)),
        candidate_max=float(candidate.get("experience_max_years", 8)),
        maximum_years=float(candidate.get("maximum_job_experience_years", 8)),
        minimum_years=float(candidate.get("minimum_job_experience_years", 2)),
    )
    salary_info = SalaryInfo(
        text=analysis.salary,
        min_lpa=analysis.salary_min_lpa,
        max_lpa=analysis.salary_max_lpa,
        disclosed=analysis.salary_disclosed,
    )
    salary = salary_component(
        salary_info,
        current_ctc_lpa=float(candidate.get("current_ctc_lpa", 6)),
        minimum_expected_lpa=float(candidate.get("minimum_expected_ctc_lpa", 10)),
    )
    location = evaluate_location(
        analysis.location,
        list(candidate.get("preferred_locations") or []),
        role_relevance=role,
        consider_remote_or_hybrid=bool(candidate.get("consider_remote_or_hybrid", True)),
    )

    cloud_listed = [
        skill
        for skill in [*analysis.required_skills, *analysis.preferred_skills]
        if canonicalize(skill) in CLOUD_AI_SKILLS
    ]
    cloud_value = adjusted(cloud_listed)
    cloud = 70.0 if cloud_value is None else cloud_value

    if analysis.education_requirements and not resume.education:
        other = 40.0
    elif analysis.education_requirements:
        other = 90.0
    else:
        other = 80.0

    components = {
        "role_relevance": role,
        "skills_match": skills,
        "experience_match": experience[0],
        "salary": salary[0],
        "location": location.score,
        "cloud_ai": cloud,
        "other": other,
    }
    total = sum(components[name] * (weights[name] / 100.0) for name in weights)
    hard = False
    status = ""
    reason = ""
    if salary[1]:
        hard, status, reason = True, "rejected_salary", "Salary is below the current CTC"
    elif experience[1]:
        hard, status, reason = True, "rejected_experience", experience[2]
    elif not location.allowed:
        hard, status, reason = True, "rejected_location", location.reason

    _ = resume_scores  # resume scores are reported separately and do not override this formula
    ai_title = is_ai_related_job_title(analysis.job_title, targets)
    return JobScore(
        total=round(total, 1),
        role_relevance=round(role, 1),
        skills_match=round(skills, 1),
        experience_match=round(experience[0], 1),
        salary=round(salary[0], 1),
        location=round(location.score, 1),
        cloud_ai=round(cloud, 1),
        other=round(other, 1),
        hard_reject=hard,
        reject_status=status,
        reject_reason=reason,
        salary_band=salary[2],
        location_reason=location.reason,
        experience_within_limit=not experience[1] and experience[2] != "experience_undisclosed",
        ai_related_title=ai_title,
    )


def decide(job_score: JobScore, *, minimum: float, minimum_role: float = 55.0) -> Decision:
    if job_score.hard_reject:
        return Decision(
            status=job_score.reject_status or "rejected",
            reason=job_score.reject_reason,
            proceed_to_resume=False,
            proceed_to_apply=False,
        )
    if not job_score.ai_related_title:
        return Decision(
            status="rejected_role",
            reason="Job title is not an Automation / QA / SDET role",
            proceed_to_resume=False,
            proceed_to_apply=False,
        )
    if job_score.role_relevance + 1e-9 < minimum_role:
        return Decision(
            status="rejected_role",
            reason=f"Role relevance {job_score.role_relevance} is below {minimum_role}",
            proceed_to_resume=False,
            proceed_to_apply=False,
        )
    if job_score.experience_within_limit or job_score.total + 1e-9 >= minimum:
        return Decision(
            status="qualified",
            reason="",
            proceed_to_resume=True,
            proceed_to_apply=True,
        )
    return Decision(
        status="rejected_score",
        reason=f"Match score {job_score.total} is below {minimum}",
        proceed_to_resume=False,
        proceed_to_apply=False,
    )


def evaluate_job(
    resume: Resume,
    analysis: JDAnalysis,
    profile: dict,
    *,
    weights: dict[str, float] | None = None,
    minimum: float = 70,
) -> tuple[SkillMatch, ResumeScores, JobScore, Decision]:
    from src.resume.matcher import score_resume

    targets = list(profile.get("target_roles") or [])
    role, _ = role_relevance(
        analysis.job_title,
        " ".join([*analysis.ai_signals, *analysis.required_skills, *analysis.keywords]),
        targets,
    )
    skill_match = match_skills(resume, analysis, profile)
    resume_scores = score_resume(resume, analysis, skill_match, role_score=role)
    job_score = score_job(
        analysis,
        skill_match,
        resume,
        profile,
        weights=weights,
        resume_scores=resume_scores,
        role_score=role,
    )
    candidate = profile.get("candidate") or {}
    minimum_role = float(candidate.get("minimum_role_relevance", 55))
    return skill_match, resume_scores, job_score, decide(
        job_score, minimum=minimum, minimum_role=minimum_role
    )
