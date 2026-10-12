FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 taste
WORKDIR /app
COPY pyproject.toml ./
COPY tasteserver ./tasteserver
COPY start.sh prompts.toml ./
RUN pip install --no-cache-dir .
USER taste
ENV PYTHONUNBUFFERED=1
CMD ["./start.sh"]
