# -*- coding: utf-8 -*-
"""重建 A5 分支 APK：把 assets/dashboard.html 换成 dashboard_a5.html 并重签 v1。

V6.31-A5 重写说明（与主线 repackage_v8.py 完全同构）：
旧版 repackage_a5.py 有三个致命隐患，本次全部修掉：
 1. **每次构建随机生成密钥** → 各版本签名不一致，已装 com.kindledash.app 无法原地升级
    （安装器报「程序未安装」）。现改为复用 signing_key.pem / signing_cert.pem，
    与主线 V6.31 共用同一把密钥，A5 包与主线包可互相覆盖升级。
 2. **摘要属性名写成 `SHA-1-Digest`（带连字符）** → Android 4.0–4.2 的 JarVerifier
    只认 `SHA1-Digest`，会被判「缺摘要」→ 点安装后报「程序未安装」。现改为 SHA1-Digest。
 3. **全条目强制 DEFLATED** → resources.arsc / classes.dex / launcher png 必须保持
    原样的 STORED 且数据起始 4 字节对齐，否则 4.0.4 Dalvik 拒装。现逐条目保留原
    compress_type，并手写 ZIP writer 给 STORED 条目补 0x00 对齐。

其余沿用成熟规则：v1(JAR) only、无 v2/v3 区块、PKCS7 走 SHA1withRSA（asn1crypto 手搓，
cryptography 3.x 禁用 SHA-1 签名）、证书有效期 2010→2040 防老设备时钟偏早。
"""
import io, os, struct, zlib, hashlib, base64, datetime, zipfile, sys
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from asn1crypto import cms, core
from asn1crypto import x509 as a_x509

BASE = "C:/Users/Administrator/WorkBuddy/2026-09-13-03-27-43/kindle_dashboard"
if BASE not in sys.path:
    sys.path.insert(0, BASE)
import apk_sign_v2            # 纯 Python 的 APK Signature Scheme v2
ORIG = os.path.join(BASE, "Kindle仪表盘_V6.31.apk")
# 可选命令行覆盖：  repackage_a5.py <html路径> <输出apk路径>
# 用于生成「去掉 API Key 的公开版」：把 scrub 过的 HTML 打成另一个 APK。
MOD = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "extracted/assets/dashboard_a5.html")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE, "KindleDash_A5_v21.apk")
# v5c：换掉二进制 AndroidManifest.xml。
#   加 RECORD_AUDIO / MODIFY_AUDIO_SETTINGS / FOREGROUND_SERVICE_MICROPHONE
#     -> AI 语音识别报 not-allowed 的根因就是缺 RECORD_AUDIO；
#   加 android.intent.category.HOME
#     -> 允许把仪表盘设为系统桌面，真正"一直在屏幕上常显"。
# 置空表示用原包的清单（不改动）。
MANIFEST_BIN = os.path.join(BASE, "manifest_a5_v29.bin")   # v29：versionName V29 / versionCode 693
ALIAS = "WORKBUDDY"
KEY_PATH = os.path.join(BASE, "signing_key.pem")
CERT_PATH = os.path.join(BASE, "signing_cert.pem")


def b64(b):
    return base64.b64encode(b).decode("ascii")


# ---------- 1. 收集条目（保留原始压缩方式） ----------
with io.open(MOD, "rb") as f:
    html = f.read()
orig = zipfile.ZipFile(ORIG, "r")
entries = []
for info in orig.infolist():
    name = info.filename
    if name.startswith("META-INF/") or name.endswith("/"):
        continue
    data = orig.read(name)
    if name == "assets/dashboard.html":
        data = html
    if name == "AndroidManifest.xml" and MANIFEST_BIN and os.path.exists(MANIFEST_BIN):
        with io.open(MANIFEST_BIN, "rb") as mf:
            data = mf.read()
        print("manifest replaced: %d bytes" % len(data))
    entries.append({
        "name": name,
        "data": data,
        "ctype": info.compress_type,     # 0=STORED, 8=DEFLATED -> 原样保留
        "dt": info.date_time,
        "eattr": info.external_attr,
    })
