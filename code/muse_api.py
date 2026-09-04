"""
MuseTalk API Service
Wrapper around original MuseTalk inference.py, exposing all parameters via REST API.
"""
import os
import sys
import time
import uuid
import json
import shutil
import glob
import copy
import pickle
import re
import threading
import subprocess
import traceback
from datetime import datetime

import cv2
import torch
import hashlib
import numpy as np
from tqdm import tqdm
from omegaconf import OmegaConf
from transformers import WhisperModel
from flask import Flask, request, jsonify, send_file, send_from_directory

# ── Path setup ──────────────────────────────────────────────
BASE_DIR = "/app/musetalk_original"
MODEL_DIR = "/app/musetalk_original/models"
os.chdir(BASE_DIR)  # Must be in musetalk_original for all relative model paths
sys.path.insert(0, BASE_DIR)

from musetalk.utils.blending import get_image, get_image_aligned
from musetalk.utils.face_parsing import FaceParsing
from musetalk.utils.audio_processor import AudioProcessor
from musetalk.utils.utils import get_file_type, get_video_fps, datagen, load_all_model
from musetalk.utils.preprocessing import get_landmark_and_bbox, read_imgs, coord_placeholder

# ── Config ───────────────────────────────────────────────────
UPLOAD_DIR = "/app/uploads"
OUTPUT_DIR = "/app/outputs"
RESULTS_DIR = "/app/results"
for d in [UPLOAD_DIR, OUTPUT_DIR, RESULTS_DIR]:
    os.makedirs(d, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 单文件上传上限 4GB


# ── API 统一 JSON 错误返回（避免前端拿到 HTML 错误页解析失败）─────
@app.errorhandler(404)
def _handle_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "接口不存在"}), 404
    return e


@app.errorhandler(413)
def _handle_413(e):
    return jsonify({"error": "上传文件过大（上限 4GB）"}), 413


@app.errorhandler(500)
def _handle_500(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "服务器内部错误，请查看容器日志 docker logs musetalk"}), 500
    return e

# ── Global model cache ───────────────────────────────────────
_model_cache = {
    "vae": None,
    "unet": None,
    "pe": None,
    "whisper": None,
    "audio_processor": None,
    "fp_v1": None,
    "fp_v15": None,
    "device": None,
    "weight_dtype": None,
    "ready": False,
}

# ── Task tracking ────────────────────────────────────────────
_tasks = {}
_tasks_lock = threading.Lock()
_cancel_events = {}  # task_id -> threading.Event() for cancellation
_gpu_slot = threading.Semaphore(1)  # GPU 同一时刻只跑一个任务，其余自动排队
_TASK_LIMIT = 100  # 内存中任务记录上限，防止长期运行内存泄漏


def _prune_tasks_locked():
    """调用前需持有 _tasks_lock：超出上限时清理最早的已结束任务记录。"""
    if len(_tasks) <= _TASK_LIMIT:
        return
    finished = sorted(
        (tid for tid, t in _tasks.items() if t["status"] in ("completed", "failed", "cancelled")),
        key=lambda tid: _tasks[tid].get("created_at", ""),
    )
    for tid in finished[: len(_tasks) - _TASK_LIMIT]:
        _tasks.pop(tid, None)


def _run_ffmpeg(args, what="ffmpeg"):
    """subprocess 列表参数执行 ffmpeg：路径含空格/中文/特殊字符也安全，失败给出明确报错。"""
    cmd = ["ffmpeg", "-y", "-v", "warning"] + args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-500:]
        raise RuntimeError(f"{what}失败 (exit {proc.returncode}): {tail}")


def _probe_duration(path):
    """ffprobe 读取媒体时长（秒），失败返回 None。"""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return round(float(proc.stdout.strip()), 2)
    except Exception:
        return None


def load_models():
    """Load all models once at startup."""
    global _model_cache
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    _model_cache["device"] = device

    print(f"[INIT] Device: {device}")

    # Load VAE + UNet + PE
    vae, unet, pe = load_all_model(
        unet_model_path=f"{MODEL_DIR}/musetalkV15/unet.pth",
        vae_type="sd-vae",
        unet_config=f"{MODEL_DIR}/musetalkV15/musetalk.json",
        device=device,
    )
    vae.vae = vae.vae.half()
    unet.model = unet.model.half()
    pe = pe.half()

    _model_cache["vae"] = vae
    _model_cache["unet"] = unet
    _model_cache["pe"] = pe
    _model_cache["weight_dtype"] = unet.model.dtype

    # Load Whisper
    whisper_dir = f"{MODEL_DIR}/whisper"
    audio_processor = AudioProcessor(feature_extractor_path=whisper_dir)
    whisper = WhisperModel.from_pretrained(whisper_dir)
    whisper = whisper.to(device=device, dtype=_model_cache["weight_dtype"]).eval()
    whisper.requires_grad_(False)

    _model_cache["audio_processor"] = audio_processor
    _model_cache["whisper"] = whisper

    # Load FaceParsing (v1 and v15) — cwd is already BASE_DIR so relative paths work
    fp_v1 = FaceParsing()
    fp_v15 = FaceParsing(left_cheek_width=90, right_cheek_width=90)
    _model_cache["fp_v1"] = fp_v1
    _model_cache["fp_v15"] = fp_v15

    _model_cache["ready"] = True
    print("[INIT] All models loaded successfully")


