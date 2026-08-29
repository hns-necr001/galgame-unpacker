# -*- coding: utf-8 -*-
"""
GARbro 其他引擎加密算法的 Python 移植(零依赖,储备模块)。
来源文件(原文存于 gar_src/ 目录):
- SimpleEncryption.cs      : XorTransform / NotTransform / ByteStringXor
- DxLib/DxKey.cs           : DxKey / DxKey7
- KiriKiri/CroixCrypt.cs   : CroixCrypt(KiriKiri 系)
- AZSys/ArcEncrypted.cs    : AzDecrypt / Isaac64Cipher / AzIsaacEncryption
"""

import hashlib
import struct

_U32_MASK = 0xFFFFFFFF
_U64_MASK = 0xFFFFFFFFFFFFFFFF


def _u32(x):
    return x & _U32_MASK


def _u64(x):
    return x & _U64_MASK


def _rotl(x, n, bits=32):
    n &= bits - 1
    return ((x << n) | (x >> (bits - n))) & ((1 << bits) - 1)


def _rotr(x, n, bits=32):
    return _rotl(x, -n % bits, bits)


# ---------- SimpleEncryption.cs ----------

def not_transform(data):
    """NotTransform:逐字节取反。"""
    return bytes(~b & 0xFF for b in data)


def xor_transform(data, key):
    """XorTransform:逐字节 XOR 单字节 key。"""
    k = key & 0xFF
    return bytes(b ^ k for b in data)


class ByteStringXor:
    """ByteStringEncryptedStream:密钥流循环 XOR(位置模 key 长度)。"""

    def __init__(self, key):
        self.key = bytes(key)

    def decrypt(self, data, start_pos=0):
        key = self.key
        n = len(key)
        base = start_pos % n
        out = bytearray(len(data))
        for i in range(len(data)):
            out[i] = data[i] ^ key[(base + i) % n]
        return bytes(out)


# ---------- DxLib/DxKey.cs ----------

def _rot_byte_r(v, n):
    n &= 7
    return ((v >> n) | (v << (8 - n))) & 0xFF


def _rot_byte_l(v, n):
    return _rot_byte_r(v, -n % 8)


def dx_key_create(keyword):
    """DxKey.CreateKey:由密码生成 12 字节密钥。"""
    if not keyword:
        key = bytearray([0xAA] * 12)
    else:
        b = keyword.encode('cp932', errors='ignore')
        key = bytearray(12)
        n = min(len(b), 12)
        key[:n] = b[:n]
        if n < 12:
            # CopyOverlapped(key, 0, n, 12-n):整体右移,前 12-n 字节保留原值
            key[12 - n:] = key[0:n]
    key[0] ^= 0xFF
    key[1] = _rot_byte_r(key[1], 4)
    key[2] ^= 0x8A
    key[3] = (~_rot_byte_r(key[3], 4)) & 0xFF
    key[4] ^= 0xFF
    key[5] ^= 0xAC
    key[6] ^= 0xFF
    key[7] = (~_rot_byte_r(key[7], 3)) & 0xFF
    key[8] = _rot_byte_l(key[8], 3)
    key[9] ^= 0x7F
    key[10] = (_rot_byte_r(key[10], 4) ^ 0xD6) & 0xFF
    key[11] ^= 0xCC
    return bytes(key)


def dx_key7_create(keyword):
    """DxKey7.CreateKey:SHA-256 摘要。"""
    return hashlib.sha256(keyword.encode('cp932', errors='ignore')).digest()


def dx_key7_entry_key(name, password='DXARC'):
    """DxKey7.GetEntryKey:密码 + 路径反序大写的 SHA-256。"""
    parts = name.replace('\\', '/').split('/')
    password = password + ''.join(p.upper() for p in reversed(parts))
    return dx_key7_create(password)


# ---------- KiriKiri/CroixCrypt.cs ----------

