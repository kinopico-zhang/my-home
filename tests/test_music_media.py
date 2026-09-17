"""My Music 媒体流测试: Range 头解析 + 媒体接口边界 (DSF/M4a/
无封面/超长标题等)。"""

import pytest
from fastapi import HTTPException

from app.music.library_media import parse_range_header
from tests.music_audio_seed import PICTURE_BYTES, _write_dsf_audio
from tests.music_library_helpers import _make_library, _wait_scan_done


# ---------------------------------------------------------------- Range 流

def test_parse_range_header():
    """Range 解析: 常规/开放/尾缀区间, 非法格式, 越界 416。"""
    total = 1000
    first = parse_range_header("bytes=0-1", total)
    assert first is not None and first.model_dump() == {
        "start": 0, "end": 1, "total": total}
    second = parse_range_header("bytes=10-", total)
    assert second is not None and second.model_dump() == {
        "start": 10, "end": 999, "total": total}
    suffix = parse_range_header("bytes=-100", total)
    assert suffix is not None and suffix.model_dump() == {
        "start": 900, "end": 999, "total": total}
    overflow = parse_range_header(      # 越界终点截到文件尾
        "bytes=990-2000", total)
    assert overflow is not None and overflow.end == 999
    assert parse_range_header("not-bytes", total) is None
    assert parse_range_header("bytes=-", total) is None
    with pytest.raises(HTTPException) as exc_info:
        parse_range_header("bytes=1000-", total)     # 起点即越界
    assert exc_info.value.status_code == 416
    with pytest.raises(HTTPException):
        parse_range_header("bytes=-0", total)


def test_media_edge_cases(auth, tmp_path):
    """媒体边界: DSF 的 APIC 封面抽得出 / 封面缓存命中 / 海报缺失 / 源文件被删。"""
    from app.music.library_media import _file_slice  # noqa: SLF001
    root = tmp_path / "music-library"
    _make_library(root)
    _write_dsf_audio(root, "DSF艺人/2018 DSDの作品 [dddd4444]/01 DSDの曲.dsf")
    assert auth.post("/music/api/rescan").status_code == 200
    _wait_scan_done(auth)
    status = auth.get("/music/api/status").json()
    assert status["track_count"] == 5 and status["album_count"] == 4

    albums = {album["title"]: album["album_id"]
              for album in auth.get("/music/api/albums").json()["albums"]}
    # DSF 的封面走 ID3 APIC, 一样抽得出 (1.4.1 起不止 FLAC)
    assert auth.get(
        f"/music/media/albums/{albums['DSD专辑']}/artwork"
    ).content == PICTURE_BYTES
    assert auth.get("/music/media/albums/99999/artwork").status_code == 404

    # 甲的封面: 第一次抽取落缓存, 第二次直接命中缓存文件
    assert auth.get(
        f"/music/media/albums/{albums['甲']}/artwork").content == PICTURE_BYTES
    assert auth.get(
        f"/music/media/albums/{albums['甲']}/artwork").content == PICTURE_BYTES

    # 艺人海报: 没海报的 404; 有海报但文件被删 404
    artists = {artist["name"]: artist["artist_id"]
               for artist in auth.get("/music/api/artists").json()["artists"]}
    assert auth.get(
        f"/music/media/artists/{artists['老歌手']}/artwork").status_code == 404
    (root / "AI机组/poster.jpeg").unlink()
    assert auth.get(
        f"/music/media/artists/{artists['AI机组']}/artwork").status_code == 404
    assert auth.get("/music/media/artists/99999/artwork").status_code == 404

    # 艺人详情 (年份倒序) + 单曲歌词的成功路径
    artist_page = auth.get(f"/music/api/artists/{artists['AI机组']}").json()
    assert [album["title"] for album in artist_page["albums"]] == ["乙", "甲"]
    tracks = auth.get("/music/api/tracks").json()["tracks"]
    qu_b = next(track for track in tracks if track["title"] == "曲B")
    lyrics = auth.get(f"/music/api/tracks/{qu_b['track_id']}/lyrics").json()
    assert lyrics["lyrics_synced"] and "乙の歌詞" in lyrics["lyrics"]

    # 作词/作曲 (全屏播放页来源行): 带标签的读得出来, 没标签的空串
    qu_a = next(track for track in tracks if track["title"] == "曲A")
    got_credits = auth.get(f"/music/api/tracks/{qu_a['track_id']}/credits").json()
    assert got_credits == {"lyricist": "词人甲", "composer": "曲人乙"}
    assert auth.get(f"/music/api/tracks/{qu_b['track_id']}/credits").json() \
        == {"lyricist": "", "composer": ""}

    # 源文件被删 (索引还在): 流 404; 尾缀 Range 比文件长 → 从 0 开始的 206
    dsf_track = next(track for track in tracks
                     if track["file_format"] == "dsf")
    suffix = auth.get(f"/music/media/stream/{dsf_track['track_id']}",
                      headers={"Range": "bytes=-999999"})
    assert suffix.status_code == 206 and suffix.content == auth.get(
        f"/music/media/stream/{dsf_track['track_id']}").content
    (root / "DSF艺人/2018 DSDの作品 [dddd4444]/01 DSDの曲.dsf").unlink()
    assert auth.get(
        f"/music/media/stream/{dsf_track['track_id']}").status_code == 404

    # _file_slice 读过文件尾: 产出到 EOF 就收手, 不无限读
    flac = root / "AI机组/2019 甲 [aaaa1111]/01 曲A.flac"
    assert b"".join(_file_slice(flac, 0, 10 ** 12)) == flac.read_bytes()
