# -*- coding: utf-8 -*-
"""
KiriKiri KrkrZ Hxv4 加密的 Python 移植(零依赖)。
参考:devseed 的 krkr_xp3_hxv4.py / krkr_hxcrypt.py、GARbro HxCrypt.cs。
- 索引区:ChaCha20(8 字节 nonce)流密码解密
- 内容区:Hx(Cx 变体随机数)生成 span key 解密
注意:Hxv4 的 key/nonce/filterkey 必须在游戏运行时用
KrkrExtract 的 krkr_hxv4_dumpkey.js 从内存 dump,无法静态获取。
"""

import io
import struct
import zlib

_U32_MASK = 0xFFFFFFFF
_U64_MASK = 0xFFFFFFFFFFFFFFFF


def _u32(x):
    return x & _U32_MASK


def _rotl(x, n, bits=32):
    n &= bits - 1
    return ((x << n) | (x >> (bits - n))) & ((1 << bits) - 1)


def _rotr(x, n, bits=32):
    return _rotl(x, -n % bits, bits)


# ---------- ChaCha20(8 字节 nonce 变体,与 pycryptodome 一致) ----------

_CHACHA_CONST = (0x61707865, 0x3320646e, 0x79622d32, 0x6b206574)


def _chacha_block(key, counter, nonce):
    """生成 64 字节 keystream block。key=32B, nonce=8B, counter=32 位。"""
    k = list(struct.unpack('<8I', key))
    n = list(struct.unpack('<2I', nonce))
    state = list(_CHACHA_CONST) + k + [counter & _U32_MASK, 0] + n
    work = state[:]

    def qr(a, b, c, d):
        work[a] = _u32(work[a] + work[b])
        work[d] = _rotl(work[d] ^ work[a], 16)
        work[c] = _u32(work[c] + work[d])
        work[b] = _rotl(work[b] ^ work[c], 12)
        work[a] = _u32(work[a] + work[b])
        work[d] = _rotl(work[d] ^ work[a], 8)
        work[c] = _u32(work[c] + work[d])
        work[b] = _rotl(work[b] ^ work[c], 7)

    for _ in range(10):
        qr(0, 4, 8, 12)
        qr(1, 5, 9, 13)
        qr(2, 6, 10, 14)
        qr(3, 7, 11, 15)
        qr(0, 5, 10, 15)
        qr(1, 6, 11, 12)
        qr(2, 7, 8, 13)
        qr(3, 4, 9, 14)
    out = bytearray()
    for i in range(16):
        out += struct.pack('<I', _u32(work[i] + state[i]))
    return bytes(out)


def chacha20_xor(data, key, nonce, counter=0):
    """用 ChaCha20 流解密/加密 data(异或流)。"""
    out = bytearray()
    ctr = counter & _U32_MASK
    pos = 0
    n = len(data)
    while pos < n:
        block = _chacha_block(key, ctr, nonce)
        chunk = block[:n - pos]
        for i in range(len(chunk)):
            out.append(data[pos + i] ^ chunk[i])
        pos += len(chunk)
        ctr = _u32(ctr + 1)
    return bytes(out)


# ---------- Hx 加密(KrkrZ 内容解密) ----------

class HxSplittableRandom:
    def __init__(self, seed):
        self.m_seed = seed & _U64_MASK

    def next(self):
        self.m_seed = (self.m_seed + 0x9e3779b97f4a7c15) & _U64_MASK
        z = self.m_seed
        z ^= z >> 30
        z = (z * 0xbf58476d1ce4e5b9) & _U64_MASK
        z ^= z >> 27
        z = (z * 0x94d049bb133111eb) & _U64_MASK
        z ^= z >> 31
        return z


