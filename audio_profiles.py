"""Supported output choices shared by the interface and download engine."""
FORMATS = [
    ("Original (best available)", "original"),
    ("Opus (.opus)", "opus"),
    ("AAC / M4A (.m4a)", "aac"),
    ("MP3 (.mp3)", "mp3"),
    ("FLAC (.flac)", "flac"),
    ("WAV (.wav)", "wav"),
]
BITRATES = {
    "opus": (64, 96, 128, 160, 192, 256),
    "aac": (64, 96, 128, 160, 192, 256, 320),
    "mp3": (64, 96, 128, 160, 192, 256, 320),
}
DEFAULT_BITRATES = {"opus": 128, "aac": 192, "mp3": 192}
EXTENSIONS = {"opus": "opus", "aac": "m4a", "mp3": "mp3", "flac": "flac", "wav": "wav"}
ENCODERS = {"opus": "libopus", "aac": "aac", "mp3": "libmp3lame", "flac": "flac", "wav": "pcm_s16le"}


def profile(settings):
    codec = settings.get("audio_codec") or "original"
    if codec not in {value for _, value in FORMATS}:
        raise ValueError("Choose a supported music output format.")
    if codec in BITRATES:
        try:
            bitrate = int(settings.get("bitrate") or DEFAULT_BITRATES[codec])
        except (ValueError, TypeError):
            raise ValueError("Choose a supported audio bitrate.") from None
        if bitrate not in BITRATES[codec]:
            raise ValueError("Choose a supported audio bitrate.")
        return codec, bitrate
    return codec, 0
