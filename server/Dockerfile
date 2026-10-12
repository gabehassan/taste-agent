FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 taste
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
# Install the exact versions in uv.lock, the ones the tests ran against.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY tasteserver ./tasteserver
COPY start.sh prompts.toml ./
RUN uv sync --locked --no-dev
USER taste
CMD ["./start.sh"]
