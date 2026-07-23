FROM python:3.11-slim@sha256:b27df5841f3355e9473f9a516d38a6783b6c8dfeacaf2d14a240f443b368ddb6

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home --uid 10001 reconradar
COPY --chown=reconradar:reconradar . .

# The SQLite case ledger lives at data/runtime/tens_hq.sqlite3 (bd_page.py),
# but data/runtime is .dockerignore'd, so it does not exist in the image.
# Create it and hand ownership to the runtime user WHILE STILL ROOT, before
# declaring it a mount point -- a bare VOLUME on a path that does not yet
# exist would make Docker auto-create it root-owned, which uid 10001 could
# not write, silently breaking the ledger.
RUN mkdir -p /app/data/runtime && chown -R reconradar:reconradar /app/data
VOLUME ["/app/data/runtime"]

USER reconradar
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.enableWebsocketCompression=false"]
