#!/usr/bin/env python3
"""
Модуль для тестирования бинарного протокола.
Может работать локально (без сети) или с сервером.
"""

import asyncio
import logging
import ssl
import sys

import websockets

from .binary_protocol import (
    PROTOCOL_VERSION, create_default_protocol, ProtocolField, FIELD_TYPE_BOOL, FIELD_TYPE_INT, FIELD_TYPE_UINT,
    FIELD_TYPE_FLOAT, FIELD_TYPE_BYTES, FIELD_TYPE_STR, FIELD_TYPE_UNDEFINED, ProtocolCommand, FIELD_TYPE_ARRAY,
    ProtocolValue, Protocol, FIELD_TYPE_STRUCT, unpack_info, CMD_INFO, serialize_protocol
)
from .encode_decode import encode_message, decode_message

logger = logging.getLogger("TestProtocol")

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


def create_test_protocol():
    """
    Создаёт протокол с расширенным набором команд для тестирования.
    Включает все стандартные команды (INFO, PING, PONG) и тестовые команды с кодами 51-56.
    """
    base = create_default_protocol()
    commands = list(base.commands.values())

    # ---------- Команда 51: все простые типы + целые разных размеров + float + пустые ----------
    cmd51_fields = [
        ProtocolField(code=0, name='field_bool', kind=FIELD_TYPE_BOOL),
        # Целые знаковые разных размеров
        ProtocolField(code=1, name='int8', kind=FIELD_TYPE_INT, size=1),
        ProtocolField(code=2, name='int16', kind=FIELD_TYPE_INT, size=2),
        ProtocolField(code=3, name='int32', kind=FIELD_TYPE_INT, size=4),
        ProtocolField(code=4, name='int64', kind=FIELD_TYPE_INT, size=8),
        # Целые беззнаковые
        ProtocolField(code=5, name='uint8', kind=FIELD_TYPE_UINT, size=1),
        ProtocolField(code=6, name='uint16', kind=FIELD_TYPE_UINT, size=2),
        ProtocolField(code=7, name='uint32', kind=FIELD_TYPE_UINT, size=4),
        ProtocolField(code=8, name='uint64', kind=FIELD_TYPE_UINT, size=8),
        # Float
        ProtocolField(code=9, name='float32', kind=FIELD_TYPE_FLOAT, size=4),
        ProtocolField(code=10, name='float64', kind=FIELD_TYPE_FLOAT, size=8),
        # Обычные поля
        ProtocolField(code=11, name='field_bytes', kind=FIELD_TYPE_BYTES),
        ProtocolField(code=12, name='field_str', kind=FIELD_TYPE_STR),
        ProtocolField(code=13, name='field_undefined', kind=FIELD_TYPE_UNDEFINED),
        # Пустые значения (должны пропускаться при сериализации)
        ProtocolField(code=14, name='empty_str', kind=FIELD_TYPE_STR),
        ProtocolField(code=15, name='empty_bytes', kind=FIELD_TYPE_BYTES),
        ProtocolField(code=16, name='empty_array', kind=FIELD_TYPE_ARRAY,
                      elements=ProtocolValue(kind=FIELD_TYPE_INT, size=4)),
        ProtocolField(code=17, name='empty_struct', kind=FIELD_TYPE_STRUCT),  # структура без полей
    ]
    commands.append(ProtocolCommand(cmd_code=51, fields=cmd51_fields))

    # ---------- Команда 52: массивы (фикс/нефикс, булевы, таблицы, undefined) ----------
    cmd52_fields = [
        ProtocolField(code=0, name='array_fixed', kind=FIELD_TYPE_ARRAY, size=5,
                      elements=ProtocolValue(kind=FIELD_TYPE_INT, size=4)),  # ровно 5 int'ов
        ProtocolField(code=1, name='array_variable', kind=FIELD_TYPE_ARRAY,
                      elements=ProtocolValue(kind=FIELD_TYPE_STR)),  # переменная длина строк
        ProtocolField(code=2, name='array_bool_only', kind=FIELD_TYPE_ARRAY,
                      elements=ProtocolValue(kind=FIELD_TYPE_BOOL)),  # только булевы
        ProtocolField(code=3, name='array_mixed', kind=FIELD_TYPE_ARRAY,
                      elements=[ProtocolValue(kind=FIELD_TYPE_INT, size=2),  # таблица: int16 + bool
                                ProtocolValue(kind=FIELD_TYPE_BOOL)]),
        ProtocolField(code=4, name='array_with_undefined', kind=FIELD_TYPE_ARRAY,
                      elements=ProtocolValue(kind=FIELD_TYPE_UNDEFINED)),  # элементы с автоматическим типом
        ProtocolField(code=5, name='array_bool', kind=FIELD_TYPE_ARRAY,
                      elements=[ProtocolValue(kind=FIELD_TYPE_INT, size=2),  # таблица: int16 + bool + bool
                                ProtocolValue(kind=FIELD_TYPE_BOOL),
                                ProtocolValue(kind=FIELD_TYPE_BOOL)]),
    ]
    commands.append(ProtocolCommand(cmd_code=52, fields=cmd52_fields))

    # ---------- Команда 53: структура со 100 полями ----------
    cmd53_fields = []
    for i in range(100):
        kind_choice = i % 6
        if kind_choice == 0:
            kind = FIELD_TYPE_BOOL
        elif kind_choice == 1:
            kind = FIELD_TYPE_INT
        elif kind_choice == 2:
            kind = FIELD_TYPE_UINT
        elif kind_choice == 3:
            kind = FIELD_TYPE_FLOAT
        elif kind_choice == 4:
            kind = FIELD_TYPE_BYTES
        else:
            kind = FIELD_TYPE_STR
        # Для некоторых полей зададим фиксированный размер (граничные условия)
        size = 0
        if kind in (FIELD_TYPE_INT, FIELD_TYPE_UINT) and i % 3 == 0:
            size = 8  # 8 байт (int64/uint64)
        elif kind == FIELD_TYPE_FLOAT and i % 2 == 0:
            size = 8  # double
        cmd53_fields.append(
            ProtocolField(code=i, name=f'field_{i}', kind=kind, size=size)
        )
    commands.append(ProtocolCommand(cmd_code=53, fields=cmd53_fields))

    # ---------- Команда 54: undefined структура ----------
    cmd54_fields = [
        ProtocolField(code=0, name='undefined_struct', kind=FIELD_TYPE_UNDEFINED)
    ]
    commands.append(ProtocolCommand(cmd_code=54, fields=cmd54_fields))

    # ---------- Команда 55: большие строки и байты (проверка сжатия) ----------
    cmd55_fields = [
        ProtocolField(code=0, name='large_str', kind=FIELD_TYPE_STR),
        ProtocolField(code=1, name='large_bytes', kind=FIELD_TYPE_BYTES),
    ]
    commands.append(ProtocolCommand(cmd_code=55, fields=cmd55_fields))

    # ---------- Команда 56: вложенные структуры (структура → структура → массив → структура) ----------
    # Определяем внутреннюю структуру для элементов массива
    inner_struct_fields = [
        ProtocolField(code=0, name='a', kind=FIELD_TYPE_INT, size=4),
        ProtocolField(code=1, name='b', kind=FIELD_TYPE_STR),
    ]
    # Определяем массив этих структур
    array_of_structs = ProtocolField(
        code=0,
        name='array_of_structs',
        kind=FIELD_TYPE_ARRAY,
        elements=ProtocolValue(kind=FIELD_TYPE_STRUCT, elements=inner_struct_fields)
    )
    # Определяем структуру, содержащую этот массив
    middle_struct_fields = [
        array_of_structs,
        ProtocolField(code=1, name='simple_field', kind=FIELD_TYPE_INT, size=4),
    ]
    # Определяем внешнюю структуру, содержащую среднюю
    outer_struct_fields = [
        ProtocolField(code=0, name='middle', kind=FIELD_TYPE_STRUCT, elements=middle_struct_fields),
    ]
    # Команда 56 имеет одно поле – внешнюю структуру
    cmd56_fields = [
        ProtocolField(code=0, name='nested', kind=FIELD_TYPE_STRUCT, elements=outer_struct_fields),
    ]
    commands.append(ProtocolCommand(cmd_code=56, fields=cmd56_fields))

    return Protocol(version=PROTOCOL_VERSION, commands=commands)


