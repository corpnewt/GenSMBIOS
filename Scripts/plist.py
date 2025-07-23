import datetime
import os
import plistlib
import struct
import sys
import itertools
import binascii
from io import BytesIO
from collections import OrderedDict

FMT_XML = plistlib.FMT_XML
FMT_BINARY = plistlib.FMT_BINARY


class InvalidFileException(ValueError):
    def __init__(self, message="Invalid file"):
        super().__init__(message)


_BINARY_FORMAT = {1: "B", 2: "H", 4: "L", 8: "Q"}

_undefined = object()


class UID(plistlib.UID):
    pass


def _is_binary(fp):
    if isinstance(fp, (bytes, bytearray)):
        return fp.startswith(b"bplist00")
    header = fp.read(32)
    fp.seek(0)
    return header[:8] == b"bplist00"


def _seek_past_whitespace(fp):
    offset = fp.tell()
    while True:
        byte = fp.read(1)
        if not byte:
            offset = fp.tell()
            break
        if not byte.isspace():
            break
        offset = fp.tell()
    fp.seek(offset)
    return offset


def load(fp, fmt=None, dict_type=OrderedDict):
    if _is_binary(fp):
        p = _BinaryPlistParser(dict_type=dict_type)
        return p.parse(fp)
    offset = _seek_past_whitespace(fp)
    if fmt is None:
        header = fp.read(32)
        fp.seek(offset)
        for info in plistlib._FORMATS.values():
            if info["detect"](header):
                P = info["parser"]
                break
        else:
            raise plistlib.InvalidFileException()
    else:
        P = plistlib._FORMATS[fmt]["parser"]
    p = P(dict_type=dict_type)
    if isinstance(p, plistlib._PlistParser):

        def end_integer():
            d = p.get_data()
            value = int(d, 16) if d.lower().startswith("0x") else int(d)
            if -1 << 63 <= value < 1 << 64:
                p.add_object(value)
            else:
                raise OverflowError(
                    f"Integer overflow at line {p.parser.CurrentLineNumber}"
                )

        def end_data():
            try:
                p.add_object(plistlib._decode_base64(p.get_data()))
            except Exception as e:
                raise Exception(f"Data error at line {p.parser.CurrentLineNumber}: {e}")

        p.end_integer = end_integer
        p.end_data = end_data
    return p.parse(fp)


def loads(value, fmt=None, dict_type=OrderedDict):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return load(BytesIO(value), fmt=fmt, dict_type=dict_type)


def dump(value, fp, fmt=FMT_XML, sort_keys=True, skipkeys=False):
    if fmt == FMT_BINARY:
        writer = _BinaryPlistWriter(fp, sort_keys=sort_keys, skipkeys=skipkeys)
        writer.write(value)
    elif fmt == FMT_XML:
        plistlib.dump(value, fp, fmt=fmt, sort_keys=sort_keys, skipkeys=skipkeys)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def dumps(value, fmt=FMT_XML, skipkeys=False, sort_keys=True):
    f = BytesIO()
    dump(value, f, fmt=fmt, skipkeys=skipkeys, sort_keys=sort_keys)
    value = f.getvalue()
    if fmt == FMT_XML:
        value = value.decode("utf-8")
    return value


def readPlist(pathOrFile):
    with open(pathOrFile, "rb") as f:
        return load(f)


def writePlist(value, pathOrFile):
    with open(pathOrFile, "wb") as f:
        return dump(value, f, fmt=FMT_XML, sort_keys=True, skipkeys=False)


