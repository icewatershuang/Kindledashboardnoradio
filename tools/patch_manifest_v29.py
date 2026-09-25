# -*- coding: utf-8 -*-
"""v29：在二进制 AndroidManifest.xml 里就地改版本信息。

  versionName  "V28" -> "V29"
  versionCode  692   -> 693

定长替换保证字符串池其它条目的绝对偏移不变。
改完用独立解码器复核 versionName，并回读 versionCode 确认。
"""
import io, os, struct, sys

BASE = "C:/Users/Administrator/WorkBuddy/2026-09-13-03-27-43/kindle_dashboard"
SRC = os.path.join(BASE, "manifest_a5_v28.bin")
DST = os.path.join(BASE, "manifest_a5_v29.bin")

d = bytearray(io.open(SRC, "rb").read())


def find_u16(hay, needle):
    nb = needle.encode("utf-16-le")
    i = hay.find(nb)
    while i > 0:
        if struct.unpack_from("<H", hay, i - 2)[0] == len(needle):
            return i - 2
        i = hay.find(nb, i + 1)
    return -1


# ---- 1) versionName: V28 -> V29 ----
pos = find_u16(d, "V28")
if pos < 0:
    raise SystemExit("找不到 versionName 字符串 V28")
old = bytes(d[pos:pos + 10])          # len(2) + 3*2 + NUL(2)
new = struct.pack("<H", 3) + "V29".encode("utf-16-le") + b"\x00\x00"
assert len(old) == len(new) == 10, (len(old), len(new))
d[pos:pos + 10] = new
print("versionName 替换:", old, "->", bytes(new))

# ---- 2) versionCode: 692 -> 693 ----
sys.path.insert(0, BASE)
import axml_info

hit = axml_info.find_attr_value_offset(bytes(d), "manifest", "versionCode", expect_int=692)
if not hit:
    raise SystemExit("找不到 manifest 的 versionCode 属性（或值不是 692）")
_p, voff = hit
struct.pack_into("<i", d, voff, 693)
print("versionCode 692 -> 693 @%d，核对 = %d" % (voff, struct.unpack_from("<i", d, voff)[0]))

io.open(DST, "wb").write(bytes(d))
print("写出", DST, os.path.getsize(DST), "字节")


# ---------------- 复核 ----------------
def decode(path):
    dd = open(path, "rb").read()
    typ, hsize, total = struct.unpack_from("<HHI", dd, 0)
    assert typ == 0x0003
    pool_off = None
    off = 8
    while off + 8 <= len(dd):
        t, hs, sz = struct.unpack_from("<HHI", dd, off)
        if sz <= 0:
            break
        if t == 0x0001 and pool_off is None:
            pool_off = off
        off += sz
    cnt, scnt, flags, strStart, styStart = struct.unpack_from("<5I", dd, pool_off + 8)
    str_base = pool_off + strStart
    offs = [struct.unpack_from("<I", dd, pool_off + hs + 4 * i)[0] for i in range(cnt)]

    def read_str(k):
        p = str_base + offs[k]
        n = struct.unpack_from("<H", dd, p)[0]
        if n & 0x8000:
            ln = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", dd, p + 2)[0]
            head = 4
        else:
            ln = n
            head = 2
        return dd[p + head:p + head + ln * 2].decode("utf-16-le")

    return [read_str(k) for k in range(cnt)]


i0 = axml_info.parse(SRC)
i1 = axml_info.parse(DST)
print("新清单解析: versionCode=%s versionName=%s minSdk=%s targetSdk=%s package=%s"
      % (i1.get("versionCode"), i1.get("versionName"),
         i1.get("minSdk"), i1.get("targetSdk"), i1.get("package")))
assert i1.get("versionCode") == 693, "versionCode 未改成功"
assert i1.get("versionName") == "V29", "versionName 未改成功"
assert i1.get("minSdk") == i0.get("minSdk") and i1.get("targetSdk") == i0.get("targetSdk"), "SDK 变了"
assert i1.get("package") == "com.kindledash.app", "包名变了"
print("复核通过：SDK/包名未变，版本已升到 V29(693)")

a = decode(SRC)
b = decode(DST)
if len(a) != len(b):
    raise SystemExit("字符串数量变了，中止")
diff = [(k, a[k], b[k]) for k in range(len(a)) if a[k] != b[k]]
print("字符串差异:", diff)
if len(diff) != 1 or diff[0][1] != "V28" or diff[0][2] != "V29":
    raise SystemExit("差异不符合预期，中止")
print("复核通过：仅 versionName V28 -> V29，其余 %d 条字符串不变" % (len(a) - 1))
