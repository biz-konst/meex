FROM python:3.11-slim

WORKDIR /app

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем ВЕСЬ проект (сохраняя структуру папок)
COPY . /app

# Добавляем корень проекта в PYTHONPATH
ENV PYTHONPATH=/app

# Открываем порт (в твоём коде используется 8765)
EXPOSE 8765

# Запускаем серверный скрипт (не модуль!)
CMD ["python", "server.py"]