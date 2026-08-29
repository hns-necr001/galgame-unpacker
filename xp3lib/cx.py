# -*- coding: utf-8 -*-
"""
KiriKiri Cx 加密的 Python 移植（参考 GARbro morkt/GARbro 的 KiriKiriCx.cs）。
适用于 Wamsoft KrkrZ Cx/Hxv4 加密（如《天色幻想岛》AmairoIsleNauts）。
"""

# CxByteCode 枚举（与 GARbro 一致）
(NOP, RETN, MOV_EDI_ARG, PUSH_EBX, POP_EBX, PUSH_ECX, POP_ECX,
 MOV_EAX_EBX, MOV_EBX_EAX, MOV_ECX_EBX, MOV_EAX_CONTROL_BLOCK, MOV_EAX_EDI,
 MOV_EAX_INDIRECT, ADD_EAX_EBX, SUB_EAX_EBX, IMUL_EAX_EBX, AND_ECX_0F,
 SHR_EBX_1, SHL_EAX_1, SHR_EAX_CL, SHL_EAX_CL, OR_EAX_EBX, NOT_EAX, NEG_EAX,
 DEC_EAX, INC_EAX) = range(26)

IMMED = 0x100
(MOV_EAX_IMMED, AND_EBX_IMMED, AND_EAX_IMMED, XOR_EAX_IMMED,
 ADD_EAX_IMMED, SUB_EAX_IMMED) = range(IMMED + 1, IMMED + 7)

LENGTH_LIMIT = 0x80
CTL_BLOCK_SIGNATURE = b" Encryption control block"


def _u32(x):
    return x & 0xFFFFFFFF


class CxScheme:
    """Cx 加密方案参数（从 GARbro Formats.dat 导出或由调用方提供）。"""
    def __init__(self, mask=0, offset=0, prolog_order=None,
                 odd_branch_order=None, even_branch_order=None,
                 control_block=None, tpm_file_name=None):
        self.mask = mask
        self.offset = offset
        self.prolog_order = prolog_order or [0, 1, 2]
        self.odd_branch_order = odd_branch_order or [5, 3, 4, 0, 1, 2]
        self.even_branch_order = even_branch_order or [4, 2, 3, 5, 7, 6, 1, 0]
        self.control_block = control_block
        self.tpm_file_name = tpm_file_name


def read_control_block(tpm_path):
    """从 TPM 插件文件中搜索 ' Encryption control block' 并读取 0x400 个 uint（取反）。"""
    with open(tpm_path, 'rb') as f:
        data = f.read()
    idx = data.find(CTL_BLOCK_SIGNATURE)
    if idx == -1:
        raise ValueError('No control block found inside TPM plugin')
    # 控制块按 dword 对齐，从签名位置开始
    block = []
    pos = idx
    for i in range(0x400):
        if pos + 4 > len(data):
            raise ValueError('TPM control block truncated')
        val = int.from_bytes(data[pos:pos + 4], 'little')
        block.append((~val) & 0xFFFFFFFF)
        pos += 4
    return block


class CxProgram:
    def __init__(self, seed, control_block):
        self.m_seed = seed
        self.m_length = 0
        self.m_code = []
        self.m_control_block = control_block

    def get_random(self):
        seed = self.m_seed
        self.m_seed = _u32(1103515245 * seed + 12345)
        return _u32(self.m_seed ^ (seed << 16) ^ (seed >> 16))

    def clear(self):
        self.m_length = 0
        self.m_code = []

    def emit_nop(self, count):
        if self.m_length + count > LENGTH_LIMIT:
            return False
        self.m_length += count
        return True

    def emit(self, code, length=1):
        if self.m_length + length > LENGTH_LIMIT:
            return False
        self.m_length += length
        self.m_code.append(code)
        return True

    def emit_uint32(self, x):
        if self.m_length + 4 > LENGTH_LIMIT:
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
        while i < len(code):
            bytecode = code[i]
            if bytecode & IMMED == IMMED:
                i += 1
                if i >= len(code):
                    raise ValueError('Incomplete IMMED bytecode')
                immed = code[i]
            if bytecode == NOP:
                pass
            elif bytecode == MOV_EDI_ARG:
                edi = hash_val
            elif bytecode == PUSH_EBX:
                stack.append(ebx)
            elif bytecode == POP_EBX:
                ebx = stack.pop()
            elif bytecode == PUSH_ECX:
                stack.append(ecx)
            elif bytecode == POP_ECX:
                ecx = stack.pop()
            elif bytecode == MOV_EBX_EAX:
                ebx = eax
            elif bytecode == MOV_EAX_EDI:
                eax = edi
            elif bytecode == MOV_ECX_EBX:
                ecx = ebx
            elif bytecode == MOV_EAX_EBX:
                eax = ebx
            elif bytecode == AND_ECX_0F:
                ecx &= 0x0f
            elif bytecode == SHR_EBX_1:
                ebx = _u32(ebx >> 1)
            elif bytecode == SHL_EAX_1:
                eax = _u32(eax << 1)
            elif bytecode == SHR_EAX_CL:
                eax = _u32(eax >> (ecx & 31))
            elif bytecode == SHL_EAX_CL:
                eax = _u32(eax << (ecx & 31))
            elif bytecode == OR_EAX_EBX:
                eax = _u32(eax | ebx)
            elif bytecode == NOT_EAX:
                eax = _u32(~eax)
            elif bytecode == NEG_EAX:
                eax = _u32(-eax)
            elif bytecode == DEC_EAX:
                eax = _u32(eax - 1)
            elif bytecode == INC_EAX:
                eax = _u32(eax + 1)
            elif bytecode == ADD_EAX_EBX:
                eax = _u32(eax + ebx)
            elif bytecode == SUB_EAX_EBX:
                eax = _u32(eax - ebx)
            elif bytecode == IMUL_EAX_EBX:
                eax = _u32(eax * ebx)
            elif bytecode == ADD_EAX_IMMED:
                eax = _u32(eax + immed)
            elif bytecode == SUB_EAX_IMMED:
                eax = _u32(eax - immed)
            elif bytecode == AND_EBX_IMMED:
                ebx = _u32(ebx & immed)
            elif bytecode == AND_EAX_IMMED:
                eax = _u32(eax & immed)
            elif bytecode == XOR_EAX_IMMED:
                eax = _u32(eax ^ immed)
            elif bytecode == MOV_EAX_IMMED:
                eax = immed
            elif bytecode == MOV_EAX_INDIRECT:
                if eax >= len(self.m_control_block):
                    raise ValueError('Index out of bounds in CxEncryption program')
                eax = _u32(~self.m_control_block[eax])
            elif bytecode == RETN:
                if stack:
                    raise ValueError('Imbalanced stack in CxEncryption program')
                return eax
            else:
                raise ValueError('Invalid bytecode in CxEncryption program')
            i += 1
        raise ValueError('CxEncryption program without RETN bytecode')


