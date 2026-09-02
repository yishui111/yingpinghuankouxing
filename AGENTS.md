# AGENTS.md — 音视频换口型（MuseTalk 口型同步）项目档案

> ⚠️ 修改本仓库前先读本文件（AI 助手/开发者项目记忆）。用户向文档见 README.md / DEPLOY.md。

## 1. 定位
自托管「人脸视频 + 音频 → 口型同步视频」服务：自研 Flask API（code/muse_api.py，端口 5000）+ 单文件 Web 控制台（static/index.html）+ 可配置混合（code/blending_configurable.py）。引擎与模型全部封装在 16.9GB Docker 镜像 image.tar（容器 musetalk，NVIDIA GPU，约 2.2GB 显存）。

## 2. 组件
| 组件 | 说明 |
| ---- | ---- |
| code/ | 自研服务与混合逻辑 + requirements.txt |
| static/index.html | Web 控制台（极速/精修/自定义三档、任务进度/取消、v1/v1.5 双模型） |
| tests/smoke_test.bat | 冒烟测试 |
| docker-compose.yml / Dockerfile | 容器入口（start.bat 首次运行自动 `docker load image.tar`） |
| docs/ | 脱敏后的方案/日志文档 |

## 3. 公开版边界（不入库）
image.tar(16.9GB)、cache/(10.4GB)、output/(1.08GB)、input/（真人素材+MuseTalk-main.zip）、ziliao/、本机绝对路径与素材盘挂载（已脱敏/注释）。Dockerfile 依赖私有基础镜像 musetalk-api-fixed-librosa（自建走 Dockerfile.reference）。image.tar 需外部渠道分发，仓库无法单独跑通（README/DEPLOY 已写明）。

## 4. 维护约定
- Windows: start.bat/stop.bat/status.bat；Linux/macOS: start.sh/stop.sh/status.sh（均有 ~%dp0 相对定位/自动开浏览器）
- 新增功能后同步 README/DEPLOY/本文件；提交 `git push origin main`；中文 UTF-8、bat 纯 ASCII+CRLF+无 BOM
