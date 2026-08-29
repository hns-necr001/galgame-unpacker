# -*- coding: utf-8 -*-
"""
KiriKiri 各加密算法的 Python 移植（参考 GARbro morkt/GARbro）。
支持从 schemes.json 加载游戏方案并按类型分发解密。
"""
import json
import os

_U32_MASK = 0xFFFFFFFF


def _u32(x):
    return x & _U32_MASK


# ---------- 简单通用算法 ----------

class NoCrypt:
    def decrypt(self, entry_hash, offset, data):
        return data


class HashCrypt:
    """每个字节 XOR entry.Hash 低 8 位。"""
    def decrypt(self, entry_hash, offset, data):
        key = entry_hash & 0xFF
        return bytes(b ^ key for b in data)


class XorCrypt:
    def __init__(self, key=0):
        self.key = key & 0xFF

    def decrypt(self, entry_hash, offset, data):
        k = self.key
        return bytes(b ^ k for b in data)


class HybridCrypt:
    """每个字节 XOR (entry.Hash >> 5) 低 8 位。"""
    def decrypt(self, entry_hash, offset, data):
        key = (entry_hash >> 5) & 0xFF
        return bytes(b ^ key for b in data)


class FlyingShineCrypt:
    """FlyingShine 算法：key 和 shift 由 entry.Hash 派生。"""
    def _adjust(self, h):
        shift = h & 0xFF
        if shift == 0:
            shift = 0x0F
        key = (h >> 8) & 0xFF
        if key == 0:
            key = 0xF0
        return key, shift

    def decrypt(self, entry_hash, offset, data):
        key, shift = self._adjust(entry_hash)
        out = bytearray(data)
        for i in range(len(out)):
            k = key
            if (offset + i) & 1:
                k = (k << shift) & 0xFF | k >> (8 - shift)
            out[i] ^= k & 0xFF
        return bytes(out)


class YuzuCrypt:
    """柚子社 yuzu 加密（用于魔女夜宴等）。基于 entry.Hash 与固定参数。"""
    MASTER_KEY = 0x1DDB6E7A
    SECONDARY_KEY = 0xD0

    def decrypt(self, entry_hash, offset, data):
        adler = entry_hash & _U32_MASK
        adler_key = (adler ^ self.MASTER_KEY) & _U32_MASK
        xor_key = (adler_key >> 24 ^ adler_key >> 16 ^ adler_key >> 8 ^ adler_key) & 0xFF
        if xor_key == 0:
            xor_key = self.SECONDARY_KEY
        out = bytearray(data)
        if out:
            first_key = adler_key & 0xFF
            if first_key == 0:
                first_key = self.MASTER_KEY & 0xFF
            out[0] ^= first_key & 0xFF
        for i in range(1, len(out)):
            out[i] ^= xor_key
        return bytes(out)


class FateCrypt:
    """XOR 0x36，特殊偏移额外 XOR。"""
    def decrypt(self, entry_hash, offset, data):
        out = bytearray(data)
        for i in range(len(out)):
            v = out[i] ^ 0x36
            o = offset + i
            if o == 0x13:
                v ^= 1
            elif o == 0x2ea29:
                v ^= 3
            out[i] = v & 0xFF
        return bytes(out)


class MizukakeCrypt:
    """XOR 0xB6，offset 0x103 处 -1。"""
    def decrypt(self, entry_hash, offset, data):
        out = bytearray(data)
        n = len(out)
        if offset <= 0x103 and offset + n > 0x103:
            out[0x103 - offset] = (out[0x103 - offset] - 1) & 0xFF
        for i in range(n):
            out[i] ^= 0xB6
        return bytes(out)


class NatsupochiCrypt:
    """XOR (entry.Hash >> 3)。"""
    def decrypt(self, entry_hash, offset, data):
        k = (entry_hash >> 3) & 0xFF
        return bytes(b ^ k for b in data)


class PoringSoftCrypt:
    """XOR ~(entry.Hash + 1)。"""
    def decrypt(self, entry_hash, offset, data):
        k = (~(entry_hash + 1)) & 0xFF
        return bytes(b ^ k for b in data)


class SourireCrypt:
    """XOR (entry.Hash ^ 0xCD)。"""
    def decrypt(self, entry_hash, offset, data):
        k = (entry_hash ^ 0xCD) & 0xFF
        return bytes(b ^ k for b in data)


