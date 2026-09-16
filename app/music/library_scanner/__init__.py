"""曲库扫描器 (对外名面): 编排在 scanner, 落库在 scanner_index_writer,
老库补数在 scanner_backfill。调用方统一 from ..library_scanner import
LibraryScanner, backfill_legacy_rows。
"""
from .scanner import LibraryScanner
from .scanner_backfill import backfill_legacy_rows

__all__ = ["LibraryScanner", "backfill_legacy_rows"]
