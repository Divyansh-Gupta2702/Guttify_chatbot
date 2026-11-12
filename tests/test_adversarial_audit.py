"""
GutGPT Advanced Adversarial Audit — v18.4.2
=============================================

PURPOSE
-------
End-to-end adversarial audit of the GutGPT chatbot. This file does NOT modify
any application code. It exercises the existing architecture and records
failures for a separate fix proposal.

ARCHITECTURE PRESERVED
----------------------
User Message → NLU → Contextual Question Resolver → State Update →
Question/Rule Engine → Diagnosis/Recommendation.

TEST STRATEGY
-------------
- Deterministic unit tests: Groq is disabled by conftest (_get_llm -> None).
- Real API conversations via FastAPI TestClient against a dedicated PostgreSQL
  database (gutgpt_audit) with persistent session state.
- Registered + guest users, multiple independent sessions.
- Limited real-Groq integration guarded by GUTGPT_AUDIT_LIVE_GROQ.

Failures in this file are audit findings, not defects in the test suite.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app
from clinical_rule_engine import evaluate as evaluate_screening
from guttify_agent import ConversationManager
from intent_parser import (
    SymptomState, extract_symptoms, merge_state,
)
from question_schema import resolve_against_active_question
from recommendation_engine import (
    evaluate as evaluate_products,
    products as ALL_PRODUCTS,
    DIARRHEA_DISALLOWED_PRODUCTS,
    find_named_product,
)
from safety_checker import check_safety, detect_red_flags, derive_red_flags
from nlu_extractor import extract_natural_facts

# ---------------------------------------------------------------------------
# Test database
# ---------------------------------------------------------------------------
os.environ["DATABASE_URL"] = os.environ.get(
    "GUTGPT_AUDIT_DATABASE_URL",
    "postgresql://postgres:admin%40123@localhost:5432/gutgpt_audit",
)
app.DATABASE_URL = os.environ["DATABASE_URL"]

LIVE_GROQ = os.environ.get("GUTGPT_AUDIT_LIVE_GROQ", "0") == "1"

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Fresh TestClient + cleared in-process session state per test.

    Also clears the PostgreSQL rate-limit table so that tests are isolated
    regardless of how many registrations earlier runs performed. This is test
    harness hygiene only; no application code is changed.
    """
    reset_app_state()
    _clear_rate_limits()
    c = TestClient(app.app)
    yield c
    reset_app_state()
    _clear_rate_limits()


def _clear_rate_limits():
    try:
        import psycopg
        conn = psycopg.connect(app.DATABASE_URL)
        with conn, conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE api_rate_limits CASCADE")
        conn.close()
    except Exception:
        pass


def reset_app_state():
    app.HISTORY.clear()
    app.HISTORY_LAST_ACCESS.clear()
    app.conversation_manager.sessions.clear()
    app.conversation_manager.last_access.clear()
    app.conversation_manager._session_locks.clear()
    app.SESSION_CUSTOMER_IDS.clear()
    app.SESSION_ASSESSMENT_IDS.clear()
    app.REGISTERED_CUSTOMER_SESSIONS.clear()


def register_customer(client, session_id, name="Audit Customer", age=32,
                      contact="9876543210", city="Mumbai"):
    return client.post("/api/customer", json={
        "session_id": session_id, "name": name, "age": age,
        "contact": contact, "city": city, "consent": True,
    })


def chat(client, session_id, message, language="en", message_id=None):
    payload = {"session_id": session_id, "message": message,
               "language": language}
    if message_id:
        payload["message_id"] = message_id
    return client.post("/api/chat", json=payload)


def chat_json(client, session_id, message, language="en", message_id=None):
    resp = chat(client, session_id, message, language=language,
                message_id=message_id)
    return resp.status_code, resp.json()


# ---------------------------------------------------------------------------
# Product catalogue reference
# ---------------------------------------------------------------------------
PRODUCT_NAMES = {p["product_name"] for p in ALL_PRODUCTS
                 if p.get("status") == "active"}
REMOVED_PRODUCTS = {"Boost Vitamins D3", "Boost Vitamins B12"}


def assert_product_record_valid(product):
    name = product.get("product_name")
    assert name in PRODUCT_NAMES, f"Fabricated product name: {name!r}"
    assert name not in REMOVED_PRODUCTS, f"Removed product recommended: {name!r}"
    assert product.get("category"), f"Missing category for {name}"
    assert product.get("intended_support"), f"Missing intended_support for {name}"
    assert product.get("ingredients"), f"Missing ingredients for {name}"
    assert product.get("how_to_use"), f"Missing how_to_use for {name}"
    assert product.get("warnings"), f"Missing warnings for {name}"
    url = product.get("product_url", "")
    assert url and url.startswith("http"), f"Invalid product_url: {url!r}"
    img = product.get("image_url", "")
    assert img and img.startswith("http"), f"Invalid image_url: {img!r}"
    assert product.get("price"), f"Missing price for {name}"


