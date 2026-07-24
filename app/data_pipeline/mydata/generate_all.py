"""마이데이터 Mock 생성기 — 페르소나 4종

설계 원칙
- 표준 API 응답 형식만 출력 (계산 결과 미포함)
- 시나리오는 역산으로 구성 (월 상환액 → balance_amt/rate/exp_date)
- 거래내역 balance_amt 시계열 정합성 보장
- 대출 상환액이 거래내역 자동이체와 일치

사용법
    python3 generate_all.py [출력디렉토리]
"""
import json
import os
import random
import sys
from datetime import datetime
from dateutil.relativedelta import relativedelta

BASE = datetime(2026, 7, 24)
MONTHS = 12
IN_TYPES = {"03", "04", "06", "98"}

OUT_ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))

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
    rd = relativedelta(target, base)
    return rd.years * 12 + rd.months


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
    start = (BASE - relativedelta(months=MONTHS - 1)).replace(day=1)
    return [start + relativedelta(months=k) for k in range(MONTHS)]


def build_transactions(persona, final_balance):
    """거래 생성 → 잔액 역산 → 내림차순 반환"""
    rnd = random.Random(persona["seed"])
    txs = []

    for d0 in month_starts():
        y, mo = d0.year, d0.month

        # ── 소득 ──────────────────────────────────
        for inc in persona["incomes"]:
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
        for _ in range(rnd.randint(*persona["card_tx_per_month"])):
            name, lo, hi = rnd.choice(CARD_MERCHANTS)
            while True:
                key = (rnd.randint(1, 28), rnd.randint(8, 21),
                       rnd.randint(0, 59), rnd.randint(0, 59))
                if key not in used:
                    used.add(key)
                    break
            txs.append(dict(
                d=datetime(y, mo, key[0], key[1], key[2], key[3]),
                type="02", cls="체크카드",
                amt=rnd.randrange(lo, hi, 500), memo=name))

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
    return (BASE + relativedelta(seconds=seq)).strftime("%Y%m%d%H%M%S")


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
                  resp_deposit_basic(a, seq)); seq += 1
            write(f"{out}/bank_003_deposit_detail_{num}.json",
                  resp_deposit_detail(a, seq)); seq += 1

        # 대출 → 은행-008 / 009
        if t[0] == "3":
            write(f"{out}/bank_008_loan_basic_{num}.json",
                  resp_loan_basic(a, seq)); seq += 1
            write(f"{out}/bank_009_loan_detail_{num}.json",
                  resp_loan_detail(a, seq)); seq += 1

        # 마이너스통장 → 수신 + 대출 양쪽
        if a.get("is_credit_line"):
            la = dict(a, balance_amt=a["loan_balance_amt"])
            write(f"{out}/bank_008_loan_basic_{num}.json",
                  resp_loan_basic(la, seq)); seq += 1
            write(f"{out}/bank_009_loan_detail_{num}.json",
                  resp_loan_detail(la, seq)); seq += 1

    # 은행-004 (주거래 계좌만)
    tl = build_transactions(persona, persona["final_balance"])
    body = {"rsp_code": "00000", "rsp_msg": "정상",
            "trans_cnt": len(tl), "trans_list": tl}
    write(f"{out}/bank_004_deposit_trans_{persona['main_account']}.json", body)

    # 사용자 입력
    write(f"{out}/user_profile.json", persona["profile"])

    n_files = len(os.listdir(out))
    print(f"  {persona['id']:36s} 파일 {n_files:2d}개  거래 {len(tl):3d}건  "
          f"최종잔액 {tl[0]['balance_amt']:>12,}원")
    return out


if __name__ == "__main__":
    print(f"출력: {OUT_ROOT}\n")
    for fn in (persona_a, persona_b, persona_c, persona_d):
        p = fn()
        print(f"[{p['label']}]")
        generate(p)
        print()
