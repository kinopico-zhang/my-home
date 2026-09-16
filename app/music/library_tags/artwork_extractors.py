"""内嵌封面抽取: 各格式挑正面封面, 出原始图片字节。

flac pictures / ID3 APIC (mp3, dsf) / MP4 covr / APE 的 Cover Art 键
(ape, tak)。探测端 (tag_readers._has_embedded_artwork) 认得出的路,
这里都得能走通 —— 否则 has_artwork=1 却抽不出图, 前端裂一张 404。
"""
from pathlib import Path

from mutagen import File as load_audio_file, MutagenError


def extract_album_artwork(audio_path: Path) -> bytes | None:
    """抽内嵌封面字节, 读不出/打不开返回 None。"""
    try:
        audio = load_audio_file(audio_path)
    except (OSError, MutagenError):
        return None        # 文件没了/打不开: 当作没有封面
    if audio is None:
        return None
    return (_flac_artwork(audio) or _id3_artwork(audio)
            or _tag_dict_artwork(audio))


def _flac_artwork(audio: object) -> bytes | None:
    """flac: pictures 列表, type 3 (front cover) 优先。"""
    pictures = getattr(audio, "pictures", None) or ()
    for picture in pictures:
        if picture.type == 3 and picture.data:
            return bytes(picture.data)
    for picture in pictures:
        if picture.data:
            return bytes(picture.data)
    return None


def _id3_artwork(audio: object) -> bytes | None:
    """ID3 (mp3 / dsf): APIC 帧, type 3 (正面) 优先。"""
    tags = getattr(audio, "tags", None)
    if tags is None or not hasattr(tags, "getall"):
        return None
    for frame in tags.getall("APIC"):
        if frame.type == 3 and frame.data:
            return bytes(frame.data)
    for frame in tags.getall("APIC"):
        if frame.data:
            return bytes(frame.data)
    return None


def _tag_dict_artwork(audio: object) -> bytes | None:
    """字典式标签: MP4 的 covr; APE (ape / tak) 的 Cover Art 键,
    键名带 Front 的优先, 值里的 "文件名\\0" 前缀剥掉。"""
    tags = getattr(audio, "tags", None)
    if tags is None or not hasattr(tags, "get"):
        return None
    try:
        covers = tags.get("covr") or ()               # MP4
    except ValueError:                # vorbis 字典拒绝非 ASCII 键
        covers = ()
    for cover in covers:
        if bytes(cover):
            return bytes(cover)
    cover_keys = [str(key) for key in getattr(tags, "keys", lambda: ())()
                  if str(key).startswith("Cover Art")]
    for key in ([k for k in cover_keys if "front" in k.lower()]
                or cover_keys):
        value = tags.get(key)
        if value is None:
            continue
        image = _strip_ape_cover_name(bytes(getattr(value, "value", value)))
        if image:
            return image
    return None


def _strip_ape_cover_name(raw: bytes) -> bytes | None:
    """APE 封面值 = "文件名\\0图像字节"; 也有不带文件名直接写图像的, 都兜住。

    不是图像开头又切不出图像的, 当没有封面 (None)。"""
    if _looks_like_image(raw):
        return raw
    name_end = raw.find(b"\x00")
    if name_end >= 0 and _looks_like_image(raw[name_end + 1:]):
        return raw[name_end + 1:]
    return None


def _looks_like_image(data: bytes) -> bool:
    """常见封面图的魔数 (JPEG/PNG/GIF/WebP), 挡住空串/截断/纯文本。"""
    return (data.startswith(b"\xff\xd8")           # JPEG
            or data.startswith(b"\x89PNG")         # PNG
            or data.startswith(b"GIF8")            # GIF
            or (data.startswith(b"RIFF") and b"WEBP" in data[:16]))  # WebP
