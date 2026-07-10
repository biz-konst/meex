# ---- Функции кодирования/декодирования в зависимости от режима ----
import json

from . import binary_protocol


def encode_message(msg, use_binary: bool, protocol, logger):
    """
    Преобразует словарь сообщения (с ключами v, c, d) в формат для отправки.
    Если use_binary == True, возвращает bytes (упакованный бинарный протокол),
    иначе возвращает JSON-строку.
    """
    version = msg.get("v")
    if version != protocol.version:
        logger.debug(f"Указана неверная версия протокола: {version}")
        return None

    if not use_binary:
        return json.dumps(msg)

    # Для бинарного режима: извлекаем cmd и dto
    cmd = msg.get("c")
    dto = msg.get("d") or {}

    # Приводим dto к формату, понятному бинарному протоколу (поля называются так же)
    # pack() ожидает объект, который можно использовать как dict или с атрибутами
    packed = binary_protocol.pack(protocol, cmd, dto)
    return packed


def decode_message(data, use_binary: bool, protocol, logger):
    """
    Преобразует полученные данные в словарь {v, c, d}.
    Если use_binary == True, data должны быть bytes (бинарный протокол),
    иначе data — JSON-строка.
    Возвращает словарь или None при ошибке.
    """
    if use_binary:
        try:
            version, cmd, fields = binary_protocol.unpack(protocol, data)
            if version != protocol.version:
                logger.debug(f"Указана неверная версия протокола: {version}")
                return None

            return {"v": version, "c": cmd, "d": fields}
        except Exception as e:
            logger.debug(f"Ошибка распаковки бинарного сообщения: {e}")
            return None
    else:
        try:
            result = json.loads(data)
            if result.get('v') != protocol.version:
                logger.debug(f"Указана неверная версия протокола: {result.get('v')}")
                return None

            return result
        except json.JSONDecodeError:
            logger.debug(f"Ошибка парсинга JSON: {data}")
            return None
