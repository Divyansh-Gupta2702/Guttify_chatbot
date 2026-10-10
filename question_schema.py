"""Central question ownership and resolution policy for GutGPT.

This module is the single source of truth for which state slots an active
question owns and what constitutes a complete answer. It intentionally does
not perform diagnosis or recommendation.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
import re


@dataclass(frozen=True)
class QuestionResolution:
    field: str | None
    answered: bool
    values: dict = field(default_factory=dict)
    confidence: float = 0.0
    clarification_needed: bool = False


@dataclass(frozen=True)
class QuestionSpec:
    fields: frozenset[str]
    answer_kind: str = "free_text"  # boolean, composite_boolean, numeric, choice, free_text
    require_all: bool = True
    allow_bare_no_all: bool = False
    allow_bare_yes_all: bool = False


# Explicit ownership for every questionnaire question id used by the
# questionnaire and legacy branches. Keep additions here, not in handlers.
QUESTION_SCHEMA = {
    "duration": QuestionSpec(frozenset({"duration"}), "duration"),
    "age": QuestionSpec(frozenset({"age"}), "numeric"),
    "weight_loss": QuestionSpec(frozenset({"weight_loss"}), "boolean"),
    "weight_loss_duration": QuestionSpec(frozenset({"weight_loss"}), "boolean"),
    "bowel_frequency": QuestionSpec(frozenset({"bowel_frequency_per_week"}), "numeric"),
    "daily_frequency": QuestionSpec(frozenset({"bowel_frequency_per_day"}), "numeric"),
    "stool_straining": QuestionSpec(frozenset({"stool_form", "straining", "constipation_explicit"}), "composite_boolean"),
    "constipation": QuestionSpec(frozenset({"stool_form", "straining", "constipation_explicit"}), "composite_boolean"),
    "hard_stools": QuestionSpec(frozenset({"hard_stools"}), "boolean"),
    "straining": QuestionSpec(frozenset({"straining"}), "boolean"),
    "incomplete_evacuation": QuestionSpec(frozenset({"incomplete_evacuation"}), "boolean"),
    "bloating_pain": QuestionSpec(frozenset({"bloating", "abdominal_pain", "pain_related_to_bowel_movement"}), "composite_boolean"),
    "pain": QuestionSpec(frozenset({"abdominal_pain", "pain_related_to_bowel_movement"}), "conjunctive_boolean", allow_bare_yes_all=True, allow_bare_no_all=True),
    "pain_relation": QuestionSpec(frozenset({"food_related", "pain_related_to_bowel_movement"}), "choice"),
    "blood": QuestionSpec(frozenset({"blood_present"}), "boolean"),
    "bleeding": QuestionSpec(frozenset({"blood_present"}), "boolean"),
    "blood_colour": QuestionSpec(frozenset({"blood_colour"}), "choice"),
    "blood_location": QuestionSpec(frozenset({"blood_location"}), "choice"),
    "blood_mucus": QuestionSpec(frozenset({"blood_present", "mucus"}), "composite_boolean"),
    "anal_pain": QuestionSpec(frozenset({"anal_pain", "sharp_pain_during_stool"}), "boolean"),
    "lump": QuestionSpec(frozenset({"lump_or_prolapse"}), "boolean"),
    "lump_or_prolapse": QuestionSpec(frozenset({"lump_or_prolapse"}), "boolean"),
    "vomiting_fever": QuestionSpec(frozenset({"vomiting", "fever"}), "composite_boolean", allow_bare_no_all=True),
    "vomiting_fever_swelling": QuestionSpec(frozenset({"vomiting", "fever", "abdominal_distension"}), "composite_boolean", allow_bare_no_all=True),
    "night_weight_fever": QuestionSpec(frozenset({"night_time_symptoms", "weight_loss", "fever"}), "composite_boolean", allow_bare_no_all=True),
    "swallowing": QuestionSpec(frozenset({"difficulty_swallowing", "persistent_vomiting", "vomiting_blood"}), "composite_boolean", allow_bare_no_all=True),
    "weight_swallow": QuestionSpec(frozenset({"weight_loss", "difficulty_swallowing", "persistent_vomiting", "vomiting_blood"}), "composite_boolean", allow_bare_no_all=True),
    "upper_symptoms": QuestionSpec(frozenset({"abdominal_pain"}), "free_text"),
    "symptoms": QuestionSpec(frozenset({"abdominal_pain", "bloating", "diarrhea", "constipation_explicit"}), "free_text"),
    "stool_form": QuestionSpec(frozenset({"stool_form"}), "numeric"),
    "severity": QuestionSpec(frozenset({"severity"}), "numeric"),
    "pain_location": QuestionSpec(frozenset({"pain_location"}), "choice"),
    "bowel_pattern": QuestionSpec(frozenset({"constipation_explicit", "diarrhea_explicit", "diarrhea"}), "choice"),
    "reflux": QuestionSpec(frozenset({"reflux_present"}), "boolean"),
    "timing": QuestionSpec(frozenset({"meal_timing", "symptom_onset_after_food", "timing_relation"}), "timing"),
    "triggers": QuestionSpec(frozenset({"food_trigger", "food_related"}), "choice"),
    "food_trigger": QuestionSpec(frozenset({"food_trigger", "food_related"}), "choice"),
    "food_relation": QuestionSpec(frozenset({"food_related"}), "boolean"),
    "trigger": QuestionSpec(frozenset({"food_trigger", "food_related"}), "choice"),
    "infection": QuestionSpec(frozenset({"recent_infection"}), "boolean"),
    "water": QuestionSpec(frozenset({"water_intake"}), "numeric"),
    "fibre": QuestionSpec(frozenset({"fibre_intake"}), "choice"),
    "medications": QuestionSpec(frozenset({"medications"}), "free_text"),
    "red_flag_check": QuestionSpec(frozenset({"red_flags"}), "free_text"),
    "product_concern": QuestionSpec(frozenset(), "free_text"),
}



# Complete state-field audit registry. Fields are classified even when they are
# not directly owned by a questionnaire question, so no state slot is silently
# orphaned from the audit.
STATE_FIELD_POLICY = {
    "primary_symptom": "initial_nlu",
    "secondary_symptoms": "initial_nlu",
    "frequency": "legacy_generic",
    "food_related": "question_or_explicit_volunteered",
    "food_trigger": "question_or_explicit_volunteered",
    "reflux_present": "question_owned",
    "meal_timing": "question_owned",
    "symptom_onset_after_food": "question_owned",
    "timing_relation": "question_owned",
    "severity": "question_owned",
    "duration": "question_owned",
    "age": "question_owned",
    "bowel_frequency_per_week": "question_owned",
    "bowel_frequency_per_day": "question_owned",
    "stool_form": "question_owned",
    "hard_stools": "question_owned_or_contextual",
    "straining": "question_owned",
    "incomplete_evacuation": "question_owned",
    "abdominal_pain": "question_owned",
    "pain_location": "question_owned",
    "pain_related_to_bowel_movement": "question_owned",
    "blood_present": "question_owned",
    "blood_colour": "question_owned",
    "blood_location": "question_owned",
    "blood_mixed_with_stool": "explicit_or_derived",
    "anal_pain": "question_owned",
    "sharp_pain_during_stool": "question_owned",
    "lump_or_prolapse": "question_owned",
    "bloating": "question_owned_or_contextual",
    "diarrhea": "question_owned_or_contextual",
    "constipation_explicit": "question_owned_or_contextual",
    "diarrhea_explicit": "question_owned_or_contextual",
    "mucus": "question_owned",
    "fever": "question_owned_or_safety",
    "vomiting": "question_owned_or_safety",
    "persistent_vomiting": "question_owned",
    "vomiting_blood": "question_owned",
    "difficulty_swallowing": "question_owned",
    "abdominal_distension": "question_owned_or_safety",
    "night_time_symptoms": "question_owned_legacy_compatibility",
    "weight_loss": "question_owned",
    "dehydration": "safety_or_contextual",
    "unable_to_pass_stool_and_gas": "safety_or_contextual",
    "water_intake": "question_owned",
    "fibre_intake": "question_owned",
    "medications": "question_owned",
    "recent_infection": "question_owned",
    "family_history_gi": "explicit_or_future_question",
    "body_areas": "contextual_nlu",
    "pain_character": "contextual_nlu",
    "pain_timing": "contextual_nlu",
    "itching": "contextual_nlu",
    "burning": "contextual_nlu",
    "swelling": "contextual_nlu",
    "gas": "contextual_nlu",
    "recent_worsening": "question_owned_or_contextual",
    "red_flags": "safety_derived",
    "asked_fields": "question_engine",
    "weight_loss_duration_asked": "question_engine",
}

def get_question_spec(question_id: str | None) -> QuestionSpec | None:
    return QUESTION_SCHEMA.get(question_id)


def _has(state: Any, name: str) -> bool:
    value = getattr(state, name, None)
    return value is not None and value != "unknown"


def question_has_answer(state: Any, question_id: str | None) -> bool:
    """Semantic completion, never based on unrelated populated state."""
    if not question_id:
        return True
    # Compatibility: unknown legacy IDs remain governed by their explicit
    # questionnaire condition rather than being treated as answered.
    spec = get_question_spec(question_id)
    if spec is None:
        return False

    if question_id in {"duration"}:
        return _has(state, "duration")
    if question_id in {"age"}:
        return _has(state, "age")
    if question_id in {"weight_loss", "weight_loss_duration"}:
        return _has(state, "weight_loss")
    if question_id == "bowel_frequency":
        return _has(state, "bowel_frequency_per_week")
    if question_id == "daily_frequency":
        return _has(state, "bowel_frequency_per_day")
    if question_id in {"stool_straining", "constipation"}:
        # A positive answer may identify only one component; the combined
        # question is complete only when both requested supporting dimensions
        # are known, unless the user explicitly supplied a canonical
        # constipation yes/no answer.
        return _has(state, "constipation_explicit") or (
            _has(state, "stool_form") and _has(state, "straining")
        )
    if question_id == "hard_stools":
        return _has(state, "hard_stools")
    if question_id == "straining":
        return _has(state, "straining")
    if question_id == "incomplete_evacuation":
        return _has(state, "incomplete_evacuation")
    if question_id == "bloating_pain":
        if state.bloating is True or state.abdominal_pain is True:
            return state.abdominal_pain is not True or _has(state, "pain_related_to_bowel_movement")
        return state.bloating is False and state.abdominal_pain is False
    if question_id == "pain":
        return _has(state, "abdominal_pain") and (
            state.abdominal_pain is False or _has(state, "pain_related_to_bowel_movement")
        )
    if question_id == "pain_relation":
        return _has(state, "food_related") or _has(state, "pain_related_to_bowel_movement")
    if question_id in {"blood", "bleeding"}:
        return _has(state, "blood_present")
    if question_id == "blood_colour":
        return _has(state, "blood_colour")
    if question_id == "blood_location":
        return _has(state, "blood_location")
    if question_id == "blood_mucus":
        return _has(state, "blood_present") and _has(state, "mucus")
    if question_id == "anal_pain":
        return _has(state, "sharp_pain_during_stool") and _has(state, "anal_pain")
    if question_id in {"lump", "lump_or_prolapse"}:
        return _has(state, "lump_or_prolapse")
    if question_id == "vomiting_fever":
        return _has(state, "vomiting") and _has(state, "fever")
    if question_id == "vomiting_fever_swelling":
        return _has(state, "vomiting") and _has(state, "fever") and _has(state, "abdominal_distension")
    if question_id == "night_weight_fever":
        return _has(state, "night_time_symptoms") and _has(state, "weight_loss") and _has(state, "fever")
    if question_id in {"swallowing"}:
        return _has(state, "difficulty_swallowing") and _has(state, "persistent_vomiting") and _has(state, "vomiting_blood")
    if question_id == "weight_swallow":
        return _has(state, "weight_loss") and _has(state, "difficulty_swallowing") and _has(state, "persistent_vomiting") and _has(state, "vomiting_blood")
    if question_id == "upper_symptoms":
        return _has(state, "abdominal_pain")
    if question_id == "symptoms":
        # The food-intolerance question asks what symptoms occur; a category
        # answer, not pre-existing pain/frequency, is required.
        return any(_has(state, f) for f in ("bloating", "diarrhea", "abdominal_pain", "constipation_explicit"))
    if question_id == "stool_form":
        return _has(state, "stool_form")
    if question_id == "severity":
        return _has(state, "severity")
    if question_id == "pain_location":
        return _has(state, "pain_location")
    if question_id == "bowel_pattern":
        # This is a categorical question. Frequency alone is not an answer.
        return _has(state, "constipation_explicit") or _has(state, "diarrhea_explicit")
    if question_id == "reflux":
        return _has(state, "reflux_present")
    if question_id == "timing":
        return _has(state, "timing_relation")
    if question_id in {"triggers", "food_trigger", "trigger"}:
        return _has(state, "food_trigger") or state.food_related is False
    if question_id == "food_relation":
        return _has(state, "food_related")
    if question_id == "infection":
        return _has(state, "recent_infection")
    if question_id == "water":
        return _has(state, "water_intake")
    if question_id == "fibre":
        return _has(state, "fibre_intake")
    if question_id == "medications":
        return _has(state, "medications")
    if question_id == "red_flag_check":
        return bool(state.red_flags) or _has(state, "red_flags_answered")
    return True
