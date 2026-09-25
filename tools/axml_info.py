# -*- coding: utf-8 -*-
"""轻量 AXML（二进制 AndroidManifest.xml）解析：只读，不依赖 aapt。

坑：AXML 里 START_ELEMENT 的属性「名字」是**字符串池索引**，不是资源 ID，
    所以不能靠 0x0101021b 这类 res id 去二进制里搜——搜不到。
    必须老老实实解析字符串池 + 元素属性表。

提供：
  parse(path_or_bytes) -> dict
     {'package':..., 'versionCode':..., 'versionName':...,
      'minSdk':..., 'targetSdk':..., 'elements':[{'tag':..., 'attrs':{...}}]}
"""
import struct

TYPE_STRING_POOL = 0x0001
TYPE_START_ELEMENT = 0x0102
TYPE_END_ELEMENT = 0x0103
TYPE_CDATA = 0x0104

DATA_TYPE_INT_DEC = 0x10
DATA_TYPE_STRING = 0x03


class StrPool(object):
    def __init__(self, b, off, hs, sz):
        cnt, scnt, flags, strStart, styStart = struct.unpack_from("<5I", b, off + 8)
        self.b = b
        self.cnt = cnt
        self.utf8 = bool(flags & 0x100)
        self.base = off + strStart
        self.offs = [struct.unpack_from("<I", b, off + hs + 4 * i)[0] for i in range(cnt)]

    def get(self, i):
        if i < 0 or i >= self.cnt:
            return None
        p = self.base + self.offs[i]
        b = self.b
        if self.utf8:
            # 长度前缀本身也是变长（1~2 字节），且与字符串同编码
            n = b[p]
            head = 1
            if n & 0x80:
                n = ((n & 0x7F) << 8) | b[p + 1]
                head = 2
            n2 = b[p + head]
            head2 = 1
            if n2 & 0x80:
                head2 = 2
            s = p + head + head2
            return b[s:s + n].decode("utf-8", "replace")
        n = struct.unpack_from("<H", b, p)[0]
        if n & 0x8000:
            ln = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", b, p + 2)[0]
            head = 4
        else:
            ln = n
            head = 2
        return b[p + head:p + head + ln * 2].decode("utf-16-le", "replace")


def _chunks(b):
    typ, hsize, total = struct.unpack_from("<HHI", b, 0)
    off = hsize if hsize >= 8 else 8
    out = []
    while off + 8 <= len(b):
        t, hs, sz = struct.unpack_from("<HHI", b, off)
        if sz <= 0:
            break
        out.append((t, off, hs, sz))
        off += sz
    return out


def parse(path_or_bytes):
    if isinstance(path_or_bytes, bytes):
        b = path_or_bytes
    else:
        b = open(path_or_bytes, "rb").read()
    pool = None
    for t, off, hs, sz in _chunks(b):
        if t == TYPE_STRING_POOL:
            pool = StrPool(b, off, hs, sz)
            break
    if pool is None:
        raise ValueError("no string pool")

    elements = []
    stack = []
    for t, off, hs, sz in _chunks(b):
        if t == TYPE_END_ELEMENT:
            if stack:
                stack.pop()
            continue
        if t != TYPE_START_ELEMENT:
            continue
        # node 头 = type(2)+headerSize(2)+size(4)+lineNumber(4)+comment(4) = 16 字节
        # attrExt 从 off+16 开始：ns(4) name(4) attributeStart(2) attributeSize(2)
        #                        attributeCount(2) idIndex(2) classIndex(2) styleIndex(2)
        (ns, name, attrStart, attrSize, attrCount,
         idIdx, clsIdx, styIdx) = struct.unpack_from("<iiHHHHHH", b, off + 16)
        tag = pool.get(name)
        attrs = {}
        for i in range(attrCount):
            p = off + 16 + attrStart + i * attrSize   # attributeStart 相对 attrExt(=off+16)
            ans, aname, araw = struct.unpack_from("<iii", b, p)
            (vsize, vres0, vtype, vdata) = struct.unpack_from("<HBBI", b, p + 12)
            key = pool.get(aname)
            if key is None:
                key = "attr#%d" % aname
            if vtype == DATA_TYPE_STRING:
                attrs[key] = pool.get(vdata)
            elif vtype in (DATA_TYPE_INT_DEC, 0x11):     # 0x11 = TYPE_INT_HEX（位标志常用）
                attrs[key] = struct.unpack("<i", struct.pack("<I", vdata))[0]
            elif vtype == 0x12:                          # TYPE_INT_BOOLEAN
                attrs[key] = bool(vdata)
            else:
                attrs[key] = (vtype, vdata)
        el = {"tag": tag, "attrs": attrs, "children": []}
        elements.append(el)
        if stack:
            stack[-1]["children"].append(el)
        stack.append(el)

    info = {"elements": elements}
    for e in elements:
        if e["tag"] == "manifest":
            info["package"] = e["attrs"].get("package")
            info["versionCode"] = e["attrs"].get("versionCode")
            info["versionName"] = e["attrs"].get("versionName")
        elif e["tag"] == "uses-sdk":
            info["minSdk"] = e["attrs"].get("minSdkVersion")
            info["targetSdk"] = e["attrs"].get("targetSdkVersion")
    return info


def find_attr_value_offset(b, tag, attr_name, expect_int=None):
    """返回 (属性块起始, 值 data 字段的偏移)，用于就地改 int 值"""
    typ, hsize, total = struct.unpack_from("<HHI", b, 0)
    pool = None
    for t, off, hs, sz in _chunks(b):
        if t == TYPE_STRING_POOL:
            pool = StrPool(b, off, hs, sz)
            break
    for t, off, hs, sz in _chunks(b):
        if t != TYPE_START_ELEMENT:
            continue
        (ns, name, attrStart, attrSize, attrCount,
         idIdx, clsIdx, styIdx) = struct.unpack_from("<iiHHHHHH", b, off + 16)
        if pool.get(name) != tag:
            continue
        for i in range(attrCount):
            p = off + 16 + attrStart + i * attrSize   # attributeStart 相对 attrExt(=off+16)
            ans, aname, araw = struct.unpack_from("<iii", b, p)
            if pool.get(aname) != attr_name:
                continue
            (vsize, vres0, vtype, vdata) = struct.unpack_from("<HBBI", b, p + 12)
            if expect_int is not None and vdata != expect_int:
                raise ValueError("值不符: 期望 %d 实际 %d" % (expect_int, vdata))
            return p, p + 16      # typedValue.data 位于 p+12+4 = p+16
    return None


if __name__ == "__main__":
    import sys
    i = parse(sys.argv[1])
    for k in ("package", "versionCode", "versionName", "minSdk", "targetSdk"):
        print("%-12s %s" % (k, i.get(k)))
