"""
Media timestamp utilities for embedding EXIF data and renaming files.
"""

import os
import logging
import shutil
from datetime import datetime
from typing import Optional

from Whatsapp_Chat_Exporter.data_model import TimeZone

logger = logging.getLogger(__name__)

# Optional imports for EXIF support
try:
    import piexif
    from PIL import Image
    HAS_EXIF_SUPPORT = True
except ImportError:
    HAS_EXIF_SUPPORT = False


def format_timestamp_for_filename(timestamp: float, timezone_offset: int = 0) -> str:
    """
    Format a Unix timestamp for use in filenames.

    Args:
        timestamp: Unix timestamp (seconds)
        timezone_offset: Hours offset from UTC

    Returns:
        Formatted string: YYYY-MM-DD_HH-MM-SS
    """
    dt = datetime.fromtimestamp(timestamp, TimeZone(timezone_offset))
    return dt.strftime("%Y-%m-%d_%H-%M-%S")


def format_timestamp_for_exif(timestamp: float, timezone_offset: int = 0) -> str:
    """
    Format a Unix timestamp for EXIF DateTime fields.

    Args:
        timestamp: Unix timestamp (seconds)
        timezone_offset: Hours offset from UTC

    Returns:
        Formatted string: YYYY:MM:DD HH:MM:SS (EXIF format)
    """
    dt = datetime.fromtimestamp(timestamp, TimeZone(timezone_offset))
    return dt.strftime("%Y:%m:%d %H:%M:%S")


def generate_timestamped_filename(
    original_path: str,
    timestamp: float,
    timezone_offset: int = 0
) -> str:
    """
    Generate a new filename with timestamp prefix.

    Args:
        original_path: Original file path
        timestamp: Unix timestamp (seconds)
        timezone_offset: Hours offset from UTC

    Returns:
        New filename with format: YYYY-MM-DD_HH-MM-SS_original-name.ext
    """
    directory = os.path.dirname(original_path)
    original_name = os.path.basename(original_path)
    timestamp_prefix = format_timestamp_for_filename(timestamp, timezone_offset)
    new_name = f"{timestamp_prefix}_{original_name}"
    return os.path.join(directory, new_name)


def embed_exif_timestamp(
    file_path: str,
    timestamp: float,
    timezone_offset: int = 0
) -> bool:
    """
    Embed timestamp in EXIF data for supported image formats.

    Args:
        file_path: Path to the image file
        timestamp: Unix timestamp (seconds)
        timezone_offset: Hours offset from UTC

    Returns:
        True if successful, False otherwise
    """
    if not HAS_EXIF_SUPPORT:
        logger.warning("EXIF support not available. Install piexif and Pillow.")
        return False

    # Check file extension
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.tiff', '.tif'):
        logger.debug(f"EXIF embedding not supported for {ext} files: {file_path}")
        return False

    try:
        exif_datetime = format_timestamp_for_exif(timestamp, timezone_offset)
        exif_datetime_bytes = exif_datetime.encode('utf-8')

        # Try to load existing EXIF data
        try:
            exif_dict = piexif.load(file_path)
        except Exception:
            # No existing EXIF, create empty structure
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

        # Set DateTime fields in Exif IFD
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = exif_datetime_bytes
        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = exif_datetime_bytes

        # Set DateTime in 0th IFD (basic TIFF tag)
        exif_dict["0th"][piexif.ImageIFD.DateTime] = exif_datetime_bytes

        # Dump and insert EXIF data
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, file_path)

        return True

    except Exception as e:
        logger.warning(f"Failed to embed EXIF in {file_path}: {e}")
        return False


def _handle_duplicate_filename(file_path: str) -> str:
    """
    Generate a unique filename by appending a counter if file exists.

    Args:
        file_path: Original file path

    Returns:
        Unique file path with counter appended if necessary
    """
    if not os.path.exists(file_path):
        return file_path

    base, ext = os.path.splitext(file_path)
    counter = 1

    while os.path.exists(file_path):
        file_path = f"{base}_{counter}{ext}"
        counter += 1

    return file_path


def process_media_with_timestamp(
    source_path: str,
    dest_path: str,
    timestamp: Optional[float],
    timezone_offset: int = 0,
    embed_exif: bool = False,
    rename_media: bool = False
) -> str:
    """
    Process a media file with optional timestamp embedding and renaming.

    Args:
        source_path: Source file path
        dest_path: Destination file path (may be modified if renaming)
        timestamp: Unix timestamp (seconds), or None if unavailable
        timezone_offset: Hours offset from UTC
        embed_exif: Whether to embed EXIF timestamp
        rename_media: Whether to rename file with timestamp prefix

    Returns:
        Final destination path (may differ from dest_path if renamed)
    """
    # If no timestamp available, just copy
    if timestamp is None:
        logger.warning(f"No timestamp available for {source_path}, skipping timestamp operations")
        shutil.copy2(source_path, dest_path)
        return dest_path

    # Determine final path
    final_path = dest_path
    if rename_media:
        final_path = generate_timestamped_filename(dest_path, timestamp, timezone_offset)

    # Handle duplicate filenames
    if os.path.exists(final_path) and final_path != source_path:
        final_path = _handle_duplicate_filename(final_path)

    # Copy file to destination
    shutil.copy2(source_path, final_path)

    # Embed EXIF if requested
    if embed_exif:
        embed_exif_timestamp(final_path, timestamp, timezone_offset)

    return final_path
