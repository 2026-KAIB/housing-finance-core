from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services.loan_product_catalog import (
    LoanProductCatalogUnavailable,
    load_configured_loan_candidates,
)
from app.services.region_trade import RegionTradesUnavailable, probe_region_trades
from app.services.savings_product_catalog import (
    SavingsProductCatalogUnavailable,
    load_configured_savings_candidates,
)

router = APIRouter(tags=["health"])
SEOUL = ZoneInfo("Asia/Seoul")


@router.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


def _loan_probe() -> int | None:
    return len(load_configured_loan_candidates(as_of=datetime.now(tz=SEOUL).date()))


def _savings_probe() -> int | None:
    return len(load_configured_savings_candidates(as_of=datetime.now(tz=SEOUL).date()))


def _region_probe() -> int | None:
    # 건수는 세지 않는다. 거래가 0건인 구와 조회 불가는 다른 상태이고, 준비
    # 확인이 답할 것은 뒤쪽뿐이다.
    probe_region_trades()
    return None


# (이름, 현재 설정값, 켜진 것으로 보는 값, 조회 함수, 조회 실패 예외)
_PROBES: tuple[
    tuple[str, Callable[[], str], frozenset[str], Callable[[], int | None], type[Exception]],
    ...,
] = (
    (
        "loan_product",
        lambda: settings.loan_product_provider,
        frozenset({"json", "database"}),
        _loan_probe,
        LoanProductCatalogUnavailable,
    ),
    (
        "savings_product",
        lambda: settings.savings_product_provider,
        frozenset({"database"}),
        _savings_probe,
        SavingsProductCatalogUnavailable,
    ),
    (
        "region_price",
        lambda: settings.region_price_provider,
        frozenset({"database"}),
        _region_probe,
        RegionTradesUnavailable,
    ),
)


@router.get("/ready")
def readiness_check() -> JSONResponse:
    """실제 계산이 쓰는 공급자를 **하나씩** 조회해 본다.

    구간마다 공급자가 다르므로 대출 하나만 확인하면 나머지가 죽어 있어도 배포가
    '준비됨'으로 통과한다. 홈서버 배포에서 `REGION_PRICE_PROVIDER`가 빠진 채
    올라가, 화면에서만 "실거래를 불러오지 못했습니다"로 드러난 적이 있다.

    **꺼짐(`disabled`)과 고장(`error`)을 뭉개지 않는다.** 꺼진 공급자는 설정으로
    고른 상태라 준비 실패가 아니고, 켜 놓고 조회에 실패한 것만 503이다. 응답에는
    공급자 이름과 건수만 담는다 — 접속 정보는 예외 로그에만 남는다.
    """

    providers: dict[str, dict[str, object]] = {}
    failed: list[str] = []
    for name, read_provider, enabled_values, probe, unavailable in _PROBES:
        provider = read_provider()
        if provider not in enabled_values:
            providers[name] = {"provider": provider, "status": "disabled"}
            continue
        try:
            count = probe()
        except unavailable:
            providers[name] = {"provider": provider, "status": "error"}
            failed.append(name)
            continue
        entry: dict[str, object] = {"provider": provider, "status": "ok"}
        if count is not None:
            entry["count"] = count
        providers[name] = entry

    body: dict[str, object] = {
        "status": "ready" if not failed else "not_ready",
        "service": settings.app_name,
        # 배포 스크립트와 컨테이너 헬스체크가 이미 읽는 두 키는 그대로 둔다.
        "loan_product_provider": settings.loan_product_provider,
        "loan_product_count": providers["loan_product"].get("count", 0),
        "providers": providers,
    }
    if failed:
        body["detail"] = "데이터 공급자가 준비되지 않았습니다: " + ", ".join(failed)
        return JSONResponse(status_code=503, content=body)
    return JSONResponse(content=body)
