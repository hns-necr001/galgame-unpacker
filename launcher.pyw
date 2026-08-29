# -*- coding: utf-8 -*-
"""
Galgame 解包工具（简化版）
================================
- 支持：Unity / KiriKiri
- 输出：所选输出目录下自动生成“提取资源”，内含 BGM / CG / 背景 / 立绘 四个文件夹
- 实时显示处理进度（当前/总数）
"""

import os
import re
import sys
import glob
import json
import queue
import shutil
import hashlib
import zipfile
import tempfile
import threading
import subprocess
import traceback
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

# ---------- 路径 ----------
if getattr(sys, 'frozen', False):
    TOOL_DIR = os.path.dirname(sys.executable)
else:
    TOOL_DIR = os.path.dirname(os.path.abspath(__file__))

XP3LIB = os.path.join(TOOL_DIR, 'xp3lib')
TOOLS_FREEMOTE = os.path.join(TOOL_DIR, 'tools', 'freemote')
TOOLS_TLG2PNG = os.path.join(TOOL_DIR, 'tools', 'tlg2png')
PSBDECOMPILE = os.path.join(TOOLS_FREEMOTE, 'PsbDecompile.exe')
EMTCONVERT = os.path.join(TOOLS_FREEMOTE, 'EmtConvert.exe')
TLG2PNG = os.path.join(TOOLS_TLG2PNG, 'tlg2png.exe')
LOG_PATH = os.path.join(TOOL_DIR, '解包日志.txt')
_LOG_LOCK = threading.Lock()

# ---------- 更新 / 设置 ----------
APP_VERSION = 'v0.1.2'                    # 当前版本号（与 GitHub Release 的 tag 对比）
UPDATE_REPO = 'hns-necr001/galgame-unpacker'  # 默认更新源（GitHub 仓库 owner/repo）
CONFIG_DIR = os.path.join(os.environ.get('APPDATA', TOOL_DIR), 'Galgame解包工具')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'settings.json')


def version_key(v):
    """把版本字符串转为可比较的元组，如 'v0.1.10' -> (0,1,10)。"""
    return tuple(int(x) for x in re.findall(r'\d+', str(v)))


def load_config():
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

OUT_SUBDIRS = ('BGM', 'CG', '背景', '立绘')

sys.path.insert(0, XP3LIB)
try:
    from xp3reader import XP3Reader
    from structs.file import XP3File
    XP3_OK = True
except Exception:
    XP3_OK = False

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
    import tkinter.ttk as ttk
    GUI_OK = True
except Exception:
    GUI_OK = False


# ---------- 基础工具 ----------
def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def exists_nonempty(path):
    return os.path.exists(path) and os.path.getsize(path) > 0


def sanitize_component(name):
    name = re.sub(r'[<>:"|?*]', '_', str(name)).strip('. ')
    return name or '_'


def safe_relpath(internal):
    parts = []
    for p in internal.split('/'):
        p = sanitize_component(p)
        if p and p not in ('', '.', '..'):
            parts.append(p)
    return os.path.join(*parts) if parts else 'unnamed'


def run_tool(cmd, timeout=600):
    tool_dir = os.path.dirname(cmd[0])
    # Windows 下禁止外部工具弹出 cmd 黑窗口
    creationflags = 0
    if sys.platform == 'win32':
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    return subprocess.run(
        cmd, capture_output=True, timeout=timeout, cwd=tool_dir,
        creationflags=creationflags)


def detect_game_type(directory):
    if not os.path.isdir(directory):
        return None
    unity_marker = os.path.join(
        directory, 'manosaba_Data', 'StreamingAssets', 'aa', 'StandaloneWindows64')
    if os.path.isdir(unity_marker):
        return 'unity'
    for name in ('evimage.xp3', 'fgimage.xp3', 'bgm.xp3', 'bgimage.xp3', 'data.xp3'):
        if os.path.exists(os.path.join(directory, name)):
            return 'kiri'

    # 兜底：文件名全被伪装也不要紧，扫描文件头，是 XP3 就认定 KiriKiri
    xp3_magic = b'XP3\x0D\x0A\x20\x0A\x1A\x8B\x67\x01'
    try:
        for _n in os.listdir(directory):
            _p = os.path.join(directory, _n)
            if os.path.isfile(_p):
                with open(_p, 'rb') as _f:
                    if _f.read(len(xp3_magic)) == xp3_magic:
                        return 'kiri'
    except Exception:
        pass
    return None

# ---------- KiriKiri（.xp3） ----------
def _write_file(dest, data):
    """写入文件，返回 True 表示本次新写入。"""
    if exists_nonempty(dest):
        return False
    ensure_dir(os.path.dirname(dest))
    with open(dest, 'wb') as fp:
        fp.write(data)
    return True


def handle_bgm(internal, data, out_dir):
    dest = os.path.join(out_dir, 'BGM', safe_relpath(internal))
    return _write_file(dest, data)


def handle_bgimage(internal, data, out_dir):
    dest = os.path.join(out_dir, '背景', safe_relpath(internal))
    return _write_file(dest, data)


def _move_all_png(source_dir, target_dir):
    """把临时目录里生成的图片移动到目标目录；WebP/伪装 tlg 会自动转成 PNG。"""
    count = 0
    if not os.path.isdir(source_dir):
        return 0
    images = []
    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            low = fn.lower()
            if low.endswith(('.png', '.webp', '.tlg')):
                images.append(os.path.join(root, fn))
    images.sort()
    ensure_dir(target_dir)
    for src in images:
        ext = os.path.splitext(src)[1].lower()
        if ext == '.png':
            name = os.path.basename(src)
            dest = os.path.join(target_dir, name)
            i = 2
            while exists_nonempty(dest):
                stem, e = os.path.splitext(name)
                dest = os.path.join(target_dir, f'{stem}_{i}{e}')
                i += 1
            shutil.move(src, dest)
            count += 1
        else:
            # WebP / 伪装成 .tlg 的图片 -> 转成 PNG
            try:
                import io
                from PIL import Image
                with open(src, 'rb') as fp:
                    img = Image.open(io.BytesIO(fp.read()))
                name = os.path.splitext(os.path.basename(src))[0] + '.png'
                dest = os.path.join(target_dir, name)
                i = 2
                while exists_nonempty(dest):
                    stem, e = os.path.splitext(name)
                    dest = os.path.join(target_dir, f'{stem}_{i}{e}')
                    i += 1
                img.save(dest, 'PNG')
                count += 1
            except Exception:
                continue
    return count


def handle_evimage(internal, data, out_dir):
    ext = os.path.splitext(internal)[1].lower()

    # PNG 直接进 CG
    if ext == '.png':
        dest = os.path.join(out_dir, 'CG', safe_relpath(internal))
        return _write_file(dest, data)

    # Pimg 用 FreeMote 转成 PNG 后进 CG（按原始文件名分目录，避免根目录混乱）
    if ext == '.pimg':
        stem = sanitize_component(os.path.splitext(os.path.basename(internal))[0])
        cg_dir = os.path.join(out_dir, 'CG')
        out_sub = os.path.join(cg_dir, stem)
        if os.path.isdir(out_sub) and any(
                f.lower().endswith('.png') for f in os.listdir(out_sub)):
            return False

        tmp = tempfile.mkdtemp(prefix='galgame_pimg_')
        try:
            raw = os.path.join(tmp, stem + '.pimg')
            out_tmp = os.path.join(tmp, 'out')
            ensure_dir(out_tmp)
            with open(raw, 'wb') as fp:
                fp.write(data)

            r = run_tool([PSBDECOMPILE, '--webp', 'image', '-t', 'Pimg', '-o', out_tmp, raw])
            if r.returncode != 0:
                raise RuntimeError(
                    f'PsbDecompile 失败 code={r.returncode} out={r.stdout[-200:]!r} err={r.stderr[-200:]!r}')

            n = _move_all_png(out_tmp, out_sub)
            if n == 0:
                return False
            return True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return False


def _role_dir_for(internal):
    """从平铺的立绘文件名里猜角色名，用于自动建角色子目录。"""
    if '/' in internal or '\\' in internal:
        return ''
    base = os.path.splitext(os.path.basename(internal))[0]
    name = base[4:] if base.lower().startswith('face') else base
    m = re.match(r'^(.*?)(?:[a-zA-Z]?)(?:_\d+)+$', name)
    if m and m.group(1):
        return m.group(1)
    return ''


