import math
import struct
import zlib
from typing import Tuple, Optional

PROTOCOL_VERSION = 2

MAX_PART_KEY_COUNT = 0x3F

MAX_LENGTH_SIZE = 3
MAX_BYTE_LENGTH = 256
MAX_SHORT_LENGTH = 65792
MAX_LENGTH = (1 << MAX_LENGTH_SIZE * 8) + MAX_SHORT_LENGTH - 1

CMD_INFO = 0
CMD_PING = 1
CMD_PONG = 2

# ===================================================================
# Константы типов полей
# ===================================================================
FIELD_TYPE_UNDEFINED = -1
FIELD_TYPE_EMPTY = 0
FIELD_TYPE_BOOL = 1
FIELD_TYPE_INT = 2
FIELD_TYPE_UINT = 3
FIELD_TYPE_FLOAT = 4
FIELD_TYPE_BYTES = 5
FIELD_TYPE_ARRAY = 6
FIELD_TYPE_STRUCT = 7
FIELD_TYPE_STR = 8
FIELD_TYPE_UNDEFINED_STRUCT = 9

FIELD_TYPE_NEW_PART = MAX_PART_KEY_COUNT

LEN_FLAG_BYTE = 0
LEN_FLAG_SHORT = 1
LEN_FLAG_INT = 2
LEN_FLAG_LONG = 3
LEN_FLAG_FIXED = 0
LEN_FLAG_COMPRESSED = 3

SIZE_BY_LEN_FLAG = (1, 2, 4, 8)
LEN_FLAG_BY_SIZE = {1: LEN_FLAG_BYTE, 2: LEN_FLAG_SHORT, 4: LEN_FLAG_INT, 8: LEN_FLAG_LONG}

CAST_SIGNED = (struct.Struct('>b'), struct.Struct('>h'), struct.Struct('>i'), struct.Struct('>q'))
CAST_UNSIGNED = (struct.Struct('>B'), struct.Struct('>H'), struct.Struct('>I'), struct.Struct('>Q'))
CAST_FLOAT = (struct.Struct('>f'), struct.Struct('>f'), struct.Struct('>f'), struct.Struct('>d'))

EMPTY_VALUE = 0

# ===================================================================
# Классы описания протокола
# ===================================================================
from dataclasses import dataclass
from typing import List, Dict, Any


# ===== ProtocolValue =====
@dataclass
class ProtocolValue:
    kind: int
    size: int = 0
    elements: Any = None

    def __post_init__(self):
        if self.kind == FIELD_TYPE_BOOL:
            self.size = 1
        elif self.kind in (FIELD_TYPE_UNDEFINED, FIELD_TYPE_STR, FIELD_TYPE_STRUCT):
            self.size = 0
        if self.size < 0 or self.size > MAX_LENGTH:
            raise ValueError(f'Invalid size: expected 0..{MAX_LENGTH} got {self.size}')

        if self.kind in (FIELD_TYPE_STRUCT, FIELD_TYPE_ARRAY) and self.elements is not None:
            if not isinstance(self.elements, list):
                self.elements = [self.elements]
            if self.kind == FIELD_TYPE_STRUCT:
                self.elements = sorted(self.elements, key=lambda x: x.code)
        else:
            self.elements = None

    def __repr__(self):
        fields_repr = ", ".join(str(f) for f in self.elements or [])
        return f"ProtocolValue(kind={self.kind}, size={self.size}, elements={fields_repr})"


# ===== ProtocolField =====
@dataclass
class ProtocolField(ProtocolValue):
    code: int = 0
    name: str = ''

    def __repr__(self):
        fields_repr = ", ".join(str(f) for f in self.elements or [])
        return f"ProtocolField(code={self.code}, name={self.name}, kind={self.kind}, size={self.size}, elements={fields_repr})"


# ===== ProtocolCommand =====
@dataclass(init=False)
class ProtocolCommand:
    cmdCode: int
    fields: Dict[int, 'ProtocolField']
    fieldsList: List['ProtocolField']

    def __init__(self, cmd_code: int, fields: List['ProtocolField']):
        self.cmdCode = cmd_code
        self.fieldsList = fields
        self.fields = {f.code: f for f in fields}

    def __repr__(self):
        fields_repr = ", ".join(str(f) for f in self.fieldsList)
        return f"ProtocolCommand(cmdCode={self.cmdCode}, fields=[{fields_repr}])"


