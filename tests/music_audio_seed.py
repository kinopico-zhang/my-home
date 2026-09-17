"""My Music 测试助手: 手拼音频文件字节。

最小可读 FLAC (魔数 + STREAMINFO + VORBIS_COMMENT + PICTURE) 与 DSF
(ID3v2 尾块), 不依赖曲库真文件。拆自 test_music.py (结构化重构,
代码逐字节未动)。"""
import os
import struct
from pathlib import Path

PICTURE_BYTES = b"\xff\xd8\xff\xe0FAKEJPEG" + b"x" * 64
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"p" * 32


def _flac_bytes(tags: dict[str, str] | None, picture: bytes | None = None,
                total_samples: int = 88200) -> bytes:
    """最小可读 FLAC: 标题/歌词等全走 vorbis 注释块, 封面走 PICTURE 块。

    tags=None 时连 vorbis 块都不写 (audio.tags 为 None 的裸文件)。"""
    packed = (44100 << 44 | 1 << 41 | 15 << 36
              | total_samples).to_bytes(8, "big")
    streaminfo = ((4096).to_bytes(2, "big") + (4096).to_bytes(2, "big")
                  + (0).to_bytes(3, "big") + (0).to_bytes(3, "big")
                  + packed + bytes(16))
    blocks = [bytes([0]) + (34).to_bytes(3, "big") + streaminfo]
    if tags is not None:
        vendor = b"pytest"
        comments = b"".join(
            struct.pack("<I", len(f"{key}={value}".encode()))
            + f"{key}={value}".encode() for key, value in tags.items())
        vorbis = (struct.pack("<I", len(vendor)) + vendor
                  + struct.pack("<I", len(tags)) + comments)
        blocks.append(bytes([4]) + len(vorbis).to_bytes(3, "big") + vorbis)
    if picture is not None:
        mime = b"image/jpeg"
        picture_block = ((3).to_bytes(4, "big") + len(mime).to_bytes(4, "big")
                         + mime + (0).to_bytes(4, "big")
                         + (500).to_bytes(4, "big") + (500).to_bytes(4, "big")
                         + (24).to_bytes(4, "big") + (0).to_bytes(4, "big")
                         + len(picture).to_bytes(4, "big") + picture)
        blocks.append(bytes([6]) + len(picture_block).to_bytes(3, "big")
                      + picture_block)
    head, body = blocks[-1][:1], blocks[-1][1:]
    blocks[-1] = bytes([head[0] | 0x80]) + body      # 最后一块打 is_last 标记
    return b"fLaC" + b"".join(blocks)


def _write_audio(root: Path, relative_path: str, tags: dict[str, str] | None = None,
                 picture: bytes | None = None,
                 sidecar_lyrics: str | None = None,
                 mtime: float | None = None) -> Path:
    """往临时曲库放一个音频文件 (+可选同名 .lrc / 指定 mtime)。"""
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_flac_bytes(tags or {}, picture))
    if sidecar_lyrics is not None:
        path.with_suffix(".lrc").write_text(sidecar_lyrics, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path

def _syncsafe(value: int) -> bytes:
    """ID3v2.4 的同步安全整数 (7bit×4)。"""
    return bytes([(value >> 21) & 0x7f, (value >> 14) & 0x7f,
                  (value >> 7) & 0x7f, value & 0x7f])


def _id3_text_frame(frame_id: str, value: str) -> bytes:
    """v2.4 文本帧 (编码 3 = utf-8)。"""
    payload = b"\x03" + value.encode()
    return frame_id.encode() + _syncsafe(len(payload)) + b"\x00\x00" + payload


def _dsf_bytes(id3_tag: bytes) -> bytes:
    """最小 DSF: DSD 头 + fmt + data + 尾部 ID3v2.4 (mutagen 只读不验数据)。"""
    fmt = (b"fmt " + struct.pack("<Q", 52) + struct.pack("<IIIIII", 1, 0, 2, 2,
           2822400, 1) + struct.pack("<Q", 2822400)     # 采样率/样本数 = 1 秒
           + struct.pack("<II", 4096, 0))
    data = b"data" + struct.pack("<Q", 64) + bytes(64)
    metadata_offset = 28 + len(fmt) + len(data)
    header = b"DSD " + struct.pack("<QQQ", 28,
                                   metadata_offset + len(id3_tag),
                                   metadata_offset)
    return header + fmt + data + id3_tag


def _write_dsf_audio(root: Path, relative_path: str) -> Path:
    """DSF + 全套 ID3 帧 (TXXX:SCRIPT / USLT 歌词 / APIC 封面)。"""
    uslt = (b"USLT" + _syncsafe(len(b"\x03XXX\x00" + "DSDの歌詞".encode()))
            + b"\x00\x00" + b"\x03" + b"XXX" + b"\x00" + "DSDの歌詞".encode())
    apic = (b"APIC" + _syncsafe(len(b"\x03image/jpeg\x00\x03\x00"
                                    + PICTURE_BYTES)) + b"\x00\x00"
            + b"\x03" + b"image/jpeg" + b"\x00" + b"\x03" + b"\x00"
            + PICTURE_BYTES)
    script = (b"TXXX" + _syncsafe(len(b"\x03SCRIPT\x00Jpan")) + b"\x00\x00"
              + b"\x03" + b"SCRIPT\x00" + b"Jpan")
    frames = [_id3_text_frame(frame, value) for frame, value in (
        ("TIT2", "DSDの曲"), ("TPE1", "DSD歌手"), ("TALB", "DSD专辑"),
        ("TPE2", "DSD歌手"), ("TSO2", "DSD, Sort"), ("TSOP", "DSD, Sort"),
        ("TRCK", "5/10"), ("TPOS", "2"), ("TDRC", "2018-03-01"))]
    body = b"".join(frames) + script + uslt + apic
    tag = b"ID3\x04\x00\x00" + _syncsafe(len(body)) + body
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_dsf_bytes(tag))
    return path


def _write_plain_track(root: Path, relative_path: str, title: str,
                       mtime: float = 1000.0) -> None:
    """放一首无歌词无封面的 FLAC (设置/自动重扫用例的最小曲库)。"""
    _write_audio(root, relative_path,
                 {"TITLE": title, "ARTIST": "A乐队", "ALBUMARTIST": "A乐队",
                  "ALBUM": title + "的专辑", "DATE": "2001"}, mtime=mtime)
