FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.4.30 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml README.md ./
COPY t2r ./t2r
COPY alembic.ini ./
RUN uv pip install --system .

EXPOSE 8000
CMD ["uvicorn", "t2r.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
