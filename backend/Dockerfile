FROM python:3.12-slim
ARG ODENTALER_VERSION=dev
LABEL org.opencontainers.image.title="Der Odentaler Backend" \
      org.opencontainers.image.version="${ODENTALER_VERSION}"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/odentaler
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY odentaler.py ledger.py reporting.py web_admin.py provisioning.py ./
COPY migrations ./migrations
USER 10001
EXPOSE 8000
CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=2", "--access-logfile=-", "odentaler:create_app()"]
