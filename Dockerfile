# stage 1: build stage
FROM python:3.11-slim AS builder
WORKDIR /app

# install build dependencies
RUN apt-get update && apt-get install -y gcc libpq-dev

# install requirements directly to the system
COPY requirements.txt .
RUN pip install --no-cache-dir gunicorn && \
    pip install --no-cache-dir -r requirements.txt

# stage 2: runtime stage
FROM python:3.11-slim
WORKDIR /app

# install runtime dependencies and curl
RUN apt-get update && apt-get install -y libpq5 curl && rm -rf /var/lib/apt/lists/*

# create user
RUN useradd -m appuser

# copy all content from the builder's python packages

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# copy app code
COPY --chown=appuser:appuser . .

# making appuser the owner of the /app directory so it can create the migrations folder
RUN chown -R appuser:appuser /app

RUN chmod +x /app/entrypoint.sh

USER appuser

# path added explicitly
ENV PATH="/usr/local/bin:${PATH}"

# setting PYTHONUNBUFFERED=1 to ensure that logs are printed as generated and not buffered
ENV PYTHONUNBUFFERED=1

# exposing port 8080 for use
EXPOSE 8080

# performing health check via /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# refers to entrypoint.sh file to exeucte db migrations
CMD ["./entrypoint.sh"]