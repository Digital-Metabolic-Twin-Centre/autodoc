FROM python:3.11-slim

EXPOSE 8000

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install runtime dependencies with uv
COPY pyproject.toml .
RUN python -m pip install uv && uv sync --system --no-dev --no-install-project

WORKDIR /app
COPY . /app

RUN mkdir -p /app/src/files /app/log && \
    useradd -m -u 5678 autodoc_user && chown -R autodoc_user:autodoc_user /app

USER autodoc_user

CMD ["python", "src/main.py"]