class HxProgram:
    """Hx 的字节码执行器与随机数生成(64 位状态)。"""

    def __init__(self, seed, control_block, random_method):
        self.m_code = []
        self.m_length = 0
        self.m_control_block = control_block
        self.m_random_method = random_method
        self.m_seed0 = 0
        self.m_seed1 = 0
        # 与 Cx 相同的字节码枚举
        from cx import (NOP, RETN, MOV_EDI_ARG, PUSH_EBX, POP_EBX, PUSH_ECX,
                        POP_ECX, MOV_EAX_EBX, MOV_EBX_EAX, MOV_ECX_EBX,
                        MOV_EAX_INDIRECT, MOV_EAX_EDI, ADD_EAX_EBX, SUB_EAX_EBX,
                        IMUL_EAX_EBX, AND_ECX_0F, SHR_EBX_1, SHL_EAX_1,
                        SHR_EAX_CL, SHL_EAX_CL, OR_EAX_EBX, NOT_EAX, NEG_EAX,
                        DEC_EAX, INC_EAX, IMMED, MOV_EAX_IMMED, AND_EBX_IMMED,
                        AND_EAX_IMMED, XOR_EAX_IMMED, ADD_EAX_IMMED,
                        SUB_EAX_IMMED)
        self._BC = dict(
            NOP=NOP, RETN=RETN, MOV_EDI_ARG=MOV_EDI_ARG, PUSH_EBX=PUSH_EBX,
            POP_EBX=POP_EBX, PUSH_ECX=PUSH_ECX, POP_ECX=POP_ECX,
            MOV_EAX_EBX=MOV_EAX_EBX, MOV_EBX_EAX=MOV_EBX_EAX,
            MOV_ECX_EBX=MOV_ECX_EBX, MOV_EAX_INDIRECT=MOV_EAX_INDIRECT,
            MOV_EAX_EDI=MOV_EAX_EDI, ADD_EAX_EBX=ADD_EAX_EBX,
            SUB_EAX_EBX=SUB_EAX_EBX, IMUL_EAX_EBX=IMUL_EAX_EBX,
            AND_ECX_0F=AND_ECX_0F, SHR_EBX_1=SHR_EBX_1, SHL_EAX_1=SHL_EAX_1,
            SHR_EAX_CL=SHR_EAX_CL, SHL_EAX_CL=SHL_EAX_CL, OR_EAX_EBX=OR_EAX_EBX,
            NOT_EAX=NOT_EAX, NEG_EAX=NEG_EAX, DEC_EAX=DEC_EAX, INC_EAX=INC_EAX,
            IMMED=IMMED, MOV_EAX_IMMED=MOV_EAX_IMMED,
            AND_EBX_IMMED=AND_EBX_IMMED, AND_EAX_IMMED=AND_EAX_IMMED,
            XOR_EAX_IMMED=XOR_EAX_IMMED, ADD_EAX_IMMED=ADD_EAX_IMMED,
            SUB_EAX_IMMED=SUB_EAX_IMMED)
        s = seed & _U32_MASK
        s = s | ((~s & _U32_MASK) << 32)
        r = HxSplittableRandom(s)
        self.m_seed0 = r.next() & _U64_MASK
        self.m_seed1 = r.next() & _U64_MASK
        self.m_prolog_order = None
        self.m_odd_branch_order = None
        self.m_even_branch_order = None

    def set_orders(self, prolog, odd, even):
        self.m_prolog_order = prolog
        self.m_odd_branch_order = odd
        self.m_even_branch_order = even

    # ---------- RNG(对照 YuriSizuku krkr_hxcrypt.py,已实测) ----------
    def _get_old_random(self):
        a0 = self.m_seed0
        a1 = self.m_seed1
        a_lo = a0 & _U32_MASK
        a_hi = (a0 >> 32) & _U32_MASK
        b_lo = a1 & _U32_MASK
        b_hi = (a1 >> 32) & _U32_MASK
        c_lo = a_hi ^ b_hi
        c_hi = a_lo ^ b_lo
        e_lo = c_hi
        e_hi = c_lo
        t = ((c_hi << 21) & _U64_MASK) ^ (a0 >> 15) ^ c_hi
        self.m_seed0 = (self.m_seed0 & 0xFFFFFFFF00000000) | (t & _U32_MASK)
        t = (a_hi >> 15) | ((a_lo << 17) & _U64_MASK)
        t ^= ((e_hi << 32) | e_lo) >> 11
        t ^= c_lo
        self.m_seed0 = ((t & _U32_MASK) << 32) | (self.m_seed0 & _U32_MASK)
        e64 = (e_hi << 32) | e_lo
        c64 = (c_hi << 32) | c_lo
        self.m_seed1 = ((((e64 >> 4) & _U32_MASK) << 32) | ((c64 >> 4) & _U32_MASK))
        d64 = (a0 + a1) & _U64_MASK
        t = ((d64 << 17) & _U64_MASK) | (((d64 >> 32) & _U32_MASK) >> 15)
        t = (t + a0) & _U64_MASK
        return t

    def _get_new_random(self):
        a0 = self.m_seed0
        a1 = self.m_seed1
        a_lo = a0 & _U32_MASK
        a_hi = (a0 >> 32) & _U32_MASK
        b_lo = a1 & _U32_MASK
        b_hi = (a1 >> 32) & _U32_MASK
        c_lo = a_lo ^ b_lo
        c_hi = a_hi ^ b_hi
        t = ((a_lo << 24) & _U64_MASK) | (a_hi >> 8)
        t ^= (c_lo << 16) & _U64_MASK
        t ^= c_lo
        self.m_seed0 = (self.m_seed0 & 0xFFFFFFFF00000000) | (t & _U32_MASK)
        c64 = (c_hi << 32) | c_lo
        t = (c64 >> 16) ^ (a0 >> 8) ^ c_hi  # 注意用旧 a0,不能用更新后的 seed0
        self.m_seed0 = ((t & _U32_MASK) << 32) | (self.m_seed0 & _U32_MASK)
        t = (c_hi >> 27) | ((c_lo << 5) & _U64_MASK)
        self.m_seed1 = (self.m_seed1 & 0xFFFFFFFF00000000) | (t & _U32_MASK)
        self.m_seed1 = ((self.m_seed1 & _U32_MASK) << 32) | ((c64 >> 27) & _U32_MASK)
        d64 = (5 * a0) & _U64_MASK
        t = (((d64 >> 32) & _U32_MASK) >> 25) | ((d64 << 7) & _U64_MASK)
        t = (t * 9) & _U64_MASK
        return t

    def get_random(self):
        if self.m_random_method == 0:
            return self._get_old_random() & _U32_MASK
        return self._get_new_random() & _U32_MASK

    # ---------- 字节码 ----------
    def clear(self):
        self.m_length = 0
        self.m_code = []

    def emit_nop(self, count):
        if self.m_length + count > 0x80:
            return False
        self.m_length += count
        return True

    def emit(self, code, length=1):
        if self.m_length + length > 0x80:
            return False
        self.m_length += length
        self.m_code.append(code)
        return True

    def emit_uint32(self, x):
        if self.m_length + 4 > 0x80:
            return False
        self.m_length += 4
        self.m_code.append(_u32(x))
        return True

    def emit_random(self):
        return self.emit_uint32(self.get_random())

    def execute(self, hash_val):
        eax = ebx = ecx = edi = 0
        stack = []
        immed = 0
        i = 0
        code = self.m_code
        BC = self._BC
        while i < len(code):
            bytecode = code[i]
            if bytecode & BC['IMMED'] == BC['IMMED']:
                i += 1
                if i >= len(code):
                    raise ValueError('Incomplete IMMED bytecode')
                immed = code[i]
            if bytecode == BC['NOP']:
                pass
            elif bytecode == BC['MOV_EDI_ARG']:
                edi = hash_val
            elif bytecode == BC['PUSH_EBX']:
                stack.append(ebx)
            elif bytecode == BC['POP_EBX']:
                ebx = stack.pop()
            elif bytecode == BC['PUSH_ECX']:
                stack.append(ecx)
            elif bytecode == BC['POP_ECX']:
                ecx = stack.pop()
            elif bytecode == BC['MOV_EBX_EAX']:
                ebx = eax
            elif bytecode == BC['MOV_EAX_EDI']:
                eax = edi
            elif bytecode == BC['MOV_ECX_EBX']:
                ecx = ebx
            elif bytecode == BC['MOV_EAX_EBX']:
                eax = ebx
            elif bytecode == BC['AND_ECX_0F']:
                ecx &= 0x0f
            elif bytecode == BC['SHR_EBX_1']:
                ebx = _u32(ebx >> 1)
            elif bytecode == BC['SHL_EAX_1']:
                eax = _u32(eax << 1)
            elif bytecode == BC['SHR_EAX_CL']:
                eax = _u32(eax >> (ecx & 31))
            elif bytecode == BC['SHL_EAX_CL']:
                eax = _u32(eax << (ecx & 31))
            elif bytecode == BC['OR_EAX_EBX']:
                eax = _u32(eax | ebx)
            elif bytecode == BC['NOT_EAX']:
                eax = _u32(~eax)
            elif bytecode == BC['NEG_EAX']:
                eax = _u32(-eax)
            elif bytecode == BC['DEC_EAX']:
                eax = _u32(eax - 1)
            elif bytecode == BC['INC_EAX']:
                eax = _u32(eax + 1)
            elif bytecode == BC['ADD_EAX_EBX']:
                eax = _u32(eax + ebx)
            elif bytecode == BC['SUB_EAX_EBX']:
                eax = _u32(eax - ebx)
            elif bytecode == BC['IMUL_EAX_EBX']:
                eax = _u32(eax * ebx)
            elif bytecode == BC['ADD_EAX_IMMED']:
                eax = _u32(eax + immed)
            elif bytecode == BC['SUB_EAX_IMMED']:
                eax = _u32(eax - immed)
            elif bytecode == BC['AND_EBX_IMMED']:
                ebx = _u32(ebx & immed)
            elif bytecode == BC['AND_EAX_IMMED']:
                eax = _u32(eax & immed)
            elif bytecode == BC['XOR_EAX_IMMED']:
                eax = _u32(eax ^ immed)
            elif bytecode == BC['MOV_EAX_IMMED']:
                eax = immed
            elif bytecode == BC['MOV_EAX_INDIRECT']:
                if eax >= len(self.m_control_block):
                    raise ValueError('Index out of bounds in HxEncryption program')
                eax = _u32(~self.m_control_block[eax])
            elif bytecode == BC['RETN']:
                if stack:
                    raise ValueError('Imbalanced stack in HxEncryption program')
                return eax
            else:
                raise ValueError('Invalid bytecode in HxEncryption program')
            i += 1
        raise ValueError('HxEncryption program without RETN bytecode')


