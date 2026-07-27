"""마이데이터 Mock 생성기 — 기본 페르소나와 사용자 정의 테스트 페르소나

설계 원칙
- 표준 API 응답 형식만 출력 (계산 결과 미포함)
- 시나리오는 역산으로 구성 (월 상환액 → balance_amt/rate/exp_date)
- 거래내역 balance_amt 시계열 정합성 보장
- 대출 상환액이 거래내역 자동이체와 일치

사용법
    python3 generate_all.py [출력디렉토리] [선택 페르소나 ID]
"""
import json
import os
import random
import sys
from calendar import monthrange
from datetime import datetime, timedelta

BASE = datetime(2026, 7, 24)
MONTHS = 12
IN_TYPES = {"03", "04", "06", "98"}

OUT_ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
SELECTED_PERSONA_ID = sys.argv[2] if len(sys.argv) > 2 else None

# ══════════════════════════════════════════════════════
# 금융 계산 (역산 전용 — 출력 JSON에는 들어가지 않음)
# ══════════════════════════════════════════════════════

def pmt_equal_installment(balance, annual_rate, n_months):
    """원리금균등 월 상환액 (repay_method 04/05 거치종료후)"""
    i = annual_rate / 12
    if i == 0:
        return round(balance / n_months)
    f = (1 + i) ** n_months
    return round(balance * i * f / (f - 1))


def pmt_interest_only(balance, annual_rate):
    """이자만 (repay_method 01 만기일시, 08 한도거래, 거치기간 중)"""
    return round(balance * annual_rate / 12)


def pmt_equal_principal_first(balance, annual_rate, n_months):
    """원금균등 1회차 상환액 (repay_method 02/03)"""
    return round(balance / n_months + balance * annual_rate / 12)


def months_until(target: datetime, base: datetime = BASE):
    months = (target.year - base.year) * 12 + target.month - base.month
    if (target.day, target.time()) < (base.day, base.time()):
        months -= 1
    return months


def add_months(value: datetime, months: int) -> datetime:
    """외부 패키지 없이 월을 이동하고 말일은 대상 월의 마지막 날로 보정한다."""

    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


# ══════════════════════════════════════════════════════
# 거래내역 생성
# ══════════════════════════════════════════════════════

CARD_MERCHANTS = [
    ("GS25 역삼점", 3_000, 18_000), ("CU 논현점", 3_000, 15_000),
    ("세븐일레븐 삼성", 3_000, 14_000),
    ("이마트 성수점", 30_000, 120_000), ("홈플러스 강남", 25_000, 90_000),
    ("롯데마트 서초", 20_000, 85_000),
    ("스타벅스 삼성점", 4_500, 12_000), ("투썸플레이스 역삼", 5_000, 15_000),
    ("김밥천국 역삼", 7_000, 25_000), ("본죽 논현점", 9_000, 30_000),
    ("맘스터치 강남", 8_000, 22_000),
    ("올리브영 강남", 12_000, 45_000),
    ("SK주유소 삼성", 50_000, 90_000), ("GS칼텍스 논현", 45_000, 85_000),
]


def month_starts():
    start = add_months(BASE, -(MONTHS - 1)).replace(day=1)
    return [add_months(start, k) for k in range(MONTHS)]


def build_transactions(persona, final_balance):
    """거래 생성 → 잔액 역산 → 내림차순 반환"""
    rnd = random.Random(persona["seed"])
    txs = []

    for d0 in month_starts():
        y, mo = d0.year, d0.month

        # ── 소득 ──────────────────────────────────
        for inc in persona["incomes"]:
            # 페르소나 기준기간 중간에 일을 시작한 경우에도 실제 수입이 없던 월을
            # 급여 월로 만들지 않는다. 사용자 제공 이력과 거래내역을 일치시키기 위한
            # 선택 필드이며, 기존 페르소나는 필드가 없어 이전 동작을 그대로 유지한다.
            current_ym = f"{y:04d}{mo:02d}"
            if inc.get("start_ym") and current_ym < inc["start_ym"]:
                continue
            if inc.get("end_ym") and current_ym > inc["end_ym"]:
                continue
            amt = inc["amount"]
            memo = inc["memo"]
            if inc.get("bonus_months") and mo in inc["bonus_months"]:
                amt = amt + inc["amount"] * inc.get("bonus_multiple", 1)
                memo = inc["bonus_memo"]
            amt = int(rnd.gauss(amt, amt * inc.get("variance", 0.0))) \
                if inc.get("variance") else amt
            txs.append(dict(
                d=datetime(y, mo, inc["day"], 9, inc.get("minute", 0)),
                type="03", cls=inc.get("cls", "인터넷뱅킹"),
                amt=amt, memo=memo))

        # ── 고정 지출 ──────────────────────────────
        for k, fx in enumerate(persona["fixed_expenses"]):
            amt = fx["amount"]
            amt = int(rnd.gauss(amt, amt * fx.get("variance", 0.0))) \
                if fx.get("variance") else amt
            txs.append(dict(
                d=datetime(y, mo, fx["day"], 6, 10 + k * 5),
                type="02", cls=fx.get("cls", "자동이체"),
                amt=amt, memo=fx["memo"]))

        # ── 변동 지출 (체크카드) ────────────────────
        used = set()
        card_count = rnd.randint(*persona["card_tx_per_month"])
        card_merchants = persona.get("card_merchants", CARD_MERCHANTS)
        card_budget = persona.get("card_monthly_budget")
        if card_budget is not None:
            # 월평균 지출이 사용자에게서 직접 주어진 페르소나는 무작위 거래 건수와
            # 상점 구성을 유지하면서도 월 카드지출 합계가 입력값과 정확히 맞아야 한다.
            # 가중치 비례 배분 후 마지막 거래에서 반올림 차이를 보정한다.
            weights = [rnd.uniform(0.6, 1.4) for _ in range(card_count)]
            weight_sum = sum(weights)
            card_amounts = [
                max(500, round(card_budget * weight / weight_sum / 500) * 500)
                for weight in weights
            ]
            card_amounts[-1] += card_budget - sum(card_amounts)
        else:
            card_amounts = None
        for card_index in range(card_count):
            name, lo, hi = rnd.choice(card_merchants)
            while True:
                key = (rnd.randint(1, 28), rnd.randint(8, 21),
                       rnd.randint(0, 59), rnd.randint(0, 59))
                if key not in used:
                    used.add(key)
                    break
            txs.append(dict(
                d=datetime(y, mo, key[0], key[1], key[2], key[3]),
                type="02", cls="체크카드",
                amt=(
                    card_amounts[card_index]
                    if card_amounts is not None
                    else rnd.randrange(lo, hi, 500)
                ),
                memo=name))

        # ── 이자 지급 (분기) ────────────────────────
        if mo in (3, 6, 9, 12):
            txs.append(dict(d=datetime(y, mo, 28, 6, 0), type="98",
                            cls="자동처리", amt=rnd.randint(500, 4_000),
                            memo="이자"))

    # ── 비정기 대규모 지출 ──────────────────────────
    for ir in persona.get("irregular_expenses", []):
        txs.append(dict(d=datetime(*ir["date"]), type="02",
                        cls=ir.get("cls", "인터넷뱅킹"),
                        amt=ir["amount"], memo=ir["memo"]))

    # 기준일 이후 제거
    txs = [t for t in txs if t["d"] <= BASE]
    txs.sort(key=lambda t: t["d"])

    # ── 잔액 역산 ──────────────────────────────────
    delta = sum(t["amt"] if t["type"] in IN_TYPES else -t["amt"] for t in txs)
    bal = final_balance - delta
    if bal < 0:
        raise ValueError(
            f"[{persona['id']}] 시작 잔액 음수({bal:,}). "
            f"final_balance를 {final_balance - bal:,} 이상으로 올리세요.")
    for t in txs:
        bal += t["amt"] if t["type"] in IN_TYPES else -t["amt"]
        t["bal"] = bal

    n = len(txs)
    return [{
        "trans_dtime": t["d"].strftime("%Y%m%d%H%M%S"),
        "trans_no": f"{n - k:08d}",
        "trans_type": t["type"],
        "trans_class": t["cls"],
        "currency_code": "KRW",
        "trans_amt": t["amt"],
        "balance_amt": t["bal"],
        "trans_memo": t["memo"],
    } for k, t in enumerate(reversed(txs))]


# ══════════════════════════════════════════════════════
# 응답 빌더
# ══════════════════════════════════════════════════════

