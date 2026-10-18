"""Create a JD-tailored resume from the master resume without adding facts."""

from __future__ import annotations

import copy

from src.jobs.models import JDAnalysis
from src.llm.base import LLMProvider
from src.llm.prompts import TAILOR_SYSTEM, tailor_user_prompt
from src.resume.matcher import match_skills, profile_skills, skill_corpus
from src.resume.models import Experience, Resume, ResumeScores, SkillMatch
from src.resume.validator import validate_identity, validate_tailored
from src.utils.logger import get_logger
from src.utils.skills import AI_EVIDENCE_TERMS, canonicalize, find_skills
from src.utils.text import content_words, jaccard, split_sentences, unique_keep

logger = get_logger("tailor")

_AI_FAMILY = [
    "Generative AI",
    "Machine Learning",
    "LLM",
    "RAG",
    "NLP",
    "Vertex AI",
    "MLflow",
    "Prompt Engineering",
    "AI Agents",
    "PyTorch",
    "TensorFlow",
    "Hugging Face",
]


def _human_join(items: list[str]) -> str:
    values = unique_keep(items)
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return ", ".join(values[:-1]) + ", and " + values[-1]


def _display_skill(canonical_name: str, skills: list[str]) -> str | None:
    for skill in skills:
        if canonicalize(skill).lower() == canonical_name.lower():
            return skill
    return None


def reorder_skills(skills: list[str], analysis: JDAnalysis, skill_match: SkillMatch) -> list[str]:
    """Put JD-matching skills first. Every name still comes from the master list."""
    ordered: list[str] = []

    def take(jd_skills: list[str]) -> None:
        for skill in jd_skills:
            display = _display_skill(canonicalize(skill), skills)
            if display and display not in ordered and any(
                pair["skill"].lower() == skill.lower() and pair["status"] == "MATCH" for pair in skill_match.pairs
            ):
                ordered.append(display)

    take(analysis.required_skills)
    take(analysis.preferred_skills)
    if analysis.ai_signals:
        for skill in skills:
            if canonicalize(skill) in _AI_FAMILY and skill not in ordered:
                ordered.append(skill)
    for skill in skills:
        if skill not in ordered:
            ordered.append(skill)
    return ordered


def clarify_bullet(bullet: str, *, evidence: set[str], jd_text: str) -> str:
    """Light wording changes that stay inside the original role."""
    text = bullet.strip()
    if text.lower().startswith("worked on "):
        text = "Developed " + text[len("Worked on ") :]
    lower = text.lower()
    jd = jd_text.lower()
    ai_evidence = set(evidence) & AI_EVIDENCE_TERMS
    jd_is_ai_pipeline = any(token in jd for token in ("pipeline", "data processing", "generative", "llm", "rag"))
    bullet_is_pipeline = "pipeline" in lower or "data processing" in lower
    if ai_evidence and jd_is_ai_pipeline and bullet_is_pipeline and "supporting ai/ml" not in lower:
        text = text.rstrip(".") + " supporting AI/ML workflows."
    return text


def _bullet_score(bullet: str, analysis: JDAnalysis) -> int:
    haystack = bullet.lower()
    score = 0
    for skill in [*analysis.required_skills, *analysis.preferred_skills, *analysis.keywords]:
        if skill.lower() in haystack or canonicalize(skill).lower() in haystack:
            score += 3 if skill in analysis.required_skills else 1
    score += len(content_words(bullet) & content_words(" ".join(analysis.responsibilities)))
    return score


def _tailor_summary(resume: Resume, skill_match: SkillMatch, corpus: set[str]) -> str:
    genuine: list[str] = []
    for skill in skill_match.matching_skills:
        canonical = canonicalize(skill)
        if canonical in corpus and canonical not in genuine:
            genuine.append(canonical)
    ai_hits = [skill for skill in genuine if skill in AI_EVIDENCE_TERMS or skill in _AI_FAMILY]
    sentences = split_sentences(resume.summary)
    if len(ai_hits) < 2:
        return resume.summary
    opening = f"AI-focused engineer with experience in {_human_join(genuine[:8])}."
    opening_words = content_words(opening)
    kept = [sentence for sentence in sentences if jaccard(content_words(sentence), opening_words) < 0.55]
    if kept:
        return opening + " " + " ".join(kept)
    return opening