class _BinaryPlistParser:
    def __init__(self, dict_type):
        self._dict_type = dict_type

    def parse(self, fp):
        try:
            self._fp = fp
            self._fp.seek(-32, os.SEEK_END)
            trailer = self._fp.read(32)
            if len(trailer) != 32:
                raise InvalidFileException()
            (
                offset_size,
                self._ref_size,
                num_objects,
                top_object,
                offset_table_offset,
            ) = struct.unpack(">6xBBQQQ", trailer)
            self._fp.seek(offset_table_offset)
            self._object_offsets = self._read_ints(num_objects, offset_size)
            self._objects = [_undefined] * num_objects
            return self._read_object(top_object)
        except (OSError, IndexError, struct.error, OverflowError, UnicodeDecodeError):
            raise InvalidFileException()

    def _get_size(self, tokenL):
        if tokenL == 0xF:
            m = self._fp.read(1)[0]
            m = m & 0x3
            s = 1 << m
            f = ">" + _BINARY_FORMAT[s]
            return struct.unpack(f, self._fp.read(s))[0]
        return tokenL

    def _read_ints(self, n, size):
        data = self._fp.read(size * n)
        if size in _BINARY_FORMAT:
            return struct.unpack(">" + _BINARY_FORMAT[size] * n, data)
        else:
            if not size or len(data) != size * n:
                raise InvalidFileException()
            return tuple(
                int.from_bytes(data[i : i + size], "big")
                for i in range(0, size * n, size)
            )

    def _read_refs(self, n):
        return self._read_ints(n, self._ref_size)

    def _read_object(self, ref):
        result = self._objects[ref]
        if result is not _undefined:
            return result
        offset = self._object_offsets[ref]
        self._fp.seek(offset)
        token = self._fp.read(1)[0]
        tokenH, tokenL = token & 0xF0, token & 0x0F
        if token == 0x00:
            result = None
        elif token == 0x08:
            result = False
        elif token == 0x09:
            result = True
        elif token == 0x0F:
            result = b""
        elif tokenH == 0x10:
            result = int.from_bytes(self._fp.read(1 << tokenL), "big", signed=True)
        elif token == 0x22:
            result = struct.unpack(">f", self._fp.read(4))[0]
        elif token == 0x23:
            result = struct.unpack(">d", self._fp.read(8))[0]
        elif token == 0x33:
            f = struct.unpack(">d", self._fp.read(8))[0]
            result = datetime.datetime(2001, 1, 1) + datetime.timedelta(seconds=f)
        elif tokenH == 0x40:
            s = self._get_size(tokenL)
            result = self._fp.read(s)
        elif tokenH == 0x50:
            s = self._get_size(tokenL)
            result = self._fp.read(s).decode("ascii")
        elif tokenH == 0x60:
            s = self._get_size(tokenL)
            result = self._fp.read(s * 2).decode("utf-16be")
        elif tokenH == 0x80:
            result = UID(int.from_bytes(self._fp.read(1 + tokenL), "big"))
        elif tokenH == 0xA0:
            s = self._get_size(tokenL)
            obj_refs = self._read_refs(s)
            result = []
            self._objects[ref] = result
            result.extend(self._read_object(x) for x in obj_refs)
        elif tokenH == 0xD0:
            s = self._get_size(tokenL)
            key_refs = self._read_refs(s)
            obj_refs = self._read_refs(s)
            result = self._dict_type()
            self._objects[ref] = result
            for k, o in zip(key_refs, obj_refs):
                key = self._read_object(k)
                result[key] = self._read_object(o)
        else:
            raise InvalidFileException()
        self._objects[ref] = result
        return result


def _count_to_size(count):
    if count < 1 << 8:
        return 1
    elif count < 1 << 16:
        return 2
    elif count < 1 << 32:
        return 4
    else:
        return 8


_scalars = (str, int, float, datetime.datetime, bytes)