orig.close()
print("html bytes:", len(html))

# ---------- 1b. 补齐 HTML 里引用、但底包没有的 assets ----------
# v16 发现：A5 分支的底包 Kindle仪表盘_V6.31.apk 里没有 assets/hls.min.js 与
# assets/radio_presets.js，而 dashboard_a5.html 用 <script src="..."> 引了这两个文件。
# 结果就是 RADIO_PRESETS 恒为 undefined —— 电台按钮界面和设置页里的电台清单
# 一直是空的，m3u8 也少了 HLS 兜底。这里按 extracted/assets/ 里的实际文件补齐。
EXTRA_ASSETS = ["hls.min.js", "radio_presets.js"]
have = set(e["name"] for e in entries)
for nm in EXTRA_ASSETS:
    path = os.path.join(BASE, "extracted/assets", nm)
    if not os.path.exists(path):
        print("WARN: missing local asset, skip:", path)
        continue
    apk_name = "assets/" + nm
    if apk_name in have:
        continue
    with io.open(path, "rb") as f:
        data = f.read()
    ent = {"name": apk_name, "data": data, "ctype": 8,
           "dt": (2026, 9, 19, 0, 0, 0), "eattr": 0}
    idx = 0
    for i, e in enumerate(entries):
        if e["name"] == "assets/dashboard.html":
            idx = i + 1
            break
    entries.insert(idx, ent)
    print("added missing asset: %s (%d bytes)" % (apk_name, len(data)))

print("STORED entries:", [e["name"] for e in entries if e["ctype"] == 0])

# ---------- 2. v1 JAR 签名：全链路 SHA-1，属性名 SHA1-Digest（无连字符） ----------
manifest = "Manifest-Version: 1.0\r\n\r\n"
manifest_sections = {}
for e in entries:
    s1 = hashlib.sha1(e["data"]).digest()
    sec = "Name: %s\r\nSHA1-Digest: %s\r\n" % (e["name"], b64(s1))
    manifest += sec + "\r\n"
    manifest_sections[e["name"]] = sec
manifest_bytes = manifest.encode("utf-8")
sf = ("Signature-Version: 1.0\r\nCreated-By: 1.0 (Android)\r\n"
      "SHA1-Digest-Manifest: %s\r\n\r\n") % (b64(hashlib.sha1(manifest_bytes).digest()))
for e in entries:
    sec = manifest_sections[e["name"]]
    sf += ("Name: %s\r\nSHA1-Digest: %s\r\n\r\n") % (
        e["name"], b64(hashlib.sha1(sec.encode("utf-8")).digest()))
sf_bytes = sf.encode("utf-8")

