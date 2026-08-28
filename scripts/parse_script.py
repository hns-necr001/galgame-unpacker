# -*- coding: utf-8 -*-
"""
解析 FreeMote 反编译的 scn JSON 剧本为可读表格
用法:
    python scripts/parse_script.py -i <json目录> -o <输出目录> -l 2 -af mp3 -s
依赖:
    tqdm
"""
import json
import os
import argparse
import csv
import re
from tqdm import tqdm


def parse(input_file, trans_language, audio_format):
    results = []
    with open(input_file, 'r', encoding='utf-8') as json_file:
        data = json.load(json_file)
    pattern = re.compile(r'[「」『』（）"]|(\[.*])|(\\n)')
    for scene in data.get('scenes', []):
        texts = scene.get('texts')
        if not texts:
            continue
        for text in texts:
            character = ""
            try:
                character = text[0] or ""
            except (TypeError, IndexError):
                pass
            try:
                sentence_ori = text[2][0][1] or ""
                sentence_ori = pattern.sub('', sentence_ori)
                sentence_trans = text[2][trans_language][1] or ""
                sentence_trans = pattern.sub('', sentence_trans)
            except (TypeError, IndexError):
                continue
            voice = ""
            try:
                voice = text[3][0].get("voice") or ""
                if voice:
                    voice += f".{audio_format}"
            except (TypeError, IndexError):
                pass
            results.append([character, sentence_ori, sentence_trans, voice])
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='解析 FreeMote scn JSON 剧本')
    parser.add_argument('-i', '--input', type=str, default=os.getcwd(), help='JSON 文件所在目录')
    parser.add_argument('-o', '--output', type=str, default=os.path.join(os.getcwd(), "parsed"), help='输出目录')
    parser.add_argument('-l', '--language', type=int, default=2, help='译文语言 0:JP 1:EN 2:ZHS 3:ZHT，默认 2')
    parser.add_argument('-d', '--delimiter', type=str, default="\t", help='输出分隔符，默认制表符')
    parser.add_argument('-af', '--audio_format', type=str, default="mp3", help='语音文件名后缀，默认 mp3')
    parser.add_argument('-s', '--single_file', action='store_true', help='合并为单个文件')
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    json_files = [f for f in os.listdir(args.input) if f.upper().endswith('.JSON')]

    if not json_files:
        print('未找到 JSON 文件')
    else:
        if args.single_file:
            results = []
            for f in tqdm(json_files):
                results += parse(os.path.join(args.input, f), args.language, args.audio_format)
            with open(os.path.join(args.output, "all_in_one_parsed.txt"), "w", encoding="utf8", newline="") as tsvfile:
                csv.writer(tsvfile, delimiter=args.delimiter).writerows(results)
        else:
            for f in tqdm(json_files):
                results = parse(os.path.join(args.input, f), args.language, args.audio_format)
                with open(os.path.join(args.output, f + "_parsed.txt"), "w", encoding="utf8", newline="") as tsvfile:
                    csv.writer(tsvfile, delimiter=args.delimiter).writerows(results)
        print('完成')