# ===== Protocol =====
@dataclass(init=False)
class Protocol:
    version: int
    commands: Dict[int, ProtocolCommand]

    def __init__(self, version: int, commands: List[ProtocolCommand]):
        self.version = version
        self.commands = {cmd.cmdCode: cmd for cmd in commands}


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
    elif isinstance(value, (bytes, bytearray)):
        return FIELD_TYPE_BYTES
    elif isinstance(value, (list, tuple, set)):
        return FIELD_TYPE_ARRAY
    elif isinstance(value, dict):
        return FIELD_TYPE_UNDEFINED_STRUCT
    elif hasattr(value, '__dict__'):
        return FIELD_TYPE_UNDEFINED_STRUCT
    elif isinstance(value, str):
        return FIELD_TYPE_STR
    else:
        return FIELD_TYPE_UNDEFINED


# ===================================================================
# Функции определения длины (флага длины) для чисел
# ===================================================================
def len_flag_for_signed(value: int) -> int:
    if -128 <= value <= 127:
        return LEN_FLAG_BYTE
    elif -32768 <= value <= 32767:
        return LEN_FLAG_SHORT
    elif -2147483648 <= value <= 2147483647:
        return LEN_FLAG_INT
    else:
        return LEN_FLAG_LONG


def len_flag_for_unsigned(value: int) -> int:
    if 0 <= value <= 255:
        return LEN_FLAG_BYTE
    elif 0 <= value <= 65535:
        return LEN_FLAG_SHORT
    elif 0 <= value <= 4294967295:
        return LEN_FLAG_INT
    else:
        return LEN_FLAG_LONG


def len_flag_for_float(value: float) -> int:
    if not math.isfinite(value):
        return LEN_FLAG_LONG
    try:
        f32 = struct.unpack('>f', struct.pack('>f', value))[0]
        if f32 == 0.0:
            return LEN_FLAG_INT
        rel_err = abs((value - f32) / value)
        if rel_err < 1e-6:
            return LEN_FLAG_INT
        else:
            return LEN_FLAG_LONG
    except OverflowError:
        return LEN_FLAG_LONG


def len_flag_for_length(value: int) -> int:
    if value < MAX_BYTE_LENGTH:
        return LEN_FLAG_BYTE
    elif value < MAX_SHORT_LENGTH:
        return LEN_FLAG_SHORT
    else:
        return LEN_FLAG_INT


def calc_length_header(value):
    len_flag = len_flag_for_length(value)
    if len_flag == LEN_FLAG_BYTE:
        return value.to_bytes(1), len_flag
    if len_flag == LEN_FLAG_SHORT:
        return (value - MAX_BYTE_LENGTH).to_bytes(2), len_flag
    return (value - MAX_SHORT_LENGTH).to_bytes(MAX_LENGTH_SIZE), len_flag


def read_length_header(data, pos, len_flag):
    if len_flag == LEN_FLAG_BYTE:
        end = pos + 1
        return int.from_bytes(data[pos:end]), end
    if len_flag == LEN_FLAG_SHORT:
        end = pos + 2
        return int.from_bytes(data[pos:end]) + MAX_BYTE_LENGTH, end
    end = pos + MAX_LENGTH_SIZE
    return int.from_bytes(data[pos:end]) + MAX_SHORT_LENGTH, end


# ===================================================================
# Словари правил упаковки и распаковки по типу поля
# ===================================================================
PACK_RULES_BY_TYPE = {
    FIELD_TYPE_BOOL: lambda v, x, f: pack_boolean(v),
    FIELD_TYPE_INT: lambda v, x, f: pack_signed(v, x),
    FIELD_TYPE_UINT: lambda v, x, f: pack_unsigned(v, x),
    FIELD_TYPE_FLOAT: lambda v, x, f: pack_float(v, x),
    FIELD_TYPE_BYTES: lambda v, x, f: pack_bytes(v, x),
    FIELD_TYPE_ARRAY: lambda v, x, f: pack_array(v, x, f),
    FIELD_TYPE_STRUCT: lambda v, x, f: pack_struct(v, f),
    FIELD_TYPE_STR: lambda v, x, f: pack_string(v),
    FIELD_TYPE_UNDEFINED_STRUCT: lambda v, x, f: pack_undefined_struct(v),
}

