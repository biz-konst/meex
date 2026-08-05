import math
from typing import Any

from server.python.protocol.binary_protocol import (
    ProtocolField, FIELD_TYPE_INT, FIELD_TYPE_FLOAT, FIELD_TYPE_BYTES,
    FIELD_TYPE_STR, FIELD_TYPE_UNDEFINED, FIELD_TYPE_STRUCT, ProtocolValue,
    ProtocolCommand, FIELD_TYPE_BOOL, FIELD_TYPE_UINT, FIELD_TYPE_ARRAY,
    Protocol, pack, unpack, CMD_INFO, unpack_info, PROTOCOL_VERSION, FIELD_TYPE_UNDEFINED_STRUCT,
    create_default_protocol
)

def create_test_protocol():
    """Создаёт протокол с командами, покрывающими все типы полей, включая:
       - команду 0 (описание протокола),
       - команду 70 (без аргументов),
       - команду 80 (один аргумент UNDEFINED).
    """
    # ---- Команда 0: описание протокола ----
    commands_fields = [
        ProtocolField(code=0, name='commands', kind=FIELD_TYPE_UNDEFINED)
    ]
    cmd_info = ProtocolCommand(cmd_code=CMD_INFO, fields=commands_fields)

    # ---- Остальные команды (как были) ----
    nested_fields = [
        ProtocolField(code=1, name='x', kind=FIELD_TYPE_INT),
        ProtocolField(code=2, name='y', kind=FIELD_TYPE_FLOAT),
        ProtocolField(code=3, name='z', kind=FIELD_TYPE_STR),
        ProtocolField(code=4, name='data', kind=FIELD_TYPE_BYTES),
        ProtocolField(code=5, name='unknown', kind=FIELD_TYPE_UNDEFINED),
    ]

    cmd_all_fields = ProtocolCommand(
        cmd_code=10,
        fields=[
            ProtocolField(code=1, name='flag', kind=FIELD_TYPE_BOOL),
            ProtocolField(code=2, name='int_val', kind=FIELD_TYPE_INT),
            ProtocolField(code=3, name='uint_val', kind=FIELD_TYPE_UINT),
            ProtocolField(code=4, name='float_val', kind=FIELD_TYPE_FLOAT),
            ProtocolField(code=5, name='bytes_val', kind=FIELD_TYPE_BYTES),
            ProtocolField(code=6, name='str_val', kind=FIELD_TYPE_STR),
            ProtocolField(code=7, name='array_fixed', kind=FIELD_TYPE_ARRAY,
                          elements=ProtocolValue(kind=FIELD_TYPE_UINT, size=8)),
            ProtocolField(code=8, name='array_undefined', kind=FIELD_TYPE_ARRAY,
                          elements=ProtocolValue(kind=FIELD_TYPE_UNDEFINED)),
            ProtocolField(code=9, name='struct_with_undefined', kind=FIELD_TYPE_STRUCT,
                          elements=nested_fields),
        ]
    )

    mixed_array_elements = [
        ProtocolValue(kind=FIELD_TYPE_BOOL),
        ProtocolValue(kind=FIELD_TYPE_INT),
        ProtocolValue(kind=FIELD_TYPE_FLOAT),
        ProtocolValue(kind=FIELD_TYPE_STR),
        ProtocolValue(kind=FIELD_TYPE_UNDEFINED),
    ]
    cmd_mixed_array = ProtocolCommand(
        cmd_code=20,
        fields=[
            ProtocolField(code=1, name='mixed', kind=FIELD_TYPE_ARRAY,
                          elements=mixed_array_elements),
        ]
    )

    cmd_bytes_compression = ProtocolCommand(
        cmd_code=30,
        fields=[
            ProtocolField(code=1, name='large_bytes', kind=FIELD_TYPE_BYTES),
        ]
    )

    cmd_empty = ProtocolCommand(
        cmd_code=40,
        fields=[
            ProtocolField(code=1, name='none_field', kind=FIELD_TYPE_STR),
            ProtocolField(code=2, name='zero_int', kind=FIELD_TYPE_INT),
            ProtocolField(code=3, name='empty_str', kind=FIELD_TYPE_STR),
            ProtocolField(code=4, name='empty_bytes', kind=FIELD_TYPE_BYTES),
        ]
    )

    cmd_bool_array = ProtocolCommand(
        cmd_code=50,
        fields=[
            ProtocolField(code=1, name='bools', kind=FIELD_TYPE_ARRAY,
                          elements=ProtocolValue(kind=FIELD_TYPE_BOOL)),
        ]
    )

    cmd_fixed_array = ProtocolCommand(
        cmd_code=60,
        fields=[
            ProtocolField(code=1, name='fixed_elems', kind=FIELD_TYPE_ARRAY,
                          elements=ProtocolValue(kind=FIELD_TYPE_UINT, size=2)),
        ]
    )

    # ---- НОВАЯ КОМАНДА 70: без аргументов ----
    cmd_no_args = ProtocolCommand(
        cmd_code=70,
        fields=[]
    )

    # ---- НОВАЯ КОМАНДА 80: один аргумент типа UNDEFINED ----
    cmd_single_undefined = ProtocolCommand(
        cmd_code=80,
        fields=[
            ProtocolField(code=0, name='single', kind=FIELD_TYPE_UNDEFINED)
        ]
    )

    return Protocol(version=2, commands=[
        cmd_info,  # команда 0
        cmd_all_fields,  # 10
        cmd_mixed_array,  # 20
        cmd_bytes_compression,  # 30
        cmd_empty,  # 40
        cmd_bool_array,  # 50
        cmd_fixed_array,  # 60
        cmd_no_args,  # 70
        cmd_single_undefined,  # 80
    ])


