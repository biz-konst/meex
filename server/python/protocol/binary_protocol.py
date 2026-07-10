import math
import struct
from typing import List, Tuple, Dict, Optional, Any

PROTOCOL_VERSION = 1

CMD_PING = 1
CMD_PONG = 2

# ===================================================================
# Константы типов полей
# ===================================================================
FIELD_TYPE_UNDEFINED = -1
FIELD_TYPE_BOOL = 1
FIELD_TYPE_INT = 2
FIELD_TYPE_UINT = 3
FIELD_TYPE_FLOAT = 4
FIELD_TYPE_STR = 5
FIELD_TYPE_ARRAY = 6
FIELD_TYPE_ARRAY_BYTES = 7
FIELD_TYPE_STRUCT = 8

DEFAULT_VALUES = {
    FIELD_TYPE_UNDEFINED: None,
    FIELD_TYPE_BOOL: False,
    FIELD_TYPE_INT: 0,
    FIELD_TYPE_UINT: 0,
    FIELD_TYPE_FLOAT: 0.0,
    FIELD_TYPE_STR: '',
    FIELD_TYPE_ARRAY: [],
    FIELD_TYPE_ARRAY_BYTES: bytes(),
    FIELD_TYPE_STRUCT: {},
}

SIZE_BY_LEN_FLAG = (1, 2, 4, 8)
LEN_FLAG_BY_SIZE = {1: 0, 2: 1, 4: 2, 8: 3}
SIGNED_CAST = ('>b', '>h', '>i', '>q')
UNSIGNED_CAST = ('>B', '>H', '>I', '>Q')
FLOAT_CAST = ('>f', '>f', '>d', '>d')


# ===================================================================
# Классы описания протокола
# ===================================================================
class ProtocolValue:
    def __init__(self, kind: int, size: int = 0, **kwargs):
        self.kind = kind
        self.size = size
        self.default = kwargs.get('default', DEFAULT_VALUES[kind])
        self.elements = kwargs.get('elements')
        self.encoding = kwargs.get('encoding')


class ProtocolField(ProtocolValue):
    def __init__(self, code: int, name: str, kind: int, size: int = 0, **kwargs):
        self.code = code
        self.name = name
        super().__init__(kind, size, **kwargs)


class ProtocolCommand:
    def __init__(self, cmd_code: int, fields: List[ProtocolField]):
        self.cmd_code = cmd_code
        self.fields = {fld.code: fld for fld in fields}
        self.fields_list: List[ProtocolField] = fields


class Protocol:
    def __init__(self, version: int, commands: List[ProtocolCommand]):
        self.version = version
        self.commands = {cmd.cmd_code: cmd for cmd in commands}


# ===================================================================
# Определение типа значения по его Python-типу
# ===================================================================
def obtain_kind(value):
    if isinstance(value, bool):
        return FIELD_TYPE_BOOL
    elif isinstance(value, int):
        return FIELD_TYPE_INT
    elif isinstance(value, float):
        return FIELD_TYPE_FLOAT
    elif isinstance(value, str):
        return FIELD_TYPE_STR
    elif isinstance(value, (bytes, bytearray)):
        return FIELD_TYPE_ARRAY_BYTES
    elif isinstance(value, (list, tuple, set)):
        return FIELD_TYPE_ARRAY
    elif isinstance(value, dict):
        return FIELD_TYPE_STRUCT
    elif hasattr(value, '__dict__'):
        return FIELD_TYPE_STRUCT
    else:
        return FIELD_TYPE_UNDEFINED


# ===================================================================
# Функции определения длины (флага длины) для чисел
# ===================================================================
def len_flag_for_signed(value: int) -> int:
    if -128 <= value <= 127:
        return 0
    elif -32768 <= value <= 32767:
        return 1
    elif -2147483648 <= value <= 2147483647:
        return 2
    else:
        return 3


def len_flag_for_unsigned(value: int) -> int:
    if 0 <= value <= 255:
        return 0
    elif 0 <= value <= 65535:
        return 1
    elif 0 <= value <= 4294967295:
        return 2
    else:
        return 3


def len_flag_for_float(value: float) -> int:
    if not math.isfinite(value):
        return 3
    try:
        f32 = struct.unpack('>f', struct.pack('>f', value))[0]
        if f32 == 0.0:
            return 2
        rel_err = abs((value - f32) / value)
        if rel_err < 1e-6:
            return 2
        else:
            return 3
    except OverflowError:
        return 3