# ===================================================================
# Вспомогательная функция: является ли значение пустым (не сериализуется)
# ===================================================================
def is_empty_value(v):
    """Возвращает True, если значение считается пустым и не будет сериализовано."""
    if v is None:
        return True
    if isinstance(v, (str, bytes, bytearray)) and len(v) == 0:
        return True
    if isinstance(v, (list, tuple, set)) and len(v) == 0:
        return True
    if isinstance(v, dict) and len(v) == 0:
        return True
    return False


# ===================================================================
# Функция сравнения с допуском для float и игнорированием пустых полей
# ===================================================================
def compare_values(orig, recv, path="root", tol=1e-6):
    """
    Рекурсивно сравнивает две структуры данных с учётом погрешности float.
    Поля, которые в оригинале имеют пустое значение, могут отсутствовать в recv.
    """
    if isinstance(orig, float) and isinstance(recv, float):
        if abs(orig - recv) > tol:
            raise AssertionError(f"Float mismatch at {path}: {orig} vs {recv} (diff {abs(orig - recv)})")
    elif isinstance(orig, list):
        if not isinstance(recv, list):
            raise AssertionError(f"Type mismatch at {path}: list vs {type(recv)}")
        if len(orig) != len(recv):
            raise AssertionError(f"Length mismatch at {path}: {len(orig)} vs {len(recv)}")
        for i, (o, r) in enumerate(zip(orig, recv)):
            compare_values(o, r, f"{path}[{i}]", tol)
    elif isinstance(orig, dict):
        if not isinstance(recv, dict):
            raise AssertionError(f"Type mismatch at {path}: dict vs {type(recv)}")
        # Проверяем, что все ключи из orig присутствуют в recv, если значение не пустое
        for k, v_orig in orig.items():
            if k not in recv:
                if is_empty_value(v_orig):
                    # Если значение пустое, оно может отсутствовать в recv – пропускаем
                    continue
                raise AssertionError(f"Key '{k}' missing at {path}, expected non-empty value {v_orig}")
            compare_values(v_orig, recv[k], f"{path}.{k}", tol)
        # Проверяем, что в recv нет лишних ключей
        for k in recv:
            if k not in orig:
                raise AssertionError(f"Unexpected key '{k}' at {path} (value: {recv[k]})")
    elif hasattr(orig, "__dict__"):
        if type(orig) != type(recv):
            raise AssertionError(f"Type mismatch at {path}: {type(orig)} vs {type(recv)}")
        # Проверяем, что все ключи из orig присутствуют в recv, если значение не пустое
        orig_dict = {k: v for k, v in getattr(orig, "__dict__").items() if not k.startswith("_")}
        recv_dict = {k: v for k, v in getattr(recv, "__dict__").items() if not k.startswith("_")}
        compare_values(orig_dict, recv_dict, path, tol)
    elif isinstance(orig, bytes) and isinstance(recv, bytes):
        if orig != recv:
            raise AssertionError(f"Bytes mismatch at {path}: {orig.hex()[:128]} vs {recv.hex()[:128]}")
    elif isinstance(orig, str) and isinstance(recv, str):
        if orig != recv:
            raise AssertionError(f"String mismatch at {path}: '{orig[:128]}' vs '{recv[:128]}'")
    elif isinstance(orig, bool) and isinstance(recv, bool):
        if orig != recv:
            raise AssertionError(f"Bool mismatch at {path}: {orig} vs {recv}")
    elif isinstance(orig, int) and isinstance(recv, int):
        if orig != recv:
            raise AssertionError(f"Int mismatch at {path}: {orig} vs {recv}")
    else:
        if orig != recv:
            raise AssertionError(f"Value mismatch at {path}: {orig} ({type(orig)}) vs {recv} ({type(recv)})")