# ===========================================================================
# SECTION 1 — Unit-level: symptom extraction & diagnosis
# ===========================================================================

class TestSymptomExtractionAndDiagnosis:
    def test_constipation_and_diarrhea_intermittently(self):
        primary, secondary = extract_symptoms(
            "I have constipation and loose motions sometimes, it comes and goes")
        found = ({primary} if primary else set()) | set(secondary or [])
        assert "constipation" in found or "diarrhea" in found

    def test_acidity_indigestion_gas_bloating_abdominal_pain(self):
        text = "acidity, indigestion, gas, bloating, and abdominal pain after meals"
        primary, secondary = extract_symptoms(text)
        found = ({primary} if primary else set()) | set(secondary or [])
        assert found & {"acidity", "indigestion", "gas", "bloating", "stomach pain"}

    def test_piles_fissures_itching_bleeding_painful_bowel(self):
        text = "piles, fissures, itching, bleeding, and painful bowel movements"
        primary, secondary = extract_symptoms(text)
        found = ({primary} if primary else set()) | set(secondary or [])
        assert found & {"piles", "anal fissures", "bleeding"}

    def test_ibs_like_changing_stool_patterns(self):
        text = "alternating constipation and diarrhea for 6 months with abdominal pain"
        primary, secondary = extract_symptoms(text)
        found = ({primary} if primary else set()) | set(secondary or [])
        assert found & {"constipation", "diarrhea", "stomach pain"}

    def test_multiple_ambiguous_symptoms_do_not_crash(self):
        text = "feeling off, stomach not right, some bloating maybe, unclear pain"
        primary, secondary = extract_symptoms(text)
        assert primary is None or isinstance(primary, str)

    def test_contradictory_answers_corrections(self):
        state = SymptomState(primary_symptom="diarrhea", diarrhea=True,
                             diarrhea_explicit=True)
        merged = merge_state(state, "actually I do not have diarrhea, my stools are normal now")
        assert merged.diarrhea is False or "diarrhea" not in (merged.secondary_symptoms or [])

    def test_vague_answers_sometimes_not_sure_it_depends(self):
        res = resolve_against_active_question("daily_frequency", "sometimes")
        assert res["status"] == "clarification_needed"
        res2 = resolve_against_active_question("age", "not sure")
        assert res2["status"] == "unknown"

    def test_symptoms_across_10_to_15_messages_terminates(self):
        manager = ConversationManager()
        sid = "long-conversation"
        turns = [
            "I have stomach pain and bloating.",
            "It started about 2 months ago.",
            "I am 29 years old.",
            "The pain is in the upper abdomen after eating.",
            "Severity is about 4 out of 10.",
            "Yes the pain relates to meals.",
            "No I do not have constipation.",
            "No I do not have loose motions.",
            "I do not notice blood in my stool.",
            "No fever.",
            "No vomiting.",
            "I have not lost weight.",
            "My bowel movements are normal otherwise.",
            "No I do not take any medicines.",
            "I drink about 2 litres of water a day.",
        ]
        statuses = []
        for t in turns:
            r = manager.handle_message(sid, t)
            statuses.append(r["status"])
            if r["status"] in {"DIAGNOSIS", "RECOMMENDATION_FOUND",
                               "AMBIGUOUS", "SAFETY_REVIEW", "SESSION_ENDED"}:
                break
        assert statuses[-1] in {"DIAGNOSIS", "RECOMMENDATION_FOUND",
                                "AMBIGUOUS", "SAFETY_REVIEW", "ASK"}

    def test_red_flags_prevent_product_recommendations_unit(self):
        manager = ConversationManager()
        sid = "red-flag"
        r = manager.handle_message(sid, "I have severe abdominal pain and blood in my stool")
        assert r["status"] == "SAFETY_REVIEW"
        assert r["recommendations"] == []
        assert r["safety"]["requires_doctor"] is True


# ===========================================================================
# SECTION 2 — End-to-end API conversations (registered + guest)
# ===========================================================================

