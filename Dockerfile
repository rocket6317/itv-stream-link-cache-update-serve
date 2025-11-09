# Use a lightweight Python base image
FROM python:3.11-slim

# Disable Python output buffering so logs appear immediately
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Expose internal port
EXPOSE 8000

# Run the app with Gunicorn using Uvicorn worker
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--log-level", "debug"]