UNPACK_RULES_BY_TYPE = {
    FIELD_TYPE_BOOL: lambda v, i, l, x, f: unpack_boolean(l, i),
    FIELD_TYPE_INT: lambda v, i, l, x, f: unpack_signed(v, i, l, x),
    FIELD_TYPE_UINT: lambda v, i, l, x, f: unpack_unsigned(v, i, l, x),
    FIELD_TYPE_FLOAT: lambda v, i, l, x, f: unpack_float(v, i, l, x),
    FIELD_TYPE_BYTES: lambda v, i, l, x, f: unpack_bytes(v, i, l, x),
    FIELD_TYPE_ARRAY: lambda v, i, l, x, f: unpack_array(v, i, l, x, f),
    FIELD_TYPE_STRUCT: lambda v, i, l, x, f: unpack_struct(v, i, l, f),
    FIELD_TYPE_STR: lambda v, i, l, x, f: unpack_string(v, i, l),
    FIELD_TYPE_UNDEFINED: lambda v, i, l, x, f: unpack_undefined(v, i, f),
    FIELD_TYPE_UNDEFINED_STRUCT: lambda v, i, l, x, f: unpack_undefined_struct(v, i, l),
}

UNDEFINED_VALUE = ProtocolValue(FIELD_TYPE_UNDEFINED, 0)


def compress_bytes(data: bytes,
                   chunk_size: int = 64 * 1024,
                   level: int = 9,
                   max_ratio: float = 1.0) -> Tuple[bool, bytes]:
    """
    Сжимает данные инкрементально. Если промежуточный размер сжатых данных
    достигает max_ratio * len(data), сжатие прерывается и возвращается оригинал.

    Аргументы:
        data: исходные байты.
        chunk_size: размер блока для поточной подачи (рекомендуется 32–256 КБ).
        level: уровень сжатия zlib (0–9).
        max_ratio: максимально допустимое отношение (сжатый / исходный).
                   Например, 0.9 означает «прервать, если выигрыш менее 10%».

    Возвращает:
        Сжатые байты, если они короче, иначе исходные.
    """
    original_size = len(data)
    if original_size <= 0:
        return False, data

    threshold = int(original_size * max_ratio)
    compressor = zlib.compressobj(level=level, wbits=-zlib.MAX_WBITS)
    parts = []
    total_compressed = 0

    # Подаём данные блоками
    for i in range(0, original_size, chunk_size):
        chunk = data[i:i + chunk_size]
        compressed_chunk = compressor.compress(chunk)
        if compressed_chunk:
            parts.append(compressed_chunk)
            total_compressed += len(compressed_chunk)

            # Если уже превысили порог – немедленный выход
            if total_compressed >= threshold:
                return False, data

    # Завершаем сжатие (могут остаться данные в буфере компрессора)
    last = compressor.flush()
    if last:
        parts.append(last)
        total_compressed += len(last)

    # Финальная проверка
    if total_compressed < original_size:
        return True, b''.join(parts)
    else:
        return False, data


def decompress_data(compressed: bytes) -> bytes:
    """
    Распаковывает данные, сжатые алгоритмом zlib (DEFLATE).
    Возвращает распакованные байты или выбрасывает ValueError при ошибке.
    """
    try:
        return zlib.decompress(compressed, wbits=-zlib.MAX_WBITS)
    except zlib.error as e:
        raise ValueError(f"Decompression failed: {e}")


# ===================================================================
# Функции упаковки (возвращают (bytes, len_flag))
# ===================================================================
def pack_boolean(value: bool) -> Tuple[bytes, int]:
    return b'', int(value)


def pack_signed(value: int, fixed: int = 0) -> Tuple[bytes, int]:
    len_flag = len_flag_for_signed(value) if fixed == 0 else LEN_FLAG_BY_SIZE[fixed]
    return CAST_SIGNED[len_flag].pack(value), len_flag


