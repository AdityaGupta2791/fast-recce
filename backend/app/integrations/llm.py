"""Gemini LLM client for subjective scoring (M7) and brief generation (M8).

Uses the modern `google-genai` SDK. Two subjective signals need the LLM:
- shoot_fit: how suitable is this property for a film/ad shoot?
- visual_uniqueness: how visually distinctive is the property?

Both are returned as floats in 0-1 via Gemini's JSON mode with response_schema.
Every public method has a deterministic fallback so a Gemini outage never
stops the pipeline — we fall back to keyword heuristics and flag the
property so it gets re-scored when the API is back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class _ScoreJSON(BaseModel):
    """Structured output schema the LLM must return."""

    score: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=200)


@dataclass
class LLMScoreResult:
    """Result returned to ScoringService.

    source is one of:
      - "llm"        : Gemini returned a valid score
      - "fallback"   : LLM failed, heuristic used
    """

    score: float
    reasoning: str
    source: str


# Keywords that strongly suggest shoot-readiness (used in fallback heuristic).
_SHOOT_FIT_KEYWORDS = {
    "photoshoot", "photo shoot", "film shoot", "shoot-ready", "film friendly",
    "events", "wedding", "reception", "brand campaign", "campaign",
    "rooftop", "lawn", "terrace", "garden", "poolside",
    "industrial", "heritage", "rustic", "minimalist", "open-air",
}


class LLMClient:
    """Async Gemini client. Stateless — safe to construct once and reuse."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3-flash-preview",
        timeout_seconds: float = 15.0,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._timeout = timeout_seconds

    async def assess_shoot_fit(
        self,
        *,
        property_type: str,
        description: str | None,
        amenities: list[str],
        feature_tags: list[str],
    ) -> LLMScoreResult:
        """How well does this property fit a shoot use-case? Returns 0-1."""
        prompt = (
            f"Property type: {property_type}\n"
            f"Description: {description or '(no description available)'}\n"
            f"Amenities: {', '.join(amenities) if amenities else '(none)'}\n"
            f"Feature tags: {', '.join(feature_tags) if feature_tags else '(none)'}\n"
            "\n"
            "Assess how suitable this property is for hosting a film, ad, "
            "or photoshoot on a scale of 0.0 to 1.0. Consider:\n"
            "- Does it have varied shooting spaces (indoor/outdoor)?\n"
            "- Are there signals of event/shoot hosting?\n"
            "- Is the aesthetic distinctive (not generic)?\n"
            "- Does it have practical shoot amenities (parking, power, wifi)?\n"
            "\n"
            "Return a JSON object with `score` (0-1) and `reasoning` (one sentence)."
        )
        return await self._ask_for_score(
            prompt=prompt,
            fallback=self._shoot_fit_heuristic,
            fallback_args=(description, amenities, feature_tags),
        )

    async def assess_visual_uniqueness(
        self,
        *,
        property_type: str,
        description: str | None,
        amenities: list[str],
        feature_tags: list[str],
    ) -> LLMScoreResult:
        """How visually distinctive is this property? Returns 0-1."""
        prompt = (
            f"Property type: {property_type}\n"
            f"Description: {description or '(no description available)'}\n"
            f"Amenities: {', '.join(amenities) if amenities else '(none)'}\n"
            f"Feature tags: {', '.join(feature_tags) if feature_tags else '(none)'}\n"
            "\n"
            "Assess how visually unique this property looks on a scale of 0.0 to 1.0.\n"
            "- 0.1: generic apartment / cookie-cutter hotel room\n"
            "- 0.5: pleasant but not distinctive\n"
            "- 0.9: strong visual identity (heritage architecture, striking views, "
            "unusual interiors)\n"
            "\n"
            "Return a JSON object with `score` (0-1) and `reasoning` (one sentence)."
        )
        return await self._ask_for_score(
            prompt=prompt,
            fallback=self._visual_uniqueness_heuristic,
            fallback_args=(property_type, feature_tags),
        )

    # --- Internals ---

    async def _ask_for_score(
        self,
        *,
        prompt: str,
        fallback: object,  # callable -> tuple[float, str]
        fallback_args: tuple,
    ) -> LLMScoreResult:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_ScoreJSON,
                    temperature=0.2,
                    # Bigger budget — gemini-2.5+ models use part of the
                    # output_tokens for hidden "thinking" before producing
                    # the visible JSON. 1000 leaves comfortable room for both.
                    max_output_tokens=1000,
                    # Cap the hidden reasoning budget for predictability/cost.
                    thinking_config=types.ThinkingConfig(thinking_budget=256),
                ),
            )
        except genai_errors.ClientError as exc:
            # 4xx — bad request, bad key, quota. Don't retry, fall back.
            logger.warning("Gemini ClientError, using fallback: %s", exc)
            score, reasoning = fallback(*fallback_args)  # type: ignore[operator]
            return LLMScoreResult(score=score, reasoning=reasoning, source="fallback")
        except (genai_errors.ServerError, Exception) as exc:  # noqa: BLE001
            logger.warning("Gemini unavailable, using fallback: %s", exc)
            score, reasoning = fallback(*fallback_args)  # type: ignore[operator]
            return LLMScoreResult(score=score, reasoning=reasoning, source="fallback")

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, _ScoreJSON):
            return LLMScoreResult(
                score=float(parsed.score),
                reasoning=parsed.reasoning,
                source="llm",
            )

        # Parse manually if parsed is missing (older SDK behaviour).
        text = getattr(response, "text", None)
        if isinstance(text, str):
            try:
                parsed_manual = _ScoreJSON.model_validate_json(text)
                return LLMScoreResult(
                    score=float(parsed_manual.score),
                    reasoning=parsed_manual.reasoning,
                    source="llm",
                )
            except Exception:  # noqa: BLE001
                pass

        logger.warning("Gemini response unparseable; using fallback")
        score, reasoning = fallback(*fallback_args)  # type: ignore[operator]
        return LLMScoreResult(score=score, reasoning=reasoning, source="fallback")

    @staticmethod
    def _shoot_fit_heuristic(
        description: str | None,
        amenities: list[str],
        feature_tags: list[str],
    ) -> tuple[float, str]:
        corpus = " ".join(
            [
                (description or "").lower(),
                " ".join(amenities).lower(),
                " ".join(feature_tags).lower(),
            ]
        )
        hits = sum(1 for kw in _SHOOT_FIT_KEYWORDS if kw in corpus)
        # 0 hits -> 0.3, 1-2 hits -> 0.5, 3-5 hits -> 0.7, 6+ hits -> 0.85
        if hits >= 6:
            score = 0.85
        elif hits >= 3:
            score = 0.7
        elif hits >= 1:
            score = 0.5
        else:
            score = 0.3
        return score, f"heuristic: matched {hits} shoot-fit keyword(s)"

    @staticmethod
    def _visual_uniqueness_heuristic(
        property_type: str,
        feature_tags: list[str],
    ) -> tuple[float, str]:
        # Heritage / rustic / industrial signal strong uniqueness.
        distinctive_tags = {"heritage", "rustic", "industrial", "traditional"}
        matches = [t for t in feature_tags if t in distinctive_tags]

        base = {
            "heritage_home": 0.75,
            "villa": 0.60,
            "farmhouse": 0.60,
            "warehouse": 0.65,
            "theatre_studio": 0.70,
            "bungalow": 0.55,
            "resort": 0.50,
            "boutique_hotel": 0.50,
            "cafe": 0.40,
            "restaurant": 0.35,
            "office_space": 0.30,
        }.get(property_type, 0.50)

        bonus = 0.1 * min(len(matches), 2)
        score = min(1.0, base + bonus)
        return score, f"heuristic: type={property_type}, distinctive_tags={matches}"

    async def close(self) -> None:
        """Release any underlying HTTP resources."""
        close = getattr(self._client, "close", None)
        if callable(close):
            try:
                result = close()
                if hasattr(result, "__await__"):
                    await result
            except Exception:  # noqa: BLE001
                pass
