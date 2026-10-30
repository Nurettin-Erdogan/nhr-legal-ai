"""The cheap one-topic shortcut must not hide explicit follow-up requests."""
import json

import pytest

from api.ai.free_answer import plan_question, simple_search_plan


@pytest.mark.parametrize('question', [
    'İşe iade şartları nelerdir hangi sürede başvurulur',
    'Yıllık izin kaç gündür nasıl hesaplanır',
    'Kıdem tazminatı nedir ne zaman ödenir',
    'İşe iade şartları nelerdir? Başvuru süresini açıkla',
    'İşe iade nasıl istenir kaç gün içinde başvurulur',
])
def test_multiple_requests_do_not_take_single_topic_shortcut(question):
    assert simple_search_plan(question) is None


@pytest.mark.parametrize('question', [
    'İşe iade şartları nelerdir?',
    'Yıllık izin kaç gündür?',
    'Kıdem tazminatı nasıl hesaplanır?',
])
def test_single_request_keeps_the_no_model_shortcut(question):
    assert simple_search_plan(question) is not None


def test_unpunctuated_requests_reach_planner_and_keep_both_search_lanes():
    class Planner:
        calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            return json.dumps({'legal': True, 'parts': [
                {'question': 'İşe iade koşulları nelerdir?', 'queries': ['işe iade koşulları']},
                {'question': 'İşe iade başvuru süresi nedir?', 'queries': ['işe iade başvuru süresi']},
            ]})

    provider = Planner()
    question = 'İşe iade şartları nelerdir hangi sürede başvurulur'
    plan = plan_question(provider, question)
    assert len(provider.calls) == 1
    assert json.loads(provider.calls[0]['prompt'])['question'] == question
    assert len(plan) == 2
    assert plan[1][1] == ('işe iade başvuru süresi',)
