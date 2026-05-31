# Fixed Debian base (glibc) — has pip and manylinux wheels for pydantic/pycryptodome,
# so the build is fast and reliable. (Do NOT use ARG BUILD_FROM: the Supervisor injects
# an Alpine base that has no pip.)
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PETKIT_HUB_DATA=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/app/

EXPOSE 8099
CMD ["python", "-m", "app.main"]
