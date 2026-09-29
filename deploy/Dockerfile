FROM python:3.12-slim

# 运行时仅需要 git（发布用）；验证为纯 HTTP 漏斗，不依赖 ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.yaml .
COPY src ./src
COPY .env.example .

ENV PYTHONPATH=/app/src
CMD ["python", "-m", "iptv_fetcher"]