# ===================================================================
# Генерация тестовых данных
# ===================================================================
def generate_test_cases():
    """Возвращает список (cmd_code, data_dict) для тестирования."""
    test_cases = []

    # Команда 51: все простые типы + целые разных размеров + float + пустые
    data51 = {
        "field_bool": True,
        "int8": 127,
        "int16": -32768,
        "int32": 2147483647,
        "int64": -9223372036854775808,
        "uint8": 255,
        "uint16": 65535,
        "uint32": 4294967295,
        "uint64": 18446744073709551615,
        "float32": 1.234567e-5,  # будет округлено до 4 байт
        "float64": 3.141592653589793,
        "field_bytes": b"hello\x00world",
        "field_str": "привет мир!",
        "field_undefined": [1, 2, 3],  # автоматически определится как массив
        # Пустые значения (должны пропускаться)
        "empty_str": "",
        "empty_bytes": b"",
        "empty_array": [],
        "empty_struct": {},
    }
    test_cases.append((51, data51))

    # Команда 52: массивы (без изменений)
    data52 = {
        "array_fixed": [10, 20, 30, 40, 50],
        "array_variable": ["один", "два", "три"],
        "array_bool_only": [True, False, True, False, True],
        "array_mixed": [
            100, True,
            200, False,
            300, True
        ],
        "array_with_undefined": [42, "строка", 3.14, [1, 2]],
        "array_bool": [
            1000, True, False,
            2000, False, True,
            3000, True, True
        ],
    }
    test_cases.append((52, data52))

    # Команда 53: структура со 100 полями (без изменений)
    data53 = {}
    for i in range(100):
        if i % 6 == 0:
            data53[f"field_{i}"] = True if i % 2 == 0 else False
        elif i % 6 == 1:
            data53[f"field_{i}"] = 123456789 + i
        elif i % 6 == 2:
            data53[f"field_{i}"] = 987654321 + i
        elif i % 6 == 3:
            data53[f"field_{i}"] = 3.14159 + i * 0.001
        elif i % 6 == 4:
            data53[f"field_{i}"] = bytes([i % 256 for _ in range(10)])
        else:  # 5
            data53[f"field_{i}"] = f"строка_{i}"
    test_cases.append((53, data53))

    # Команда 54: undefined структура (без изменений)
    data54 = {
        "undefined_struct": {
            "dynamic_field1": 100500,
            "dynamic_field2": "динамическая строка",
            "dynamic_field3": [1.1, 2.2, 3.3]
        }
    }
    test_cases.append((54, data54))

    # Команда 55: большие строки и байты (без изменений)
    data55 = {
        "large_str": "A" * 100000,  # 100 КБ
        "large_bytes": bytes([0xFF, 0xAA] * 50000)  # 100 КБ
    }
    test_cases.append((55, data55))

    # Команда 56: вложенные структуры
    data56 = {
        "nested": {
            "middle": {
                "array_of_structs": [
                    {"a": 100, "b": "first"},
                    {"a": 200, "b": "second"},
                    {"a": 300, "b": "third"}
                ],
                "simple_field": 999
            }
        }
    }
    test_cases.append((56, data56))

    # --- Команда INFO (код 0) с сериализованным протоколом ---
    # proto = create_test_protocol()
    # info_data = serialize_protocol(proto)
    # test_cases.append((CMD_INFO, info_data))  # CMD_INFO = 0
    test_cases.append((CMD_INFO, None))  # CMD_INFO = 0

    return test_cases


