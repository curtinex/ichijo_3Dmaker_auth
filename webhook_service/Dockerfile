FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# copy requirements and install
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# copy application
COPY . /app

ENV PORT 5000

# Use uvicorn to serve the FastAPI app. Use shell form so $PORT is expanded at runtime
CMD sh -c "uvicorn webhook_fastapi:app --host 0.0.0.0 --port $PORT"
