"""Persisted user-message memory, without a new DB table or model-written facts."""
from uuid import uuid4

from api.ai.conversation_history import load_conversation_context, MEMORY_USER_MESSAGES
from api.ai.dialogue import prompt_user_inputs
from api.ai.user_facts import collect_user_facts


PAY = "Brüt ücretim 40000 TL. İşe giriş 01.01.2010, işten çıkış 01.01.2020."
FOLLOWUP = "İhbar tazminatının koşullarını da açıklar mısın?"


class HistoryDB:
    def __init__(self, questions, *, visible=True):
        self.questions, self.visible, self.calls = questions, visible, []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        db = self
        class Result:
            def fetchone(self):
                return {"project_id":None} if db.visible else None
            def fetchall(self):
                if "role = 'user'" in sql:
                    return [{"role":"user", "content":q, "metadata":{}} for q in reversed(db.questions[-params[1]:])]
                rows = []
                for q in db.questions:
                    rows.extend([{"role":"user", "content":q, "metadata":{}},
                                 {"role":"assistant", "content":"Kaynaklı açıklama.", "metadata":{"grounded":True}}])
                return list(reversed(rows))[:params[1]]
        return Result()


def test_old_pay_and_dates_survive_far_beyond_the_recent_transcript():
    questions = ["İşten çıkarıldım, tazminatımı hesaplar mısın?", PAY] + [FOLLOWUP]*60
    db = HistoryDB(questions)
    conversation = uuid4()
    context = load_conversation_context(db, conversation)
    assert len(context.turns) == 2 and len(context.questions) == len(questions)
    facts = collect_user_facts("Toplam tutarı hesaplayabilir misin?", prior_questions=context.questions)
    assert str(facts.amount) == "40000" and str(facts.start_date) == "2010-01-01"
    assert str(facts.end_date) == "2020-01-01"
    memory_sql, params = db.calls[-1]
    assert "deleted_at IS NULL" in memory_sql and "role = 'user'" in memory_sql
    assert params == (conversation, MEMORY_USER_MESSAGES)


def test_invisible_conversation_never_reads_memory():
    from api.ai.conversation_history import ConversationNotFound
    import pytest
    db = HistoryDB([PAY], visible=False)
    with pytest.raises(ConversationNotFound):
        load_conversation_context(db, uuid4())
    assert len(db.calls) == 1


def test_prompt_is_compact_but_preserves_exact_fact_statement_and_original_index():
    prior = ["İşten çıkarıldım ne kadar tazminat alırım?", PAY] + [FOLLOWUP]*60
    entries = prompt_user_inputs("Toplamı hesaplar mısın?", prior_questions=prior)
    assert len(entries) <= 16
    assert {"question_index":1,"text":PAY} in entries
    assert entries[-1]["question_index"] == len(prior)
    assert all("origin" not in entry and entry["text"] in [*prior, "Toplamı hesaplar mısın?"] for entry in entries)


def test_latest_correction_remains_effective_after_many_more_followups():
    prior = ["İşten çıkarıldım ne kadar tazminat alırım?", PAY] + [FOLLOWUP]*30
    prior += ["Düzeltme: brüt ücretim 45000 TL."] + [FOLLOWUP]*30
    facts = collect_user_facts("Hesaplayalım mı?", prior_questions=prior)
    assert str(facts.amount) == "45000"
    entries = prompt_user_inputs("Hesaplayalım mı?", prior_questions=prior)
    assert any("45000" in e["text"] for e in entries)
    assert str(facts.start_date) == "2010-01-01"
    assert next(r.question_index for r in facts.records if r.field == "pay_amount") == 32


def test_invalid_date_correction_does_not_restore_old_valid_date():
    prior = ["İşten çıkarıldım ne kadar tazminat alırım?", PAY] + [FOLLOWUP]*30
    correction = "Düzeltme: işten çıkış tarihim 31.02.2020."
    prior += [correction] + [FOLLOWUP]*30
    facts = collect_user_facts("Hesaplayalım mı?", prior_questions=prior)
    assert facts.end_date is None and "invalid_employment_end" in facts.issues
    assert any(e["text"] == correction for e in prompt_user_inputs("Hesaplayalım mı?", prior_questions=prior))


def test_new_clients_event_does_not_inherit_the_previous_clients_salary():
    prior = ["İşten çıkarıldım ne kadar tazminat alırım?", PAY] + [FOLLOWUP]*30
    facts = collect_user_facts("Başka bir müvekkil için işten çıkarılma durumuna bakalım.", prior_questions=prior)
    assert facts.amount is None and facts.start_date is None and facts.end_date is None
