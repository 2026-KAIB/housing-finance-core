"""화면용 대시보드: 판정이 맨 위에 오고, 엔진 수치와 AI 서술이 구분되는가.

렌더러는 순수 함수이므로 네트워크가 필요 없다. AI 서술은 가짜 생성기로 채운다.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.reports.ai_explanation.gemini import GenerationResult
from app.reports.ai_explanation.pipeline import FinalReport, build_final_report
from app.reports.templates.form import FORM_SECTIONS
from app.reports.templates.html import collect_product_terms, render_report_html
from app.rule_engine.product_packs.handoff import ProductCandidate
from app.schemas.report import ReportAIInput
from app.schemas.simulation import SectionRunStatus, SimulationResult
from tests.reports.conftest import EXPECTED_AMOUNT_LABEL, MORTGAGE_PRODUCT

_KEYS = tuple(key for key, _title in FORM_SECTIONS)
_CLEAN = "표시된 수치의 의미를 설명하는 문장입니다."


@dataclass
class FakeClient:
    result: GenerationResult
    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
    ) -> GenerationResult:
        self.calls.append({"user_prompt": user_prompt})
        return self.result


def _settings() -> Settings:
    return Settings(_env_file=None).model_copy(
        update={"gemini_api_key": None, "report_ai_egress_guard": True}
    )


def _report(report_input: ReportAIInput, narration: str = _CLEAN, **overrides: str) -> FinalReport:
    writer_payload = {key: narration for key in _KEYS}
    writer_payload.update(overrides)
    judge_payload = {key: {"verdict": "OK", "reason": ""} for key in _KEYS}
    return build_final_report(
        report_input,
        writer_client=FakeClient(
            GenerationResult(text=json.dumps(writer_payload, ensure_ascii=False), model="w")
        ),
        judge_client=FakeClient(
            GenerationResult(text=json.dumps(judge_payload, ensure_ascii=False), model="j")
        ),
        settings=_settings(),
    )


class TestVerdictComesFirst:
    def test_the_product_count_is_stated_before_the_option_count(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        """"6 실행 가능"만 쓰면 상품 6개로 읽힌다. 실제로는 한 상품의 옵션 6개다."""
        html = render_report_html(_report(report_input), simulation)

        headline = html.index("금리·상환방식 옵션")
        tiles = html.index('class="tiles"')
        assert headline < tiles, "상품/옵션 구분이 타일보다 먼저 나와야 한다"
        assert "상품 <strong>1건</strong>" in html

    def test_the_verdict_board_precedes_every_chart(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        html = render_report_html(_report(report_input), simulation)

        assert html.index('class="tiles"') < html.index("자금 조달 구성")
        assert html.index('class="tiles"') < html.index("생활 스트레스 시나리오")

    def test_each_status_carries_an_icon_and_a_label(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        """상태색 `#fab219`는 흰 배경에서 1.83:1이다. 색 단독으로 읽히면 안 된다."""
        html = render_report_html(_report(report_input), simulation)

        for label in ("실행 가능", "최소금액 미달", "입력 부족", "자격 미달"):
            assert label in html
        assert html.count('class="tile-icon" aria-hidden="true"') == 4


class TestFigures:
    def test_amounts_are_whole_won(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        html = render_report_html(_report(report_input), simulation)

        assert EXPECTED_AMOUNT_LABEL in html
        assert ".8125" not in html

    def test_the_shortfall_names_its_basis(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        html = render_report_html(_report(report_input), simulation)

        assert "필요 대출금액 대비" in html
        assert "목표 금액 대비" not in html

    def test_both_rates_appear_with_the_assessment_warning(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        html = render_report_html(_report(report_input), simulation)

        assert "실제 적용 금리" in html
        assert "심사용 금리" in html
        assert "실제로 내는 금리가 아닙니다" in html

    def test_every_bar_carries_a_direct_label(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        """aqua는 흰 배경에서 2.82:1이라 값 라벨이 필수 완화 조치다."""
        html = render_report_html(_report(report_input), simulation)

        assert html.count('class="bar-fill') == html.count('class="bar-value"')

    def test_marks_carry_hover_titles(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        html = render_report_html(_report(report_input), simulation)

        assert html.count("title=") >= 5


class TestProductTerms:
    def test_terms_are_rendered_verbatim_when_supplied(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
        product_terms: dict[str, dict[str, str]],
    ) -> None:
        html = render_report_html(_report(report_input), simulation, product_terms=product_terms)

        assert "우대금리 · 부대비용 조건" in html
        assert "최고 연 1.4%p 우대" in html
        assert "자동 판정하지 않으므로" in html

    def test_no_terms_section_without_data(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        """원천 조건이 없으면 그 절을 만들지 않는다 — 빈 카드를 보이지 않는다."""
        html = render_report_html(_report(report_input), simulation)

        assert "우대금리 · 부대비용 조건" not in html

    def test_collect_product_terms_reads_only_display_fields(self) -> None:
        candidate = ProductCandidate(
            product_name=MORTGAGE_PRODUCT,
            base_data={
                "fin_prdt_nm": MORTGAGE_PRODUCT,
                "spcl_cnd": "우대 조건 원문",
                "join_deny": "1",
            },
        )

        terms = collect_product_terms([candidate])

        assert terms[MORTGAGE_PRODUCT] == {"spcl_cnd": "우대 조건 원문"}
        # 자유텍스트 자격조건은 표시 대상이 아니다(자동 판정 금지 규약).
        assert "join_deny" not in terms[MORTGAGE_PRODUCT]


class TestNarrationBoundary:
    def test_adopted_narration_is_labelled_as_ai(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        html = render_report_html(_report(report_input), simulation)

        assert "AI 설명" in html
        assert _CLEAN in html

    def test_a_blocked_section_shows_its_reason_and_keeps_figures(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        html = render_report_html(
            _report(report_input, base_vs_stress="최악 DSR은 45.55%입니다."),
            simulation,
        )

        assert "미채택" in html
        assert "number_in_narration" in html
        assert "계산 엔진 산출값이므로 그대로 유효합니다" in html
        # 같은 수치는 엔진 렌더링으로 남는다.
        assert "45.55%" in html

    def test_model_output_is_escaped(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        """서술은 외부 모델이 만든 문자열이므로 그대로 HTML에 넣지 않는다."""
        html = render_report_html(
            _report(report_input, narration="<script>alert(1)</script>"),
            simulation,
        )

        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestDocumentShape:
    def test_both_themes_are_declared(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        html = render_report_html(_report(report_input), simulation)

        assert "prefers-color-scheme:dark" in html
        assert '[data-theme="dark"]' in html
        assert '[data-theme="light"]' in html

    def test_tags_are_balanced(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        html = render_report_html(_report(report_input), simulation)
        body = html.split("</style>", 1)[1]

        for tag in ("div", "section", "table", "tbody", "tr", "td", "ul", "li", "dl", "footer"):
            opened = len(re.findall(rf"<{tag}[\s>]", body))
            closed = len(re.findall(rf"</{tag}>", body))
            assert opened == closed, f"{tag}: 열림 {opened} 닫힘 {closed}"

    def test_it_survives_a_report_with_no_loan_section(
        self,
        report_input: ReportAIInput,
        simulation: SimulationResult,
    ) -> None:
        """대출 구간이 NOT_RUN이어도 렌더링이 깨지지 않고 사유를 보여준다."""
        bare = simulation.model_copy(
            update={
                "loan_simulation": simulation.loan_simulation.model_copy(
                    update={
                        "run_status": SectionRunStatus.NOT_RUN,
                        "engine_status": None,
                        "result": None,
                        "reasons": ("상품 후보가 없습니다.",),
                    }
                )
            }
        )

        html = render_report_html(_report(report_input), bare)

        assert "대출 계산이 실행되지 않았습니다" in html
        assert "상품 후보가 없습니다." in html
