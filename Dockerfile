FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY decimal_iron ./decimal_iron
RUN pip install --no-cache-dir . \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin decimaliron

USER 10001:10001
EXPOSE 8080 8090
ENTRYPOINT ["python", "-m", "decimal_iron"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080", "--journal", "/var/lib/decimal-iron/ledger.jsonl"]