# ===================================================================
# Словари правил упаковки и распаковки по типу поля
# ===================================================================
PACK_RULES_BY_TYPE = {
    FIELD_TYPE_BOOL: lambda v, x, f: pack_boolean(v, x, f),
    FIELD_TYPE_INT: lambda v, x, f: pack_signed(v, x, f),
    FIELD_TYPE_UINT: lambda v, x, f: pack_unsigned(v, x, f),
    FIELD_TYPE_FLOAT: lambda v, x, f: pack_float(v, x, f),
    FIELD_TYPE_STR: lambda v, x, f: pack_string(v, x, f),
    FIELD_TYPE_ARRAY_BYTES: lambda v, x, f: pack_bytes(v, x, f),
    FIELD_TYPE_ARRAY: lambda v, x, f: pack_array(v, x, f),
    FIELD_TYPE_STRUCT: lambda v, x, f: pack_struct(v, f),
}

UNPACK_RULES_BY_TYPE = {
    FIELD_TYPE_BOOL: lambda v, i, l, x, f: unpack_boolean(l, i),
    FIELD_TYPE_INT: lambda v, i, l, x, f: unpack_signed(v, i, l, x),
    FIELD_TYPE_UINT: lambda v, i, l, x, f: unpack_unsigned(v, i, l, x),
    FIELD_TYPE_FLOAT: lambda v, i, l, x, f: unpack_float(v, i, l, x),
    FIELD_TYPE_STR: lambda v, i, l, x, f: unpack_string(v, i, l, x, f),
    FIELD_TYPE_ARRAY_BYTES: lambda v, i, l, x, f: unpack_bytes(v, i, l, x),
    FIELD_TYPE_ARRAY: lambda v, i, l, x, f: unpack_array(v, i, l, x, f),
    FIELD_TYPE_STRUCT: lambda v, i, l, x, f: unpack_struct(v, i, l, f),
}


# ===================================================================
# Функции упаковки (возвращают (bytes, len_flag))
# ===================================================================
def pack_boolean(value: bool, fixed: int = 0, field_def: ProtocolValue = None) -> Tuple[bytes, int]:
    if fixed > 0 or (getattr(field_def, 'default', None) != value):
        return b'', int(value)


def pack_signed(value: int, fixed: int = 0, field_def: ProtocolValue = None) -> Tuple[bytes, int]:
    if fixed > 0:
        len_flag = LEN_FLAG_BY_SIZE[fixed]
    else:
        if getattr(field_def, 'default', None) == value:
            return None
        len_flag = len_flag_for_signed(value)
    return struct.pack(SIGNED_CAST[len_flag], value), len_flag


def pack_unsigned(value: int, fixed: int = 0, field_def: ProtocolValue = None) -> Tuple[bytes, int]:
    if fixed > 0:
        len_flag = LEN_FLAG_BY_SIZE[fixed]
    else:
        if getattr(field_def, 'default', None) == value:
            return None
        len_flag = len_flag_for_unsigned(value)
    return struct.pack(UNSIGNED_CAST[len_flag], value), len_flag


def pack_float(value: float, fixed: int = 0, field_def: ProtocolValue = None) -> Tuple[bytes, int]:
    if fixed > 0:
        len_flag = LEN_FLAG_BY_SIZE[fixed]
    else:
        if getattr(field_def, 'default', None) == value:
            return None
        len_flag = len_flag_for_float(value)
    return struct.pack(FLOAT_CAST[len_flag], value), len_flag


def pack_bytes(value: bytes, fixed: int, field_def: ProtocolValue) -> Tuple[bytes, int]:
    """
    Упаковывает байтовый массив.
    Если fixed > 0, длина должна совпадать, возвращается ДП=3 (маркер фиксированной длины).
    Иначе добавляется префикс длины.
    """
    if fixed == 0 and getattr(field_def, 'default', None) == value:
        return None

    if fixed > 0:
        if len(value) != fixed:
            raise ValueError(f'Array length mismatch: expected {fixed}, got {len(value)}')
        return value, 3
    else:
        size_bytes, len_flag = pack_unsigned(len(value))
        return size_bytes + value, len_flag


