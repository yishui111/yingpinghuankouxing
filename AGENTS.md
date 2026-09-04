# AGENTS.md — 音视频换口型（MuseTalk 口型同步）项目档案

> ⚠️ 修改本仓库前先读本文件（AI 助手/开发者项目记忆）。用户向文档见 README.md / DEPLOY.md。

## 1. 定位
自托管「人脸视频 + 音频 → 口型同步视频」服务：自研 Flask API（code/muse_api.py，端口 5000）+ 单文件 Web 控制台（static/index.html）+ 可配置混合（code/blending_configurable.py）。引擎与模型全部封装在 16.9GB Docker 镜像 image.tar（容器 musetalk，NVIDIA GPU，约 2.2GB 显存）。

## 2. 组件
| 组件 | 说明 |
| ---- | ---- |
| code/ | 自研服务与混合逻辑 + requirements.txt |
| static/index.html | Web 控制台（极速/精修/极速对话/自定义四档、上传进度、任务进度/取消/清空记录、缓存清理、v1/v1.5 双模型） |
| tests/smoke_test.bat | 冒烟测试 |
| docker-compose.yml / Dockerfile | 容器入口（start.bat 首次运行自动 `docker load image.tar`） |
| docs/ | 脱敏后的方案/日志文档 |

## 3. 公开版边界（不入库）
image.tar(16.9GB)、cache/(10.4GB)、output/(1.08GB)、input/（真人素材+MuseTalk-main.zip）、ziliao/、本机绝对路径与素材盘挂载（已脱敏/注释）。Dockerfile 依赖私有基础镜像 musetalk-api-fixed-librosa（自建走 Dockerfile.reference）。image.tar 需外部渠道分发，仓库无法单独跑通（README/DEPLOY 已写明）。

## 4. 维护约定
- Windows: start.bat/stop.bat/status.bat；Linux/macOS: start.sh/stop.sh/status.sh（均有 ~%dp0 相对定位/自动开浏览器）
- 新增功能后同步 README/DEPLOY/本文件；提交 `git push origin main`；中文 UTF-8、bat 纯 ASCII+CRLF+无 BOM
---
### 关键点（2026-09-02 上传整理补充）
- 容器 musetalk 端口 5000：code/muse_api.py(Flask 自研) + static/index.html 控制台；引擎与模型全部在镜像内
- image.tar(16.9GB) 不入库 → 需外部渠道（网盘/母版复制），start.bat 检测到会自动 docker load；Dockerfile 依赖私有基础镜像 musetalk-api-fixed-librosa（自建走 Dockerfile.reference）
- input/（真人素材）、cache/(10.4GB)、output/(1.08GB) 不入库
- 需 NVIDIA GPU（约 2.2GB 显存）；docs/ 四篇方案已脱敏；轻量口型驱动方案.md 为未实现方案

### 关键点（2026-09-05 优化补充）
- GPU 串行：muse_api.py 用 `_gpu_slot` 信号量排队，同一时刻只跑一个任务；`/api/reload` 有任务进行时返回 409
- ffmpeg 全部走 subprocess 列表参数（`_run_ffmpeg`），路径带空格/中文安全；二次封装 `-c:v copy` 零转码 + `+faststart`
- 上传扩展名白名单；`video_path/audio_path` 用 realpath 限制在容器 /app 内；上传临时文件任务结束自动删
- 新端点：`POST /api/tasks/clear`（清记录，delete_files=true 连输出一起删）、`GET /api/cache`、`POST /api/cache/clear`（cache_preprocess 管理）
- `/api/files` 扫描 data/materials/input 三目录，含 size_mb/duration；音频长于视频时任务 info.warning 提示回环
- 任务记录内存上限 100 条自动修剪；blending 的 `_color_match`/`_reinject_noise` 只保留 mask 限内生效版（防方框色差），高斯核尺寸钳制到图像内
