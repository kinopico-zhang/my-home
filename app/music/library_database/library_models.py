"""My Music 的库表结构 (data/music.db, 独立 SQLite 文件)。

曲库本体 (/share/Media/Music) 始终只读 —— 这里只存扫描出来的索引:
艺人 / 专辑 / 曲目三级, 附歌词全文 (服务端 LIKE 搜歌词) 与 script 语言标记
(MusicBrainz 刮削自带, 没有就按标题文字检测); 另有每人自己的播放记录
(play_stats, 最近播放的原料)。
"""
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 能扫进索引的音频扩展名 → 格式名; 浏览器播不了的 (tak/dsf/ape) 也进索引
AUDIO_EXTENSION_FORMATS = {
    ".flac": "flac", ".mp3": "mp3", ".m4a": "m4a", ".ogg": "ogg",
    ".opus": "opus", ".wav": "wav", ".aac": "aac",
    ".tak": "tak", ".dsf": "dsf", ".ape": "ape",
}
# <audio> 能直接播的 (其余格式前端置灰; 转码以后再说)
BROWSER_PLAYABLE_FORMATS = frozenset({
    "flac", "mp3", "m4a", "ogg", "opus", "wav", "aac",
})


class MusicLibraryBase(DeclarativeBase):
    """曲库索引库基类 (data/music.db, 独立文件)。"""


class Artist(MusicLibraryBase):
    """艺人 = 曲库的一级目录 (目录名是归并键, 名字取 albumartist 标签)。"""

    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(default="")
    sort_name: Mapped[str] = mapped_column(default="", index=True)  # artistsort 标签
    directory: Mapped[str] = mapped_column(String, unique=True)     # 相对曲库根
    poster_file: Mapped[str] = mapped_column(default="")            # 目录里的 poster.*
    search_keys: Mapped[str] = mapped_column(default="")            # 拼音/简繁检索键


class Album(MusicLibraryBase):
    """专辑 = 艺人下的二级目录 (目录名含刮削器的 [hex] 尾巴, 标题取标签)。"""

    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(default="")
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id"),
                                           index=True)
    year: Mapped[int] = mapped_column(default=0)
    directory: Mapped[str] = mapped_column(String, unique=True)     # 相对曲库根
    added_at: Mapped[float] = mapped_column(default=0.0)            # 旗下曲目入库最晚时刻
    track_count: Mapped[int] = mapped_column(default=0)
    duration_seconds: Mapped[float] = mapped_column(default=0.0)
    has_artwork: Mapped[bool] = mapped_column(default=False)        # 曲目内嵌封面
    search_keys: Mapped[str] = mapped_column(default="")            # 拼音/简繁检索键


class Track(MusicLibraryBase):
    """一首歌: 文件路径是唯一键, mtime/size 变了才重读标签 (增量重扫)。"""

    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    album_id: Mapped[int] = mapped_column(ForeignKey("albums.id"),
                                          index=True)
    title: Mapped[str] = mapped_column(default="")
    artist: Mapped[str] = mapped_column(default="")      # 这一首的演唱者
    track_number: Mapped[int] = mapped_column(default=0)
    disc_number: Mapped[int] = mapped_column(default=1)
    duration_seconds: Mapped[float] = mapped_column(default=0.0)
    file_path: Mapped[str] = mapped_column(String, unique=True)     # 相对曲库根
    file_size: Mapped[int] = mapped_column(default=0)
    file_mtime: Mapped[float] = mapped_column(default=0.0)
    file_format: Mapped[str] = mapped_column(default="")
    script: Mapped[str] = mapped_column(default="")      # Latn/Jpan/Hant/Hans/Kore…
    lyrics: Mapped[str] = mapped_column(default="")      # lrc 原文或纯文本
    lyrics_synced: Mapped[bool] = mapped_column(default=False)
    has_artwork: Mapped[bool] = mapped_column(default=False)  # 内嵌封面 (专辑封面取材)
    added_at: Mapped[float] = mapped_column(default=0.0)      # 入库时刻 (首插记, 重扫不改)
    search_keys: Mapped[str] = mapped_column(default="")      # 拼音/简繁检索键


class Playlist(MusicLibraryBase):
    """播放列表 (2026-09-15 起全在应用内建管; is_local 是同步时代的
    遗留列, 存量行已全部转 True, 新建恒 True)。

    cover_version: 自定义封面的版本号, 0 = 没传过; 每次换封面 +1,
    封面 URL 带 ?v={版本} 长缓存, 换图即换址。"""

    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    position: Mapped[int] = mapped_column(default=0)      # 列表内成员的排序档
    track_count: Mapped[int] = mapped_column(default=0)
    duration_seconds: Mapped[float] = mapped_column(default=0.0)
    plex_playlist_id: Mapped[int] = mapped_column(default=0)   # 源库 id (溯源/幂等)
    is_local: Mapped[bool] = mapped_column(default=False)  # 同步时代遗留, 恒 True
    cover_version: Mapped[int] = mapped_column(default=0)  # 自定义封面版本 (0 = 无)


class PlaylistItem(MusicLibraryBase):
    """播放列表成员 (position 列表内顺序; added_locally = 应用内加的,
    同步时代用来在重灌时保留, 现在恒 True)。"""

    __tablename__ = "playlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id"),
                                             index=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"),
                                          index=True)
    position: Mapped[int] = mapped_column(default=0)
    added_locally: Mapped[bool] = mapped_column(default=False)


class PlayStat(MusicLibraryBase):
    """一个人的播放记录 (user+track 一行, 重播只推进时刻/次数)。

    最近播放按人算 —— 账号体系全站共享, 这里只存 uuid 不建外键
    (账号库是另一个文件, 跨库不 JOIN)。"""

    __tablename__ = "play_stats"
    __table_args__ = (UniqueConstraint("user_uuid", "track_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_uuid: Mapped[str] = mapped_column(index=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), index=True)
    last_played_at: Mapped[float] = mapped_column(default=0.0)  # epoch 秒
    play_count: Mapped[int] = mapped_column(default=1)


class MusicSetting(MusicLibraryBase):
    """运行时设置 (恒单行 id=1): 曲库路径 / 歌词 API。

    空字段 = 回落 env 默认; 改曲库路径由服务层换扫描根目录并全量重扫。"""

    __tablename__ = "music_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    music_directory: Mapped[str] = mapped_column(default="")     # 曲库根目录 (空 = 默认)
    lyrics_api_enabled: Mapped[bool] = mapped_column(default=True)
    lyrics_api_base: Mapped[str] = mapped_column(default="")     # 空 = LRCLIB 默认


class CellularUsage(MusicLibraryBase):
    """蜂窝流量月账 (一月一行): 客户端认得出蜂窝网络时按月上报,
    设置页看这几个月听歌走了多少流量。"""

    __tablename__ = "cellular_usage"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)   # "2026-09"
    bytes: Mapped[int] = mapped_column(default=0)


class ShareLink(MusicLibraryBase):
    """分享链接: 一首歌 / 一个播放列表 24 小时免登录可开。

    token (uuid4 hex) 本身就是凭证 —— 发给谁谁就能看能听, 过期即废;
    创建时顺手清掉全库过期行 (量小, 不值得后台任务)。"""

    __tablename__ = "share_links"

    token: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))       # "track" | "playlist"
    target_id: Mapped[int] = mapped_column(default=0)  # track_id / playlist_id
    created_by: Mapped[str] = mapped_column(default="")  # 开链接的账号 uuid (审计)
    created_at: Mapped[float] = mapped_column(default=0.0)  # epoch 秒