_CROIX_CRC_TABLE = [
    0x00000000, 0x09073096, 0x120E612C, 0x1B0951BA, 0xFF6DC419, 0xF66AF48F, 0xED63A535, 0xE46495A3,
    0xFEDB8832, 0xF7DCB8A4, 0xECD5E91E, 0xE5D2D988, 0x01B64C2B, 0x08B17CBD, 0x13B82D07, 0x1ABF1D91,
    0xFDB71064, 0xF4B020F2, 0xEFB97148, 0xE6BE41DE, 0x02DAD47D, 0x0BDDE4EB, 0x10D4B551, 0x19D385C7,
    0x036C9856, 0x0A6BA8C0, 0x1162F97A, 0x1865C9EC, 0xFC015C4F, 0xF5066CD9, 0xEE0F3D63, 0xE7080DF5,
    0xFB6E20C8, 0xF269105E, 0xE96041E4, 0xE0677172, 0x0403E4D1, 0x0D04D447, 0x160D85FD, 0x1F0AB56B,
    0x05B5A8FA, 0x0CB2986C, 0x17BBC9D6, 0x1EBCF940, 0xFAD86CE3, 0xF3DF5C75, 0xE8D60DCF, 0xE1D13D59,
    0x06D930AC, 0x0FDE003A, 0x14D75180, 0x1DD06116, 0xF9B4F4B5, 0xF0B3C423, 0xEBBA9599, 0xE2BDA50F,
    0xF802B89E, 0xF1058808, 0xEA0CD9B2, 0xE30BE924, 0x076F7C87, 0x0E684C11, 0x15611DAB, 0x1C662D3D,
    0xF6DC4190, 0xFFDB7106, 0xE4D220BC, 0xEDD5102A, 0x09B18589, 0x00B6B51F, 0x1BBFE4A5, 0x12B8D433,
    0x0807C9A2, 0x0100F934, 0x1A09A88E, 0x130E9818, 0xF76A0DBB, 0xFE6D3D2D, 0xE5646C97, 0xEC635C01,
    0x0B6B51F4, 0x026C6162, 0x196530D8, 0x1062004E, 0xF40695ED, 0xFD01A57B, 0xE608F4C1, 0xEF0FC457,
    0xF5B0D9C6, 0xFCB7E950, 0xE7BEB8EA, 0xEEB9887C, 0x0ADD1DDF, 0x03DA2D49, 0x18D37CF3, 0x11D44C65,
    0x0DB26158, 0x04B551CE, 0x1FBC0074, 0x16BB30E2, 0xF2DFA541, 0xFBD895D7, 0xE0D1C46D, 0xE9D6F4FB,
    0xF369E96A, 0xFA6ED9FC, 0xE1678846, 0xE860B8D0, 0x0C042D73, 0x05031DE5, 0x1E0A4C5F, 0x170D7CC9,
    0xF005713C, 0xF90241AA, 0xE20B1010, 0xEB0C2086, 0x0F68B525, 0x066F85B3, 0x1D66D409, 0x1461E49F,
    0x0EDEF90E, 0x07D9C998, 0x1CD09822, 0x15D7A8B4, 0xF1B33D17, 0xF8B40D81, 0xE3BD5C3B, 0xEABA6CAD,
    0xEDB88320, 0xE4BFB3B6, 0xFFB6E20C, 0xF6B1D29A, 0x12D54739, 0x1BD277AF, 0x00DB2615, 0x09DC1683,
    0x13630B12, 0x1A643B84, 0x016D6A3E, 0x086A5AA8, 0xEC0ECF0B, 0xE509FF9D, 0xFE00AE27, 0xF7079EB1,
    0x100F9344, 0x1908A3D2, 0x0201F268, 0x0B06C2FE, 0xEF62575D, 0xE66567CB, 0xFD6C3671, 0xF46B06E7,
    0xEED41B76, 0xE7D32BE0, 0xFCDA7A5A, 0xF5DD4ACC, 0x11B9DF6F, 0x18BEEFF9, 0x03B7BE43, 0x0AB08ED5,
    0x16D6A3E8, 0x1FD1937E, 0x04D8C2C4, 0x0DDFF252, 0xE9BB67F1, 0xE0BC5767, 0xFBB506DD, 0xF2B2364B,
    0xE80D2BDA, 0xE10A1B4C, 0xFA034AF6, 0xF3047A60, 0x1760EFC3, 0x1E67DF55, 0x056E8EEF, 0x0C69BE79,
    0xEB61B38C, 0xE266831A, 0xF96FD2A0, 0xF068E236, 0x140C7795, 0x1D0B4703, 0x060216B9, 0x0F05262F,
    0x15BA3BBE, 0x1CBD0B28, 0x07B45A92, 0x0EB36A04, 0xEAD7FFA7, 0xE3D0CF31, 0xF8D99E8B, 0xF1DEAE1D,
    0x1B64C2B0, 0x1263F226, 0x096AA39C, 0x006D930A, 0xE40906A9, 0xED0E363F, 0xF6076785, 0xFF005713,
    0xE5BF4A82, 0xECB87A14, 0xF7B12BAE, 0xFEB61B38, 0x1AD28E9B, 0x13D5BE0D, 0x08DCEFB7, 0x01DBDF21,
    0xE6D3D2D4, 0xEFD4E242, 0xF4DDB3F8, 0xFDDA836E, 0x19BE16CD, 0x10B9265B, 0x0BB077E1, 0x02B74777,
    0x18085AE6, 0x110F6A70, 0x0A063BCA, 0x03010B5C, 0xE7659EFF, 0xEE62AE69, 0xF56BFFD3, 0xFC6CCF45,
    0xE00AE278, 0xE90DD2EE, 0xF2048354, 0xFB03B3C2, 0x1F672661, 0x166016F7, 0x0D69474D, 0x046E77DB,
    0x1ED16A4A, 0x17D65ADC, 0x0CDF0B66, 0x05D83BF0, 0xE1BCAE53, 0xE8BB9EC5, 0xF3B2CF7F, 0xFAB5FFE9,
    0x1DBDF21C, 0x14BAC28A, 0x0FB39330, 0x06B4A3A6, 0xE2D03605, 0xEBD70693, 0xF0DE5729, 0xF9D967BF,
    0xE3667A2E, 0xEA614AB8, 0xF1681B02, 0xF86F2B94, 0x1C0BBE37, 0x150C8EA1, 0x0E05DF1B, 0x0702EF8D,
]


