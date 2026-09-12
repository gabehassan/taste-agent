FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY tasteserver ./tasteserver
COPY start.sh ./start.sh
RUN pip install --no-cache-dir .
ENV PYTHONUNBUFFERED=1
CMD ["./start.sh"]