def ts(seq):
    return (BASE + timedelta(seconds=seq)).strftime("%Y%m%d%H%M%S")


def resp_accounts(persona):
    lst = []
    for a in persona["accounts"]:
        item = {
            "account_num": a["num"],
            "is_consent": True,
            "prod_name": a["prod_name"],
            "account_type": a["type"],
            "account_status": "01",
        }
        if a["type"][0] in "12":  # 수신·투자
            item["is_foreign_deposit"] = False
            item["is_minus"] = a.get("is_minus", False)
        lst.append(item)
    return {
        "rsp_code": "00000", "rsp_msg": "정상",
        "search_timestamp": ts(0),
        "reg_date": persona["reg_date"],
        "account_cnt": len(lst),
        "account_list": lst,
    }


def resp_deposit_basic(a, seq):
    inner = {"currency_code": "KRW", "saving_method": a["saving_method"],
             "issue_date": a["issue_date"]}
    for k in ("exp_date", "commit_amt", "monthly_paid_in_amt"):
        if a.get(k) is not None:
            inner[k] = a[k]
    return {"rsp_code": "00000", "rsp_msg": "정상",
            "search_timestamp": ts(seq),
            "basic_cnt": 1, "basic_list": [inner]}


def resp_deposit_detail(a, seq):
    inner = {"currency_code": "KRW",
             "balance_amt": a["balance_amt"],
             "withdrawable_amt": a["withdrawable_amt"],
             "offered_rate": a["offered_rate"]}
    if a.get("last_paid_in_cnt") is not None:
        inner["last_paid_in_cnt"] = a["last_paid_in_cnt"]
    return {"rsp_code": "00000", "rsp_msg": "정상",
            "search_timestamp": ts(seq),
            "detail_cnt": 1, "detail_list": [inner]}


def resp_loan_basic(a, seq):
    out = {"rsp_code": "00000", "rsp_msg": "정상",
           "search_timestamp": ts(seq),
           "issue_date": a["issue_date"],
           "exp_date": a["exp_date"],
           "last_offered_rate": a["rate"],
           "repay_method": a["repay_method"]}
    if a.get("repay_date"):
        out["repay_date"] = a["repay_date"]
    if a.get("repay_account_num"):
        out["repay_org_code"] = "00040001"
        out["repay_account_num"] = a["repay_account_num"]
    if a.get("unredeemed_start"):
        out["unredeemed_start"] = a["unredeemed_start"]
        out["unredeemed_end"] = a["unredeemed_end"]
    return out


def resp_loan_detail(a, seq):
    out = {"rsp_code": "00000", "rsp_msg": "정상",
           "search_timestamp": ts(seq),
           "currency_code": "KRW",
           "balance_amt": a["balance_amt"],
           "loan_principal": a["loan_principal"]}
    if a.get("next_repay_date"):
        out["next_repay_date"] = a["next_repay_date"]
    return out


# ══════════════════════════════════════════════════════
# 페르소나 정의
# ══════════════════════════════════════════════════════

def persona_a():
    """A. 사회초년생 — 자산 부족, 학자금대출, 청약 보유"""
    loan_bal, loan_rate = 12_400_000, 0.021
    loan_n = months_until(datetime(2031, 3, 20))
    loan_pmt = pmt_equal_installment(loan_bal, loan_rate, loan_n)

    return {
        "id": "persona_a_social_starter",
        "label": "사회초년생 (27세, 미혼, 원룸 월세)",
        "seed": 101,
        "reg_date": "20220304",
        "final_balance": 4_850_000,
        "main_account": "10120304000001",
        "card_tx_per_month": (18, 26),
        "incomes": [
            {"day": 25, "amount": 2_850_000, "memo": "(주)한빛소프트 급여",
             "bonus_months": (12,), "bonus_multiple": 1,
             "bonus_memo": "(주)한빛소프트 상여", "variance": 0.01},
        ],
        "fixed_expenses": [
            {"day": 25, "memo": "월세", "amount": 650_000},
            {"day": 25, "memo": "관리비", "amount": 70_000, "variance": 0.12},
            {"day": 17, "memo": "KT 통신요금", "amount": 55_000, "variance": 0.03},
            {"day": 20, "memo": "한국장학재단 학자금상환",
             "amount": loan_pmt},
            {"day": 5, "memo": "주택청약종합저축 이체", "amount": 100_000},
            {"day": 14, "memo": "신한카드 결제", "amount": 620_000,
             "variance": 0.22},
        ],
        "irregular_expenses": [
            {"date": (2026, 2, 14, 15, 20), "amount": 1_800_000,
             "memo": "OO치과 임플란트"},
        ],
        "accounts": [
            {"num": "10120304000001", "type": "1001",
             "prod_name": "KB국민 첫급여 우대통장",
             "saving_method": "01", "issue_date": "20220304",
             "balance_amt": 4_850_000, "withdrawable_amt": 4_850_000,
             "offered_rate": 0.001},
            {"num": "10120304000002", "type": "1999",
             "prod_name": "주택청약종합저축",
             "saving_method": "04", "issue_date": "20220401",
             "balance_amt": 5_200_000, "withdrawable_amt": 5_200_000,
             "offered_rate": 0.021},
            {"num": "10120304000003", "type": "3150",
             "prod_name": "한국장학재단 취업후상환 학자금대출",
             "issue_date": "20190302", "exp_date": "20310320",
             "rate": loan_rate, "repay_method": "04", "repay_date": "20",
             "repay_account_num": "10120304000001",
             "balance_amt": loan_bal, "loan_principal": 24_000_000,
             "next_repay_date": "20260820"},
        ],
        "profile": {
            "birth_year": 1999, "marital_status": "single",
            "household_size": 1, "is_first_home_buyer": True,
            "owns_property": False,
            "lease_deposit": 10_000_000, "lease_end_date": "20270228",
            "target_region": "11350", "target_price": 450_000_000,
            "target_move_in_ym": "203003",
            "annual_income_verified": 37_000_000,
            "spouse_annual_income": 0,
            "planned_expenses": [],
            "risk_preference": "stability",
        },
    }


def persona_b():
    """B. 신혼부부 (전세) — 전세대출 만기일시, 부부 합산"""
    loan_bal, loan_rate = 180_000_000, 0.035
    loan_pmt = pmt_interest_only(loan_bal, loan_rate)  # 만기일시 = 이자만

    return {
        "id": "persona_b_newlywed_jeonse",
        "label": "신혼부부 (33/31세, 전세 거주)",
        "seed": 202,
        "reg_date": "20190815",
        "final_balance": 26_400_000,
        "main_account": "20230815000001",
        "card_tx_per_month": (24, 32),
        "incomes": [
            {"day": 25, "amount": 3_800_000, "memo": "(주)디자인랩 급여",
             "bonus_months": (6, 12), "bonus_multiple": 1,
             "bonus_memo": "(주)디자인랩 상여", "variance": 0.01},
            {"day": 10, "amount": 3_100_000, "memo": "배우자 급여 이체",
             "minute": 30, "variance": 0.01},
        ],
        "fixed_expenses": [
            {"day": 15, "memo": "KB국민은행 전세자금대출이자",
             "amount": loan_pmt},
            {"day": 25, "memo": "관리비", "amount": 195_000, "variance": 0.06},
            {"day": 17, "memo": "LGU+ 통신요금", "amount": 92_000,
             "variance": 0.02},
            {"day": 10, "memo": "한화생명 보험료", "amount": 285_000},
            {"day": 5, "memo": "신혼부부 우대적금 이체", "amount": 1_200_000},
            {"day": 5, "memo": "주택청약종합저축 이체", "amount": 200_000},
            {"day": 14, "memo": "현대카드 결제", "amount": 1_480_000,
             "variance": 0.16},
        ],
        "irregular_expenses": [
            {"date": (2025, 10, 8, 11, 0), "amount": 3_200_000,
             "memo": "가전 구입"},
        ],
        "accounts": [
            {"num": "20230815000001", "type": "1001",
             "prod_name": "KB국민 신혼부부 우대통장",
             "saving_method": "01", "issue_date": "20230815",
             "balance_amt": 26_400_000, "withdrawable_amt": 26_400_000,
             "offered_rate": 0.002},
            {"num": "20230815000002", "type": "1003",
             "prod_name": "KB 신혼부부 우대적금",
             "saving_method": "03", "issue_date": "20240701",
             "exp_date": "20270630", "commit_amt": 43_200_000,
             "monthly_paid_in_amt": 1_200_000,
             "balance_amt": 30_000_000, "withdrawable_amt": 30_000_000,
             "offered_rate": 0.041, "last_paid_in_cnt": 25},
            {"num": "20230815000003", "type": "1999",
             "prod_name": "주택청약종합저축",
             "saving_method": "04", "issue_date": "20190815",
             "balance_amt": 16_800_000, "withdrawable_amt": 16_800_000,
             "offered_rate": 0.023},
            {"num": "20230815000004", "type": "3170",
             "prod_name": "KB 전세자금대출 (버팀목)",
             "issue_date": "20250301", "exp_date": "20270228",
             "rate": loan_rate, "repay_method": "01", "repay_date": "15",
             "repay_account_num": "20230815000001",
             "balance_amt": loan_bal, "loan_principal": loan_bal,
             "next_repay_date": "20260815"},
        ],
        "profile": {
            "birth_year": 1993, "marital_status": "married",
            "household_size": 2, "is_first_home_buyer": True,
            "owns_property": False,
            "lease_deposit": 320_000_000, "lease_end_date": "20270228",
            "target_region": "41135", "target_price": 780_000_000,
            "target_move_in_ym": "202903",
            "annual_income_verified": 48_000_000,
            "spouse_annual_income": 41_000_000,
            "planned_expenses": [
                {"name": "출산·육아 준비", "amount": 15_000_000,
                 "target_ym": "202709"},
            ],
            "risk_preference": "stability",
        },
    }