class CroixCrypt:
    """CroixCrypt(KiriKiri):多层 XOR/加减流,密钥由 hash 派生。"""

    def __init__(self):
        # 生成 byte_10014F64(0x3D 字节)
        v160 = 0xA5665A5F061EC576
        crc = 0xE51804DAE70D133E
        v58 = _u32(v160 + crc)
        v59 = ((v160 + crc) >> 32) & 0x1FFFFFFF
        self.table = bytearray(0x3D)
        for i in range(0x3D):
            v61 = v58 & 0xFF
            self.table[i] = v61
            v58 = _u32((v59 << 24) | (v58 >> 8))
            v59 = ((v59 >> 8) | (v61 << 21)) & 0x1FFFFFFF
        self.table = bytes(self.table)
        # 计算初始密钥常量
        v16 = 0x6EDC44A8
        v17 = 0x139E
        v19 = 0x4B93
        for i in range(0x3D):
            v17 += self.table[i]
            v19 += v17
        v17 %= 0xFFEF
        v19 %= 0xFFEF
        v21 = v17 ^ (v19 << 16)
        self.v22 = self._scramble(v21)
        v25 = ~(((v16 & 0x78 | (v16 >> 14) & 0x3FF80) >> 3)
                | (v16 & 0xC000 | (v16 & 0x1F0000 | ((v16 & 7 | 2 * (v16 & 0xFFFFFF80)) << 13)) << 3) << 1)
        for i in range(0x3D):
            v25 = _CROIX_CRC_TABLE[(v25 ^ self.table[i]) & 0xFF] ^ (v25 >> 8)
        v25 = ~v25
        self.v25 = self._scramble(v25)
        self.sigdata_checksum = 0x6C04B9AB66EF2EF0

    @staticmethod
    def _scramble(v):
        v &= _U32_MASK
        return _u32(((v & 0xF | ((v & 0xFFFFFFF0) << 14)) << 3
                     | (v & 0x18000 | ((v & 0x1F00000 | ((v & 0xE0000 | (v >> 1) & 0x7F000000) >> 13)) >> 3)) >> 1))

    def decrypt(self, entry_hash, offset, data):
        out = bytearray(data)
        n = len(out)
        v29 = 0x5793CE00
        v71 = self.v22 ^ (v29 << 21)
        v75 = self.v25 ^ (v29 >> 11)
        v33 = (self.sigdata_checksum ^ 0x5793CE00 ^ v71 ^ (v75 << 32)) & _U64_MASK
        v55 = _u32(v33 >> 17)
        # 第一轮
        hash_val = _u32(entry_hash ^ v55 ^ 0x15C3F972)
        for i in range(n):
            shift = (int(offset) + i & 3) << 3
            v = out[i] ^ (hash_val >> shift)
            v = _u32(v - (0xE3AD9ACB >> shift))
            v ^= (offset >> ((int(offset) + i & 7) << 3)) & 0xFF
            v = _u32(v + (0xFECAB9F2 >> shift))
            out[i] = v & 0xFF
        # 第二轮
        hash_val = _u32(entry_hash ^ 0x27D3BCA1)
        for i in range(n):
            shift = (int(offset) + i & 3) << 3
            v = out[i] ^ (hash_val >> shift)
            v = _u32(v - (0xE3779ACB >> shift))
            v ^= (offset >> ((int(offset) + i & 7) << 3)) & 0xFF
            v = _u32(v + (0xFDCAB972 >> shift))
            out[i] = v & 0xFF
        # 密钥流表
        hash_val = entry_hash & 0x7FFFFFFF
        v83 = bytearray(0x1F)
        for i in range(0x1F):
            v83[i] = hash_val & 0xFF
            hash_val = _u32(v55 ^ (hash_val >> 8 | (hash_val & 0xFF) << 23))
        v58 = 0
        v59 = 0
        v84 = bytearray(0x3D)
        for i in range(0x3D):
            v61 = v58 & 0xFF
            v84[i] = v61
            v58 = _u32(v55 ^ ((v59 << 24) | (v58 >> 8)))
            v59 = _u32((v59 >> 8) | (v61 << 21))
        for i in range(n):
            pos = int(offset) + i
            out[i] ^= v83[pos % 0x1F]
            out[i] = (out[i] + (v55 ^ v84[pos % 0x3D] ^ self.table[pos % 0x3D])) & 0xFF
        return bytes(out)


