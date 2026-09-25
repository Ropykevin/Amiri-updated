FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/uploads/crm static/uploads/blog \
    && useradd --create-home --uid 1000 amiri \
    && chown -R amiri:amiri /app

USER amiri

ENV APP_ENV=production \
    FLASK_DEBUG=0 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
