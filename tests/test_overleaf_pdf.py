from pathlib import Path

from src.resume.models import Experience, Resume
from src.resume.overleaf_pdf import (
    clone_command,
    escape_prose_ampersands,
    project_id_from_url,
    render_tailored_tex,
)

SOURCE = r"""
\documentclass{article}
\begin{document}
Test Candidate
Data Engineer with experience in Python, SQL, cloud technologies, and building data processing pipelines.
\section{Skills}
Python, SQL, Docker, Vertex AI
\section{Experience}
\item Worked on Python-based data processing pipelines.
\item Built RAG workflows on Vertex AI for internal search.
\end{document}
"""


def _resume() -> Resume:
    return Resume(
        name="Test Candidate",
        summary=(
            "Data Engineer with experience in Python, SQL, cloud technologies, "
            "and building data processing pipelines."
        ),
        skills=["Python", "SQL", "Docker", "Vertex AI"],
        experience=[
            Experience(
                company="Example Analytics",
                role="Data Engineer",
                duration="Jan 2024 – Present",
                responsibilities=[
                    "Worked on Python-based data processing pipelines.",
                    "Built RAG workflows on Vertex AI for internal search.",
                ],
            )
        ],
    )


def test_key_skills_come_from_the_jd_only_when_the_resume_already_has_them():
    source = r"""
\section{TECHNICAL SKILLS}
\begin{itemize}[leftmargin=0in,label={}]
\small{
\item \textbf{Programming \& Query Languages:} SQL, Python
\item \textbf{AI \& LLM Engineering:} RAG, LangChain
\item \textbf{Cloud Platforms:} AWS, Microsoft Azure (ADF, ADLS Gen2), Google Cloud Platform (GCP, Vertex AI)
\item \textbf{DevOps \& Tools:} Docker, Azure DevOps
}
\end{itemize}
\section{EXPERIENCE}
"""
    rendered = render_tailored_tex(
        source,
        Resume(name="Test Candidate", summary=""),
        {"summary": "", "skills": [], "experience": [], "jd_skills": ["LangChain", "Kubernetes", "Python", "RAG", "Azure", "GCP"]},
    )
    skills = rendered.split(r"\section{TECHNICAL SKILLS}", 1)[1]
    assert r"\textbf{Programming \& Query Languages:} Python, SQL" in skills
    assert r"\textbf{AI \& LLM Engineering:} LangChain, RAG" in skills
    assert r"\textbf{Cloud Platforms:} Microsoft Azure (ADF, ADLS Gen2), Google Cloud Platform (GCP, Vertex AI), AWS" in skills
    assert r"\textbf{DevOps \& Tools:} Docker, Azure DevOps" in skills
    assert "Key skills" not in skills
    assert "Kubernetes" not in skills


def test_prose_ampersands_are_escaped_without_touching_tabular_rows():
    source = "\\item \\textbf{Programming & Query Languages:}\n    \\textbf{#1} & {x}\\\\\n"
    rendered = escape_prose_ampersands(source)
    assert r"Programming \& Query Languages" in rendered
    assert r"\textbf{#1} & {x}\\" in rendered


def test_overleaf_url_and_clone_keep_the_token_out_of_the_remote():
    assert project_id_from_url("https://www.overleaf.com/project/6a30ef64681e0646543a37ab") == (
        "6a30ef64681e0646543a37ab"
    )
    command = clone_command("6a30ef64681e0646543a37ab", "secret-token", Path("resume/overleaf"))
    assert "push" not in command
    assert "https://git.overleaf.com/6a30ef64681e0646543a37ab" in command
    assert not any("secret-token@" in part for part in command)
    assert any(part.startswith("http.extraheader=Authorization: Basic ") for part in command)


def test_render_reorders_existing_overleaf_text_only():
    resume = _resume()
    tailored = {
        "summary": "AI-focused engineer with experience in Python, SQL, Docker, and Vertex AI.",
        "skills": ["Vertex AI", "Docker", "Python", "SQL", "LangChain"],
        "experience": [
            Experience(
                company="Example Analytics",
                role="Data Engineer",
                duration="Jan 2024 – Present",
                responsibilities=[
                    "Built RAG workflows on Vertex AI for internal search.",
                    "Developed Python-based data processing pipelines supporting AI/ML workflows.",
                ],
            )
        ],
    }
    rendered = render_tailored_tex(SOURCE, resume, tailored)
    skills = rendered.split(r"\section{Skills}", 1)[1].split(r"\section{Experience}", 1)[0]
    assert "AI-focused engineer with experience in Python, SQL, Docker, and Vertex AI." in rendered
    assert "Vertex AI, Docker, Python, SQL" in skills
    assert "LangChain" not in rendered
    assert rendered.index("Built RAG workflows on Vertex AI") < rendered.index(
        "Developed Python-based data processing pipelines supporting AI/ML workflows."
    )
    assert r"\documentclass{article}" in rendered
