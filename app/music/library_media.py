"""媒体流: 音频按 Range 分段流 (iOS Safari 的 <audio> 必须支持 206),
专辑封面从 FLAC 内嵌抽取后缓存到 data/music-art/ (曲库本体只读)。
"""
import re
from pathlib import Path
from typing import Iterator

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .library_database import (Album, Artist, Track, artwork_cache_directory,
                               music_directory)
from .library_tags import extract_album_artwork

_STREAM_CHUNK_BYTES = 256 * 1024
# 浏览器播不了的格式 (tak/dsf/ape) 也照给: 前端置灰, 下载仍可用
_CONTENT_TYPES = {
    "flac": "audio/flac", "mp3": "audio/mpeg", "m4a": "audio/mp4",
    "ogg": "audio/ogg", "opus": "audio/ogg", "wav": "audio/wav",
    "aac": "audio/aac",
    "tak": "application/octet-stream", "dsf": "application/octet-stream",
    "ape": "application/octet-stream",
}
_POSTER_CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                         ".png": "image/png", ".webp": "image/webp"}
_RANGE_HEADER_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
_LONG_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


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


def _first_artwork_track(session: Session, album_id: int) -> Track | None:
    """专辑里第一首有内嵌封面的曲目 (碟号/音轨序)。"""
    return session.execute(
        select(Track).where(Track.album_id == album_id,
                            Track.has_artwork.is_(True))
        .order_by(Track.disc_number, Track.track_number, Track.id)
        .limit(1)).scalar_one_or_none()


def album_artwork_response(session: Session, album_id: int) -> Response:
    """专辑封面: 优先缓存, 失效/没有就抽一遍 (抽不出 404, 前端放占位图)。

    有效性 = 缓存文件 mtime ≥ 专辑 added_at (专辑进了新文件就重抽);
    URL 带 ?v={added_at} 作版本, 应答可长缓存。"""
    album = session.get(Album, album_id)
    if album is None:
        raise HTTPException(404, "专辑不存在")
    cache_path = artwork_cache_directory() / f"album-{album_id}.jpg"
    if not (cache_path.is_file()
            and cache_path.stat().st_mtime >= album.added_at):
        track = _first_artwork_track(session, album_id)
        if track is None:
            raise HTTPException(404, "没有封面")
        artwork = extract_album_artwork(
            music_directory() / track.file_path)
        if artwork is None:
            raise HTTPException(404, "封面抽取失败")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_suffix(".tmp")
        temporary_path.write_bytes(artwork)
        temporary_path.replace(cache_path)
    return FileResponse(cache_path, media_type="image/jpeg",
                        headers=_LONG_CACHE_HEADERS)


def artist_artwork_response(session: Session, artist_id: int) -> Response:
    """艺人海报: 曲库里现成的 poster.* 文件, 直接透传 (没有 404)。"""
    artist = session.get(Artist, artist_id)
    if artist is None or not artist.poster_file:
        raise HTTPException(404, "没有海报")
    poster_path = (music_directory() / artist.directory
                   / artist.poster_file)
    if not poster_path.is_file():
        raise HTTPException(404, "海报文件不存在")
    media_type = _POSTER_CONTENT_TYPES.get(poster_path.suffix.lower(),
                                           "application/octet-stream")
    return FileResponse(poster_path, media_type=media_type,
                        headers=_LONG_CACHE_HEADERS)
