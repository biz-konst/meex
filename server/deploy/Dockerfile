FROM python:3.11-slim

WORKDIR /app

# Копируем requirements.txt из папки python/
COPY python/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект (сохраняя структуру)
COPY . .

# Устанавливаем PYTHONPATH, чтобы импорты из python/ работали
ENV PYTHONPATH=/app

EXPOSE 8765

# Запускаем сервер (путь от корня /app)
CMD ["python", "python/server.py"]