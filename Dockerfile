FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# WeasyPrint는 순수 파이썬이 아니다. Pango/cairo/gdk-pixbuf를 dlopen 하므로
# 라이브러리가 없으면 import 자체가 OSError로 실패한다.
#
# fonts-noto-cjk가 없으면 **PDF 생성은 성공하는데 한글이 전부 두부(□□□)로 나간다.**
# 크기·형식 검사로는 절대 안 잡히는 실패라 이 줄을 지우면 조용히 망가진다.
# `app/reports/pdf.py::verify_korean_glyphs`가 런타임에서 한 번 더 확인한다.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
COPY sample_data ./sample_data

RUN python -m pip install --no-cache-dir ".[pdf]"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app

# 보고서 보관 루트. 컨테이너 밖 볼륨으로 마운트하지 않으면 컨테이너와 함께
# 사라진다 — 보관이 목적이라면 반드시 볼륨을 붙여야 한다.
RUN mkdir -p /var/lib/housing-finance/reports \
    && chown -R app:app /var/lib/housing-finance

USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