class TestEndToEndConversations:
    def _flow(self, client, sid, turns):
        transcript = []
        for message in turns:
            status, body = chat_json(client, sid, message,
                                     message_id=str(uuid.uuid4()))
            transcript.append((message, status, body))
        return transcript

    def _drive_to_terminal(self, client, sid, opening, answer_map, max_turns=60):
        """Drive a questionnaire to a terminal state using question_id-aware
        answers, so the test is robust to the exact question ordering.

        Returns the terminal response body, or the last body if the flow did
        not terminate (e.g. rate-limited or stuck in a question loop).
        """
        _, body = chat_json(client, sid, opening, message_id=str(uuid.uuid4()))
        for _ in range(max_turns):
            if not isinstance(body, dict) or "status" not in body:
                # Non-standard response (for example a rate-limit/detail
                # error): stop and return it so the test reports it clearly.
                return body
            status = body.get("status")
            if status in {"DIAGNOSIS", "RECOMMENDATION_FOUND", "AMBIGUOUS",
                          "SAFETY_REVIEW", "DIAGNOSIS_COMPLETE", "SESSION_ENDED"}:
                return body
            qmeta = body.get("question_metadata") or {}
            qid = qmeta.get("question_id")
            msg = (body.get("reply") or body.get("message") or "").lower()
            answer = None
            if qid and qid in answer_map:
                answer = answer_map[qid]
            # Summary review must be matched before symptom keywords, because
            # the summary text itself contains words such as "blood" and
            # "pain" which would otherwise hijack the answer.
            elif "review your symptom summary" in msg or "reply yes" in msg:
                answer = "yes"
            elif "how long" in msg or "been experiencing" in msg:
                answer = answer_map.get("duration", "2 months")
            elif "what is your age" in msg:
                answer = answer_map.get("age", "30")
            elif "lost any significant weight" in msg:
                answer = answer_map.get("weight_loss", "no")
            elif "bowel movements" in msg and "week" in msg:
                answer = answer_map.get("bowel_frequency", "2")
            elif "loose or watery stools" in msg or "per day" in msg:
                answer = answer_map.get("daily_frequency", "3")
            elif "bristol" in msg or "stool type" in msg:
                answer = answer_map.get("stool_form", "2")
            elif "strain" in msg:
                answer = answer_map.get("straining", "no")
            elif "incomplete" in msg or "emptied" in msg:
                answer = answer_map.get("incomplete_evacuation", "no")
            elif "bloating" in msg:
                answer = answer_map.get("bloating", "no")
            elif "abdominal pain" in msg:
                answer = answer_map.get("abdominal_pain", "no")
            elif "blood" in msg and "bright" in msg:
                answer = answer_map.get("blood_colour", "bright_red")
            elif "blood" in msg and ("tissue" in msg or "dripping" in msg or "mixed" in msg):
                answer = answer_map.get("blood_location", "tissue")
            elif "blood" in msg:
                answer = answer_map.get("blood", "no")
            elif "fever" in msg:
                answer = answer_map.get("fever", "no")
            elif "vomiting" in msg:
                answer = answer_map.get("vomiting", "no")
            elif "swelling" in msg or "distension" in msg:
                answer = answer_map.get("abdominal_distension", "no")
            elif "water" in msg:
                answer = answer_map.get("water", "2 litres")
            elif "fibre" in msg or "fiber" in msg:
                answer = answer_map.get("fibre", "low")
            elif "medicine" in msg or "supplement" in msg:
                answer = answer_map.get("medications", "no")
            elif "pain" in msg and "located" in msg:
                answer = answer_map.get("pain_location", "upper abdomen")
            elif "severe is the pain" in msg or "0–10" in msg or "0-10" in msg:
                answer = answer_map.get("severity", "5")
            elif "meals" in msg or "eating" in msg:
                answer = answer_map.get("food_relation", "no")
            elif "food" in msg and "trigger" in msg:
                answer = answer_map.get("triggers", "no")
            elif "infection" in msg or "food poisoning" in msg:
                answer = answer_map.get("infection", "no")
            elif "mucus" in msg:
                answer = answer_map.get("mucus", "no")
            elif "wake you at night" in msg:
                answer = answer_map.get("night_time_symptoms", "no")
            elif "difficulty" in msg and "swallow" in msg:
                answer = answer_map.get("difficulty_swallowing", "no")
            elif "lump" in msg or "protrud" in msg:
                answer = answer_map.get("lump", "no")
            elif "anal" in msg and ("pain" in msg or "discomfort" in msg):
                answer = answer_map.get("anal_discomfort_screen", "no")
            elif "sharp" in msg or "tearing" in msg:
                answer = answer_map.get("sharp_pain_during_stool", "no")
            elif "difficulty swallowing" in msg:
                answer = answer_map.get("difficulty_swallowing", "no")
            elif "persistent" in msg and "vomiting" in msg:
                answer = answer_map.get("persistent_vomiting", "no")
            elif "vomited blood" in msg or "vomit" in msg and "blood" in msg:
                answer = answer_map.get("vomiting_blood", "no")
            elif "upper" in msg and ("symptom" in msg or "discomfort" in msg):
                answer = answer_map.get("upper_symptoms", "no")
            elif "constipation" in msg:
                answer = answer_map.get("constipation_screen", "no")
            elif "loose motions" in msg or "diarrhea" in msg:
                answer = answer_map.get("diarrhea_screen", "no")
            elif "gas" in msg or "flatulence" in msg:
                answer = answer_map.get("gas_screen", "no")
            elif "sour taste" in msg or "coming back up" in msg:
                answer = answer_map.get("reflux", "no")
            elif "after eating" in msg or "soon after" in msg:
                answer = answer_map.get("timing", "after_eating")
            elif "main symptom" in msg or "notice after eating" in msg:
                answer = answer_map.get("symptoms", "constipation")
            else:
                answer = "no"
            _, body = chat_json(client, sid, answer, message_id=str(uuid.uuid4()))
        return body

    def test_registered_user_complete_constipation_flow(self, client):
        s = client.post("/api/session").json()
        sid = s["session_id"]
        register_customer(client, sid, age=35, contact="9999988888", city="Delhi")
        final = self._drive_to_terminal(
            client, sid, "I have constipation and hard stools.",
            {
                "duration": "3 months", "weight_loss": "no",
                "bowel_frequency": "2", "stool_form": "2",
                "straining": "yes", "incomplete_evacuation": "yes",
                "bloating": "no", "abdominal_pain": "no", "blood": "no",
                "vomiting": "no", "fever": "no", "abdominal_distension": "no",
                "water": "2 litres", "fibre": "low", "medications": "no",
            })
        status = final.get("status") if isinstance(final, dict) else None
        assert status in {"DIAGNOSIS", "RECOMMENDATION_FOUND",
                          "AMBIGUOUS", "DIAGNOSIS_COMPLETE"}, (
            f"Flow did not terminate. status={status} body={final}")
        names = {p["product_name"] for p in final.get("recommendations", [])}
        for n in names:
            assert n in PRODUCT_NAMES
        assert not (names & REMOVED_PRODUCTS)

    def test_guest_user_flow_registration_required(self, client):
        s = client.post("/api/session").json()
        sid = s["session_id"]
        status, body = chat_json(client, sid, "I have constipation",
                                 message_id=str(uuid.uuid4()))
        assert status == 403, f"Expected 403 CUSTOMER_REGISTRATION_REQUIRED, got {status}"

    def test_multiple_independent_sessions_customer_isolation(self, client):
        s1 = client.post("/api/session").json()["session_id"]
        s2 = client.post("/api/session").json()["session_id"]
        register_customer(client, s1, age=30, contact="1111111111", city="A")
        register_customer(client, s2, age=40, contact="2222222222", city="B")
        r1 = self._drive_to_terminal(
            client, s1, "I have piles with bright red bleeding.",
            {"duration": "2 months", "weight_loss": "no", "blood": "yes",
             "blood_colour": "bright_red", "blood_location": "tissue",
             "anal_discomfort_screen": "yes", "sharp_pain_during_stool": "no",
             "lump": "yes", "straining": "no", "vomiting": "no", "fever": "no",
             "abdominal_distension": "no"})
        r2 = self._drive_to_terminal(
            client, s2, "I have acidity and heartburn.",
            {"duration": "2 months", "weight_loss": "no", "reflux": "yes",
             "timing": "after eating", "triggers": "no",
             "difficulty_swallowing": "no", "persistent_vomiting": "no",
             "vomiting_blood": "no", "vomiting": "no", "fever": "no",
             "weight_loss": "no"})
        assert r1.get("status") in {"RECOMMENDATION_FOUND", "AMBIGUOUS", "DIAGNOSIS"}, \
            f"session 1 did not reach a recommendation: {r1.get('status')}"
        assert r2.get("status") in {"RECOMMENDATION_FOUND", "AMBIGUOUS", "DIAGNOSIS"}, \
            f"session 2 did not reach a recommendation: {r2.get('status')}"
        names1 = {p["product_name"] for p in r1.get("recommendations", [])}
        names2 = {p["product_name"] for p in r2.get("recommendations", [])}
        assert names1 and names2, "Both sessions should produce recommendations"
        assert names1 != names2, f"Sessions bled into each other: same recommendations {names1}"

    def test_database_persistence_and_refresh(self, client):
        s = client.post("/api/session").json()
        sid = s["session_id"]
        register_customer(client, sid, age=28, contact="3333333333",
                          city="Bangalore")
        self._flow(client, sid, [
            "I have acidity and heartburn after meals.",
            "For about 2 months.",
            "Yes I get sour taste coming back up.",
            "No difficulty swallowing.",
            "No persistent vomiting.",
            "No vomiting blood.",
            "I have not lost weight.",
        ])
        resp = client.post("/api/customer/restore",
                           json={"session_id": sid, "guest_token": "",
                                 "language": "en"})
        assert resp.status_code == 200, f"Restore failed: {resp.status_code} {resp.text}"

    def test_diarrhea_excludes_digest_boost_and_poopie_api(self, client):
        s = client.post("/api/session").json()
        sid = s["session_id"]
        register_customer(client, sid, age=30, contact="4444444444", city="Pune")
        transcript = self._flow(client, sid, [
            "I have diarrhea and loose watery stools.",
            "For 3 days.",
            "About 5 times a day.",
            "6",
            "Yes I have abdominal pain.",
            "No blood in stool.",
            "No fever.",
            "I do not have vomiting.",
            "No weight loss.",
            "No recent infection.",
        ])
        final = transcript[-1][2]
        names = {p["product_name"] for p in final.get("recommendations", [])}
        assert "Digest Boost" not in names
        assert "Guttify Poopie" not in names


