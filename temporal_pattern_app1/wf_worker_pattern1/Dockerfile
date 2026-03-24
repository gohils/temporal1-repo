FROM python:3.12-slim

WORKDIR /app

# Copy Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy worker code
COPY . .

CMD ["python", "ai_temporal_worker_pattern1.py"]