def is_empty_value(val):
    """Проверяет, является ли значение "пустым" (не упаковывается в протоколе)."""
    return val is None or val == 0 or val == '' or val == b'' or val == [] or val == ()


def compare_values(a, b):
    """
    Сравнивает два значения, допуская:
      - объекты и словари (сравниваются по атрибутам/ключам),
      - списки объектов и списки словарей,
      - погрешность для float,
      - пустые значения (None, 0, '', [], ()) могут отсутствовать в распакованном словаре.
    """
    # Если b отсутствует, то a должно быть пустым
    if b is None:
        return is_empty_value(a)

    # Если a - объект (не словарь), а b - словарь или наоборот
    if hasattr(a, '__dict__') and isinstance(b, dict):
        # Преобразуем объект в словарь (исключая служебные атрибуты)
        a_dict = {k: v for k, v in a.__dict__.items() if not k.startswith('_')}
        return compare_values(a_dict, b)

    if isinstance(a, dict) and hasattr(b, '__dict__'):
        # Симметрично: b - объект, a - словарь
        b_dict = {k: v for k, v in b.__dict__.items() if not k.startswith('_')}
        return compare_values(a, b_dict)

    # Если типы разные, но оба могут быть преобразованы в числа/строки — пробуем привести
    if type(a) != type(b):
        # Если один из них - число, а другой - строка, пробуем преобразовать
        if isinstance(a, (int, float)) and isinstance(b, (int, float, str)):
            try:
                return abs(float(a) - float(b)) < 1e-9 if isinstance(a, float) or isinstance(b, float) else int(
                    a) == int(b)
            except:
                pass
        # Если один - список, другой - кортеж и т.п. - пробуем сравнить как последовательности
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            if len(a) != len(b):
                return False
            for x, y in zip(a, b):
                if not compare_values(x, y):
                    return False
            return True
        # Если один - None, а другой - пустая структура - считаем эквивалентными
        if a is None:
            return is_empty_value(b)
        if b is None:
            return is_empty_value(a)
        # Иначе считаем несовпадающими
        return False

    # Дальше идёт стандартное сравнение для одинаковых типов
    if isinstance(a, float):
        if math.isinf(a) or math.isinf(b) or math.isnan(a) or math.isnan(b):
            return (math.isnan(a) and math.isnan(b)) or (a == b)
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)

    elif isinstance(a, dict):
        for k, v in a.items():
            if k not in b:
                if not is_empty_value(v):
                    return False
            else:
                if not compare_values(v, b[k]):
                    return False
        for k in b:
            if k not in a:
                # Если в b есть ключ, которого нет в a, считаем это допустимым только если значение в b пустое
                if not is_empty_value(b[k]):
                    return False
        return True

    elif isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return False
        for x, y in zip(a, b):
            if not compare_values(x, y):
                return False
        return True

    else:
        return a == b


