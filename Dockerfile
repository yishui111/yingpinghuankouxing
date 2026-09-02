# ============================================================
#  MuseTalk Platform Dockerfile（备用构建文件）
#  基于本地基础镜像 musetalk-api-fixed-librosa（内部含 MuseTalk 引擎
#  代码与模型，不随本仓库分发），补装运行 API 所需的全部依赖。
#  日常使用无需构建：下载 image.tar 并 docker load 即可（见 README/DEPLOY）。
#  如需从零重建镜像，参考同目录 Dockerfile.reference，并自行准备
#  musetalk_original（官方 MuseTalk 代码）与模型权重。
# ============================================================
FROM musetalk-api-fixed-librosa

# 切换到 root 以确保系统级安装
USER root

# 安装 MuseTalk API 运行所需的额外 Python 包
RUN pip3 install --no-cache-dir \
    omegaconf==2.3.0 \
    scipy==1.15.2 \
    scikit-image==0.25.2 \
    face-alignment==1.4.1 \
    kornia==0.8.1 \
    python-speech-features==0.6 \
    easydict==1.13 \
    einops==0.8.1 \
    librosa==0.10.2.post1 \
    resampy==0.4.3 \
    soundfile==0.13.1 \
    matplotlib==3.10.1 \
    tensorboard==2.19.0 \
    accelerate==1.6.0 \
    av==14.2.0

# mmcv 从 openmmlab 预编译索引安装
RUN pip3 install --no-cache-dir mmcv \
    -f https://download.openmmlab.com/mmcv/dist/cu121/torch2.4.0/index.html

# mmdet + mmpose（先修复 pip 模块问题，再装 xtcocotools 依赖、最后装 mmdet/mmpose）
RUN pip3 install --no-cache-dir pip --upgrade \
    && pip3 install --no-cache-dir xtcocotools \
    && pip3 install --no-cache-dir \
        mmdet==3.3.0 \
        mmpose==1.3.2

# Patch mmdet 版本检查
RUN sed -i "s/parse_version('2.2.0')/parse_version('2.3.0')/g" /usr/local/lib/python3.10/dist-packages/mmdet/__init__.py

# 切回 musetalk 用户
USER musetalk

CMD ["python3", "main.py"]
