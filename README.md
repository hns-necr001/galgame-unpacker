# Galgame 解包工具

一个通用的 Galgame 资源解包工具，目前仅支持 **Unity（Naninovel）** 和 **KiriKiri（.xp3）** 两类引擎。
目前正在一步一步添加功能，还有修bug

## 功能

- 自动识别游戏引擎，无需手动指定类型
- 解包结果统一输出到 `BGM / CG / 背景 / 立绘` 四个文件夹
- KiriKiri 支持“内容识别兜底”：即使 `.xp3` 被乱改名、甚至后缀被伪装，也能通过文件头识别并扫描内部内容自动分类
- 支持多线程并行转换图片，速度更快
- 自动处理各种特殊格式：
  - 真 TLG 立绘 → `tlg2png` / `EmtConvert` 转 PNG
  - WebP 伪装成 `.tlg` → 自动识别并用 Pillow 转 PNG
  - PSB/Pimg 事件图 → `PsbDecompile` 拆图转 PNG
  - 平铺立绘自动按角色名建子目录
- 界面实时显示 `（已完成/总数）` 进度
- 支持图形界面和命令行两种模式
- 直接解压压缩包：支持选取 zip / 7z / rar，自动解压并识别游戏目录（7z/rar 需系统已装 7-Zip 或 WinRAR）

## 目录结构

```
Galgame解包工具/
├─ launcher.pyw            # 主程序源码（GUI + CLI）
├─ xp3lib/                 # 自研 KiriKiri .xp3 解析库
├─ tools/                  # 外部转换工具（freemote / tlg2png）
├─ Galgame解包工具.spec    # PyInstaller 打包配置
├─ requirements.txt        # Python 依赖
├─ LICENSE                 # MIT 许可证
├─ 使用说明.txt
├─ README.md
└─ release/                # 已打包的可运行版本（含 exe 和运行库）
```

## 使用方法

### 图形界面

```bash
# 直接运行打包版
release/Galgame解包工具.exe

# 或从源码运行
python launcher.pyw
```

1. 选择游戏目录
2. 选择输出目录
3. 自定义输出文件夹名（默认 `提取资源`）
4. 点击开始解包

### 命令行

```bash
python launcher.pyw --cli <游戏目录> <输出目录> [输出文件夹名]
```

```bash
# 打包版
release/Galgame解包工具.exe --cli "<游戏目录>" "<输出目录>" 我的资源
```

## 从源码运行

```bash
pip install -r requirements.txt
python launcher.pyw
```

KiriKiri 解包需要 `tools/` 目录下的外部工具：
- `tools/freemote/PsbDecompile.exe`、`EmtConvert.exe`（PSB/Pimg 转换）
- `tools/tlg2png/tlg2png.exe`（TLG 转换）

Unity 解包需要：
- `fmod_toolkit` 及其 `fmod.dll`（FMOD 音频解码）
- `archspec/json` 数据文件（astc_encoder 依赖）

## 附带脚本

`scripts/` 目录提供两个解包后的资源处理脚本（源自 [2DIPW/atri_extract_toolbox](https://github.com/2DIPW/atri_extract_toolbox)）：

### batch_convert.py —— 批量转换音频

把解包出来的 `.opus` / `.ogg` 批量转成 `mp3` / `wav` 等（需要 `ffmpeg` 并加入 PATH）：

```bash
python scripts/batch_convert.py -i <音频目录> -o <输出目录> -f mp3 -t 16
```

参数：
- `-i / --input`：输入目录，默认当前目录
- `-o / --output`：输出目录，默认 `converted`
- `-f / --format`：目标格式（mp3、wav 等），默认 `mp3`
- `-t / --thread`：并发线程数，默认 16

### parse_script.py —— 解析剧本 JSON

把 [FreeMote](https://github.com/UlyssesWu/FreeMote) 反编译出来的 `scn` JSON 剧本解析成可读表格（角色 / 日文 / 译文 / 语音）：

```bash
python scripts/parse_script.py -i <json目录> -o <输出目录> -l 2 -af mp3 -s
```

参数：
- `-i / --input`：JSON 文件目录，默认当前目录
- `-o / --output`：输出目录，默认 `parsed`
- `-l / --language`：译文语言 `0:JP 1:EN 2:ZHS 3:ZHT`，默认 2（简中）
- `-af / --audio_format`：语音文件名后缀，默认 `mp3`
- `-s / --single_file`：合并所有 JSON 输出为一个文件

## 重新打包

```bash
python -m PyInstaller --noconfirm --clean --onedir --windowed \
  --name Galgame解包工具 \
  --contents-directory . \
  --paths . \
  --distpath . \
  --workpath build_tmp \
  --specpath build_tmp \
  launcher.pyw
```

## License

本项目使用 [MIT License](LICENSE) 开源。

## 免责声明

本工具仅用于个人学习、备份和资源整理，不修改游戏原始文件。解包结果请遵守当地法律和游戏用户协议。