def persona_c():
    """C. 맞벌이 (기존 주담대 거치식 + 신용대출) — 복수 대출 DSR"""
    mort_bal, mort_rate = 250_000_000, 0.042
    mort_pmt = pmt_interest_only(mort_bal, mort_rate)  # 거치기간 중

    cred_bal, cred_rate = 28_400_000, 0.058
    cred_n = months_until(datetime(2028, 8, 10))
    cred_pmt = pmt_equal_installment(cred_bal, cred_rate, cred_n)

    return {
        "id": "persona_c_dual_income_mortgage",
        "label": "맞벌이 (36/34세, 기존 주담대 보유, 상급지 이동)",
        "seed": 303,
        "reg_date": "20170412",
        "final_balance": 21_300_000,
        "main_account": "11020204000001",
        "card_tx_per_month": (22, 30),
        "incomes": [
            {"day": 25, "amount": 4_200_000, "memo": "(주)테크노솔루션 급여",
             "bonus_months": (6, 12), "bonus_multiple": 2,
             "bonus_memo": "(주)테크노솔루션 상여", "variance": 0.01},
            {"day": 10, "amount": 3_500_000, "memo": "배우자 급여 이체",
             "minute": 30, "variance": 0.01},
        ],
        "fixed_expenses": [
            {"day": 15, "memo": "KB국민은행 대출원리금", "amount": mort_pmt},
            {"day": 15, "memo": "KB국민은행 신용대출원리금", "amount": cred_pmt},
            {"day": 25, "memo": "관리비", "amount": 285_000, "variance": 0.05},
            {"day": 17, "memo": "SKT 통신요금", "amount": 128_000,
             "variance": 0.03},
            {"day": 10, "memo": "삼성생명 보험료", "amount": 412_000},
            {"day": 5, "memo": "KB내집마련적금 이체", "amount": 1_000_000},
            {"day": 14, "memo": "KB국민카드 결제", "amount": 1_950_000,
             "variance": 0.18},
        ],
        "irregular_expenses": [
            {"date": (2025, 11, 20, 14, 30), "amount": 4_800_000,
             "memo": "OO병원 수술비"},
        ],
        "accounts": [
            {"num": "11020204000001", "type": "1001",
             "prod_name": "KB국민 주거래 우대통장",
             "saving_method": "01", "issue_date": "20170412",
             "balance_amt": 21_300_000, "withdrawable_amt": 21_300_000,
             "offered_rate": 0.001},
            {"num": "11020204000002", "type": "1002",
             "prod_name": "KB Star 정기예금",
             "saving_method": "02", "issue_date": "20250620",
             "exp_date": "20270620", "commit_amt": 50_000_000,
             "balance_amt": 50_000_000, "withdrawable_amt": 30_000_000,
             "offered_rate": 0.034},
            {"num": "11020204000003", "type": "1003",
             "prod_name": "KB내집마련 적금",
             "saving_method": "03", "issue_date": "20240301",
             "exp_date": "20270228", "commit_amt": 36_000_000,
             "monthly_paid_in_amt": 1_000_000,
             "balance_amt": 28_000_000, "withdrawable_amt": 28_000_000,
             "offered_rate": 0.038, "last_paid_in_cnt": 28},
            {"num": "11020204000004", "type": "1999",
             "prod_name": "주택청약종합저축",
             "saving_method": "04", "issue_date": "20180510",
             "balance_amt": 19_400_000, "withdrawable_amt": 19_400_000,
             "offered_rate": 0.021},
            {"num": "11020204000007", "type": "2003",
             "prod_name": "KB able ISA (신탁형)",
             "saving_method": "04", "issue_date": "20230215",
             "balance_amt": 22_600_000, "withdrawable_amt": 22_600_000,
             "offered_rate": 0.0},
            {"num": "11020204000005", "type": "3220",
             "prod_name": "KB주택담보대출 혼합금리형",
             "issue_date": "20240315", "exp_date": "20540315",
             "rate": mort_rate, "repay_method": "05", "repay_date": "15",
             "repay_account_num": "11020204000001",
             "unredeemed_start": "202403", "unredeemed_end": "202703",
             "balance_amt": mort_bal, "loan_principal": mort_bal,
             "next_repay_date": "20260815"},
            {"num": "11020204000006", "type": "3100",
             "prod_name": "KB 직장인든든 신용대출",
             "issue_date": "20250810", "exp_date": "20280810",
             "rate": cred_rate, "repay_method": "04", "repay_date": "15",
             "repay_account_num": "11020204000001",
             "balance_amt": cred_bal, "loan_principal": 40_000_000,
             "next_repay_date": "20260815"},
        ],
        "profile": {
            "birth_year": 1990, "marital_status": "married",
            "household_size": 3, "is_first_home_buyer": False,
            "owns_property": True,
            "lease_deposit": 0, "lease_end_date": None,
            "target_region": "11680", "target_price": 1_100_000_000,
            "target_move_in_ym": "202903",
            "annual_income_verified": 58_000_000,
            "spouse_annual_income": 46_000_000,
            "planned_expenses": [
                {"name": "자동차 교체", "amount": 25_000_000,
                 "target_ym": "202803"},
            ],
            "risk_preference": "stability",
        },
    }


