# -*- coding: utf-8 -*-
"""纯 Python 实现 APK Signature Scheme v2（无需 JDK / apksigner）。

为什么要这个模块
-----------------
A5 包原来的签法只有 v1（JAR）签名，但清单里 targetSdkVersion=34。
Android 11(API 30) 起，PackageParser 对 targetSdk>=30 的 APK 要求最低签名方案
是 v2；只有 v1 的包在 Android 7 以后的设备（尤其 11+）上会直接判签名校验失败，
表现为「安装包损坏 / 未安装」。这是「某些设备安装不了」的首要根因。

v2 签名块放在「最后一个 ZIP 条目」与「Central Directory」之间，
且 EOCD 里的 centralDirOffset 仍然指向真正的 Central Directory，
所以 Android 4.x 这类不认识 v2 的旧设备会直接按 EOCD 找到 CD，
把签名块当空隙忽略 —— v2 对老设备完全无害（Google 就是这么设计向后兼容的）。

签名方案 ID（按 Android 官方 apksig 规范，已被 apksigner 实测确认）：
  0x0101 = RSASSA-PSS            with SHA2-256   （PSS，非 PKCS1v15！）
  0x0102 = RSASSA-PSS            with SHA2-512
  0x0103 = RSASSA-PKCS1-v1_5     with SHA2-256   ← 本脚本用的就是这个
  0x0104 = RSASSA-PKCS1-v1_5     with SHA2-512
内容摘要算法 = CHUNKED_SHA256（按 1MB 分块）。

⚠️ 致命坑（v21 修正）：算法 ID 必须与实际签名算法一致。
  本脚本用 cryptography 的 PKCS1v15 签名，因此必须标 0x0103。
  若错标成 0x0101，Android/apksigner 会按 PSS 去验，直接
  NoSuchAlgorithmException / 签名不匹配 → 设备上「安装包有问题」/ error 103。
  早期把 0x0101 当 PKCS1v15 是记反了规范，v17→v20 全部因此拒装。

层级陷阱（v19 修正）
-------------------
signed data 里的 digests / signatures，**外层有 lp 包住整个序列，且每个条目
各自还要再套一层 lp**。只套外层会写出一个「自己能解、Android 解不了」的块。
自写的校验脚本必须用**独立于本文件的第三方实现**交叉验证，否则会一起错。
"""
import struct, hashlib

V2_BLOCK_ID = 0x7109871a
APK_SIG_BLOCK_MAGIC = b"APK Sig Block 42"
CHUNK_SIZE = 1024 * 1024

# RSASSA-PKCS1-v1_5 with SHA2-256，内容摘要用 CHUNKED_SHA256
# 注意：Android 规范里 0x0101 是 PSS，PKCS1v15 必须用 0x0103（v21 修正）
SIG_RSA_PKCS1V15_SHA256 = 0x0103
# RSASSA-PKCS1-v1_5 with SHA2-512，内容摘要用 CHUNKED_SHA512
SIG_RSA_PKCS1V15_SHA512 = 0x0104


def _u32(v):
    return struct.pack("<I", v)


def _u64(v):
    return struct.pack("<Q", v)


def _lp(b):
    """length-prefixed: uint32 LE length + data"""
    return _u32(len(b)) + b


# ---------------- ZIP 区段定位 ----------------
def find_eocd(data):
    """从末尾往前找 EOCD（0x06054b50）。返回 (offset, cd_offset, cd_size, total_entries)"""
    # EOCD 最小 22 字节；comment 最长 65535
    start = max(0, len(data) - 22 - 65535)
    i = len(data) - 22
    while i >= start:
        if data[i:i + 4] == b"PK\x05\x06":
            cd_size = struct.unpack("<I", data[i + 12:i + 16])[0]
            cd_offset = struct.unpack("<I", data[i + 16:i + 20])[0]
            cnt = struct.unpack("<H", data[i + 10:i + 12])[0]
            if cd_offset + cd_size <= i:      # 合理性校验
                return i, cd_offset, cd_size, cnt
        i -= 1
    raise ValueError("EOCD not found")


# ---------------- v2 内容摘要 ----------------
# 规范（source.android.com APK Signature Scheme v2）：
#   对每个 1MB 分块：chunk_digest = H(0xa5 + u32(len) + chunk)
#   顶层摘要 = H(0x5a + u32(总块数) + 各块摘要依次拼接)
#   三个区段（条目区 / Central Directory / EOCD）在「分块」层面拼接，
#   即先各自按 1MB 切块、取各块摘要，再全部拼接后做一次顶层哈希。
#   —— 注意：绝不能是「先对每个区段各做一次顶层哈希，再把三段哈希拼起来再哈希」，
#   那样得到的摘要与 Android 计算的不同，设备会判签名不匹配直接拒装。
def _chunk_digest(algo_name, chunk):
    """单个分块摘要：H(0xa5 + u32(len) + chunk)"""
    h = getattr(hashlib, algo_name)
    return h(b"\xa5" + _u32(len(chunk)) + chunk).digest()