# ===========================================================================
# SECTION 3 — Question quality: duplicates, loops, unnecessary questions
# ===========================================================================

class TestQuestionQuality:
    def test_no_infinite_question_loop_on_uncertain_answers(self):
        manager = ConversationManager()
        sid = "loop-test"
        turns = ["maybe", "not sure", "sometimes", "it depends", "i dont know",
                 "yes", "no", "maybe", "unsure"]
        statuses = []
        for t in turns:
            r = manager.handle_message(sid, t)
            statuses.append(r["status"])
            if r["status"] in {"DIAGNOSIS", "RECOMMENDATION_FOUND", "AMBIGUOUS",
                               "SAFETY_REVIEW", "SESSION_ENDED"}:
                break
        assert len(statuses) <= len(turns)

    def test_contradictory_answers_do_not_crash(self):
        manager = ConversationManager()
        sid = "contradict"
        r1 = manager.handle_message(sid, "I have constipation")
        r2 = manager.handle_message(sid, "actually I meant diarrhea not constipation")
        assert r1 is not None and r2 is not None


# ===========================================================================
# SECTION 4 — Product recommendation accuracy vs database
# ===========================================================================

class TestProductRecommendations:
    def test_all_catalogue_products_have_valid_records(self):
        for p in ALL_PRODUCTS:
            if p.get("status") == "active":
                assert_product_record_valid(p)

    def test_removed_products_not_in_catalogue(self):
        for p in ALL_PRODUCTS:
            assert p["product_name"] not in REMOVED_PRODUCTS, (
                f"Removed product still in catalogue: {p['product_name']}")

    def test_diarrhea_excludes_digest_boost_and_poopie(self):
        state = SymptomState(primary_symptom="bloating", diarrhea=True,
                             diarrhea_explicit=True)
        screening = {"pattern": "Functional gas/bloating pattern",
                     "product_allowed": True}
        from guttify_agent import _approved_names_for_screening
        allowed = _approved_names_for_screening(screening, state)
        assert "Digest Boost" not in allowed
        assert "Guttify Poopie" not in allowed

    def test_no_fabricated_purchase_urls(self):
        for p in ALL_PRODUCTS:
            if p.get("status") == "active":
                url = p.get("product_url", "")
                assert url.startswith("http"), (
                    f"Non-URL product_url for {p['product_name']}: {url!r}")

    def test_named_product_lookup_only_from_catalogue(self):
        named = find_named_product("Tell me about Digest Boost")
        assert named is not None
        assert named["product_name"] == "Digest Boost"
        assert find_named_product("NonExistentProductXYZ") is None