def persona_d():
    """D. 마이너스통장 보유 — 한도 기준 DSR, 음수 잔액, 원금균등 자동차대출"""
    minus_used, minus_limit, minus_rate = 8_000_000, 30_000_000, 0.061
    minus_pmt = pmt_interest_only(minus_used, minus_rate)

    auto_bal, auto_rate = 18_600_000, 0.049
    auto_n = months_until(datetime(2029, 5, 20))
    auto_pmt = pmt_equal_principal_first(auto_bal, auto_rate, auto_n)

    return {
        "id": "persona_d_credit_line",
        "label": "마이너스통장 보유 (31세, 미혼, 자동차 할부)",
        "seed": 404,
        "reg_date": "20200210",
        "final_balance": 3_950_000,
        "main_account": "30200210000001",
        "card_tx_per_month": (26, 34),
        "incomes": [
            {"day": 25, "amount": 4_600_000, "memo": "(주)넥스트커머스 급여",
             "bonus_months": (7,), "bonus_multiple": 1,
             "bonus_memo": "(주)넥스트커머스 상여", "variance": 0.01},
            {"day": 20, "amount": 550_000, "memo": "프리랜스 외주비",
             "minute": 45, "cls": "인터넷뱅킹", "variance": 0.45},
        ],
        "fixed_expenses": [
            {"day": 25, "memo": "월세", "amount": 900_000},
            {"day": 25, "memo": "관리비", "amount": 130_000, "variance": 0.10},
            {"day": 15, "memo": "KB국민은행 마이너스통장이자",
             "amount": minus_pmt, "variance": 0.08},
            {"day": 20, "memo": "KB캐피탈 자동차할부금", "amount": auto_pmt},
            {"day": 17, "memo": "KT 통신요금", "amount": 78_000,
             "variance": 0.04},
            {"day": 5, "memo": "KB Star 적금 이체", "amount": 500_000},
            {"day": 14, "memo": "롯데카드 결제", "amount": 1_720_000,
             "variance": 0.25},
        ],
        "irregular_expenses": [
            {"date": (2026, 4, 3, 16, 40), "amount": 2_400_000,
             "memo": "자동차 수리비"},
        ],
        "accounts": [
            {"num": "30200210000001", "type": "1001",
             "prod_name": "KB국민 직장인 우대통장",
             "saving_method": "01", "issue_date": "20200210",
             "balance_amt": 3_950_000, "withdrawable_amt": 3_950_000,
             "offered_rate": 0.001},
            # 마이너스통장: 수신(1001, is_minus) + 대출(008/009) 양쪽 생성
            {"num": "30200210000002", "type": "1001", "is_minus": True,
             "prod_name": "KB 마이너스통장",
             "saving_method": "01", "issue_date": "20230920",
             "balance_amt": -minus_used, "withdrawable_amt": 0,
             "offered_rate": minus_rate,
             "is_credit_line": True,
             "exp_date": "20270920",
             "rate": minus_rate, "repay_method": "08",
             "repay_date": None,
             "repay_account_num": "30200210000001",
             "loan_balance_amt": minus_used,
             "loan_principal": minus_limit},
            {"num": "30200210000003", "type": "1003",
             "prod_name": "KB Star 자유적금",
             "saving_method": "04", "issue_date": "20250401",
             "exp_date": "20280331",
             "balance_amt": 7_500_000, "withdrawable_amt": 7_500_000,
             "offered_rate": 0.036},
            {"num": "30200210000004", "type": "3500",
             "prod_name": "KB캐피탈 신차 할부금융",
             "issue_date": "20240520", "exp_date": "20290520",
             "rate": auto_rate, "repay_method": "02", "repay_date": "20",
             "repay_account_num": "30200210000001",
             "balance_amt": auto_bal, "loan_principal": 32_000_000,
             "next_repay_date": "20260820"},
        ],
        "profile": {
            "birth_year": 1995, "marital_status": "single",
            "household_size": 1, "is_first_home_buyer": True,
            "owns_property": False,
            "lease_deposit": 30_000_000, "lease_end_date": "20270630",
            "target_region": "11740", "target_price": 620_000_000,
            "target_move_in_ym": "203009",
            "annual_income_verified": 61_000_000,
            "spouse_annual_income": 0,
            "planned_expenses": [
                {"name": "결혼 자금", "amount": 40_000_000,
                 "target_ym": "202805"},
            ],
            "risk_preference": "speed",
        },
    }


# 대학생1(기본형): 군필, 부모 자가 거주, 월 80만원 고정 알바를 하는 25세 학생.
def persona_e():
    """E. 대학생1(기본형) — 결과를 미리 정하지 않는 월세 보증금 마련 시나리오.

    목적:
        사용자가 제공한 현재 자산·소득·지출과 2년 뒤 월세 입주 목표를 그대로
        입력하고, 상품 PASS/FAIL/UNKNOWN과 목표 달성 가능성은 엔진이 판단하게 한다.
    자동 생성 근거:
        사용자가 정하지 않은 지역·거래 분류·유동성 가정은 현실적인 기본값으로
        채우되 ``generation_metadata``에 제공 사실과 분리해 기록한다.
    """

    return {
        "id": "persona_e_college_student_basic",
        "label": "대학생1(기본형) (25세, 군필, 부모 자가 거주)",
        "seed": 505,
        "reg_date": "20240102",
        "final_balance": 1_000_000,
        "main_account": "40100102000001",
        # 월 고정지출 29만원 + 아래 카드지출 41만원 = 사용자가 제시한 월 70만원.
        "card_tx_per_month": (18, 22),
        "card_monthly_budget": 410_000,
        "card_merchants": [
            ("학교 학생식당", 4_500, 9_000),
            ("대학가 김밥집", 5_000, 12_000),
            ("교내 카페", 3_000, 7_000),
            ("편의점", 3_000, 15_000),
            ("동네 마트", 15_000, 50_000),
            ("서점", 10_000, 40_000),
            ("영화관", 12_000, 20_000),
        ],
        "incomes": [
            {
                "day": 10,
                "amount": 800_000,
                "memo": "OO카페 아르바이트 급여",
                "start_ym": "202509",
            },
        ],
        "fixed_expenses": [
            {"day": 2, "memo": "교통카드 충전", "amount": 70_000},
            {"day": 17, "memo": "알뜰폰 통신요금", "amount": 40_000},
            {"day": 5, "memo": "교재·온라인학습비", "amount": 50_000},
            {"day": 25, "memo": "부모님 생활비 분담", "amount": 100_000},
            {"day": 20, "memo": "문화·구독 서비스", "amount": 30_000},
        ],
        "irregular_expenses": [],
        "accounts": [
            {
                "num": "40100102000001",
                "type": "1001",
                "prod_name": "KB국민 대학생 생활통장",
                "saving_method": "01",
                "issue_date": "20240102",
                "balance_amt": 1_000_000,
                "withdrawable_amt": 1_000_000,
                "offered_rate": 0.001,
            },
        ],
        "profile": {
            "birth_date": "20010315",
            "birth_year": 2001,
            "age_as_of": 25,
            "military_service_status": "completed",
            "education_status": "university_student",
            "employment_type": "part_time",
            "employment_expected_to_continue": True,
            "marital_status": "single",
            "household_size": 3,
            "living_parent_count": 2,
            "lives_with_parents": True,
            "same_household_with_parents": True,
            "parents_home_tenure": "owned",
            "is_first_home_buyer": True,
            "owns_property": False,
            "current_housing_type": "living_with_parents",
            "lease_deposit": 0,
            "lease_end_date": None,
            "target_housing_type": "monthly_rent",
            "target_region": "30200",
            # 기존 profile 소비자와의 호환을 위해 목표 필요자금(보증금)을
            # target_price에도 둔다. 신규 코드는 target_housing_type을 먼저 읽는다.
            "target_price": 5_000_000,
            "target_lease_deposit": 5_000_000,
            "target_monthly_rent": 200_000,
            "target_management_fee": 50_000,
            "target_move_in_ym": "202807",
            "annual_income_verified": 9_600_000,
            "spouse_annual_income": 0,
            "monthly_income": 800_000,
            "monthly_average_expense": 700_000,
            "tuition_payer": "parents",
            "planned_expenses": [],
            "risk_preference": "stability",
        },
        "savings_preferences": {
            "as_of": "20260728",
            "applicant_type": "individual",
            "is_first_payment": True,
            "fund_needed_date": "20280728",
            "monthly_savings_budget": 100_000,
            # 한 달 생활비 70만원을 비상자금으로 남기고 나머지만 일시예치한다.
            "lump_sum_budget": 300_000,
            "emergency_reserve": 700_000,
            "bonus_achievement_probability": 0.5,
            "contribution_timing": "end",
            "maturity_tolerance_days": 180,
            "liquidity_preference": "high",
            "accepts_principal_risk": False,
            "existing_institution_deposits": {"0010927": 1_000_000},
            "maximum_recommended_products": 2,
            "expected_outcome": None,
        },
        "generation_metadata": {
            "purpose": (
                "기대 결과를 지정하지 않고 대학생의 실제 입력값으로 예적금 "
                "상품 평가와 월세 보증금 마련 가능성을 확인한다."
            ),
            "provided_facts": {
                "persona_name": "대학생1(기본형)",
                "age": 25,
                "military_service_status": "completed",
                "living_arrangement": "부모님과 부모님 소유 주택에 거주",
                "marital_status": "single",
                "owns_property": False,
                "monthly_income": 800_000,
                "monthly_average_expense": 700_000,
                "current_assets": 1_000_000,
                "has_loans": False,
                "tuition_payer": "parents",
                "target_period": "약 2년",
                "target_lease_deposit": 5_000_000,
                "target_monthly_rent": 200_000,
                "employment_expected_to_continue": True,
            },
            "generated_assumptions": {
                "birth_date": "20010315",
                "target_region": "30200",
                "target_move_in_ym": "202807",
                "target_management_fee": 50_000,
                "part_time_income_start_ym": "202509",
                "applicant_type": "individual",
                "is_first_payment": True,
                "emergency_reserve": 700_000,
                "lump_sum_budget": 300_000,
                "bonus_achievement_probability": 0.5,
                "contribution_timing": "end",
                "maturity_tolerance_days": 180,
                "risk_preference": "stability",
            },
            "expected_outcome_policy": "derive_from_engine",
        },
    }


