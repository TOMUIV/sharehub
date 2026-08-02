# ShareHub — self-hosted resource sharing station
FROM python:3.12-slim

LABEL org.opencontainers.image.title="ShareHub"
LABEL org.opencontainers.image.description="Self-hosted resource sharing station: admin uploads, visitors download without login."
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY server.py config.json /app/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

VOLUME ["/app/files", "/app/logs"]
EXPOSE 18888

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "18888", "--prefix", ""]