# ---------- AZSys/ArcEncrypted.cs ----------

def az_decrypt(data, offset, key):
    """AzArchive.Decrypt:key * 0x9E370001 的旋转流。"""
    hash_val = _u64(key * 0x9E370001)
    if offset & 0x3F:
        hash_val = _rotl(hash_val, int(offset), 64)
    out = bytearray(data)
    for i in range(len(out)):
        out[i] ^= hash_val & 0xFF
        hash_val = _rotl(hash_val, 1, 64)
    return bytes(out)


class Isaac64Cipher:
    """ISAAC 64 位伪随机数生成器(ISAAC-64)。"""

    def __init__(self, seed):
        self.m_entropy = [0] * 0x100
        self.m_state = [0] * 0x100
        self.m_count = 0
        self.aa = self.bb = self.cc = 0
        self.a = self.b = self.c = self.d = self.e = self.f = self.g = self.h = 0
        # 熵初始化
        e32 = bytearray(0x800)
        struct.pack_into('<I', e32, 0, _u32(seed ^ 0x9E370001))
        for i in range(1, 0x200):
            prev = struct.unpack_from('<I', e32, (i - 1) * 4)[0]
            val = _u32(i - 0x61C88647 * (prev ^ (prev >> 30)))
            struct.pack_into('<I', e32, i * 4, val)
        self.m_entropy = list(struct.unpack('<256Q', e32))
        self._init()

    def _mix(self):
        self.a = _u64(self.a - self.e); self.f ^= self.h >> 9; self.h = _u64(self.h + self.a)
        self.b = _u64(self.b - self.f); self.g ^= self.a << 9; self.a = _u64(self.a + self.b)
        self.c = _u64(self.c - self.g); self.h ^= self.b >> 23; self.b = _u64(self.b + self.c)
        self.d = _u64(self.d - self.h); self.a ^= self.c << 15; self.c = _u64(self.c + self.d)
        self.e = _u64(self.e - self.a); self.b ^= self.d >> 14; self.d = _u64(self.d + self.e)
        self.f = _u64(self.f - self.b); self.c ^= self.e << 20; self.e = _u64(self.e + self.f)
        self.g = _u64(self.g - self.c); self.d ^= self.f >> 17; self.f = _u64(self.f + self.g)
        self.h = _u64(self.h - self.d); self.e ^= self.g << 14; self.g = _u64(self.g + self.h)

    def _init(self):
        self.aa = self.bb = self.cc = 0
        self.a = self.b = self.c = self.d = self.e = self.f = self.g = self.h = 0x9E3779B97F4A7C13
        for _ in range(4):
            self._mix()
        for i in range(0, 0x100, 8):
            self.a = _u64(self.a + self.m_entropy[i])
            self.b = _u64(self.b + self.m_entropy[i + 1])
            self.c = _u64(self.c + self.m_entropy[i + 2])
            self.d = _u64(self.d + self.m_entropy[i + 3])
            self.e = _u64(self.e + self.m_entropy[i + 4])
            self.f = _u64(self.f + self.m_entropy[i + 5])
            self.g = _u64(self.g + self.m_entropy[i + 6])
            self.h = _u64(self.h + self.m_entropy[i + 7])
            self._mix()
            self.m_state[i] = self.a
            self.m_state[i + 1] = self.b
            self.m_state[i + 2] = self.c
            self.m_state[i + 3] = self.d
            self.m_state[i + 4] = self.e
            self.m_state[i + 5] = self.f
            self.m_state[i + 6] = self.g
            self.m_state[i + 7] = self.h
        for i in range(0, 0x100, 8):
            self.a = _u64(self.a + self.m_state[i])
            self.b = _u64(self.b + self.m_state[i + 1])
            self.c = _u64(self.c + self.m_state[i + 2])
            self.d = _u64(self.d + self.m_state[i + 3])
            self.e = _u64(self.e + self.m_state[i + 4])
            self.f = _u64(self.f + self.m_state[i + 5])
            self.g = _u64(self.g + self.m_state[i + 6])
            self.h = _u64(self.h + self.m_state[i + 7])
            self._mix()
            self.m_state[i] = self.a
            self.m_state[i + 1] = self.b
            self.m_state[i + 2] = self.c
            self.m_state[i + 3] = self.d
            self.m_state[i + 4] = self.e
            self.m_state[i + 5] = self.f
            self.m_state[i + 6] = self.g
            self.m_state[i + 7] = self.h
        self._shuffle()
        self.m_count = 0x100

    def _rng_step(self, mix, m, m2, r):
        x = self.m_state[m]
        self.aa = _u64(mix + self.m_state[m2])
        m2 += 1
        y = _u64(self.m_state[(x >> 3) & 0xFF] + self.aa + self.bb)
        self.m_state[m] = y
        m += 1
        self.bb = _u64(self.m_state[(y >> 11) & 0xFF] + x)
        self.m_entropy[r] = self.bb
        r += 1
        return m, m2, r

    def _shuffle(self):
        m1 = 0
        r = 0
        self.bb = _u64(self.bb + (self.cc + 1))
        self.cc = _u64(self.cc + 1)
        m2 = 0x80
        while m1 < 0x80:
            m1, m2, r = self._rng_step(~(self.aa ^ (self.aa << 21)) & _U64_MASK, m1, m2, r)
            m1, m2, r = self._rng_step(self.aa ^ (self.aa >> 5), m1, m2, r)
            m1, m2, r = self._rng_step(self.aa ^ (self.aa << 12), m1, m2, r)
            m1, m2, r = self._rng_step(self.aa ^ (self.aa >> 33), m1, m2, r)
        m2 = 0
        while m2 < 0x80:
            m1, m2, r = self._rng_step(~(self.aa ^ (self.aa << 21)) & _U64_MASK, m1, m2, r)
            m1, m2, r = self._rng_step(self.aa ^ (self.aa >> 5), m1, m2, r)
            m1, m2, r = self._rng_step(self.aa ^ (self.aa << 12), m1, m2, r)
            m1, m2, r = self._rng_step(self.aa ^ (self.aa >> 33), m1, m2, r)

    def get_rand32(self):
        self.m_count -= 1
        if self.m_count == 0:
            self._shuffle()
            self.m_count = 0xFF
        num = self.m_entropy[self.m_count]
        return _u32(num ^ (num >> 32))


class AzIsaacEncryption:
    """AZ 系统 ISAAC 加密:ISAAC 生成 0x100 个 key,按 offset 旋转 XOR。"""

    def __init__(self, seed):
        isaac = Isaac64Cipher(seed)
        self.m_key = [isaac.get_rand32() for _ in range(0x100)]

    def decrypt(self, data, offset=0):
        out = bytearray(data)
        off = offset & 0xFFFF
        for i in range(len(out)):
            out[i] ^= (_rotl(self.m_key[off & 0xFF] ^ 0x1000193, off >> 8)) & 0xFF
            off = (off + 1) & 0xFFFF
        return bytes(out)
