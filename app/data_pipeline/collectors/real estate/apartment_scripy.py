import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

load_dotenv()
APARTMENT_API_KEY = (os.getenv("APARTMENT_API_KEY") or "").strip()
if len(APARTMENT_API_KEY) != 64:
    raise SystemExit(f"키 로드 실패: len={len(APARTMENT_API_KEY)}")

ENDPOINTS = {
    ("아파트", "매매"): "RTMSDataSvcAptTradeDev",
    ("아파트", "전월세"): "RTMSDataSvcAptRent",
    ("오피스텔", "매매"): "RTMSDataSvcOffiTrade",
    ("오피스텔", "전월세"): "RTMSDataSvcOffiRent",
    ("연립다세대", "매매"): "RTMSDataSvcRHTrade",
    ("연립다세대", "전월세"): "RTMSDataSvcRHRent",
    ("단독다가구", "매매"): "RTMSDataSvcSHTrade",
}

def fetch(prop, trade, lawd_cd, deal_ymd, page=1, rows=1000):
    svc = ENDPOINTS[(prop, trade)]
    url = f"https://apis.data.go.kr/1613000/{svc}/get{svc}"
    params = {
        "serviceKey": APARTMENT_API_KEY,
        "LAWD_CD": lawd_cd,
        "DEAL_YMD": deal_ymd,
        "pageNo": page,
        "numOfRows": rows,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()

    root = ET.fromstring(r.content)
    code = root.findtext(".//resultCode")
    if code not in ("00", "000"):
        raise RuntimeError(f"{code}: {root.findtext('.//resultMsg')}")

    items = [{c.tag: (c.text or "").strip() for c in item}
             for item in root.iter("item")]
    total = int(root.findtext(".//totalCount") or 0)
    return items, total


def fetch_month(prop, trade, lawd_cd, deal_ymd):
    """페이징 포함 한 달치 전량"""
    all_items, page = [], 1
    while True:
        items, total = fetch(prop, trade, lawd_cd, deal_ymd, page)
        all_items.extend(items)
        if len(all_items) >= total or not items:
            break
        page += 1
        time.sleep(0.2)
    return all_items


def month_range(start, end):
    cur = datetime.strptime(start, "%Y%m")
    last = datetime.strptime(end, "%Y%m")
    while cur <= last:
        yield cur.strftime("%Y%m")
        cur += relativedelta(months=1)


def collect(prop, trade, lawd_list, start, end):
    frames = []
    for lawd in lawd_list:
        for ymd in month_range(start, end):
            for attempt in range(3):
                try:
                    items = fetch_month(prop, trade, lawd, ymd)
                    if items:
                        df = pd.DataFrame(items)
                        df["지역코드"] = lawd
                        frames.append(df)
                    print(f"{lawd} {ymd}: {len(items)}건")
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"{lawd} {ymd} 실패: {e}")
                    time.sleep(2 ** attempt)
            time.sleep(0.3)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def clean(df):
    if df.empty:
        return df
    num_cols = ["dealAmount", "deposit", "monthlyRent",
                "excluUseAr", "buildYear", "floor"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(
                df[c].astype(str).str.replace(",", "").str.strip(),
                errors="coerce"
            )
    if {"dealYear", "dealMonth", "dealDay"}.issubset(df.columns):
        df["계약일"] = pd.to_datetime(
            df["dealYear"] + "-" + df["dealMonth"].str.zfill(2)
            + "-" + df["dealDay"].str.zfill(2),
            errors="coerce"
        )
    if {"dealAmount", "excluUseAr"}.issubset(df.columns):
        df["평단가_만원"] = (df["dealAmount"] / (df["excluUseAr"] / 3.3058)).round(0)
    return df


if __name__ == "__main__":
    # 서울 전체 구(25개)
    df = collect("아파트", "매매",
                 ["11110","11140","11170","11200","11215","11230","11260","11290",
         "11305","11320","11350","11380","11410","11440","11470","11500",
         "11530","11545","11560","11590","11620","11650","11680","11710","11740"],  
                 "202507", "202607")
    df = clean(df)
    df.to_csv("apt_trades_seoul.csv", index=False, encoding="utf-8-sig")
    print(df.shape)