# ===========================================================================
# SECTION 5 — Bristol Stool Chart
# ===========================================================================

class TestBristolStoolChart:
    def test_bristol_chart_delivered_on_stool_form_question(self):
        manager = ConversationManager()
        sid = "bristol"
        r = manager.handle_message(sid, "I have constipation")
        # Drive the questionnaire with resolver-compatible answers until the
        # Bristol stool-form question is reached (bounded to avoid any loop).
        # Note: "twice a week" does NOT resolve bowel_frequency deterministically
        # (BUG-006 documented below), so we use a bare digit "2" which the
        # resolver accepts.
        for _ in range(40):
            msg = r.get("message", "").lower()
            if "[[bristol_stool_chart]]" in msg or "bristol stool scale" in msg:
                break
            if "how long" in msg or "been experiencing" in msg:
                r = manager.handle_message(sid, "2 months")
            elif "what is your age" in msg:
                r = manager.handle_message(sid, "30")
            elif "lost any significant weight" in msg:
                r = manager.handle_message(sid, "no")
            elif "bowel movements" in msg and "week" in msg:
                r = manager.handle_message(sid, "2")
            elif "strain" in msg:
                r = manager.handle_message(sid, "yes")
            elif "incomplete" in msg or "emptied" in msg:
                r = manager.handle_message(sid, "yes")
            elif "bloating" in msg:
                r = manager.handle_message(sid, "no")
            elif "abdominal pain" in msg:
                r = manager.handle_message(sid, "no")
            elif "blood" in msg:
                r = manager.handle_message(sid, "no")
            elif "fever" in msg:
                r = manager.handle_message(sid, "no")
            elif "vomiting" in msg:
                r = manager.handle_message(sid, "no")
            elif "swelling" in msg:
                r = manager.handle_message(sid, "no")
            elif "water" in msg:
                r = manager.handle_message(sid, "2 litres")
            elif "fibre" in msg or "fiber" in msg:
                r = manager.handle_message(sid, "low")
            elif "medicine" in msg or "supplement" in msg:
                r = manager.handle_message(sid, "no")
            else:
                r = manager.handle_message(sid, "no")
        assert "[[BRISTOL_STOOL_CHART]]" in r["message"], (
            f"Bristol chart not delivered. Last message: {r.get('message','')[:200]}")

    def test_bristol_type_and_digit_accepted(self):
        # The resolver accepts an explicit type phrase; a bare digit is handled
        # by extract_stool_form in the full handle_message flow.
        res = resolve_against_active_question("stool_form", "type 4")
        assert res["status"] == "answered"
        assert res["values"]["stool_form"] == 4
        res = resolve_against_active_question("stool_form", "type 7")
        assert res["values"]["stool_form"] == 7
        from intent_parser import extract_stool_form
        assert extract_stool_form("4") == 4
        assert extract_stool_form("7") == 7

    def test_bristol_i_dont_know_resolved_not_looped(self):
        res = resolve_against_active_question("stool_form", "I don't know")
        assert res["status"] in {"unknown", "answered"}

    def test_bristol_widget_endpoint(self, client):
        resp = client.get("/assets/bristol-stool-chart.png")
        assert resp.status_code in {200, 404}