class HxEncryption:
    """Hxv4 内容加密:Hx 随机数 + Cx 风格字节码生成 span key。"""

    def __init__(self, scheme):
        self.m_mask = scheme.get('mask', 0) or 0
        self.m_offset = scheme.get('offset', 0) or 0
        fk = scheme.get('filterkey', b'\x00' * 8)
        self.m_filter_key = struct.unpack('<Q', fk)[0] if isinstance(fk, (bytes, bytearray)) else (fk & _U64_MASK)
        self.m_random_type = scheme.get('randtype', 0) or 0
        self.control_block = scheme.get('control_block') or [0] * 0x400
        self._scheme_prolog = scheme.get('prologorder') or [0, 1, 2]
        self._scheme_odd = scheme.get('oddbranchorder') or [5, 3, 4, 0, 1, 2]
        self._scheme_even = scheme.get('evenbranchorder') or [4, 2, 3, 5, 7, 6, 1, 0]
        self.m_program_list = [None] * 0x80

    def _new_program(self, seed):
        p = HxProgram(seed, self.control_block, self.m_random_type)
        p.set_orders(self._scheme_prolog, self._scheme_odd, self._scheme_even)
        return p

    # 生成逻辑与 Cx 相同但用 Hx RNG
    def _generate_program(self, seed):
        program = self._new_program(seed)
        for stage in (5, 4, 3, 2, 1):
            if self._emit_code(program, stage):
                return program
            program.clear()
        raise ValueError('Overly large HxEncryption bytecode')

    def _emit_code(self, program, stage):
        from cx import MOV_EDI_ARG, RETN
        return (program.emit_nop(5)
                and program.emit(MOV_EDI_ARG, 4)
                and self._emit_body(program, stage)
                and program.emit_nop(5)
                and program.emit(RETN))

    def _emit_body(self, program, stage):
        from cx import PUSH_EBX, POP_EBX, MOV_EBX_EAX
        if stage == 1:
            return self._emit_prolog(program)
        if not program.emit(PUSH_EBX):
            return False
        if program.get_random() & 1:
            ok = self._emit_body(program, stage - 1)
        else:
            ok = self._emit_body2(program, stage - 1)
        if not ok:
            return False
        if not program.emit(MOV_EBX_EAX, 2):
            return False
        if program.get_random() & 1:
            ok = self._emit_body(program, stage - 1)
        else:
            ok = self._emit_body2(program, stage - 1)
        if not ok:
            return False
        return self._emit_odd_branch(program) and program.emit(POP_EBX)

    def _emit_body2(self, program, stage):
        if stage == 1:
            return self._emit_prolog(program)
        if program.get_random() & 1:
            ok = self._emit_body(program, stage - 1)
        else:
            ok = self._emit_body2(program, stage - 1)
        return ok and self._emit_even_branch(program)

    def _emit_prolog(self, program):
        from cx import MOV_EAX_IMMED, MOV_EAX_EDI, MOV_EAX_INDIRECT
        order = program.m_prolog_order[program.get_random() % 3]
        if order == 2:
            return (program.emit_nop(5)
                    and program.emit(MOV_EAX_IMMED, 2)
                    and program.emit_uint32(program.get_random() & 0x3ff)
                    and program.emit(MOV_EAX_INDIRECT, 0))
        if order == 1:
            return program.emit(MOV_EAX_EDI, 2)
        return program.emit(MOV_EAX_IMMED) and program.emit_random()

    def _emit_even_branch(self, program):
        from cx import (NOT_EAX, DEC_EAX, NEG_EAX, INC_EAX, AND_EAX_IMMED,
                        MOV_EAX_INDIRECT, PUSH_EBX, MOV_EBX_EAX, AND_EBX_IMMED,
                        SHR_EBX_1, SHL_EAX_1, OR_EAX_EBX, POP_EBX, XOR_EAX_IMMED,
                        ADD_EAX_IMMED, SUB_EAX_IMMED)
        order = program.m_even_branch_order[program.get_random() & 7]
        if order == 0:
            return program.emit(NOT_EAX, 2)
        if order == 1:
            return program.emit(DEC_EAX)
        if order == 2:
            return program.emit(NEG_EAX, 2)
        if order == 3:
            return program.emit(INC_EAX)
        if order == 4:
            return (program.emit_nop(5)
                    and program.emit(AND_EAX_IMMED)
                    and program.emit_uint32(0x3ff)
                    and program.emit(MOV_EAX_INDIRECT, 3))
        if order == 5:
            return (program.emit(PUSH_EBX)
                    and program.emit(MOV_EBX_EAX, 2)
                    and program.emit(AND_EBX_IMMED, 2)
                    and program.emit_uint32(0xaaaaaaaa)
                    and program.emit(AND_EAX_IMMED)
                    and program.emit_uint32(0x55555555)
                    and program.emit(SHR_EBX_1, 2)
                    and program.emit(SHL_EAX_1, 2)
                    and program.emit(OR_EAX_EBX, 2)
                    and program.emit(POP_EBX))
        if order == 6:
            return program.emit(XOR_EAX_IMMED) and program.emit_random()
        if program.get_random() & 1:
            ok = program.emit(ADD_EAX_IMMED)
        else:
            ok = program.emit(SUB_EAX_IMMED)
        return ok and program.emit_random()

    def _emit_odd_branch(self, program):
        from cx import (PUSH_ECX, MOV_ECX_EBX, AND_ECX_0F, SHR_EAX_CL,
                        SHL_EAX_CL, POP_ECX, ADD_EAX_EBX, NEG_EAX, IMUL_EAX_EBX,
                        SUB_EAX_EBX)
        order = program.m_odd_branch_order[program.get_random() % 6]
        if order == 0:
            return (program.emit(PUSH_ECX)
                    and program.emit(MOV_ECX_EBX, 2)
                    and program.emit(AND_ECX_0F, 3)
                    and program.emit(SHR_EAX_CL, 2)
                    and program.emit(POP_ECX))
        if order == 1:
            return (program.emit(PUSH_ECX)
                    and program.emit(MOV_ECX_EBX, 2)
                    and program.emit(AND_ECX_0F, 3)
                    and program.emit(SHL_EAX_CL, 2)
                    and program.emit(POP_ECX))
        if order == 2:
            return program.emit(ADD_EAX_EBX, 2)
        if order == 3:
            return (program.emit(NEG_EAX, 2)
                    and program.emit(ADD_EAX_EBX, 2))
        if order == 4:
            return program.emit(IMUL_EAX_EBX, 3)
        return program.emit(SUB_EAX_EBX, 2)

    def _execute_xcode(self, hash_val):
        seed = hash_val & 0x7f
        if self.m_program_list[seed] is None:
            self.m_program_list[seed] = self._generate_program(seed)
        program = self.m_program_list[seed]
        hash_val = _u32(hash_val >> 7)
        ret1 = program.execute(hash_val)
        ret2 = program.execute(_u32(~hash_val))
        return ret1, ret2

    def create_filter_key(self, entry_key, entry_id):
        """生成 Hxv4 内容的 filter key(header_key + span_key + split_pos)。"""
        if (entry_id & 0x100000000) == 0:
            entry_key ^= self.m_filter_key
        header_key_seed = (~entry_key) & _U64_MASK

        key0 = entry_key & _U32_MASK
        key1 = (entry_key >> 32) & _U32_MASK
        k0 = self._execute_xcode(key0)
        span_key0 = (k0[0] | (k0[1] << 32)) & _U64_MASK
        k1 = self._execute_xcode(key1)
        span_key1 = (k1[0] | (k1[1] << 32)) & _U64_MASK

        idx = (entry_key >> 16) & self.m_mask
        split_pos = (self.m_offset + idx) & _U32_MASK

        k3 = self._execute_xcode(header_key_seed & _U32_MASK)
        v5 = (k3[0] | (k3[1] << 32)) & _U64_MASK
        v5 = (~v5) & _U64_MASK
        header_key = bytearray(16)
        j = 56
        for i in range(8):
            header_key[i] = (v5 >> j) & 0xFF
            j -= 8
        k3 = self._execute_xcode(v5 & _U32_MASK)
        v5 = (k3[0] | (k3[1] << 32)) & _U64_MASK
        v5 = (~v5) & _U64_MASK
        j = 56
        for i in range(8):
            header_key[i + 8] = (v5 >> j) & 0xFF
            j -= 8
        return {'header_key': bytes(header_key), 'span_key': (span_key0, span_key1),
                'split_pos': split_pos}