def _check_cancel(task_id):
    """Check if task was cancelled, raise CancelledError if so."""
    ev = _cancel_events.get(task_id)
    if ev and ev.is_set():
        raise Exception("CANCELLED_BY_USER")


# ── 提速缓存：人脸检测 + VAE 编码结果按视频文件缓存 ──────────
# 同一段形象视频第一次合成后，第二次起直接加载缓存，跳过最耗时的
# 人脸关键点检测(~2min) + VAE 编码，对话场景加速明显。
_CACHE_DIR = "/app/cache_preprocess"  # 独立于输出目录，避免被清理
os.makedirs(_CACHE_DIR, exist_ok=True)


def _video_cache_key(video_path, version, bbox_shift, extra_margin):
    """基于视频内容 + 参数生成缓存 key，内容变了自动失效。"""
    try:
        st = os.stat(video_path)
        # size + mtime 作为简易内容指纹 (够用且快)
        sig = f"{os.path.basename(video_path)}:{st.st_size}:{int(st.st_mtime)}:{version}:{bbox_shift}:{extra_margin}"
    except Exception:
        sig = f"{os.path.basename(video_path)}:unknown:{version}:{bbox_shift}:{extra_margin}"
    return hashlib.md5(sig.encode()).hexdigest()


def _load_preprocess_cache(cache_key):
    """加载缓存的 coord_list/frame_list/latents。返回 None 表示无缓存。"""
    pkl_path = os.path.join(_CACHE_DIR, f"{cache_key}.pkl")
    if not os.path.exists(pkl_path):
        return None
    try:
        with open(pkl_path, "rb") as f:
            data = pickle.load(f)
        # 校验字段齐全
        if not all(k in data for k in ("coord_list", "frame_list", "input_latent_list")):
            return None
        return data
    except Exception as e:
        print(f"[CACHE] load failed: {e}")
        return None


def _save_preprocess_cache(cache_key, coord_list, frame_list, input_latent_list):
    """保存预处理结果到磁盘缓存。"""
    pkl_path = os.path.join(_CACHE_DIR, f"{cache_key}.pkl")
    try:
        # 帧存 numpy 数组，latents 存 CPU tensor，避免 GPU 显存
        frame_list_cpu = [np.array(f) if isinstance(f, np.ndarray) else f for f in frame_list]
        latent_list_cpu = [l.detach().cpu() if hasattr(l, "detach") else l for l in input_latent_list]
        with open(pkl_path, "wb") as f:
            pickle.dump({
                "coord_list": coord_list,
                "frame_list": frame_list_cpu,
                "input_latent_list": latent_list_cpu,
            }, f, protocol=4)
        print(f"[CACHE] saved: {pkl_path}")
    except Exception as e:
        print(f"[CACHE] save failed: {e}")


def run_inference(task_id, params):
    """后台线程执行推理；GPU 同一时刻只跑一个任务，其余任务自动排队。"""
    try:
        with _tasks_lock:
            _tasks[task_id]["message"] = "排队等待 GPU..."
        _gpu_slot.acquire()
        try:
            _check_cancel(task_id)
            with _tasks_lock:
                _tasks[task_id]["status"] = "running"
                _tasks[task_id]["progress"] = 0
            _run_inference_inner(task_id, params)
        finally:
            _gpu_slot.release()
    except Exception as e:
        with _tasks_lock:
            if "CANCELLED_BY_USER" in str(e):
                _tasks[task_id]["status"] = "cancelled"
                _tasks[task_id]["message"] = "已取消"
            else:
                _tasks[task_id]["status"] = "failed"
                _tasks[task_id]["error"] = str(e)
                _tasks[task_id]["traceback"] = traceback.format_exc()
                print(f"[ERROR] Task {task_id}: {e}")
                print(traceback.format_exc())
    finally:
        _cancel_events.pop(task_id, None)
        # 上传的临时素材用完即删，避免 uploads 目录无限膨胀
        for key in ("video_path", "audio_path"):
            if params.get("uploaded_" + key) and os.path.isfile(params[key]):
                try:
                    os.remove(params[key])
                except OSError:
                    pass


