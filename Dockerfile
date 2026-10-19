FROM python:3.12-slim
RUN pip install --no-cache-dir tzdata==2025.2
WORKDIR /app
COPY collector ./collector
ENV PYTHONUNBUFFERED=1 EW_DB=/data/earlywarn.db
CMD ["python3", "-m", "collector.main"]