class _BinaryPlistWriter(object):
    def __init__(self, fp, sort_keys, skipkeys):
        self._fp = fp
        self._sort_keys = sort_keys
        self._skipkeys = skipkeys

    def write(self, value):
        self._objlist = []
        self._objtable = {}
        self._objidtable = {}
        self._flatten(value)
        num_objects = len(self._objlist)
        self._object_offsets = [0] * num_objects
        self._ref_size = _count_to_size(num_objects)
        self._ref_format = _BINARY_FORMAT[self._ref_size]
        self._fp.write(b"bplist00")
        for obj in self._objlist:
            self._write_object(obj)
        top_object = self._getrefnum(value)
        offset_table_offset = self._fp.tell()
        offset_size = _count_to_size(offset_table_offset)
        offset_format = ">" + _BINARY_FORMAT[offset_size] * num_objects
        self._fp.write(struct.pack(offset_format, *self._object_offsets))
        sort_version = 0
        trailer = (
            sort_version,
            offset_size,
            self._ref_size,
            num_objects,
            top_object,
            offset_table_offset,
        )
        self._fp.write(struct.pack(">5xBBBQQQ", *trailer))

    def _flatten(self, value):
        if isinstance(value, _scalars):
            if (type(value), value) in self._objtable:
                return
        elif id(value) in self._objidtable:
            return
        refnum = len(self._objlist)
        self._objlist.append(value)
        if isinstance(value, _scalars):
            self._objtable[(type(value), value)] = refnum
        else:
            self._objidtable[id(value)] = refnum
        if isinstance(value, dict):
            keys = []
            values = []
            items = sorted(value.items()) if self._sort_keys else value.items()
            for k, v in items:
                if not isinstance(k, str):
                    if self._skipkeys:
                        continue
                    raise TypeError("keys must be strings")
                keys.append(k)
                values.append(v)
            for o in itertools.chain(keys, values):
                self._flatten(o)
        elif isinstance(value, (list, tuple)):
            for o in value:
                self._flatten(o)

    def _getrefnum(self, value):
        if isinstance(value, _scalars):
            return self._objtable[(type(value), value)]
        else:
            return self._objidtable[id(value)]

    def _write_size(self, token, size):
        if size < 15:
            self._fp.write(struct.pack(">B", token | size))
        elif size < 1 << 8:
            self._fp.write(struct.pack(">BBB", token | 0xF, 0x10, size))
        elif size < 1 << 16:
            self._fp.write(struct.pack(">BBH", token | 0xF, 0x11, size))
        elif size < 1 << 32:
            self._fp.write(struct.pack(">BBL", token | 0xF, 0x12, size))
        else:
            self._fp.write(struct.pack(">BBQ", token | 0xF, 0x13, size))

    def _write_object(self, value):
        ref = self._getrefnum(value)
        self._object_offsets[ref] = self._fp.tell()
        if value is None:
            self._fp.write(b"\x00")
        elif value is False:
            self._fp.write(b"\x08")
        elif value is True:
            self._fp.write(b"\x09")
        elif isinstance(value, int):
            if value < 0:
                try:
                    self._fp.write(struct.pack(">Bq", 0x13, value))
                except struct.error:
                    raise OverflowError(value)
            elif value < 1 << 8:
                self._fp.write(struct.pack(">BB", 0x10, value))
            elif value < 1 << 16:
                self._fp.write(struct.pack(">BH", 0x11, value))
            elif value < 1 << 32:
                self._fp.write(struct.pack(">BL", 0x12, value))
            elif value < 1 << 63:
                self._fp.write(struct.pack(">BQ", 0x13, value))
            elif value < 1 << 64:
                self._fp.write(b"\x14" + value.to_bytes(16, "big", signed=True))
            else:
                raise OverflowError(value)
        elif isinstance(value, float):
            self._fp.write(struct.pack(">Bd", 0x23, value))
        elif isinstance(value, datetime.datetime):
            f = (value - datetime.datetime(2001, 1, 1)).total_seconds()
            self._fp.write(struct.pack(">Bd", 0x33, f))
        elif isinstance(value, bytes):
            self._write_size(0x40, len(value))
            self._fp.write(value)
        elif isinstance(value, str):
            try:
                t = value.encode("ascii")
                self._write_size(0x50, len(value))
            except UnicodeEncodeError:
                t = value.encode("utf-16be")
                self._write_size(0x60, len(t) // 2)
            self._fp.write(t)
        elif isinstance(value, plistlib.UID):
            if value.data < 0:
                raise ValueError("UIDs must be positive")
            elif value.data < 1 << 8:
                self._fp.write(struct.pack(">BB", 0x80, value.data))
            elif value.data < 1 << 16:
                self._fp.write(struct.pack(">BH", 0x81, value.data))
            elif value.data < 1 << 32:
                self._fp.write(struct.pack(">BL", 0x83, value.data))
            else:
                raise OverflowError(value)
        elif isinstance(value, (list, tuple)):
            refs = [self._getrefnum(o) for o in value]
            s = len(refs)
            self._write_size(0xA0, s)
            self._fp.write(struct.pack(">" + self._ref_format * s, *refs))
        elif isinstance(value, dict):
            keyRefs, valRefs = [], []
            items = sorted(value.items()) if self._sort_keys else value.items()
            for k, v in items:
                if not isinstance(k, str):
                    if self._skipkeys:
                        continue
                    raise TypeError("keys must be strings")
                keyRefs.append(self._getrefnum(k))
                valRefs.append(self._getrefnum(v))
            s = len(keyRefs)
            self._write_size(0xD0, s)
            self._fp.write(struct.pack(">" + self._ref_format * s, *keyRefs))
            self._fp.write(struct.pack(">" + self._ref_format * s, *valRefs))
        else:
            raise TypeError(value)
