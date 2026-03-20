"""AI engine: skill categorization via Groq API with rule-based fallback."""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime

from dotenv import load_dotenv

from models import CategorizationResult

load_dotenv()

logger = logging.getLogger(__name__)

# Keyword-based category mapping for the fallback categorizer
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Programming Languages": [
        "python", "java", "javascript", "typescript", "go", "rust", "c++",
        "c#", "ruby", "php", "swift", "kotlin", "bash",
    ],
    "Cloud & Infrastructure": [
        "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "linux",
        "jenkins", "github actions", "ci/cd",
    ],
    "Data & ML": [
        "machine learning", "deep learning", "tensorflow", "pytorch",
        "scikit-learn", "pandas", "numpy", "data analysis", "tableau",
        "power bi", "sql", "postgresql", "mongodb", "redis", "kafka",
        "elasticsearch",
    ],
    "DevOps": [
        "ci/cd", "docker", "kubernetes", "terraform", "jenkins",
        "github actions",
    ],
    "Soft Skills": [
        "communication", "leadership", "project management", "agile",
        "scrum", "problem solving", "technical writing",
    ],
}


class SkillCategorizerInterface(ABC):
    """Abstract interface for skill categorization."""

    @abstractmethod
    def categorize(
        self,
        missing_skills: list[str],
        matched_skills: list[str],
    ) -> CategorizationResult:
        """Categorize skills into groups and produce a summary."""


class FallbackCategorizer(SkillCategorizerInterface):
    """Rule-based categorizer: groups skills by keyword categories."""

    def categorize(
        self,
        missing_skills: list[str],
        matched_skills: list[str],
    ) -> CategorizationResult:
        groups: dict[str, list[str]] = {}

        for skill in missing_skills:
            placed = False
            for category, keywords in _CATEGORY_KEYWORDS.items():
                if skill.lower() in keywords:
                    groups.setdefault(category, []).append(skill)
                    placed = True
                    break
            if not placed:
                groups.setdefault("Other", []).append(skill)

        # Build a 2-4 sentence summary
        total_missing = len(missing_skills)
        total_matched = len(matched_skills)
        summary_parts: list[str] = []

        if total_matched > 0:
            summary_parts.append(
                f"You have {total_matched} matching skill{'s' if total_matched != 1 else ''} for this role."
            )
        if total_missing > 0:
            summary_parts.append(
                f"There {'are' if total_missing != 1 else 'is'} {total_missing} skill{'s' if total_missing != 1 else ''} to develop."
            )
        if groups:
            top_category = max(groups, key=lambda k: len(groups[k]))
            summary_parts.append(
                f"The largest gap area is {top_category} with {len(groups[top_category])} skill{'s' if len(groups[top_category]) != 1 else ''}."
            )
        if not summary_parts:
            summary_parts.append("No skill gaps were identified.")

        summary = " ".join(summary_parts)

        return CategorizationResult(
            groups=groups,
            summary=summary,
            is_fallback=True,
        )


class GroqCategorizer(SkillCategorizerInterface):
    """Uses Groq API (Llama 3.3 70B) for skill categorization with 5-second timeout."""

    MODEL = "llama-3.3-70b-versatile"
    TIMEOUT = 5

    def __init__(self) -> None:
        from groq import Groq
        self._client = Groq(
            api_key=os.environ.get("GROQ_API_KEY", ""),
            timeout=self.TIMEOUT,
        )
        self._fallback = FallbackCategorizer()

    def categorize(
        self,
        missing_skills: list[str],
        matched_skills: list[str],
    ) -> CategorizationResult:
        try:
            prompt = (
                "You are a career advisor. Categorize these missing skills into groups "
                "(e.g. Programming Languages, Cloud & Infrastructure, Data & ML, DevOps, Soft Skills, Other). "
                "Also provide a 2-4 sentence summary of the person's skill gaps.\n\n"
                f"Missing skills: {', '.join(missing_skills)}\n"
                f"Matched skills: {', '.join(matched_skills)}\n\n"
                "Respond in JSON with keys 'groups' (dict of category -> list of skills) "
                "and 'summary' (string)."
            )

            response = self._client.chat.completions.create(
                model=self.MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1024,
            )

            content = response.choices[0].message.content or ""
            # Try to parse JSON from the response
            # Strip markdown code fences if present
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()

            data = json.loads(cleaned)
            groups = data.get("groups", {})
            summary = data.get("summary", "")

            return CategorizationResult(
                groups=groups,
                summary=summary,
                is_fallback=False,
            )

        except Exception as e:
            timestamp = datetime.now().isoformat()
            logger.error("[%s] Groq API error: %s", timestamp, e)
            return self._fallback.categorize(missing_skills, matched_skills)


def get_categorizer() -> SkillCategorizerInterface:
    """Factory: return GroqCategorizer if GROQ_API_KEY is set, else FallbackCategorizer."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if api_key:
        try:
            return GroqCategorizer()
        except Exception as e:
            timestamp = datetime.now().isoformat()
            logger.error("[%s] Failed to initialize GroqCategorizer: %s", timestamp, e)
            return FallbackCategorizer()
    return FallbackCategorizer()
