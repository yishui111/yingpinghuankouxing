from PIL import Image
import numpy as np
import cv2
import copy


def get_crop_box(box, expand):
    x, y, x1, y1 = box
    x_c, y_c = (x+x1)//2, (y+y1)//2
    w, h = x1-x, y1-y
    s = int(max(w, h)//2*expand)
    crop_box = [x_c-s, y_c-s, x_c+s, y_c+s]
    return crop_box, s


def face_seg(image, mode="raw", fp=None):
    seg_image = fp(image, mode=mode)
    if seg_image is None:
        print("error, no person_segment")
        return None
    seg_image = seg_image.resize(image.size)
    return seg_image


def _blur_kernel(blur_factor, shape):
    """高斯模糊核尺寸：按 blur_factor 计算并钳制到图像尺寸内（cv2 要求核 < 图像）。"""
    size = min(int(blur_factor * shape[0] // 2 * 2) + 1, max(min(shape) - 1, 1))
    if size % 2 == 0:
        size -= 1
    return max(size, 1)


def get_image(image, face, face_box, upper_boundary_ratio=0.5, expand=1.5, mode="raw", fp=None, blur_factor=0.02):
    """
    Args:
        blur_factor (float): 高斯模糊核系数，0.01=最锐利, 0.05=柔和, 默认0.02
        upper_boundary_ratio (float): 上半脸保留比例，0.3=只替换下巴, 0.5=替换下半脸, 0.7=替换更多
    """
    body = Image.fromarray(image[:, :, ::-1])
    face = Image.fromarray(face[:, :, ::-1])

    x, y, x1, y1 = face_box
    crop_box, s = get_crop_box(face_box, expand)
    x_s, y_s, x_e, y_e = crop_box
    face_position = (x, y)

    face_large = body.crop(crop_box)
    ori_shape = face_large.size

    mask_image = face_seg(face_large, mode=mode, fp=fp)

    mask_small = mask_image.crop((x - x_s, y - y_s, x1 - x_s, y1 - y_s))
    mask_image = Image.new('L', ori_shape, 0)
    mask_image.paste(mask_small, (x - x_s, y - y_s, x1 - x_s, y1 - y_s))

    width, height = mask_image.size
    top_boundary = int(height * upper_boundary_ratio)
    modified_mask_image = Image.new('L', ori_shape, 0)
    modified_mask_image.paste(mask_image.crop((0, top_boundary, width, height)), (0, top_boundary))

    blur_kernel_size = _blur_kernel(blur_factor, ori_shape)
    mask_array = cv2.GaussianBlur(np.array(modified_mask_image), (blur_kernel_size, blur_kernel_size), 0)
    mask_image = Image.fromarray(mask_array)

    face_large.paste(face, (x - x_s, y - y_s, x1 - x_s, y1 - y_s))
    body.paste(face_large, crop_box[:2], mask_image)
    body = np.array(body)

    return body[:, :, ::-1]


def _color_match(src, ref, mask):
    """色彩/亮度对齐：把 src 中 mask 覆盖区域的颜色分布，线性变换到与 ref 一致。
    解决"重绘区域颜色与原视频分层"的问题。

    关键：变换结果只在 mask 覆盖区域生效，mask 外保持原图，
    避免 crop 方形边界处出现色差"方框"。
    """
    src_float = src.astype(np.float32)
    ref_float = ref.astype(np.float32)
    mask_f = (mask[..., None] / 255.0).astype(np.float32)

    wsum = mask_f.sum(axis=(0, 1), keepdims=True) + 1e-6
    src_mean = (src_float * mask_f).sum(axis=(0, 1), keepdims=True) / wsum
    ref_mean = (ref_float * mask_f).sum(axis=(0, 1), keepdims=True) / wsum
    src_var = ((src_float - src_mean) ** 2 * mask_f).sum(axis=(0, 1), keepdims=True) / wsum + 1e-6
    ref_var = ((ref_float - ref_mean) ** 2 * mask_f).sum(axis=(0, 1), keepdims=True) / wsum + 1e-6
    src_std = np.sqrt(src_var)
    ref_std = np.sqrt(ref_var)

    scale = ref_std / src_std
    matched = (src_float - src_mean) * scale + ref_mean
    # 只在 mask 区域应用变换，mask 外保留原图（消除方形边界）
    out = src_float * (1.0 - mask_f) + matched * mask_f
    out = np.clip(out, 0, 255).astype(np.uint8)
    return out


def _reinject_noise(src, ref, mask, sigma_high=3.0, sigma_low=0.8, strength=0.55):
    """噪点重注入：从参考帧(ref)提取高频细节，叠加回 src 的 mask 区域。
    让重绘区域拥有与原视频一致的"皮肤颗粒/噪点质感"，消除磨皮感。
    """
    gray_ref = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.float32)
    high_ref = cv2.GaussianBlur(gray_ref, (0, 0), sigma_high) - cv2.GaussianBlur(gray_ref, (0, 0), sigma_low)
    high_ref = np.clip(high_ref * strength, -30, 30)

    mask_f = (mask[..., None] / 255.0).astype(np.float32)
    src_float = src.astype(np.float32)
    out = src_float + high_ref[..., None] * mask_f
    out = np.clip(out, 0, 255).astype(np.uint8)
    return out


def get_image_aligned(image, face, face_box, upper_boundary_ratio=0.5, expand=1.5, mode="raw", fp=None, blur_factor=0.02, texture_align=True, color_match=True, noise_strength=0.55):
    """get_image 的质感增强版：色彩对齐 + 噪点重注入。

    与原版 get_image 相同的调用方式，仅在贴回前多了两步后处理：
      1. color_match    — 重绘区域颜色/明暗对齐到原帧 (消除颜色分层)
      2. noise_reinject — 从原帧提取高频颗粒噪点叠加回重绘区域 (消除磨皮感)

    新增可选参数（默认开启）：
      texture_align (bool): 总开关
      color_match   (bool): 是否做色彩对齐
      noise_strength (float): 噪点强度, 0=关, 0.3=轻, 0.55=适中, 0.8=强
    """
    body = Image.fromarray(image[:, :, ::-1])
    face = Image.fromarray(face[:, :, ::-1])

    x, y, x1, y1 = face_box
    crop_box, s = get_crop_box(face_box, expand)
    x_s, y_s, x_e, y_e = crop_box
    face_position = (x, y)

    face_large = body.crop(crop_box)
    ori_shape = face_large.size

    mask_image = face_seg(face_large, mode=mode, fp=fp)

    mask_small = mask_image.crop((x - x_s, y - y_s, x1 - x_s, y1 - y_s))
    mask_image = Image.new('L', ori_shape, 0)
    mask_image.paste(mask_small, (x - x_s, y - y_s, x1 - x_s, y1 - y_s))

    width, height = mask_image.size
    top_boundary = int(height * upper_boundary_ratio)
    modified_mask_image = Image.new('L', ori_shape, 0)
    modified_mask_image.paste(mask_image.crop((0, top_boundary, width, height)), (0, top_boundary))

    blur_kernel_size = _blur_kernel(blur_factor, ori_shape)
    mask_array = cv2.GaussianBlur(np.array(modified_mask_image), (blur_kernel_size, blur_kernel_size), 0)
    mask_image = Image.fromarray(mask_array)

    # 在 crop 区域(face_large)内做质感统一：mask 与 face_large 同尺寸，无坐标偏移问题
    if texture_align:
        ref_np = np.array(body.crop(crop_box))[:, :, ::-1].copy()  # 原帧 crop 参考 (BGR)
        mask_np = np.array(mask_image)  # L, 0-255, 与 face_large 同尺寸

        # 先贴重绘人脸到 crop 区域
        face_large.paste(face, (x - x_s, y - y_s, x1 - x_s, y1 - y_s))
        blended_bgr = np.array(face_large)[:, :, ::-1].copy()

        if color_match:
            blended_bgr = _color_match(blended_bgr, ref_np, mask_np)
        blended_bgr = _reinject_noise(blended_bgr, ref_np, mask_np, strength=noise_strength)

        # 转回 RGB 贴回 crop
        face_large = Image.fromarray(blended_bgr[:, :, ::-1])
    else:
        face_large.paste(face, (x - x_s, y - y_s, x1 - x_s, y1 - y_s))

    body.paste(face_large, crop_box[:2], mask_image)
    body = np.array(body)

    return body[:, :, ::-1]


def get_image_blending(image, face, face_box, mask_array, crop_box, texture_align=True, color_match=True, noise_strength=0.55):
    """带质感统一的面部混合。

    相比原版 get_image / get_image_blending 的"直接贴回"，新增两步后处理：
      1. color_match   — 重绘区域颜色/明暗对齐到原帧 (消除颜色分层)
      2. noise_reinject — 从原帧提取高频颗粒噪点叠加回重绘区域 (消除磨皮感)

    用法与参数保持兼容；texture_align=True 时启用增强。
    """
    body = Image.fromarray(image[:, :, ::-1])
    face = Image.fromarray(face[:, :, ::-1])

    x, y, x1, y1 = face_box
    x_s, y_s, x_e, y_e = crop_box
    face_large = body.crop(crop_box)

    mask_image = Image.fromarray(mask_array)
    mask_image = mask_image.convert("L")
    face_large.paste(face, (x - x_s, y - y_s, x1 - x_s, y1 - y_s))

    # 合成区域
    blended = np.array(face_large)[:, :, ::-1]  # BGR

    if texture_align:
        # 原帧的 crop 区域 (BGR) 作为颜色/质感参考
        ref = np.array(body.crop(crop_box))[:, :, ::-1]
        mask_np = np.array(mask_image)  # L, 0-255

        if color_match:
            blended = _color_match(blended, ref, mask_np)
        blended = _reinject_noise(blended, ref, mask_np, strength=noise_strength)

    # 贴回
    blended_pil = Image.fromarray(blended[:, :, ::-1])
    face_large.paste(blended_pil, (0, 0), mask_image)
    body.paste(face_large, crop_box[:2], mask_image)
    body = np.array(body)
    return body[:, :, ::-1]


def get_image_prepare_material(image, face_box, upper_boundary_ratio=0.5, expand=1.5, fp=None, mode="raw", blur_factor=0.04):
    body = Image.fromarray(image[:,:,::-1])

    x, y, x1, y1 = face_box
    crop_box, s = get_crop_box(face_box, expand)
    x_s, y_s, x_e, y_e = crop_box

    face_large = body.crop(crop_box)
    ori_shape = face_large.size

    mask_image = face_seg(face_large, mode=mode, fp=fp)
    mask_small = mask_image.crop((x-x_s, y-y_s, x1-x_s, y1-y_s))
    mask_image = Image.new('L', ori_shape, 0)
    mask_image.paste(mask_small, (x-x_s, y-y_s, x1-x_s, y1-y_s))

    width, height = mask_image.size
    top_boundary = int(height * upper_boundary_ratio)
    modified_mask_image = Image.new('L', ori_shape, 0)
    modified_mask_image.paste(mask_image.crop((0, top_boundary, width, height)), (0, top_boundary))

    blur_kernel_size = _blur_kernel(blur_factor, ori_shape)
    mask_array = cv2.GaussianBlur(np.array(modified_mask_image), (blur_kernel_size, blur_kernel_size), 0)
    return mask_array, crop_box
