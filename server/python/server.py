#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
import ssl
import sys
import time

import websockets

from protocol import binary_protocol
from protocol.binary_protocol import PROTOCOL_VERSION, CMD_PING, CMD_PONG, CMD_INFO, serialize_protocol
from protocol.encode_decode import decode_message, encode_message
from protocol import test_protocol

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("websocket-ipc-server")

# Создаём экземпляр бинарного протокола (версия 1, команды CMD_PING/CMD_PONG)
BINARY_PROTOCOL = binary_protocol.create_default_protocol()


async def ipc_handler(websocket):
    logger.info(f"Новое соединение: {websocket.remote_address}")
    try:
        async for raw in websocket:
            use_binary = not isinstance(raw, str)
            msg = decode_message(raw, use_binary, BINARY_PROTOCOL, logger)
            if msg is None:
                continue

            if msg.get("v") != PROTOCOL_VERSION:
                continue

            cmd = msg.get("c")

            # --- Обработка PING (существующая логика) ---
            if cmd == CMD_PING:
                dto = msg.get("d") or {}
                pong_delay = dto.get("pong")
                if pong_delay is not None and pong_delay < 0:
                    continue

                req_id = dto.get("reqId")
                timestamp = dto.get("ts")
                received_time = int(time.time() * 1000) if timestamp is not None else None
                delay_ms = pong_delay if pong_delay and pong_delay > 0 else 0

                async def send_pong(delay, req_id, timestamp, received_time):
                    try:
                        if delay > 0:
                            await asyncio.sleep(delay / 1000.0)

                        response = {"v": PROTOCOL_VERSION, "c": CMD_PONG}
                        dto = {}
                        if req_id:
                            dto["replyTo"] = req_id
                        if timestamp is not None:
                            dto["ts"] = [timestamp, received_time]
                        if dto:
                            response["d"] = dto

                        await websocket.send(encode_message(response, use_binary, BINARY_PROTOCOL, logger))
                    except Exception:
                        pass

                asyncio.create_task(send_pong(delay_ms, req_id, timestamp, received_time))

            # --- НОВАЯ ОБРАБОТКА CMD_INFO ---
            elif cmd == CMD_INFO:
                logger.info("Получен запрос INFO, отправляем метаданные протокола")
                info_data = serialize_protocol(BINARY_PROTOCOL)
                response = {
                    "v": PROTOCOL_VERSION,
                    "c": CMD_INFO,
                    "d": {"commands": info_data["commands"]}
                }
                await websocket.send(encode_message(response, use_binary, BINARY_PROTOCOL, logger))

            # --- НОВАЯ ЛОГИКА: эхо для команд > 50 ---
            elif cmd > 50:
                logger.info(f"Echo command {cmd}")
                await websocket.send(encode_message(msg, use_binary, BINARY_PROTOCOL, logger))

            # --- Остальные команды игнорируются ---
            else:
                pass

    except websockets.exceptions.ConnectionClosed:
        logger.info("Соединение закрыто")
    except Exception as e:
        logger.error(f"Ошибка: {e}")


def get_script_dir(follow_symlinks=True):
    """
    This function returns the correct script path only if defined in the script's root directory.
    """
    from os import path as ospath
    import sys
    import inspect

    if getattr(sys, 'frozen', False):  # py2exe, PyInstaller, cx_Freeze
        path = ospath.abspath(sys.executable)
    else:
        path = inspect.getabsfile(get_script_dir)

    if follow_symlinks: path = ospath.realpath(path)

    path = ospath.dirname(path)
    if ospath.basename(path) == 'tools':
        path = ospath.dirname(path)

    return path


async def main(host="0.0.0.0", port=8765, use_test=False):
    global BINARY_PROTOCOL
    if use_test:
        BINARY_PROTOCOL = test_protocol.create_test_protocol()
        logger.info("🧪 Используется ТЕСТОВЫЙ протокол (команды 51-56)")
    else:
        BINARY_PROTOCOL = binary_protocol.create_default_protocol()
        logger.info("📦 Используется СТАНДАРТНЫЙ протокол (INFO, PING, PONG)")

    # Правильный путь: на две папки выше
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cert_path = os.path.join(base_dir, "server.crt")
    key_path = os.path.join(base_dir, "server.key")

    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(certfile=cert_path, keyfile=key_path)

    logger.info(f"Запуск WSS сервера на {host}:{port}")
    async with websockets.serve(ipc_handler, host, port, ssl=ssl_context, ping_interval=None, ping_timeout=None):
        await asyncio.Future()


if __name__ == "__main__":
    os.chdir(get_script_dir())

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--test", action="store_true")

    args = parser.parse_args()
    try:
        asyncio.run(main(args.host, args.port, args.test))
    except KeyboardInterrupt:
        logger.info("Сервер остановлен")