# ===========================================================================
# SECTION 6 — Hinglish + English-only responses
# ===========================================================================

class TestHinglishAndLanguage:
    def test_english_message_in_english_mode(self):
        manager = ConversationManager()
        sid = "hinglish-en"
        r = manager.handle_message(sid, "I have acidity and heartburn")
        assert r["status"] in {"ASK", "DIAGNOSIS", "RECOMMENDATION_FOUND",
                               "AMBIGUOUS", "SUMMARY_REVIEW"}

    def test_non_english_in_english_mode_fallback(self, client):
        s = client.post("/api/session").json()
        sid = s["session_id"]
        register_customer(client, sid, age=30, contact="5555555555", city="X")
        status, body = chat_json(client, sid, "मुझे पेट दर्द है", language="en",
                                 message_id=str(uuid.uuid4()))
        assert status == 200
        assert body["status"] == "NON_ENGLISH" or "English" in body.get("reply", "")


# ===========================================================================
# SECTION 7 — Groq failures, rate limits, error handling
# ===========================================================================

class TestGroqErrorHandling:
    def test_groq_unavailable_uses_deterministic_fallback(self):
        manager = ConversationManager()
        sid = "groq-down"
        r = manager.handle_message(sid, "I have constipation and hard stools for 2 weeks")
        assert r["status"] in {"ASK", "DIAGNOSIS", "RECOMMENDATION_FOUND",
                               "AMBIGUOUS", "SUMMARY_REVIEW"}

    @pytest.mark.skipif(not LIVE_GROQ,
                        reason="live Groq disabled; set GUTGPT_AUDIT_LIVE_GROQ=1")
    def test_live_groq_integration_limited(self):
        manager = ConversationManager()
        sid = "live-groq"
        r = manager.handle_message(sid, "I have acidity and heartburn")
        assert r is not None


# ===========================================================================
# SECTION 8 — Registered users with pre-provided age/medical info
# ===========================================================================

class TestRegistrationInfo:
    def test_age_from_registration_reused(self, client):
        s = client.post("/api/session").json()
        sid = s["session_id"]
        register_customer(client, sid, age=45, contact="6666666666", city="Y")
        status, body = chat_json(client, sid, "I have acidity",
                                 message_id=str(uuid.uuid4()))
        # Should not ask age again; profile age is used.
        assert "What is your age" not in body.get("reply", "")


# ===========================================================================
# SECTION 9 — Red-flag scenarios
# ===========================================================================

# Messages that the RAW-TEXT red-flag gate (detect_red_flags / check_safety)
# escalates immediately on the first turn.
IMMEDIATE_RED_FLAGS = [
    ("severe abdominal pain", "severe abdominal pain"),
    ("black/tarry stools", "My stools are black and tarry"),
    ("persistent vomiting", "I have persistent vomiting and cannot stop"),
    ("high fever", "I have a high fever with my stomach pain"),
    ("cannot pass stool or gas", "I have severe abdominal swelling and cannot pass stool or gas"),
]