# ---------- Hxv4 数据解密 ----------

def _span_dec_key(key):
    deckey = ((key >> 8) & 0xff) | ((key >> 8) & 0xff00)
    positions = [(key >> 48) & 0xffff, (key >> 32) & 0xffff]
    fisrdeckey = key & 0xff
    if positions[0] == positions[1]:
        positions[1] = (positions[1] + 1) & 0xFFFF
    if fisrdeckey == 0:
        fisrdeckey = 0xa5
    fisrdeckey *= 0x1010101
    return deckey, fisrdeckey, positions


def _decrypt_span(span, key, offset):
    """解密一段 span(原地)。"""
    deckey, fisrdeckey, positions = _span_dec_key(key)
    firstkeybuf = struct.pack('<I', fisrdeckey & _U32_MASK)
    n = len(span)
    for i in range(n):
        span[i] ^= firstkeybuf[i & 3]
    keys = [deckey & 0xff, (deckey >> 8) & 0xff]
    for k, p in zip(keys, positions):
        if p >= offset and p - offset < n:
            span[p - offset] ^= k


def decrypt_content_hxv4(data, filterkey):
    """解密 Hxv4 内容块(header_key + 两段 span)。"""
    buf = bytearray(data)
    header_key = filterkey['header_key']
    span_key0, span_key1 = filterkey['span_key']
    split_pos = filterkey['split_pos']
    n = len(buf)
    for i in range(min(n, len(header_key))):
        buf[i] ^= header_key[i]
    _decrypt_span(buf[:min(split_pos, n)], span_key0, 0)
    if split_pos < n:
        _decrypt_span(buf[split_pos:], span_key1, split_pos)
    return bytes(buf)


