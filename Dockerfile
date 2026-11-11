# syntax=docker/dockerfile:1
# Прототип СППР: интерфейс ЛПР (Streamlit) и расчётные модули практик 2-7
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
# кэш загрузок pip и повторы - сборка переживает медленную сеть
RUN --mount=type=cache,target=/root/.cache/pip pip install --default-timeout=600 --retries 15 -r requirements.txt
COPY . .
EXPOSE 8501
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD curl -f http://localhost:8501/_stcore/health || exit 1
CMD ["streamlit", "run", "app/main.py", "--server.address=0.0.0.0", "--server.port=8501"]
