
## 🚀 换电脑部署（保证可用）

> **方式 A（推荐 · 100% 保证）**：用 U 盘 / 网盘把「原项目整份文件夹」（含全部大件）复制到新电脑 → 双击 `start.bat` 即可。
>
> **方式 B（代码装配）**：`git clone` 本仓库 → 双击 `assemble.bat` 预检大件 → 按提示补齐缺失项（下载地址见下文/README）→ 双击 `start.bat`。

> 说明：引擎、模型、镜像、运行时等大件体积超过 GitHub 单文件 100MB 上限，**不随仓库分发**；本仓库承载全部自研代码与装配指引，"方式 A"是换机部署最稳路径，"方式 B"适合需要重新下载大件的场景。
# 音视频换口型 · MuseTalk 数字人口型同步服务 · 部署方案

> 目标：在一台**新电脑**上，把本仓库部署成可用的口型同步服务（Web 控制台 + API）。
> 本文是**权威部署文档**，`docs/部署方案.md` 为早期笔记（历史参考）。

## 1. 环境要求

| 项 | 要求 |
| ---- | ---- |
| 操作系统 | Windows 10/11（推荐），或 Linux / macOS |
| Docker | Windows/macOS 装 **Docker Desktop**（并启动到 Engine running）；Linux 装 Docker Engine + docker compose 插件 |
| GPU | **NVIDIA 独立显卡**，约 **2.2GB** 可用显存（8GB 卡体验更佳），已装官方驱动；无 GPU 不建议（CPU 极慢） |
| 浏览器 | Chrome / Edge / Firefox |
| 磁盘 | 镜像约 16.9GB + 运行产物，建议预留 ≥ 40GB |

## 2. 准备大件：image.tar（关键，先看）

本仓库**不包含**引擎镜像大件。正常运行需要一个 **约 16.9GB 的 `image.tar`**（内含 MuseTalk 引擎 + 全部模型权重 + Python 环境，镜像名 `musetalk-platform-full`），由仓库作者通过**网盘/直链**分享。

拿到后把它放到仓库根目录（与 `start.bat` / `docker-compose.yml` 同级），启动脚本会自动导入；也可手动导入：

```bash
docker load -i image.tar    # 约 5~10 分钟
docker images               # 确认出现 musetalk-platform-full
```

> 拿不到 image.tar 时，可走「从源码构建」路线（见第 7 节），门槛高，仅作备选。

## 3. 获取代码

```bash
git clone https://github.com/yishui111/yingpinghuankouxing.git
cd yingpinghuankouxing
```

不会用 git？GitHub 仓库页 → 绿色 `Code` → `Download ZIP` 解压即可。

## 4. 启动 / 停止 / 状态

| 操作 | Windows | Linux/macOS |
| ---- | ---- | ---- |
| 启动 | 双击 `start.bat`（或 `启动.bat`） | `./start.sh` |
| 停止 | 双击 `stop.bat`（或 `关闭.bat`） | `./stop.sh` |
| 状态 | `status.bat`（或 `状态.bat`） | `./status.sh` |
| 手动启动 | `docker compose up -d` | 同左 |
| 看日志 | `docker logs -f musetalk` | 同左 |

首次启动流程（脚本自动完成）：

1. 检查 Docker 是否在运行；
2. 检查镜像 `musetalk-platform-full` 是否已加载，未加载且有 `image.tar` 则自动 `docker load`（5~10 分钟）；
3. `docker compose up -d` 启动容器（容器名 `musetalk`，端口 5000）；
4. Windows 下自动用浏览器打开 <http://localhost:5000>。

## 5. 验证

1. `docker ps` 中有容器 `musetalk` 且状态 `Up`；
2. 浏览器打开 <http://localhost:5000> 能看到控制台；
3. API 健康检查返回 ok（模型加载约需 1~2 分钟，未就绪时返回 `status=loading`）：

```bash
curl http://localhost:5000/api/health
# {"status":"ok","model_ready":true,"device":"cuda:0",...}
```

4. 选一段**人脸视频** + 一段**音频**点「开始合成」，进度到 100% 后即可预览/下载。

## 6. 目录与数据说明

首次 `docker compose up` 时，Docker 会自动创建以下空目录（已写入 .gitignore，不入仓库）：

| 目录 | 容器内路径 | 说明 |
| ---- | ---- | ---- |
| `input/` | /app/input | 输入视频/音频（预留） |
| `output/` | /app/outputs | 生成结果视频（每个任务一个子目录） |
| `cache/` | /root/.cache/huggingface、/app/checkpoints/torch_cache、/app/cache_preprocess | HuggingFace / PyTorch / 预处理缓存 |
| `data/` | /app/data | 业务数据；网页端「服务器文件」会扫描它 |
| `materials/`（可选） | /app/materials | 素材目录；**默认不挂载**，需要时自建并取消 docker-compose.yml 中注释 |

`code/` 与 `static/index.html` 通过 docker-compose **只读挂载**进容器（/app/main.py、/app/static/index.html 等），改完 `docker compose restart` 即生效，无需重打镜像。

## 7. 备选：从源码构建镜像（仅当拿不到 image.tar）

1. 按 [MuseTalk 官方仓库](https://github.com/TMElyralab/MuseTalk) 文档准备 `musetalk_original/` 代码目录与模型权重（官方模型在 HuggingFace，体积大）；
2. 参考 `Dockerfile.reference`（从 nvidia/cuda 基础镜像装依赖）与 `Dockerfile`（在本地基础镜像上补装 API 依赖）自行构建，打上 `musetalk-platform-full` 标签；
3. 之后按第 4 节启动（此时无需 image.tar）。

> `Dockerfile` 的 `FROM musetalk-api-fixed-librosa` 是**本机私有基础镜像**，不随仓库分发；两者都只是构建参考，日常部署请优先用现成 image.tar。

## 8. 常见问题排查

| 现象 | 处理 |
| ---- | ---- |
| 提示 Docker 未运行 | 启动 Docker Desktop，等 Engine running |
| 提示 image.tar not found | 先下载 image.tar 到项目根目录（第 2 节） |
| 镜像加载失败 | 检查 image.tar 完整性（约 16.9GB），重新 `docker load -i image.tar` |
| 页面打不开 / API 一直 loading | 模型加载 1~2 分钟属正常；`docker logs -f musetalk` 看日志；异常时 `docker rm -f musetalk` 后重新启动 |
| 端口 5000 被占用 | 关掉占用程序；需改端口则同时改 docker-compose.yml 的 ports 和 static/index.html 里的 5000 |
| 显存不足（CUDA out of memory） | 用「极速版」模式或调小 batch_size（自定义参数），必要时重启容器 |
| GPU 不可用（/api/health 里 gpu_available=false） | 检查 NVIDIA 驱动与 Docker Desktop 的 GPU 支持（WSL2 + nvidia-container-toolkit） |
| 容器起不来 / 崩溃 | `docker logs musetalk` 查原因；`docker compose down` 后重试 |

## 9. 更新约定

每次修改代码/文档后，同步更新本文件与 README.md；改动记录追加到 `docs/项目日志.md`。