class CxEncryption:
    def __init__(self, scheme):
        self.mask = scheme.mask
        self.offset = scheme.offset
        self.prolog_order = scheme.prolog_order
        self.odd_branch_order = scheme.odd_branch_order
        self.even_branch_order = scheme.even_branch_order
        self.control_block = scheme.control_block
        self.tpm_file_name = scheme.tpm_file_name
        self._program_list = [None] * 0x80

    def init_from_tpm(self, tpm_path):
        self.control_block = read_control_block(tpm_path)
        self._program_list = [None] * 0x80

    # ---------- 字节码生成 ----------
    def _new_program(self, seed):
        return CxProgram(seed, self.control_block)

    def _generate_program(self, seed):
        # 注意:program 只创建一次,重试时仅 clear()(保留 RNG 种子),
        # 与 GARbro 原版一致;若每次 new_program 会重置种子导致程序错误。
        program = self._new_program(seed)
        for stage in (5, 4, 3, 2, 1):
            if self._emit_code(program, stage):
                return program
            program.clear()
        raise ValueError('Overly large CxEncryption bytecode')

    def _emit_code(self, program, stage):
        return (program.emit_nop(5)
                and program.emit(MOV_EDI_ARG, 4)
                and self._emit_body(program, stage)
                and program.emit_nop(5)
                and program.emit(RETN))

    def _emit_body(self, program, stage):
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
        order = self.prolog_order[program.get_random() % 3]
        if order == 2:
            return (program.emit_nop(5)
                    and program.emit(MOV_EAX_IMMED, 2)
                    and program.emit_uint32(program.get_random() & 0x3ff)
                    and program.emit(MOV_EAX_INDIRECT, 0))
        if order == 1:
            return program.emit(MOV_EAX_EDI, 2)
        # order == 0
        return program.emit(MOV_EAX_IMMED) and program.emit_random()

    def _emit_even_branch(self, program):
        order = self.even_branch_order[program.get_random() & 7]
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
        # order == 7
        if program.get_random() & 1:
            ok = program.emit(ADD_EAX_IMMED)
        else:
            ok = program.emit(SUB_EAX_IMMED)
        return ok and program.emit_random()

    def _emit_odd_branch(self, program):
        order = self.odd_branch_order[program.get_random() % 6]
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
        # order == 5
        return program.emit(SUB_EAX_EBX, 2)

    # ---------- 解密 ----------
    def _execute_xcode(self, hash_val):
        seed = hash_val & 0x7f
        if self._program_list[seed] is None:
            self._program_list[seed] = self._generate_program(seed)
        program = self._program_list[seed]
        hash_val = _u32(hash_val >> 7)
        ret1 = program.execute(hash_val)
        ret2 = program.execute(_u32(~hash_val))
        return ret1, ret2

    def _decode(self, key, offset, data):
        """对 data（从 offset 开始）按 Cx 规则解密，返回新 bytes。"""
        ret1, ret2 = self._execute_xcode(key)
        key1 = _u32(ret2 >> 16)
        key2 = ret2 & 0xffff
        key3 = ret1 & 0xff
        if key1 == key2:
            key2 = _u32(key2 + 1)
        if key3 == 0:
            key3 = 1

        out = bytearray(data)
        n = len(data)
        # key2 命中
        if key2 >= offset and key2 < offset + n:
            idx = key2 - offset
            out[idx] ^= (ret1 >> 16) & 0xff
        # key1 命中
        if key1 >= offset and key1 < offset + n:
            idx = key1 - offset
            out[idx] ^= (ret1 >> 8) & 0xff
        # 整段 XOR key3
        for i in range(n):
            out[i] ^= key3
        return bytes(out)

    def decrypt(self, entry_hash, offset, data):
        """解密一段数据。entry_hash 为条目的 adler32，offset 为数据在文件中的偏移。"""
        key = entry_hash & 0xFFFFFFFF
        base_offset = _u32((key & self.mask) + self.offset)
        count = len(data)
        pos = 0
        if offset < base_offset:
            base_length = min(int(base_offset - offset), count)
            part = self._decode(key, offset, data[pos:pos + base_length])
            out = bytearray(part)
            offset += base_length
            pos += base_length
            count -= base_length
        else:
            out = bytearray()
        if count > 0:
            key = _u32((key >> 16) ^ key)
            part = self._decode(key, offset, data[pos:pos + count])
            out.extend(part)
        return bytes(out)