def run_test_case(name: str, protocol: Protocol, cmd: int, value: Any):
    """Упаковывает и распаковывает одно значение, сравнивает результат."""
    print(f"\n=== {name} ===")
    try:
        packed = pack(protocol, cmd, value)
        print(f"Упаковано {len(packed)} байт: {packed[:50].hex()}{'...' if len(packed) > 50 else ''}")
        version, cmd_out, unpacked = unpack(protocol, packed)
        print(f"Распаковано: версия={version}, команда={cmd_out}")

        if cmd_out == CMD_INFO:
            unpacked = unpack_info(unpacked)

        ok = compare_values(value, unpacked)
        if ok:
            print("✅ Совпадает")
        else:
            print("❌ НЕ СОВПАДАЕТ")
            print(f"Исходное: {value}")
            print(f"Распакованное: {unpacked}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        raise e


def main():
    protocol = create_test_protocol()

    # ---- Тест 0: команда описания протокола ----
    # desc = build_protocol_description(protocol)
    run_test_case("Команда 0 – описание протокола", protocol, CMD_INFO, {'commands': list(protocol.commands.values())})

    # ---- Тест 1: все типы с UNDEFINED ----
    test_all = {
        'flag': True,
        'int_val': -123456,
        'uint_val': 987654321,
        'float_val': 3.141592653589793,
        'bytes_val': b'Hello, \x00\x01\x02',
        'str_val': 'Привет мир!',
        'array_fixed': [100, 200, 300, 400, 500],
        'array_undefined': [42, 3.14, 'text', b'bytes', None, True],
        'struct_with_undefined': {
            'x': 42,
            'y': 3.14,
            'z': 'nested',
            'data': b'\xde\xad\xbe\xef',
            'unknown': {'a': 1, 'b': 'foo'}
        }
    }
    run_test_case("Все типы с UNDEFINED", protocol, 10, test_all)

    # ---- Тест 2: смешанный массив с UNDEFINED ----
    mixed_data = [
        True,
        -42,
        3.14,
        'hello',
        None,
        False,
        0,
        0.0,
        'world',
        {'key': 'value'},
        True,
        100,
        2.71,
        'foo',
        [1, 2, 3],
    ]
    run_test_case("Смешанный массив с UNDEFINED", protocol, 20, {'mixed': mixed_data})

    # ---- Тест 3: сжатие больших байтов ----
    large_data = b'X' * 200000
    run_test_case("Сжатие больших байтов", protocol, 30, {'large_bytes': large_data})

    # ---- Тест 4: пустые поля ----
    empty_data = {
        'none_field': None,
        'zero_int': 0,
        'empty_str': '',
        'empty_bytes': b'',
    }
    run_test_case("Пустые поля", protocol, 40, empty_data)

    # ---- Тест 5: чистый булевый массив ----
    bools = [True, False, True, True, False, False, True, False, True]
    run_test_case("Булевый массив", protocol, 50, {'bools': bools})

    # ---- Тест 6: массив с фиксированной длиной элементов ----
    fixed_elems = [10, 20, 30, 65535]
    run_test_case("Массив с фиксированной длиной", protocol, 60, {'fixed_elems': fixed_elems})

    # ---- Тест 7: граничные значения чисел ----
    for v in [0, 127, 128, 32767, 32768, 2147483647, 2147483648, -1, -128, -129, -32768, -32769, -2147483648,
              -2147483649]:
        run_test_case(f"Целое {v}", protocol, 10, {'int_val': v})

    for v in [0, 255, 256, 65535, 65536, 4294967295, 4294967296]:
        run_test_case(f"Беззнаковое {v}", protocol, 10, {'uint_val': v})

    for v in [0.0, 1.0, -1.0, 123.456, 1e-30, 1e30, float('inf'), float('-inf'), float('nan')]:
        run_test_case(f"Float {v}", protocol, 10, {'float_val': v})

    # ---- Тест 8: пустые массивы ----
    run_test_case("Пустой массив (array_fixed)", protocol, 10, {'array_fixed': []})
    run_test_case("Пустой массив (array_undefined)", protocol, 10, {'array_undefined': []})
    run_test_case("Пустой булевый массив", protocol, 50, {'bools': []})
    run_test_case("Пустой массив с фиксированной длиной", protocol, 60, {'fixed_elems': []})

    # ---- Тест 9: вложенная структура с UNDEFINED ----
    nested_complex = {
        'x': -999,
        'y': 2.71828,
        'z': 'deep',
        'data': b'\x01\x02\x03',
        'unknown': ['list', 'inside', 123]
    }
    run_test_case("Вложенная структура с UNDEFINED", protocol, 10, {'struct_with_undefined': nested_complex})

    # ---- НОВЫЙ ТЕСТ 10: команда без аргументов ----
    run_test_case("Команда без аргументов (None)", protocol, 70, None)

    # ---- НОВЫЙ ТЕСТ 11: команда с одним полем UNDEFINED ----
    test_values = [
        12345,
        -9876,
        3.14159,
        "Привет, мир!",
        b"\x01\x02\x03",
        True,
        False,
        None,
        [1, 2, 3],
        {"key": "value"},
        {"a": 1, "b": 2.0, "c": "str", "d": [True, False]},
    ]
    for val in test_values:
        run_test_case(f"Один аргумент UNDEFINED: {val!r}", protocol, 80, {'single': val})

    # Пустые значения для UNDEFINED
    run_test_case("Один аргумент UNDEFINED: None", protocol, 80, {'single': None})
    run_test_case("Один аргумент UNDEFINED: 0", protocol, 80, {'single': 0})
    run_test_case("Один аргумент UNDEFINED: ''", protocol, 80, {'single': ''})
    run_test_case("Один аргумент UNDEFINED: []", protocol, 80, {'single': []})

    print("\n=== ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ ===")


if __name__ == "__main__":
    main()