class HaikuoCrypt:
    """XOR (entry.Hash ^ entry.Hash>>8)。"""
    def decrypt(self, entry_hash, offset, data):
        k = (entry_hash ^ (entry_hash >> 8)) & 0xFF
        return bytes(b ^ k for b in data)


class StripeCrypt:
    def __init__(self, key=0):
        self.m_key = key & 0xFF

    def decrypt(self, entry_hash, offset, data):
        k = self.m_key
        return bytes(((b ^ k) + 1) & 0xFF for b in data)


class ExaCrypt:
    """XOR entry.Hash >> ((offset+i) % 5)。"""
    def decrypt(self, entry_hash, offset, data):
        out = bytearray(data)
        for i in range(len(out)):
            shift = (offset + i) % 5
            out[i] ^= (entry_hash >> shift) & 0xFF
        return bytes(out)


class DameganeCrypt:
    """offset 奇偶：奇数 XOR hash，偶数 XOR offset。"""
    def decrypt(self, entry_hash, offset, data):
        out = bytearray(data)
        for i in range(len(out)):
            o = offset + i
            if o & 1:
                out[i] ^= entry_hash & 0xFF
            else:
                out[i] ^= o & 0xFF
        return bytes(out)


class NephriteCrypt:
    """与 Damegane 相反。"""
    def decrypt(self, entry_hash, offset, data):
        out = bytearray(data)
        for i in range(len(out)):
            o = offset + i
            if o & 1:
                out[i] ^= o & 0xFF
            else:
                out[i] ^= entry_hash & 0xFF
        return bytes(out)


class AppliqueCrypt:
    """offset < 5 跳过，之后 XOR entry.Hash>>12。"""
    def decrypt(self, entry_hash, offset, data):
        out = bytearray(data)
        k = (entry_hash >> 12) & 0xFF
        for i in range(len(out)):
            if offset + i >= 5:
                out[i] ^= k
        return bytes(out)


class HibikiCrypt:
    def decrypt(self, entry_hash, offset, data):
        key1 = (entry_hash >> 5) & 0xFF
        key2 = (entry_hash >> 8) & 0xFF
        out = bytearray(data)
        for i in range(len(out)):
            o = offset + i
            if (o & 4) or o <= 0x64:
                out[i] ^= key1
            else:
                out[i] ^= key2
        return bytes(out)


class FestivalCrypt:
    """XOR ~(entry.Hash >> 7)。"""
    def decrypt(self, entry_hash, offset, data):
        k = (~(entry_hash >> 7)) & 0xFF
        return bytes(b ^ k for b in data)


class HighRunningCrypt:
    def decrypt(self, entry_hash, offset, data):
        k = entry_hash & 0xFF
        if k == 0:
            return data
        out = bytearray(data)
        for i in range(len(out)):
            if (offset + i) % k != 0:
                out[i] ^= k
        return bytes(out)


class DieselmineCrypt:
    def decrypt(self, entry_hash, offset, data):
        key = entry_hash & 0xFF
        out = bytearray(data)
        for i in range(len(out)):
            o = offset + i
            if o < 123:
                out[i] ^= (21 * key) & 0xFF
            elif o < 246:
                out[i] = (out[i] + ((-32 * key) & 0xFF)) & 0xFF
            elif o < 369:
                out[i] ^= (key << 1) & 0xFF
            elif o < 492:
                out[i] = (out[i] + key) & 0xFF
            elif o < 615:
                out[i] ^= (key >> 1) & 0xFF
            else:
                out[i] = (out[i] - key) & 0xFF
        return bytes(out)


# ---------- 追加移植:参考 GARbro CryptAlgorithms.cs / ChainReactionCrypt.cs ----------

