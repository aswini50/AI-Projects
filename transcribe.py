# One-file pipeline: captions first, Whisper fallback. Resume-safe.

import os, re, csv, json, time, random
from pathlib import Path
from typing import Optional, Tuple

from tqdm import tqdm
from unidecode import unidecode
from youtube_transcript_api import YouTubeTranscriptApi
from faster_whisper import WhisperModel

# ---- config (edit only these if needed) ----
LIST_FILE   = "jaigurudev_videos.txt"
OUT_DIR     = "t"          # short to avoid Windows path issues
AUDIO_DIR   = "a"
BATCH_LIMIT = 25           # set to None to process all
WHISPER_MODEL = "small"    # "tiny"/"base" = faster; "medium" = better
DEVICE        = "auto"     # "auto" | "cpu" | "cuda"
COMPUTE_TYPE  = "int8"     # "float16" if DEVICE="cuda"
# --------------------------------------------

Path(OUT_DIR).mkdir(exist_ok=True)
Path(AUDIO_DIR).mkdir(exist_ok=True)

def parse_line(line: str) -> Tuple[str, str, str]:
    raw = line.strip()
    murl = re.search(r'(https?://[^\s]+)', raw)
    url = murl.group(1).strip('\'"') if murl else ""
    title = raw.split('|', 1)[0].strip() if '|' in raw else (raw.replace(url, '').strip() or "Untitled")
    mid = re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_\-]{6,})', url)
    vid = mid.group(1) if mid else ""
    return title, vid, url

def safe_name(s: str, n: int = 80) -> str:
    s = unidecode(s)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^A-Za-z0-9_\-\.]", "", s)
    return (s[:n] if len(s) > n else s) or "untitled"

# ---- captions fast path ----
def fetch_captions_en(video_id: str) -> Optional[str]:
    try:
        tx = YouTubeTranscriptApi.list_transcripts(video_id)
    except Exception:
        return None
    for code in ("en", "en-US", "en-GB"):
        for finder in ("find_manually_created_transcript", "find_generated_transcript"):
            if hasattr(tx, finder):
                try:
                    t = getattr(tx, finder)([code])
                    data = t.fetch()
                    return "\n".join(s.get("text","").strip() for s in data if s.get("text","").strip())
                except Exception:
                    pass
    # translate any to English (prefer manual)
    cand = None
    for t in tx:
        if getattr(t, "is_translatable", False):
            cand = t
            if not getattr(t, "is_generated", False):
                break
    if cand:
        try:
            data = cand.translate("en").fetch()
            return "\n".join(s.get("text","").strip() for s in data if s.get("text","").strip())
        except Exception:
            return None
    # any transcript (original language)
    for t in tx:
        try:
            data = t.fetch()
            return "\n".join(s.get("text","").strip() for s in data if s.get("text","").strip())
        except Exception:
            continue
    return None

# ---- download audio ----
def download_audio(video_id: str, url: str) -> Path:
    from yt_dlp import YoutubeDL
    m = re.search(r'(https?://[^\s]+)', url)
    url = m.group(1) if m else url
    out_tmpl = str(Path(AUDIO_DIR) / f"{video_id}.%(ext)s")
    ydl_opts = {"format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
                "quiet": True, "no_warnings": True, "noprogress": True, "outtmpl": out_tmpl}
    with YoutubeDL(ydl_opts) as y:
        info = y.extract_info(url, download=True)
        p = Path(y.prepare_filename(info))
    return p

# ---- Whisper ----
_model = None
def whisper_model():
    global _model
    if _model is None:
        _model = WhisperModel(WHISPER_MODEL, device=DEVICE, compute_type=COMPUTE_TYPE)
    return _model

def whisper_translate(audio_path: Path) -> str:
    m = whisper_model()
    segs, _ = m.transcribe(str(audio_path), task="translate",
                           vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
                           beam_size=5)
    return "\n".join(s.text.strip() for s in segs if s.text)

def main():
    print(f"[INFO] Writing to: {os.path.abspath(OUT_DIR)}")
    src = Path(LIST_FILE)
    if not src.exists():
        print(f"[ERROR] {LIST_FILE} not found"); return
    rows = [ln.strip() for ln in src.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if BATCH_LIMIT is not None:
        rows = rows[:int(BATCH_LIMIT)]
    print(f"[INFO] Processing {len(rows)} videos... (batch limit={BATCH_LIMIT})")

    ok = skipped = 0
    fails = []
    for line in tqdm(rows, desc="Transcribing", unit="video"):
        title, vid, url = parse_line(line)
        if not vid or not url:
            fails.append({"video_id":"", "title":title, "url":url, "reason":"parse_error"})
            continue
        out_path = Path(OUT_DIR) / f"{safe_name(title)}.txt"
        if out_path.exists() and out_path.stat().st_size > 0:
            skipped += 1; continue

        text = fetch_captions_en(vid)
        if not text:
            audio = None
            try:
                audio = download_audio(vid, url)
                text = whisper_translate(audio)
            except Exception as e:
                fails.append({"video_id":vid,"title":title,"url":url,
                              "reason":f"whisper_error:{type(e).__name__}:{str(e)[:160]}"})
                text = None
            finally:
                if audio and audio.exists():
                    try: audio.unlink()
                    except Exception: pass

        if text:
            out_path.parent.mkdir(exist_ok=True)
            out_path.write_text(f"{title}\n{url}\n\n{text.strip()}\n", encoding="utf-8")
            ok += 1
        time.sleep(0.3 + random.uniform(0.05,0.2))

    # summary
    br = {}
    for f in fails: br[f["reason"]] = br.get(f["reason"],0)+1
    Path("transcript_report_summary.json").write_text(
        json.dumps({"attempted": len(rows), "ok": ok, "skipped": skipped,
                    "failed": len(fails), "breakdown": br, "out_dir": OUT_DIR},
                   indent=2, ensure_ascii=False),
        encoding="utf-8")
    with open("transcript_report_summary.txt","w",encoding="utf-8") as tf:
        tf.write(f"OK: {ok}  Skipped: {skipped}  Failed: {len(fails)}\nOut: {OUT_DIR}\n")

    print("\nDone.")
    print(f"✔ Transcripts: {ok}   ✖ Failed: {len(fails)}   ↻ Skipped existing: {skipped}")
    print("Summary: transcript_report_summary.txt")

if __name__ == "__main__":
    main()
