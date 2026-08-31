set -o errexit

# ffmpeg is required by faster-whisper/yt-dlp (social-intel speech-to-text).
# Render's native Python runtime doesn't guarantee apt access — this is a
# best-effort install; if it fails, video transcription will error out at
# runtime while the rest of the app keeps working. If it fails on your
# Render plan, switch that service to a Docker-based Render deploy with
# ffmpeg baked into the image instead.
(apt-get update -y && apt-get install -y ffmpeg) || echo "WARNING: ffmpeg install skipped/failed — video transcription will not work until it's available."

pip install -r requirements.txt

python manage.py collectstatic --no-input

python manage.py migrate

