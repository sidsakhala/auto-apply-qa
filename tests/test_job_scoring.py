"""JD parsing, salary, experience, location, and job scoring for QA roles."""

from __future__ import annotations

from src.jobs.experience import experience_component, parse_experience, strictest_experience
from src.jobs.jd_analyzer import analyze_jd
from src.jobs.matcher import evaluate_job
from src.jobs.parser import posting_from_dict
from src.jobs.relevance import is_ai_related_job_title, role_relevance
from src.jobs.search import build_search_queries
from src.resume.parser import parse_resume
from src.utils.location import evaluate_location
from src.utils.salary import parse_salary, salary_component
from tests.support import SAMPLE_JD, make_config


def _salary(text: str):
    info = parse_salary(text)
    return salary_component(info, current_ctc_lpa=6, minimum_expected_lpa=8)


def test_salary_bands():
    high, reject, band = _salary("₹12–18 LPA")
    assert band == "high" and not reject and high == 100
    below_score, below_reject, below_band = _salary("₹4–5 LPA")
    assert below_reject and below_band == "below_current" and below_score == 0
    undisclosed_score, undisclosed_reject, undisclosed_band = _salary("Not disclosed")
    assert not undisclosed_reject and undisclosed_band == "not_disclosed" and undisclosed_score == 60


def test_experience_ranges_qa_band():
    qa = dict(candidate_min=2, candidate_max=8, maximum_years=8, minimum_years=2)
    in_band = parse_experience("2-5 years")
    score, reject, _ = experience_component(in_band, **qa)
    assert not reject and score >= 85
    top = parse_experience("6-8 years")
    assert not experience_component(top, **qa)[1]
    too_high = parse_experience("9-14 years")
    assert experience_component(too_high, **qa)[1]
    assert experience_component(too_high, **qa)[2] == "experience_too_high"
    capped = dict(candidate_min=3, candidate_max=3, maximum_years=3, minimum_years=3)
    assert not experience_component(parse_experience("3-5 years"), **capped)[1]
    assert not experience_component(parse_experience("3-8 years"), **capped)[1]
    assert experience_component(parse_experience("4-7 years"), **capped)[2] == "experience_too_high"
    assert experience_component(parse_experience("5-10 years"), **capped)[2] == "experience_too_high"
    too_low = parse_experience("0-1 years")
    assert experience_component(too_low, **qa)[2] == "experience_too_low"
    url_only = strictest_experience(
        "",
        "Automation with Selenium.",
        "https://www.naukri.com/job-listings-sdet-company-hyderabad-3-to-7-years-100000001",
    )
    assert (url_only.minimum, url_only.maximum) == (3, 7)


def test_location_priority():
    preferred = ["Pune", "Hyderabad", "Bangalore", "Bengaluru"]
    pune = evaluate_location("Pune", preferred, role_relevance=90, consider_remote_or_hybrid=True)
    assert pune.allowed
    mumbai = evaluate_location("Mumbai", preferred, role_relevance=95, consider_remote_or_hybrid=True)
    assert not mumbai.allowed


def test_qa_role_relevance_from_jd():
    roles = ["Automation Test Engineer", "SDET", "QA Engineer"]
    description = "Selenium, TestNG, API testing with Postman, CI/CD Jenkins, BDD Cucumber."
    score, signals = role_relevance("Software Engineer", description, roles)
    assert score >= 70
    assert "Selenium" in signals or "Test automation" in signals


def test_qa_job_title_detection():
    roles = ["Automation Test Engineer", "SDET", "QA Automation Engineer"]
    assert is_ai_related_job_title("QA Automation Engineer", roles)
    assert is_ai_related_job_title("SDET - Selenium", roles)
    assert is_ai_related_job_title("Automation Test Engineer", roles)
    assert is_ai_related_job_title("Full Stack .Net Developer", roles) is False


def test_developer_title_without_qa_jd_is_not_qualified(tmp_path):
    config = make_config(tmp_path)
    resume = parse_resume(config.master_resume)
    posting = posting_from_dict(
        {
            **SAMPLE_JD,
            "job_title": "Java Developer",
            "description": "Spring Boot microservices only. No testing scope.",
        }
    )
    _match, _scores, _job_score, decision = evaluate_job(
        resume, analyze_jd(posting), config.profile, weights=config.weights, minimum=70
    )
    assert decision.status == "rejected_role"


def test_primary_search_queries_come_first():
    profile = {"target_roles": ["QA Engineer", "Automation Test Engineer", "SDET"]}
    queries = build_search_queries(profile, limit=45)
    labels = [query.label for query in queries]
    assert labels[:3] == [
        "Automation Test Engineer Pune",
        "Automation Test Engineer Hyderabad",
        "Automation Test Engineer Bangalore",
    ]
    assert "SDET Pune" in labels