class SeitenCrypt:
    """SeitenCrypt:每个字节按 key = hash ^ offset 的位标志做变换。"""
    def decrypt(self, entry_hash, offset, data):
        out = bytearray(data)
        off = offset
        for i in range(len(out)):
            key = (entry_hash ^ off) & 0xFFFFFFFF
            v = out[i]
            if key & 2:
                shift = int(key) & 0x18
                ebx = key >> shift
                shift &= 8
                v ^= (ebx | (key >> shift)) & 0xFF
            if key & 4:
                v = (v + key) & 0xFF
            if key & 8:
                shift = int(key) & 0x10
                v = (v - (key >> shift)) & 0xFF
            out[i] = v & 0xFF
            off += 1
        return bytes(out)

    def encrypt(self, entry_hash, offset, data):
        """逆操作(仅用于自测)。"""
        out = bytearray(data)
        off = offset
        for i in range(len(out)):
            key = (entry_hash ^ off) & 0xFFFFFFFF
            v = out[i]
            if key & 8:
                shift = int(key) & 0x10
                v = (v + (key >> shift)) & 0xFF
            if key & 4:
                v = (v - key) & 0xFF
            if key & 2:
                shift = int(key) & 0x18
                ebx = key >> shift
                shift &= 8
                v ^= (ebx | (key >> shift)) & 0xFF
            out[i] = v & 0xFF
            off += 1
        return bytes(out)


class OkibaCrypt:
    """OkibaCrypt:前 0x65 字节 XOR hash>>4,之后按重排的 key 循环。"""
    def decrypt(self, entry_hash, offset, data):
        out = bytearray(data)
        n = len(out)
        i = 0
        if offset < 0x65:
            key = (entry_hash >> 4) & 0xFF
            limit = min(n, int(0x65 - offset))
            for j in range(limit):
                out[j] ^= key
            i = limit
        if i < n:
            off = (offset + i) - 0x65
            key = entry_hash & 0xFFFFFFFF
            key = (((key & 0xff0000) << 8) | ((key & 0xff000000) >> 8)
                   | ((key & 0xff00) >> 8) | ((key & 0xff) << 8)) & 0xFFFFFFFF
            while i < n:
                out[i] ^= (key >> (8 * (int(off) & 3))) & 0xFF
                off += 1
                i += 1
        return bytes(out)


# AlteredPinkCrypt 的 256 字节 KeyTable(来自 GARbro)
_ALTERED_PINK_KEY = bytes([
    0x43, 0xF8, 0xAD, 0x08, 0xDF, 0xB7, 0x26, 0x44, 0xF0, 0xD9, 0xE9, 0x24, 0x1A, 0xC1, 0xEE, 0xB4,
    0x11, 0x4B, 0xE4, 0xAF, 0x01, 0x5B, 0xF0, 0xAB, 0x6A, 0x70, 0x78, 0x84, 0xB0, 0x78, 0x4F, 0xED,
    0x39, 0x52, 0x69, 0xAF, 0xC4, 0x92, 0x2A, 0x21, 0xDE, 0xDC, 0x6E, 0x63, 0x9D, 0x9B, 0x63, 0xE1,
    0xB1, 0x94, 0x40, 0x6E, 0x3A, 0x52, 0x5A, 0x28, 0x08, 0x4D, 0xFB, 0x22, 0x18, 0xEB, 0xBA, 0x98,
    0x49, 0x77, 0xBF, 0xAA, 0x43, 0x75, 0xF5, 0xD3, 0x83, 0x71, 0x58, 0xA4, 0xAF, 0x1B, 0x53, 0x99,
    0x8A, 0x27, 0x5B, 0xC2, 0x7F, 0x7A, 0xCD, 0x8D, 0x33, 0x59, 0xEB, 0xA6, 0xFA, 0x7C, 0x00, 0x19,
    0xC4, 0xAA, 0x24, 0xF8, 0x84, 0xCD, 0xF7, 0x20, 0x4B, 0xAB, 0xF1, 0xD5, 0x01, 0x6F, 0x7C, 0x91,
    0x08, 0x7D, 0x8D, 0x89, 0x7C, 0x71, 0x65, 0x99, 0x9B, 0x6F, 0x3A, 0x1C, 0x49, 0xE3, 0xAF, 0x1F,
    0xC6, 0xA5, 0x79, 0xFE, 0xAE, 0xA1, 0xCA, 0x59, 0x3C, 0xEE, 0xC1, 0x02, 0xBD, 0x2B, 0x8E, 0xC5,
    0x7D, 0x38, 0x80, 0x8F, 0x72, 0xF3, 0x86, 0x5D, 0xF4, 0x20, 0x0A, 0x5B, 0xA0, 0xE3, 0x85, 0xB5,
    0x67, 0x43, 0x96, 0xBB, 0x75, 0x86, 0x8D, 0x7E, 0x7E, 0xE6, 0xAA, 0x18, 0x57, 0xC4, 0xAA, 0x87,
    0xDC, 0x74, 0x05, 0xAA, 0xBD, 0x5E, 0x4F, 0xA9, 0xB5, 0x5E, 0xC5, 0xE8, 0x11, 0x6D, 0x68, 0x89,
    0x17, 0x7C, 0x10, 0x05, 0xA2, 0xBA, 0x43, 0x01, 0xD6, 0xFD, 0x26, 0x19, 0x57, 0xFA, 0x4D, 0x01,
    0xB0, 0xED, 0x3A, 0x55, 0xEB, 0x65, 0x8E, 0xD1, 0x58, 0x27, 0xAD, 0xA1, 0x5E, 0x57, 0x3F, 0xA0,
    0xEF, 0x59, 0x3E, 0xA4, 0xEB, 0x12, 0x15, 0x60, 0xBE, 0x95, 0x61, 0x0B, 0x98, 0xF5, 0xF4, 0x12,
    0x1C, 0xD8, 0x62, 0x3F, 0xFD, 0xCF, 0x01, 0x3A, 0xE7, 0xC2, 0x19, 0x38, 0x6C, 0xC3, 0x90, 0x3E,
])