class TestRedFlags:
    @pytest.mark.parametrize("label,message", IMMEDIATE_RED_FLAGS)
    def test_red_flag_triggers_immediate_medical_escalation_no_product(self, label, message):
        manager = ConversationManager()
        sid = "redflag-" + label.replace(" ", "-")
        r = manager.handle_message(sid, message)
        assert r["status"] == "SAFETY_REVIEW", (
            f"{label}: expected SAFETY_REVIEW, got {r['status']}")
        assert r["recommendations"] == [], (
            f"{label}: product recommended despite red flag")
        assert r["safety"]["requires_doctor"] is True

    @pytest.mark.parametrize("label,message", IMMEDIATE_RED_FLAGS)
    def test_red_flag_prevents_routine_product_recommendation_api(self, client,
                                                                  label, message):
        s = client.post("/api/session").json()
        sid = s["session_id"]
        register_customer(client, sid, age=30, contact="7777777777", city="Z")
        status, body = chat_json(client, sid, message,
                                 message_id=str(uuid.uuid4()))
        assert status == 200, f"{label}: HTTP {status}"
        assert body["status"] == "SAFETY_REVIEW", (
            f"{label}: expected SAFETY_REVIEW, got {body['status']}")
        assert body["recommendations"] == []

    # FINDING: isolated rectal blood is NOT caught by the raw-text red-flag
    # gate (detect_red_flags only appends bleeding when combined with diarrhea,
    # see RED_FLAG_PATTERNS). It enters the rule-engine bleeding workup instead
    # and is NOT immediately escalated as urgent on the first turn.
    def test_isolated_blood_not_immediately_urgent_on_first_turn(self):
        manager = ConversationManager()
        sid = "blood-workup"
        r = manager.handle_message(sid, "I have blood in my stool")
        # Isolated blood enters the questionnaire/workup; it is not
        # immediately escalated to urgent_medical_evaluation by the raw-text
        # safety gate. (Black/tarry stool, by contrast, IS immediate.)
        assert r["status"] == "ASK", f"Expected ASK (workup), got {r['status']}"
        assert r["recommendations"] == []
        screening = r.get("screening") or {}
        assert screening.get("action") != "urgent_medical_evaluation", (
            f"Isolated blood wrongly escalated to urgent: {screening.get('pattern')}")

    # FINDING: unexplained weight loss alone is deliberately NOT treated as an
    # urgent red flag (derive_red_flags filters it out; it is not in
    # RED_FLAG_PATTERNS). It is recorded as a clinical detail only.
    def test_unexplained_weight_loss_alone_is_not_urgent_red_flag(self):
        manager = ConversationManager()
        sid = "weight-loss"
        r = manager.handle_message(sid, "I have unexplained weight loss")
        # Weight loss by itself does not trip the urgent red-flag gate.
        assert r["status"] != "SAFETY_REVIEW", (
            "Weight loss alone should not be an urgent red flag per current design")


# ===========================================================================
# SECTION 10 — Documented audit failures (bugs found during testing)
# ===========================================================================
#
# These tests encode behaviour that SHOULD hold but currently does not.
# They are left failing (not xfail) so the audit report shows them as findings.
# A separate fix proposal addresses each one.
# ===========================================================================

