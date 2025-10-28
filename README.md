# YouTube Transcript Scraper

A comprehensive Python tool for downloading YouTube video transcripts with both GUI and headless batch processing capabilities.

## Features

- **GUI Interface**: Easy-to-use graphical interface for manual processing
- **Headless Mode**: Automated batch processing for scheduled tasks
- **Batch Processing**: Process multiple URLs from a text file
- **Error Handling**: Retry failed downloads with attempt tracking
- **File Management**: Automatic cleanup of successful downloads
- **Logging**: Comprehensive logging of all operations
- **Throttling**: Configurable delays between requests
- **Multiple Languages**: Support for different transcript languages

## Installation

1. Install Python 3.8+ (tested with Python 3.13.3)
2. Install required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
potentially need to install youtube package too, on windows did this with choco but pip should catch it.

## Usage

### GUI Mode (Interactive)

Run the application with the GUI interface:

```bash
python youtube_transcriber.py
```

Features:
- Enter URLs manually in the text area
- Load URLs from a text file
- Configure output directory
- Set processing delays and retry limits
- Real-time progress tracking
- Live logging display

### Headless Mode (Automated)

Run in headless mode for scheduled tasks:

```bash
python youtube_transcriber.py --headless
```

This mode:
- Automatically checks for `urls.txt` file
- Processes all URLs in the file
- Removes successful URLs from the input file
- Saves failed URLs to `failed_urls.txt` with attempt counts
- Logs all operations to `transcriber.log`

### Input File Format

Create a `urls.txt` file with one YouTube URL per line:

```
https://www.youtube.com/watch?v=dQw4w9WgXcQ
https://www.youtube.com/watch?v=example2
https://youtu.be/example3
```

Lines starting with `#` are ignored as comments.

### Output Files

- **Transcripts**: Saved in the `transcripts/` directory with format `{VideoTitle}_{VideoID}.txt`
- **Failed URLs**: Saved to `failed_urls.txt` with attempt counts and error messages
- **Logs**: All operations logged to `transcriber.log`

### Failed URL Tracking

Failed URLs are saved with the format:
```
URL | AttemptCount | ErrorMessage | Timestamp
```

The system will retry failed URLs on subsequent runs, incrementing the attempt count.

## Scheduling with Task Manager

To run automatically on Windows:

1. Open Task Scheduler
2. Create a new task
3. Set trigger (e.g., daily at specific time)
4. Set action to run: `python C:\path\to\youtube_transcriber.py --headless`
5. Set working directory to the script location

## Configuration

### Settings

- **Delay between requests**: Time to wait between processing URLs (default: 2 seconds)
- **Max retries**: Maximum number of retry attempts (default: 3)
- **Output directory**: Where to save transcript files
- **Languages**: Transcript languages to try (default: English)

### File Structure

```
project/
├── youtube_transcriber.py    # Main script
├── requirements.txt          # Dependencies
├── urls.txt                 # Input URLs file
├── failed_urls.txt         # Failed URLs (auto-generated)
├── transcriber.log          # Log file (auto-generated)
└── transcripts/             # Output directory (auto-generated)
    ├── VideoTitle1_ID1.txt
    ├── VideoTitle2_ID2.txt
    └── ...
```

## Error Handling

The tool handles various error scenarios:

- **Invalid URLs**: Logged and skipped
- **No transcript available**: Saved to failed list
- **Network errors**: Retried with exponential backoff
- **File system errors**: Logged with details
- **API rate limits**: Handled with configurable delays

## Logging

All operations are logged with timestamps:

- URL processing start/completion
- Success/failure status
- Error messages and details
- File operations
- System events

## Requirements

- Python 3.8+
- youtube-transcript-api library
- Internet connection for YouTube API access

## Troubleshooting

### Common Issues

1. **"youtube-transcript-api not installed"**
   - Run: `pip install youtube-transcript-api`

2. **"No transcripts available"**
   - Some videos don't have transcripts
   - Try different languages
   - Check if video is public

3. **"Rate limit exceeded"**
   - Increase delay between requests
   - Reduce batch size

4. **"Permission denied"**
   - Check file/directory permissions
   - Run as administrator if needed

### Debug Mode

Enable debug logging by modifying the logging level in the script:

```python
logging.basicConfig(level=logging.DEBUG, ...)
```

## License

This project is open source. Use responsibly and respect YouTube's terms of service.
