#!/bin/bash
git pull
docker stop ws-meex-app 2>/dev/null
docker rm ws-meex-app 2>/dev/null
docker build -t meex-server .
docker run -d --restart unless-stopped --name ws-meex-app -p 8765:8765 meex-server