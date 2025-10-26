@echo off
REM YouTube Transcript Scraper - Headless Runner
REM This batch file runs the transcriber in headless mode
REM Place this in the same directory as youtube_transcriber.py

echo Starting YouTube Transcript Scraper in headless mode...
python youtube_transcriber.py --headless
echo.
echo Processing complete. Check transcriber.log for details.
pause
