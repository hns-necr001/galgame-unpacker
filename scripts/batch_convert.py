# -*- coding: utf-8 -*-
"""
批量转换音频格式（opus/ogg -> mp3/wav 等）
用法:
    python scripts/batch_convert.py -i <输入目录> -o <输出目录> -f mp3 -t 16
依赖:
    ffmpeg（需加入 PATH）
"""
import os
import subprocess
import threading
import argparse
from tqdm import tqdm


def convert(input_file, output_dir, format, sem):
    output_file = os.path.join(output_dir, os.path.splitext(input_file)[0] + '.' + format)
    subprocess.call(['ffmpeg', '-i', input_file, output_file],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sem.release()


def batch_convert(input_files, output_dir, format, sem):
    threads = []
    for input_file in tqdm(input_files):
        sem.acquire()
        thread = threading.Thread(target=convert, args=(input_file, output_dir, format, sem))
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='批量转换 opus/ogg 音频')
    parser.add_argument('-i', '--input', type=str, default=os.getcwd(), help='输入目录')
    parser.add_argument('-o', '--output', type=str, default=os.path.join(os.getcwd(), "converted"), help='输出目录')
    parser.add_argument('-f', '--format', type=str, default='mp3', help='目标格式，如 mp3、wav')
    parser.add_argument('-t', '--thread', type=int, default=16, help='并发线程数')
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    sem = threading.Semaphore(args.thread)

    input_files = []
    for f in os.listdir(args.input):
        file = os.path.join(args.input, f)
        if os.path.isfile(file) and f.split('.')[-1].upper() in ("OPUS", "OGG"):
            input_files.append(file)

    if not input_files:
        print('未找到 opus/ogg 文件')
    else:
        print(f'共 {len(input_files)} 个音频，开始转换...')
        batch_convert(input_files, args.output, args.format, sem)
        print('完成')