def pack_string(value: str, fixed: int, field_def: ProtocolValue) -> Tuple[bytes, int]:
    """
    Упаковывает строку.
    Если fixed > 0, длина должна совпадать, возвращается ДП=3 (маркер фиксированной длины).
    Иначе добавляется префикс длины.
    """
    if fixed == 0 and getattr(field_def, 'default', None) == value:
        return None

    value = value.encode(encoding=getattr(field_def, 'encoding', None) or 'utf-8')
    return pack_bytes(value, fixed, field_def)


def pack_array(items, fixed: int, field_def: ProtocolValue) -> Tuple[bytes, int]:
    """
    Упаковывает массив.
    Элементы упаковываются рекурсивно с их типами.
    Если fixed > 0, количество элементов должно совпадать, возвращается ДП=3.
    Иначе добавляется префикс количества элементов.
    """
    elements = field_def.elements
    item_kind, item_size = elements.kind, elements.size
    code_to_use = 0 if (item_size != 0 and item_kind != FIELD_TYPE_UNDEFINED) else item_kind

    packed = bytearray()
    count = 0
    for item in items:
        part = pack_value(item, item_kind, code_to_use, item_size, elements.elements)
        if part:
            packed.extend(part)
            count += 1

    if fixed > 0:
        if count != fixed:
            raise ValueError(f'Array length mismatch: expected {fixed}, got {count}')
        return packed, 3
    elif count:
        size_bytes, len_flag = pack_unsigned(count)
        return size_bytes + packed, len_flag


def pack_fields(data, fields: List[ProtocolField]) -> Tuple[bytes, int]:
    """
    Упаковывает структуру.
    Поля упаковываются последовательно
    """
    if isinstance(data, dict):
        getter = lambda k: data.get(k)
    else:
        getter = lambda k: getattr(data, k, None)

    packed = bytearray()
    count = 0
    for field in fields:
        val = getter(field.name)
        if val is None:
            continue

        part = pack_value(val, field.kind, field.code, field.size, field)
        if part:
            packed.extend(part)
            count += 1

    if count:
        return packed, count


def pack_struct(data, field_def: ProtocolValue) -> Tuple[bytes, int]:
    """
    Упаковывает структуру.
    Поля упаковываются последовательно, затем добавляется префикс с количеством непустых полей.
    """
    packed, count = pack_fields(data, field_def.elements)

    if not count:
        return None

    size_bytes, len_flag = pack_unsigned(count)
    return size_bytes + packed, len_flag


def pack_value(value, kind: int, code: int, fixed: int = 0, val_def=None) -> Optional[bytes]:
    """
    Упаковывает одно значение.
    Если kind == FIELD_TYPE_UNDEFINED, определяется автоматически.
    Возвращает bytes или None, если значение считается пустым.
    """
    if value is None:
        return None

    result = bytearray()

    if kind == FIELD_TYPE_UNDEFINED:
        kind = obtain_kind(value)
        if code:
            result.append(code)
        code, fixed = kind, 0

    pack_func = PACK_RULES_BY_TYPE.get(kind)
    if pack_func is None:
        raise ValueError(f'Unsupported kind: {kind}')

    packed_result = pack_func(value, fixed, val_def)
    if packed_result is None:
        return None

    packed, len_flag = packed_result

    if not packed and kind != FIELD_TYPE_BOOL:
        return None

    if fixed == 0 or code != 0:
        result.append((len_flag << 6) | code)

    result.extend(packed)
    return bytes(result)


def pack(protocol: Protocol, cmd: int, value) -> bytes:
    """
    Упаковывает сообщение согласно протоколу.
    value может быть dict, объектом с атрибутами или простым значением (если команда имеет одно поле).
    """
    command = protocol.commands.get(cmd)
    if command is None:
        raise ValueError(f'Unknown command: {cmd}')

    header = (protocol.version << 10) | cmd
    result = bytearray(struct.pack('>H', header))

    if value is None:
        return bytes(result)

    is_composite = isinstance(value, dict) or hasattr(value, '__dict__')

    if is_composite:
        packed = pack_fields(value, command.fields_list)
        if packed:
            result.extend(packed[0])
    else:
        if len(command.fields_list) != 1:
            raise ValueError('For simple value, command must have exactly one field')

        field = command.fields_list[0]
        code_to_use = 0 if (field.size != 0 and field.kind != FIELD_TYPE_UNDEFINED) else field.code
        packed = pack_value(value, field.kind, code_to_use, field.size, field)
        if packed:
            result.extend(packed)

    return bytes(result)


