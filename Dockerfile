# Stage 1 — install dependencies with uv
FROM python:3.13-slim AS builder
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Stage 2 — runtime
FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY src/ src/
COPY ui.py .
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8501
ENTRYPOINT ["streamlit", "run", "ui.py", \
  "--server.port=8501", \
  "--server.address=0.0.0.0", \
  "--server.headless=true"]
