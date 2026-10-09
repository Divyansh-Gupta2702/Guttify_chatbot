import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from intent_parser import SymptomState
from clinical_rule_engine import evaluate


def state(**kw):
    base = SymptomState(
        primary_symptom=kw.pop("primary_symptom", None),
        duration=kw.pop("duration", "2 months"),
        age=kw.pop("age", 25),
        weight_loss=kw.pop("weight_loss", False),
        fever=kw.pop("fever", False),
        family_history_gi=kw.pop("family_history_gi", False),
        night_time_symptoms=kw.pop("night_time_symptoms", False),
        red_flags=kw.pop("red_flags", []),
    )
    for k, v in kw.items():
        setattr(base, k, v)
    return base


def test_all_primary_symptom_branches_are_reachable():
    cases = {
        "constipation": "Functional constipation pattern",
        "hard stools": "Functional constipation pattern",
        "diarrhea": "Diarrhea pattern",
        "acidity": "Reflux/GERD-like symptom pattern",
        "heartburn": "Reflux/GERD-like symptom pattern",
        "bloating": "Functional gas/bloating pattern",
        "gas": "Functional gas/bloating pattern",
        "indigestion": "Dyspepsia/indigestion pattern",
        "food intolerance": "Possible food-triggered intolerance pattern",
        "stomach pain": "Nonspecific abdominal pain pattern",
        "piles": "Possible hemorrhoid pattern",
    }
    for primary, expected in cases.items():
        extra = {}
        if primary in ("constipation", "hard stools"):
            extra.update(constipation_explicit=True, bowel_frequency_per_week=2, stool_form=2, straining=True)
        elif primary == "diarrhea":
            extra.update(diarrhea_explicit=True, bowel_frequency_per_day=5, stool_form=6)
        elif primary == "food intolerance":
            extra.update(food_trigger="dairy")
        elif primary == "stomach pain":
            extra.update(pain_location="lower abdomen", severity="4")
        result = evaluate(state(primary_symptom=primary, **extra))
        assert result["pattern"] == expected, (primary, result)


def test_bloating_plus_single_hard_stool_is_not_constipation():
    result = evaluate(state(
        primary_symptom="bloating",
        constipation_explicit=False,
        bowel_frequency_per_week=5,
        stool_form=2,
    ))
    assert result["pattern"] == "Functional gas/bloating pattern"


def test_bloating_plus_strong_constipation_is_constipation_associated():
    result = evaluate(state(
        primary_symptom="bloating",
        constipation_explicit=True,
        bowel_frequency_per_week=2,
        stool_form=2,
        straining=True,
    ))
    assert result["pattern"] == "Constipation-associated bloating pattern"


def test_bloating_plus_diarrhea_does_not_become_constipation():
    result = evaluate(state(
        primary_symptom="bloating",
        constipation_explicit=False,
        diarrhea_explicit=True,
        bowel_frequency_per_day=5,
        stool_form=6,
    ))
    assert result["pattern"] == "Functional gas/bloating pattern"


def test_explicit_no_diarrhea_blocks_frequency_only_inference():
    result = evaluate(state(
        primary_symptom="bloating",
        diarrhea_explicit=False,
        bowel_frequency_per_day=4,
        stool_form=4,
    ))
    assert result["pattern"] == "Functional gas/bloating pattern"


def test_explicit_no_constipation_blocks_low_frequency_inference():
    result = evaluate(state(
        primary_symptom="bloating",
        constipation_explicit=False,
        bowel_frequency_per_week=2,
        stool_form=4,
    ))
    assert result["pattern"] == "Functional gas/bloating pattern"


def test_ibs_c_requires_real_constipation_pattern():
    result = evaluate(state(
        primary_symptom="bloating",
        constipation_explicit=False,
        abdominal_pain=True,
        pain_related_to_bowel_movement=True,
        duration="6 months",
        bowel_frequency_per_week=5,
        stool_form=2,
    ))
    assert result["pattern"] != "IBS-C pattern"


def test_ibs_c_with_explicit_constipation():
    result = evaluate(state(
        primary_symptom="constipation",
        constipation_explicit=True,
        abdominal_pain=True,
        pain_related_to_bowel_movement=True,
        duration="6 months",
        bowel_frequency_per_week=2,
        stool_form=2,
        straining=True,
    ))
    assert result["pattern"] == "IBS-C pattern"


def test_ibs_d_with_strong_diarrhea():
    result = evaluate(state(
        primary_symptom="diarrhea",
        diarrhea_explicit=True,
        constipation_explicit=False,
        abdominal_pain=True,
        pain_related_to_bowel_movement=True,
        duration="6 months",
        bowel_frequency_per_day=5,
        stool_form=6,
    ))
    assert result["pattern"] == "IBS-D pattern"