class AlteredPinkCrypt:
    """AlteredPinkCrypt:每字节 XOR KeyTable[offset & 0xFF]。"""
    def decrypt(self, entry_hash, offset, data):
        key = _ALTERED_PINK_KEY
        start = int(offset) & 0xFF
        n = len(data)
        out = bytearray(n)
        for i in range(n):
            out[i] = data[i] ^ key[(start + i) & 0xFF]
        return bytes(out)


class AkabeiCrypt:
    """AkabeiCrypt:由 hash 与 seed 生成 32 字节密钥流循环 XOR。"""
    def __init__(self, seed=0):
        self.seed = seed & 0xFFFFFFFF

    def _get_key(self, hash_val):
        h = (hash_val ^ self.seed) & 0x7FFFFFFF
        h = ((h << 31) | h) & 0xFFFFFFFF
        key = bytearray(0x20)
        for i in range(0x20):
            key[i] = h & 0xFF
            h = ((h & 0xFFFFFFFE) << 23 | h >> 8) & 0xFFFFFFFF
        return bytes(key)

    def decrypt(self, entry_hash, offset, data):
        key = self._get_key(entry_hash)
        out = bytearray(data)
        key_pos = int(offset)
        for i in range(len(out)):
            out[i] ^= key[key_pos & 0x1F]
            key_pos += 1
        return bytes(out)


class MadoCrypt(AkabeiCrypt):
    """MadoCrypt:AkabeiCrypt 变体,密钥流循环长度 0x1F。"""
    def decrypt(self, entry_hash, offset, data):
        key = self._get_key(entry_hash)
        out = bytearray(data)
        key_pos = int(offset)
        for i in range(len(out)):
            out[i] ^= key[key_pos % 0x1F]
            key_pos += 1
        return bytes(out)


class SmileCrypt:
    """SmileCrypt:hash 与 key_xor 混合出主 key,首字节额外处理。"""
    def __init__(self, key_xor=0, first_xor=0, zero_xor=0):
        self.key_xor = key_xor & 0xFFFFFFFF
        self.first_xor = first_xor & 0xFF
        self.zero_xor = zero_xor & 0xFF

    def decrypt(self, entry_hash, offset, data):
        out = bytearray(data)
        n = len(out)
        hash_val = (entry_hash ^ self.key_xor) & 0xFFFFFFFF
        key = (hash_val ^ (hash_val >> 8) ^ (hash_val >> 16) ^ (hash_val >> 24)) & 0xFF
        if key == 0:
            key = self.zero_xor
        if offset == 0 and n > 0:
            h0 = hash_val & 0xFF
            if h0 == 0:
                h0 = self.first_xor
            out[0] ^= h0
        for i in range(n):
            out[i] ^= key
        return bytes(out)


class KissCrypt:
    """KissCrypt:每 0x10 字节跳变,key = hash ^ (hash>>19) ^ 0x4A9EEFF0。"""
    def decrypt(self, entry_hash, offset, data):
        key = (entry_hash ^ (entry_hash >> 19) ^ 0x4A9EEFF0) & 0xFFFFFFFF
        out = bytearray(data)
        i = 0
        off = offset
        while (off + i) & 0xF:
            i += 1
        while i < len(out):
            out[i] ^= (key ^ (off + i)) & 0xFF
            i += 0x10
        return bytes(out)


