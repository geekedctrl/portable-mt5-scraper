FROM python:3.12-slim
WORKDIR /app
COPY dashboard/server.py /app/server.py
COPY dashboard/static/ /app/static/
COPY dashboard/static/openapi.json /app/static/openapi.json
COPY dashboard/static/swagger.html /app/static/swagger.html
USER 1001:1001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/data/market.db
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["python", "server.py"]