def handle_fgimage(internal, data, out_dir):
    ext = os.path.splitext(internal)[1].lower()
    rel = safe_relpath(internal)
    lh_dir = os.path.join(out_dir, '立绘')

    # TLG 立绘转 PNG
    if ext == '.tlg':
        role = _role_dir_for(internal)
        if role:
            png = os.path.join(lh_dir, role, os.path.splitext(rel)[0] + '.png')
        else:
            png = os.path.join(lh_dir, os.path.splitext(rel)[0] + '.png')
        if exists_nonempty(png):
            return False

        # 某些游戏（如 ATRI）把 WebP/PNG 伪装成 .tlg，直接用 Pillow 转 PNG
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            try:
                import io
                from PIL import Image
                img = Image.open(io.BytesIO(data))
                ensure_dir(os.path.dirname(png))
                img.save(png, 'PNG')
                return True
            except Exception:
                pass

        tmp = tempfile.mkdtemp(prefix='galgame_tlg_')
        try:
            raw = os.path.join(tmp, os.path.basename(rel))
            ensure_dir(os.path.dirname(raw))
            with open(raw, 'wb') as fp:
                fp.write(data)

            # 先试 tlg2png
            ensure_dir(os.path.dirname(png))
            r = run_tool([TLG2PNG, raw, png], timeout=120)
            if r.returncode == 0 and exists_nonempty(png):
                return True

            # 失败则用 EmtConvert 再试
            r2 = run_tool([EMTCONVERT, raw], timeout=180)
            temp_png = os.path.splitext(raw)[0] + '.png'
            if r2.returncode == 0 and exists_nonempty(temp_png):
                ensure_dir(os.path.dirname(png))
                shutil.move(temp_png, png)
                return True

            raise RuntimeError(
                f'tlg2png={r.returncode} emtconvert={r2.returncode}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # 其他文件直接进立绘
    dest = os.path.join(lh_dir, rel)
    return _write_file(dest, data)


def _is_atri_style(game_dir):
    """检测是否为 ATRI 这类通用 KiriKiri 结构：data.xp3 + bgimage.xp3 + fgimage.xp3 + vol1.xp3。"""
    return (os.path.exists(os.path.join(game_dir, 'data.xp3'))
            and os.path.exists(os.path.join(game_dir, 'bgimage.xp3'))
            and os.path.exists(os.path.join(game_dir, 'fgimage.xp3'))
            and os.path.exists(os.path.join(game_dir, 'vol1.xp3')))

# 已知 Cx 加密游戏方案（参数来自 GARbro Formats.dat / 逆向）
_CX_SCHEMES = {
    # 《天色幻想岛》 AmairoIsleNauts
    'AmairoIsleNauts': {
        'tpm': r'plugin\AmairoIsleNauts.tpm',
        'mask': 548, 'offset': 1442,
        'prolog_order': [0, 1, 2],
        'odd_branch_order': [5, 3, 4, 0, 1, 2],
        'even_branch_order': [4, 2, 3, 5, 7, 6, 1, 0],
    },
}


# Cx 加密系类型(含柚子社变体)
_CX_TYPES = {'CxEncryption', 'SenrenCxCrypt', 'CabbageCxCrypt', 'NanaCxCrypt', 'RiddleCxCrypt'}


def _verify_cx_decoder(dec, game_dir):
    """试解一个 xp3 的加密条目，adler32 匹配才确认方案正确。"""
    import zlib
    try:
        for arch in ('data.xp3', 'scn.xp3', 'bgimage.xp3'):
            p = os.path.join(game_dir, arch)
            if not os.path.exists(p):
                continue
            with open(p, 'rb') as f:
                reader = XP3Reader(f, True)
                for e in reader.file_index.entries:
                    if not e.info.is_encrypted:
                        continue
                    xf = XP3File(e, f, True, True)
                    raw = xf.read('none')
                    out = dec.decrypt(xf.adler32, 0, raw)
                    return zlib.adler32(out) == xf.adler32
    except Exception:
        return False
    return False


def _detect_cx(game_dir):
    """检测 Cx 加密游戏，返回 (解密器, tpm路径) 或 None。
    优先从 schemes.json 加载全部 Cx 系方案：带 ControlBlock 的直接用（并试解验证），
    否则按 TPM 文件匹配。"""
    try:
        from cx import CxScheme, CxEncryption, read_control_block, build_cx_variant
        import json
    except Exception:
        return None
    plugin_dir = os.path.join(game_dir, 'plugin')
    if not os.path.isdir(plugin_dir):
        return None

    schemes_path = os.path.join(XP3LIB, 'schemes.json')
    try:
        with open(schemes_path, encoding='utf-8') as f:
            all_schemes = json.load(f)
    except Exception:
        all_schemes = {}

    # 先试硬编码的 Amairo（保底）
    for name, params in _CX_SCHEMES.items():
        tpm_rel = params['tpm'].replace('\\', '/')
        tpm_path = os.path.join(game_dir, *tpm_rel.split('/'))
        if os.path.exists(tpm_path):
            cb = read_control_block(tpm_path)
            scheme = CxScheme(
                mask=params['mask'], offset=params['offset'],
                prolog_order=params['prolog_order'],
                odd_branch_order=params['odd_branch_order'],
                even_branch_order=params['even_branch_order'],
                control_block=cb, tpm_file_name=params['tpm'])
            dec = CxEncryption(scheme)
            if _verify_cx_decoder(dec, game_dir):
                return dec, tpm_path

    # 遍历 schemes.json 中所有 Cx 系方案
    for name, s in all_schemes.items():
        if s.get('type') not in _CX_TYPES:
            continue
        fields = s.get('fields', {})
        # 带 ControlBlock 的方案可直接构造(不需 TPM)，用试解验证
        if fields.get('ControlBlock'):
            try:
                dec = build_cx_variant(s['type'], fields)
                if dec is not None and _verify_cx_decoder(dec, game_dir):
                    return dec, None
            except Exception:
                continue
        # 否则按 TPM 匹配
        tpm_rel = fields.get('TpmFileName')
        if not tpm_rel:
            continue
        tpm_path = os.path.join(game_dir, *tpm_rel.replace('\\', '/').split('/'))
        if os.path.exists(tpm_path):
            try:
                cb = read_control_block(tpm_path)
            except Exception:
                continue
            scheme = CxScheme(
                mask=int(fields.get('m_mask', 0) or 0),
                offset=int(fields.get('m_offset', 0) or 0),
                prolog_order=fields.get('PrologOrder') or [0, 1, 2],
                odd_branch_order=fields.get('OddBranchOrder') or [5, 3, 4, 0, 1, 2],
                even_branch_order=fields.get('EvenBranchOrder') or [4, 2, 3, 5, 7, 6, 1, 0],
                control_block=cb, tpm_file_name=tpm_rel)
            cls = build_cx_variant(s['type'], {**fields, 'ControlBlock': cb})
            if cls is not None and _verify_cx_decoder(cls, game_dir):
                return cls, tpm_path
    return None


def _is_steam_xp3(game_dir):
    """检测 Steam 版 xp3：索引能读但条目文件名是 32 位十六进制哈希。"""
    for arch in ('bgimage.xp3', 'data.xp3', 'fgimage.xp3', 'vol1.xp3'):
        p = os.path.join(game_dir, arch)
        if not os.path.exists(p):
            continue
        try:
            with open(p, 'rb') as f:
                reader = XP3Reader(f, True)
                entries = list(reader.file_index.entries)
                if not entries:
                    continue
                hash_count = sum(
                    1 for e in entries if re.fullmatch(r'[0-9a-f]{32}', e.file_path))
                if hash_count / len(entries) > 0.5:
                    return True
        except Exception:
            pass
    return False


def _steam_decrypt(data):
    """Steam 版数据：常见格式直接返回；否则暴力试单字节 XOR，能匹配常见格式就还原。"""
    if data[:4] == b'\x89PNG':
        return data, '.png'
    if data[:4] == b'OggS':
        return data, '.ogg'
    if data[:4] == b'RIFF':
        if data[8:12] == b'WEBP':
            return data, '.webp'
        return data, '.wav'
    if data[:3] == b'ID3' or data[:2] == b'\xff\xfb':
        return data, '.mp3'

    for k in range(1, 256):
        head = bytes(b ^ k for b in data[:16])
        if head[:4] == b'\x89PNG':
            return bytes(b ^ k for b in data), '.png'
        if head[:4] == b'OggS':
            return bytes(b ^ k for b in data), '.ogg'
        if head[:4] == b'RIFF':
            if head[8:12] == b'WEBP':
                return bytes(b ^ k for b in data), '.webp'
            return bytes(b ^ k for b in data), '.wav'
        if head[:3] == b'ID3' or head[:2] == b'\xff\xfb':
            return bytes(b ^ k for b in data), '.mp3'
    return data, None




def _find_garbro_cli():
    """查找 C# 解包核心(garbro_cli.exe)。"""
    for c in (os.path.join(TOOL_DIR, 'tools', 'garbro_cli', 'garbro_cli.exe'),
              os.path.join(TOOL_DIR, 'garbro_cli', 'garbro_cli.exe'),
              os.path.join(TOOL_DIR, 'garbro_cli.exe'),
              os.path.join(TOOL_DIR, 'tools', 'garbro_cli', 'bin', 'Release',
                           'net8.0-windows', 'garbro_cli.exe')):
        if os.path.exists(c):
            return c
    return None


def _extract_with_garbro_cli(cli, game_dir, out_root, out_name, log, progress):
    """用 C# GARbro 核心解包(支持 GARbro 全部格式),按 xp3 类型归档。"""
    out_dir = os.path.join(out_root, out_name)
    ensure_dir(out_dir)
    targets = {'bgimage': '背景', 'evimage': 'CG', 'fgimage': '立绘', 'bgm': 'BGM'}
    xp3s = sorted(f for f in os.listdir(game_dir) if f.lower().endswith('.xp3'))
    if not xp3s:
        # 非 xp3 游戏(其他引擎):整目录交给 C# 核心
        log('[C#核心] 未发现 xp3,交给 GARbro 核心整体解包')
        subprocess.run([cli, 'extract', game_dir, out_dir],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
        log('[C#核心] 完成')
        return
    for i, arch in enumerate(xp3s):
        sub = next((v for k, v in targets.items() if arch.lower().startswith(k)), None)
        dest = os.path.join(out_dir, sub) if sub else os.path.join(out_dir, '其他')
        ensure_dir(dest)
        log(f'[C#核心] 解包 {arch} -> {sub or "其他"}')
        r = subprocess.run([cli, 'extract', os.path.join(game_dir, arch), dest],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode != 0 and r.stderr:
            tail = r.stderr.strip().splitlines()
            if tail:
                log('[C#核心] ' + tail[-1])
        progress('解包', i + 1, len(xp3s), arch)
    log('[C#核心] 完成')


def kiri_extract_unified(game_dir, out_root, log, progress, out_name='提取资源'):
    """通用 KiriKiri 提取器（自动兼容柚子社/ATRI 等结构）：
    - bgm.xp3 / data.xp3 中 bgm 开头的音频 -> BGM
    - bgimage.xp3 的图片 -> 背景
    - evimage.xp3 的 png/pimg、vol*.xp3 的 ev*.png -> CG
    - fgimage.xp3 的 tlg/webp -> 立绘（转 PNG）
    """
    if not XP3_OK:
        log('[错误] XP3 解包库加载失败，请检查 xp3lib 目录是否完整。')
        return

    # C# GARbro 核心优先(覆盖 GARbro 全部格式,含 Hxv4 等)
    _cli = _find_garbro_cli()
    if _cli is not None:
        log(f'[C#核心] 检测到 garbro_cli({_cli})，使用 C# 解包核心')
        _extract_with_garbro_cli(_cli, game_dir, out_root, out_name, log, progress)
        return

    # Steam 版 xp3（文件名哈希 + XOR 数据加密）：数据层尚未完整逆向，明确提示避免空跑
    if _is_steam_xp3(game_dir):
        log('[提示] 检测到 Steam 加密版 ATRI（文件名哈希 + 数据加密）。')
        log('[提示] Steam 版 ATRI 加密暂未破解，暂时放弃解包。')
        log('[提示] 请使用其他版本（如标准版/D 盘版），或用 GARbro 等工具自行尝试。')
        return

    # Cx 加密游戏（如《天色幻想岛》）
    cx_decryptor = None
    _cx = _detect_cx(game_dir)
    if _cx is not None:
        cx_decryptor = _cx[0]
        log('[提示] 检测到 Cx 加密游戏，使用 Cx 解密器。')

    # 其他已知算法（从 schemes.json 按目录名模糊匹配）
    scheme_decoder = None
    try:
        from krkr_crypt import KrkrCrypto
        _crypto = KrkrCrypto(os.path.join(XP3LIB, 'schemes.json'))
        _clean = re.sub(r'[^a-z0-9]', '', os.path.basename(game_dir.rstrip('\\/')).lower())
        for _gname, _sch in _crypto.schemes.items():
            _gt = _sch.get('type')
            if _gt in _CX_TYPES or _gt == 'YuzuCrypt':
                continue
            _gc = re.sub(r'[^a-z0-9]', '', _gname.lower())
            if _gc and (_gc in _clean or _clean in _gc):
                scheme_decoder = _crypto.get_decoder(_gname)
                if scheme_decoder is not None:
                    log(f'[提示] 匹配到方案 {_gname}（{_gt}），使用对应解密器。')
                    break
    except Exception:
        scheme_decoder = None

    out_dir = os.path.join(out_root, out_name)
    ensure_dir(out_dir)
    for sub in OUT_SUBDIRS:
        ensure_dir(os.path.join(out_dir, sub))

    log(f'[KiriKiri] 游戏目录：{game_dir}')
    log(f'[KiriKiri] 输出目录：{out_dir}')

    def handle_bgm(internal, data, out_dir):
        dest = os.path.join(out_dir, 'BGM', os.path.basename(internal))
        return _write_file(dest, data)

    def handle_bg_image(internal, data, out_dir):
        dest = os.path.join(out_dir, '背景', safe_relpath(internal))
        return _write_file(dest, data)

    def handle_cg(internal, data, out_dir):
        dest = os.path.join(out_dir, 'CG', os.path.basename(internal))
        return _write_file(dest, data)

    def process_archive(arch, match, handle, label, parallel=False):
        path = os.path.join(game_dir, arch)
        if not os.path.exists(path):
            log(f'[跳过] 找不到 {arch}')
            return
        with open(path, 'rb') as f:
            reader = XP3Reader(f, True)
            entries = [e for e in reader.file_index.entries if match(e.file_path)]
            total = len(entries)
            progress(label, 0, total, '准备读取')
            done = skipped = 0

            def run_one(internal, data):
                try:
                    return internal, handle(internal, data, out_dir), None
                except Exception as exc:
                    return internal, False, f'{exc!r}'

            def collect(internal, ok, err):
                nonlocal done, skipped
                done += 1 if ok else 0
                skipped += 0 if ok else 1
                if err:
                    log(f'[{label}失败] {internal!r}: {err}')
                progress(label, done + skipped, total, f'成功 {done}，跳过 {skipped}')

            def read_data(entry):
                xf = XP3File(entry, f, True, True)
                if not xf.info.is_encrypted:
                    return xf.read('none')
                if cx_decryptor is not None:
                    raw = xf.read('none')
                    return cx_decryptor.decrypt(xf.adler32, 0, raw)
                if scheme_decoder is not None:
                    raw = xf.read('none')
                    off = xf.segm.segments[0].offset if xf.segm.segments else 0
                    return scheme_decoder.decrypt(xf.adler32, off, raw)
                return xf.read('yuzu')

            if parallel:
                max_workers = min(4, os.cpu_count() or 2)
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    in_flight = []
                    for entry in entries:
                        internal = entry.file_path
                        try:
                            data = read_data(entry)
                        except Exception as exc:
                            log(f'[读取失败] {label} {internal!r}: {exc!r}')
                            collect(internal, False, None)
                            continue
                        while len(in_flight) >= 8:
                            fut = in_flight.pop(0)
                            i2, ok2, err2 = fut.result()
                            collect(i2, ok2, err2)
                        in_flight.append(pool.submit(run_one, internal, data))
                    for fut in in_flight:
                        i2, ok2, err2 = fut.result()
                        collect(i2, ok2, err2)
            else:
                for entry in entries:
                    internal = entry.file_path
                    try:
                        data = read_data(entry)
                    except Exception as exc:
                        log(f'[读取失败] {label} {internal!r}: {exc!r}')
                        collect(internal, False, None)
                        continue
                    i2, ok2, err2 = run_one(internal, data)
                    collect(i2, ok2, err2)
        log(f'[完成] {label} 处理 {done} 个，跳过 {skipped} 个，共 {total} 个')

    # 遍历所有文件：不只看 .xp3 后缀，文件头是 XP3 签名的都算（防伪装改名）
    xp3_magic = b'XP3\x0D\x0A\x20\x0A\x1A\x8B\x67\x01'

    def _is_xp3_file(path):
        try:
            with open(path, 'rb') as f:
                return f.read(len(xp3_magic)) == xp3_magic
        except Exception:
            return False

    xp3_files = []
    for _n in sorted(os.listdir(game_dir)):
        _p = os.path.join(game_dir, _n)
        if os.path.isfile(_p) and _is_xp3_file(_p):
            xp3_files.append(_n)
    handled = set()

    for arch in xp3_files:
        al = arch.lower()
        known = False

        # BGM：bgm*.xp3 全部音频条目；data*.xp3 中 bgm 开头的音频
        if al.startswith('bgm'):
            known = True
            process_archive(arch, lambda p: not p.startswith('$$$'), handle_bgm, 'BGM')
        elif al.startswith('data'):
            known = True
            process_archive(
                arch,
                lambda p: p.lower().startswith(('bgm/', 'bgm\\'))
                and p.lower().endswith(('.ogg', '.opus', '.wav')),
                handle_bgm, 'BGM')

        # 背景：bgimage*.xp3 中的图片（排除明显非背景素材，如 item/mask/parts/ui 图标）
        elif al.startswith('bgimage'):
            known = True
            def _is_bg_image(p):
                low = p.lower()
                base = os.path.basename(low)
                if not low.endswith(('.png', '.jpg', '.jpeg', '.psd', '.bmp')):
                    return False
                for prefix in ('item', 'mask', 'parts', 'ui_', 'icon', 'thum', 'chara_'):
                    if base.startswith(prefix):
                        return False
                return True
            process_archive(arch, _is_bg_image, handle_bg_image, '背景')

        # CG：evimage*.xp3 的 png/pimg；vol*.xp3 的 ev*.png；patch 补丁里的 ev*.pimg
        elif al.startswith('evimage'):
            known = True
            process_archive(
                arch,
                lambda p: p.lower().endswith(('.png', '.pimg')),
                handle_evimage, 'CG')
        elif al.startswith('vol'):
            known = True
            process_archive(
                arch,
                lambda p: p.lower().endswith('.png')
                and os.path.basename(p).lower().startswith('ev')
                and not os.path.basename(p).lower().startswith('thum_ev'),
                handle_cg, 'CG')
        elif al.startswith('patch'):
            known = True
            process_archive(
                arch,
                lambda p: p.lower().endswith(('.png', '.pimg'))
                and os.path.basename(p).lower().startswith('ev'),
                handle_evimage, 'CG')

        # 立绘：fgimage*.xp3 的 tlg/webp（并行转换）
        elif al.startswith('fgimage'):
            known = True
            process_archive(
                arch,
                lambda p: p.lower().endswith(('.tlg', '.webp')),
                handle_fgimage, '立绘', parallel=True)

        # 其它：voice/scn/video 等不按前缀处理，留给内容识别兜底
        if known:
            handled.add(arch)

    # ---------- 内容识别兜底：判断不出名字的 xp3，打开扫内部内容再分类 ----------
    def process_archive_by_content(arch):
        path = os.path.join(game_dir, arch)
        try:
            with open(path, 'rb') as f:
                reader = XP3Reader(f, True)
                lows = [e.file_path.lower() for e in reader.file_index.entries]
        except Exception:
            return
        if not lows:
            return
        al = arch.lower()

        audio_exts = ('.ogg', '.opus', '.wav', '.mp3')
        image_exts = ('.png', '.jpg', '.jpeg', '.psd', '.bmp', '.webp')

        bgm_audio = [p for p in lows if 'bgm' in p and p.endswith(audio_exts)]
        tlg = [p for p in lows if p.endswith(('.tlg', '.webp'))]
        pimg = [p for p in lows if p.endswith('.pimg')]
        ev_png = [p for p in lows if p.endswith('.png')
                  and os.path.basename(p).startswith('ev')
                  and not os.path.basename(p).startswith('thum_ev')]

        def _is_bg_image(p):
            base = os.path.basename(p)
            if not p.endswith(('.png', '.jpg', '.jpeg', '.psd', '.bmp')):
                return False
            for prefix in ('item', 'mask', 'parts', 'ui_', 'icon', 'thum', 'chara_'):
                if base.startswith(prefix):
                    return False
            return base.startswith('bg') or 'bgimage' in p or 'background' in p

        bg_img = [p for p in lows if _is_bg_image(p)]
        images_count = len([p for p in lows if p.endswith(image_exts)])
        audio_count = len([p for p in lows if p.endswith(audio_exts)])
        is_image_dominant = images_count > 0 and images_count / len(lows) >= 0.6

        # 纯图片包（图片占绝大多数，且没有 pimg/tlg/ev 特征）→ 整包按背景提取，兼容日文命名的背景
        pure_bg = (images_count > 0 and images_count / len(lows) >= 0.8
                   and not pimg and not tlg and not ev_png)

        # 语音/音效包直接跳过（音频为主、没有图片特征、也没有 BGM 标记）
        is_audio_pack = (audio_count > 0 and images_count == 0
                         and not tlg and not pimg and not ev_png and not bgm_audio)
        if 'voice' in al or is_audio_pack:
            log(f'[跳过] {arch}：识别为语音/音效包')
            return

        matched = False
        if bgm_audio:
            matched = True
            process_archive(
                arch,
                lambda p: 'bgm' in p.lower() and p.lower().endswith(audio_exts),
                handle_bgm, 'BGM')
        # 混合包（图片占比低，如 data 包）不提取背景，避免 UI 图混入
        if bg_img and is_image_dominant:
            matched = True
            process_archive(arch, _is_bg_image, handle_bg_image, '背景')
        elif pure_bg:
            matched = True
            process_archive(
                arch,
                lambda p: p.endswith(('.png', '.jpg', '.jpeg', '.psd', '.bmp')),
                handle_bg_image, '背景')
        if tlg:
            matched = True
            process_archive(
                arch,
                lambda p: p.lower().endswith(('.tlg', '.webp')),
                handle_fgimage, '立绘', parallel=True)
        if pimg or ev_png:
            matched = True
            process_archive(
                arch,
                lambda p: os.path.basename(p).startswith('ev')
                and not os.path.basename(p).startswith('thum_ev')
                and p.endswith(('.png', '.pimg')),
                handle_evimage, 'CG')
        if not matched:
            log(f'[跳过] {arch}：未能识别内容类型')

    for arch in xp3_files:
        if arch not in handled:
            process_archive_by_content(arch)


def kiri_extract_steam(game_dir, out_root, log, progress, out_name='提取资源'):
    """Steam 版 xp3 专用提取：文件名是哈希，数据用单字节 XOR 加密，按档案名粗分类。"""
    if not XP3_OK:
        log('[错误] XP3 解包库加载失败，请检查 xp3lib 目录是否完整。')
        return

    out_dir = os.path.join(out_root, out_name)
    ensure_dir(out_dir)
    for sub in OUT_SUBDIRS:
        ensure_dir(os.path.join(out_dir, sub))

    log(f'[KiriKiri-Steam] 游戏目录：{game_dir}')
    log(f'[KiriKiri-Steam] 输出目录：{out_dir}')

    def save_image(data, dest_dir, name):
        import io
        from PIL import Image
        try:
            img = Image.open(io.BytesIO(data))
            if img.mode in ('RGB', 'RGBA', 'L', 'P'):
                img = img.convert('RGBA')
            ensure_dir(dest_dir)
            path = os.path.join(dest_dir, name + '.png')
            if exists_nonempty(path):
                return False
            img.save(path, 'PNG')
            return True
        except Exception:
            return False

    def process_archive(arch, label, allow_audio, allow_image, image_dir):
        path = os.path.join(game_dir, arch)
        if not os.path.exists(path):
            return
        try:
            with open(path, 'rb') as f:
                reader = XP3Reader(f, True)
                entries = list(reader.file_index.entries)
                total = len(entries)
                progress(label, 0, total, '准备读取')
                done = skipped = 0
                for entry in entries:
                    try:
                        xf = XP3File(entry, f, True, True)
                        raw = xf.read('yuzu')
                    except Exception as exc:
                        log(f'[读取失败] {label} {entry.file_path!r}: {exc!r}')
                        skipped += 1
                        progress(label, done + skipped, total, f'成功 {done}，跳过 {skipped}')
                        continue
                    data, ext = _steam_decrypt(raw)
                    if ext is None:
                        skipped += 1
                        progress(label, done + skipped, total, f'成功 {done}，跳过 {skipped}')
                        continue
                    name = entry.file_path
                    ok = False
                    if ext in ('.png', '.webp', '.tlg') and allow_image:
                        ok = save_image(data, os.path.join(out_dir, image_dir), name)
                    elif ext in ('.ogg', '.opus', '.wav', '.mp3') and allow_audio:
                        ok = _write_file(os.path.join(out_dir, 'BGM', name + ext), data)
                    if ok:
                        done += 1
                    else:
                        skipped += 1
                    progress(label, done + skipped, total, f'成功 {done}，跳过 {skipped}')
        except Exception as exc:
            log(f'[错误] {arch}: {exc!r}')
            return
        log(f'[完成] {label} 处理 {done} 个，跳过 {skipped} 个，共 {total} 个')

    for _n in sorted(os.listdir(game_dir)):
        _al = _n.lower()
        if _al.startswith('bgimage'):
            process_archive(_n, '背景', allow_audio=False, allow_image=True, image_dir='背景')
        elif _al.startswith('fgimage'):
            process_archive(_n, '立绘', allow_audio=False, allow_image=True, image_dir='立绘')
        elif _al.startswith('evimage'):
            process_archive(_n, 'CG', allow_audio=False, allow_image=True, image_dir='CG')
        elif _al.startswith('data'):
            process_archive(_n, 'BGM', allow_audio=True, allow_image=True, image_dir='CG')
        elif _al.startswith('vol'):
            process_archive(_n, 'CG', allow_audio=False, allow_image=True, image_dir='CG')
        # voice / steam / patch 等不处理



def kiri_extract(game_dir, out_root, log, progress, out_name='提取资源'):
    """统一 KiriKiri 提取入口：自动适配柚子社/ATRI 等结构。"""
    return kiri_extract_unified(game_dir, out_root, log, progress, out_name)


# ---------- Unity ----------
def unity_extract(game_dir, out_root, log, progress, out_name='提取资源'):
    try:
        import UnityPy
    except Exception:
        log('[错误] 未安装 UnityPy。请检查 UnityPy 目录是否完整。')
        return

    out_dir = os.path.join(out_root, out_name)
    ensure_dir(out_dir)
    for sub in OUT_SUBDIRS:
        ensure_dir(os.path.join(out_dir, sub))

    asset_base = os.path.join(
        game_dir, 'manosaba_Data', 'StreamingAssets', 'aa', 'StandaloneWindows64')
    log(f'[Unity] 游戏目录：{game_dir}')
    log(f'[Unity] 输出目录：{out_dir}')

    def sanitize(name):
        name = str(name).replace('\\', '/').replace('/', '_')
        name = re.sub(r'[^A-Za-z0-9._\-\u4e00-\u9fff]+', '_', name).strip('._')
        return (name or 'unnamed')[:180]

    def save_pil(img, path):
        if img is None:
            return False
        if img.mode in ('RGB', 'RGBA', 'L', 'P'):
            img = img.convert('RGBA')
        img.save(path, 'PNG')
        return True

    def reserve_path(directory, name, ext, used):
        base = sanitize(name)
        candidate = os.path.join(directory, base + ext)
        i = 1
        while candidate in used:
            candidate = os.path.join(directory, f'{base}_{i}{ext}')
            i += 1
        used.add(candidate)
        if exists_nonempty(candidate):
            return None
        return candidate

    def export_textures(env, stem, outdir):
        ensure_dir(outdir)
        used = set()
        count = 0
        for obj in env.objects:
            if obj.type.name != 'Texture2D':
                continue
            try:
                data = obj.read()
                if data.image is None:
                    continue
                name = getattr(data, 'm_Name', None) or f'tex_{obj.path_id}'
                path = reserve_path(outdir, f'{stem}__{name}', '.png', used)
                if path and save_pil(data.image, path):
                    count += 1
            except Exception as exc:
                log(f'[贴图失败] {stem} {obj.path_id}: {exc!r}')
        return count

    def export_sprites(env, stem, outdir):
        ensure_dir(outdir)
        used = set()
        count = 0
        for obj in env.objects:
            if obj.type.name != 'Sprite':
                continue
            try:
                data = obj.read()
                if data.image is None:
                    continue
                name = getattr(data, 'm_Name', None) or f'sprite_{obj.path_id}'
                path = reserve_path(outdir, f'{stem}__{name}', '.png', used)
                if path and save_pil(data.image, path):
                    count += 1
            except Exception as exc:
                log(f'[立绘失败] {stem} {obj.path_id}: {exc!r}')
        return count

    def export_audio(env, stem, outdir):
        ensure_dir(outdir)
        used = set()
        count = 0
        for obj in env.objects:
            if obj.type.name != 'AudioClip':
                continue
            try:
                data = obj.read()
                samples = data.samples
                if not isinstance(samples, dict):
                    continue
                for fname, raw in samples.items():
                    if not isinstance(raw, (bytes, bytearray)):
                        continue
                    raw = bytes(raw)
                    base_name = os.path.splitext(str(fname))[0] if str(fname).lower().endswith(('.wav', '.ogg', '.mp3')) else str(fname)
                    if raw[:4] == b'RIFF':
                        ext = '.wav'
                    elif raw[:4] == b'OggS':
                        ext = '.ogg'
                    elif raw[:3] == b'ID3' or raw[:2] == b'\xff\xfb':
                        ext = '.mp3'
                    else:
                        ext = '.bin'
                    path = reserve_path(outdir, f'{stem}__{base_name}', ext, used)
                    if path:
                        with open(path, 'wb') as fp:
                            fp.write(raw)
                        count += 1
            except Exception as exc:
                log(f'[音频失败] {stem} {obj.path_id}: {exc!r}')
                log(traceback.format_exc())
        return count

    max_workers = min(4, os.cpu_count() or 2)

    # 1) CG：backgrounds/stills（静态图属于 CG，并行）
    bg_base = os.path.join(asset_base, 'naninovel-backgrounds_assets_naninovel', 'backgrounds')
    files = sorted(glob.glob(os.path.join(bg_base, 'stills', '*.bundle')))
    log(f'[开始] CG 共 {len(files)} 个 bundle')

    def process_cg(f):
        stem = os.path.splitext(os.path.basename(f))[0]
        try:
            env = UnityPy.load(f)
            n = export_textures(env, stem, os.path.join(out_dir, 'CG'))
            return stem, n, None, None
        except Exception as exc:
            return stem, 0, None, f'{exc!r}'

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = []
        for f in files:
            while len(futures) >= 8:
                stem, n, extra, err = futures.pop(0).result()
                done += 1
                if err:
                    log(f'[CG失败] {stem}: {err}')
                else:
                    log(f'[完成] CG {stem} 导出 {n} 张')
                progress('CG', done, len(files), f'{stem} 导出 {n} 张')
            futures.append(pool.submit(process_cg, f))
        for fut in futures:
            stem, n, extra, err = fut.result()
            done += 1
            if err:
                log(f'[CG失败] {stem}: {err}')
            else:
                log(f'[完成] CG {stem} 导出 {n} 张')
            progress('CG', done, len(files), f'{stem} 导出 {n} 张')

    # 2) 背景：mainbackground（主背景）+ tricks（特效背景），并行
    files = sorted(
        glob.glob(os.path.join(bg_base, 'mainbackground', '*.bundle')) +
        glob.glob(os.path.join(bg_base, 'tricks', '*.bundle')))
    log(f'[开始] 背景 共 {len(files)} 个 bundle')

    def process_bg(f):
        stem = os.path.splitext(os.path.basename(f))[0]
        rel = os.path.relpath(os.path.dirname(f), bg_base)
        sub = '' if rel == '.' else rel
        try:
            env = UnityPy.load(f)
            n = export_textures(env, stem, os.path.join(out_dir, '背景', sub))
            return stem, n, None, None
        except Exception as exc:
            return stem, 0, None, f'{exc!r}'

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = []
        for f in files:
            while len(futures) >= 8:
                stem, n, extra, err = futures.pop(0).result()
                done += 1
                if err:
                    log(f'[背景失败] {stem}: {err}')
                else:
                    log(f'[完成] 背景 {stem} 导出 {n} 张')
                progress('背景', done, len(files), f'{stem} 导出 {n} 张')
            futures.append(pool.submit(process_bg, f))
        for fut in futures:
            stem, n, extra, err = fut.result()
            done += 1
            if err:
                log(f'[背景失败] {stem}: {err}')
            else:
                log(f'[完成] 背景 {stem} 导出 {n} 张')
            progress('背景', done, len(files), f'{stem} 导出 {n} 张')

    # 3) 立绘：characters（部件 + 图集，并行）
    pattern = os.path.join(asset_base, 'naninovel-characters_assets_naninovel', 'characters', '*.bundle')
    files = sorted(glob.glob(pattern))
    log(f'[开始] 立绘 共 {len(files)} 个 bundle')

    def process_character(f):
        stem = os.path.splitext(os.path.basename(f))[0]
        try:
            env = UnityPy.load(f)
            n = export_sprites(env, stem, os.path.join(out_dir, '立绘', stem))
            m = export_textures(env, stem, os.path.join(out_dir, '立绘', stem + '_atlas'))
            return stem, n, m, None
        except Exception as exc:
            return stem, 0, 0, f'{exc!r}'

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = []
        for f in files:
            while len(futures) >= 8:
                stem, n, m, err = futures.pop(0).result()
                done += 1
                if err:
                    log(f'[立绘失败] {stem}: {err}')
                else:
                    log(f'[完成] 立绘 {stem} 导出 {n} 张部件，{m} 张贴图')
                progress('立绘', done, len(files), f'{stem} 部件 {n} 张 / 贴图 {m} 张')
            futures.append(pool.submit(process_character, f))
        for fut in futures:
            stem, n, m, err = fut.result()
            done += 1
            if err:
                log(f'[立绘失败] {stem}: {err}')
            else:
                log(f'[完成] 立绘 {stem} 导出 {n} 张部件，{m} 张贴图')
            progress('立绘', done, len(files), f'{stem} 部件 {n} 张 / 贴图 {m} 张')

    # 4) BGM：audio-bgm（并行）
    pattern = os.path.join(asset_base, 'naninovel-audio_assets_audio-bgm_*.bundle')
    files = sorted(glob.glob(pattern))
    log(f'[开始] BGM 共 {len(files)} 个 bundle')

    def process_bgm(f):
        stem = os.path.splitext(os.path.basename(f))[0]
        try:
            env = UnityPy.load(f)
            m = re.search(r'bgm_(\d+)', stem)
            short = 'bgm_' + m.group(1) if m else stem
            n = export_audio(env, short, os.path.join(out_dir, 'BGM'))
            return short, n, None, None
        except Exception as exc:
            return stem, 0, None, f'{exc!r}'

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = []
        for f in files:
            while len(futures) >= 8:
                stem, n, extra, err = futures.pop(0).result()
                done += 1
                if err:
                    log(f'[BGM失败] {stem}: {err}')
                else:
                    log(f'[完成] BGM {stem} 导出 {n} 个音频')
                progress('BGM', done, len(files), f'{stem} 导出 {n} 个音频')
            futures.append(pool.submit(process_bgm, f))
        for fut in futures:
            stem, n, extra, err = fut.result()
            done += 1
            if err:
                log(f'[BGM失败] {stem}: {err}')
            else:
                log(f'[完成] BGM {stem} 导出 {n} 个音频')
            progress('BGM', done, len(files), f'{stem} 导出 {n} 个音频')


# ---------- 界面 ----------
class App:
    def __init__(self, root):
        self.root = root
        root.title('Galgame 解包工具')
        root.geometry('820x620')

        self.path_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.name_var = tk.StringVar(value='提取资源')
        self.status_var = tk.StringVar(value='等待开始...')
        self.progress_var = tk.IntVar(value=0)
        self._prog_last = None
        self.stop_requested = False

        topbar = tk.Frame(root)
        topbar.pack(fill='x', padx=10, pady=(10, 0))
        info = tk.Label(
            topbar,
            text='输出：所选输出目录下自动生成自定义文件夹，内含 BGM / CG / 背景 / 立绘 四个子文件夹',
            fg='#555555', anchor='w', justify='left')
        info.pack(side='left', fill='x', expand=True)
        tk.Button(topbar, text='设置', width=8, command=self.open_settings).pack(side='right', padx=(8, 0))

        top = tk.Frame(root)
        top.pack(fill='x', padx=10, pady=5)
        tk.Label(top, text='游戏目录：').pack(side='left')
        tk.Entry(top, textvariable=self.path_var, width=62).pack(side='left', fill='x', expand=True, padx=5)
        tk.Button(top, text='选择目录', command=self.choose_dir).pack(side='left')

        outrow = tk.Frame(root)
        outrow.pack(fill='x', padx=10, pady=5)
        tk.Label(outrow, text='输出目录：').pack(side='left')
        tk.Entry(outrow, textvariable=self.out_var, width=62).pack(side='left', fill='x', expand=True, padx=5)
        tk.Button(outrow, text='选择输出', command=self.choose_out).pack(side='left')

        namerow = tk.Frame(root)
        namerow.pack(fill='x', padx=10, pady=5)
        tk.Label(namerow, text='文件夹名：').pack(side='left')
        tk.Entry(namerow, textvariable=self.name_var, width=62).pack(side='left', fill='x', expand=True, padx=5)
        tk.Label(namerow, text='默认：提取资源', fg='#888888').pack(side='left')

        progrow = tk.Frame(root)
        progrow.pack(fill='x', padx=10, pady=5)
        self.progress_bar = ttk.Progressbar(progrow, variable=self.progress_var, maximum=1, length=380)
        self.progress_bar.pack(side='left', padx=(0, 10))
        tk.Label(progrow, textvariable=self.status_var, anchor='w').pack(side='right', padx=(10, 0))

        btnrow = tk.Frame(root)
        btnrow.pack(pady=5)
        tk.Button(btnrow, text='开始解包', command=self.start).pack(side='left', padx=5)
        tk.Button(btnrow, text='停止解包', command=self.stop).pack(side='left', padx=5)
        tk.Button(btnrow, text='算法状态', command=self.show_crypto_status).pack(side='left', padx=5)

        self.log_box = scrolledtext.ScrolledText(root, height=16, state='disabled')
        self.log_box.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        self.log_queue = queue.Queue()
        self.worker = None
        root.after(100, self.poll_queue)

        # 启动时自动检查更新（设置里可开关）
        cfg = load_config()
        if cfg.get('auto_check'):
            root.after(2000, self._auto_check_startup)

    def choose_dir(self):
        path = filedialog.askdirectory(title='请选择游戏目录')
        if path:
            self.path_var.set(path)

    def choose_out(self):
        path = filedialog.askdirectory(title='请选择输出目录（将自动创建自定义文件夹）')
        if path:
            self.out_var.set(path)

    def append_log(self, msg):
        self.log_box.configure(state='normal')
        self.log_box.insert('end', msg + '\n')
        self.log_box.see('end')
        self.log_box.configure(state='disabled')

    def poll_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg[0] == 'log':
                    self.append_log(msg[1])
                elif msg[0] == 'progress':
                    _, cur, total, text = msg
                    if total > 0:
                        self.progress_bar.configure(maximum=total)
                        self.progress_var.set(cur)
                    # 简单估算剩余时间
                    eta = ''
                    now = time.time()
                    if self._prog_last and total > 0 and 0 < cur <= total:
                        t0, c0 = self._prog_last
                        dt = now - t0
                        dc = cur - c0
                        if dt > 0 and dc > 0:
                            speed = dc / dt
                            remain = (total - cur) / speed
                            if remain > 0:
                                if remain < 60:
                                    eta = f'，预计剩余 {int(remain)} 秒'
                                else:
                                    eta = f'，预计剩余 {remain/60:.1f} 分钟'
                    if cur > 0:
                        self._prog_last = (now, cur)
                    self.status_var.set(f'{text}  ({cur}/{total}){eta}')
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    def log(self, msg):
        line = msg + '\n'
        with _LOG_LOCK:
            try:
                with open(LOG_PATH, 'a', encoding='utf-8') as f:
                    f.write(line)
            except OSError:
                pass
        self.log_queue.put(('log', msg))

    def progress(self, archive, current, total, text):
        if self.stop_requested:
            raise RuntimeError('用户已停止解包')
        self.log_queue.put(('progress', current, total, text))

    def stop(self):
        if self.worker and self.worker.is_alive():
            self.stop_requested = True
            self.status_var.set('正在停止...')
        else:
            messagebox.showinfo('提示', '当前没有正在运行的解包任务')

    def show_crypto_status(self):
        """弹窗展示加密算法移植状态：已测试 / 已实现未测试 / 未实现，并列出具体游戏。"""
        import json
        from collections import Counter, defaultdict
        try:
            from krkr_crypt import IMPLEMENTED
        except Exception as exc:
            messagebox.showerror('错误', f'krkr_crypt 模块加载失败：{exc!r}')
            return
        schemes_path = os.path.join(XP3LIB, 'schemes.json')
        try:
            with open(schemes_path, encoding='utf-8') as f:
                schemes = json.load(f)
        except Exception as exc:
            messagebox.showerror('错误', f'schemes.json 加载失败：{exc!r}')
            return
        types = Counter(v.get('type') for v in schemes.values())
        tested = {'CxEncryption'}  # 已实测过（天色幻想岛）
        implemented = set(IMPLEMENTED) | tested

        win = tk.Toplevel(self.root)
        win.title('加密算法状态')
        win.geometry('620x560')

        nb = ttk.Notebook(win)
        nb.pack(fill='both', expand=True, padx=10, pady=10)

        # ---- 页 1：算法状态总览 ----
        page1 = tk.Frame(nb)
        nb.add(page1, text='算法状态')
        txt = scrolledtext.ScrolledText(page1, width=76, height=32, state='normal')
        txt.pack(fill='both', expand=True, padx=4, pady=4)

        txt.insert('end', '========== 测试了的和没测试了的 ==========\n\n')

        txt.insert('end', '【已测试】\n')
        for t in sorted(tested):
            txt.insert('end', f'  ✓ {t}（{types.get(t, 0)} 个游戏）\n')
        if not tested:
            txt.insert('end', '  （无）\n')

        txt.insert('end', '\n【已实现 · 未测试】\n')
        for t in sorted(implemented - tested):
            txt.insert('end', f'  · {t}（{types.get(t, 0)} 个游戏）\n')

        txt.insert('end', '\n【未实现】\n')
        for t in sorted(set(types) - implemented):
            txt.insert('end', f'  ✗ {t}（{types.get(t, 0)} 个游戏）\n')

        txt.configure(state='disabled')

        # ---- 页 2：具体游戏清单（按算法分组）----
        page2 = tk.Frame(nb)
        nb.add(page2, text='具体游戏清单')
        txt2 = scrolledtext.ScrolledText(page2, width=76, height=32, state='normal')
        txt2.pack(fill='both', expand=True, padx=4, pady=4)

        by_type = defaultdict(list)
        for name, s in schemes.items():
            by_type[s.get('type')].append(name)

        txt2.insert('end', '========== 各算法对应的具体游戏 ==========\n\n')

        def write_group(title, types_sorted, marker):
            txt2.insert('end', f'\n{title}\n')
            for t in types_sorted:
                games = sorted(by_type.get(t, []))
                txt2.insert('end', f'  {marker} {t}（{len(games)} 个游戏）\n')
                for g in games:
                    txt2.insert('end', f'      - {g}\n')

        write_group('【已测试】', sorted(tested), '✓')
        write_group('【已实现 · 未测试】', sorted(implemented - tested), '·')
        write_group('【未实现】', sorted(set(types) - implemented), '✗')

        txt2.configure(state='disabled')

    # ---------- 设置 / 检测更新 ----------

    def open_settings(self):
        """右上角【设置】窗口：更新源、检查更新、下载安装更新。"""
        if getattr(self, '_settings_win', None) is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        cfg = load_config()
        win = tk.Toplevel(self.root)
        self._settings_win = win
        win.title('设置')
        win.geometry('560x480')
        win.transient(self.root)

        row = tk.Frame(win)
        row.pack(fill='x', padx=12, pady=(14, 4))
        tk.Label(row, text='当前版本：').pack(side='left')
        tk.Label(row, text=APP_VERSION, font=('', 10, 'bold'), fg='#0066cc').pack(side='left')
        tk.Label(row, text='（GitHub Release tag）', fg='#999999').pack(side='left', padx=6)

        row2 = tk.Frame(win)
        row2.pack(fill='x', padx=12, pady=6)
        tk.Label(row2, text='更新源：').pack(side='left')
        self.update_repo_var = tk.StringVar(value=cfg.get('update_repo') or UPDATE_REPO)
        tk.Entry(row2, textvariable=self.update_repo_var, width=46).pack(
            side='left', fill='x', expand=True, padx=5)

        row3 = tk.Frame(win)
        row3.pack(fill='x', padx=12, pady=4)
        self.auto_check_var = tk.BooleanVar(value=bool(cfg.get('auto_check')))
        tk.Checkbutton(row3, text='启动时自动检查更新',
                       variable=self.auto_check_var,
                       command=self._save_settings).pack(side='left')
        self.update_status_var = tk.StringVar(value='')
        tk.Label(row3, textvariable=self.update_status_var, fg='#0066cc',
                 anchor='e').pack(side='right', fill='x', expand=True)

        btns = tk.Frame(win)
        btns.pack(fill='x', padx=12, pady=6)
        tk.Button(btns, text='检查更新', width=12, command=self.check_update).pack(side='left')
        tk.Button(btns, text='下载并安装更新', width=16,
                  command=self.download_update).pack(side='left', padx=8)

        logf = tk.Frame(win)
        logf.pack(fill='both', expand=True, padx=12, pady=(4, 12))
        self.update_log_box = scrolledtext.ScrolledText(logf, height=11, state='disabled')
        self.update_log_box.pack(fill='both', expand=True)

        win.protocol('WM_DELETE_WINDOW', lambda: (self._save_settings(), win.destroy()))
        self._update_log(f'当前版本：{APP_VERSION}；更新源：{self.update_repo_var.get()}')
        self._update_log('提示：发布新版本时，在 GitHub 仓库创建带 tag 的 Release，'
                         '把整个 release 目录打成 zip 上传即可被检测到。')

    def _settings_alive(self):
        return (getattr(self, '_settings_win', None) is not None
                and self._settings_win.winfo_exists())

    def _save_settings(self):
        cfg = load_config()
        cfg['update_repo'] = self.update_repo_var.get().strip() or UPDATE_REPO
        cfg['auto_check'] = bool(self.auto_check_var.get())
        save_config(cfg)

    def _update_status(self, msg):
        if self._settings_alive() and getattr(self, 'update_status_var', None):
            self.update_status_var.set(msg)

    def _update_log(self, msg):
        if self._settings_alive() and getattr(self, 'update_log_box', None):
            self.update_log_box.configure(state='normal')
            self.update_log_box.insert('end', msg + '\n')
            self.update_log_box.see('end')
            self.update_log_box.configure(state='disabled')

    def _normalize_repo(self, s):
        """把 'https://github.com/a/b.git' 或 'a/b' 归一化为 owner/repo。"""
        s = (s or '').strip().rstrip('/')
        s = re.sub(r'^https?://(www\.)?github\.com/', '', s)
        s = re.sub(r'\.git$', '', s)
        parts = s.split('/')
        if len(parts) >= 2 and parts[0] and parts[1]:
            return parts[0] + '/' + parts[1]
        return None

    def check_update(self):
        repo = self._normalize_repo(self.update_repo_var.get())
        if not repo:
            self._update_status('更新源格式不正确（应为 owner/repo 或 GitHub 网址）')
            return
        self._update_status('正在检查更新...')
        self._update_log(f'[检查] 更新源：{repo}')
        threading.Thread(target=self._check_worker,
                         args=(repo, self._on_check_done), daemon=True).start()

    def _check_worker(self, repo, on_done):
        """后台查询 GitHub 最新 Release；结果在主线程回调 on_done(msg, newer, tag, asset)。"""
        def finish(msg, newer, tag, asset):
            self.root.after(0, lambda: on_done(msg, newer, tag, asset))
        try:
            url = f'https://api.github.com/repos/{repo}/releases/latest'
            req = urllib.request.Request(url, headers={
                'User-Agent': 'galgame-unpacker-updater',
                'Accept': 'application/vnd.github+json'})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            tag = data.get('tag_name') or ''
            if not tag:
                finish('仓库没有可用的 Release', False, '', None)
                return
            asset = next((a for a in data.get('assets', [])
                          if (a.get('name') or '').endswith('.zip')), None)
            newer = version_key(tag) > version_key(APP_VERSION)
            if newer:
                size_mb = (asset.get('size') or 0) // 1024 // 1024 if asset else 0
                msg = f'发现新版本 {tag}（当前 {APP_VERSION}）'
                if asset:
                    msg += f'\n更新包：{asset["name"]}（约 {size_mb} MB）'
            else:
                msg = f'已是最新版本 {APP_VERSION}'
            self._last_update = {'tag': tag, 'asset': asset, 'newer': newer}
            finish(msg, newer, tag, asset)
        except urllib.error.HTTPError as e:
            finish(f'检查失败：HTTP {e.code}（仓库不存在或没有 Release）', False, '', None)
        except Exception as exc:
            finish(f'检查失败：{exc!r}', False, '', None)

    def _on_check_done(self, msg, newer, tag, asset):
        self._update_status('')
        self._update_log(f'[结果] {msg}')
        parent = self._settings_win if self._settings_alive() else self.root
        if newer:
            messagebox.showinfo('发现新版本', msg + '\n\n点击“下载并安装更新”开始更新。', parent=parent)
        else:
            messagebox.showinfo('检查更新', msg, parent=parent)

    def download_update(self):
        info = getattr(self, '_last_update', None)
        if not info:
            self._update_status('请先点击“检查更新”')
            return
        if not info.get('newer'):
            self._update_status('当前已是最新版本，无需更新')
            return
        asset = info.get('asset')
        if not asset:
            self._update_status('Release 中没有 zip 更新包')
            return
        self._update_status('正在下载更新包...')
        self._update_log(f'[下载] 开始：{asset["name"]}')
        threading.Thread(target=self._download_worker, args=(asset,), daemon=True).start()

    def _download_worker(self, asset):
        try:
            url = asset['browser_download_url']
            req = urllib.request.Request(url, headers={
                'User-Agent': 'galgame-unpacker-updater'})
            tmpdir = tempfile.mkdtemp(prefix='galgame_upd_')
            zip_path = os.path.join(tmpdir, asset.get('name') or 'update.zip')
            with urllib.request.urlopen(req, timeout=120) as resp, open(zip_path, 'wb') as f:
                total = int(resp.headers.get('Content-Length') or 0)
                done = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = min(100, done * 100 // total)
                        self.root.after(0, lambda p=pct: self._update_status(f'下载中… {p}%'))
            self.root.after(0, lambda: self._update_status('下载完成，校验中...'))
            digest = asset.get('digest') or ''
            if digest and ':' in digest:
                expect = digest.rsplit(':', 1)[-1].lower()
                h = hashlib.sha256()
                with open(zip_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(65536), b''):
                        h.update(chunk)
                if h.hexdigest() != expect:
                    self.root.after(0, lambda: self._update_status('SHA256 校验失败，更新包可能损坏'))
                    self.root.after(0, lambda: self._update_log('[失败] SHA256 校验不一致，已中止'))
                    return
                self.root.after(0, lambda: self._update_log('[校验] SHA256 一致'))
            self.root.after(0, lambda: self._update_log(
                f'[下载] 完成：{os.path.basename(zip_path)}（{done} 字节）'))
            self._apply_update(zip_path, tmpdir)
        except Exception as exc:
            self.root.after(0, lambda: self._update_status(f'下载失败：{exc!r}'))
            self.root.after(0, lambda: self._update_log(f'[失败] {exc!r}'))

    def _apply_update(self, zip_path, tmpdir):
        """解压更新包、写替换脚本、提示退出（exe 运行中无法自我覆盖）。"""
        try:
            new_root = os.path.join(tmpdir, 'new')
            os.makedirs(new_root, exist_ok=True)
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(new_root)
            exe_name = (os.path.basename(sys.executable) if getattr(sys, 'frozen', False)
                        else 'Galgame解包工具.exe')
            content = None
            for dirpath, _dirs, files in os.walk(new_root):
                if exe_name in files:
                    content = dirpath
                    break
            if content is None:
                self.root.after(0, lambda: self._update_status('更新包内未找到主程序，已中止'))
                self.root.after(0, lambda: self._update_log('[失败] 更新包结构不符合预期'))
                return
            pid = os.getpid()
            bat = os.path.join(tmpdir, 'update.bat')
            tooldir = TOOL_DIR
            exe_path = os.path.join(tooldir, exe_name)
            lines = [
                '@echo off',
                'chcp 65001 >nul',
                ':wait',
                f'tasklist /FI "PID eq {pid}" | findstr /I "PID" >nul',
                'if not errorlevel 1 (',
                '  timeout /t 1 /nobreak >nul',
                '  goto wait',
                ')',
                f'xcopy /E /Y /Q "{content}\\*" "{tooldir}\\" >nul',
                'rmdir /S /Q "%~dp0new" >nul 2>&1',
                'del "%~dp0update.zip" >nul 2>&1',
                f'start "" "{exe_path}"',
                '(goto) 2>nul & del "%~f0"',
            ]
            with open(bat, 'w', encoding='gbk', errors='replace') as f:
                f.write('\r\n'.join(lines))
            subprocess.Popen(['cmd', '/c', bat],
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                             close_fds=True)
            self.root.after(0, lambda: self._update_status('替换脚本已就绪，即将重启完成更新'))
            self.root.after(0, lambda: self._update_log('[更新] 解压完成，等待退出替换...'))
            self.root.after(600, self._quit_for_update)
        except Exception as exc:
            self.root.after(0, lambda: self._update_status(f'准备更新失败：{exc!r}'))
            self.root.after(0, lambda: self._update_log(f'[失败] {exc!r}'))

    def _quit_for_update(self):
        try:
            messagebox.showinfo('更新', '文件已就绪，程序将退出并自动完成替换，随后自动重新启动。',
                                parent=self.root)
        finally:
            self.root.destroy()

    def _auto_check_startup(self):
        repo = self._normalize_repo(load_config().get('update_repo') or UPDATE_REPO)
        if repo:
            threading.Thread(target=self._check_worker,
                             args=(repo, self._on_auto_check), daemon=True).start()

    def _on_auto_check(self, msg, newer, tag, asset):
        if newer:
            messagebox.showinfo('发现新版本', msg + '\n\n可在右上角“设置”中查看并更新。')

    def start(self):
        path = self.path_var.get().strip()
        out_root = self.out_var.get().strip()
        out_name = sanitize_component(self.name_var.get().strip()) or '提取资源'

        if not path:
            messagebox.showwarning('提示', '请先选择游戏目录')
            return
        if not os.path.isdir(path):
            messagebox.showerror('错误', '所选游戏目录不存在')
            return
        if not out_root:
            messagebox.showwarning('提示', '请选择输出目录')
            return

        gtype = detect_game_type(path)
        if gtype is None:
            messagebox.showerror(
                '无法识别',
                '这个目录看起来不像支持的 Unity 或 KiriKiri 游戏。\n\n'
                '请选择游戏根目录，例如包含 manosaba_Data 或 .xp3 文件的文件夹。')
            return

        game_name = 'Unity' if gtype == 'unity' else 'KiriKiri'
        if not messagebox.askyesno(
                '确认',
                f'识别为：{game_name}\n\n游戏目录：{path}\n输出目录：{out_root}\n'
                f'输出文件夹：{out_name}\n\n'
                f'将自动创建：{os.path.join(out_root, out_name)}\n开始解包？'):
            return

        # 删除旧日志，重新开始
        try:
            os.remove(LOG_PATH)
        except FileNotFoundError:
            pass

        if self.worker and self.worker.is_alive():
            messagebox.showinfo('提示', '已有解包任务正在运行')
            return

        self.progress_var.set(0)
        self.progress_bar.configure(maximum=1)
        self.status_var.set('开始解包...')
        self.stop_requested = False

        self.worker = threading.Thread(
            target=self.worker_main, args=(path, gtype, out_root, out_name), daemon=True)
        self.worker.start()

    def worker_main(self, path, gtype, out_root, out_name):
        try:
            if gtype == 'unity':
                unity_extract(path, out_root, self.log, self.progress, out_name)
            else:
                kiri_extract(path, out_root, self.log, self.progress, out_name)
            self.log('[全部完成]')
            self.progress('', 0, 1, '全部完成')
        except Exception:
            if self.stop_requested:
                self.log('[已停止] 解包已停止')
                self.log_queue.put(('progress', 0, 1, '已停止'))
            else:
                self.log(traceback.format_exc())


def main_cli():
    """命令行提取：Galgame解包工具.exe --cli <游戏目录> <输出目录> [输出文件夹名]"""
    args = sys.argv[1:]
    if '--cli' not in args:
        return None
    idx = args.index('--cli')
    rest = [a for a in args[idx + 1:] if not a.startswith('--')]
    if len(rest) < 2:
        print('用法: --cli <游戏目录> <输出目录> [输出文件夹名]')
        return 1

    game_dir, out_root = rest[0], rest[1]
    out_name = sanitize_component(rest[2]) or '提取资源' if len(rest) > 2 else '提取资源'

    def log(msg):
        line = msg + '\n'
        print(line, end='')
        with _LOG_LOCK:
            try:
                with open(LOG_PATH, 'a', encoding='utf-8') as f:
                    f.write(line)
            except OSError:
                pass

    def progress(archive, cur, total, text):
        print(f'{archive}: {cur}/{total} {text}')

    gtype = detect_game_type(game_dir)
    if gtype is None:
        print('无法识别游戏目录')
        return 1

    try:
        if gtype == 'unity':
            unity_extract(game_dir, out_root, log, progress, out_name)
        else:
            kiri_extract(game_dir, out_root, log, progress, out_name)
        log('[全部完成]')
    except Exception:
        log(traceback.format_exc())
        return 1
    return 0


def main():
    if not GUI_OK:
        print('未找到 tkinter，无法启动图形界面。')
        return
    if '--cli' in sys.argv:
        sys.exit(main_cli() or 0)
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