def decrypt_index_hxv4(data, key, nonce):
    """解密索引区数据(ChaCha20,counter 从 1 开始,跳过前 64 字节)。"""
    return chacha20_xor(data, key, nonce, counter=1)


def decrypt_text(data, enc_type):
    """Hxv4 脚本内容解密(加密脚本特征 \xfe\xfe 后的部分)。"""
    if enc_type == 2:
        r = io.BytesIO(data)
        r.read(8)  # packed_size
        r.read(8)  # unpacked_size
        return zlib.decompress(r.read())
    if enc_type == 1:
        out = bytearray()
        for c in data:
            c = ((c & 0xAAAA) >> 1 | (c & 0x5555) << 1) & 0xFF
            out.append(c)
        return bytes(out)
    out = bytearray()
    for c in data:
        if c >= 0x20:
            out.append(c ^ (((c & 0xFE) << 8) ^ 1) & 0xFF)
    return bytes(out)


def extract_entry_hxv4(data, segms, filterkey, base_offset=0):
    """按 segment 读取并解密一条目数据。data 为整个 xp3 文件内容。"""
    out = bytearray()
    for segm in segms:
        offset = base_offset + segm['offset']
        segdata = data[offset:offset + segm['zsize']]
        if segm['fsize'] != segm['zsize']:
            segdata = bytearray(zlib.decompress(segdata))
        else:
            segdata = bytearray(segdata)
        segdata = bytearray(decrypt_content_hxv4(segdata, filterkey))
        if len(segdata) > 5 and segdata[0] == 0xfe and segdata[1] == 0xfe \
                and segdata[3] == 0xff and segdata[4] == 0xfe:
            segdata = bytearray(decrypt_text(segdata[5:], segdata[2]))
        out += segdata
    return bytes(out)