class PuCaCrypt:
    """PuCaCrypt:可用 HashTable/KeyTable 查表,否则按 hash 生成 0x400 密钥表。"""
    def __init__(self, hash_table=None, key_table=None):
        self.hash_table = hash_table
        self.key_table = key_table

    def _build_key_table(self, hash_val):
        ht = bytearray(32)
        h = hash_val & 0xFFFFFFFF
        for k in range(0, 32, 4):
            if h & 1:
                h |= 0x80000000
            else:
                h &= 0x7FFFFFFF
            h &= 0xFFFFFFFF
            ht[k] = h & 0xFF
            ht[k + 1] = (h >> 8) & 0xFF
            ht[k + 2] = (h >> 16) & 0xFF
            ht[k + 3] = (h >> 24) & 0xFF
            h >>= 1
        table = bytearray(0x400)
        for l in range(32):
            for m in range(32):
                table[32 * l + m] = (~ht[l] ^ ht[m]) & 0xFF
        return bytes(table)

    def decrypt(self, entry_hash, offset, data):
        out = bytearray(data)
        n = len(out)
        if self.hash_table is not None and self.key_table is not None:
            try:
                i = self.hash_table.index(entry_hash & 0xFFFFFFFF)
            except ValueError:
                i = -1
            if i != -1:
                k = self.key_table[i] & 0xFF
                for j in range(n):
                    out[j] ^= k
                return bytes(out)
        table = self._build_key_table(entry_hash)
        pos = int(offset)
        for j in range(n):
            out[j] ^= table[(pos + j) & 0x3FF]
        return bytes(out)


class RhapsodyCrypt:
    """RhapsodyCrypt:12 字节密钥流循环(hash + 固定常量)。"""
    def decrypt(self, entry_hash, offset, data):
        key = bytearray(12)
        h = entry_hash & 0xFFFFFFFF
        key[0] = h & 0xFF
        key[1] = (h >> 8) & 0xFF
        key[2] = (h >> 16) & 0xFF
        key[3] = (h >> 24) & 0xFF
        key[4] = 0xB2
        key[5] = 0xA9
        key[6] = 0x1D
        key[7] = 0x6E
        key[8] = 0x00
        key[9] = 0xC8
        key[10] = 0x40
        key[11] = 0x00
        out = bytearray(data)
        k = int(offset) % 12
        for i in range(len(out)):
            out[i] ^= key[k]
            k += 1
            if k == 12:
                k = 0
        return bytes(out)


def _count_set_bits(x):
    x = (x & 0x55) + ((x >> 1) & 0x55)
    x = (x & 0x33) + ((x >> 2) & 0x33)
    return ((x & 0xF) + ((x >> 4) & 0xF)) & 0xF


def _rot_left8(v, n):
    n &= 7
    return ((v << n) | (v >> (8 - n))) & 0xFF


class PinPointCrypt:
    """PinPointCrypt:每字节按置位位数左旋。"""
    def decrypt(self, entry_hash, offset, data):
        out = bytearray(data)
        for i in range(len(out)):
            v = out[i]
            bits = _count_set_bits(v)
            if bits > 0:
                out[i] = _rot_left8(v, bits)
        return bytes(out)


class SmxCrypt:
    """SmxCrypt:前 101 字节 XOR hash>>KeySeq[0],之后按 Mask 循环密钥流。"""
    def __init__(self, mask=5, key_seq=None):
        self.mask = mask
        self.key_seq = list(key_seq) if key_seq else [0]

    def decrypt(self, entry_hash, offset, data):
        start_key = (entry_hash >> self.key_seq[0]) & 0xFF
        key = [(entry_hash >> s) & 0xFF for s in self.key_seq[1:]]
        out = bytearray(data)
        for i in range(len(out)):
            pos = offset + i
            if pos <= 100:
                out[i] ^= start_key
            else:
                out[i] ^= key[int(pos) & self.mask]
        return bytes(out)


class TokidokiCrypt:
    """TokidokiCrypt:按扩展名确定 key 与加密长度(简化:固定 0x100)。"""
    def __init__(self, ext=None):
        self.ext = (ext or '').lower()

    def _get_params(self, entry_hash):
        ext = self.ext
        if ext:
            eb = (ext[:4] + '\x00\x00\x00\x00')[:4].encode('cp932', errors='ignore')
            key = ~int.from_bytes(eb, 'little') & 0xFFFFFFFF
            return key, 0x100
        return 0xFFFFFFFF, 0x100

    def decrypt(self, entry_hash, offset, data):
        key, limit = self._get_params(entry_hash)
        out = bytearray(data)
        off = offset
        n = len(out)
        for i in range(n):
            if off >= limit:
                break
            out[i] ^= (key >> ((int(off) & 3) << 3)) & 0xFF
            off += 1
        return bytes(out)


