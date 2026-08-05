#!/bin/bash
cd "$(dirname "$0")/.." || exit

TEST_FLAG=""
if [ "$1" == "--test" ]; then
    TEST_FLAG="--test"
fi

git pull

docker stop ws-meex-app 2>/dev/null
docker rm ws-meex-app 2>/dev/null

docker build -t meex-server -f deploy/Dockerfile .

docker run -d --restart unless-stopped --name ws-meex-app -p 8765:8765 meex-server python python/server.py $TEST_FLAG

docker logs ws-meex-app