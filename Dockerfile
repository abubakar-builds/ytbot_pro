# For hosts that run containers (Render, Railway, Fly.io, VPS).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# JavaScript runtime recommended by recent yt-dlp versions for YouTube.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PORT=8080
CMD gunicorn app:app --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 300