class ChainReactionCrypt:
    """ChainReactionCrypt:前 limit 字节 XOR (offset ^ hash 分片)。默认 limit=0x200。"""
    def __init__(self, limit=0x200):
        self.limit = limit

    def decrypt(self, entry_hash, offset, data):
        limit = self.limit
        out = bytearray(data)
        if offset >= limit:
            return bytes(out)
        count = min(len(out), int(limit - offset))
        key = entry_hash & 0xFFFFFFFF
        for i in range(count):
            pos = int(offset) + i
            out[i] ^= (pos ^ (key >> ((pos & 3) << 3))) & 0xFF
        return bytes(out)


class HachukanoCrypt(ChainReactionCrypt):
    """HachukanoCrypt:阈值映射 0/0x100/0x200/全部(简化:默认 0x200)。"""
    def __init__(self, limit=0x200):
        self.limit = limit


class ChocolatCrypt(ChainReactionCrypt):
    """ChocolatCrypt:阈值映射 0/0x100/全部(简化:默认 0x100)。"""
    def __init__(self, limit=0x100):
        self.limit = limit


class XanaduCrypt:
    """XanaduCrypt:key = hash ^ ~0x03020100,带 extra 进位。"""
    def __init__(self, limit=0x100):
        self.limit = limit

    def decrypt(self, entry_hash, offset, data):
        limit = self.limit
        out = bytearray(data)
        if offset >= limit:
            return bytes(out)
        count = min(len(out), int(limit - offset))
        key = (entry_hash ^ ~0x03020100) & 0xFFFFFFFF
        extra = 0
        for i in range(count):
            pos = int(offset) + i
            if (pos & 0xFF) == 0:
                extra = 0
            elif (pos & 3) == 0:
                extra += 4
            out[i] ^= ((key >> ((pos & 3) << 3)) ^ extra) & 0xFF
        return bytes(out)


class SisMikoCrypt:
    """SisMikoCrypt:key = ~RotR(hash,16),前 limit 字节循环 XOR。"""
    def __init__(self, limit=0x100):
        self.limit = limit

    def decrypt(self, entry_hash, offset, data):
        limit = self.limit
        out = bytearray(data)
        if offset >= limit:
            return bytes(out)
        count = min(len(out), int(limit - offset))
        h = entry_hash & 0xFFFFFFFF
        ror = ((h >> 16) | (h << 16)) & 0xFFFFFFFF
        key = (~ror) & 0xFFFFFFFF
        for i in range(count):
            pos = int(offset) + i
            out[i] ^= (key >> ((pos & 3) << 3)) & 0xFF
        return bytes(out)


# ---------- 解密器工厂 ----------

# 已实现的算法类型（用于 GUI 展示）
IMPLEMENTED = {
    'NoCrypt', 'HashCrypt', 'XorCrypt', 'HybridCrypt', 'FlyingShineCrypt',
    'YuzuCrypt', 'FateCrypt', 'MizukakeCrypt', 'NatsupochiCrypt',
    'PoringSoftCrypt', 'SourireCrypt', 'HaikuoCrypt', 'StripeCrypt',
    'ExaCrypt', 'DameganeCrypt', 'NephriteCrypt', 'AppliqueCrypt',
    'HibikiCrypt', 'FestivalCrypt', 'HighRunningCrypt', 'DieselmineCrypt',
    'CxEncryption',  # 在 cx.py 中实现
    # ---- 追加移植(GARbro CryptAlgorithms.cs / ChainReactionCrypt.cs)----
    'SeitenCrypt', 'OkibaCrypt', 'AlteredPinkCrypt', 'AkabeiCrypt',
    'MadoCrypt', 'SmileCrypt', 'KissCrypt', 'PuCaCrypt', 'RhapsodyCrypt',
    'PinPointCrypt', 'SmxCrypt', 'TokidokiCrypt', 'ChainReactionCrypt',
    'HachukanoCrypt', 'ChocolatCrypt', 'XanaduCrypt', 'SisMikoCrypt',
}