# ---------- Hxv4 索引解析 ----------

def _read_int32(r):
    return struct.unpack('>i', r.read(4))[0]


def _read_uint64(r):
    return struct.unpack('>Q', r.read(8))[0]


def _read_string(r):
    length = _read_int32(r)
    return r.read(length * 2).decode('utf-16-le')


def _read_byte_array(r):
    count = _read_int32(r)
    return r.read(count)


def _read_object(r):
    obj_type = r.read(1)[0]
    if obj_type <= 0x01:
        return None
    if obj_type == 0x02:
        return _read_string(r)
    if obj_type == 0x03:
        return _read_byte_array(r)
    if obj_type in (0x04, 0x05):
        return _read_uint64(r)
    if obj_type == 0x81:
        count = _read_int32(r)
        return [_read_object(r) for _ in range(count)]
    if obj_type == 0xC1:
        count = _read_int32(r)
        d = {}
        for _ in range(count):
            k = _read_string(r)
            d[k] = _read_object(r)
        return d
    raise ValueError(f'Unknown object type: {hex(obj_type)}')


def convert_fakename_hxv4(d):
    s = ''
    while True:
        u = ((d & 0x3FFF) + 0x5000) & 0xFFFF
        s += chr(u)
        d >>= 14
        if d == 0:
            break
    return s


