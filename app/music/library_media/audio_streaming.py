"""曲目音频流: 按 Range 分段流 (iOS Safari 的 <audio> 必须支持 206)。"""
import re
from pathlib import Path
from typing import Iterator

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..library_database import Track, music_directory

_STREAM_CHUNK_BYTES = 256 * 1024
# 浏览器播不了的格式 (tak/dsf/ape) 也照给: 前端置灰, 下载仍可用
_CONTENT_TYPES = {
    "flac": "audio/flac", "mp3": "audio/mpeg", "m4a": "audio/mp4",
    "ogg": "audio/ogg", "opus": "audio/ogg", "wav": "audio/wav",
    "aac": "audio/aac",
    "tak": "application/octet-stream", "dsf": "application/octet-stream",
    "ape": "application/octet-stream",
}
_RANGE_HEADER_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")


class ByteRange(BaseModel):
    """解析出来的 Range 请求 (end 含端点)。"""

    start: int
    end: int
    total: int


def parse_range_header(header: str, total: int) -> ByteRange | None:
    """Range 头 → 区间; 格式非法返回 None (按无 Range 应答 200)。

    'bytes=0-1' 常规区间; 'bytes=500-' 到结尾; 'bytes=-500' 最后 500 字节。"""
    match = _RANGE_HEADER_PATTERN.match(header.strip())
    if match is None:
        return None
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return None
    if not start_text:                       # 尾缀区间
        length = int(end_text)
        if length == 0:
            raise _unsatisfiable(total)
        return ByteRange(start=max(0, total - length), end=total - 1,
                         total=total)
    start = int(start_text)
    if start >= total:
        raise _unsatisfiable(total)
    end = min(int(end_text), total - 1) if end_text else total - 1
    return ByteRange(start=start, end=end, total=total)


def _unsatisfiable(total: int) -> HTTPException:
    """Range 越界 → 416 (带 Content-Range 告诉总长)。"""
    return HTTPException(416, detail="Range 越界",
                         headers={"Content-Range": f"bytes */{total}"})


def _file_slice(path: Path, start: int, end: int) -> Iterator[bytes]:
    """从 start 读到 end (含端点), 分段产出。"""
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = handle.read(min(_STREAM_CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def stream_track(session: Session, track_id: int,
                 range_header: str | None) -> Response:
    """曲目流: 有合法 Range 答 206 分段, 没有/格式非法答 200 全量。"""
    track = session.get(Track, track_id)
    if track is None:
        raise HTTPException(404, "曲目不存在")
    path = music_directory() / track.file_path
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    total = path.stat().st_size
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": _CONTENT_TYPES.get(track.file_format,
                                           "application/octet-stream"),
        "Cache-Control": "no-store",
    }
    byte_range = (parse_range_header(range_header, total)
                  if range_header else None)
    if byte_range is None:
        return StreamingResponse(
            _file_slice(path, 0, total - 1),
            headers={**headers, "Content-Length": str(total)})
    return StreamingResponse(
        _file_slice(path, byte_range.start, byte_range.end),
        status_code=206,
        headers={
            **headers,
            "Content-Length": str(byte_range.end - byte_range.start + 1),
            "Content-Range": (f"bytes {byte_range.start}-{byte_range.end}"
                              f"/{byte_range.total}")})
