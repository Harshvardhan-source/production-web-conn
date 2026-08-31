"""
transcribe.py — speech-to-text for video posts, using faster-whisper
(CTranslate2-based; no torch dependency, CPU-friendly for Render).

Known limitation to surface to users, not hide: Whisper's Kannada support is
mediocre and it has no Tulu support at all, so transcripts of local-language
video will be lower quality than English content. This module doesn't try to
paper over that — a rough/partial transcript is still returned rather than
silently failing.
"""
import logging
import os
import tempfile

logger = logging.getLogger('socialintel.transcribe')

_MODEL = None


def _get_model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        # "base" balances speed/quality for CPU inference on a small Render dyno.
        _MODEL = WhisperModel('base', device='cpu', compute_type='int8')
    return _MODEL


def transcribe_video_url(video_url):
    """Download audio for `video_url` (currently: YouTube only) and return
    the transcribed text. Raises on failure — callers are expected to catch
    and record the failure on the job/post document."""
    from .. import connectors  # noqa: F401 (documents the dependency)
    from ..connectors.youtube import download_audio

    with tempfile.TemporaryDirectory() as tmp_dir:
        audio_path = download_audio(video_url, tmp_dir)
        try:
            model = _get_model()
            segments, _info = model.transcribe(audio_path, beam_size=5)
            text = ' '.join(seg.text.strip() for seg in segments).strip()
            return text
        finally:
            try:
                if os.path.exists(audio_path):
                    os.remove(audio_path)
            except OSError:
                pass