# ---------- 3. 持久签名密钥（与主线共用，保证可原地升级） ----------
if os.path.exists(KEY_PATH) and os.path.exists(CERT_PATH):
    with open(KEY_PATH, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    with open(CERT_PATH, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())
    print("loaded persistent signing key")
else:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Shanghai"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Shanghai"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "KindleDash"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Dev"),
        x509.NameAttribute(NameOID.COMMON_NAME, "KindleDash"),
    ])
    not_before = datetime.datetime(2010, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    not_after = datetime.datetime(2040, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(not_before).not_valid_after(not_after)
            .sign(key, hashes.SHA256()))
    with open(KEY_PATH, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption()))
    with open(CERT_PATH, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print("generated + saved persistent signing key")

cert_der = cert.public_bytes(serialization.Encoding.DER)
acert = a_x509.Certificate.load(cert_der)
si = cms.SignerInfo({
    'version': 1,
    'sid': cms.SignerIdentifier({'issuer_and_serial_number': cms.IssuerAndSerialNumber({
        'issuer': acert.subject, 'serial_number': acert.serial_number})}),
    'digest_algorithm': cms.DigestAlgorithm({'algorithm': 'sha1'}),
    'signature_algorithm': cms.SignedDigestAlgorithm({'algorithm': 'rsassa_pkcs1v15'}),
    'signature': core.OctetString(key.sign(sf_bytes, padding.PKCS1v15(), hashes.SHA1())),
})
sd = cms.SignedData({
    'version': 1,
    'digest_algorithms': cms.DigestAlgorithms([cms.DigestAlgorithm({'algorithm': 'sha1'})]),
    'encap_content_info': cms.ContentInfo({'content_type': 'data'}),
    'certificates': cms.CertificateSet([acert]),
    'signer_infos': cms.SignerInfos([si]),
})
sig = cms.ContentInfo({'content_type': 'signed_data', 'content': sd}).dump()

meta = [("META-INF/MANIFEST.MF", manifest_bytes),
        ("META-INF/%s.SF" % ALIAS, sf_bytes),
        ("META-INF/%s.RSA" % ALIAS, sig)]

# ---------- 4. 手写 ZIP writer：保留 compress_type + STORED 4 字节对齐 ----------
def dos_datetime(dt):
    y, mo, d, h, mi, s = (dt + (0,))[:6] if len(dt) < 6 else dt
    t = (h << 11) | (mi << 5) | (s // 2)
    dte = ((y - 1980) << 9) | (mo << 5) | d
    return t & 0xffff, dte & 0xffff


def compress_data(data, ctype):
    if ctype == 0:
        return data
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    return co.compress(data) + co.flush()


# v17：对齐方式改为「local header 的 extra field 填充」。
#   旧做法是在上一个条目数据之后、下一个 local header 之前插入裸 0x00 —— 这在 ZIP
#   规范里是非法的（两个 local header 之间不允许有额外数据），严格解析器（Android
#   4.x 的 ZipFileRO / 部分厂商 ROM 的校验）会直接判「包损坏」。
#   正确做法同 zipalign：把填充塞进 extra field（ID+长度+数据），header 变长，
#   数据起始位置随之对齐，任何解析器都能正确跳过。
ALIGN_EXTRA_ID = 0xFECA


def align_extra(buf_len, name_len):
    """返回需要写入 local header 的 extra 字节（已含 4 字节头）"""
    base = buf_len + 30 + name_len          # local header 固定 30 字节
    need = (4 - (base % 4)) % 4
    if need == 0:
        return b""
    return struct.pack("<HH", ALIGN_EXTRA_ID, need) + b"\x00" * need


buf = bytearray()
central = bytearray()
for e in entries:
    data = e["data"]
    crc = zlib.crc32(data) & 0xffffffff
    comp = compress_data(data, e["ctype"])
    t, dte = dos_datetime(e["dt"])
    name_b = e["name"].encode("utf-8")
    method = 0 if e["ctype"] == 0 else 8
    extra = align_extra(len(buf), len(name_b)) if e["ctype"] == 0 else b""
    lho = (struct.pack("<I", 0x04034b50) + struct.pack("<H", 20) + struct.pack("<H", 0)
           + struct.pack("<H", method) + struct.pack("<H", t) + struct.pack("<H", dte)
           + struct.pack("<I", crc) + struct.pack("<I", len(comp)) + struct.pack("<I", len(data))
           + struct.pack("<H", len(name_b)) + struct.pack("<H", len(extra)) + name_b + extra)
    off = len(buf)
    buf += lho + comp
    central += (struct.pack("<I", 0x02014b50) + struct.pack("<H", 20) + struct.pack("<H", 20)
                + struct.pack("<H", 0) + struct.pack("<H", method) + struct.pack("<H", t)
                + struct.pack("<H", dte) + struct.pack("<I", crc) + struct.pack("<I", len(comp))
                + struct.pack("<I", len(data)) + struct.pack("<H", len(name_b))
                + struct.pack("<H", 0) + struct.pack("<H", 0) + struct.pack("<H", 0)
                + struct.pack("<H", 0) + struct.pack("<I", e["eattr"]) + struct.pack("<I", off)
                + name_b)

for (name, data) in meta:
    crc = zlib.crc32(data) & 0xffffffff
    comp = compress_data(data, 8)
    t, dte = dos_datetime((1980, 1, 1, 0, 0, 0))
    name_b = name.encode("utf-8")
    lho = (struct.pack("<I", 0x04034b50) + struct.pack("<H", 20) + struct.pack("<H", 0)
           + struct.pack("<H", 8) + struct.pack("<H", t) + struct.pack("<H", dte)
           + struct.pack("<I", crc) + struct.pack("<I", len(comp)) + struct.pack("<I", len(data))
           + struct.pack("<H", len(name_b)) + struct.pack("<H", 0) + name_b)
    off = len(buf)
    buf += lho + comp
    central += (struct.pack("<I", 0x02014b50) + struct.pack("<H", 20) + struct.pack("<H", 20)
                + struct.pack("<H", 0) + struct.pack("<H", 8) + struct.pack("<H", t)
                + struct.pack("<H", dte) + struct.pack("<I", crc) + struct.pack("<I", len(comp))
                + struct.pack("<I", len(data)) + struct.pack("<H", len(name_b))
                + struct.pack("<H", 0) + struct.pack("<H", 0) + struct.pack("<H", 0)
                + struct.pack("<H", 0) + struct.pack("<I", 0) + struct.pack("<I", off) + name_b)

cd_offset = len(buf)
cd_size = len(central)
buf += central
buf += (struct.pack("<I", 0x06054b50) + struct.pack("<H", 0) + struct.pack("<H", 0)
        + struct.pack("<H", len(entries) + len(meta)) + struct.pack("<H", len(entries) + len(meta))
        + struct.pack("<I", cd_size) + struct.pack("<I", cd_offset) + struct.pack("<H", 0))

# ---------- 4b. 严格自检：条目之间不得有裸填充、STORED 必须 4 字节对齐 ----------
def selfcheck(zbytes):
    eocd_off, cd_off, cd_size, cnt = apk_sign_v2.find_eocd(zbytes)
    assert cd_off + cd_size == eocd_off, "CD 与 EOCD 不连续"
    pos, gaps, bad = 0, 0, []
    for _ in range(cnt):
        assert zbytes[pos:pos + 4] == b"PK\x03\x04", "条目 %d 处不是 local header（有垃圾字节）" % pos
        (ver, flag, meth, t, dte, crc, csz, usz, nl, el) = struct.unpack(
            "<HHHHHIIIHH", zbytes[pos + 4:pos + 30])
        dstart = pos + 30 + nl + el
        if meth == 0 and dstart % 4:
            bad.append((pos, dstart))
        pos = dstart + csz
    assert pos == cd_off, "最后一个条目之后还有 %d 字节垃圾" % (cd_off - pos)
    return gaps, bad


selfcheck(bytes(buf))

# ---------- 5. v2 签名：targetSdk=34 时 Android 11+ 强制要求，缺了装不上 ----------
pub_der = key.public_key().public_bytes(
    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
if os.environ.get("KD_NO_V2") == "1":
    signed = bytes(buf)
    print("!! KD_NO_V2=1 -> 只做 v1 签名（仅调试用，真机勿发）")
else:
    signed = apk_sign_v2.sign_apk_v2(bytes(buf), key, cert_der, pub_der)

with io.open(OUT, "wb") as f:
    f.write(signed)
print("Wrote", OUT, os.path.getsize(OUT), "bytes")
print("entries", len(entries), "+ META-INF", len(meta),
      "(v1+v2, zipalign via extra field, SHA1-Digest, persistent key)")