def _digests_of(apk_bytes, cd_offset, cd_size, eocd_offset, block_offset):
    """返回 [(算法ID, 摘要字节), ...]，按 APK 规范覆盖「条目区 / CD / EOCD」三段。"""
    # 1) Contents of ZIP entries: [0, 签名块起始)
    contents = apk_bytes[0:block_offset]
    # 2) Central Directory
    central = apk_bytes[cd_offset:cd_offset + cd_size]
    # 3) EOCD，其中 centralDirOffset 字段替换为「APK Signing Block 的起始偏移」
    eocd = bytearray(apk_bytes[eocd_offset:])
    eocd[16:20] = _u32(block_offset)
    eocd = bytes(eocd)

    regions = [contents, central, eocd]
    out = []
    for sig_id, algo_name in ((SIG_RSA_PKCS1V15_SHA256, "sha256"),
                              (SIG_RSA_PKCS1V15_SHA512, "sha512")):
        h = getattr(hashlib, algo_name)
        chunk_digests = []
        for part in regions:
            for off in range(0, len(part), CHUNK_SIZE):
                chunk = part[off:off + CHUNK_SIZE]
                chunk_digests.append(_chunk_digest(algo_name, chunk))
        top = h(b"\x5a" + _u32(len(chunk_digests)) + b"".join(chunk_digests)).digest()
        out.append((sig_id, top))
    return out, contents, central, eocd


# ---------------- v2 签名块构造 ----------------
def build_v2_block(apk_bytes, cd_offset, cd_size, eocd_offset, block_offset,
                   key, cert_der, pubkey_der, sig_ids=None):
    if sig_ids is None:
        sig_ids = [SIG_RSA_PKCS1V15_SHA256]

    digests, _, _, _ = _digests_of(apk_bytes, cd_offset, cd_size,
                                   eocd_offset, block_offset)

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding as cpadding
    _HASH = {SIG_RSA_PKCS1V15_SHA256: hashes.SHA256(),
             SIG_RSA_PKCS1V15_SHA512: hashes.SHA512()}

    # digests: lp( 序列( lp( u32 算法ID + lp(摘要) ) ) )
    #   注意：外层一层 lp 包住整个序列，**每个条目自己还要再套一层 lp**。
    #   少套内层 -> Android 解析时把「算法 ID 0x0101」当成条目长度(257)，
    #   立刻越界 -> 直接判签名块非法 -> 设备上「无法安装」。
    #   （v18 及以前就是栽在这里：自写的校验脚本用同样错的解析，所以自洽地"通过"了）
    dig = b""
    for sig_id, d in digests:
        if sig_id in sig_ids:
            dig += _lp(_u32(sig_id) + _lp(d))
    # certificates: 序列( lp(DER) )
    certs = _lp(cert_der)
    # additional attributes: 空
    attrs = b""

    signed_data = _lp(dig) + _lp(certs) + _lp(attrs)

    # signatures: lp( 序列( lp( u32 算法ID + lp(签名) ) ) )  —— 同样每项再套一层 lp
    #   签名对象是 signed_data 本体（不含长度前缀）
    sigs = b""
    for sig_id in sig_ids:
        sig = key.sign(signed_data, cpadding.PKCS1v15(), _HASH[sig_id])
        sigs += _lp(_u32(sig_id) + _lp(sig))

    # 结构层级（少一层就会整体错位，解析出来全是垃圾）：
    #   signers = lp( concat( lp(signer) ) )       <- 外层序列 + 每个 signer 各带前缀
    #   signer  = lp(signed_data) + lp(signatures) + lp(public_key)
    signer_body = _lp(signed_data) + _lp(sigs) + _lp(pubkey_der)
    signers = _lp(_lp(signer_body))

    pair = _u64(4 + len(signers)) + _u32(V2_BLOCK_ID) + signers
    # 注意：首尾那两个 uint64 的语义是「块总长减去自身这 8 字节」
    #   （= pairs 区 + 8 字节尾部 size + 16 字节 magic），
    #   Android 校验时用 totalBlockSize = 8 + 该字段 反推块起始。
    #   写成块总长会让解析整整偏移 8 字节——第一次就是栽在这里。
    block_size = len(pair) + 24
    block = _u64(block_size) + pair + _u64(block_size) + APK_SIG_BLOCK_MAGIC
    return block


# ---------------- 主入口：给已打包好的 ZIP 补 v2 签名 ----------------
def sign_apk_v2(apk_bytes, key, cert_der, pubkey_der, sig_ids=None):
    """输入：已经做完 v1(JAR) 签名的完整 APK 字节。输出：带 APK Signing Block 的新字节。"""
    eocd_offset, cd_offset, cd_size, cnt = find_eocd(apk_bytes)

    # 签名块起始位置 = 原 CD 起始位置（块插在 CD 前面）
    block_offset = cd_offset
    block = build_v2_block(apk_bytes, cd_offset, cd_size, eocd_offset,
                           block_offset, key, cert_der, pubkey_der, sig_ids)

    out = bytearray()
    out += apk_bytes[:cd_offset]
    out += block
    out += apk_bytes[cd_offset:]
    # 更新 EOCD 里的 centralDirOffset：CD 往后挪了 len(block)
    new_eocd = eocd_offset + len(block)
    out[new_eocd + 16:new_eocd + 20] = _u32(cd_offset + len(block))
    return bytes(out)
