"""Заглушка: жалобы (`/reports`, ban-пайплайн) не входят в MVP-срез
(поиск + чат), см. CLAUDE.md — "Чего избегать" и project-structure.md 6.5.
Тесты появятся вместе с модулем модерации.
"""

import pytest


@pytest.mark.skip(reason="модуль жалоб/модерации не входит в MVP-срез (поиск + чат)")
def test_reports_placeholder():
    pass
