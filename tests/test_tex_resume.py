"""The scorer reads the Overleaf resume when that file is present."""

from pathlib import Path

from src.resume.tex_parser import parse_overleaf_tex

SAMPLE = r"""
\begin{document}
{\Huge \textbf{Ada Lovelace}}
\section{PROFESSIONAL SUMMARY}
\item AI Engineer who builds RAG systems.
\section{TECHNICAL SKILLS}
\item \textbf{AI \& LLM Engineering:} LangChain, RAG, Azure DevOps
\item \textbf{Cloud Platforms:} Microsoft Azure (ADF, Azure Databricks), AWS
\section{PROFESSIONAL EXPERIENCE}
\resumeSubheading
{Example Analytics}
{Nov 2024 -- Present}
{AI Engineer}
{Hybrid}
\resumeItem{Built RAG workflows.}
\section{EDUCATION}
\resumeSubheading
{Example University}
{Aug 2022 -- Aug 2024}
{Master of Computer Application (MCA)}
{Pune}
\resumeItem{\textbf{CGPA:} 8.11 / 10}
\end{document}
"""


def test_overleaf_tex_supplies_the_facts_the_scorer_needs(tmp_path: Path):
    path = tmp_path / "main.tex"
    path.write_text(SAMPLE, encoding="utf-8")
    resume = parse_overleaf_tex(path)
    assert resume.name == "Ada Lovelace"
    assert "RAG" in resume.summary
    assert "LangChain" in resume.skills
    assert "Azure DevOps" in resume.skills
    assert "Microsoft Azure (ADF, Azure Databricks)" in resume.skills
    assert resume.experience[0].company == "Example Analytics"
    assert resume.experience[0].role == "AI Engineer"
    assert resume.experience[0].responsibilities == ["Built RAG workflows."]
    assert resume.education[0].degree == "Master of Computer Application (MCA)"
    assert resume.education[0].institution == "Example University"


def test_real_overleaf_resume_is_readable():
    path = Path("resume/overleaf/My_Resume/main.tex")
    if not path.exists():
        return
    resume = parse_overleaf_tex(path)
    assert resume.name == "Sudhanshu Sakhala"
    assert "LangChain" in resume.skills
    assert "Azure DevOps" in resume.skills
    assert any("Modak" in role.company for role in resume.experience)
    assert resume.education[0].degree.startswith("Master of Computer Application")
