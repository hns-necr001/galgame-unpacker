# 🎉 Galgame 解包工具 v0.1.0

首个公开版本！一个通用的 Galgame 资源解包工具，支持 **Unity（Naninovel）** 和 **KiriKiri（.xp3）** 两类引擎。

## ✨ 功能特性

- **自动识别游戏引擎**：无需手动指定类型，自动判断 Unity / KiriKiri
- **统一输出结构**：解包结果自动整理到 `BGM / CG / 背景 / 立绘` 四个文件夹
- **KiriKiri 内容识别兜底**：
  - 支持标准结构（柚子社、ATRI、千恋万花）
  - 支持 `1080` 高清后缀命名（`bgimage1080.xp3` 等）
  - 支持乱改名 / 伪装后缀，通过文件头识别 XP3 并扫描内部内容自动分类
- **多线程并行转换**：图片转换更快
- **特殊格式自动处理**：
  - 真 TLG 立绘 → 自动转 PNG
  - WebP 伪装成 `.tlg` → 自动识别并转 PNG
  - PSB/Pimg 事件图 → 自动拆图转 PNG
  - 平铺立绘自动按角色名建子目录
- **实时进度显示**：界面显示 `（已完成/总数）`
- **输出文件夹名可自定义**：默认 `提取资源`
- **双模式使用**：图形界面 + 命令行（`--cli`）

## 🎮 已实测支持

| 引擎 | 游戏 |
|------|------|
| KiriKiri（.xp3） | 《魔女的夜宴》 |
| KiriKiri（.xp3） | 《ATRI -My Dear Moments-》 |
| KiriKiri（.xp3） | 《千恋万花》 |
| Unity（Naninovel） | 《魔法少女的魔女审判》 |

## 📦 安装 / 使用

- **源码运行**：`pip install -r requirements.txt && python launcher.pyw`
- **命令行**：`python launcher.pyw --cli <游戏目录> <输出目录> [输出文件夹名]`
- **可运行版**：发布页附带的 `release` 压缩包，解压后双击 `Galgame解包工具.exe`

## ⚠️ 已知限制

- Unity 引擎目前只适配了 manosaba 这一种 Naninovel 资源结构，其他 Unity Galgame 不一定能直接提取
- KiriKiri 已针对三个游戏做过实测，但其他同类游戏的命名/格式差异可能导致部分资源识别失败
- 语音包（voice）默认不提取，只提取 BGM / CG / 背景 / 立绘
- 项目仍在持续完善中，欢迎提 issue 反馈问题

## 📄 许可证

[MIT License](LICENSE)

---

> 前面全是AI生成的，说人话

> 我测试了千恋万花，魔女的夜宴，atri三个krkr格式的，和魔法少女的魔女审判这个以unity编程的

> 之后有时间会更新一些内容，我要上学

> 有问题的你就说，现在功能和ui都挺简陋的，以后再说
