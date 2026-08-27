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
import queue
import shutil
import tempfile
import threading
import subprocess
import traceback
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

        info = tk.Label(
            root,
            text='支持引擎：Unity / KiriKiri\n'
                 '输出：所选输出目录下自动生成自定义文件夹，内含 BGM / CG / 背景 / 立绘 四个子文件夹',
            fg='#555555', anchor='w', justify='left')
        info.pack(fill='x', padx=10, pady=(10, 0))

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
        self.progress_bar = ttk.Progressbar(progrow, variable=self.progress_var, maximum=1)
        self.progress_bar.pack(fill='x', side='left', expand=True)
        tk.Label(progrow, textvariable=self.status_var, width=46).pack(side='left', padx=5)

        tk.Button(root, text='开始解包', command=self.start).pack(pady=5)

        self.log_box = scrolledtext.ScrolledText(root, height=16, state='disabled')
        self.log_box.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        self.log_queue = queue.Queue()
        self.worker = None
        root.after(100, self.poll_queue)

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
                    self.status_var.set(f'{text}  ({cur}/{total})')
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
        self.log_queue.put(('progress', current, total, text))

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
