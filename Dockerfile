FROM python:3.13-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

ENV HELPDESK_DB=/data/helpdesk.db
RUN mkdir -p /data
# Tickets live here: run with a named volume (-v helpdesk-data:/data), otherwise
# they are lost when the container is recreated (incident on v0.3.0)
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