def build_decoder(alg_type, fields):
    """根据算法类型和字段构造解密器。"""
    if alg_type == 'NoCrypt':
        return NoCrypt()
    if alg_type == 'HashCrypt':
        return HashCrypt()
    if alg_type == 'XorCrypt':
        key = fields.get('m_key', 0)
        if key is None:
            key = 0
        return XorCrypt(key)
    if alg_type == 'HybridCrypt':
        return HybridCrypt()
    if alg_type == 'FlyingShineCrypt':
        return FlyingShineCrypt()
    if alg_type == 'YuzuCrypt':
        return YuzuCrypt()
    if alg_type == 'FateCrypt':
        return FateCrypt()
    if alg_type == 'MizukakeCrypt':
        return MizukakeCrypt()
    if alg_type == 'NatsupochiCrypt':
        return NatsupochiCrypt()
    if alg_type == 'PoringSoftCrypt':
        return PoringSoftCrypt()
    if alg_type == 'SourireCrypt':
        return SourireCrypt()
    if alg_type == 'HaikuoCrypt':
        return HaikuoCrypt()
    if alg_type == 'StripeCrypt':
        return StripeCrypt(fields.get('m_key', 0) or 0)
    if alg_type == 'ExaCrypt':
        return ExaCrypt()
    if alg_type == 'DameganeCrypt':
        return DameganeCrypt()
    if alg_type == 'NephriteCrypt':
        return NephriteCrypt()
    if alg_type == 'AppliqueCrypt':
        return AppliqueCrypt()
    if alg_type == 'HibikiCrypt':
        return HibikiCrypt()
    if alg_type == 'FestivalCrypt':
        return FestivalCrypt()
    if alg_type == 'HighRunningCrypt':
        return HighRunningCrypt()
    if alg_type == 'DieselmineCrypt':
        return DieselmineCrypt()
    # ---- 追加移植算法 ----
    if alg_type == 'SeitenCrypt':
        return SeitenCrypt()
    if alg_type == 'OkibaCrypt':
        return OkibaCrypt()
    if alg_type == 'AlteredPinkCrypt':
        return AlteredPinkCrypt()
    if alg_type == 'AkabeiCrypt':
        return AkabeiCrypt(fields.get('m_seed', 0) or 0)
    if alg_type == 'MadoCrypt':
        return MadoCrypt(fields.get('m_seed', 0) or 0)
    if alg_type == 'SmileCrypt':
        return SmileCrypt(fields.get('m_key_xor', 0) or 0,
                          fields.get('m_first_xor', 0) or 0,
                          fields.get('m_zero_xor', 0) or 0)
    if alg_type == 'KissCrypt':
        return KissCrypt()
    if alg_type == 'PuCaCrypt':
        return PuCaCrypt(fields.get('HashTable'), fields.get('KeyTable'))
    if alg_type == 'RhapsodyCrypt':
        return RhapsodyCrypt()
    if alg_type == 'PinPointCrypt':
        return PinPointCrypt()
    if alg_type == 'SmxCrypt':
        return SmxCrypt(fields.get('Mask', 5) or 5, fields.get('KeySeq') or [0])
    if alg_type == 'TokidokiCrypt':
        return TokidokiCrypt()
    if alg_type == 'ChainReactionCrypt':
        return ChainReactionCrypt()
    if alg_type == 'HachukanoCrypt':
        return HachukanoCrypt()
    if alg_type == 'ChocolatCrypt':
        return ChocolatCrypt()
    if alg_type == 'XanaduCrypt':
        return XanaduCrypt()
    if alg_type == 'SisMikoCrypt':
        return SisMikoCrypt()
    # 其他算法尚未实现
    return None


class KrkrCrypto:
    """按游戏方案加载解密器。"""

    def __init__(self, schemes_path=None):
        if schemes_path is None:
            schemes_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schemes.json')
        with open(schemes_path, encoding='utf-8') as f:
            self.schemes = json.load(f)
        self._cache = {}

    def get_scheme(self, game_name):
        return self.schemes.get(game_name)

    def get_decoder(self, game_name):
        if game_name in self._cache:
            return self._cache[game_name]
        scheme = self.schemes.get(game_name)
        if scheme is None:
            return None
        decoder = build_decoder(scheme['type'], scheme.get('fields', {}))
        self._cache[game_name] = decoder
        return decoder