def pack_unsigned(value: int, fixed: int = 0) -> Tuple[bytes, int]:
    len_flag = len_flag_for_unsigned(value) if fixed == 0 else LEN_FLAG_BY_SIZE[fixed]
    return CAST_UNSIGNED[len_flag].pack(value), len_flag


def pack_float(value: float, fixed: int = 0) -> Tuple[bytes, int]:
    len_flag = len_flag_for_float(value) if fixed == 0 else LEN_FLAG_BY_SIZE[fixed]
    return CAST_FLOAT[len_flag].pack(value), len_flag


def pack_bytes(value: bytes, fixed: int) -> Tuple[bytes, int]:
    """
    Упаковывает байтовый массив.
    """
    if 0 < fixed != len(value):
        raise ValueError(f'Array length mismatch: expected {fixed}, got {len(value)}')

    if len(value) == 0:
        return None

    is_compressed, value = compress_bytes(value)
    length = len(value)

    if is_compressed:
        if length > MAX_LENGTH - MAX_SHORT_LENGTH:
            raise ValueError(f'Array length too large: maximum {MAX_LENGTH - MAX_SHORT_LENGTH}, got {length}')

        return length.to_bytes(MAX_LENGTH_SIZE) + value, LEN_FLAG_COMPRESSED

    if length > MAX_LENGTH:
        raise ValueError(f'Array length too large: maximum {MAX_LENGTH}, got {length}')

    if fixed > 0:
        return value, LEN_FLAG_FIXED

    size_hdr, len_flag = calc_length_header(length)
    return size_hdr + value, len_flag


def pack_string(value: str) -> Tuple[bytes, int]:
    """
    Упаковывает строку.
    """
    return pack_bytes(value.encode(), 0)