# ===================================================================
# Функции распаковки (низкоуровневые)
# ===================================================================
def unpack_boolean(value: int, pos: int) -> Tuple[bool, int]:
    return bool(value), pos


def unpack_signed(data, pos: int, len_flag: int, size: int) -> Tuple[int, int]:
    if size > 0:
        len_flag = LEN_FLAG_BY_SIZE[size]
    else:
        size = SIZE_BY_LEN_FLAG[len_flag]
    end = pos + size
    return struct.unpack(SIGNED_CAST[len_flag], data[pos:end])[0], end


def unpack_unsigned(data, pos: int, len_flag: int, size: int) -> Tuple[int, int]:
    if size > 0:
        len_flag = LEN_FLAG_BY_SIZE[size]
    else:
        size = SIZE_BY_LEN_FLAG[len_flag]
    end = pos + size
    return struct.unpack(UNSIGNED_CAST[len_flag], data[pos:end])[0], end


def unpack_float(data, pos: int, len_flag: int, size: int) -> Tuple[float, int]:
    if size > 0:
        len_flag = LEN_FLAG_BY_SIZE[size]
    else:
        size = SIZE_BY_LEN_FLAG[len_flag]
    end = pos + size
    return struct.unpack(FLOAT_CAST[len_flag], data[pos:end])[0], end


def unpack_bytes(data, pos: int, len_flag: int, size: int) -> Tuple[bytes, int]:
    """
    Распаковывает байтовый массив или строку.
    Если len_flag < 3, то читается префикс длины (размер определяется по len_flag).
    Если len_flag == 3, размер берётся из параметра size (фиксированная длина).
    """
    if len_flag < 3:
        size, pos = unpack_unsigned(data, pos, len_flag, 0)
    end = pos + size
    return data[pos:end], end


def unpack_string(data, pos: int, len_flag: int, size: int, field_def: ProtocolValue) -> Tuple[str, int]:
    raw, pos = unpack_bytes(data, pos, len_flag, size)
    return raw.decode(encoding=getattr(field_def, 'encoding', None) or 'utf-8'), pos


def unpack_array(data, pos: int, len_flag: int, count: int, field_def: ProtocolValue) -> Tuple[List[Any], int]:
    """
    Распаковывает массив.
    Если len_flag < 3, читается количество элементов (размер по len_flag),
    иначе count берётся из параметра (фиксированное).
    Элементы распаковываются рекурсивно: если элемент имеет фиксированный размер и известный тип – без заголовка,
    иначе с заголовком.
    """
    if len_flag < 3:
        count, pos = unpack_unsigned(data, pos, len_flag, 0)

    elements = field_def.elements
    item_kind, item_size = elements.kind, elements.size
    item_has_header = (item_size == 0 or item_kind == FIELD_TYPE_UNDEFINED)
    if not item_has_header:
        item_len = 3

    unpacked = []
    for _ in range(count):
        if item_has_header:
            item_len, item_kind, pos = unpack_header(data, pos)
        value, pos = unpack_value(data, pos, item_kind, item_len, item_size, elements.elements)
        unpacked.append(value)

    return unpacked, pos


def unpack_fields(data, pos: int, count: int, field_by_code: Dict[int, ProtocolField]) -> Tuple[Dict[str, Any], int]:
    """
    Распаковывает последовательность полей (для команд и структур).
    Читает не более count полей, но останавливается при достижении конца данных.
    """
    unpacked = {}
    max_pos = len(data)

    for _ in range(count):
        if pos >= max_pos:
            break

        field_len, field_code, pos = unpack_header(data, pos)

        field = field_by_code.get(field_code)
        if field is None:
            raise ValueError(f'Unknown field code {field_code}')

        field_kind = field.kind
        # Если тип не определён, то следующий байт содержит реальный тип и флаг длины
        if field_kind == FIELD_TYPE_UNDEFINED:
            field_len, field_kind, pos = unpack_header(data, pos)

        value, pos = unpack_value(data, pos, field_kind, field_len, field.size, field)
        unpacked[field.name] = value

    return unpacked, pos


def unpack_struct(data, pos: int, len_flag: int, field_def: ProtocolValue) -> Tuple[Dict[str, Any], int]:
    """
    Распаковывает структуру.
    Сначала читается количество полей (по len_flag), затем распаковываются поля.
    """
    count, pos = unpack_unsigned(data, pos, len_flag, 0)
    field_by_code = {fld.code: fld for fld in field_def.elements}
    return unpack_fields(data, pos, count, field_by_code)


