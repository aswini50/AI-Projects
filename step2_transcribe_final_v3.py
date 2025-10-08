# step2_transcribe_final_v3.py
# Captions-only (no Whisper). Short paths + clear summary.

import os, re, csv, json, time, random, inspect, sys
from pathlib import Path
from typing import Tuple

from tqdm import tqdm
from unidecode import unidecode
from youtube_transcript_api import YouTubeTranscriptApi

# exceptions across versions
try:
    from youtube_transcript_api._errors import (
        TranscriptsDisabled, NoTranscriptFound, VideoUnavailable,
        CouldNotRetrieveTranscript, TooManyRequests, YouTubeRequestFailed,
    )
except Exception:
    from youtube_transcript_api._errors import (  # type: ignore
        TranscriptsDisabled, NoTranscriptFound, VideoUnavailable,
        CouldNotRetrieveTranscript, YouTubeRequestFailed,
    )
    class TooManyRequests(YouTubeRequestFailed):  # shim
        pass

# ---------- config ----------
LIST_FILE   = "jaigurudev_videos.txt"
OUT_DIR     = "t"          # keep short
SUMMARY_TXT = "transcript_report_summary.txt"
SUMMARY_JSON= "transcript_report_summary.json"
FAIL_CSV    = "transcript_failures.csv"
BATCH_LIMIT = 3            # set None for full run
BASE_SLEEP  = 0.6

Path(OUT_DIR).mkdir(parents=True, exist_ok=True)

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

def raise_no_transcript(video_id: str):
    try:
        sig = inspect.signature(NoTranscriptFound)
        if len(sig.parameters) >= 4:
            raise NoTranscriptFound(video_id, ['en'], None)
        else:
            raise NoTranscriptFound(video_id)
    except TypeError:
        raise NoTranscriptFound(video_id, ['en'], None)

def fetch_english_transcript(video_id: str, max_retries: int = 6, cool: float = 0.8) -> str:
    attempt = 0
    while True:
        try:
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
            # 1) English direct
            for code in ("en", "en-US", "en-GB"):
                for finder in ("find_manually_created_transcript", "find_generated_transcript"):
                    if hasattr(transcripts, finder):
                        try:
                            t = getattr(transcripts, finder)([code])
                            data = t.fetch()
                            return "\n".join(s["text"].strip() for s in data if s["text"].strip())
                        except Exception:
                            pass
            # 2) translate any → en
            for t in transcripts:
                try:
                    if getattr(t, "is_translatable", False):
                        data = t.translate("en").fetch()
                        return "\n".join(s["text"].strip() for s in data if s["text"].strip())
                except Exception:
                    pass
            # 3) any available
            for t in transcripts:
                try:
                    data = t.fetch()
                    return "\n".join(s["text"].strip() for s in data if s["text"].strip())
                except Exception:
                    continue
            raise_no_transcript(video_id)

        except TooManyRequests:
            attempt += 1
            if attempt > max_retries:
                raise
            time.sleep((2 ** attempt) * cool + random.uniform(0.1, 0.6))
        except Exception as e:
            if hasattr(e, "status_code") and getattr(e, "status_code") == 429:
                attempt += 1
                if attempt > max_retries:
                    raise
                time.sleep((2 ** attempt) * cool + random.uniform(0.1, 0.6))
            else:
                raise

def main():
    print("[DEBUG] Starting captions-only run")
    print(f"[DEBUG] Batch limit: {BATCH_LIMIT}")
    print("[DEBUG] Writing to:", os.path.abspath(OUT_DIR))

    p = Path(LIST_FILE)
    if not p.exists():
        print(f"[ERROR] Missing {LIST_FILE}")
        return

    rows = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if BATCH_LIMIT is not None:
        rows = rows[:int(BATCH_LIMIT)]
    print(f"[DEBUG] Loaded {len(rows)} lines")

    ok = skipped = 0
    failures = []

    for line in tqdm(rows, desc="Transcribing", unit="video"):
        title, vid, url = parse_line(line)
        if not vid or not title:
            failures.append({"video_id":"", "title":title, "url":url, "reason":"parse_error"})
            continue

        out_path = clamp_path(Path(OUT_DIR) / f"{safe_name(title)}.txt")
        if out_path.exists() and out_path.stat().st_size > 0:
            skipped += 1
            continue

        try:
            text = fetch_english_transcript(vid)
            with open(out_path, "w", encoding="utf-8") as out:
                out.write(f"{title}\n{url}\n\n{text.strip()}\n")
            ok += 1
            time.sleep(BASE_SLEEP)
        except TranscriptsDisabled:
            failures.append({"video_id":vid,"title":title,"url":url,"reason":"transcripts_disabled"})
        except NoTranscriptFound:
            failures.append({"video_id":vid,"title":title,"url":url,"reason":"no_captions_available"})
        except VideoUnavailable:
            failures.append({"video_id":vid,"title":title,"url":url,"reason":"video_unavailable"})
        except TooManyRequests:
            failures.append({"video_id":vid,"title":title,"url":url,"reason":"rate_limited_429"})
        except CouldNotRetrieveTranscript as e:
            failures.append({"video_id":vid,"title":title,"url":url,
                             "reason":f"could_not_retrieve:{getattr(e,'message',str(e))[:180]}"})
        except Exception as e:
            failures.append({"video_id":vid,"title":title,"url":url,
                             "reason":f"unknown_error:{type(e).__name__}:{str(e)[:200]}"})

    breakdown = {}
    for f in failures:
        breakdown[f["reason"]] = breakdown.get(f["reason"], 0) + 1

    Path(SUMMARY_JSON).write_text(
        json.dumps({
            "total_in_list": len(rows),
            "attempted": len(rows),
            "transcribed_ok": ok,
            "skipped_existing": skipped,
            "failed": len(failures),
            "failure_breakdown": breakdown,
            "output_dir": OUT_DIR,
            "failures_csv": FAIL_CSV if failures else None,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    with open(SUMMARY_TXT, "w", encoding="utf-8") as tf:
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
            for k, v in sorted(breakdown.items(), key=lambda x: (-x[1], x[0])):
                tf.write(f"  {k}: {v}\n")
            tf.write("\nSee details: transcript_failures.csv\n")

    if failures:
        with open(FAIL_CSV, "w", newline="", encoding="utf-8") as cf:
            w = csv.DictWriter(cf, fieldnames=["video_id","title","url","reason"])
            w.writeheader()
            w.writerows(failures)

    print("\nDone.")
    print(f"✔ Transcripts: {ok}   ✖ Failed: {len(failures)}   ↻ Skipped existing: {skipped}")
    print(f"Summary file: {SUMMARY_TXT}")

if __name__ == "__main__":
    main()
