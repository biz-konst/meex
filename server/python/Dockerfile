FROM python:3.11-slim

WORKDIR /app

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем ВЕСЬ проект (сохраняя структуру)
COPY . /app

# ЯВНО копируем сертификаты в корень /app (туда, где их ищет код)
COPY server.crt server.key /app/

ENV PYTHONPATH=/app

EXPOSE 8765

CMD ["python", "server.py"]