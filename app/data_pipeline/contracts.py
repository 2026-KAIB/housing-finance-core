from collections.abc import Iterable
from typing import Protocol, TypeVar

RawRecord = TypeVar("RawRecord")
NormalizedRecord = TypeVar("NormalizedRecord")


class DataProvider(Protocol[RawRecord]):
    def fetch(self) -> Iterable[RawRecord]:
        """원천에서 레코드를 읽습니다."""


class Normalizer(Protocol[RawRecord, NormalizedRecord]):
    def normalize(self, record: RawRecord) -> NormalizedRecord:
        """원천 레코드를 내부 표준 모델로 변환합니다."""


class Loader(Protocol[NormalizedRecord]):
    def load(self, records: Iterable[NormalizedRecord]) -> int:
        """정규화 레코드를 저장하고 적재 건수를 반환합니다."""

