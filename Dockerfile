FROM python:3.13-slim

WORKDIR /app

# Install system deps if needed (pycryptodome may need build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the whole IoTdeviceInfo project
COPY . /app/

# Install Python deps
RUN pip install --no-cache-dir -r backend/requirements.txt

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
