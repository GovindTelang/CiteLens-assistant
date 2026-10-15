
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    HOME=/home/user \
    HF_HOME=/home/user/.cache/huggingface \
    XDG_CACHE_HOME=/home/user/.cache \
    STREAMLIT_SERVER_HEADLESS=true

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    tesseract-ocr \
    libtesseract-dev \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 user

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user src/ ./src/
COPY --chown=user:user app.py ./

RUN mkdir -p /home/user/.cache/huggingface /home/user/.streamlit \
    && chown -R user:user /home/user /app

USER user

EXPOSE 7860

HEALTHCHECK CMD curl --fail http://localhost:7860/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true"]
