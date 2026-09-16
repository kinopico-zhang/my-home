"""单个音频文件的元数据读取 (mutagen) → ScannedTrack。

标签读取底座在 tag_readers, 兜底组装在 track_metadata, 内嵌封面抽取在
artwork_extractors; 这里聚合对外名面 (调用方统一 from ..library_tags
import …, 不感知内部分层)。
"""
from .artwork_extractors import extract_album_artwork
from .tag_readers import (_has_embedded_artwork, _read_tag,
                          read_track_credits)
from .track_metadata import (album_title_from_directory,
                             looks_like_synced_lyrics, read_track_metadata,
                             title_from_filename)

__all__ = [
    "_has_embedded_artwork", "_read_tag", "album_title_from_directory",
    "extract_album_artwork", "looks_like_synced_lyrics",
    "read_track_credits", "read_track_metadata", "title_from_filename",
]