# ===================================================================
# Локальное тестирование (без сети)
# ===================================================================
def run_local_test(use_binary=False):
    """
    Выполняет кодирование/декодирование тестовых команд локально,
    без отправки по сети. Сравнивает оригинал и декодированный результат.
    Возвращает True при успехе, иначе False.
    """
    proto = create_test_protocol()
    logger.info("Запуск локального тестирования (без сервера)")
    for cmd_code, expected_data in generate_test_cases():
        message = {"v": PROTOCOL_VERSION, "c": cmd_code, "d": expected_data}
        try:
            payload = encode_message(message, use_binary, proto, logger)
            # Декодируем
            decoded = decode_message(payload, use_binary, proto, logger)
            if decoded is None:
                logger.error(f"Команда {cmd_code}: decode вернул None")
                return False
            if decoded.get("v") != PROTOCOL_VERSION:
                logger.error(f"Команда {cmd_code}: неверная версия {decoded.get('v')}")
                return False
            if decoded.get("c") != cmd_code:
                logger.error(f"Команда {cmd_code}: не совпадает команда {decoded.get('c')}")
                return False
            received_data = decoded.get("d")

            # Особый случай для INFO: распаковываем протокол через unpack_info
            if cmd_code == CMD_INFO:
                if received_data is None:
                    logger.error(f"Команда INFO: данные отсутствуют")
                    return False
                # Восстанавливаем протокол из полученных данных
                recovered_commands = unpack_info(received_data)
                expected_data = serialize_protocol(proto)
                # Сравниваем с исходным протоколом
                try:
                    compare_values(expected_data, recovered_commands)
                    logger.info(f"✅ Команда {cmd_code} (INFO): протокол восстановлен корректно")
                except Exception as e:
                    logger.error(f"❌ Команда {cmd_code} (INFO): ошибка сравнения: {e}")
                    return False
            else:
                # Обычное сравнение данных
                if received_data is None and expected_data is not None:
                    logger.error(f"Команда {cmd_code}: в ответе отсутствуют данные")
                    return False
                compare_values(expected_data, received_data)
                logger.info(f"✅ Команда {cmd_code}: локальный тест пройден")
        except Exception as e:
            logger.error(f"❌ Команда {cmd_code}: ошибка: {e}", exc_info=True)
            return False
    logger.info("✅ Все локальные тесты пройдены")
    return True


