<div align="center">

# 🎬 音视频换口型 · MuseTalk 数字人口型同步服务

> ⭐ **喜欢这个项目？请先点个 Star ⭐ 支持一下，让更多人看到！**

![GitHub stars](https://img.shields.io/github/stars/yishui111/yingpinghuankouxing.svg?style=flat-square&color=orange)
![GitHub forks](https://img.shields.io/github/forks/yishui111/yingpinghuankouxing.svg?style=flat-square)
![GitHub repo size](https://img.shields.io/github/repo-size/yishui111/yingpinghuankouxing.svg?style=flat-square)

**输入一段人脸视频 + 一段音频，自动生成「说话口型同步」的视频 —— 自托管 Web 控制台 + REST API，一键 Docker 部署。**

</div>

---

## ✨ 项目简介

本项目是围绕开源口型同步方案 [MuseTalk](https://github.com/TMElyralab/MuseTalk) 自研封装的一套**口型驱动（换口型）服务**：给一段**人脸视频**和一段**语音/音频**，逐帧把嘴型对上音频，输出换好口型的 MP4 视频。适合做数字人视频、口播二创、影视/访谈类「换口型」场景。

- **Web 控制台**：上传/点选素材 → 调参数 → 实时进度 → 预览/下载，开箱即用
- **REST API**：`/api/synthesize` 等接口，方便接入自己的前端或自动化流程
- **Docker 一键部署**：`start.bat` 首次运行自动导入镜像，之后秒起
- **已内置优化**：同一形象视频二次合成直接命中预处理缓存；音频不超视频长度时不循环画面（大提速）；支持「极速 / 精修 / 自定义」三档

> 仓库只含**自研代码 / 脚本 / 配置 / 文档**；引擎镜像与模型权重是约 **16.9GB** 的大文件，**不随仓库分发**，见下方「大件资源下载」获取方式。

## 🎯 主要功能

- 🎤 **换口型合成**：人脸视频 + 音频 → 口型同步视频（支持 v1 / v1.5 两版模型）
- 🖥️ **Web 控制台**（端口 5000）：素材「服务器文件 / 本地上传」双来源、极速版/精修版/自定义、实时进度条、在线预览与下载
- ⚡ **智能提速**：人脸检测 + VAE 编码结果按视频内容缓存，同素材二次合成跳过最耗时环节
- 🔄 **画面智能循环**：音频 ≤ 视频长度顺序播放；音频更长时自动「正向 + 反向回环」无缝续画面
- 🎛️ **参数全开放**：batch_size、面部混合范围（jaw/neck/raw）、上半脸保留比例、边缘模糊、质感统一/噪点重注入等十余项
- 🔁 **任务管理**：后台异步任务，支持查询进度 / 取消任务 / 一键刷新模型释放显存（/api/reload）
- 🌐 **API 文档内置**：控制台内附完整接口文档与 curl 示例；前端地址自适应（局域网可直接访问）

## 🗂️ 目录结构

```
yingpinghuankouxing/
├── code/                  # 自研 API 服务（容器启动时以只读方式挂载进 /app）
│   ├── muse_api.py            # Flask API：任务调度 / 推理封装 / 文件管理
│   ├── blending_configurable.py # 可配置面部混合（替换引擎内默认实现）
│   └── requirements.txt        # API 运行依赖（容器内已装，供参考）
├── static/
│   └── index.html         # Web 控制台前端（单文件，无构建步骤）
├── tests/
│   └── smoke_test.bat     # 冒烟测试：Docker / 容器 / API 健康检查
├── docs/                  # 历史方案与笔记（已脱敏）
│   ├── 轻量口型驱动方案.md  # 轻量 3D 表情数字人替代方案（可选后续）
│   ├── 部署方案.md          # 早期部署笔记（最新步骤以 DEPLOY.md 为准）
│   ├── 启动项目.md          # 启停命令速查
│   └── 项目日志.md          # 改动记录
├── docker-compose.yml     # 服务编排（容器 musetalk，端口 5000）
├── Dockerfile             # 备用构建文件（基于本地基础镜像）
├── Dockerfile.reference   # 从零构建参考（需自行准备引擎源码与模型）
├── start.bat / stop.bat / status.bat   # Windows 一键启停/状态
├── 启动.bat / 关闭.bat / 状态.bat        # 中文名别名（等价于上方三个）
├── start.sh / stop.sh / status.sh       # Linux/macOS 一键启停/状态
├── DEPLOY.md              # 新机器完整部署步骤（推荐先读）
├── .gitignore
└── README.md
```

> 💡 本仓库只包含**源代码 / 脚本 / 配置 / 文档**等关键内容。
> `image.tar`、`input/`、`output/`、`cache/`、`ziliao/` 等大文件/真人素材一律不随仓库分发。

## 🚀 快速开始（拉到新电脑即可部署）

### 环境要求

- 操作系统：Windows 10/11（推荐）或 Linux/macOS
- **Docker Desktop**（https://www.docker.com）或 Linux/macOS 上的 Docker Engine
- **NVIDIA 独立显卡**（约 2.2GB 显存即可）+ 已装驱动（容器内已含 CUDA；无 GPU 时 CPU 模式极慢，不建议）
- 浏览器：Chrome / Edge / Firefox 等现代浏览器

> **部署形态说明**：本仓库开箱即用的运行方式是 **Docker + 现成镜像**（即下方步骤）。
> 备选：拿不到 image.tar 时，可参考 `Dockerfile.reference` 从 MuseTalk 官方源码自行构建镜像（见 `DEPLOY.md` 第 7 节），门槛较高。
> 注意 `code/muse_api.py` 依赖镜像内预装的 MuseTalk 引擎与模型，**不支持脱离容器直接 `python muse_api.py` 在本机运行**；
> 仓库内另有轻量 3D 表情数字人的**方案文档**（`docs/轻量口型驱动方案.md`），属后续可选方向，尚未实现。

### 1. 克隆

```bash
git clone https://github.com/yishui111/yingpinghuankouxing.git
cd yingpinghuankouxing
```

### 2. 准备大件：下载 image.tar

从作者分享的网盘/直链下载 **image.tar（约 16.9GB）**，放到仓库根目录（与 `start.bat` 同级）。下载方式见下方表格与 `DEPLOY.md`。

### 3. 启动

```text
# Windows：双击 start.bat（或 启动.bat），或命令行执行：
start.bat

# Linux/macOS：
./start.sh
```

首次运行 `start.bat` 会自动检测镜像 `musetalk-platform-full`：未加载时会先从 `image.tar` 导入（约 5~10 分钟），然后 `docker compose up -d` 拉起容器，并自动打开浏览器。

> 不想用脚本也可以手动两步：
> ```bash
> docker load -i image.tar      # 仅首次需要
> docker compose up -d
> ```

### 4. 验证

1. 打开 <http://localhost:5000>，看到「MuseTalk 数字人口型同步」控制台
2. 顶部状态点变绿、显示「就绪 | GPU: …」（模型加载约 1~2 分钟，可用 `status.bat` / `curl http://localhost:5000/api/health` 查看）
3. 选择/上传一段人脸视频 + 一段音频，点「开始合成」，等待进度完成即可下载结果

### 5. 停止

```bash
stop.bat        # Windows；Linux/macOS 用 ./stop.sh
```

## 📥 大件资源下载（模型 / 素材 / 运行时）

| 资源 | 用途 | 下载地址 / 获取方式 |
| ---- | ---- | ---- |
| `image.tar`（约 16.9GB） | **完整 Docker 镜像**：内含 MuseTalk 引擎代码、全部模型权重（musetalkV15/V1、Whisper、人脸解析模型）与 Python 环境，日常运行只需它 | 由仓库作者通过网盘/直链分享（本仓库无法托管大文件）；下载后放入仓库根目录，`start.bat` 首次运行会自动 `docker load` |
| MuseTalk 官方源码与模型（可选） | 想从零构建镜像（`Dockerfile.reference` 路线）时使用 | [github.com/TMElyralab/MuseTalk](https://github.com/TMElyralab/MuseTalk)（官方权重下载见其 README） |
| 人脸视频 / 音频素材（可选） | 合成输入素材；放入本机 `materials/` 等目录即可在控制台「服务器文件」中点选 | 自行准备（真人素材请勿提交到仓库） |

## 🛠️ 本地开发 & 提交

```bash
git add .
git commit -m "feat: xxx"
git push origin main
```

> 修改 `code/` 或 `static/` 后，`docker compose restart` 即生效（compose 已把这两个目录只读挂载进容器）。

## ❓ 常见问题（FAQ）

- **Q：提示 Docker 未运行？** A：先启动 Docker Desktop，等 "Engine running" 后再执行 start.bat。
- **Q：提示 image.tar not found？** A：镜像大件需先从网盘下载并放到项目根目录，见「大件资源下载」。
- **Q：页面打不开 / 健康检查不 OK？** A：容器内模型加载需 1~2 分钟，稍后再试；或 `docker logs -f musetalk` 看日志；异常时 `docker rm -f musetalk` 后重新启动。
- **Q：没有 NVIDIA 显卡能跑吗？** A：能启动但极慢（CPU 模式），不建议；服务按 GPU 场景设计。
- **Q：端口 5000 被占用？** A：关掉占用程序；如需改端口请同步修改 docker-compose.yml 的 ports 与 static/index.html 中的 5000。
- **Q：合成结果很慢？** A：选「极速版」，或给同一形象视频用同一参数再合成（命中预处理缓存会快很多）；显存允许时调大 batch_size。

## ⚠️ 注意事项

- 敏感信息（密钥、token、账号密码）一律放 `.env` 并加入 `.gitignore`，禁止提交到仓库；
- 本仓库不含真人视频/音频素材、缓存与 16.9GB 镜像大件，请勿把 `input/` `output/` `cache/` `ziliao/` 等目录提交上来；
- 请遵守相关肖像权/著作权规定，勿对未经授权的人脸进行换口型制作；
- 本仓库仅供学习交流使用。

## 📄 许可证

MIT License（如项目自带 LICENSE 则以仓库内为准）

## 🙏 支持与致谢

- 底层方案：[MuseTalk](https://github.com/TMElyralab/MuseTalk)（TMElyralab）
- 如果这个项目帮到了你，**请点亮右上角的 ⭐ Star**，你的支持是我持续更新的最大动力！
