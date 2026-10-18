"""Canonical skill names and conservative partial-match rules.

A JD skill is an exact match only when it, or a listed alias, appears in the
master resume or candidate profile. Partial matches are reported and are never
written onto a resume as if they were possessed skills.
"""

from __future__ import annotations

import re

from src.utils.text import unique_keep

# alias (lowercase) -> display name
ALIASES: dict[str, str] = {
    "python": "Python",
    "sql": "SQL",
    "pyspark": "PySpark",
    "apache spark": "Spark",
    "spark": "Spark",
    "kafka": "Kafka",
    "apache kafka": "Kafka",
    "aws": "AWS",
    "amazon web services": "AWS",
    "azure": "Azure",
    "microsoft azure": "Azure",
    "azure devops": "Azure DevOps",
    "gcp": "GCP",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    "vertex ai": "Vertex AI",
    "google vertex ai": "Vertex AI",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "terraform": "Terraform",
    "machine learning": "Machine Learning",
    "ai/ml": "Machine Learning",
    "generative ai": "Generative AI",
    "genai": "Generative AI",
    "gen ai": "Generative AI",
    "llm": "LLM",
    "llms": "LLM",
    "large language model": "LLM",
    "large language models": "LLM",
    "rag": "RAG",
    "retrieval augmented generation": "RAG",
    "retrieval-augmented generation": "RAG",
    "mlflow": "MLflow",
    "nlp": "NLP",
    "natural language processing": "NLP",
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "llamaindex": "LlamaIndex",
    "llama index": "LlamaIndex",
    "hugging face": "Hugging Face",
    "huggingface": "Hugging Face",
    "transformers": "Transformers",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "airflow": "Apache Airflow",
    "apache airflow": "Apache Airflow",
    "dbt": "dbt",
    "snowflake": "Snowflake",
    "bigquery": "BigQuery",
    "google bigquery": "BigQuery",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "git": "Git",
    "github actions": "GitHub Actions",
    "gitlab ci": "GitLab CI",
    "jenkins": "Jenkins",
    "linux": "Linux",
    "rest": "REST",
    "rest api": "REST APIs",
    "rest apis": "REST APIs",
    "restful apis": "REST APIs",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "mlops": "MLOps",
    "data pipelines": "Data Pipelines",
    "data pipeline": "Data Pipelines",
    "data processing pipelines": "Data Pipelines",
    "prompt engineering": "Prompt Engineering",
    "vector database": "Vector Databases",
    "vector databases": "Vector Databases",
    "pinecone": "Pinecone",
    "faiss": "FAISS",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "sagemaker": "SageMaker",
    "amazon sagemaker": "SageMaker",
    "azure machine learning": "Azure Machine Learning",
    "azure ml": "Azure Machine Learning",
    "kubeflow": "Kubeflow",
    "deep learning": "Deep Learning",
    "computer vision": "Computer Vision",
    "feature store": "Feature Store",
    "data engineering": "Data Engineering",
    "etl": "ETL",
    "elt": "ELT",
    "spark streaming": "Spark Streaming",
    "hadoop": "Hadoop",
    "hive": "Hive",
    "looker": "Looker",
    "tableau": "Tableau",
    "power bi": "Power BI",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "java": "Java",
    "golang": "Go",
    "c++": "C++",
    "c#": "C#",
    "bash": "Bash",
    "shell scripting": "Bash",
    "streamlit": "Streamlit",
    "gradio": "Gradio",
    "langchain expression language": "LangChain",
    "semantic kernel": "Semantic Kernel",
    "crewai": "CrewAI",
    "autogen": "AutoGen",
    "bert": "BERT",
    "spacy": "spaCy",
    "nltk": "NLTK",
    "openai api": "OpenAI",
    "gemini": "Gemini",
    "function calling": "Function Calling",
    "ai agents": "AI Agents",
    "agentic workflows": "AI Agents",
    "model context protocol": "Model Context Protocol",
    "mcp": "Model Context Protocol",
}

# JD skill -> groups of resume skills. Any one group is enough for a partial.
# Product names such as LangChain are intentionally absent.
PARTIAL_RULES: dict[str, list[list[str]]] = {
    "CI/CD": [["Jenkins"], ["GitHub Actions"], ["GitLab CI"]],
    "Containerization": [["Docker"]],
    "Container Orchestration": [["Kubernetes"]],
    "Infrastructure as Code": [["Terraform"]],
    "Cloud Computing": [["AWS"], ["Azure"], ["GCP"]],
    "Cloud": [["AWS"], ["Azure"], ["GCP"]],
    "Relational Databases": [["SQL"], ["PostgreSQL"], ["MySQL"]],
    "REST APIs": [["FastAPI"], ["Flask"], ["Django"]],
    "REST": [["FastAPI"], ["Flask"], ["Django"]],
    "Data Pipelines": [["Apache Airflow"], ["PySpark"], ["Spark"], ["Kafka"]],
    "MLOps": [["MLflow"]],
    "Azure Machine Learning": [["Azure", "Machine Learning"]],
    "SageMaker": [["AWS", "Machine Learning"]],
}

CLOUD_AI_SKILLS = {
    "AWS",
    "Azure",
    "GCP",
    "Vertex AI",
    "Docker",
    "Kubernetes",
    "Terraform",
    "Machine Learning",
    "Generative AI",
    "LLM",
    "RAG",
    "MLflow",
    "NLP",
    "SageMaker",
    "Azure Machine Learning",
    "Kubeflow",
    "PyTorch",
    "TensorFlow",
    "Hugging Face",
    "LangChain",
    "LlamaIndex",
    "Deep Learning",
    "AI Agents",
    "Prompt Engineering",
    "Vector Databases",
    "MLOps",
}

AI_EVIDENCE_TERMS = {
    "Generative AI",
    "LLM",
    "RAG",
    "Vertex AI",
    "Machine Learning",
    "MLflow",
    "NLP",
    "Deep Learning",
    "PyTorch",
    "TensorFlow",
    "Hugging Face",
    "AI Agents",
    "Prompt Engineering",
}


def canonicalize(skill: str) -> str:
    key = re.sub(r"\s+", " ", skill.strip().lower())
    return ALIASES.get(key, skill.strip())


def _pattern(alias: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![a-z0-9+#]){re.escape(alias)}(?![a-z0-9+#])",
        re.IGNORECASE,
    )


def find_skills(text: str) -> list[str]:
    """Return canonical skills in the order they appear in ``text``."""
    if not text:
        return []
    occupied = [False] * len(text)
    hits: list[tuple[int, str]] = []
    aliases = sorted(ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
    for alias, canonical in aliases:
        for match in _pattern(alias).finditer(text):
            start, end = match.start(), match.end()
            if any(occupied[start:end]):
                continue
            for index in range(start, end):
                occupied[index] = True
            hits.append((start, canonical))
    hits.sort(key=lambda item: item[0])
    return unique_keep([canonical for _, canonical in hits])


def is_partial(jd_skill: str, resume_skills: set[str]) -> bool:
    canonical = canonicalize(jd_skill)
    if canonical in resume_skills:
        return False
    for group in PARTIAL_RULES.get(canonical, []):
        if all(skill in resume_skills for skill in group):
            return True
    return False