def pack_bool_array(items: List[bool]) -> bytes:
    packed = 0
    for item in items:
        packed = (packed << 1) | int(item) & 0x01
    packed <<= (8 - len(items)) % 8
    return packed.to_bytes((len(items) + 7) // 8)


def pack_array(value, fixed: int, fields: List[ProtocolValue]) -> Tuple[bytes, int]:
    fields = fields or [UNDEFINED_VALUE]
    elements_length = len(fields)
    packed = []
    count = len(value)

    # Если массив состоит из одного элемента и он BOOL, упаковываем все булевы в битовый массив
    if elements_length == 1 and fields[0].kind == FIELD_TYPE_BOOL:
        bool_values = [bool(v) for v in value]
        packed.append(pack_bool_array(bool_values))

    else:
        # Иначе – стандартная группировка по элементам
        pending_bool = []

        def write_pending_bool():
            if pending_bool:
                packed.append(pack_bool_array(pending_bool))
                pending_bool.clear()

        for i, item in enumerate(value):
            if (element_index := i % elements_length) == 0:
                write_pending_bool()

            element = fields[element_index]
            item_kind, item_size, item_elements = element.kind, element.size, element.elements

            if item_kind == FIELD_TYPE_BOOL:
                pending_bool.append(item)
                continue

            write_pending_bool()

            part = pack_value(item, item_kind, None, item_size, item_elements)
            packed.append(EMPTY_VALUE.to_bytes(1) if part is None else part)

        write_pending_bool()

    if fixed > 0:
        if count != fixed:
            raise ValueError(f'Array length mismatch: expected {fixed}, got {count}')
        len_flag = LEN_FLAG_FIXED
    elif count == 0:
        return None
    else:
        size_hdr, len_flag = calc_length_header(count)
        packed = [size_hdr] + packed
    return b''.join(packed), len_flag


def pack_new_partition(start: int) -> bytes:
    size_hdr, len_flag = calc_length_header(start)
    return ((len_flag << 6) | (FIELD_TYPE_NEW_PART & 0x3F)).to_bytes(1) + size_hdr


def pack_fields(value, fields: List[ProtocolField], indexed_code: bool = False) -> Tuple[List, int]:
    """
    Упаковывает структуру.
    Поля упаковываются последовательно
    """
    if isinstance(value, dict):
        getter = lambda k: value.get(k)
    else:
        getter = lambda k: getattr(value, k, None)

    packed = []
    packed_fields = []
    start_code = 0
    for field in fields:
        val = getter(field.name)
        if not val:
            continue

        field_code = (len(packed) if indexed_code else field.code) - start_code
        if field_code >= FIELD_TYPE_NEW_PART:
            start_code += field_code
            packed.append(pack_new_partition(start_code))
            field_code -= start_code

        part = pack_value(val, field.kind, field_code, field.size, field.elements)
        if part:
            packed.append(part)
            packed_fields.append(field)

    return packed, packed_fields


def pack_struct(value, fields: List[ProtocolField]) -> Tuple[bytes, int]:
    """
    Упаковывает структуру.
    Поля упаковываются последовательно, затем добавляется префикс с количеством непустых полей.
    """
    packed, packed_fields = pack_fields(value, fields)

    if packed:
        size_hdr, len_flag = calc_length_header(len(packed_fields))
        return b''.join([size_hdr] + packed), len_flag


def pack_undefined_fields(fields: List[ProtocolField]) -> Tuple[Any, int]:
    fields_names = [
        len(b).to_bytes(1) + b for b in (
            f.name.encode() for f in fields
        )
    ]
    return pack_bytes(b''.join(fields_names), 0)


def pack_undefined_struct(value) -> Tuple[List[Tuple[str, int, int, Any]], int]:
    if isinstance(value, dict):
        names = value.keys()
    else:
        raw_names = getattr(value, '__dict__', None)
        if not raw_names:
            raise ValueError(f'Unknown structure: expected "dict" or "object" got {type(value)}')
        names = filter(lambda s: not s.startswith('_'), raw_names.keys())

    fields = [
        ProtocolField(code=i, name=str(n), kind=FIELD_TYPE_UNDEFINED, size=0)
        for i, n in enumerate(names, 0)
    ]

    packed, packed_fields = pack_fields(value, fields, indexed_code=True)
    if packed:
        fields_part, len_flag = pack_undefined_fields(packed_fields)
        return b''.join([fields_part] + packed), len_flag


def pack_value(value, kind: int, code: int, fixed: int = 0, fields: List[ProtocolValue] = None) -> Optional[bytes]:
    """
    Упаковывает одно значение.
    Если kind == FIELD_TYPE_UNDEFINED, определяется автоматически.
    Возвращает bytes или None, если значение считается пустым.
    """
    if value is None:
        return None

    result = []

    if kind == FIELD_TYPE_UNDEFINED:
        kind = obtain_kind(value)
        if code is not None:
            result.append(code.to_bytes(1))
        code, fixed = kind, 0

    pack_func = PACK_RULES_BY_TYPE.get(kind)
    if pack_func is None:
        raise ValueError(f'Unsupported kind: {kind}')

    packed_result = pack_func(value, fixed, fields)
    if packed_result is None:
        return None

    packed, len_flag = packed_result

    # if not packed and kind != FIELD_TYPE_BOOL:
    #     return None

    if code is not None:
        result.append(((len_flag << 6) | (code & 0x3F)).to_bytes(1))
    elif fixed == 0:
        result.append(((len_flag << 6) | (kind & 0x3F)).to_bytes(1))

    result.append(packed)
    return b''.join(result)


def pack(protocol: Protocol, cmd: int, value) -> bytes:
    """
    Упаковывает сообщение согласно протоколу.
    value может быть dict, объектом с атрибутами или простым значением (если команда имеет одно поле).
    """
    command = protocol.commands.get(cmd)
    if command is None:
        raise ValueError(f'Unknown command: {cmd}')

    header = (protocol.version << 10) | cmd
    result = [header.to_bytes(2)]

    if value is None:
        return result[0]

    is_composite = isinstance(value, dict) or hasattr(value, '__dict__')

    if is_composite:
        packed = pack_fields(value, command.fieldsList)
        if packed:
            result.extend(packed[0])
    else:
        if len(command.fieldsList) != 1:
            raise ValueError('For simple value, command must have exactly one field')

        field = command.fieldsList[0]
        code_to_use = None if (field.size != 0 or field.kind == FIELD_TYPE_UNDEFINED) else field.kind
        packed = pack_value(value, field.kind, code_to_use, field.size, field.elements)
        if packed:
            result.append(packed)

    return b''.join(result)


# ===================================================================
# Функции распаковки (низкоуровневые)
# ===================================================================
def unpack_boolean(data: int, pos: int) -> Tuple[bool, int]:
    return bool(data), pos


def unpack_signed(data, pos: int, len_flag: int, fixed: int) -> Tuple[int, int]:
    if fixed > 0:
        len_flag = LEN_FLAG_BY_SIZE[fixed]
    else:
        fixed = SIZE_BY_LEN_FLAG[len_flag]
    end = pos + fixed
    return CAST_SIGNED[len_flag].unpack(data[pos:end])[0], end


def unpack_unsigned(data, pos: int, len_flag: int, fixed: int) -> Tuple[int, int]:
    if fixed > 0:
        len_flag = LEN_FLAG_BY_SIZE[fixed]
    else:
        fixed = SIZE_BY_LEN_FLAG[len_flag]
    end = pos + fixed
    return CAST_UNSIGNED[len_flag].unpack(data[pos:end])[0], end


def unpack_float(data, pos: int, len_flag: int, fixed: int) -> Tuple[float, int]:
    if fixed > 0:
        len_flag = LEN_FLAG_BY_SIZE[fixed]
    else:
        fixed = SIZE_BY_LEN_FLAG[len_flag]
    end = pos + fixed
    return CAST_FLOAT[len_flag].unpack(data[pos:end])[0], end


def unpack_bytes(data, pos: int, len_flag: int, fixed: int) -> Tuple[bytes, int]:
    """
    Распаковывает байтовый массив или строку.
    """
    if len_flag == LEN_FLAG_COMPRESSED:  # 3
        length, pos = read_length_header(data, pos, len_flag)
        end = pos + length - MAX_SHORT_LENGTH
        if end > len(data):
            raise ValueError("Not enough data for compressed payload")
        decompressed = decompress_data(data[pos:end])
        return decompressed, end

    if fixed > 0:
        end = pos + fixed
    else:
        length, pos = read_length_header(data, pos, len_flag)
        end = pos + length
    return data[pos:end], end


def unpack_string(data, pos: int, len_flag: int) -> Tuple[str, int]:
    raw, pos = unpack_bytes(data, pos, len_flag, 0)
    return raw.decode(), pos


def unpack_header(data, pos: int) -> Tuple[int, int, int]:
    """
    Читает байт заголовка поля, возвращает (len_flag, field_code, new_pos).
    """
    end = pos + 1
    header = int.from_bytes(data[pos:end])
    return (header >> 6) & 0x03, header & 0x3F, end


def unpack_bool_array(data, pos: int, count: int) -> Tuple[List[bool], int]:
    unpacked = []
    while len(unpacked) < count:
        byte = data[pos]
        pos += 1
        for i in range(8):
            value = bool(byte & 0x80)
            byte <<= 1
            unpacked.append(value)
            if len(unpacked) == count:
                break
    return unpacked, pos


def unpack_array(data, pos: int, len_flag: int, count: int, fields: List[ProtocolValue]) -> Tuple[List[Any], int]:
    fields = fields or [UNDEFINED_VALUE]
    elements_length = len(fields)

    # Если массив из одного BOOL – читаем битовый массив
    if elements_length == 1 and fields[0].kind == FIELD_TYPE_BOOL:
        if count == 0:
            count, pos = read_length_header(data, pos, len_flag)
        bool_values, pos = unpack_bool_array(data, pos, count)
        return bool_values, pos

    # Стандартная распаковка
    if count == 0:
        count, pos = read_length_header(data, pos, len_flag)

    unpacked = []

    def read_pending_bool():
        nonlocal pending_bool, pos
        if pending_bool != 0:
            unpacked_bool, pos = unpack_bool_array(data, pos, pending_bool)
            unpacked.extend(unpacked_bool)
            pending_bool = 0
        return pos

    while len(unpacked) < count:
        pending_bool = 0
        for element in fields:
            item_kind, item_size = element.kind, element.size

            if item_kind == FIELD_TYPE_BOOL:
                pending_bool += 1
                continue

            pos = read_pending_bool()

            if item_size == 0 or item_kind == FIELD_TYPE_UNDEFINED:
                if data[pos] == EMPTY_VALUE:
                    unpacked.append(None)
                    pos += 1
                    continue

                item_len, item_kind, pos = unpack_header(data, pos)
            else:
                item_len = LEN_FLAG_BY_SIZE[item_size]

            value, pos = unpack_value(data, pos, item_kind, item_len, item_size, element.elements)
            unpacked.append(value)

        pos = read_pending_bool()

    return unpacked, pos


def unpack_fields(data, pos: int, count: int, field_by_code: Dict[int, ProtocolField]) -> Tuple[Dict[str, Any], int]:
    """
    Распаковывает последовательность полей (для команд и структур).
    Читает не более count полей, но останавливается при достижении конца данных.
    """
    unpacked = {}
    max_pos = len(data)
    start_code = 0

    for _ in range(count):
        if pos >= max_pos:
            break

        field_len, field_code, pos = unpack_header(data, pos)

        while field_code == FIELD_TYPE_NEW_PART:
            start_code, pos = read_length_header(data, pos, field_len)
            field_len, field_code, pos = unpack_header(data, pos)

        field_code += start_code
        field = field_by_code.get(field_code)
        if field is None:
            raise ValueError(f'Unknown field code {field_code}')

        field_kind = field.kind
        # Если тип не определён, то следующий байт содержит реальный тип и флаг длины
        if field_kind == FIELD_TYPE_UNDEFINED:
            field_len, field_kind, pos = unpack_header(data, pos)

        value, pos = unpack_value(data, pos, field_kind, field_len, field.size, field.elements)
        unpacked[field.name] = value

    return unpacked, pos


def unpack_struct(data, pos: int, len_flag: int, fields_def: List[ProtocolField]) -> Tuple[Dict[str, Any], int]:
    """
    Распаковывает структуру.
    Сначала читается количество полей (по len_flag), затем распаковываются поля.
    """
    count, pos = read_length_header(data, pos, len_flag)

    field_by_code = {f.code: f for f in fields_def}
    return unpack_fields(data, pos, count, field_by_code)


def unpack_undefined_fields(data, pos: int, len_flag: int) -> Tuple[List[ProtocolField], int]:
    unpacked, pos = unpack_bytes(data, pos, len_flag, 0)

    fields = []
    part_pos = 0
    max_pos = len(unpacked)

    while part_pos < max_pos:
        part_len, part_pos = unpacked[part_pos], part_pos + 1
        field_name = unpacked[part_pos: part_pos + part_len].decode()
        part_pos += part_len
        fields.append(ProtocolField(code=len(fields), name=field_name, kind=FIELD_TYPE_UNDEFINED, size=0))

    return fields, pos


def unpack_undefined_struct(data, pos: int, len_flag: int) -> Tuple[Dict[str, Any], int]:
    """
    Распаковывает структуру.
    """
    fields_def, pos = unpack_undefined_fields(data, pos, len_flag)

    field_by_code = {f.code: f for f in fields_def}
    return unpack_fields(data, pos, len(fields_def), field_by_code)


def unpack_undefined(data, pos: int, fields_def: List[ProtocolValue]) -> Tuple[Any, int]:
    len_flag, kind, pos = unpack_header(data, pos)
    return unpack_value(data, pos, kind, len_flag, 0, fields_def)


def unpack_value(data, pos: int, kind: int, len_flag: int, fixed: int, fields_def: List[ProtocolValue]) -> Any:
    """
    Распаковывает значение одного поля заданного типа.
    """
    unpack_func = UNPACK_RULES_BY_TYPE.get(kind)
    if unpack_func is None:
        raise ValueError(f'Unsupported kind: {kind}')
    return unpack_func(data, pos, len_flag, fixed, fields_def)


def unpack(protocol: Protocol, data: bytes) -> Tuple[int, int, Dict[str, Any]]:
    """
    Распаковывает сообщение.
    Возвращает (version, cmd, словарь с распакованными полями).
    """
    if len(data) < 2:
        raise ValueError('Message too short')
    header = int.from_bytes(data[:2])
    version = (header >> 10) & 0x3F
    cmd = header & 0x3FF
    if version != protocol.version:
        raise ValueError(f'Unsupported version: {version}')

    command = protocol.commands.get(cmd)
    if command is None:
        raise ValueError(f'Unknown command: {cmd}')

    if len(command.fieldsList) == 0:
        return version, cmd, None

    pos = 2
    if len(command.fieldsList) == 1:
        single = command.fieldsList[0]
        if single.size != 0 and single.kind != FIELD_TYPE_UNDEFINED:
            value, _ = unpack_value(data, pos, single.kind, LEN_FLAG_FIXED, single.size, single.elements)
            return version, cmd, {single.name: value}

    payload, _ = unpack_fields(data, pos, len(command.fieldsList), command.fields)
    return version, cmd, payload


def serialize_protocol(protocol):
    return {"commands": list(protocol.commands.values())}


def unpack_info(info: dict) -> List[ProtocolCommand]:
    """
    Распаковывает информацию о протоколе из словаря, полученного при распаковке команды CMD_INFO.
    Возвращает список объектов ProtocolCommand.
    """

    def parse_element(elem_data):
        """
        Рекурсивно разбирает элемент (может быть ProtocolField или ProtocolValue).
        """
        if isinstance(elem_data, dict):
            kind = elem_data.get('kind', FIELD_TYPE_UNDEFINED)
            size = elem_data.get('size', 0)
            raw_elements = elem_data.get('elements')
            elements = None
            if raw_elements is not None:
                if isinstance(raw_elements, list):
                    elements = [parse_element(e) for e in raw_elements]
                else:
                    elements = [parse_element(raw_elements)]
            # Проверяем, является ли это полем структуры (есть code и name)
            if 'code' in elem_data or 'name' in elem_data:
                return ProtocolField(
                    code=elem_data.get('code', 0),
                    name=elem_data.get('name', ''),
                    kind=kind,
                    size=size,
                    elements=elements
                )
            else:
                # Это элемент массива (только kind и size)
                return ProtocolValue(kind=kind, size=size, elements=elements)
        else:
            # Если элемент не словарь (маловероятно)
            return ProtocolValue(kind=FIELD_TYPE_UNDEFINED, size=0)

    commands_data = info.get('commands')
    if commands_data is None:
        return []
    if not isinstance(commands_data, list):
        return []

    result = []
    for cmd_data in commands_data:
        if not isinstance(cmd_data, dict):
            continue

        cmd_code = cmd_data.get('cmdCode', 0)
        fields_list = cmd_data.get('fieldsList', [])

        fields = []
        for fld in fields_list:
            field = parse_element(fld)
            if isinstance(field, ProtocolField):
                fields.append(field)
            else:
                # В полях команд всегда должны быть поля с code/name
                raise ValueError(f'Expected ProtocolField, got {type(field)}')

        command = ProtocolCommand(cmd_code=cmd_code, fields=fields)
        result.append(command)

    return {'commands': result}


# ===================================================================
# Пример описания протокола
# ===================================================================
def create_default_protocol():
    commands_field = [
        ProtocolField(code=0, name='commands', kind=FIELD_TYPE_UNDEFINED)
    ]
    info_cmd = ProtocolCommand(cmd_code=CMD_INFO, fields=commands_field)

    ping_fields = [
        ProtocolField(code=0, name='pong', kind=FIELD_TYPE_INT),
        ProtocolField(code=1, name='reqId', kind=FIELD_TYPE_STR),
        ProtocolField(code=2, name='ts', kind=FIELD_TYPE_UINT, size=8),
    ]
    ping_cmd = ProtocolCommand(cmd_code=CMD_PING, fields=ping_fields)

    pong_fields = [
        ProtocolField(code=0, name='replyTo', kind=FIELD_TYPE_STR),
        ProtocolField(code=1, name='ts', kind=FIELD_TYPE_ARRAY, size=2,
                      elements=ProtocolValue(kind=FIELD_TYPE_UINT, size=8)),
    ]
    pong_cmd = ProtocolCommand(cmd_code=CMD_PONG, fields=pong_fields)

    return Protocol(
        version=PROTOCOL_VERSION,
        commands=[info_cmd, ping_cmd, pong_cmd]
    )
