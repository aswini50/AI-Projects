#!/usr/bin/env python3
"""
YouTube Transcript Scraper
A tool for downloading YouTube video transcripts with GUI and batch processing.
"""

import os
import sys
import time
import json
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
from pathlib import Path
import threading
import re
from typing import List, Dict, Optional, Tuple

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    print("Error: youtube-transcript-api not installed. Run: pip install youtube-transcript-api")
    sys.exit(1)


class YouTubeTranscriber:
    def __init__(self):
        self.setup_logging()
        self.input_file = "urls.txt"
        self.output_dir = "transcripts"
        self.failed_file = "failed_urls.txt"
        self.log_file = "transcriber.log"
        self.delay_between_requests = 2  # seconds
        self.max_retries = 3
        
        # Create output directory
        Path(self.output_dir).mkdir(exist_ok=True)
        
        self.logger.info("YouTube Transcriber initialized")

    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('transcriber.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from YouTube URL"""
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([^&\n?#]+)',
            r'youtube\.com/v/([^&\n?#]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def get_video_title(self, video_id: str) -> str:
        """Get video title using transcript API"""
        try:
            # Try to get transcript list to extract title info
            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.list(video_id)
            # This is a workaround since the API doesn't directly provide title
            # We'll use the video_id as fallback
            return f"Video_{video_id}"
        except Exception as e:
            self.logger.warning(f"Could not get title for {video_id}: {e}")
            return f"Video_{video_id}"

    def sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for filesystem"""
        # Remove or replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename[:200]  # Limit length

    def fetch_transcript(self, video_id: str, languages: List[str] = ['en']) -> Optional[Dict]:
        """Fetch transcript for a video"""
        try:
            self.logger.info(f"Fetching transcript for video ID: {video_id}")
            
            # Use the new API approach
            ytt_api = YouTubeTranscriptApi()
            fetched_transcript = ytt_api.fetch(video_id, languages=languages)
            
            # Get the text from the FetchedTranscript object
            transcript_text = ""
            for snippet in fetched_transcript:
                transcript_text += snippet.text + " "
            
            return {
                'text': transcript_text.strip(),
                'raw': fetched_transcript.to_raw_data(),
                'success': True
            }
            
        except Exception as e:
            self.logger.error(f"Failed to fetch transcript for {video_id}: {e}")
            return {
                'text': None,
                'raw': None,
                'success': False,
                'error': str(e)
            }

    def process_single_url(self, url: str, attempt_count: int = 0) -> Tuple[bool, str]:
        """Process a single URL and return success status and message"""
        try:
            # Extract video ID
            video_id = self.extract_video_id(url.strip())
            if not video_id:
                return False, f"Invalid YouTube URL: {url}"
            
            # Get video title
            title = self.get_video_title(video_id)
            safe_title = self.sanitize_filename(title)
            
            # Fetch transcript
            result = self.fetch_transcript(video_id)
            
            if result['success']:
                # Save transcript
                filename = f"{safe_title}_{video_id}.txt"
                filepath = os.path.join(self.output_dir, filename)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(f"Title: {title}\n")
                    f.write(f"Video ID: {video_id}\n")
                    f.write(f"URL: {url}\n")
                    f.write(f"Downloaded: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("-" * 50 + "\n\n")
                    f.write(result['text'])
                
                self.logger.info(f"Successfully saved transcript: {filename}")
                return True, f"Success: {title}"
            else:
                return False, f"Failed to fetch transcript: {result.get('error', 'Unknown error')}"
                
        except Exception as e:
            self.logger.error(f"Error processing URL {url}: {e}")
            return False, f"Error: {str(e)}"

    def load_urls_from_file(self) -> List[str]:
        """Load URLs from input file"""
        if not os.path.exists(self.input_file):
            return []
        
        urls = []
        with open(self.input_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    urls.append(line)
        return urls

    def save_failed_url(self, url: str, attempt_count: int, error_msg: str):
        """Save failed URL to retry file"""
        with open(self.failed_file, 'a', encoding='utf-8') as f:
            f.write(f"{url} | {attempt_count + 1} | {error_msg} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    def remove_url_from_file(self, url: str):
        """Remove successfully processed URL from input file"""
        if not os.path.exists(self.input_file):
            return
        
        with open(self.input_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        with open(self.input_file, 'w', encoding='utf-8') as f:
            for line in lines:
                if line.strip() != url.strip():
                    f.write(line)

    def process_batch(self, urls: List[str], progress_callback=None):
        """Process a batch of URLs"""
        total = len(urls)
        success_count = 0
        failure_count = 0
        
        self.logger.info(f"Starting batch processing of {total} URLs")
        
        for i, url in enumerate(urls):
            if progress_callback:
                progress_callback(i, total, f"Processing: {url}")
            
            # Extract attempt count if present
            attempt_count = 0
            if ' | ' in url:
                parts = url.split(' | ')
                if len(parts) >= 2:
                    try:
                        attempt_count = int(parts[1])
                    except ValueError:
                        attempt_count = 0
                url = parts[0]  # Clean URL
            
            # Process URL
            success, message = self.process_single_url(url, attempt_count)
            
            if success:
                success_count += 1
                self.remove_url_from_file(url)
                self.logger.info(f"[SUCCESS] {message}")
            else:
                failure_count += 1
                self.save_failed_url(url, attempt_count, message)
                self.logger.error(f"[FAILED] {message}")
            
            # Throttle requests
            if i < total - 1:  # Don't delay after last item
                time.sleep(self.delay_between_requests)
        
        self.logger.info(f"Batch processing complete. Success: {success_count}, Failures: {failure_count}")
        return success_count, failure_count

    def run_headless(self):
        """Run in headless mode for scheduled tasks"""
        self.logger.info("Running in headless mode")
        
        urls = self.load_urls_from_file()
        if not urls:
            self.logger.info("No URLs found in input file. Exiting.")
            return
        
        self.logger.info(f"Found {len(urls)} URLs to process")
        success_count, failure_count = self.process_batch(urls)
        
        self.logger.info(f"Headless run complete. Success: {success_count}, Failures: {failure_count}")


class YouTubeTranscriberGUI:
    def __init__(self):
        self.transcriber = YouTubeTranscriber()
        self.setup_gui()
        self.processing = False

    def setup_gui(self):
        """Setup the GUI interface"""
        self.root = tk.Tk()
        self.root.title("YouTube Transcript Scraper")
        self.root.geometry("800x600")
        
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # URL input section
        ttk.Label(main_frame, text="YouTube URLs:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        self.url_text = scrolledtext.ScrolledText(main_frame, height=8, width=70)
        self.url_text.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        
        # File input section
        ttk.Label(main_frame, text="Or load from file:").grid(row=2, column=0, sticky=tk.W)
        
        self.file_path_var = tk.StringVar()
        ttk.Entry(main_frame, textvariable=self.file_path_var, width=50).grid(row=2, column=1, sticky=(tk.W, tk.E), padx=(5, 5))
        ttk.Button(main_frame, text="Browse", command=self.browse_file).grid(row=2, column=2, sticky=tk.W)
        
        # Output directory section
        ttk.Label(main_frame, text="Output Directory:").grid(row=3, column=0, sticky=tk.W, pady=(10, 0))
        
        self.output_dir_var = tk.StringVar(value=self.transcriber.output_dir)
        ttk.Entry(main_frame, textvariable=self.output_dir_var, width=50).grid(row=3, column=1, sticky=(tk.W, tk.E), padx=(5, 5))
        ttk.Button(main_frame, text="Browse", command=self.browse_output_dir).grid(row=3, column=2, sticky=tk.W)
        
        # Settings section
        settings_frame = ttk.LabelFrame(main_frame, text="Settings", padding="5")
        settings_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(10, 10))
        
        ttk.Label(settings_frame, text="Delay between requests (seconds):").grid(row=0, column=0, sticky=tk.W)
        self.delay_var = tk.StringVar(value=str(self.transcriber.delay_between_requests))
        ttk.Entry(settings_frame, textvariable=self.delay_var, width=10).grid(row=0, column=1, sticky=tk.W, padx=(5, 0))
        
        ttk.Label(settings_frame, text="Max retries:").grid(row=0, column=2, sticky=tk.W, padx=(20, 0))
        self.retries_var = tk.StringVar(value=str(self.transcriber.max_retries))
        ttk.Entry(settings_frame, textvariable=self.retries_var, width=10).grid(row=0, column=3, sticky=tk.W, padx=(5, 0))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=3, pady=(10, 0))
        
        self.process_btn = ttk.Button(button_frame, text="Process URLs", command=self.process_urls)
        self.process_btn.grid(row=0, column=0, padx=(0, 10))
        
        ttk.Button(button_frame, text="Clear", command=self.clear_inputs).grid(row=0, column=1, padx=(0, 10))
        ttk.Button(button_frame, text="Exit", command=self.root.quit).grid(row=0, column=2)
        
        # Progress section
        ttk.Label(main_frame, text="Progress:").grid(row=6, column=0, sticky=tk.W, pady=(20, 0))
        
        self.progress_var = tk.StringVar(value="Ready")
        ttk.Label(main_frame, textvariable=self.progress_var).grid(row=6, column=1, sticky=tk.W, padx=(5, 0))
        
        self.progress_bar = ttk.Progressbar(main_frame, mode='determinate')
        self.progress_bar.grid(row=7, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(5, 0))
        
        # Log section
        ttk.Label(main_frame, text="Log:").grid(row=8, column=0, sticky=tk.W, pady=(20, 0))
        
        self.log_text = scrolledtext.ScrolledText(main_frame, height=10, width=70)
        self.log_text.grid(row=9, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(5, 0))
        
        # Configure grid weights for scrolling
        main_frame.rowconfigure(1, weight=1)
        main_frame.rowconfigure(9, weight=1)

    def browse_file(self):
        """Browse for input file"""
        filename = filedialog.askopenfilename(
            title="Select URL file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if filename:
            self.file_path_var.set(filename)
            self.load_urls_from_file(filename)

    def browse_output_dir(self):
        """Browse for output directory"""
        directory = filedialog.askdirectory(title="Select output directory")
        if directory:
            self.output_dir_var.set(directory)

    def load_urls_from_file(self, filepath: str):
        """Load URLs from file into text widget"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            self.url_text.delete(1.0, tk.END)
            self.url_text.insert(1.0, content)
        except Exception as e:
            messagebox.showerror("Error", f"Could not load file: {e}")

    def clear_inputs(self):
        """Clear all inputs"""
        self.url_text.delete(1.0, tk.END)
        self.file_path_var.set("")
        self.output_dir_var.set(self.transcriber.output_dir)
        self.delay_var.set(str(self.transcriber.delay_between_requests))
        self.retries_var.set(str(self.transcriber.max_retries))
        self.progress_var.set("Ready")
        self.progress_bar['value'] = 0
        self.log_text.delete(1.0, tk.END)

    def update_progress(self, current: int, total: int, message: str):
        """Update progress bar and status"""
        if total > 0:
            progress = (current / total) * 100
            self.progress_bar['value'] = progress
        self.progress_var.set(f"{current}/{total} - {message}")
        self.root.update_idletasks()

    def log_message(self, message: str):
        """Add message to log text widget"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def process_urls(self):
        """Process URLs in a separate thread"""
        if self.processing:
            return
        
        # Get URLs from text widget
        urls_text = self.url_text.get(1.0, tk.END).strip()
        if not urls_text:
            messagebox.showwarning("Warning", "Please enter some URLs")
            return
        
        # Update settings
        try:
            self.transcriber.delay_between_requests = float(self.delay_var.get())
            self.transcriber.max_retries = int(self.retries_var.get())
            self.transcriber.output_dir = self.output_dir_var.get()
        except ValueError:
            messagebox.showerror("Error", "Invalid settings values")
            return
        
        # Create output directory
        Path(self.transcriber.output_dir).mkdir(exist_ok=True)
        
        # Parse URLs
        urls = [url.strip() for url in urls_text.split('\n') if url.strip()]
        
        if not urls:
            messagebox.showwarning("Warning", "No valid URLs found")
            return
        
        # Start processing in separate thread
        self.processing = True
        self.process_btn.config(text="Processing...", state='disabled')
        
        def process_thread():
            try:
                self.log_message(f"Starting processing of {len(urls)} URLs")
                success_count, failure_count = self.transcriber.process_batch(
                    urls, 
                    progress_callback=self.update_progress
                )
                
                self.log_message(f"Processing complete. Success: {success_count}, Failures: {failure_count}")
                
            except Exception as e:
                self.log_message(f"Error during processing: {e}")
            finally:
                self.processing = False
                self.process_btn.config(text="Process URLs", state='normal')
                self.progress_var.set("Complete")
        
        threading.Thread(target=process_thread, daemon=False).start()

    def run(self):
        """Run the GUI"""
        self.root.mainloop()


def main():
    """Main entry point"""
    if len(sys.argv) > 1 and sys.argv[1] == '--headless':
        # Run in headless mode
        transcriber = YouTubeTranscriber()
        transcriber.run_headless()
    else:
        # Run GUI mode
        app = YouTubeTranscriberGUI()
        app.run()


if __name__ == "__main__":
    main()