STUDENT_CARD_MERCHANTS = [
    ("학교 학생식당", 4_500, 9_000),
    ("대학가 분식집", 5_000, 12_000),
    ("교내 카페", 3_000, 7_000),
    ("편의점", 3_000, 15_000),
    ("동네 마트", 15_000, 50_000),
    ("서점", 10_000, 40_000),
    ("영화관", 12_000, 20_000),
]


def _college_student_variant(spec):
    """명시된 학생 특성을 표준 계좌·거래·프로필·예적금 입력으로 확장한다.

    소득·생활지출·부채상환 후 남는 금액을 월 저축예산으로 계산한다. 결과 상태나
    추천상품은 넣지 않으며 각 spec의 사실만으로 후속 엔진이 판단하게 한다.
    """

    index = spec["index"]
    account_prefix = f"4{index:02d}00102000"
    main_account = f"{account_prefix}001"
    savings_account = f"{account_prefix}002"
    deposit_account = f"{account_prefix}003"
    loan_account = f"{account_prefix}004"

    monthly_income = spec["monthly_income"]
    monthly_expense = spec["monthly_expense"]
    monthly_debt_payment = spec.get("monthly_debt_payment", 0)
    monthly_savings_budget = max(
        0,
        monthly_income - monthly_expense - monthly_debt_payment,
    )

    housing_cost = spec["current_housing_cost"]
    transport_cost = spec.get("transport_cost", 60_000)
    phone_cost = spec.get("phone_cost", 40_000)
    fixed_living_expense = housing_cost + transport_cost + phone_cost
    if fixed_living_expense >= monthly_expense:
        raise ValueError(
            f"{spec['name']}: 고정생활비가 월평균 지출보다 작아야 합니다."
        )
    card_monthly_budget = monthly_expense - fixed_living_expense
    card_count = max(8, min(36, card_monthly_budget // 25_000))

    fixed_expenses = [
        {"day": 2, "memo": "교통비", "amount": transport_cost},
        {"day": 17, "memo": "통신요금", "amount": phone_cost},
    ]
    if housing_cost > 0:
        fixed_expenses.append(
            {
                "day": 25,
                "memo": spec["current_housing_memo"],
                "amount": housing_cost,
            }
        )
    if monthly_debt_payment > 0:
        fixed_expenses.append(
            {
                "day": 20,
                "memo": "한국장학재단 학자금대출 원리금",
                "amount": monthly_debt_payment,
            }
        )
    if monthly_savings_budget > 0:
        fixed_expenses.append(
            {
                "day": 12,
                "memo": "대학생 목표적금 이체",
                "amount": monthly_savings_budget,
            }
        )

    checking_balance = spec["checking_balance"]
    savings_balance = spec.get("savings_balance", 0)
    term_deposit_balance = spec.get("term_deposit_balance", 0)
    loan_balance = spec.get("loan_balance", 0)
    accounts = [
        {
            "num": main_account,
            "type": "1001",
            "prod_name": "KB국민 대학생 생활통장",
            "saving_method": "01",
            "issue_date": "20240102",
            "balance_amt": checking_balance,
            "withdrawable_amt": checking_balance,
            "offered_rate": 0.001,
        },
    ]
    if savings_balance > 0:
        savings_method = "03" if monthly_savings_budget > 0 else "04"
        savings_item = {
            "num": savings_account,
            "type": "1003",
            "prod_name": "KB 대학생 목표적금",
            "saving_method": savings_method,
            "issue_date": "20250102",
            "exp_date": "20280102",
            "balance_amt": savings_balance,
            "withdrawable_amt": savings_balance,
            "offered_rate": 0.034,
            "last_paid_in_cnt": 18,
        }
        if monthly_savings_budget > 0:
            savings_item["commit_amt"] = monthly_savings_budget * 36
            savings_item["monthly_paid_in_amt"] = monthly_savings_budget
        accounts.append(savings_item)
    if term_deposit_balance > 0:
        accounts.append(
            {
                "num": deposit_account,
                "type": "1002",
                "prod_name": "KB 가족지원 정기예금",
                "saving_method": "02",
                "issue_date": "20250701",
                "exp_date": "20270701",
                "commit_amt": term_deposit_balance,
                "balance_amt": term_deposit_balance,
                "withdrawable_amt": term_deposit_balance,
                "offered_rate": 0.031,
            }
        )
    if loan_balance > 0:
        accounts.append(
            {
                "num": loan_account,
                "type": "3150",
                "prod_name": "한국장학재단 일반상환 학자금대출",
                "issue_date": "20230302",
                "exp_date": "20330302",
                "rate": 0.021,
                "repay_method": "04",
                "repay_date": "20",
                "repay_account_num": main_account,
                "balance_amt": loan_balance,
                "loan_principal": max(loan_balance, spec.get("loan_principal", 0)),
                "next_repay_date": "20260820",
            }
        )

    category = spec["category"]
    emergency_months = 3 if category == "affluent" else 1
    emergency_reserve = min(checking_balance, monthly_expense * emergency_months)
    lump_sum_budget = max(0, checking_balance - emergency_reserve)
    current_assets = checking_balance + savings_balance + term_deposit_balance
    target_date = add_months(datetime(2026, 7, 28), spec["target_months"])
    target_move_in_ym = target_date.strftime("%Y%m")
    fund_needed_date = target_date.strftime("%Y%m%d")
    birth_year = 2026 - spec["age"]
    bonus_probability = {
        "basic": 0.5,
        "affluent": 0.7,
        "poor": 0.3,
    }[category]
    liquidity_preference = "medium" if category == "affluent" else "high"
    max_products = 3 if category == "affluent" else 2

    return {
        "id": spec["id"],
        "label": f"{spec['name']} - {spec['summary']}",
        "seed": 500 + index,
        "reg_date": "20240102",
        "final_balance": checking_balance,
        "main_account": main_account,
        "card_tx_per_month": (max(6, card_count - 2), card_count + 2),
        "card_monthly_budget": card_monthly_budget,
        "card_merchants": STUDENT_CARD_MERCHANTS,
        "incomes": [
            {
                "day": 10,
                "amount": monthly_income,
                "memo": spec["income_memo"],
            },
        ],
        "fixed_expenses": fixed_expenses,
        "irregular_expenses": [],
        "accounts": accounts,
        "profile": {
            "persona_type": f"college_student_{category}",
            "character_summary": spec["summary"],
            "birth_date": f"{birth_year}0315",
            "birth_year": birth_year,
            "age_as_of": spec["age"],
            "military_service_status": spec["military_service_status"],
            "education_status": "university_student",
            "employment_type": spec["employment_type"],
            "employment_expected_to_continue": True,
            "marital_status": "single",
            "household_size": spec["household_size"],
            "living_parent_count": 2,
            "lives_with_parents": spec["current_housing_type"] == "parents",
            "same_household_with_parents": spec["current_housing_type"] == "parents",
            "parents_home_tenure": spec["parents_home_tenure"],
            "is_first_home_buyer": True,
            "owns_property": False,
            "current_housing_type": spec["current_housing_type"],
            "lease_deposit": spec.get("current_lease_deposit", 0),
            "lease_end_date": None,
            "target_housing_type": "monthly_rent",
            "target_region": spec["target_region"],
            "target_price": spec["target_lease_deposit"],
            "target_lease_deposit": spec["target_lease_deposit"],
            "target_monthly_rent": spec["target_monthly_rent"],
            "target_management_fee": spec["target_management_fee"],
            "target_move_in_ym": target_move_in_ym,
            "annual_income_verified": monthly_income * 12,
            "spouse_annual_income": 0,
            "monthly_income": monthly_income,
            "monthly_average_expense": monthly_expense,
            "monthly_debt_payment": monthly_debt_payment,
            "current_assets": current_assets,
            "tuition_payer": spec["tuition_payer"],
            "planned_expenses": [],
            "risk_preference": "stability",
        },
        "savings_preferences": {
            "as_of": "20260728",
            "applicant_type": "individual",
            "is_first_payment": True,
            "fund_needed_date": fund_needed_date,
            "monthly_savings_budget": monthly_savings_budget,
            "lump_sum_budget": lump_sum_budget,
            "emergency_reserve": emergency_reserve,
            "bonus_achievement_probability": bonus_probability,
            "contribution_timing": "end",
            "maturity_tolerance_days": 180,
            "liquidity_preference": liquidity_preference,
            "accepts_principal_risk": False,
            "existing_institution_deposits": {
                "0010927": current_assets,
            },
            "maximum_recommended_products": max_products,
            "expected_outcome": None,
        },
        "generation_metadata": {
            "persona_name": spec["name"],
            "persona_category": category,
            "character_summary": spec["summary"],
            "purpose": (
                "기대 결과를 미리 정하지 않고 해당 학생의 재무 사실로 "
                "예적금 평가와 월세 보증금 마련 가능성을 관찰한다."
            ),
            "provided_facts": {
                "generation_request": "대학생 기본형·부유형·가난형 총 20명",
            },
            "generated_assumptions": {
                "age": spec["age"],
                "monthly_income": monthly_income,
                "monthly_average_expense": monthly_expense,
                "monthly_debt_payment": monthly_debt_payment,
                "current_assets": current_assets,
                "target_lease_deposit": spec["target_lease_deposit"],
                "target_monthly_rent": spec["target_monthly_rent"],
                "target_move_in_ym": target_move_in_ym,
                "emergency_reserve": emergency_reserve,
                "lump_sum_budget": lump_sum_budget,
                "monthly_savings_budget": monthly_savings_budget,
                "bonus_achievement_probability": bonus_probability,
            },
            "expected_outcome_policy": "derive_from_engine",
        },
    }


COLLEGE_STUDENT_VARIANT_SPECS = (
    # 대학생2(기본형): 부모 전세집에서 통학하며 편의점 야간근무를 하는 21세 학생.
    {
        "index": 2,
        "id": "persona_f_college_student_02_basic",
        "name": "대학생2(기본형)",
        "category": "basic",
        "summary": "부모 전세집 통학, 편의점 야간 아르바이트",
        "age": 21,
        "military_service_status": "not_applicable",
        "household_size": 4,
        "parents_home_tenure": "jeonse",
        "current_housing_type": "parents",
        "current_housing_cost": 80_000,
        "current_housing_memo": "부모님 생활비 분담",
        "monthly_income": 900_000,
        "monthly_expense": 700_000,
        "checking_balance": 900_000,
        "savings_balance": 600_000,
        "income_memo": "편의점 아르바이트 급여",
        "employment_type": "part_time",
        "tuition_payer": "parents",
        "target_region": "11290",
        "target_lease_deposit": 6_000_000,
        "target_monthly_rent": 250_000,
        "target_management_fee": 50_000,
        "target_months": 24,
    },
    # 대학생3(기본형): 기숙사에 거주하며 교내근로와 장학금으로 생활하는 22세 학생.
    {
        "index": 3,
        "id": "persona_g_college_student_03_basic",
        "name": "대학생3(기본형)",
        "category": "basic",
        "summary": "기숙사 거주, 교내근로와 생활비 장학금 수령",
        "age": 22,
        "military_service_status": "not_applicable",
        "household_size": 3,
        "parents_home_tenure": "owned",
        "current_housing_type": "dormitory",
        "current_housing_cost": 250_000,
        "current_housing_memo": "기숙사비",
        "monthly_income": 1_200_000,
        "monthly_expense": 900_000,
        "checking_balance": 1_200_000,
        "savings_balance": 800_000,
        "income_memo": "교내근로·생활비 장학금",
        "employment_type": "work_study",
        "tuition_payer": "scholarship",
        "target_region": "30200",
        "target_lease_deposit": 8_000_000,
        "target_monthly_rent": 300_000,
        "target_management_fee": 60_000,
        "target_months": 30,
    },
    # 대학생4(기본형): 군 복학 후 주말 서점 아르바이트를 하는 24세 통학생.
    {
        "index": 4,
        "id": "persona_h_college_student_04_basic",
        "name": "대학생4(기본형)",
        "category": "basic",
        "summary": "군 복학 통학생, 주말 서점 아르바이트",
        "age": 24,
        "military_service_status": "completed",
        "household_size": 3,
        "parents_home_tenure": "owned",
        "current_housing_type": "parents",
        "current_housing_cost": 100_000,
        "current_housing_memo": "부모님 생활비 분담",
        "monthly_income": 1_100_000,
        "monthly_expense": 850_000,
        "checking_balance": 1_500_000,
        "savings_balance": 1_500_000,
        "income_memo": "서점 아르바이트 급여",
        "employment_type": "part_time",
        "tuition_payer": "parents",
        "target_region": "11350",
        "target_lease_deposit": 7_000_000,
        "target_monthly_rent": 300_000,
        "target_management_fee": 50_000,
        "target_months": 24,
    },
    # 대학생5(기본형): 실습·재료비 지출이 큰 예체능 전공 23세 학생.
    {
        "index": 5,
        "id": "persona_i_college_student_05_basic",
        "name": "대학생5(기본형)",
        "category": "basic",
        "summary": "부모와 거주하지만 실습·재료비 지출이 큰 예체능 전공",
        "age": 23,
        "military_service_status": "not_applicable",
        "household_size": 3,
        "parents_home_tenure": "owned",
        "current_housing_type": "parents",
        "current_housing_cost": 50_000,
        "current_housing_memo": "부모님 생활비 분담",
        "monthly_income": 800_000,
        "monthly_expense": 750_000,
        "checking_balance": 500_000,
        "savings_balance": 300_000,
        "income_memo": "전시관 아르바이트 급여",
        "employment_type": "part_time",
        "tuition_payer": "parents",
        "target_region": "29170",
        "target_lease_deposit": 5_000_000,
        "target_monthly_rent": 250_000,
        "target_management_fee": 50_000,
        "target_months": 24,
    },
    # 대학생6(기본형): 연구실 장려금과 조교비를 받는 26세 대학원생.
    {
        "index": 6,
        "id": "persona_j_college_student_06_basic",
        "name": "대학생6(기본형)",
        "category": "basic",
        "summary": "대학원 재학, 연구장려금과 조교비 수령",
        "age": 26,
        "military_service_status": "completed",
        "household_size": 1,
        "parents_home_tenure": "owned",
        "current_housing_type": "monthly_rent",
        "current_housing_cost": 450_000,
        "current_housing_memo": "원룸 월세·관리비",
        "monthly_income": 1_500_000,
        "monthly_expense": 1_100_000,
        "checking_balance": 2_000_000,
        "savings_balance": 3_000_000,
        "current_lease_deposit": 5_000_000,
        "income_memo": "연구장려금·조교비",
        "employment_type": "graduate_assistant",
        "tuition_payer": "scholarship",
        "target_region": "30200",
        "target_lease_deposit": 10_000_000,
        "target_monthly_rent": 350_000,
        "target_management_fee": 70_000,
        "target_months": 30,
    },
    # 대학생7(기본형): 졸업을 앞두고 취업준비와 카페근무를 병행하는 25세 학생.
    {
        "index": 7,
        "id": "persona_k_college_student_07_basic",
        "name": "대학생7(기본형)",
        "category": "basic",
        "summary": "졸업 예정, 취업준비와 카페 아르바이트 병행",
        "age": 25,
        "military_service_status": "completed",
        "household_size": 3,
        "parents_home_tenure": "owned",
        "current_housing_type": "parents",
        "current_housing_cost": 100_000,
        "current_housing_memo": "부모님 생활비 분담",
        "monthly_income": 1_000_000,
        "monthly_expense": 900_000,
        "checking_balance": 700_000,
        "savings_balance": 500_000,
        "income_memo": "카페 아르바이트 급여",
        "employment_type": "part_time",
        "tuition_payer": "parents",
        "target_region": "11500",
        "target_lease_deposit": 8_000_000,
        "target_monthly_rent": 350_000,
        "target_management_fee": 60_000,
        "target_months": 18,
    },
    # 대학생8(부유형): 부모의 월 생활비 지원과 기존 목돈이 충분한 21세 학생.
    {
        "index": 8,
        "id": "persona_l_college_student_08_affluent",
        "name": "대학생8(부유형)",
        "category": "affluent",
        "summary": "부모 생활비 지원과 기존 목돈이 충분한 통학생",
        "age": 21,
        "military_service_status": "not_applicable",
        "household_size": 4,
        "parents_home_tenure": "owned",
        "current_housing_type": "parents",
        "current_housing_cost": 0,
        "current_housing_memo": "주거비 없음",
        "monthly_income": 2_000_000,
        "monthly_expense": 1_000_000,
        "checking_balance": 8_000_000,
        "savings_balance": 7_000_000,
        "term_deposit_balance": 10_000_000,
        "income_memo": "부모 생활비 지원",
        "employment_type": "family_support",
        "tuition_payer": "parents",
        "target_region": "11680",
        "target_lease_deposit": 30_000_000,
        "target_monthly_rent": 700_000,
        "target_management_fee": 120_000,
        "target_months": 24,
    },
    # 대학생9(부유형): 가족 증여 예금과 높은 생활비 지원을 가진 23세 학생.
    {
        "index": 9,
        "id": "persona_m_college_student_09_affluent",
        "name": "대학생9(부유형)",
        "category": "affluent",
        "summary": "가족 증여 정기예금과 월 생활비 지원 보유",
        "age": 23,
        "military_service_status": "completed",
        "household_size": 3,
        "parents_home_tenure": "owned",
        "current_housing_type": "parents",
        "current_housing_cost": 0,
        "current_housing_memo": "주거비 없음",
        "monthly_income": 3_000_000,
        "monthly_expense": 1_200_000,
        "checking_balance": 10_000_000,
        "savings_balance": 10_000_000,
        "term_deposit_balance": 30_000_000,
        "income_memo": "가족 생활비·교육비 지원",
        "employment_type": "family_support",
        "tuition_payer": "parents",
        "target_region": "11680",
        "target_lease_deposit": 50_000_000,
        "target_monthly_rent": 900_000,
        "target_management_fee": 150_000,
        "target_months": 18,
    },
    # 대학생10(부유형): 고액 과외로 월 400만원을 버는 25세 학생.
    {
        "index": 10,
        "id": "persona_n_college_student_10_affluent",
        "name": "대학생10(부유형)",
        "category": "affluent",
        "summary": "고액 과외 수입이 안정적인 상위권 대학생",
        "age": 25,
        "military_service_status": "completed",
        "household_size": 3,
        "parents_home_tenure": "owned",
        "current_housing_type": "parents",
        "current_housing_cost": 200_000,
        "current_housing_memo": "부모님 생활비 분담",
        "monthly_income": 4_000_000,
        "monthly_expense": 1_800_000,
        "checking_balance": 12_000_000,
        "savings_balance": 8_000_000,
        "term_deposit_balance": 10_000_000,
        "income_memo": "개인과외 수입",
        "employment_type": "self_employed_tutor",
        "tuition_payer": "self",
        "target_region": "11680",
        "target_lease_deposit": 40_000_000,
        "target_monthly_rent": 800_000,
        "target_management_fee": 150_000,
        "target_months": 18,
    },
    # 대학생11(부유형): 가족사업을 도우며 급여와 큰 금융자산을 보유한 24세 학생.
    {
        "index": 11,
        "id": "persona_o_college_student_11_affluent",
        "name": "대학생11(부유형)",
        "category": "affluent",
        "summary": "가족사업 보조 급여와 큰 예적금 자산 보유",
        "age": 24,
        "military_service_status": "completed",
        "household_size": 4,
        "parents_home_tenure": "owned",
        "current_housing_type": "parents",
        "current_housing_cost": 0,
        "current_housing_memo": "주거비 없음",
        "monthly_income": 2_500_000,
        "monthly_expense": 1_500_000,
        "checking_balance": 15_000_000,
        "savings_balance": 15_000_000,
        "term_deposit_balance": 50_000_000,
        "income_memo": "가족사업 근로소득",
        "employment_type": "family_business",
        "tuition_payer": "parents",
        "target_region": "11680",
        "target_lease_deposit": 70_000_000,
        "target_monthly_rent": 1_000_000,
        "target_management_fee": 180_000,
        "target_months": 24,
    },
    # 대학생12(부유형): 전액장학금과 부모 지원으로 지출 대비 여유가 큰 22세 학생.
    {
        "index": 12,
        "id": "persona_p_college_student_12_affluent",
        "name": "대학생12(부유형)",
        "category": "affluent",
        "summary": "전액장학금과 부모 지원으로 높은 저축여력 보유",
        "age": 22,
        "military_service_status": "not_applicable",
        "household_size": 3,
        "parents_home_tenure": "owned",
        "current_housing_type": "dormitory",
        "current_housing_cost": 300_000,
        "current_housing_memo": "기숙사비",
        "monthly_income": 1_800_000,
        "monthly_expense": 900_000,
        "checking_balance": 6_000_000,
        "savings_balance": 14_000_000,
        "term_deposit_balance": 20_000_000,
        "income_memo": "생활비 장학금·부모 지원",
        "employment_type": "scholarship_and_support",
        "tuition_payer": "scholarship",
        "target_region": "11290",
        "target_lease_deposit": 30_000_000,
        "target_monthly_rent": 600_000,
        "target_management_fee": 100_000,
        "target_months": 30,
    },
    # 대학생13(부유형): 프리랜서 개발로 고소득과 1억원대 자산을 만든 26세 학생.
    {
        "index": 13,
        "id": "persona_q_college_student_13_affluent",
        "name": "대학생13(부유형)",
        "category": "affluent",
        "summary": "프리랜서 개발 고소득과 1억원대 금융자산 보유",
        "age": 26,
        "military_service_status": "completed",
        "household_size": 1,
        "parents_home_tenure": "owned",
        "current_housing_type": "monthly_rent",
        "current_housing_cost": 900_000,
        "current_housing_memo": "오피스텔 월세·관리비",
        "monthly_income": 5_000_000,
        "monthly_expense": 2_000_000,
        "checking_balance": 20_000_000,
        "savings_balance": 30_000_000,
        "term_deposit_balance": 70_000_000,
        "current_lease_deposit": 20_000_000,
        "income_memo": "프리랜서 개발 용역비",
        "employment_type": "freelancer",
        "tuition_payer": "self",
        "target_region": "11680",
        "target_lease_deposit": 80_000_000,
        "target_monthly_rent": 1_200_000,
        "target_management_fee": 200_000,
        "target_months": 12,
    },
    # 대학생14(가난형): 단시간 알바와 빠듯한 생활비로 월 5만원만 남는 20세 학생.
    {
        "index": 14,
        "id": "persona_r_college_student_14_poor",
        "name": "대학생14(가난형)",
        "category": "poor",
        "summary": "단시간 아르바이트, 월 잉여자금 5만원",
        "age": 20,
        "military_service_status": "not_served",
        "household_size": 4,
        "parents_home_tenure": "monthly_rent",
        "current_housing_type": "parents",
        "current_housing_cost": 100_000,
        "current_housing_memo": "가족 월세 분담",
        "monthly_income": 600_000,
        "monthly_expense": 550_000,
        "checking_balance": 500_000,
        "savings_balance": 100_000,
        "income_memo": "패스트푸드점 아르바이트 급여",
        "employment_type": "part_time",
        "tuition_payer": "scholarship",
        "target_region": "29170",
        "target_lease_deposit": 3_000_000,
        "target_monthly_rent": 200_000,
        "target_management_fee": 40_000,
        "target_months": 24,
    },
    # 대학생15(가난형): 학자금대출 1,200만원을 상환 중인 24세 학생.
    {
        "index": 15,
        "id": "persona_s_college_student_15_poor",
        "name": "대학생15(가난형)",
        "category": "poor",
        "summary": "학자금대출 1,200만원과 월 상환 부담 보유",
        "age": 24,
        "military_service_status": "completed",
        "household_size": 3,
        "parents_home_tenure": "jeonse",
        "current_housing_type": "parents",
        "current_housing_cost": 100_000,
        "current_housing_memo": "가족 생활비 분담",
        "monthly_income": 800_000,
        "monthly_expense": 650_000,
        "monthly_debt_payment": 100_000,
        "checking_balance": 300_000,
        "savings_balance": 50_000,
        "loan_balance": 12_000_000,
        "loan_principal": 16_000_000,
        "income_memo": "물류센터 아르바이트 급여",
        "employment_type": "part_time",
        "tuition_payer": "student_loan",
        "target_region": "27200",
        "target_lease_deposit": 5_000_000,
        "target_monthly_rent": 250_000,
        "target_management_fee": 50_000,
        "target_months": 30,
    },
    # 대학생16(가난형): 지방 원룸 월세 때문에 소득 대부분을 쓰는 23세 학생.
    {
        "index": 16,
        "id": "persona_t_college_student_16_poor",
        "name": "대학생16(가난형)",
        "category": "poor",
        "summary": "현재 원룸 월세로 소득 대부분을 지출",
        "age": 23,
        "military_service_status": "not_applicable",
        "household_size": 1,
        "parents_home_tenure": "monthly_rent",
        "current_housing_type": "monthly_rent",
        "current_housing_cost": 450_000,
        "current_housing_memo": "원룸 월세·관리비",
        "monthly_income": 1_000_000,
        "monthly_expense": 950_000,
        "checking_balance": 700_000,
        "savings_balance": 100_000,
        "current_lease_deposit": 2_000_000,
        "income_memo": "식당 아르바이트 급여",
        "employment_type": "part_time",
        "tuition_payer": "scholarship",
        "target_region": "26440",
        "target_lease_deposit": 5_000_000,
        "target_monthly_rent": 250_000,
        "target_management_fee": 50_000,
        "target_months": 24,
    },
    # 대학생17(가난형): 생활비가 수입보다 많아 잔액이 줄어드는 22세 학생.
    {
        "index": 17,
        "id": "persona_u_college_student_17_poor",
        "name": "대학생17(가난형)",
        "category": "poor",
        "summary": "월 2만원 적자 현금흐름으로 잔액 감소 중",
        "age": 22,
        "military_service_status": "not_applicable",
        "household_size": 3,
        "parents_home_tenure": "monthly_rent",
        "current_housing_type": "parents",
        "current_housing_cost": 120_000,
        "current_housing_memo": "가족 월세·생활비 분담",
        "monthly_income": 500_000,
        "monthly_expense": 520_000,
        "checking_balance": 150_000,
        "income_memo": "교내 단기근로 급여",
        "employment_type": "work_study",
        "tuition_payer": "scholarship",
        "target_region": "29170",
        "target_lease_deposit": 3_000_000,
        "target_monthly_rent": 180_000,
        "target_management_fee": 40_000,
        "target_months": 24,
    },
    # 대학생18(가난형): 소득과 생활비가 같아 저축여력이 없는 25세 학생.
    {
        "index": 18,
        "id": "persona_v_college_student_18_poor",
        "name": "대학생18(가난형)",
        "category": "poor",
        "summary": "월수입과 지출이 같아 정기 저축여력 없음",
        "age": 25,
        "military_service_status": "completed",
        "household_size": 2,
        "parents_home_tenure": "jeonse",
        "current_housing_type": "parents",
        "current_housing_cost": 150_000,
        "current_housing_memo": "가족 생활비 분담",
        "monthly_income": 700_000,
        "monthly_expense": 700_000,
        "checking_balance": 550_000,
        "income_memo": "주말 행사 아르바이트 급여",
        "employment_type": "part_time",
        "tuition_payer": "scholarship",
        "target_region": "27200",
        "target_lease_deposit": 4_000_000,
        "target_monthly_rent": 220_000,
        "target_management_fee": 50_000,
        "target_months": 18,
    },
    # 대학생19(가난형): 가족부양과 학자금대출을 동시에 부담하는 26세 학생.
    {
        "index": 19,
        "id": "persona_w_college_student_19_poor",
        "name": "대학생19(가난형)",
        "category": "poor",
        "summary": "가족 생활비와 학자금대출 상환을 함께 부담",
        "age": 26,
        "military_service_status": "completed",
        "household_size": 4,
        "parents_home_tenure": "monthly_rent",
        "current_housing_type": "parents",
        "current_housing_cost": 200_000,
        "current_housing_memo": "가족 월세·생활비 분담",
        "monthly_income": 900_000,
        "monthly_expense": 800_000,
        "monthly_debt_payment": 80_000,
        "checking_balance": 400_000,
        "savings_balance": 50_000,
        "loan_balance": 8_000_000,
        "loan_principal": 10_000_000,
        "income_memo": "야간 편의점 아르바이트 급여",
        "employment_type": "part_time",
        "tuition_payer": "student_loan",
        "target_region": "26440",
        "target_lease_deposit": 5_000_000,
        "target_monthly_rent": 230_000,
        "target_management_fee": 50_000,
        "target_months": 36,
    },
    # 대학생20(가난형): 가족지원 없이 월 20만원 적자가 누적되는 21세 학생.
    {
        "index": 20,
        "id": "persona_x_college_student_20_poor",
        "name": "대학생20(가난형)",
        "category": "poor",
        "summary": "가족지원 없이 월 20만원 적자가 누적되는 학생",
        "age": 21,
        "military_service_status": "not_served",
        "household_size": 1,
        "parents_home_tenure": "monthly_rent",
        "current_housing_type": "dormitory",
        "current_housing_cost": 250_000,
        "current_housing_memo": "기숙사비",
        "monthly_income": 400_000,
        "monthly_expense": 600_000,
        "checking_balance": 100_000,
        "income_memo": "단기 아르바이트 급여",
        "employment_type": "irregular_part_time",
        "tuition_payer": "scholarship",
        "target_region": "30200",
        "target_lease_deposit": 3_000_000,
        "target_monthly_rent": 180_000,
        "target_management_fee": 40_000,
        "target_months": 24,
    },
)


def college_student_variant_factories():
    """각 명시적 학생 spec을 기존 generate() 계약의 factory로 감싼다."""

    factories = []
    for spec in COLLEGE_STUDENT_VARIANT_SPECS:

        def factory(selected_spec=spec):
            return _college_student_variant(selected_spec)

        factories.append(factory)
    return tuple(factories)


# ══════════════════════════════════════════════════════
# 파일 출력
# ══════════════════════════════════════════════════════

def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def generate(persona):
    out = os.path.join(OUT_ROOT, persona["id"])
    os.makedirs(out, exist_ok=True)

    # 은행-001
    write(f"{out}/bank_001_accounts.json", resp_accounts(persona))

    seq = 1
    for a in persona["accounts"]:
        num, t = a["num"], a["type"]

        # 수신·투자 → 은행-002 / 003
        if t[0] in "12":
            write(f"{out}/bank_002_deposit_basic_{num}.json",
                  resp_deposit_basic(a, seq)) 
            seq += 1
            write(f"{out}/bank_003_deposit_detail_{num}.json",
                  resp_deposit_detail(a, seq)) 
            seq += 1

        # 대출 → 은행-008 / 009
        if t[0] == "3":
            write(f"{out}/bank_008_loan_basic_{num}.json",
                  resp_loan_basic(a, seq)) 
            seq += 1
            write(f"{out}/bank_009_loan_detail_{num}.json",
                  resp_loan_detail(a, seq)) 
            seq += 1

        # 마이너스통장 → 수신 + 대출 양쪽
        if a.get("is_credit_line"):
            la = dict(a, balance_amt=a["loan_balance_amt"])
            write(f"{out}/bank_008_loan_basic_{num}.json",
                  resp_loan_basic(la, seq)) 
            seq += 1
            write(f"{out}/bank_009_loan_detail_{num}.json",
                  resp_loan_detail(la, seq)) 
            seq += 1

    # 은행-004 (주거래 계좌만)
    tl = build_transactions(persona, persona["final_balance"])
    body = {"rsp_code": "00000", "rsp_msg": "정상",
            "trans_cnt": len(tl), "trans_list": tl}
    write(f"{out}/bank_004_deposit_trans_{persona['main_account']}.json", body)

    # 사용자 입력
    write(f"{out}/user_profile.json", persona["profile"])
    if persona.get("savings_preferences") is not None:
        write(f"{out}/savings_preferences.json", persona["savings_preferences"])
    if persona.get("generation_metadata") is not None:
        write(f"{out}/generation_metadata.json", persona["generation_metadata"])

    n_files = len(os.listdir(out))
    print(f"  {persona['id']:36s} 파일 {n_files:2d}개  거래 {len(tl):3d}건  "
          f"최종잔액 {tl[0]['balance_amt']:>12,}원")
    return out


if __name__ == "__main__":
    print(f"출력: {OUT_ROOT}\n")
    persona_factories = (
        persona_a,
        persona_b,
        persona_c,
        persona_d,
        persona_e,
        *college_student_variant_factories(),
    )
    if SELECTED_PERSONA_ID is not None:
        persona_factories = tuple(
            fn for fn in persona_factories if fn()["id"] == SELECTED_PERSONA_ID
        )
        if not persona_factories:
            raise ValueError(f"알 수 없는 페르소나 ID: {SELECTED_PERSONA_ID}")
    for fn in persona_factories:
        p = fn()
        print(f"[{p['label']}]")
        generate(p)
        print()
