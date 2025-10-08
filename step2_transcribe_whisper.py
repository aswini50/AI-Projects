# step2_transcribe_whisper.py
# Captions -> Whisper(translate) fallback. Short paths for Windows. Resume-safe.

import os, re, csv, json, time, random
from typing import Tuple, Optional
from pathlib import Path

from tqdm import tqdm
from unidecode import unidecode
from faster_whisper import WhisperModel
from youtube_transcript_api import YouTubeTranscriptApi

# ---------- config ----------
LIST_FILE   = "jaigurudev_videos.txt"
OUT_DIR     = "t"          # short to avoid MAX_PATH
AUDIO_DIR   = "a"
BATCH_LIMIT = None            # set None for full run after testing
BASE_SLEEP  = 0.4

WHISPER_MODEL = "small"    # "tiny"/"base" = faster; "medium" = higher quality
DEVICE        = "auto"     # "auto" | "cpu" | "cuda"
COMPUTE_TYPE  = "int8"     # "int8" for CPU; "float16" for GPU

Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
Path(AUDIO_DIR).mkdir(parents=True, exist_ok=True)

# ---------- helpers ----------
def parse_line(line: str) -> Tuple[str, str, str]:
    raw = line.strip()
    murl = re.search(r'(https?://[^\s]+)', raw)
    url = murl.group(1).strip('\'"') if murl else ""
    title = raw.split('|', 1)[0].strip() if '|' in raw else (raw.replace(url, '').strip() or "Untitled")
    mid = re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_\-]{6,})', url)
    vid = mid.group(1) if mid else ""
    return title, vid, url

def safe_name(title: str, max_len: int = 80) -> str:
    base = unidecode(title).strip()
    base = re.sub(r"\s+", "_", base)
    base = re.sub(r"[^A-Za-z0-9_\-\.]", "", base)
    return (base[:max_len] if len(base) > max_len else base) or "untitled"

def clamp_path(path: Path, max_total: int = 230) -> Path:
    if len(str(path)) <= max_total:
        return path
    stem, ext = path.stem, path.suffix
    while len(str(path)) > max_total and len(stem) > 10:
        stem = stem[:-5]
        path = path.with_name(stem + ext)
    return path

# ---------- captions fast path ----------
def fetch_captions_english(video_id: str) -> Optional[str]:
    try:
        transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
    except Exception:
        return None
    # direct English
    for code in ("en", "en-US", "en-GB"):
        for finder in ("find_manually_created_transcript", "find_generated_transcript"):
            if hasattr(transcripts, finder):
                try:
                    t = getattr(transcripts, finder)([code])
                    data = t.fetch()
                    return "\n".join(s.get("text", "").strip() for s in data if s.get("text", "").strip())
                except Exception:
                    pass
    # translate any → English (prefer manual)
    candidate = None
    for t in transcripts:
        if getattr(t, "is_translatable", False):
            candidate = t
            if not getattr(t, "is_generated", False):
                break
    if candidate:
        try:
            data = candidate.translate("en").fetch()
            return "\n".join(s.get("text", "").strip() for s in data if s.get("text", "").strip())
        except Exception:
            return None
    # fallback: any transcript
    for t in transcripts:
        try:
            data = t.fetch()
            return "\n".join(s.get("text", "").strip() for s in data if s.get("text", "").strip())
        except Exception:
            continue
    return None

# ---------- audio download ----------
def download_audio(video_id: str, url: str) -> Path:
    from yt_dlp import YoutubeDL
    m = re.search(r'(https?://[^\s]+)', url)
    url_clean = m.group(1) if m else url
    out_tmpl = str(Path(AUDIO_DIR) / f"{video_id}.%(ext)s")
    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
        "quiet": True, "no_warnings": True, "noprogress": True,
        "outtmpl": out_tmpl,
    }
    with YoutubeDL(ydl_opts) as y:
        info = y.extract_info(url_clean, download=True)
        path = Path(y.prepare_filename(info))
    return path