def _apply_bullet_order(
    master: Resume,
    analysis: JDAnalysis,
    jd_text: str,
    rewrites: dict[tuple[str, str], str] | None = None,
) -> list[Experience]:
    rewrites = rewrites or {}
    tailored: list[Experience] = []
    for item in master.experience:
        evidence = set(find_skills(" ".join([*item.bullets(), *item.technologies, item.role])))
        indexed = list(enumerate(item.bullets()))
        indexed.sort(key=lambda pair: (-_bullet_score(pair[1], analysis), pair[0]))
        responsibilities: list[str] = []
        achievements: list[str] = []
        for _, bullet in indexed:
            proposed = rewrites.get((item.company, bullet), bullet)
            if proposed == bullet:
                proposed = clarify_bullet(bullet, evidence=evidence, jd_text=jd_text)
            # Achievements stay in the achievement list when they began there, but
            # relevance order is preserved by emitting responsibilities first only
            # after the combined sort. The generator prints both lists in order,
            # so store the sorted sequence entirely in responsibilities and keep
            # achievements empty to avoid printing twice. Identity of the facts
            # is checked against the original union.
            responsibilities.append(proposed)
        tailored.append(
            Experience(
                company=item.company,
                role=item.role,
                duration=item.duration,
                responsibilities=responsibilities,
                achievements=achievements,
                technologies=list(item.technologies),
            )
        )
    return tailored


def _heuristic(
    resume: Resume,
    analysis: JDAnalysis,
    skill_match: SkillMatch,
    jd_text: str,
    profile: dict | None,
) -> tuple[str, list[Experience], list[str]]:
    corpus = skill_corpus(resume, profile)
    summary = _tailor_summary(resume, skill_match, corpus)
    experience = _apply_bullet_order(resume, analysis, jd_text)
    skills = reorder_skills([*resume.skills, *_profile_only(resume, profile)], analysis, skill_match)
    return summary, experience, skills


def _profile_only(resume: Resume, profile: dict | None) -> list[str]:
    existing = {canonicalize(skill) for skill in resume.skills}
    return [skill for skill in profile_skills(profile) if canonicalize(skill) not in existing]


def _llm_rewrites(resume: Resume, analysis: JDAnalysis, llm: LLMProvider) -> tuple[str, dict[tuple[str, str], str], list[str]] | None:
    facts = []
    for item in resume.experience:
        facts.append(f"{item.role} | {item.company} | {item.duration}")
        for bullet in item.bullets():
            facts.append(f"- {bullet}")
        if item.technologies:
            facts.append("Technologies: " + ", ".join(item.technologies))
    facts.append("Summary: " + resume.summary)
    facts.append("Skills: " + ", ".join(resume.skills))
    jd_summary = (
        f"{analysis.job_title} at {analysis.company} ({analysis.location})\n"
        f"Required: {', '.join(analysis.required_skills)}\n"
        f"Preferred: {', '.join(analysis.preferred_skills)}\n"
        f"Responsibilities: {'; '.join(analysis.responsibilities)}"
    )
    try:
        raw = llm.complete_json(
            system=TAILOR_SYSTEM,
            user=tailor_user_prompt(
                resume_facts="\n".join(facts),
                jd_summary=jd_summary,
                allowed_skills=resume.skills,
            ),
        )
    except Exception as exc:
        logger.warning("LLM resume tailoring failed (%s). Using the deterministic tailor.", exc)
        return None
    summary = str(raw.get("summary") or "").strip()
    rewrites: dict[tuple[str, str], str] = {}
    for item in raw.get("bullets") or []:
        if not isinstance(item, dict):
            continue
        company = str(item.get("company") or "")
        original = str(item.get("original") or "")
        rewritten = str(item.get("rewritten") or "")
        if company and original and rewritten:
            rewrites[(company, original)] = rewritten
    order = [str(skill) for skill in raw.get("skills_order") or [] if str(skill).strip()]
    return summary, rewrites, order


def _safe_summary_and_experience(
    resume: Resume,
    analysis: JDAnalysis,
    skill_match: SkillMatch,
    jd_text: str,
    profile: dict | None,
    llm: LLMProvider | None,
) -> tuple[str, list[Experience], list[str]]:
    summary, experience, skills = _heuristic(resume, analysis, skill_match, jd_text, profile)
    extra = _profile_only(resume, profile)
    if llm is not None and llm.available:
        proposed = _llm_rewrites(resume, analysis, llm)
        if proposed:
            llm_summary, rewrites, llm_order = proposed
            candidate_summary = llm_summary or summary
            candidate_experience = _apply_bullet_order(resume, analysis, jd_text, rewrites)
            candidate_skills = _merge_skill_order(resume.skills, extra, llm_order, analysis, skill_match)
            errors = validate_tailored(
                resume,
                candidate_summary,
                candidate_experience,
                candidate_skills,
                resume.projects,
                profile=profile,
            ).errors
            errors.extend(validate_identity(resume, resume.certifications, resume.education))
            if not errors:
                return candidate_summary, candidate_experience, candidate_skills
            logger.info("Discarded LLM resume edits that failed validation: %s", "; ".join(errors))
    return summary, experience, skills


