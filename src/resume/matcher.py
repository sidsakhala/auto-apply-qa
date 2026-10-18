"""Compare master-resume facts with a job description.

Missing skills stay missing. Nothing in this module invents a skill.
"""

from __future__ import annotations

from src.jobs.models import JDAnalysis
from src.resume.models import Resume, ResumeScores, SkillMatch
from src.utils.skills import AI_EVIDENCE_TERMS, CLOUD_AI_SKILLS, canonicalize, find_skills, is_partial
from src.utils.text import content_words, jaccard


def profile_skills(profile: dict | None) -> list[str]:
    candidate = (profile or {}).get("candidate") or {}
    raw = candidate.get("skills") or []
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def skill_corpus(resume: Resume, profile: dict | None = None) -> set[str]:
    """Canonical skills that the resume or the candidate profile actually supports."""
    chunks = [resume.raw_text, resume.summary, " ".join(resume.skills), " ".join(resume.certifications)]
    for item in resume.experience:
        chunks.extend(item.bullets())
        chunks.append(" ".join(item.technologies))
    for project in resume.projects:
        chunks.extend(project.bullets)
        chunks.append(" ".join(project.technologies))
    found = set(find_skills("\n".join(chunks)))
    for skill in resume.skills:
        found.add(canonicalize(skill))
    for skill in profile_skills(profile):
        found.add(canonicalize(skill))
    return {skill for skill in found if skill}


def match_skills(resume: Resume, analysis: JDAnalysis, profile: dict | None = None) -> SkillMatch:
    corpus = skill_corpus(resume, profile)
    seen: set[str] = set()
    matching: list[str] = []
    partial: list[str] = []
    missing: list[str] = []
    pairs: list[dict] = []

    ordered = [*analysis.required_skills, *analysis.preferred_skills]
    for skill in ordered:
        key = canonicalize(skill).lower()
        if not skill.strip() or key in seen:
            continue
        seen.add(key)
        canonical = canonicalize(skill)
        if canonical in corpus:
            status = "MATCH"
            matching.append(skill)
        elif is_partial(skill, corpus):
            status = "PARTIAL"
            partial.append(skill)
        else:
            status = "MISSING"
            missing.append(skill)
        pairs.append({"skill": skill, "status": status, "canonical": canonical})

    return SkillMatch(
        matching_skills=matching,
        partial_match=partial,
        missing_skills=missing,
        pairs=pairs,
    )


def _coverage(skills: list[str], corpus: set[str]) -> float | None:
    if not skills:
        return None
    score = 0.0
    for skill in skills:
        canonical = canonicalize(skill)
        if canonical in corpus:
            score += 1.0
        elif is_partial(skill, corpus):
            score += 0.5
    return 100.0 * score / len(skills)


def score_resume(
    resume: Resume,
    analysis: JDAnalysis,
    skill_match: SkillMatch,
    *,
    role_score: float,
) -> ResumeScores:
    corpus = set()
    for pair in skill_match.pairs:
        if pair["status"] == "MATCH":
            corpus.add(pair["canonical"])
    # Coverage uses the real corpus, not only JD pairs.
    full_corpus = {pair["canonical"] for pair in skill_match.pairs if pair["status"] == "MATCH"}
    # Recompute from the resume so partial/missing math uses the same rules.
    from_resume = skill_corpus(resume)
    required = _coverage(analysis.required_skills, from_resume)
    preferred = _coverage(analysis.preferred_skills, from_resume)
    if required is None and preferred is None:
        skills_score = 70.0
    elif preferred is None:
        skills_score = required or 0.0
    elif required is None:
        skills_score = preferred or 0.0
    else:
        skills_score = 0.8 * required + 0.2 * preferred

    responsibilities = analysis.responsibilities or analysis.keywords
    if responsibilities:
        resume_words = content_words(resume.raw_text)
        overlaps = []
        for line in responsibilities:
            overlaps.append(jaccard(content_words(line), resume_words))
        experience_score = 100.0 * (sum(overlaps) / len(overlaps))
        # A single shared stack still deserves credit beyond raw token overlap.
        experience_score = min(100.0, experience_score * 1.6 + skills_score * 0.25)
    else:
        experience_score = skills_score

    cloud_skills = [
        skill
        for skill in [*analysis.required_skills, *analysis.preferred_skills]
        if canonicalize(skill) in CLOUD_AI_SKILLS
    ]
    cloud = _coverage(cloud_skills, from_resume)
    cloud_score = 70.0 if cloud is None else cloud

    overall = (
        0.40 * skills_score
        + 0.25 * experience_score
        + 0.20 * role_score
        + 0.15 * cloud_score
    )
    return ResumeScores(
        overall=round(overall, 1),
        skills=round(skills_score, 1),
        experience=round(experience_score, 1),
        role=round(role_score, 1),
        cloud_ai=round(cloud_score, 1),
    )


def evidence_terms(resume: Resume, experience_index: int) -> set[str]:
    if experience_index < 0 or experience_index >= len(resume.experience):
        return set()
    item = resume.experience[experience_index]
    text = " ".join([*item.bullets(), *item.technologies, item.role])
    return set(find_skills(text)) | (set(find_skills(text)) & AI_EVIDENCE_TERMS)
