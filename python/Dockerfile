FROM python:3.12-slim AS builder

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS final

WORKDIR /app

COPY --from=builder /install /usr/local
COPY app.py .
COPY templates/ templates/

USER 10001

EXPOSE 80

CMD ["gunicorn", "--bind", "0.0.0.0:80", "--workers", "2", "--no-control-socket", "app:app"]