def _merge_skill_order(
    master_skills: list[str],
    extra: list[str],
    requested: list[str],
    analysis: JDAnalysis,
    skill_match: SkillMatch,
) -> list[str]:
    allowed = {canonicalize(skill): skill for skill in [*master_skills, *extra]}
    ordered: list[str] = []
    for skill in requested:
        display = allowed.get(canonicalize(skill))
        if display and display not in ordered:
            ordered.append(display)
    fallback = reorder_skills([*master_skills, *extra], analysis, skill_match)
    for skill in fallback:
        if skill not in ordered:
            ordered.append(skill)
    return ordered


def _ats_keywords(analysis: JDAnalysis, summary: str, skills: list[str], experience: list[Experience]) -> list[str]:
    blob = " ".join([summary, " ".join(skills), " ".join(bullet for item in experience for bullet in item.bullets())]).lower()
    found = []
    for keyword in analysis.keywords:
        if keyword.lower() in blob:
            found.append(keyword)
    return found


def tailor_resume(
    resume: Resume,
    analysis: JDAnalysis,
    *,
    profile: dict | None = None,
    llm: LLMProvider | None = None,
    jd_text: str = "",
    role_score: float = 0.0,
    resume_scores: ResumeScores | None = None,
    skill_match: SkillMatch | None = None,
) -> dict:
    """Return tailored sections plus the comparison payload.

    The master ``Resume`` object is not mutated.
    """
    original = copy.deepcopy(resume)
    skill_match = skill_match or match_skills(original, analysis, profile)
    summary, experience, skills = _safe_summary_and_experience(
        original,
        analysis,
        skill_match,
        jd_text or " ".join(analysis.responsibilities),
        profile,
        llm,
    )
    projects = copy.deepcopy(original.projects)
    errors = validate_tailored(
        original, summary, experience, skills, projects, profile=profile
    ).errors
    errors.extend(validate_identity(original, original.certifications, original.education))
    if errors:
        # Last resort: original wording, reordered skills and bullets only.
        logger.warning("Heuristic tailor failed validation (%s). Falling back to reordering only.", "; ".join(errors))
        summary = original.summary
        experience = _apply_bullet_order(original, analysis, "")
        for item in experience:
            source = next(job for job in original.experience if job.company == item.company and job.role == item.role)
            ranked = sorted(
                source.bullets(),
                key=lambda bullet: (-_bullet_score(bullet, analysis), source.bullets().index(bullet)),
            )
            item.responsibilities = ranked
            item.achievements = []
        skills = reorder_skills([*original.skills, *_profile_only(original, profile)], analysis, skill_match)
        errors = validate_tailored(original, summary, experience, skills, projects, profile=profile).errors
        if errors:
            from src.exceptions import ResumeIntegrityError

            raise ResumeIntegrityError("Refusing to generate a resume that fails factual checks: " + "; ".join(errors))

    if resume_scores is None:
        from src.resume.matcher import score_resume

        resume_scores = score_resume(original, analysis, skill_match, role_score=role_score)

    comparison = {
        "jd_skills": [{"skill": pair["skill"], "status": pair["status"]} for pair in skill_match.pairs],
        "matching_skills": list(skill_match.matching_skills),
        "partial_match": list(skill_match.partial_match),
        "missing_skills": list(skill_match.missing_skills),
        "summary_before": original.summary,
        "summary_after": summary,
        "skills_before": list(original.skills),
        "skills_after": list(skills),
        "experience_highlights": [
            {
                "company": item.company,
                "role": item.role,
                "duration": item.duration,
                "bullets": list(item.bullets()),
            }
            for item in experience
        ],
        "ats_keywords": _ats_keywords(analysis, summary, skills, experience),
        "resume_scores": resume_scores.to_dict(),
    }
    return {
        "name": original.name,
        "summary": summary,
        "experience": experience,
        "projects": projects,
        "skills": skills,
        "certifications": list(original.certifications),
        "education": copy.deepcopy(original.education),
        "comparison": comparison,
        "skill_match": skill_match,
        "resume_scores": resume_scores,
    }
