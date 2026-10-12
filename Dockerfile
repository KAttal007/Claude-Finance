# Application image: API, Celery workers and scheduler (design doc 22.1, Appendix G.1, G.8).
FROM python:3.12-slim

# Tesseract for scanned pages; headless LibreOffice Calc for recalculating workbooks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng libreoffice-calc-nogui libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv
WORKDIR /app
COPY requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt
COPY pyproject.toml README.md alembic.ini ./
COPY analekh ./analekh
RUN uv pip install --system --no-cache --no-deps .

RUN useradd --create-home --uid 10001 analekh
USER analekh
EXPOSE 8000
CMD ["uvicorn", "analekh.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
