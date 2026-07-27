"""Mock 데이터 검증 — 페르소나 전체

사용법
    python3 validate_all.py [Mock루트디렉토리]
"""
import glob
import json
import os
import sys
from datetime import datetime

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/mock"

IN_TYPES = {"03", "04", "06", "98"}
OUT_TYPES = {"02", "05", "07", "99"}
VALID_TRANS = IN_TYPES | OUT_TYPES | {"01"}
VALID_SAVING = {"01", "02", "03", "04"}
VALID_REPAY = {f"{n:02d}" for n in range(1, 13)}
DEPOSIT_TYPES = {"1001", "1002", "1003", "1999"}
INVEST_TYPES = {"2001", "2002", "2003", "2004", "2999"}
LOAN_PREFIX = "3"


class Report:
    def __init__(self, name):
        self.name = name
        self.ok = 0
        self.fails = []

    def chk(self, cond, msg):
        if cond:
            self.ok += 1
        else:
            self.fails.append(msg)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_date(s, n=8):
    if not isinstance(s, str) or len(s) != n or not s.isdigit():
        return False
    try:
        datetime.strptime(s[:8], "%Y%m%d")
        return True
    except ValueError:
        return s == "99991231"


def validate(d):
    r = Report(os.path.basename(d))
    files = {os.path.basename(p) for p in glob.glob(f"{d}/*.json")}

    # ── 은행-001 ──────────────────────────────────
    acc = load(f"{d}/bank_001_accounts.json")
    r.chk(acc["rsp_code"] == "00000", "rsp_code")
    r.chk(acc["account_cnt"] == len(acc["account_list"]), "account_cnt 일치")
    r.chk(is_date(acc["reg_date"]), "reg_date 형식")

    accounts = acc["account_list"]
    nums = {a["account_num"] for a in accounts}

    for a in accounts:
        n, t = a["account_num"], a["account_type"]
        r.chk(isinstance(t, str) and len(t) == 4, f"{n} account_type 4자리 문자열")
        r.chk(a["account_status"] == "01", f"{n} account_status")
        r.chk(isinstance(a["is_consent"], bool), f"{n} is_consent bool")
        r.chk(t in DEPOSIT_TYPES | INVEST_TYPES or t.startswith(LOAN_PREFIX),
              f"{n} account_type 유효 ({t})")

        # 참조 무결성
        if t in DEPOSIT_TYPES | INVEST_TYPES:
            r.chk(f"bank_002_deposit_basic_{n}.json" in files, f"{n} 은행-002 존재")
            r.chk(f"bank_003_deposit_detail_{n}.json" in files, f"{n} 은행-003 존재")
            r.chk("is_minus" in a, f"{n} is_minus 필드")
        if t.startswith(LOAN_PREFIX):
            r.chk(f"bank_008_loan_basic_{n}.json" in files, f"{n} 은행-008 존재")
            r.chk(f"bank_009_loan_detail_{n}.json" in files, f"{n} 은행-009 존재")
            r.chk("is_minus" not in a, f"{n} 대출계좌에 is_minus 없음")

        # 마이너스통장: 수신+대출 양쪽
        if a.get("is_minus"):
            r.chk(f"bank_008_loan_basic_{n}.json" in files,
                  f"{n} 마이너스통장 은행-008 존재")
            r.chk(f"bank_009_loan_detail_{n}.json" in files,
                  f"{n} 마이너스통장 은행-009 존재")

    # ── 은행-002 ──────────────────────────────────
    for p in glob.glob(f"{d}/bank_002_*.json"):
        b, num = load(p), os.path.basename(p)[24:-5]
        r.chk(b["basic_cnt"] == len(b["basic_list"]), f"{num} basic_cnt")
        x = b["basic_list"][0]
        r.chk(x["saving_method"] in VALID_SAVING, f"{num} saving_method")
        r.chk(is_date(x["issue_date"]), f"{num} issue_date 형식")
        if "exp_date" in x:
            r.chk(is_date(x["exp_date"]), f"{num} exp_date 형식")
            r.chk(x["issue_date"] < x["exp_date"], f"{num} issue<exp")
        r.chk(x.get("currency_code") == "KRW", f"{num} currency_code")

    # ── 은행-003 ──────────────────────────────────
    detail_map = {}
    for p in glob.glob(f"{d}/bank_003_*.json"):
        b, num = load(p), os.path.basename(p)[25:-5]
        r.chk(b["detail_cnt"] == len(b["detail_list"]), f"{num} detail_cnt")
        x = b["detail_list"][0]
        detail_map[num] = x
        r.chk(x["withdrawable_amt"] <= abs(x["balance_amt"]) or x["balance_amt"] < 0,
              f"{num} withdrawable<=balance")
        r.chk(isinstance(x["offered_rate"], (int, float)), f"{num} offered_rate 숫자")
        r.chk(0 <= x["offered_rate"] < 1,
              f"{num} offered_rate 소수 표기 ({x['offered_rate']})")

    # ── 은행-008 / 009 ────────────────────────────
    for p in glob.glob(f"{d}/bank_008_*.json"):
        b, num = load(p), os.path.basename(p)[21:-5]
        r.chk(b["repay_method"] in VALID_REPAY, f"{num} repay_method")
        r.chk(is_date(b["issue_date"]) and is_date(b["exp_date"]),
              f"{num} 대출 날짜 형식")
        r.chk(b["issue_date"] < b["exp_date"], f"{num} 대출 issue<exp")
        r.chk(0 <= b["last_offered_rate"] < 1,
              f"{num} last_offered_rate 소수 ({b['last_offered_rate']})")
        if "repay_account_num" in b:
            r.chk(b["repay_account_num"] in nums, f"{num} 상환계좌 참조 유효")
            r.chk(len(b["repay_org_code"]) == 8, f"{num} repay_org_code 8자리")
        if "unredeemed_start" in b:
            r.chk(len(b["unredeemed_start"]) == 6, f"{num} unredeemed_start 6자리")
            r.chk(b["unredeemed_start"] < b["unredeemed_end"],
                  f"{num} 거치 시작<종료")
        # 한도거래는 repay_date 미회신
        if b["repay_method"] == "08":
            r.chk("repay_date" not in b, f"{num} 한도거래 repay_date 생략")

    for p in glob.glob(f"{d}/bank_009_*.json"):
        b, num = load(p), os.path.basename(p)[22:-5]
        r.chk("detail_list" not in b, f"{num} 은행-009는 Body 직속 (배열 아님)")
        r.chk(b["balance_amt"] <= b["loan_principal"],
              f"{num} 대출잔액<=원금")
        r.chk(b["balance_amt"] > 0, f"{num} 대출잔액 양수")

    # ── 은행-004 ──────────────────────────────────
    tp = glob.glob(f"{d}/bank_004_*.json")
    r.chk(len(tp) >= 1, "거래내역 파일 존재")
    for p in tp:
        b = load(p)
        num = os.path.basename(p)[24:-5]
        tl = b["trans_list"]
        r.chk(b["trans_cnt"] == len(tl), f"{num} trans_cnt")
        r.chk(all(t["trans_type"] in VALID_TRANS for t in tl),
              f"{num} trans_type 유효")
        r.chk(all(t["trans_amt"] > 0 for t in tl), f"{num} trans_amt 양수")
        r.chk(all(len(t["trans_dtime"]) == 14 for t in tl),
              f"{num} trans_dtime 14자리")
        r.chk(tl[0]["trans_dtime"] > tl[-1]["trans_dtime"],
              f"{num} 내림차순 정렬")
        r.chk(len({t["trans_dtime"] for t in tl}) == len(tl),
              f"{num} 타임스탬프 중복 없음")
        r.chk(tl[0]["trans_dtime"][:8] <= "20260724",
              f"{num} 미래 거래 없음")

        # 잔액 시계열
        srt = sorted(tl, key=lambda x: x["trans_dtime"])
        bad = 0
        for k in range(1, len(srt)):
            dlt = (srt[k]["trans_amt"] if srt[k]["trans_type"] in IN_TYPES
                   else -srt[k]["trans_amt"])
            if srt[k - 1]["balance_amt"] + dlt != srt[k]["balance_amt"]:
                bad += 1
        r.chk(bad == 0, f"{num} 잔액 시계열 정합 (오류 {bad}건)")
        r.chk(srt[0]["balance_amt"] >= 0, f"{num} 시작잔액 음수 아님")

        # 은행-003과 최종잔액 일치
        if num in detail_map:
            r.chk(srt[-1]["balance_amt"] == detail_map[num]["balance_amt"],
                  f"{num} 최종잔액 == 은행-003")

        # 대출 상환 자동이체 존재 및 금액 일정
        pay_memos = {t["trans_memo"] for t in tl
                     if "원리금" in t["trans_memo"] or "이자" in t["trans_memo"]
                     or "할부금" in t["trans_memo"] or "상환" in t["trans_memo"]}
        for memo in pay_memos:
            if memo == "이자":
                continue
            amts = {t["trans_amt"] for t in tl if t["trans_memo"] == memo}
            # 마이너스통장 이자는 사용액 변동에 따라 매월 다름 (정상)
            if "마이너스통장" in memo:
                lo, hi = min(amts), max(amts)
                r.chk(hi <= lo * 1.5,
                      f"{num} '{memo}' 변동폭 합리 ({lo:,}~{hi:,})")
            else:
                r.chk(len(amts) <= 2, f"{num} '{memo}' 금액 일정 ({len(amts)}종)")

    # 대출 계좌마다 상환 이체 기록이 있는지
    all_memos = set()
    for p in tp:
        all_memos |= {t["trans_memo"] for t in load(p)["trans_list"]}
    loan_cnt = sum(1 for a in accounts
                   if a["account_type"].startswith("3") or a.get("is_minus"))
    pay_cnt = sum(1 for m in all_memos
                  if any(k in m for k in ("원리금", "이자", "할부금", "상환"))
                  and m != "이자")
    r.chk(pay_cnt >= loan_cnt,
          f"대출 {loan_cnt}건 대비 상환이체 {pay_cnt}종")

    # ── user_profile ──────────────────────────────
    up = load(f"{d}/user_profile.json")
    for k in ("birth_year", "marital_status", "household_size",
              "is_first_home_buyer", "owns_property", "lease_deposit",
              "target_region", "target_price", "target_move_in_ym",
              "annual_income_verified", "planned_expenses",
              "risk_preference"):
        r.chk(k in up, f"user_profile.{k} 존재")
    r.chk(len(up["target_region"]) == 5, "target_region 5자리")
    r.chk(len(up["target_move_in_ym"]) == 6, "target_move_in_ym 6자리")

    return r


if __name__ == "__main__":
    # 목적: 실행기 import가 만든 __pycache__ 같은 보조 폴더를 페르소나로
    # 오인하지 않고, 생성 규약인 persona_* 데이터만 검증한다.
    dirs = sorted(
        p
        for p in glob.glob(f"{ROOT}/*")
        if os.path.isdir(p) and os.path.basename(p).startswith("persona_")
    )
    total_ok = total_fail = 0
    for d in dirs:
        r = validate(d)
        total_ok += r.ok
        total_fail += len(r.fails)
        mark = "PASS" if not r.fails else "FAIL"
        print(f"[{mark}] {r.name:36s} 통과 {r.ok:3d} / 실패 {len(r.fails)}")
        for f in r.fails:
            print(f"        - {f}")
    print(f"\n합계: 통과 {total_ok} / 실패 {total_fail}")
    sys.exit(1 if total_fail else 0)