# ---------- whisper ----------
_whisper = None
def get_model():
    global _whisper
    if _whisper is None:
        _whisper = WhisperModel(WHISPER_MODEL, device=DEVICE, compute_type=COMPUTE_TYPE)
    return _whisper

def whisper_translate(audio_path: Path) -> str:
    model = get_model()
    segments, _ = model.transcribe(
        str(audio_path),
        task="translate",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        beam_size=5,
    )
    return "\n".join(s.text.strip() for s in segments if s.text)

# ---------- main ----------
def main():
    p = Path(LIST_FILE)
    if not p.exists():
        print(f"[ERROR] Missing {LIST_FILE}")
        return
    rows = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if BATCH_LIMIT is not None:
        rows = rows[:int(BATCH_LIMIT)]
    print(f"[INFO] Processing {len(rows)} videos... (batch limit={BATCH_LIMIT})")
    print("[INFO] Writing to:", os.path.abspath(OUT_DIR))

    ok = skipped = 0
    failures = []

    for line in tqdm(rows, desc="Transcribing", unit="video"):
        title, vid, url = parse_line(line)
        if not vid or not url:
            failures.append({"video_id":"", "title":title, "url":url, "reason":"parse_error"})
            continue

        out_path = clamp_path(Path(OUT_DIR) / f"{safe_name(title)}.txt")
        if out_path.exists() and out_path.stat().st_size > 0:
            skipped += 1
            continue

        text = fetch_captions_english(vid)
        if not text:
            audio_path = None
            try:
                audio_path = download_audio(vid, url)
                text = whisper_translate(audio_path)
            except Exception as e:
                failures.append({"video_id":vid, "title":title, "url":url,
                                 "reason":f"whisper_error:{type(e).__name__}:{str(e)[:160]}"})
                text = None
            finally:
                if audio_path and audio_path.exists():
                    try: audio_path.unlink()
                    except Exception: pass

        if text:
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as out:
                    out.write(f"{title}\n{url}\n\n{text.strip()}\n")
                ok += 1
            except OSError as e:
                failures.append({"video_id":vid, "title":title, "url":url,
                                 "reason":f"write_error:{type(e).__name__}:{str(e)[:160]}"})

        time.sleep(BASE_SLEEP + random.uniform(0.05, 0.2))

    # ---- reporting ----
    breakdown = {}
    for r in failures:
        breakdown[r["reason"]] = breakdown.get(r["reason"], 0) + 1

    Path("transcript_report_summary.json").write_text(
        json.dumps({
            "total_in_list": len(rows),
            "attempted": len(rows),
            "transcribed_ok": ok,
            "skipped_existing": skipped,
            "failed": len(failures),
            "failure_breakdown": breakdown,
            "output_dir": OUT_DIR,
            "failures_csv": "transcript_failures.csv" if failures else None,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    with open("transcript_report_summary.txt", "w", encoding="utf-8") as tf:
        tf.write(
            "TRANSCRIPT REPORT SUMMARY\n"
            f"Total lines in list : {len(rows)}\n"
            f"Attempted            : {len(rows)}\n"
            f"Transcribed OK       : {ok}\n"
            f"Skipped (already had): {skipped}\n"
            f"Failed               : {len(failures)}\n"
        )
        if failures:
            tf.write("\nFailure breakdown:\n")
            for k,v in sorted(breakdown.items(), key=lambda x:(-x[1], x[0])):
                tf.write(f"  {k}: {v}\n")
            tf.write("\nSee details: transcript_failures.csv\n")

    if failures:
        with open("transcript_failures.csv", "w", newline="", encoding="utf-8") as cf:
            w = csv.DictWriter(cf, fieldnames=["video_id","title","url","reason"])
            w.writeheader(); w.writerows(failures)

    print("\nDone.")
    print(f"✔ Transcripts: {ok}   ✖ Failed: {len(failures)}   ↻ Skipped existing: {skipped}")
    print("Summary: transcript_report_summary.txt")

if __name__ == "__main__":
    main()
