FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.lock.txt .
RUN python -m pip install --no-cache-dir --timeout 600 --retries 10 --index-url https://pypi.org/simple pip==26.2 \
    && python -m pip install --no-cache-dir --timeout 600 --retries 10 --index-url https://pypi.org/simple -r requirements.lock.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
