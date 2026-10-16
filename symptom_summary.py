"""Deterministic, read-only customer-facing symptom summary for GutGPT.

This module formats already-collected structured facts. It does not infer
symptoms, diagnose, mutate assessment state, or choose products.
"""

BRISTOL_LABELS = {
    1: "separate hard pellets",
    2: "lumpy, sausage-shaped stool",
    3: "sausage-shaped stool with surface cracks",
    4: "smooth, soft sausage-shaped stool",
    5: "soft blobs with clear edges",
    6: "mushy stool with ragged edges",
    7: "watery stool with no solid pieces",
}


def _yes_no(value):
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return None


def build_symptom_summary(state):
    """Return a stable summary string based only on known state values."""
    lines = ["**Please review your symptom summary**", ""]
    facts = []

    primary = getattr(state, "primary_symptom", None)
    secondary = list(getattr(state, "secondary_symptoms", []) or [])
    symptoms = []
    if primary:
        symptoms.append(str(primary))
    for symptom in secondary:
        if symptom and str(symptom).casefold() not in {x.casefold() for x in symptoms}:
            symptoms.append(str(symptom))
    if symptoms:
        facts.append("Symptoms reported: " + ", ".join(symptoms))

    duration = getattr(state, "duration", None)
    if duration and str(duration).casefold() != "unknown":
        facts.append(f"Duration: {duration}")

    age = getattr(state, "age", None)
    if age is not None:
        facts.append(f"Age: {age}")

    severity = getattr(state, "severity", None)
    if severity and str(severity).casefold() != "unknown":
        facts.append(f"Severity: {severity}")

    stool_form = getattr(state, "stool_form", None)
    if isinstance(stool_form, int) and stool_form in BRISTOL_LABELS:
        facts.append(f"Bristol Stool Chart: Type {stool_form} — {BRISTOL_LABELS[stool_form]}")
    elif stool_form == "unknown":
        facts.append("Bristol Stool Chart: Not sure / not provided")

    for attr, label in (
        ("bowel_frequency_per_week", "Bowel movements per week"),
        ("bowel_frequency_per_day", "Loose/watery stools per day"),
    ):
        value = getattr(state, attr, None)
        if value is not None:
            facts.append(f"{label}: {value:g}" if isinstance(value, (int, float)) else f"{label}: {value}")

    for attr, label in (
        ("straining", "Straining to pass stool"),
        ("incomplete_evacuation", "Feeling of incomplete emptying"),
        ("bloating", "Bloating"),
        ("abdominal_pain", "Abdominal pain"),
        ("blood_present", "Blood in/around stool"),
        ("fever", "Fever"),
        ("vomiting", "Vomiting"),
        ("weight_loss", "Significant weight loss"),
    ):
        answer = _yes_no(getattr(state, attr, None))
        if answer is not None:
            facts.append(f"{label}: {answer}")

    if not facts:
        facts.append("No structured symptom details have been recorded yet.")
    lines.extend(f"- {fact}" for fact in facts)
    lines.extend([
        "",
        "Reply **yes** if this is correct. If anything is missing or incorrect, tell me what to change.",
        "This summary is a recap of your answers, not a confirmed medical diagnosis.",
    ])
    return "\n".join(lines)
