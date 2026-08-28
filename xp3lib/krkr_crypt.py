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


# ---------- 解密器工厂 ----------

# 已实现的算法类型（用于 GUI 展示）
IMPLEMENTED = {
    'NoCrypt', 'HashCrypt', 'XorCrypt', 'HybridCrypt', 'FlyingShineCrypt',
    'YuzuCrypt', 'FateCrypt', 'MizukakeCrypt', 'NatsupochiCrypt',
    'PoringSoftCrypt', 'SourireCrypt', 'HaikuoCrypt', 'StripeCrypt',
    'ExaCrypt', 'DameganeCrypt', 'NephriteCrypt', 'AppliqueCrypt',
    'HibikiCrypt', 'FestivalCrypt', 'HighRunningCrypt', 'DieselmineCrypt',
    'CxEncryption',  # 在 cx.py 中实现
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