def test_ibs_m_requires_both_bowel_patterns():
    result = evaluate(state(
        primary_symptom="stomach pain",
        constipation_explicit=True,
        diarrhea_explicit=True,
        abdominal_pain=True,
        pain_related_to_bowel_movement=True,
        duration="6 months",
        bowel_frequency_per_week=2,
        bowel_frequency_per_day=4,
        stool_form=6,
    ))
    assert result["pattern"] == "IBS-M (mixed) pattern"


def test_warning_features_prevent_ibs_pattern():
    for warning in ("weight_loss", "fever", "family_history_gi", "night_time_symptoms"):
        result = evaluate(state(
            primary_symptom="constipation",
            constipation_explicit=True,
            abdominal_pain=True,
            pain_related_to_bowel_movement=True,
            duration="6 months",
            bowel_frequency_per_week=2,
            stool_form=2,
            straining=True,
            **{warning: True},
        ))
        assert result["pattern"] != "IBS-C pattern", warning


def test_blood_combinations_are_not_misclassified():
    fissure = evaluate(state(primary_symptom="constipation", blood_present=True, blood_colour="bright_red", sharp_pain_during_stool=True))
    hemorrhoid = evaluate(state(primary_symptom="piles", blood_present=True, blood_colour="bright_red", sharp_pain_during_stool=False, lump_or_prolapse=True))
    unclear = evaluate(state(primary_symptom="piles", blood_present=True, blood_colour="bright_red", sharp_pain_during_stool=False, lump_or_prolapse=False))
    assert fissure["pattern"] == "Possible anal fissure pattern"
    assert hemorrhoid["pattern"] == "Possible hemorrhoid pattern"
    assert unclear["pattern"] == "Rectal bleeding of unclear cause"


def test_black_stool_always_wins():
    result = evaluate(state(primary_symptom="constipation", blood_present=True, blood_colour="black", bowel_frequency_per_week=2, stool_form=2))
    assert result["action"] == "urgent_medical_evaluation"
    assert result["product_allowed"] is False


def test_red_flag_always_wins_over_every_primary_branch():
    primaries = ["constipation", "diarrhea", "bloating", "gas", "acidity", "heartburn", "indigestion", "food intolerance", "stomach pain", "piles"]
    for primary in primaries:
        result = evaluate(state(primary_symptom=primary, red_flags=["test red flag"]))
        assert result["pattern"] == "Red-flag presentation"
        assert result["product_allowed"] is False


def test_acidity_does_not_become_constipation_from_hard_stool():
    result = evaluate(state(primary_symptom="acidity", constipation_explicit=False, stool_form=2, bowel_frequency_per_week=5))
    assert result["pattern"] == "Reflux/GERD-like symptom pattern"


def test_indigestion_does_not_become_diarrhea_from_high_frequency_without_loose_stool():
    result = evaluate(state(primary_symptom="indigestion", diarrhea_explicit=False, bowel_frequency_per_day=4, stool_form=4))
    assert result["pattern"] == "Dyspepsia/indigestion pattern"


def test_food_intolerance_remains_food_pattern_with_bowel_changes():
    result = evaluate(state(primary_symptom="food intolerance", food_trigger="dairy", diarrhea_explicit=True, bowel_frequency_per_day=4, stool_form=6))
    assert result["pattern"] == "Possible food-triggered intolerance pattern"


def test_stomach_pain_with_bowel_change_is_not_automatically_ibs_without_chronic_pain_criteria():
    result = evaluate(state(primary_symptom="stomach pain", abdominal_pain=True, pain_related_to_bowel_movement=True, constipation_explicit=True, bowel_frequency_per_week=2, stool_form=2, duration="2 weeks", pain_location="lower abdomen", severity="5"))
    assert result["pattern"] == "Bowel-related abdominal pain pattern"

def test_bowel_related_abdominal_pain_allows_digest_boost_without_red_flags():
    result = evaluate(state(primary_symptom="stomach pain", abdominal_pain=True, pain_related_to_bowel_movement=True, constipation_explicit=True, bowel_frequency_per_week=2, stool_form=2, duration="2 weeks", pain_location="lower abdomen", severity="5"))
    assert result["pattern"] == "Bowel-related abdominal pain pattern"
    assert result["product_allowed"] is True


def test_piles_without_bleeding_is_reachable():
    result = evaluate(state(primary_symptom="piles", blood_present=False, lump_or_prolapse=True))
    assert result["pattern"] == "Possible hemorrhoid pattern"


def test_no_primary_symptom_is_not_fabricated_into_diagnosis():
    result = evaluate(state())
    assert result["pattern"] == "Insufficiently characterized gut symptom pattern"


def test_explicit_negative_fields_are_stable():
    # This is the exact class of regression that caused the original bug.
    for primary in ["bloating", "gas", "acidity", "indigestion", "food intolerance"]:
        result = evaluate(state(primary_symptom=primary, constipation_explicit=False, diarrhea_explicit=False, stool_form=2, bowel_frequency_per_week=2, bowel_frequency_per_day=4))
        assert "constipation" not in result["pattern"].lower()
        assert result["pattern"] not in {"Diarrhea pattern", "IBS-D pattern"}