def _run_inference_inner(task_id, params):
    """实际推理流程（已在 GPU 信号量保护内调用）。"""
    device = _model_cache["device"]
    vae = _model_cache["vae"]
    unet = _model_cache["unet"]
    pe = _model_cache["pe"]
    whisper = _model_cache["whisper"]
    audio_processor = _model_cache["audio_processor"]
    weight_dtype = _model_cache["weight_dtype"]

    version = params.get("version", "v15")
    fp = _model_cache["fp_v15"] if version == "v15" else _model_cache["fp_v1"]

    timesteps = torch.tensor([0], device=device)

    # ── Prepare paths ────────────────────────────────────
    video_path = params["video_path"]
    audio_path = params["audio_path"]
    result_dir = os.path.join(OUTPUT_DIR, task_id)
    os.makedirs(result_dir, exist_ok=True)
    save_dir_full = None  # 目录输入时不存在帧目录，避免清理阶段 UnboundLocalError

    # 探测音视频时长，音频比视频长时提前告知会回环续播
    video_dur = _probe_duration(video_path) if os.path.isfile(video_path) else None
    audio_dur = _probe_duration(audio_path)
    with _tasks_lock:
        _tasks[task_id]["info"]["video_duration"] = video_dur
        _tasks[task_id]["info"]["audio_duration"] = audio_dur
        if video_dur and audio_dur and audio_dur > video_dur + 0.3:
            _tasks[task_id]["info"]["warning"] = (
                f"音频 {audio_dur}s 超过视频画面 {video_dur}s，画面将自动回环续播"
            )

    input_basename = os.path.splitext(os.path.basename(video_path))[0]
    audio_basename = os.path.splitext(os.path.basename(audio_path))[0]
    output_basename = f"{input_basename}_{audio_basename}"

    result_img_save_path = os.path.join(result_dir, output_basename)
    os.makedirs(result_img_save_path, exist_ok=True)

    with _tasks_lock:
        _tasks[task_id]["progress"] = 5
    _check_cancel(task_id)

    # ── Extract frames ────────────────────────────────────
    _tasks[task_id]["message"] = "提取视频帧..."
    if get_file_type(video_path) == "video":
        save_dir_full = os.path.join(result_dir, input_basename)
        os.makedirs(save_dir_full, exist_ok=True)
        _run_ffmpeg(["-i", video_path, "-start_number", "0",
                     f"{save_dir_full}/%08d.png"], what="视频帧提取")
        input_img_list = sorted(glob.glob(os.path.join(save_dir_full, '*.[jpJP][pnPN]*[gG]')))
        if not input_img_list:
            raise ValueError("视频帧提取失败：ffmpeg 未产出任何帧，请检查视频文件是否损坏")
        fps = get_video_fps(video_path)
    elif os.path.isdir(video_path):
        input_img_list = sorted(glob.glob(os.path.join(video_path, '*.[jpJP][pnPN]*[gG]')))
        fps = params.get("fps", 25)
    else:
        raise ValueError("Unsupported video input")

    with _tasks_lock:
        _tasks[task_id]["progress"] = 10
        _tasks[task_id]["info"]["frame_count"] = len(input_img_list)
        _tasks[task_id]["info"]["fps"] = fps
    _check_cancel(task_id)

    # ── Extract audio features ────────────────────────────
    _tasks[task_id]["message"] = "提取音频特征..."
    whisper_input_features, librosa_length = audio_processor.get_audio_feature(audio_path)
    whisper_chunks = audio_processor.get_whisper_chunk(
        whisper_input_features, device, weight_dtype, whisper, librosa_length,
        fps=fps,
        audio_padding_length_left=params.get("audio_padding_left", 2),
        audio_padding_length_right=params.get("audio_padding_right", 2),
    )

    with _tasks_lock:
        _tasks[task_id]["progress"] = 15
    _check_cancel(task_id)

    # ── Face detection + VAE encode (带缓存) ──────────────
    bbox_shift = params.get("bbox_shift", 0)
    extra_margin = params.get("extra_margin", 10)
    cache_key = _video_cache_key(video_path, version, bbox_shift, extra_margin)
    cached = _load_preprocess_cache(cache_key)

    if cached is not None:
        _tasks[task_id]["message"] = "使用预处理缓存..."
        coord_list = cached["coord_list"]
        frame_list = cached["frame_list"]
        input_latent_list = cached["input_latent_list"]
        # latents 缓存的是 CPU tensor，转回 GPU
        input_latent_list = [l.to(device) for l in input_latent_list]
        with _tasks_lock:
            _tasks[task_id]["progress"] = 30
    else:
        _tasks[task_id]["message"] = "人脸关键点检测..."
        coord_list, frame_list = get_landmark_and_bbox(input_img_list, bbox_shift)

        with _tasks_lock:
            _tasks[task_id]["progress"] = 25
        _check_cancel(task_id)

        # ── Encode latents ────────────────────────────────────
        _tasks[task_id]["message"] = "VAE 编码..."
        input_latent_list = []
        for bbox, frame in zip(coord_list, frame_list):
            if bbox == coord_placeholder:
                continue
            x1, y1, x2, y2 = bbox
            if version == "v15":
                y2 = min(y2 + extra_margin, frame.shape[0])
            crop_frame = frame[y1:y2, x1:x2]
            crop_frame = cv2.resize(crop_frame, (256, 256), interpolation=cv2.INTER_LANCZOS4)
            latents = vae.get_latents_for_unet(crop_frame)
            input_latent_list.append(latents)

        # 后台存缓存，不阻塞主流程
        _save_preprocess_cache(cache_key, coord_list, frame_list, input_latent_list)

        with _tasks_lock:
            _tasks[task_id]["progress"] = 30
    _check_cancel(task_id)

    if not input_latent_list:
        raise ValueError("未检测到有效人脸，请确认素材画面中有清晰正脸")

    # ── 智能循环：音频 ≤ 视频长度时不循环，直接顺序播放 ──
    # 对话场景音频通常很短，视频帧够用；只有音频比视频长才循环画面
    video_num = len(whisper_chunks)  # 音频对应的帧数
    face_num = len(input_latent_list)  # 视频有效人脸帧数
    if face_num >= video_num:
        # 音频不超视频 → 顺序播放，不循环 (大提速)
        frame_list_cycle = frame_list[:video_num]
        coord_list_cycle = coord_list[:video_num]
        input_latent_list_cycle = input_latent_list[:video_num]
    else:
        # 音频比视频长 → 循环 + 反向回环保持无缝
        frame_list_cycle = (frame_list + frame_list[::-1]) * ((video_num // (face_num * 2)) + 1)
        coord_list_cycle = (coord_list + coord_list[::-1]) * ((video_num // (face_num * 2)) + 1)
        input_latent_list_cycle = (input_latent_list + input_latent_list[::-1]) * ((video_num // (face_num * 2)) + 1)
        frame_list_cycle = frame_list_cycle[:video_num]
        coord_list_cycle = coord_list_cycle[:video_num]
        input_latent_list_cycle = input_latent_list_cycle[:video_num]

    with _tasks_lock:
        _tasks[task_id]["progress"] = 35
    _check_cancel(task_id)

    # ── UNet inference ────────────────────────────────────
    _tasks[task_id]["message"] = "UNet 推理中..."
    video_num = len(whisper_chunks)
    batch_size = params.get("batch_size", 16)  # 4080 建议 16-32
    gen = datagen(
        whisper_chunks=whisper_chunks,
        vae_encode_latents=input_latent_list_cycle,
        batch_size=batch_size,
        delay_frame=0,
        device=device,
    )

    res_frame_list = []
    total_batches = int(np.ceil(float(video_num) / batch_size))

    for i, (whisper_batch, latent_batch) in enumerate(gen):
        audio_feature_batch = pe(whisper_batch)
        latent_batch = latent_batch.to(dtype=unet.model.dtype)
        pred_latents = unet.model(latent_batch, timesteps, encoder_hidden_states=audio_feature_batch).sample
        recon = vae.decode_latents(pred_latents)
        for res_frame in recon:
            res_frame_list.append(res_frame)

        pct = 35 + int(40 * (i + 1) / total_batches)
        with _tasks_lock:
            _tasks[task_id]["progress"] = pct
            _tasks[task_id]["message"] = f"UNet 推理中... ({i+1}/{total_batches})"
        _check_cancel(task_id)

    # ── Blend & composite ─────────────────────────────────
    _tasks[task_id]["message"] = "面部混合合成..."
    parsing_mode = params.get("parsing_mode", "jaw")
    blur_factor = params.get("blur_factor", 2) / 100.0  # API 传整数 (如2)，转成 0.02
    upper_boundary_ratio = params.get("upper_boundary_ratio", 0.5)  # already divided by 100 in api_synthesize
    texture_align = params.get("texture_align", True)  # 质感统一总开关 (默认开)
    noise_strength = float(params.get("noise_strength", 0.55))  # 噪点强度 0~1
    fast_blend = params.get("fast_blend", False)  # 极速模式: 跳过质感统一, 混合更快
    fallback_count = 0  # resize 等失败回退原帧的帧数（保持帧号连续，防止 ffmpeg 截断）
    for i, res_frame in enumerate(res_frame_list):
        bbox = coord_list_cycle[i % len(coord_list_cycle)]
        ori_frame = copy.deepcopy(frame_list_cycle[i % len(frame_list_cycle)])
        x1, y1, x2, y2 = bbox
        if version == "v15":
            y2 = min(y2 + extra_margin, frame_list[0].shape[0])
        resize_ok = True
        try:
            res_frame_resized = cv2.resize(res_frame.astype(np.uint8), (x2 - x1, y2 - y1))
        except Exception:
            resize_ok = False
            fallback_count += 1

        if not resize_ok:
            # 回退原帧而不是跳过：帧号 i 保持连续，ffmpeg 不会因缺帧截断视频
            combine_frame = ori_frame
        elif texture_align and not fast_blend:
            combine_frame = get_image_aligned(
                ori_frame, res_frame_resized, [x1, y1, x2, y2],
                mode=parsing_mode,
                fp=fp,
                blur_factor=blur_factor,
                upper_boundary_ratio=upper_boundary_ratio,
                color_match=True,
                noise_strength=noise_strength,
            )
        else:
            combine_frame = get_image(
                ori_frame, res_frame_resized, [x1, y1, x2, y2],
                mode=parsing_mode,
                fp=fp,
                blur_factor=blur_factor,
                upper_boundary_ratio=upper_boundary_ratio,
            )

        cv2.imwrite(f"{result_img_save_path}/{str(i).zfill(8)}.png", combine_frame)

        if i % 50 == 0:
            pct = 75 + int(10 * (i + 1) / len(res_frame_list))
            with _tasks_lock:
                _tasks[task_id]["progress"] = pct

    # ── Encode video + audio ──────────────────────────────
    _tasks[task_id]["message"] = "合成视频..."
    output_vid_name = os.path.join(result_dir, output_basename + ".mp4")
    temp_vid_path = os.path.join(result_dir, f"temp_{output_basename}.mp4")

    _run_ffmpeg([
        "-r", str(fps), "-f", "image2", "-i", f"{result_img_save_path}/%08d.png",
        "-vcodec", "libx264", "-vf", "format=yuv420p", "-crf", "18",
        temp_vid_path,
    ], what="帧序列合成视频")
    # 第二步直接 copy 视频流、只封装音轨：省掉一次全片重编码（更快且零画质损失），
    # +faststart 把索引放文件头，网页预览可秒开
    _run_ffmpeg([
        "-i", audio_path, "-i", temp_vid_path,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_vid_name,
    ], what="音视频封装")

    # Cleanup
    shutil.rmtree(result_img_save_path, ignore_errors=True)
    if os.path.exists(temp_vid_path):
        os.remove(temp_vid_path)
    if os.path.exists(save_dir_full):
        shutil.rmtree(save_dir_full, ignore_errors=True)

    with _tasks_lock:
        _tasks[task_id]["status"] = "completed"
        _tasks[task_id]["progress"] = 100
        _tasks[task_id]["message"] = "完成"
        _tasks[task_id]["result_file"] = output_vid_name
        _tasks[task_id]["result_filename"] = output_basename + ".mp4"
        if fallback_count:
            _tasks[task_id]["info"]["blend_fallback"] = fallback_count


# ═══════════════════════════════════════════════════════════════
#  API Routes
# ═══════════════════════════════════════════════════════════════

@app.route("/api/health")
def api_health():
    gpu_ok = torch.cuda.is_available()
    try:
        gpu_mem = f"{torch.cuda.memory_allocated() // 1024 // 1024}MB / {torch.cuda.get_device_properties(0).total_memory // 1024 // 1024}MB" if gpu_ok else "N/A"
    except Exception:
        gpu_mem = "N/A"
    device = _model_cache.get("device")
    reload_error = _model_cache.get("reload_error")
    with _tasks_lock:
        tasks_active = sum(1 for t in _tasks.values() if t["status"] in ("queued", "running"))
    return jsonify({
        "status": "ok" if _model_cache.get("ready") else ("error" if reload_error else "loading"),
        "model_ready": bool(_model_cache.get("ready")),
        "device": str(device) if device is not None else "N/A",
        "gpu_available": gpu_ok,
        "gpu_mem": gpu_mem,
        "tasks_active": tasks_active,
        "reload_error": reload_error,
    })


@app.route("/api/reload", methods=["POST"])
def api_reload():
    """Release all models from GPU memory and reload them."""
    global _model_cache
    try:
        # 有任务正在进行时禁止重载：否则运行中任务的模型会被抽走直接崩掉
        with _tasks_lock:
            active = [tid for tid, t in _tasks.items() if t["status"] in ("queued", "running")]
        if active:
            return jsonify({"error": f"有 {len(active)} 个任务正在进行，无法刷新模型；请先取消或等待完成"}), 409

        # Step 1: release all model references
        for k in list(_model_cache.keys()):
            del _model_cache[k]
        _model_cache["ready"] = False

        # Step 2: force GC + CUDA cache clear
        import gc
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.synchronize()

        # Step 3: reload models in background thread (takes ~90s)
        def _reload_bg():
            global _model_cache
            try:
                _model_cache.pop("reload_error", None)
                load_models()
            except Exception as e:
                _model_cache["reload_error"] = str(e)

        t = threading.Thread(target=_reload_bg, daemon=True)
        t.start()

        return jsonify({"status": "reloading", "message": "模型正在重新加载，约 90 秒后可用"})

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/params")
def api_params():
    """Return all available parameters with descriptions and ranges."""
    return jsonify({
        "presets": {
            "fast": {
                "label": "极速版",
                "desc": "batch_size=8 GPU加速, 锐利边缘, 约 6-8 分钟/250帧",
                "params": {"batch_size": 8, "blur_factor": 1, "extra_margin": 5, "parsing_mode": "jaw", "upper_boundary_ratio": 35},
            },
            "quality": {
                "label": "精修版",
                "desc": "batch_size=2 逐帧精细, 柔滑过渡, 约 10-12 分钟/250帧",
                "params": {"batch_size": 2, "blur_factor": 3, "extra_margin": 15, "parsing_mode": "neck", "upper_boundary_ratio": 55},
            },
            "turbo": {
                "label": "极速对话",
                "desc": "最快出片: batch_size=16, 跳过质感统一, 适合对话/批量场景",
                "params": {"batch_size": 16, "blur_factor": 1, "extra_margin": 5, "parsing_mode": "jaw", "upper_boundary_ratio": 30, "texture_align": False, "fast_blend": True},
            },
        },
        "version": {
            "type": "select",
            "options": ["v15", "v1"],
            "default": "v15",
            "label": "模型版本",
            "desc": "v15 口型更准确，v1 更稳定",
        },
        "bbox_shift": {
            "type": "range",
            "min": -15, "max": 15, "step": 1,
            "default": 0,
            "label": "人脸框偏移",
            "desc": "正数=框下移/嘴巴更张开，负数=框上移/嘴巴更闭合，(v15 固定为 0)",
        },
        "batch_size": {
            "type": "range",
            "min": 1, "max": 64, "step": 1,
            "default": 8,
            "label": "批大小",
            "desc": "越大越快但占显存越多，RTX3060 建议 4-8",
        },
        "extra_margin": {
            "type": "range",
            "min": 0, "max": 50, "step": 1,
            "default": 10,
            "label": "人脸额外边距",
            "desc": "裁剪人脸时下巴下方多留的像素",
        },
        "parsing_mode": {
            "type": "select",
            "options": ["jaw", "neck", "raw"],
            "default": "jaw",
            "label": "面部混合模式",
            "desc": "jaw=仅下巴区域替换，neck=含脖子，raw=整个面部",
        },
        "blur_factor": {
            "type": "range",
            "min": 1, "max": 10, "step": 1,
            "default": 2,
            "label": "边缘模糊程度",
            "desc": "1=最锐利，10=最柔和过渡，(百分数，内部 ×0.01)",
        },
        "upper_boundary_ratio": {
            "type": "range",
            "min": 30, "max": 70, "step": 5,
            "default": 50,
            "label": "上半脸保留比例(%)",
            "desc": "30=只替换下巴，70=替换更多脸部区域",
        },
        "left_cheek_width": {
            "type": "range",
            "min": 50, "max": 150, "step": 5,
            "default": 90,
            "label": "左脸颊宽度",
            "desc": "控制左脸混合区域，(v15 生效)",
        },
        "right_cheek_width": {
            "type": "range",
            "min": 50, "max": 150, "step": 5,
            "default": 90,
            "label": "右脸颊宽度",
            "desc": "控制右脸混合区域，(v15 生效)",
        },
        "fps": {
            "type": "number",
            "default": 25,
            "label": "输出帧率",
            "desc": "图片序列合成视频时使用",
        },
        "audio_padding_left": {
            "type": "range",
            "min": 0, "max": 10, "step": 1,
            "default": 2,
            "label": "音频左填充",
            "desc": "音频特征左侧额外帧数",
        },
        "audio_padding_right": {
            "type": "range",
            "min": 0, "max": 10, "step": 1,
            "default": 2,
            "label": "音频右填充",
            "desc": "音频特征右侧额外帧数",
        },
        "use_float16": {
            "type": "bool",
            "default": True,
            "label": "使用 FP16",
            "desc": "模型固定以 FP16 加载，此参数仅作兼容保留",
        },
        "texture_align": {
            "type": "bool",
            "default": True,
            "label": "质感统一",
            "desc": "色彩对齐+噪点重注入，消除嘴部与面部纹理差异 (推荐开启)",
        },
        "noise_strength": {
            "type": "range",
            "min": 0, "max": 100, "step": 5,
            "default": 55,
            "label": "噪点强度",
            "desc": "0=关闭质感统一, 55=适中(默认), 100=最强颗粒感",
        },
    })


@app.route("/api/synthesize", methods=["POST"])
def api_synthesize():
    if not _model_cache.get("ready"):
        return jsonify({"error": "模型尚未加载完成，请稍候"}), 503

    task_id = str(uuid.uuid4())[:8]

    # Handle file uploads
    video_file = request.files.get("video")
    audio_file = request.files.get("audio")

    if video_file:
        ext = os.path.splitext(video_file.filename)[1].lower()
        if not re.fullmatch(r"\.(mp4|avi|mov|mkv|webm|flv)", ext):
            ext = ".mp4"  # 扩展名白名单，防止拼接进 shell 命令
        video_path = os.path.join(UPLOAD_DIR, f"{task_id}_video{ext}")
        video_file.save(video_path)
    else:
        # Use path from existing files（限制在容器 /app 内，避免任意路径读取；允许图片序列目录）
        video_path = request.form.get("video_path", "")
        real = os.path.realpath(video_path) if video_path else ""
        if not real.startswith("/app/") or not (os.path.isfile(real) or os.path.isdir(real)):
            return jsonify({"error": "请上传视频文件或提供有效路径"}), 400
        video_path = real

    if audio_file:
        ext = os.path.splitext(audio_file.filename)[1].lower()
        if not re.fullmatch(r"\.(wav|mp3|flac|m4a|aac|ogg|opus)", ext):
            ext = ".wav"
        audio_path = os.path.join(UPLOAD_DIR, f"{task_id}_audio{ext}")
        audio_file.save(audio_path)
    else:
        audio_path = request.form.get("audio_path", "")
        real = os.path.realpath(audio_path) if audio_path else ""
        if not real.startswith("/app/") or not os.path.isfile(real):
            return jsonify({"error": "请上传音频文件或提供有效路径"}), 400
        audio_path = real

    # ── Preset modes ────────────────────────────────────────
    # Mode overrides individual params when specified
    PRESETS = {
        "fast": {
            "batch_size": 8,
            "blur_factor": 1,
            "extra_margin": 5,
            "parsing_mode": "jaw",
            "upper_boundary_ratio": 35,
        },
        "quality": {
            "batch_size": 2,
            "blur_factor": 3,
            "extra_margin": 15,
            "parsing_mode": "neck",
            "upper_boundary_ratio": 55,
        },
        "turbo": {
            # 极速对话模式：牺牲画面质量，追求最快出片
            "batch_size": 16,
            "blur_factor": 1,
            "extra_margin": 5,
            "parsing_mode": "jaw",
            "upper_boundary_ratio": 30,
            "texture_align": False,
            "fast_blend": True,
        },
    }

    mode = request.form.get("mode", "custom")
    defaults = {
        "version": request.form.get("version", "v15"),
        "bbox_shift": int(request.form.get("bbox_shift", 0)),
        "batch_size": int(request.form.get("batch_size", 8)),
        "extra_margin": int(request.form.get("extra_margin", 10)),
        "parsing_mode": request.form.get("parsing_mode", "jaw"),
        "blur_factor": int(request.form.get("blur_factor", 2)),
        "upper_boundary_ratio": int(request.form.get("upper_boundary_ratio", 50)),
        "left_cheek_width": int(request.form.get("left_cheek_width", 90)),
        "right_cheek_width": int(request.form.get("right_cheek_width", 90)),
        "fps": int(request.form.get("fps", 25)),
        "audio_padding_left": int(request.form.get("audio_padding_left", 2)),
        "audio_padding_right": int(request.form.get("audio_padding_right", 2)),
        "use_float16": request.form.get("use_float16", "true").lower() == "true",
        "texture_align": request.form.get("texture_align", "true").lower() == "true",
        "noise_strength": float(request.form.get("noise_strength", 55)) / 100.0,
        "fast_blend": request.form.get("fast_blend", "false").lower() == "true",
    }

    # Apply preset overrides if mode is set
    if mode in PRESETS:
        for k, v in PRESETS[mode].items():
            defaults[k] = v

    params = {
        "video_path": video_path,
        "audio_path": audio_path,
        **defaults,
    }
    params["upper_boundary_ratio"] = params["upper_boundary_ratio"] / 100.0
    # 标记哪些是本请求上传的临时文件，任务结束（含失败/取消）后自动删除
    params["uploaded_video_path"] = bool(video_file)
    params["uploaded_audio_path"] = bool(audio_file)

    with _tasks_lock:
        _tasks[task_id] = {
            "id": task_id,
            "status": "queued",
            "progress": 0,
            "message": "排队中...",
            "params": {k: v for k, v in params.items()
                       if k not in ["video_path", "audio_path",
                                    "uploaded_video_path", "uploaded_audio_path"]},
            "created_at": datetime.now().isoformat(),
            "info": {},
        }
        _prune_tasks_locked()
    _cancel_events[task_id] = threading.Event()

    # Start inference in background
    thread = threading.Thread(target=run_inference, args=(task_id, params), daemon=True)
    thread.start()

    return jsonify({
        "task_id": task_id,
        "status": "queued",
        "message": "任务已提交",
    })


@app.route("/api/status/<task_id>")
def api_status(task_id):
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify({
        "task_id": task["id"],
        "status": task["status"],
        "progress": task["progress"],
        "message": task.get("message", ""),
        "info": task.get("info", {}),
        "params": task.get("params", {}),
        "error": task.get("error"),
    })


@app.route("/api/cancel/<task_id>", methods=["POST"])
def api_cancel(task_id):
    """Cancel a running task."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    if task["status"] not in ("running", "queued"):
        return jsonify({"error": f"任务状态为 {task['status']}，无法取消"}), 400

    # Set cancel event
    ev = _cancel_events.get(task_id)
    if ev:
        ev.set()
    with _tasks_lock:
        _tasks[task_id]["message"] = "取消中..."

    return jsonify({"task_id": task_id, "status": "cancelling", "message": "正在取消..."})


@app.route("/api/tasks")
def api_tasks():
    """List recent tasks."""
    with _tasks_lock:
        tasks = [{
            "task_id": t["id"],
            "status": t["status"],
            "progress": t["progress"],
            "message": t.get("message", ""),
            "created_at": t.get("created_at", ""),
        } for t in list(reversed(list(_tasks.values())))[:20]]
    return jsonify({"tasks": tasks})


@app.route("/api/tasks/clear", methods=["POST"])
def api_tasks_clear():
    """清除已结束（完成/失败/取消）的任务记录。

    delete_files=true 时同时删除对应的输出目录（output/<task_id>/）；
    默认只清内存记录，输出文件保留在磁盘上。
    """
    delete_files = request.form.get("delete_files", "false").lower() == "true"
    removed = 0
    with _tasks_lock:
        done_tids = [tid for tid, t in _tasks.items()
                     if t["status"] in ("completed", "failed", "cancelled")]
        for tid in done_tids:
            _tasks.pop(tid, None)
            removed += 1
    if delete_files:
        for tid in done_tids:
            shutil.rmtree(os.path.join(OUTPUT_DIR, tid), ignore_errors=True)
    return jsonify({"cleared": removed, "files_deleted": delete_files})


@app.route("/api/download/<task_id>")
def api_download(task_id):
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task or task["status"] != "completed":
        return jsonify({"error": "任务未完成或不存在"}), 404

    result_file = task.get("result_file")
    if not result_file or not os.path.exists(result_file):
        return jsonify({"error": "结果文件不存在"}), 404

    filename = task.get("result_filename", "output.mp4")
    return send_file(result_file, as_attachment=True, download_name=filename)


@app.route("/api/files")
def api_files():
    """List available input files (video + audio) for quick selection.

    Scans three directories:
      - /app/data       (compose 挂载 ./data 目录)
      - /app/materials  (可选素材目录，挂载方式见 docker-compose.yml)
      - /app/input      (compose 挂载 ./input 目录)
    Each entry includes a "src" tag, file size (MB) and duration (秒, ffprobe 探测)。
    """
    files = {"videos": [], "audios": []}
    video_exts = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    audio_exts = {".wav", ".mp3", ".flac", ".m4a", ".aac"}
    scan_dirs = [
        ("/app/data", "data"),
        ("/app/materials", "materials"),
        ("/app/input", "input"),
    ]
    for data_dir, src in scan_dirs:
        if not os.path.isdir(data_dir):
            continue
        try:
            for f in sorted(os.listdir(data_dir)):
                path = os.path.join(data_dir, f)
                if not os.path.isfile(path):
                    continue
                ext = os.path.splitext(f)[1].lower()
                if ext not in video_exts and ext not in audio_exts:
                    continue
                try:
                    size_mb = round(os.path.getsize(path) / 1048576, 1)
                    mtime = int(os.path.getmtime(path))
                except OSError:
                    continue
                entry = {
                    "name": f, "path": path, "src": src,
                    "size_mb": size_mb, "mtime": mtime,
                    "duration": _probe_duration(path),
                }
                if ext in video_exts:
                    files["videos"].append(entry)
                else:
                    files["audios"].append(entry)
        except Exception as e:
            print(f"[WARN] scan {data_dir} failed: {e}")
    # 最近改动的排前面，方便找到刚放进去的素材
    files["videos"].sort(key=lambda x: -x["mtime"])
    files["audios"].sort(key=lambda x: -x["mtime"])
    return jsonify(files)


# ── 预处理缓存管理 ────────────────────────────────────────────
def _cache_stats():
    total, count = 0, 0
    for f in glob.glob(os.path.join(_CACHE_DIR, "*.pkl")):
        try:
            total += os.path.getsize(f)
            count += 1
        except OSError:
            pass
    return {"count": count, "size_mb": round(total / 1048576, 1), "dir": _CACHE_DIR}


@app.route("/api/cache")
def api_cache():
    """预处理缓存（人脸检测+VAE编码）占用情况。"""
    return jsonify(_cache_stats())


@app.route("/api/cache/clear", methods=["POST"])
def api_cache_clear():
    """清空预处理缓存。缓存可随时重建，只影响下次同素材首次合成的速度。"""
    removed = 0
    for f in glob.glob(os.path.join(_CACHE_DIR, "*.pkl")):
        try:
            os.remove(f)
            removed += 1
        except OSError:
            pass
    return jsonify({"removed": removed, **_cache_stats()})


@app.route("/api/preview/<task_id>")
def api_preview(task_id):
    """Stream result video for preview (not download)."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task or task["status"] != "completed":
        return jsonify({"error": "任务未完成"}), 404

    result_file = task.get("result_file")
    if not result_file or not os.path.exists(result_file):
        return jsonify({"error": "结果文件不存在"}), 404

    return send_file(result_file, mimetype="video/mp4")


# ── Static frontend ───────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("/app/static", "index.html")


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("MuseTalk API Service")
    print("=" * 60)
    load_models()
    print(f"[READY] API server starting on port 5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