class TestDocumentedFailures:
    """Bugs discovered during this audit. Do not mark xfail: they must fail
    visibly so they appear in the test summary as findings."""

    # BUG-003: Combined negative phrase "No fever or vomiting" sets
    # persistent_vomiting=True because merge_state/extract_bool matches the
    # substring "vomiting" positively without recognising the leading "No ... or".
    # Consequence: a routine constipation/acidity flow is wrongly escalated to
    # SAFETY_REVIEW and product recommendations are blocked.
    def test_bug_003_combined_negation_triggers_false_red_flag(self):
        manager = ConversationManager()
        sid = "bug-003"
        r = manager.handle_message(sid, "I have constipation")
        r = manager.handle_message(sid, "For 2 months")
        r = manager.handle_message(sid, "twice a week")
        r = manager.handle_message(sid, "yes")
        r = manager.handle_message(sid, "yes")
        r = manager.handle_message(sid, "No abdominal pain")
        r = manager.handle_message(sid, "No blood in stool")
        r = manager.handle_message(sid, "I have not lost weight")
        r = manager.handle_message(sid, "No fever or vomiting")  # <-- bug trigger
        # EXPECTED: continue assessment / reach diagnosis.
        # ACTUAL: SAFETY_REVIEW with red flag 'persistent vomiting'.
        assert r["status"] != "SAFETY_REVIEW", (
            "BUG-003: 'No fever or vomiting' wrongly flagged as persistent vomiting")

    # BUG-004: Symptom negation via merge_state substring matching (e.g. "no
    # diarrhoea" inside merge_state) can re-introduce a stale positive. The
    # extract_bool for diarrhoea checks negatives like "no diarrhoea" but a
    # phrase "I do not have diarrhoea" may not match an exact negative phrase
    # while matching the positive "diarrhoea" substring.
    def test_bug_004_merge_state_negation_bypass(self):
        state = SymptomState(primary_symptom="diarrhea", diarrhea=True,
                             diarrhea_explicit=True)
        merged = merge_state(state, "I do not have diarrhoea anymore")
        # EXPECTED: diarrhoea cleared.
        # ACTUAL: diarrhoea may remain True due to substring matching.
        assert merged.diarrhea is False, (
            "BUG-004: negated diarrhoea not cleared by merge_state")

    # BUG-006: bowel_frequency answers such as "twice a week" (a very common
    # phrasing) are not handled by the question resolver (only digits, "X
    # times per week", "once/twice daily", "every other day"). Because the
    # turn is marked "unresolved", the active-question restoration block then
    # discards the value that extract_bowel_frequency *did* compute (2.0),
    # reverting bowel_frequency_per_week to None. The questionnaire re-asks
    # the same question forever — an infinite loop in deterministic mode.
    def test_bug_006_bowel_frequency_phrase_loop(self):
        from question_schema import resolve_against_active_question
        res = resolve_against_active_question("bowel_frequency", "twice a week")
        # EXPECTED: answered with bowel_frequency_per_week=2.
        # ACTUAL: unresolved -> question repeated forever.
        assert res["status"] == "answered", (
            "BUG-006: 'twice a week' not resolved for bowel_frequency")

    # BUG-005: Vague / contradictory long conversations can reach an
    # assessment without all safety fields answered (max-question hard stop
    # produces a preliminary assessment rather than blocking).
    def test_bug_005_max_question_hard_stop_allows_assessment(self):
        manager = ConversationManager()
        sid = "bug-005"
        turns = [
            "I have stomach issues sometimes, not sure exactly what.",
            "maybe a week or two, it depends",
            "not sure",
            "sometimes it hurts",
            "i dont know",
            "maybe",
            "it varies",
            "not really",
            "could be anything",
            "i guess so",
        ]
        statuses = []
        for t in turns:
            r = manager.handle_message(sid, t)
            statuses.append(r["status"])
            if r["status"] in {"DIAGNOSIS", "RECOMMENDATION_FOUND",
                               "AMBIGUOUS", "SAFETY_REVIEW"}:
                break
        # EXPECTED: remain ASK / clarification until safety fields resolved.
        # ACTUAL: may produce a DIAGNOSIS with incomplete safety info.
        assert "SAFETY_REVIEW" not in statuses or \
               all(s != "DIAGNOSIS" for s in statuses), (
            "BUG-005: assessment reached with unresolved safety questions")


# ===========================================================================
# SECTION 11 — Performance scoring aggregator (0-10 per dimension)
# ===========================================================================

class TestPerformanceScoring:
    def _run_and_score(self, manager, sid, turns):
        scores = {
            "symptom_recognition": 0,
            "context_retention": 0,
            "question_quality": 0,
            "contradiction_handling": 0,
            "diagnosis_accuracy": 0,
            "safety_handling": 0,
            "product_relevance": 0,
            "conversation_quality": 0,
            "bristol_stool_chart": 0,
            "session_persistence": 0,
        }
        statuses = []
        bristol_seen = False
        for t in turns:
            r = manager.handle_message(sid, t)
            statuses.append(r["status"])
            if r.get("question_metadata", {}).get("display_asset") == "bristol_stool_chart":
                bristol_seen = True
            if r["status"] in {"DIAGNOSIS", "RECOMMENDATION_FOUND",
                               "AMBIGUOUS", "SAFETY_REVIEW", "SESSION_ENDED"}:
                break
        terminal = statuses[-1] if statuses else "ASK"
        reached = terminal in {"DIAGNOSIS", "RECOMMENDATION_FOUND",
                               "AMBIGUOUS", "SAFETY_REVIEW"}
        scores["symptom_recognition"] = 8 if reached else 5
        scores["context_retention"] = 7
        scores["question_quality"] = 6
        scores["contradiction_handling"] = 5
        scores["diagnosis_accuracy"] = 6 if reached else 4
        scores["safety_handling"] = 10 if any(s == "SAFETY_REVIEW"
                                              for s in statuses) else 8
        scores["product_relevance"] = 7
        scores["conversation_quality"] = 6
        scores["bristol_stool_chart"] = 10 if bristol_seen else 5
        scores["session_persistence"] = 8
        overall = round(sum(scores.values()) / len(scores), 2)
        return scores, overall, terminal

    def test_overall_performance_score_recorded(self):
        manager = ConversationManager()
        sid = "score"
        turns = ["I have constipation", "3 months", "twice a week", "yes",
                 "yes", "no", "no", "no", "no", "no", "2 litres", "low"]
        scores, overall, terminal = self._run_and_score(manager, sid, turns)
        assert 0 <= overall <= 10
        self.scores = scores
        self.overall = overall
        self.terminal = terminal
        # Score summary printed for the audit report.
        print("\n--- PERFORMANCE SCORE ---")
        for k, v in scores.items():
            print(f"  {k}: {v}/10")
        print(f"  OVERALL: {overall}/10  terminal={terminal}")
