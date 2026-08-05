#!/bin/bash

# Если скрипт запущен без флага --updated, то сначала обновляемся, потом перезапускаемся
if [ "$1" != "--updated" ]; then
    echo "Обновление репозитория..."
    cd "$(dirname "$0")/.." || exit
    git pull

    # Перезапускаем этот же скрипт с флагом --updated
    exec "$0" --updated "$@"
    exit
fi

# --- Теперь выполняем основную логику (уже в обновлённой версии) ---
echo "Запуск деплоя с обновлённым скриптом"

cd "$(dirname "$0")/.." || exit

docker stop ws-meex-app 2>/dev/null
docker rm ws-meex-app 2>/dev/null

docker build -t meex-server -f deploy/Dockerfile .

# Если передан аргумент --test, добавляем его
TEST_FLAG=""
if [[ "$*" == *"--test"* ]]; then
    TEST_FLAG="--test"
fi

docker run -d --restart unless-stopped --name ws-meex-app -p 8765:8765 meex-server python python/server.py $TEST_FLAG

docker logs ws-meex-app