def unpack_header(data, pos: int) -> Tuple[int, int, int]:
    """
    Читает байт заголовка поля, возвращает (len_flag, field_code, new_pos).
    """
    end = pos + 1
    header = struct.unpack('>B', data[pos:end])[0]
    return (header >> 6) & 0x03, header & 0x3F, end


def unpack_value(data, pos: int, kind: int, len_flag: int, fixed: int, field: ProtocolValue) -> Any:
    """
    Распаковывает значение одного поля заданного типа.
    """
    unpack_func = UNPACK_RULES_BY_TYPE.get(kind)
    if unpack_func is None:
        raise ValueError(f'Unsupported kind: {kind}')
    return unpack_func(data, pos, len_flag, fixed, field)


def unpack(protocol: Protocol, data: bytes) -> Tuple[int, int, Dict[str, Any]]:
    """
    Распаковывает сообщение.
    Возвращает (version, cmd, словарь с распакованными полями).
    """
    if len(data) < 2:
        raise ValueError('Message too short')
    header = struct.unpack('>H', data[:2])[0]
    version = (header >> 10) & 0x3F
    cmd = header & 0x3FF
    if version != protocol.version:
        raise ValueError(f'Unsupported version: {version}')

    command = protocol.commands.get(cmd)
    if command is None:
        raise ValueError(f'Unknown command: {cmd}')

    pos = 2
    if len(command.fields_list) == 1:
        single = command.fields_list[0]
        if single.size != 0 and single.kind != FIELD_TYPE_UNDEFINED:
            value, _ = unpack_value(data, pos, single.kind, 3, single.size, single)
            result = {single.name: value}
            return version, cmd, result

    result, _ = unpack_fields(data, pos, len(command.fields_list), command.fields)
    return version, cmd, result


def load_defaults(cmd: ProtocolCommand, data):
    """
    Заполняет отсутствующие поля значениями по умолчанию.
    Поддерживает dict и объекты. Рекурсия только если у поля есть elements.
    """

    def _has_field(obj, name):
        if isinstance(obj, dict):
            return name in obj
        return hasattr(obj, name)

    def _get_field(obj, name):
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    def _set_field(obj, name, value):
        if isinstance(obj, dict):
            obj[name] = value
        else:
            setattr(obj, name, value)

    def _is_container(obj):
        return isinstance(obj, dict) or hasattr(obj, '__dict__')

    def load(value, fields):
        if not fields or not _is_container(value):
            return

        for field in fields:
            # ---- Если поля нет – ставим default (ваша логика) ----
            if not _has_field(value, field.name):
                default = getattr(field, 'default', None)
                if default:
                    _set_field(value, field.name, default)
                continue

            # ---- Поле есть – берём значение ----
            val = _get_field(value, field.name)
            if val is None:
                continue

            if hasattr(field, 'elements') and field.elements:
                # Если значение – словарь/объект и elements – список полей
                if _is_container(val) and isinstance(field.elements, list):
                    load(val, field.elements)
                # Если значение – список и elements – описание элемента-структуры
                elif isinstance(val, (list, tuple, set)):
                    sub_fields = getattr(field.elements, 'elements', None)
                    if sub_fields:
                        for item in val:
                            load(item, sub_fields)

    load(data, cmd.fields_list)
    return data


# ===================================================================
# Пример описания протокола
# ===================================================================
def create_default_protocol():
    ping_fields = [
        ProtocolField(code=1, name='pong', kind=FIELD_TYPE_INT),
        ProtocolField(code=3, name='reqId', kind=FIELD_TYPE_STR, size=22),
        ProtocolField(code=4, name='ts', kind=FIELD_TYPE_UINT, size=8),
    ]
    pong_fields = [
        ProtocolField(code=2, name='replyTo', kind=FIELD_TYPE_STR, size=22),
        ProtocolField(code=4, name='ts', kind=FIELD_TYPE_ARRAY, size=2,
                      elements=ProtocolValue(kind=FIELD_TYPE_UINT, size=8)),
    ]
    ping_cmd = ProtocolCommand(cmd_code=CMD_PING, fields=ping_fields)
    pong_cmd = ProtocolCommand(cmd_code=CMD_PONG, fields=pong_fields)
    return Protocol(version=1, commands=[ping_cmd, pong_cmd])