# ===================================================================
# Тестирование с сервером (по сети)
# ===================================================================
async def run_server_test(uri, use_binary=False):
    """
    Подключается к серверу, отправляет тестовые команды и сравнивает эхо-ответы.
    Возвращает True при успехе, иначе False.
    """
    proto = create_test_protocol()
    logger.info(f"Запуск тестирования с сервером {uri}")
    try:
        async with websockets.connect(uri, ssl=ssl_context) as ws:
            for cmd_code, expected_data in generate_test_cases():
                message = {"v": PROTOCOL_VERSION, "c": cmd_code, "d": expected_data}
                payload = encode_message(message, use_binary, proto, logger)
                logger.info(f"Отправка команды {cmd_code}, размер данных {len(payload)} байт")
                await ws.send(payload)

                # Получаем ответ (эхо)
                resp_raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                resp = decode_message(resp_raw, use_binary, proto, logger)
                if resp is None:
                    logger.error(f"Команда {cmd_code}: не удалось декодировать ответ")
                    return False

                if resp.get("v") != PROTOCOL_VERSION:
                    logger.error(f"Команда {cmd_code}: неверная версия {resp.get('v')}")
                    return False

                if resp.get("c") != cmd_code:
                    logger.error(f"Команда {cmd_code}: получен не эхо, а команда {resp.get('c')}")
                    return False

                received_data = resp.get("d")

                # Особый случай для INFO
                if cmd_code == CMD_INFO:
                    if received_data is None:
                        logger.error(f"Команда INFO: данные отсутствуют")
                        return False
                    # Восстанавливаем протокол из полученных данных
                    recovered_commands = unpack_info(received_data)
                    expected_data = serialize_protocol(proto)
                    # Сравниваем с исходным протоколом
                    try:
                        compare_values(expected_data, recovered_commands)
                        logger.info(f"✅ Команда {cmd_code} (INFO): протокол восстановлен корректно")
                    except Exception as e:
                        logger.error(f"❌ Команда {cmd_code} (INFO): ошибка сравнения: {e}")
                        return False
                else:
                    # Обычное сравнение данных
                    if received_data is None and expected_data is not None:
                        logger.error(f"Команда {cmd_code}: в ответе отсутствуют данные")
                        return False
                    compare_values(expected_data, received_data)
                    logger.info(f"✅ Команда {cmd_code}: данные совпадают")

            logger.info("✅ Все тестовые команды с сервером успешно пройдены")
            return True
    except Exception as e:
        logger.error(f"❌ Ошибка при тестировании с сервером: {e}", exc_info=True)
        return False


def setup_logging(level=logging.INFO):
    root = logger
    if root.handlers:
        return  # уже настроено
    root.setLevel(level)
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(level)
    root.addHandler(sh)
    eh = logging.StreamHandler(sys.stderr)
    eh.setLevel(logging.ERROR)
    root.addHandler(eh)


if __name__ == "__main__":
    setup_logging()
    run_local_test(True)