def parse_hxv4_index(encdata, key, nonce):
    """解析 Hxv4 索引区,返回条目列表 [{id, key, fakename, filehash, dirhash}]。"""
    dec = decrypt_index_hxv4(encdata, key, nonce)
    indexdata = zlib.decompress(dec[4:])
    r = io.BytesIO(indexdata)
    objects = _read_object(r)
    entries = []
    for i in range(0, len(objects), 2):
        dirhash = objects[i]
        sub = objects[i + 1]
        for j in range(0, len(sub), 2):
            filehash = sub[j]
            entry_id, entry_key = sub[j + 1][:2]
            entries.append({
                'id': entry_id,
                'key': entry_key,
                'fakename': convert_fakename_hxv4(entry_id),
                'filehash': filehash,
                'dirhash': dirhash,
            })
    return entries


class Hxv4Param:
    """Hxv4 参数(key/nonce/filterkey 等,由 krkr_hxv4_dumpkey.js dump)。"""

    def __init__(self, key=b'\x00' * 32, nonce=b'\x00' * 16, filterkey=b'\x00' * 8,
                 mask=0, offset=0, randtype=0, prologorder=None,
                 oddbranchorder=None, evenbranchorder=None, control_block=None):
        self.key = key
        self.nonce = nonce
        self.filterkey = filterkey
        self.mask = mask
        self.offset = offset
        self.randtype = randtype
        self.prologorder = prologorder or [0, 1, 2]
        self.oddbranchorder = oddbranchorder or [5, 3, 4, 0, 1, 2]
        self.evenbranchorder = evenbranchorder or [4, 2, 3, 5, 7, 6, 1, 0]
        self.control_block = control_block or [0] * 0x400

    def make_hx(self):
        """构造 HxEncryption 实例。"""
        return HxEncryption({
            'mask': self.m_mask, 'offset': self.m_offset,
            'filterkey': self.filterkey, 'randtype': self.randtype,
            'control_block': self.control_block,
            'prologorder': self.prologorder,
            'oddbranchorder': self.oddbranchorder,
            'evenbranchorder': self.evenbranchorder})
