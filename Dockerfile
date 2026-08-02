# ShareHub — self-hosted resource sharing station
FROM python:3.12-slim

LABEL org.opencontainers.image.title="ShareHub"
LABEL org.opencontainers.image.description="Self-hosted resource sharing station: admin uploads, visitors download without login."
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY server.py server-en.py config.json /app/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 界面语言：zh（默认，中文）/ en（英文）。通过 -e SHARE_LANG=en 切换。
ENV SHARE_LANG=zh

VOLUME ["/app/files", "/app/logs"]
EXPOSE 18888

CMD ["sh", "-c", "if [ \"$SHARE_LANG\" = \"en\" ]; then exec python server-en.py --host 0.0.0.0 --port 18888 --prefix \"\"; else exec python server.py --host 0.0.0.0 --port 18888 --prefix \"\"; fi"]
