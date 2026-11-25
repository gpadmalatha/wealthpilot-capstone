# WealthPilot API. Build from the repository root:  docker build -t wealthpilot:1.0 .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so this layer is cached until pyproject.toml changes.
COPY pyproject.toml ./
COPY src ./src
RUN pip install -e .

COPY prompts ./prompts
COPY configs ./configs
COPY evaluation ./evaluation
COPY scripts ./scripts

# Run as a non-root user. data/ and runtime/ are mounted as volumes (see docker-compose.yml).
RUN useradd --create-home --uid 10001 app && mkdir -p /app/runtime /app/data && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "capstone.api.main:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
