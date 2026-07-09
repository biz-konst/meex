#!/usr/bin/env python3
import asyncio
import websockets
import argparse
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("websocket-ipc-server")

CMD_PING = 1
CMD_PONG = 2

async def ipc_handler(websocket):
    logger.info(f"Новое соединение: {websocket.remote_address}")
    try:
        async for raw in websocket:
            logger.debug(f"Получено: {raw}")
            try:
                msg = json.loads(raw)
                req_id = msg.get("reqId")
                cmd = msg.get("cmd")
                data = msg.get("data")

                if cmd == CMD_PING:
                    logger.info(f"PING reqId={req_id}, data={data}")
                    response = {
                        "reqId": req_id,
                        "cmd": CMD_PONG,
                        "data": data
                    }
                    await websocket.send(json.dumps(response))
                    logger.debug(f"PONG отправлен: {response}")
                else:
                    logger.warning(f"Неизвестная команда: {cmd}")
                    await websocket.send(json.dumps({"error": "unknown cmd"}))
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка JSON: {e}")
                await websocket.send(json.dumps({"error": "invalid json"}))
    except websockets.exceptions.ConnectionClosed:
        logger.info("Соединение закрыто")
    except Exception as e:
        logger.error(f"Ошибка: {e}")

async def main(host="0.0.0.0", port=8765):
    logger.info(f"Запуск сервера на {host}:{port}")
    async with websockets.serve(ipc_handler, host, port, ping_interval=None, ping_timeout=None):
        await asyncio.Future()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.host, args.port))
    except KeyboardInterrupt:
        logger.info("Сервер остановлен")