#!/usr/bin/env python3
"""
Tool to submit a vote for Cutler Whitaker on the Sports Illustrated
High School Athlete of the Week poll.

This module provides automated voting functionality with the following features:
- Adaptive timing based on voting results (4-tier system)
- Parallel processing with up to 5 threads when Cutler is behind
- Force parallel mode option to keep threads active regardless of position
- Centralized status display showing all active voting threads
- Exponential backoff when Cutler's lead exceeds a threshold
- Thread-safe counters and vote tracking
- JSON logging of all vote activity to voting_activity.json
- Graceful shutdown on Ctrl+C
- Result extraction and display

Thread Management:
- Main thread: Runs continuously with adaptive timing
- Parallel threads: Start automatically when Cutler is behind (scalable design):
  * Parallel-1: Starts at 20 rounds behind
  * Parallel-2: Starts at 30 rounds behind
  * Parallel-3: Starts at 40 rounds behind
  * Parallel-4: Starts at 50 rounds behind
  * Additional threads: Continue at 60, 70, 80, etc. (increment by 10 per thread)
  * Default maximum: 8 total threads (1 main + 7 parallel)
  * Configurable via --max-threads command-line argument

Adaptive Timing Tiers:
- Standard (Cutler ahead): 53-67 seconds
- Initial Accelerated (1-4 rounds behind): 14-37 seconds
- Accelerated (5-9 rounds behind): 7-16 seconds
- Super Accelerated (10+ rounds behind): 3-10 seconds

Dependencies:
- selenium: Browser automation
- beautifulsoup4: HTML parsing
- requests: HTTP requests
- ChromeDriver: Required for Selenium (must be in PATH)
"""

import requests
from bs4 import BeautifulSoup
import re
import json
import time
import signal
import sys
import argparse
import random
import threading
import uuid
import os
import platform
from datetime import datetime

VOTE_URL = "https://www.si.com/high-school/national/vote-who-should-be-high-school-on-si-national-boys-athlete-of-the-week-11-3-2025"
TARGET_ATHLETE = "Cutler Whitaker"
VOTE_INTERVAL = 60  # seconds between votes

# Global flags
shutdown_flag = False
debug_mode = False

# Thread-safe lock for vote counters
# This ensures thread-safe operations when incrementing vote counters
# in case we add threading to submit votes in parallel
_counter_lock = threading.Lock()

# Thread control for parallel voting (scalable design)
# Default to 8 total threads (1 main + 7 parallel) - configurable via --max-threads
# These will be initialized dynamically in main() based on --max-threads argument
_parallel_threads = []  # List of thread objects [thread1, thread2, ...]
_parallel_active = []  # List of active flags [bool, bool, ...]
_parallel_thresholds = []  # List of thresholds [20, 30, 40, ...] - calculated dynamically
_parallel_voting_lock = threading.Lock()  # Lock for parallel voting control variables

# Centralized display coordinator for fixed-line output
# All output goes through this system to maintain fixed positions
_thread_line_map = {}  # Dictionary: thread_id -> line_number (0 = bottom thread line)
_max_thread_lines = 0  # Maximum number of thread lines to reserve at bottom
_results_area_start = 0  # Starting line number for results area (0 = top)
_results_area_height = 22  # Number of lines reserved for results display (includes top 5 results + verification info + separator)
_verification_info_lines = []  # Store current verification info to display in fixed area
_error_message_lines = []  # Store error/warning messages to display below thread status
_error_area_height = 3  # Number of lines reserved for error messages below threads
_display_lock = threading.Lock()  # Lock for all display operations
_display_initialized = False  # Flag to track if display has been initialized
_is_windows = platform.system() == 'Windows'
_ansi_supported = False  # Will be set during initialization

# Centralized status display for all threads
_thread_status = {}  # Dictionary: thread_id -> {'status': str, 'vote_num': int, 'spinner': str, 'message': str}
_status_lock = threading.Lock()  # Lock for thread status updates
_status_display_thread = None  # Reference to the status display thread
_status_display_active = False  # Flag to control status display thread
_status_display_paused = False  # Flag to temporarily pause status updates (e.g., when printing results)

# Global vote counters (thread-safe)
vote_count = 0  # Total number of vote attempts
consecutive_behind_count = 0  # Track consecutive rounds where Cutler is behind (for adaptive timing)
standard_vote_count = 0  # Votes when Cutler is ahead
accelerated_vote_count = 0  # Votes when Cutler is behind 5-9 rounds
super_accelerated_vote_count = 0  # Votes when Cutler is behind 10+ rounds
initial_accelerated_vote_count = 0  # Votes when Cutler is behind 1-4 rounds

# Lead backoff control (to prevent pushing lead too high)
lead_backoff_multiplier = 1.0  # Exponential backoff multiplier when lead is high
lead_backoff_lock = threading.Lock()  # Lock for backoff state
MAX_BACKOFF_DELAY = 300  # Maximum delay: 5 minutes (300 seconds)

# JSON logging file
JSON_LOG_FILE = 'voting_activity.json'  # File to store vote activity summary
_json_log_lock = threading.Lock()  # Lock for thread-safe JSON file writes
_current_session_id = None  # Unique session identifier for this run
_save_top_results = False  # Whether to save top_5_results in JSON (default: False to keep file size down)
_force_parallel_mode = False  # Whether to force parallel threads to stay active (default: False)

# Vote verification tracking
VOTE_VERIFICATION_FILE = 'vote_verification.json'  # File to track vote effectiveness
_verification_log_lock = threading.Lock()  # Lock for thread-safe verification file writes
_last_verification_vote_count = 0  # Track last vote count when we did verification
_first_vote_completed = False  # Flag to track when main thread's first vote completes

def _init_display_coordinator():
    """Initialize the display coordinator with ANSI support detection."""
    global _ansi_supported, _is_windows, _display_initialized
    
    _is_windows = platform.system() == 'Windows'
    _ansi_supported = False
    
    # Mac (ARM/Intel) and Linux terminals naturally support ANSI, so no action needed
    if not _is_windows:
        _ansi_supported = True  # Assume ANSI works on Unix-like systems
    else:
        # Windows: Try to enable and verify ANSI support
        # Modern terminals (Windows Terminal, Warp) support ANSI natively
        # Command Prompt needs ANSI enabled via SetConsoleMode, but may not support it
        
        # Check if we're in a modern terminal that likely supports ANSI
        term_program = os.environ.get('TERM_PROGRAM', '').lower()
        term_emulator = os.environ.get('WT_SESSION', '')  # Windows Terminal
        is_warp = 'warp' in term_program
        is_windows_terminal = bool(term_emulator)
        
        # If we're in a known modern terminal, assume ANSI works
        if is_warp or is_windows_terminal:
            _ansi_supported = True
        else:
            # Command Prompt or unknown terminal - try to enable ANSI
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                # Enable VT100 escape sequences for Windows 10+
                # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                hOut = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
                mode = ctypes.wintypes.DWORD()
                if kernel32.GetConsoleMode(hOut, ctypes.byref(mode)):
                    # Try to enable ANSI
                    if kernel32.SetConsoleMode(hOut, mode.value | 0x0004):
                        # Successfully enabled - verify it works by checking if mode was set
                        new_mode = ctypes.wintypes.DWORD()
                        if kernel32.GetConsoleMode(hOut, ctypes.byref(new_mode)):
                            if new_mode.value & 0x0004:
                                _ansi_supported = True
            except (ImportError, OSError, AttributeError):
                # Can't enable ANSI - will use fallback
                _ansi_supported = False
    
    _display_initialized = True

def _print_to_thread_line(thread_id, message):
    """
    Print a message to a thread's fixed line at the bottom of the screen.
    
    Args:
        thread_id (str): Thread identifier (e.g., "Main", "Parallel-1")
        message (str): Message to display on this thread's line
    """
    global _thread_line_map, _max_thread_lines, _ansi_supported, _is_windows
    
    if not _display_initialized:
        _init_display_coordinator()
    
    line_pos = _thread_line_map.get(thread_id, -1)
    if line_pos < 0 or line_pos >= _max_thread_lines:
        # Thread not in map or invalid position - fallback to regular print
        print(message, flush=True)
        return
    
    # Calculate absolute line position from bottom (0 = bottom line)
    # Use simpler ANSI codes that work better on Windows
    with _display_lock:
        if _ansi_supported:
            # Use line-based positioning: move to specific line number
            # Calculate line number from top: results_area_height + thread_line_position
            # Thread lines start after results area, so line number = _results_area_height + line_pos
            target_line = _results_area_height + line_pos
            
            # Move cursor to specific line using ANSI escape sequence
            # \033[n;H moves cursor to line n, column 1 (1-based, so add 1)
            print(f'\033[{target_line + 1};1H', end='', flush=True)
            
            # Clear line and print message
            print('\033[K', end='', flush=True)  # Clear to end of line
            print(message, end='', flush=True)
        else:
            # Windows Command Prompt without ANSI support: use simple scrolling output
            # Print with newline - will scroll, but is readable and functional
            # No ANSI escape codes are used here
            print(message, flush=True)

def status_display_manager():
    """
    Centralized status display thread that updates fixed thread lines at bottom.
    
    This thread continuously updates the fixed lines at the bottom of the screen,
    one line per thread. Each thread always uses the same line.
    """
    global _status_display_active, _thread_line_map, _max_thread_lines
    spinner_chars = ['|', '/', '-', '\\']
    spinner_idx = 0
    
    if not _display_initialized:
        _init_display_coordinator()
    
    while _status_display_active:
        # Check if status display is temporarily paused (e.g., during results printing)
        with _status_lock:
            if _status_display_paused:
                time.sleep(0.1)  # Short sleep while paused
                continue
        
        # Update spinner
        spinner_char = spinner_chars[spinner_idx % 4]
        spinner_idx += 1
        
        with _status_lock:
            # Update spinner characters and get all thread statuses
            for thread_id in _thread_status.keys():
                if _thread_status[thread_id]['status'] == 'processing':
                    _thread_status[thread_id]['spinner'] = spinner_char
        
        # Update each thread's fixed line
        with _status_lock:
            all_thread_ids = list(_thread_line_map.keys())
        
        for thread_id in all_thread_ids:
            status_info = _thread_status.get(thread_id, {})
            status = status_info.get('status', 'idle')
            vote_num = status_info.get('vote_num', 0)
            spinner = status_info.get('spinner', '|')
            custom_message = status_info.get('message', '')
            
            # Build message for this thread's line
            if custom_message:
                # Use custom message if provided
                message = custom_message
            elif status == 'processing':
                message = f"[{thread_id}] Processing Vote... {spinner}  (Vote #{vote_num})"
            else:
                # Thread is idle - show blank line to maintain position
                message = " " * 80
            
            # Print to this thread's fixed line
            _print_to_thread_line(thread_id, message)
        
        time.sleep(0.2)  # Update 5 times per second

def update_thread_status(thread_id, status, vote_num=0, message=None):
    """
    Update the status of a voting thread for centralized display.
    
    Args:
        thread_id (str): Identifier for the thread
        status (str): Status string ('processing', 'completed', 'idle', 'message')
        vote_num (int): Vote number being processed (optional)
        message (str, optional): Custom message to display on thread's line
    """
    with _status_lock:
        if status == 'processing':
            _thread_status[thread_id] = {
                'status': 'processing',
                'vote_num': vote_num,
                'spinner': '|',
                'message': message if message else ''
            }
        elif status == 'message' and message:
            # Update thread with a custom message (e.g., "Starting...", "Vote #X submitted")
            if thread_id in _thread_status:
                _thread_status[thread_id]['message'] = message
                _thread_status[thread_id]['status'] = 'message'
            else:
                _thread_status[thread_id] = {
                    'status': 'message',
                    'vote_num': vote_num,
                    'spinner': '|',
                    'message': message
                }
        elif status == 'completed':
            # Clear custom message, keep thread in status for a moment
            if thread_id in _thread_status:
                _thread_status[thread_id]['status'] = 'idle'
                _thread_status[thread_id]['message'] = ''
        elif status == 'idle':
            if thread_id in _thread_status:
                _thread_status[thread_id]['status'] = 'idle'
                _thread_status[thread_id]['message'] = ''
        

def start_status_display():
    """Start the centralized status display thread and initialize display layout."""
    global _status_display_thread, _status_display_active, _thread_line_map, _max_thread_lines
    
    if not _display_initialized:
        _init_display_coordinator()
    
    if not _status_display_active:
        # Reserve space at bottom for thread lines and error area
        # Print blank lines to create the reserved area
        global _error_area_height
        total_reserved_lines = _max_thread_lines + _error_area_height
        if total_reserved_lines > 0:
            # Move cursor to bottom and reserve space
            for _ in range(total_reserved_lines):
                print()  # Print blank line
            # Move cursor back up to top of reserved area
            if _ansi_supported:
                for _ in range(total_reserved_lines):
                    print('\033[A', end='')  # Move up
            # For Windows without ANSI, cursor will be at bottom after printing blank lines
            # This is fine - thread status will print below naturally
        
        _status_display_active = True
        _status_display_thread = threading.Thread(target=status_display_manager, daemon=True)
        _status_display_thread.start()

def display_error_message(message, thread_id=None):
    """
    Display an error or warning message in a fixed area below thread status.
    
    Args:
        message (str): Error/warning message to display
        thread_id (str, optional): Thread identifier if message is thread-specific
    """
    global _error_message_lines, _error_area_height, _max_thread_lines, _results_area_height
    global _ansi_supported, _is_windows, _display_initialized
    
    if not _display_initialized:
        _init_display_coordinator()
    
    # Add message to error lines (keep last N messages)
    timestamp = datetime.now().strftime('[%H:%M:%S]')
    if thread_id:
        error_line = f"{timestamp} [{thread_id}] ⚠ {message}"
    else:
        error_line = f"{timestamp} ⚠ {message}"
    
    with _display_lock:
        _error_message_lines.append(error_line)
        # Keep only the last N messages (based on error area height)
        if len(_error_message_lines) > _error_area_height:
            _error_message_lines = _error_message_lines[-_error_area_height:]
        
        # Display error messages in fixed area below threads
        if _ansi_supported:
            # Calculate line number: results_area_height + max_thread_lines + error_line_index
            error_start_line = _results_area_height + _max_thread_lines + 1
            
            # Always display/clear all error area lines (even if fewer messages)
            for i in range(_error_area_height):
                target_line = error_start_line + i
                # Move to error line
                print(f'\033[{target_line + 1};1H', end='', flush=True)
                # Clear line
                print('\033[K', end='', flush=True)
                # Print error message if available
                if i < len(_error_message_lines[-_error_area_height:]):
                    print(_error_message_lines[-_error_area_height:][i], end='', flush=True)
        else:
            # Windows without ANSI: print error messages (will scroll, but better than nothing)
            for error_line in _error_message_lines[-_error_area_height:]:
                print(error_line, flush=True)

def stop_status_display():
    """Stop the centralized status display thread and wait for it to finish."""
    global _status_display_active, _status_display_thread
    _status_display_active = False
    with _status_lock:
        _thread_status.clear()
    # Wait for display thread to finish (with timeout)
    if _status_display_thread and _status_display_thread.is_alive():
        _status_display_thread.join(timeout=0.5)
    # Don't clear screen - we want to preserve the displayed results
    # Just ensure we're ready for normal printing
    if _ansi_supported:
        # Move cursor to a new line below the reserved area to avoid overwriting
        # Calculate where the reserved area ends
        total_reserved = _results_area_height + _max_thread_lines + _error_area_height
        print(f'\033[{total_reserved + 2};1H', end='', flush=True)
    # For non-ANSI terminals, cursor will naturally be at the bottom

def log_vote_to_json(vote_num, thread_id, timestamp, success, results, cutler_ahead, 
                     consecutive_behind_count, vote_type, lead_percentage=None, is_backoff_vote=False, 
                     save_top_results=False, vote_duration=None):
    """
    Log vote details to a JSON file for activity tracking.
    
    This function writes vote information to a JSON file that maintains a summary
    of all voting activity. Each vote is appended to a list in the JSON file,
    creating a chronological record of all votes cast. The summary statistics are
    automatically updated with each vote. The file is preserved across restarts,
    with new sessions appending to existing data.
    
    The JSON file structure:
    {
        "session_start": "YYYY-MM-DD HH:MM:SS",  # First session start time (preserved)
        "target_athlete": "Cutler Whitaker",
        "summary": {
            "total_votes_submitted": int,
            "standard_votes": int,
            "initial_accelerated_votes": int,
            "accelerated_votes": int,
            "super_accelerated_votes": int,
            "exponential_backoff_votes": int
        },
        "votes": [
            {
                "vote_number": int,  # Session-scoped (resets each session)
                "session_id": str,    # Unique session identifier
                "thread_id": str,
                "timestamp": "YYYY-MM-DD HH:MM:SS",
                "success": bool,
                "cutler_ahead": bool,
                "cutler_position": int (1-based, or null if not found),
                "cutler_percentage": float (or null),
                "consecutive_behind_count": int,
                "vote_type": str,
                "lead_percentage": float (or null, only if cutler_ahead),
                "exponential_backoff": bool,
                "vote_duration": float (or null),  # Time in seconds to complete the vote
                "top_5_results": [  # Only included if --save-top-results flag is used
                    {"athlete": str, "percentage": float},
                    ...
                ]
            },
            ...
        ]
    }
    
    Args:
        vote_num (int): Vote number (sequential)
        thread_id (str): Thread identifier (e.g., "Main", "Parallel-1")
        timestamp (str): ISO format timestamp of the vote
        success (bool): Whether the vote was successfully submitted
        results (list): List of (athlete_name, percentage) tuples, or None
        cutler_ahead (bool): Whether Cutler is in first place
        consecutive_behind_count (int): Current consecutive rounds behind count
        vote_type (str): Type of vote ("standard", "initial_accelerated", "accelerated", "super_accelerated")
        lead_percentage (float, optional): Cutler's lead percentage if ahead, None otherwise
        is_backoff_vote (bool, optional): Whether this vote was cast during exponential backoff
        save_top_results (bool, optional): Whether to include top_5_results in the vote entry.
            Defaults to False to keep file size down. Uses global _save_top_results flag.
            Note: This parameter is kept for compatibility but the global flag is used instead.
        vote_duration (float, optional): Time in seconds taken to complete the vote iteration.
            This includes the entire vote submission process from start to finish.
    
    Returns:
        None: This function only writes to file
    
    Thread Safety:
        This function is fully thread-safe. It uses _json_log_lock to ensure that
        the entire read-modify-write operation is atomic. Multiple threads can call
        this function concurrently without risk of file corruption or data loss.
        The lock ensures that:
        1. Only one thread can read the file at a time
        2. Only one thread can modify and write the file at a time
        3. The summary statistics are calculated and updated atomically
    """
    global JSON_LOG_FILE, _json_log_lock, _current_session_id, _save_top_results
    
    # Session ID should already be initialized in main(), but provide fallback
    if _current_session_id is None:
        # Fallback: Generate unique session ID (timestamp + random component)
        _current_session_id = f"{timestamp}_{uuid.uuid4().hex[:8]}"
    
    # Determine Cutler's position and percentage
    cutler_position = None
    cutler_percentage = None
    top_5_results = []
    
    if results:
        # Find Cutler's position (1-based index)
        for idx, (name, percentage) in enumerate(results, 1):
            name_lower = name.lower()
            if 'cutler' in name_lower and 'whitaker' in name_lower:
                cutler_position = idx
                cutler_percentage = percentage
                break
        
        # Get top 5 results for summary (only if save_top_results is enabled)
        if _save_top_results:
            top_5_results = [
                {"athlete": name, "percentage": round(pct, 2)}
                for name, pct in results[:5]
            ]
    
    # Build vote entry
    vote_entry = {
        "vote_number": vote_num,  # Session-scoped vote number (resets each session)
        "session_id": _current_session_id,  # Unique session identifier
        "thread_id": thread_id,
        "timestamp": timestamp,
        "success": success,
        "cutler_ahead": cutler_ahead,
        "cutler_position": cutler_position,
        "cutler_percentage": round(cutler_percentage, 2) if cutler_percentage is not None else None,
        "consecutive_behind_count": consecutive_behind_count,
        "vote_type": vote_type,
        "lead_percentage": round(lead_percentage, 2) if lead_percentage is not None else None,
        "exponential_backoff": is_backoff_vote,
        "vote_duration": round(vote_duration, 2) if vote_duration is not None else None  # Time in seconds
    }
    
    # Only include top_5_results if save_top_results is True (to keep file size down)
    # Use global flag instead of parameter to avoid threading issues
    if _save_top_results:
        vote_entry["top_5_results"] = top_5_results
    
    # Thread-safe JSON file write
    # The entire read-modify-write operation is protected by _json_log_lock
    # This ensures atomicity and prevents corruption when multiple threads write simultaneously
    with _json_log_lock:
        try:
            # Try to read existing file
            try:
                with open(JSON_LOG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # IMPORTANT: Preserve original session_start timestamp (don't overwrite)
                # This ensures the file tracks the first session start time
                # New sessions will append votes but keep the original session_start
                
                # Ensure summary exists (handle old format without summary)
                if "summary" not in data:
                    data["summary"] = {
                        "total_votes_submitted": 0,
                        "standard_votes": 0,
                        "initial_accelerated_votes": 0,
                        "accelerated_votes": 0,
                        "super_accelerated_votes": 0,
                        "exponential_backoff_votes": 0
                    }
                # Ensure exponential_backoff_votes exists in summary (for old format)
                if "exponential_backoff_votes" not in data["summary"]:
                    data["summary"]["exponential_backoff_votes"] = 0
                
                # Ensure session_start exists (for old format)
                if "session_start" not in data:
                    data["session_start"] = timestamp
                    data["target_athlete"] = TARGET_ATHLETE
                
                # Ensure votes array exists (for old format)
                if "votes" not in data:
                    data["votes"] = []
                
            except (FileNotFoundError, json.JSONDecodeError):
                # File doesn't exist or is corrupted - create new structure
                data = {
                    "session_start": timestamp,  # First session start time
                    "target_athlete": TARGET_ATHLETE,
                    "summary": {
                        "total_votes_submitted": 0,
                        "standard_votes": 0,
                        "initial_accelerated_votes": 0,
                        "accelerated_votes": 0,
                        "super_accelerated_votes": 0,
                        "exponential_backoff_votes": 0
                    },
                    "votes": []
                }
            
            # Get existing summary BEFORE appending new vote (for historical totals preservation)
            existing_summary = data.get("summary", {})
            
            # Calculate summary from existing votes BEFORE adding the new vote
            # This gives us the baseline from votes currently in the file
            summary_before = {
                "total_votes_submitted": 0,
                "standard_votes": 0,
                "initial_accelerated_votes": 0,
                "accelerated_votes": 0,
                "super_accelerated_votes": 0,
                "exponential_backoff_votes": 0
            }
            
            # Count existing votes by type
            for vote in data["votes"]:
                if vote.get("success", False):
                    summary_before["total_votes_submitted"] += 1
                
                vote_type_in_entry = vote.get("vote_type", "standard")
                if vote_type_in_entry == "standard":
                    summary_before["standard_votes"] += 1
                elif vote_type_in_entry == "initial_accelerated":
                    summary_before["initial_accelerated_votes"] += 1
                elif vote_type_in_entry == "accelerated":
                    summary_before["accelerated_votes"] += 1
                elif vote_type_in_entry == "super_accelerated":
                    summary_before["super_accelerated_votes"] += 1
                
                if vote.get("exponential_backoff", False):
                    summary_before["exponential_backoff_votes"] += 1
            
            # Append new vote entry
            data["votes"].append(vote_entry)
            
            # Calculate increment for this new vote
            # This is what we need to add to the existing summary
            increment = {
                "total_votes_submitted": 0,
                "standard_votes": 0,
                "initial_accelerated_votes": 0,
                "accelerated_votes": 0,
                "super_accelerated_votes": 0,
                "exponential_backoff_votes": 0
            }
            
            # Increment based on the new vote being added
            if vote_entry.get("success", False):
                increment["total_votes_submitted"] = 1
            
            vote_type_in_entry = vote_entry.get("vote_type", "standard")
            if vote_type_in_entry == "standard":
                increment["standard_votes"] = 1
            elif vote_type_in_entry == "initial_accelerated":
                increment["initial_accelerated_votes"] = 1
            elif vote_type_in_entry == "accelerated":
                increment["accelerated_votes"] = 1
            elif vote_type_in_entry == "super_accelerated":
                increment["super_accelerated_votes"] = 1
            
            if vote_entry.get("exponential_backoff", False):
                increment["exponential_backoff_votes"] = 1
            
            # Calculate the difference between historical totals and current file totals
            # This represents votes that were manually added as historical data
            historical_offset = {
                "total_votes_submitted": max(0, existing_summary.get("total_votes_submitted", 0) - summary_before["total_votes_submitted"]),
                "standard_votes": max(0, existing_summary.get("standard_votes", 0) - summary_before["standard_votes"]),
                "initial_accelerated_votes": max(0, existing_summary.get("initial_accelerated_votes", 0) - summary_before["initial_accelerated_votes"]),
                "accelerated_votes": max(0, existing_summary.get("accelerated_votes", 0) - summary_before["accelerated_votes"]),
                "super_accelerated_votes": max(0, existing_summary.get("super_accelerated_votes", 0) - summary_before["super_accelerated_votes"]),
                "exponential_backoff_votes": max(0, existing_summary.get("exponential_backoff_votes", 0) - summary_before["exponential_backoff_votes"])
            }
            
            # Final summary = historical offset + current file totals + new vote increment
            final_summary = {
                "total_votes_submitted": historical_offset["total_votes_submitted"] + summary_before["total_votes_submitted"] + increment["total_votes_submitted"],
                "standard_votes": historical_offset["standard_votes"] + summary_before["standard_votes"] + increment["standard_votes"],
                "initial_accelerated_votes": historical_offset["initial_accelerated_votes"] + summary_before["initial_accelerated_votes"] + increment["initial_accelerated_votes"],
                "accelerated_votes": historical_offset["accelerated_votes"] + summary_before["accelerated_votes"] + increment["accelerated_votes"],
                "super_accelerated_votes": historical_offset["super_accelerated_votes"] + summary_before["super_accelerated_votes"] + increment["super_accelerated_votes"],
                "exponential_backoff_votes": historical_offset["exponential_backoff_votes"] + summary_before["exponential_backoff_votes"] + increment["exponential_backoff_votes"]
            }
            
            # Update summary in data structure (preserving historical totals and incrementing)
            data["summary"] = final_summary
            
            # Write back to file (atomic write operation)
            with open(JSON_LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        
        except Exception as e:
            # Log error but don't crash the voting process
            # This ensures that voting can continue even if JSON logging fails
            debug_print(f"⚠ Error writing to JSON log: {e}")
            import traceback
            debug_print(traceback.format_exc())

def log_vote_verification(vote_count, total_votes, cutler_percentage, results):
    """
    Log vote verification data to track vote effectiveness.
    
    This function calculates Cutler's actual vote count from the total votes and
    his percentage, then records this data to a JSON file. This helps track whether
    votes are being counted by the server or silently rejected.
    
    Verification is triggered:
    - After the first vote is cast (main thread only)
    - Every 500 votes thereafter
    
    The JSON file structure:
    {
        "verification_records": [
            {
                "timestamp": "YYYY-MM-DD HH:MM:SS",
                "session_id": str,
                "our_vote_count": int,  # Number of votes we've attempted
                "total_votes_on_server": int,  # Total votes shown on server
                "cutler_percentage": float,  # Cutler's percentage from results
                "cutler_vote_count_calculated": int,  # total_votes * (cutler_percentage / 100)
                "cutler_position": int,  # Cutler's position (1-based)
                "expected_vote_increase": int,  # How many votes we expected Cutler to have gained
                "actual_vote_increase": int or null  # How many votes Cutler actually gained (calculated from previous record)
                "effectiveness_percentage": float or null  # (actual_increase / expected_increase * 100)
            },
            ...
        ]
    }
    
    Args:
        vote_count (int): Current vote count (number of votes we've attempted)
        total_votes (int or None): Total votes shown on the server results page
        cutler_percentage (float or None): Cutler's percentage from the results
        results (list or None): List of (athlete_name, percentage) tuples from results page
    
    Returns:
        None: This function only writes to file
    
    Thread Safety:
        This function is thread-safe using _verification_log_lock.
    """
    global VOTE_VERIFICATION_FILE, _verification_log_lock, _current_session_id, _verification_info_lines
    
    # Only proceed if we have valid data
    if total_votes is None or cutler_percentage is None or results is None:
        return
    
    # Calculate Cutler's vote count from percentage
    cutler_vote_count = int(total_votes * (cutler_percentage / 100.0))
    
    # Find Cutler's position
    cutler_position = None
    for idx, (name, pct) in enumerate(results, 1):
        name_lower = name.lower()
        if 'cutler' in name_lower and 'whitaker' in name_lower:
            cutler_position = idx
            break
    
    # Get timestamp
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    
    # Session ID should already be initialized in main()
    if _current_session_id is None:
        _current_session_id = f"{timestamp}_{uuid.uuid4().hex[:8]}"
    
    # Build verification record
    verification_record = {
        "timestamp": timestamp,
        "session_id": _current_session_id,
        "our_vote_count": vote_count,
        "total_votes_on_server": total_votes,
        "cutler_percentage": round(cutler_percentage, 2),
        "cutler_vote_count_calculated": cutler_vote_count,
        "cutler_position": cutler_position,
    }
    
    # Thread-safe JSON file write
    with _verification_log_lock:
        try:
            # Try to read existing file
            try:
                with open(VOTE_VERIFICATION_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Ensure verification_records exists
                if "verification_records" not in data:
                    data["verification_records"] = []
                
                # Get previous record from CURRENT SESSION ONLY to calculate vote increase
                # This prevents comparing against previous session's data
                previous_record = None
                if len(data["verification_records"]) > 0:
                    # Find the most recent record from this session (search backwards)
                    for record in reversed(data["verification_records"]):
                        if record.get("session_id") == _current_session_id:
                            previous_record = record
                            break
                
                # Calculate expected and actual vote increases
                if previous_record:
                    previous_our_votes = previous_record.get("our_vote_count", 0)
                    previous_cutler_votes = previous_record.get("cutler_vote_count_calculated", 0)
                    
                    expected_increase = vote_count - previous_our_votes
                    actual_increase = cutler_vote_count - previous_cutler_votes
                    
                    verification_record["expected_vote_increase"] = expected_increase
                    verification_record["actual_vote_increase"] = actual_increase
                    
                    # Calculate effectiveness (if we expected 500 votes, did Cutler's count increase by close to 500?)
                    if expected_increase > 0:
                        effectiveness = (actual_increase / expected_increase * 100) if expected_increase > 0 else 0
                        verification_record["effectiveness_percentage"] = round(effectiveness, 2)
                    else:
                        verification_record["effectiveness_percentage"] = None
                else:
                    # First record - no previous data to compare
                    verification_record["expected_vote_increase"] = vote_count
                    verification_record["actual_vote_increase"] = None
                    verification_record["effectiveness_percentage"] = None
                
            except (FileNotFoundError, json.JSONDecodeError):
                # File doesn't exist or is corrupted - create new structure
                data = {
                    "verification_records": []
                }
                # First record
                verification_record["expected_vote_increase"] = vote_count
                verification_record["actual_vote_increase"] = None
                verification_record["effectiveness_percentage"] = None
            
            # Append new verification record
            data["verification_records"].append(verification_record)
            
            # Write back to file
            with open(VOTE_VERIFICATION_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Build verification info lines for fixed display
            _verification_info_lines = []
            _verification_info_lines.append(f"VOTE VERIFICATION CHECK #{len(data['verification_records'])}")
            _verification_info_lines.append("=" * 60)
            _verification_info_lines.append(f"Our vote count:           {vote_count}")
            _verification_info_lines.append(f"Total votes on server:    {total_votes:,}")
            _verification_info_lines.append(f"Cutler's percentage:      {cutler_percentage:.2f}%")
            _verification_info_lines.append(f"Cutler's vote count:      {cutler_vote_count:,} (calculated)")
            
            if verification_record.get("actual_vote_increase") is not None:
                expected = verification_record.get("expected_vote_increase", 0) or 0
                actual = verification_record.get("actual_vote_increase", 0) or 0
                effectiveness = verification_record.get("effectiveness_percentage")
                _verification_info_lines.append("")
                _verification_info_lines.append(f"Expected increase:        {expected:,} votes")
                _verification_info_lines.append(f"Actual increase:          {actual:,} votes")
                if effectiveness is not None:
                    _verification_info_lines.append(f"Effectiveness:            {effectiveness:.1f}%")
                    if effectiveness < 50:
                        _verification_info_lines.append("⚠ WARNING: Low effectiveness - votes may be being rejected!")
                    elif effectiveness < 80:
                        _verification_info_lines.append("⚠ CAUTION: Some votes may not be counting")
                    else:
                        _verification_info_lines.append("✓ Good effectiveness - votes appear to be counting")
                else:
                    _verification_info_lines.append("Effectiveness:            N/A (first verification)")
            else:
                # First verification - no previous data
                expected = verification_record.get("expected_vote_increase", vote_count)
                _verification_info_lines.append("")
                _verification_info_lines.append(f"Expected increase:        {expected:,} votes")
                _verification_info_lines.append("Actual increase:          N/A (first verification)")
                _verification_info_lines.append("Effectiveness:            N/A (first verification)")
            
            _verification_info_lines.append("=" * 60)
            
            # Verification info is now stored and will be displayed when print_top_results is called
            
        except Exception as e:
            # Log error but don't crash the voting process
            print(f"⚠ Error writing to vote verification log: {e}")
            if debug_mode:
                import traceback
                traceback.print_exc()
            # Clear verification info on error to prevent stale display
            _verification_info_lines = []

def debug_print(*args, **kwargs):
    """
    Print debug messages only if debug mode is enabled, with timestamps.
    
    This function acts as a conditional print statement that respects the global
    debug_mode flag. When debug mode is disabled, all debug messages are silently
    ignored to reduce output verbosity. When enabled, messages are prefixed with
    a timestamp in [HH:MM:SS.mmm] format.
    
    Args:
        *args: Variable positional arguments passed to print()
        **kwargs: Variable keyword arguments passed to print()
    """
    if debug_mode:
        # Format timestamp as [HH:MM:SS.mmm]
        timestamp = datetime.now().strftime('[%H:%M:%S.%f')[:-3] + ']'
        # Combine timestamp with message
        print(timestamp, *args, **kwargs)

def get_voting_widget_info():
    """
    Fetch the voting page and analyze its structure to extract widget/API information.
    
    This function attempts to discover voting mechanisms by:
    - Parsing HTML for forms, iframes, and voting widgets
    - Searching scripts for API endpoints, widget IDs, and poll IDs
    - Identifying embedded JSON data related to polls
    - Finding interactive elements with voting-related attributes
    
    Returns:
        dict: Dictionary containing:
            - 'html' (str): Raw HTML content of the page
            - 'soup' (BeautifulSoup): Parsed HTML soup object
            - 'api_endpoint' (str|None): Discovered API endpoint URL, if any
            - 'widget_id' (str|None): Discovered widget ID, if any
            - 'poll_id' (str|None): Discovered poll ID, if any
            - 'forms' (list): List of form elements found
            - 'iframes' (list): List of iframe elements found
        None: If the page fetch failed or an error occurred
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        response = requests.get(VOTE_URL, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Try to find voting widget scripts or API endpoints
        # Common patterns: PollWidget, voting API, etc.
        scripts = soup.find_all('script')
        
        # Look for JSON data or API endpoints
        api_endpoint = None
        widget_id = None
        poll_id = None
        
        for script in scripts:
            if script.string:
                # Look for API endpoints
                api_match = re.search(r'["\']([^"\']*api[^"\']*vote[^"\']*)["\']', script.string, re.I)
                if api_match:
                    api_endpoint = api_match.group(1)
                
                # Look for widget IDs
                widget_match = re.search(r'widget[_-]?id["\']?\s*[:=]\s*["\']?([^"\',\s]+)', script.string, re.I)
                if widget_match:
                    widget_id = widget_match.group(1)
                
                # Look for poll IDs
                poll_match = re.search(r'poll[_-]?id["\']?\s*[:=]\s*["\']?([^"\',\s]+)', script.string, re.I)
                if poll_match:
                    poll_id = poll_match.group(1)
                
                # Look for embedded JSON data
                json_match = re.search(r'\{[^{}]*"poll"[^{}]*\}', script.string)
                if json_match:
                    try:
                        data = json.loads(json_match.group(0))
                        print(f"Found JSON data: {data}")
                    except:
                        pass
        
        # Look for iframes (common for embedded polls)
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src', '')
            if 'poll' in src.lower() or 'vote' in src.lower():
                print(f"Found voting iframe: {src}")
        
        # Look for form elements
        forms = soup.find_all('form')
        for form in forms:
            action = form.get('action', '')
            method = form.get('method', 'GET').upper()
            print(f"Found form: {method} {action}")
        
        # Look for data attributes that might contain voting info
        vote_elements = soup.find_all(attrs={'data-vote': True}) + \
                       soup.find_all(attrs={'data-poll': True}) + \
                       soup.find_all(attrs={'data-athlete': True})
        
        print(f"\nPage analysis:")
        print(f"  API Endpoint: {api_endpoint}")
        print(f"  Widget ID: {widget_id}")
        print(f"  Poll ID: {poll_id}")
        print(f"  Forms found: {len(forms)}")
        print(f"  Iframes found: {len(iframes)}")
        print(f"  Vote elements found: {len(vote_elements)}")
        
        return {
            'html': response.text,
            'soup': soup,
            'api_endpoint': api_endpoint,
            'widget_id': widget_id,
            'poll_id': poll_id,
            'forms': forms,
            'iframes': iframes
        }
        
    except requests.RequestException as e:
        print(f"Error fetching page: {e}")
        return None

def find_athlete_option(soup, athlete_name):
    """
    Find the voting option/button element for the specified athlete in the HTML.
    
    This function searches the parsed HTML for elements containing the athlete's name
    and attempts to locate associated interactive elements (radio buttons, checkboxes,
    buttons, or links) that can be used to vote for that athlete.
    
    Args:
        soup (BeautifulSoup): Parsed HTML soup object to search within
        athlete_name (str): Name of the athlete to find (e.g., "Cutler Whitaker")
    
    Returns:
        BeautifulSoup element: The voting element (input, button, or link) if found
        None: If no voting element could be located for the athlete
    """
    # Try various patterns to find the athlete
    patterns = [
        f"//*[contains(text(), '{athlete_name}')]",
        f"//*[contains(., '{athlete_name}')]",
    ]
    
    # Look for text containing the athlete name
    elements = soup.find_all(string=re.compile(athlete_name, re.I))
    
    if elements:
        print(f"\nFound {len(elements)} text elements containing '{athlete_name}'")
        for elem in elements[:3]:  # Show first 3
            parent = elem.parent
            print(f"  Parent tag: {parent.name if parent else 'None'}")
            print(f"  Parent classes: {parent.get('class') if parent else 'None'}")
            print(f"  Parent ID: {parent.get('id') if parent else 'None'}")
    
    # Look for radio buttons or checkboxes near the athlete name
    for elem in elements:
        parent = elem.parent
        while parent:
            # Look for radio/checkbox inputs
            inputs = parent.find_all(['input', 'button'], type=['radio', 'checkbox', 'button', 'submit'])
            for inp in inputs:
                value = inp.get('value', '')
                if athlete_name.lower() in value.lower() or '21' in value or 'whitaker' in value.lower():
                    return inp
            parent = parent.parent
    
    # Look for buttons with athlete name
    buttons = soup.find_all('button', string=re.compile(athlete_name, re.I))
    if buttons:
        return buttons[0]
    
    # Look for links with athlete name
    links = soup.find_all('a', string=re.compile(athlete_name, re.I))
    if links:
        return links[0]
    
    return None

def submit_vote_selenium():
    """
    Submit a vote using Selenium WebDriver for JavaScript-rendered content.
    
    This is the primary voting method that uses browser automation to:
    1. Load the voting page in a headless Chrome browser
    2. Handle cookie consent modals/overlays
    3. Locate and interact with voting elements (radio buttons, vote buttons)
    4. Handle iframes that may contain embedded voting widgets
    5. Wait for and capture the results page after voting
    6. Save the results HTML and screenshot for later analysis
    
    The function uses multiple strategies to find voting elements:
    - XPath searches for buttons/inputs containing the athlete's name
    - CSS selectors for poll-specific elements
    - Fallback to JavaScript click if regular clicks are intercepted
    - Frame switching to handle embedded content
    
    Returns:
        bool: True if vote was successfully submitted and results page captured,
              False if voting failed or elements could not be found
    
    Note:
        Requires Selenium and ChromeDriver to be installed.
        ChromeDriver must be in PATH or accessible to the system.
    """
    vote_function_start = time.time()
    debug_print("[PERF] Starting submit_vote_selenium()")
    
    # Import Selenium components - required for browser automation
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
    except ImportError:
        print("Selenium not installed. Install with: pip install selenium")
        print("Also requires ChromeDriver: https://chromedriver.chromium.org/")
        return False
    
    # Configure Chrome options for headless operation and anti-detection
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # Run in background without GUI
    chrome_options.add_argument('--no-sandbox')  # Required for some environments
    chrome_options.add_argument('--disable-dev-shm-usage')  # Prevent shared memory issues
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')  # Hide automation
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])  # Anti-detection
    chrome_options.add_experimental_option('useAutomationExtension', False)  # Disable automation extension
    
    # Initialize driver to None to ensure cleanup in finally block
    driver = None
    service = None
    
    try:
        # Try to use ChromeDriver from environment variable or common locations
        # This helps with systems that have GLIBC compatibility issues with selenium-manager
        chromedriver_path = None
        
        # Check for CHROMEDRIVER_PATH environment variable
        if 'CHROMEDRIVER_PATH' in os.environ:
            chromedriver_path = os.environ['CHROMEDRIVER_PATH']
            if os.path.exists(chromedriver_path):
                debug_print(f"Using ChromeDriver from environment: {chromedriver_path}")
                chromedriver_init_start = time.time()
                service = Service(chromedriver_path)
                driver = webdriver.Chrome(service=service, options=chrome_options)
                # Service is now tracked for cleanup
                chromedriver_init_elapsed = time.time() - chromedriver_init_start
                debug_print(f"[PERF] ChromeDriver initialization took {chromedriver_init_elapsed:.3f} seconds")
            else:
                debug_print(f"Warning: CHROMEDRIVER_PATH set but file not found: {chromedriver_path}")
                chromedriver_init_start = time.time()
                driver = webdriver.Chrome(options=chrome_options)
                chromedriver_init_elapsed = time.time() - chromedriver_init_start
                debug_print(f"[PERF] ChromeDriver initialization took {chromedriver_init_elapsed:.3f} seconds")
        else:
            # Try common locations for ChromeDriver
            # Note: We check these paths first, but if ChromeDriver is in PATH,
            # selenium-manager will still find it automatically in the fallback below
            is_windows = platform.system() == 'Windows'
            
            # Build platform-specific common paths
            common_paths = []
            
            if is_windows:
                # Windows common locations
                program_files = os.environ.get('ProgramFiles', 'C:\\Program Files')
                program_files_x86 = os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')
                local_appdata = os.environ.get('LOCALAPPDATA', os.path.expanduser('~\\AppData\\Local'))
                
                common_paths = [
                    os.path.join(program_files, 'chromedriver', 'chromedriver.exe'),
                    os.path.join(program_files_x86, 'chromedriver', 'chromedriver.exe'),
                    os.path.join(local_appdata, 'chromedriver', 'chromedriver.exe'),
                    os.path.expanduser('~\\chromedriver.exe'),
                    os.path.join(os.path.dirname(__file__), 'chromedriver.exe'),
                    'chromedriver.exe',  # Current directory
                ]
            else:
                # Unix-like systems (macOS, Linux)
                common_paths = [
                    '/usr/local/bin/chromedriver',      # macOS Intel (Homebrew default)
                    '/opt/homebrew/bin/chromedriver',   # macOS Apple Silicon (Homebrew default)
                    '/usr/bin/chromedriver',             # Linux common location
                    '/opt/chromedriver/chromedriver',    # Alternative Linux location
                    os.path.expanduser('~/chromedriver'),
                    os.path.join(os.path.dirname(__file__), 'chromedriver'),
                ]
            
            chromedriver_found = False
            for path in common_paths:
                if os.path.exists(path):
                    # On Windows, check if file exists (no need for X_OK check)
                    # On Unix, check if file is executable
                    if not is_windows:
                        if not os.access(path, os.X_OK):
                            continue
                    
                    debug_print(f"Using ChromeDriver from: {path}")
                    chromedriver_init_start = time.time()
                    service = Service(path)
                    driver = webdriver.Chrome(service=service, options=chrome_options)
                    # Service is now tracked for cleanup
                    chromedriver_init_elapsed = time.time() - chromedriver_init_start
                    debug_print(f"[PERF] ChromeDriver initialization took {chromedriver_init_elapsed:.3f} seconds")
                    chromedriver_found = True
                    break
            
            if not chromedriver_found:
                # No ChromeDriver found in common locations, try selenium-manager
                # This works on Mac/Linux/Windows when ChromeDriver is in PATH
                # (e.g., installed via Homebrew on Mac: brew install chromedriver)
                # This will fail on systems with old GLIBC, but provides a helpful error message
                try:
                    debug_print("ChromeDriver not found in common locations, trying selenium-manager (PATH lookup)...")
                    chromedriver_init_start = time.time()
                    driver = webdriver.Chrome(options=chrome_options)
                    chromedriver_init_elapsed = time.time() - chromedriver_init_start
                    debug_print(f"[PERF] ChromeDriver initialization took {chromedriver_init_elapsed:.3f} seconds")
                except WebDriverException as e:
                    error_msg = str(e)
                    if "GLIBC" in error_msg or "selenium-manager" in error_msg.lower():
                        print("\n" + "="*60)
                        print("ERROR: ChromeDriver not found or incompatible GLIBC version")
                        print("="*60)
                        if is_windows:
                            print("This error typically occurs on Windows if ChromeDriver is not in PATH.")
                            print("\nTo fix this, install ChromeDriver:")
                            print("1. Download ChromeDriver from: https://chromedriver.chromium.org/")
                            print("2. Extract chromedriver.exe to a folder (e.g., C:\\chromedriver)")
                            print("3. Add that folder to your system PATH")
                            print("\nOR set the CHROMEDRIVER_PATH environment variable:")
                            print("   set CHROMEDRIVER_PATH=C:\\path\\to\\chromedriver.exe")
                            print("   python vote.py")
                        else:
                            print("This system's GLIBC version is too old for selenium-manager.")
                            print("\nTo fix this, install ChromeDriver manually:")
                            print("1. Download ChromeDriver from: https://chromedriver.chromium.org/")
                            print("2. Install it to a location like /usr/local/bin/chromedriver")
                            print("3. Make it executable: chmod +x /usr/local/bin/chromedriver")
                            print("\nOR set the CHROMEDRIVER_PATH environment variable:")
                            print("   export CHROMEDRIVER_PATH=/path/to/chromedriver")
                        print("="*60 + "\n")
                    raise
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # Page load timing
        page_load_start = time.time()
        debug_print("[PERF] Starting page load")
        driver.get(VOTE_URL)
        debug_print("[PERF] Page load request sent")
        
        # Wait for page to fully load and JavaScript to execute
        # Use WebDriverWait instead of fixed sleep for better performance
        debug_print("Waiting for page to load...")
        try:
            wait = WebDriverWait(driver, 10)
            # Wait for document ready state
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            debug_print("Page DOM ready")
        except Exception as e:
            # Fallback to shorter fixed wait if WebDriverWait fails
            debug_print(f"[PERF] WebDriverWait failed, using fallback: {e}")
            time.sleep(2)
        
        page_load_elapsed = time.time() - page_load_start
        debug_print(f"[PERF] Page load completed in {page_load_elapsed:.2f} seconds")
        
        # Wait for React/content to be rendered
        wait = WebDriverWait(driver, 30)
        
        # Handle cookie consent modal/overlay that might block clicks
        # OneTrust is a common cookie consent platform used by many websites
        # These overlays can intercept clicks on voting elements, so we must dismiss them first
        cookie_start = time.time()
        debug_print("[PERF] Starting cookie consent handling")
        debug_print("Checking for cookie consent modal...")
        try:
            # Look for OneTrust cookie consent elements (common cookie consent platform)
            overlay_search_start = time.time()
            cookie_overlays = driver.find_elements(By.CSS_SELECTOR, ".onetrust-pc-dark-filter, .onetrust-pc-sdk, #onetrust-pc-sdk")
            overlay_search_elapsed = time.time() - overlay_search_start
            if cookie_overlays:
                debug_print(f"[PERF] Overlay search took {overlay_search_elapsed:.3f} seconds")
                debug_print(f"Found {len(cookie_overlays)} cookie consent overlay(s)")
            
            # Try multiple selectors to find accept/dismiss buttons
            # Different sites use different button IDs and classes
            accept_selectors = [
                "button#onetrust-accept-btn-handler",
                "button#onetrust-reject-all-handler",
                "button.onetrust-close-btn-handler",
                "button[class*='onetrust'][class*='accept']",
                "button[class*='onetrust'][class*='close']",
                "button[aria-label*='Accept']",
                "button[aria-label*='Close']",
                "button[aria-label*='Reject']",
                ".onetrust-close-btn-handler",
                "#onetrust-accept-btn-handler",
            ]
            
            button_found = False
            for selector_idx, selector in enumerate(accept_selectors, 1):
                if button_found:
                    break
                selector_start = time.time()
                try:
                    accept_buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                    selector_elapsed = time.time() - selector_start
                    debug_print(f"[PERF] Selector {selector_idx} ({selector[:50]}): {len(accept_buttons)} elements found in {selector_elapsed:.3f}s")
                    for btn in accept_buttons:
                            btn_check_start = time.time()
                            if btn.is_displayed() and btn.is_enabled():
                                btn_check_elapsed = time.time() - btn_check_start
                                debug_print(f"[PERF] Button visibility check took {btn_check_elapsed:.3f}s")
                                debug_print(f"Found cookie consent button: {selector}")
                                # Try to click it
                                click_start = time.time()
                                try:
                                    btn.click()
                                    click_elapsed = time.time() - click_start
                                    debug_print(f"[PERF] Button click took {click_elapsed:.3f}s")
                                    debug_print("✓ Clicked cookie consent button")
                                    # Reduced wait time - overlay should disappear quickly
                                    time.sleep(0.5)
                                    button_found = True
                                    break
                                except Exception as click_error:
                                    # Try JavaScript click as fallback
                                    try:
                                        js_click_start = time.time()
                                        driver.execute_script("arguments[0].click();", btn)
                                        js_click_elapsed = time.time() - js_click_start
                                        debug_print(f"[PERF] JavaScript click took {js_click_elapsed:.3f}s")
                                        debug_print("✓ Clicked cookie consent button (JavaScript)")
                                        # Reduced wait time - overlay should disappear quickly
                                        time.sleep(0.5)
                                        button_found = True
                                        break
                                    except Exception as js_error:
                                        debug_print(f"[PERF] Both click methods failed: {click_error}, {js_error}")
                                        continue
                except Exception as e:
                    selector_elapsed = time.time() - selector_start
                    debug_print(f"[PERF] Selector {selector_idx} failed after {selector_elapsed:.3f}s: {e}")
                    continue
            
            # Wait for overlay to disappear
            overlay_wait_start = time.time()
            max_overlay_wait = 10
            overlay_wait = 0
            while overlay_wait < max_overlay_wait:
                try:
                    check_start = time.time()
                    overlays = driver.find_elements(By.CSS_SELECTOR, ".onetrust-pc-dark-filter")
                    visible_overlays = [o for o in overlays if o.is_displayed()]
                    check_elapsed = time.time() - check_start
                    if not visible_overlays:
                        overlay_wait_elapsed = time.time() - overlay_wait_start
                        debug_print(f"[PERF] Overlay dismissal check took {check_elapsed:.3f}s (total wait: {overlay_wait_elapsed:.2f}s)")
                        debug_print("✓ Cookie consent overlay dismissed")
                        break
                    time.sleep(0.5)
                    overlay_wait += 0.5
                except Exception as e:
                    debug_print(f"[PERF] Error checking overlay: {e}")
                    break
            
            # Reduced wait for animations - check if overlay is gone instead of fixed wait
            animation_wait_start = time.time()
            # Quick check - if overlay is already gone, don't wait
            try:
                overlays_check = driver.find_elements(By.CSS_SELECTOR, ".onetrust-pc-dark-filter")
                visible_check = [o for o in overlays_check if o.is_displayed()]
                if visible_check:
                    time.sleep(0.5)  # Only wait if overlay still visible
                else:
                    debug_print("[PERF] Overlay already gone, skipping animation wait")
            except:
                time.sleep(0.3)  # Minimal fallback wait
            animation_wait_elapsed = time.time() - animation_wait_start
            debug_print(f"[PERF] Animation wait: {animation_wait_elapsed:.3f}s")
            
            cookie_elapsed = time.time() - cookie_start
            debug_print(f"[PERF] Cookie consent handling completed in {cookie_elapsed:.2f} seconds")
        except Exception as e:
            cookie_elapsed = time.time() - cookie_start
            debug_print(f"[PERF] Cookie consent handling failed after {cookie_elapsed:.2f}s")
            print(f"Note: Could not handle cookie consent: {e}")
            # Continue anyway - might not be an issue
        
        # Check for iframes that might contain the voting widget
        # Many polling widgets are embedded in iframes, so we need to check and potentially
        # switch context to interact with elements inside the iframe
        # We'll check all iframes since the voting widget might be in any of them
        iframe_start = time.time()
        debug_print("[PERF] Starting iframe detection")
        in_iframe = False  # Track if we've switched to an iframe context
        active_iframe = None  # Store reference to the iframe we're currently in
        all_iframes = []  # Store all iframes for later checking
        try:
            iframe_search_start = time.time()
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            iframe_search_elapsed = time.time() - iframe_search_start
            debug_print(f"[PERF] Iframe search took {iframe_search_elapsed:.3f} seconds")
            debug_print(f"Found {len(iframes)} iframes on page")
            for iframe_idx, iframe in enumerate(iframes, 1):
                try:
                    attr_start = time.time()
                    src = iframe.get_attribute('src')
                    iframe_id = iframe.get_attribute('id') or 'no-id'
                    attr_elapsed = time.time() - attr_start
                    all_iframes.append((iframe, src, iframe_id))
                    if src and ('poll' in src.lower() or 'vote' in src.lower() or 'survey' in src.lower() or 'widget' in src.lower()):
                        debug_print(f"[PERF] Iframe {iframe_idx} attribute check took {attr_elapsed:.3f}s")
                        debug_print(f"Found potential voting iframe: {src}")
                        switch_start = time.time()
                        driver.switch_to.frame(iframe)
                        switch_elapsed = time.time() - switch_start
                        debug_print(f"[PERF] Frame switch took {switch_elapsed:.3f}s")
                        in_iframe = True
                        active_iframe = iframe
                        time.sleep(2)
                        # Now search within the iframe
                        break
                    else:
                        debug_print(f"[PERF] Iframe {iframe_idx} check took {attr_elapsed:.3f}s (not a voting iframe)")
                except Exception as e:
                    debug_print(f"[PERF] Error checking iframe {iframe_idx}: {e}")
                    continue
            iframe_elapsed = time.time() - iframe_start
            debug_print(f"[PERF] Iframe detection completed in {iframe_elapsed:.2f} seconds")
        except Exception as e:
            iframe_elapsed = time.time() - iframe_start
            debug_print(f"[PERF] Iframe detection failed after {iframe_elapsed:.2f}s")
            debug_print(f"Error finding iframes: {e}")
        
        # Wait for voting widget to be fully loaded and interactive
        # This prevents searching for elements before React/JavaScript has finished rendering
        widget_wait_start = time.time()
        debug_print("[PERF] Waiting for voting widget to be ready...")
        try:
            # Wait for voting widget container or key elements to be present and visible
            # Try multiple selectors that indicate the widget is loaded
            widget_ready = False
            widget_selectors = [
                "input[type='radio']",  # Radio buttons indicate widget is loaded
                "button.css-vote-button",  # Vote button class
                "button.pds-vote-button",  # Alternative vote button class
                "button[id*='vote']",  # Vote button with ID containing 'vote'
                ".pds-radiobutton",  # Radio button container
            ]
            
            max_widget_wait = 5  # Maximum 5 seconds to wait for widget
            widget_wait_elapsed = 0
            wait_interval = 0.2
            
            while widget_wait_elapsed < max_widget_wait and not widget_ready:
                for selector in widget_selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        # Check if at least one element is visible and interactive
                        for elem in elements[:5]:  # Check first 5 elements
                            try:
                                if elem.is_displayed() and elem.is_enabled():
                                    # Found a visible, interactive element - widget is ready
                                    widget_ready = True
                                    debug_print(f"[PERF] Voting widget ready (found: {selector})")
                                    break
                            except:
                                continue
                        if widget_ready:
                            break
                    except:
                        continue
                if widget_ready:
                    break
                
                time.sleep(wait_interval)
                widget_wait_elapsed += wait_interval
            
            if not widget_ready:
                debug_print(f"[PERF] Widget wait timeout after {widget_wait_elapsed:.2f}s, proceeding anyway")
            
            widget_wait_total = time.time() - widget_wait_start
            debug_print(f"[PERF] Widget ready check completed in {widget_wait_total:.2f} seconds")
        except Exception as e:
            widget_wait_total = time.time() - widget_wait_start
            debug_print(f"[PERF] Widget wait error after {widget_wait_total:.2f}s: {e}")
            # Continue anyway - might still work
        
        # Try multiple strategies to find the vote button for Cutler Whitaker
        # We use multiple strategies because different sites structure their polls differently
        # If one strategy fails, we try the next one until we find the element
        vote_search_start = time.time()
        debug_print("[PERF] Starting vote button search")
        vote_button = None
        strategies = [
            # Strategy 1: Find button containing athlete name (most specific)
            (By.XPATH, f"//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{TARGET_ATHLETE.lower()}')]"),
            # Strategy 2: Find radio button or input near athlete name
            (By.XPATH, f"//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'cutler') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'whitaker')]/ancestor::*//input[@type='radio' or @type='checkbox'][1]"),
            # Strategy 3: Find button near athlete name (in same container)
            (By.XPATH, f"//*[(contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'cutler') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'whitaker')) and (ancestor::*[contains(@class, 'poll') or contains(@class, 'vote') or contains(@class, 'widget') or contains(@id, 'poll') or contains(@id, 'vote')])]//button"),
            # Strategy 4: Find submit button in a form containing the athlete name
            (By.XPATH, f"//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'cutler') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'whitaker')]/ancestor::form//button[@type='submit']"),
            # Strategy 5: Find any button with "vote" text near athlete name
            (By.XPATH, f"//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'cutler') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'whitaker')]/ancestor::*//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'vote')]"),
            # Strategy 6: Find all buttons and filter by text and proximity
            (By.TAG_NAME, "button"),
        ]
        
        debug_print("Searching for voting elements...")
        for strategy_idx, (strategy_type, selector) in enumerate(strategies, 1):
            strategy_start = time.time()
            try:
                if strategy_type == By.TAG_NAME:
                    # Special handling for finding all buttons - filter more carefully
                    buttons = driver.find_elements(By.TAG_NAME, "button")
                    strategy_elapsed = time.time() - strategy_start
                    debug_print(f"[PERF] Strategy {strategy_idx} (TAG_NAME): Found {len(buttons)} buttons in {strategy_elapsed:.3f}s")
                    for btn_idx, btn in enumerate(buttons, 1):
                        try:
                            btn_check_start = time.time()
                            # Skip menu/navigation buttons
                            btn_id = btn.get_attribute('id') or ''
                            btn_class = btn.get_attribute('class') or ''
                            btn_aria = btn.get_attribute('aria-label') or ''
                            btn_check_elapsed = time.time() - btn_check_start
                            
                            # Skip obvious non-vote buttons
                            if any(skip in btn_id.lower() or skip in btn_class.lower() or skip in btn_aria.lower() 
                                   for skip in ['menu', 'nav', 'hamburger', 'close', 'more', 'dropdown']):
                                if btn_idx <= 5:  # Only log first few for performance
                                    debug_print(f"[PERF] Button {btn_idx} check took {btn_check_elapsed:.3f}s (skipped)")
                                continue
                            
                            text = btn.text.lower()
                            # Must contain vote-related text OR be near athlete name
                            if ('vote' in text or 'submit' in text) and ('cutler' in text or 'whitaker' in text):
                                debug_print(f"[PERF] Button {btn_idx} check took {btn_check_elapsed:.3f}s")
                                debug_print(f"Found potential vote button: text='{btn.text[:50]}', id='{btn_id}', class='{btn_class[:50]}'")
                                vote_button = btn
                                break
                        except Exception as e:
                            debug_print(f"[PERF] Button {btn_idx} check failed: {e}")
                            continue
                    if vote_button:
                        break
                else:
                    elements = driver.find_elements(strategy_type, selector)
                    strategy_elapsed = time.time() - strategy_start
                    debug_print(f"[PERF] Strategy {strategy_idx} ({strategy_type}): Found {len(elements)} elements in {strategy_elapsed:.3f}s")
                    if elements:
                        for elem_idx, elem in enumerate(elements, 1):
                            try:
                                elem_check_start = time.time()
                                # Wait for element to be clickable, not just present
                                # This ensures React/JavaScript has finished making it interactive
                                try:
                                    # Use WebDriverWait to ensure element is clickable
                                    wait_elem = WebDriverWait(driver, 1)
                                    wait_elem.until(EC.element_to_be_clickable(elem))
                                except:
                                    # If WebDriverWait fails, fall back to basic checks
                                    if not elem.is_displayed() or not elem.is_enabled():
                                        continue
                                
                                elem_check_elapsed = time.time() - elem_check_start
                                elem_text = elem.text[:50] if elem.text else 'N/A'
                                elem_tag = elem.tag_name
                                debug_print(f"[PERF] Element {elem_idx} check took {elem_check_elapsed:.3f}s (clickable)")
                                debug_print(f"Found clickable element: {elem_tag}, text='{elem_text}'")
                                # For buttons, make sure it's not a menu button
                                if elem_tag == 'button':
                                    btn_id = elem.get_attribute('id') or ''
                                    btn_class = elem.get_attribute('class') or ''
                                    if any(skip in btn_id.lower() or skip in btn_class.lower() 
                                           for skip in ['menu', 'nav', 'hamburger', 'more']):
                                        debug_print(f"  Skipping (looks like menu button)")
                                        continue
                                vote_button = elem
                                break
                            except Exception as e:
                                debug_print(f"[PERF] Element {elem_idx} check failed: {e}")
                                continue
                        if vote_button:
                            break
            except Exception as e:
                strategy_elapsed = time.time() - strategy_start
                debug_print(f"[PERF] Strategy {strategy_idx} failed after {strategy_elapsed:.3f}s: {e}")
                continue
        
        vote_search_elapsed = time.time() - vote_search_start
        debug_print(f"[PERF] Vote button search completed in {vote_search_elapsed:.2f} seconds")
        
        if not vote_button:
            # Last resort: Save page source and try to find by inspecting DOM
            # Use error message display instead of direct print
            display_error_message("Could not find vote button using standard strategies.")
            display_error_message("Saving page source for manual inspection...")
            with open('page_source.html', 'w', encoding='utf-8') as f:
                f.write(driver.page_source)
            
            # Try to find any interactive element near text containing the name
            try:
                text_elements = driver.find_elements(By.XPATH, f"//*[contains(text(), 'Cutler') or contains(text(), 'Whitaker')]")
                if text_elements:
                    display_error_message(f"Found {len(text_elements)} text elements containing 'Cutler' or 'Whitaker'")
                for text_elem in text_elements:
                    try:
                        # Look for nearby button or clickable element
                        parent = text_elem.find_element(By.XPATH, "./ancestor::*[button or @onclick or @role='button'][1]")
                        vote_button = parent
                        break
                    except:
                        continue
            except:
                pass
        
        if vote_button:
            try:
                # Element interaction timing
                element_interaction_start = time.time()
                debug_print("[PERF] Starting element interaction")
                
                # Scroll into view
                scroll_start = time.time()
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});", vote_button)
                scroll_elapsed = time.time() - scroll_start
                debug_print(f"[PERF] Scroll into view took {scroll_elapsed:.3f}s")
                # Reduced wait - scroll should be instant
                time.sleep(0.2)
                
                # Make sure no overlays are blocking
                overlay_check_start = time.time()
                try:
                    overlays = driver.find_elements(By.CSS_SELECTOR, ".onetrust-pc-dark-filter")
                    visible_overlays = [o for o in overlays if o.is_displayed()]
                    if visible_overlays:
                        print("⚠ Cookie consent overlay still visible, trying to dismiss...")
                        # Try to click outside the overlay or press ESC
                        driver.execute_script("document.querySelectorAll('.onetrust-pc-dark-filter').forEach(el => el.remove());")
                        time.sleep(0.3)
                    overlay_check_elapsed = time.time() - overlay_check_start
                    debug_print(f"[PERF] Overlay check took {overlay_check_elapsed:.3f}s")
                except:
                    pass
                
                # Save the initial page state for comparison
                initial_page_source = driver.page_source
                initial_url = driver.current_url
                
                # Print button details for debugging
                btn_tag = vote_button.tag_name
                btn_text = vote_button.text[:100] if vote_button.text else 'N/A'
                btn_id = vote_button.get_attribute('id') or 'N/A'
                btn_class = vote_button.get_attribute('class') or 'N/A'
                debug_print(f"\nFound element:")
                debug_print(f"  Tag: {btn_tag}")
                debug_print(f"  Text: {btn_text}")
                debug_print(f"  ID: {btn_id}")
                debug_print(f"  Class: {btn_class[:100]}")
                
                # Handle two-step voting process: select radio button, then click submit
                # Many polls use radio buttons for selection and a separate "Vote" button to submit
                if btn_tag == 'input' and vote_button.get_attribute('type') in ['radio', 'checkbox']:
                    radio_selection_start = time.time()
                    debug_print(f"\n✓ This is a radio/checkbox button. Selecting it first...")
                    # Step 1: Select the radio button for Cutler Whitaker
                    try:
                        radio_click_start = time.time()
                        if not vote_button.is_selected():
                            vote_button.click()
                            radio_click_elapsed = time.time() - radio_click_start
                            debug_print(f"[PERF] Radio button click took {radio_click_elapsed:.3f}s")
                            debug_print(f"✓ Selected radio button for {TARGET_ATHLETE}")
                        else:
                            debug_print(f"✓ Radio button already selected")
                    except Exception as click_error:
                        if "click intercepted" in str(click_error).lower():
                            debug_print("⚠ Click intercepted, trying JavaScript click instead...")
                            driver.execute_script("""
                                document.querySelectorAll('.onetrust-pc-dark-filter').forEach(el => el.remove());
                                document.querySelectorAll('#onetrust-pc-sdk').forEach(el => el.remove());
                            """)
                            time.sleep(0.3)
                            js_click_start = time.time()
                            driver.execute_script("arguments[0].click();", vote_button)
                            js_click_elapsed = time.time() - js_click_start
                            debug_print(f"[PERF] JavaScript radio click took {js_click_elapsed:.3f}s")
                            debug_print(f"✓ Selected radio button (JavaScript click)")
                        else:
                            raise click_error
                    
                    # Reduced wait - radio selection should register immediately
                    time.sleep(0.3)
                    radio_selection_elapsed = time.time() - radio_selection_start
                    debug_print(f"[PERF] Radio button selection completed in {radio_selection_elapsed:.3f}s")
                    
                    # Step 2: Find and click the Vote/Submit button
                    submit_search_start = time.time()
                    debug_print(f"\nLooking for Vote/Submit button...")
                    submit_button = None
                    # Use faster CSS selectors first, then fallback to XPath
                    submit_selectors_css = [
                        ("css", "button[type='submit']"),
                        ("css", "button.css-vote-button"),
                        ("css", "button.pds-vote-button"),
                        ("css", "button[id*='vote']"),
                        ("css", "button[id*='Vote']"),
                        ("css", "button[class*='vote']"),
                        ("css", "input[type='submit']"),
                    ]
                    submit_selectors_xpath = [
                        ("xpath", "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'vote')]"),
                        ("xpath", "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'submit')]"),
                        ("xpath", "//input[@type='submit']"),
                        ("xpath", "//button[@type='submit']"),
                        ("xpath", "//button[contains(@class, 'vote')]"),
                        ("xpath", "//button[contains(@id, 'vote')]"),
                    ]
                    
                    # Try CSS selectors first (faster)
                    for selector_type, selector in submit_selectors_css:
                        selector_start = time.time()
                        try:
                            if selector_type == "css":
                                buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                            else:
                                buttons = driver.find_elements(By.XPATH, selector)
                            selector_elapsed = time.time() - selector_start
                            debug_print(f"[PERF] Submit selector ({selector_type}): {len(buttons)} found in {selector_elapsed:.3f}s")
                            for btn in buttons:
                                try:
                                    if btn.is_displayed() and btn.is_enabled():
                                        btn_text_val = btn.text or btn.get_attribute('value') or ''
                                        debug_print(f"  Found submit button: {btn.tag_name}, text='{btn_text_val[:50]}'")
                                        submit_button = btn
                                        break
                                except:
                                    continue
                            if submit_button:
                                break
                        except Exception as e:
                            selector_elapsed = time.time() - selector_start
                            debug_print(f"[PERF] Submit selector ({selector_type}) failed after {selector_elapsed:.3f}s: {e}")
                            continue
                    
                    # Fallback to XPath if CSS didn't work
                    if not submit_button:
                        for selector_type, selector in submit_selectors_xpath:
                            selector_start = time.time()
                            try:
                                buttons = driver.find_elements(By.XPATH, selector)
                                selector_elapsed = time.time() - selector_start
                                debug_print(f"[PERF] Submit selector ({selector_type}): {len(buttons)} found in {selector_elapsed:.3f}s")
                                for btn in buttons:
                                    try:
                                        if btn.is_displayed() and btn.is_enabled():
                                            btn_text_val = btn.text or btn.get_attribute('value') or ''
                                            debug_print(f"  Found submit button: {btn.tag_name}, text='{btn_text_val[:50]}'")
                                            submit_button = btn
                                            break
                                    except:
                                        continue
                                if submit_button:
                                    break
                            except Exception as e:
                                selector_elapsed = time.time() - selector_start
                                debug_print(f"[PERF] Submit selector ({selector_type}) failed after {selector_elapsed:.3f}s: {e}")
                                continue
                    
                    submit_search_elapsed = time.time() - submit_search_start
                    debug_print(f"[PERF] Submit button search completed in {submit_search_elapsed:.3f}s")
                    
                    if not submit_button:
                        # Try to find any button near the radio button
                        try:
                            # Look for button in the same form or container
                            parent = vote_button.find_element(By.XPATH, "./ancestor::*[form or @class[contains(., 'poll')] or @class[contains(., 'vote')] or @id[contains(., 'poll')] or @id[contains(., 'vote')]][1]")
                            buttons = parent.find_elements(By.XPATH, ".//button[not(@type='button') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'vote')]")
                            if buttons:
                                for btn in buttons:
                                        if btn.is_displayed() and btn.is_enabled():
                                            submit_button = btn
                                            debug_print(f"  Found submit button near radio: {btn.text[:50] if btn.text else 'N/A'}")
                                            break
                        except:
                            pass
                    
                    if submit_button:
                        vote_button = submit_button  # Update to use the submit button
                        debug_print(f"\n✓ Found Vote/Submit button, will click it now")
                    else:
                        debug_print(f"⚠ Could not find Vote/Submit button. Trying to submit form directly...")
                        # Try to find the form and submit it
                        try:
                            form = vote_button.find_element(By.XPATH, "./ancestor::form[1]")
                            driver.execute_script("arguments[0].submit();", form)
                            debug_print(f"✓ Submitted form directly")
                        except:
                            debug_print(f"⚠ Could not submit form. Results may not appear.")
                
                # Now click the vote/submit button
                vote_click_start = time.time()
                debug_print(f"\nClicking vote/submit button...")
                btn_tag = vote_button.tag_name
                btn_text = vote_button.text[:100] if vote_button.text else vote_button.get_attribute('value') or 'N/A'
                btn_id = vote_button.get_attribute('id') or 'N/A'
                btn_class = vote_button.get_attribute('class') or 'N/A'
                debug_print(f"  Tag: {btn_tag}")
                debug_print(f"  Text: {btn_text}")
                debug_print(f"  ID: {btn_id}")
                debug_print(f"  Class: {btn_class[:100]}")
                
                # Try to click - if intercepted, use JavaScript click
                try:
                    vote_button.click()
                    vote_click_elapsed = time.time() - vote_click_start
                    debug_print(f"[PERF] Vote button click took {vote_click_elapsed:.3f}s")
                    debug_print(f"✓ Successfully clicked vote button (regular click)")
                except Exception as click_error:
                    if "click intercepted" in str(click_error).lower():
                        debug_print("⚠ Click intercepted, trying JavaScript click instead...")
                        # Try to remove overlay with JavaScript
                        driver.execute_script("""
                            document.querySelectorAll('.onetrust-pc-dark-filter').forEach(el => el.remove());
                            document.querySelectorAll('#onetrust-pc-sdk').forEach(el => el.remove());
                        """)
                        time.sleep(0.3)
                        # Try JavaScript click
                        js_click_start = time.time()
                        driver.execute_script("arguments[0].click();", vote_button)
                        js_click_elapsed = time.time() - js_click_start
                        debug_print(f"[PERF] JavaScript vote click took {js_click_elapsed:.3f}s")
                        debug_print(f"✓ Successfully clicked vote button (JavaScript click)")
                    else:
                        raise click_error
                
                element_interaction_elapsed = time.time() - element_interaction_start
                debug_print(f"[PERF] Element interaction completed in {element_interaction_elapsed:.3f}s")
                
                debug_print("Waiting for vote to be processed...")
                
                # Wait for the results page to appear after clicking vote button
                # The page may redirect, update dynamically, or show results in an iframe
                # We look for multiple indicators: "Thank you for voting!" message, URL changes,
                # percentage displays, or significant DOM changes
                result_page_source = None
                max_wait = 20  # Maximum seconds to wait for results to appear
                wait_interval = 0.5  # Check every 0.5 seconds
                waited = 0
                found_results = False
                
                debug_print("Waiting for results page to appear...")
                debug_print(f"Current frame: {'iframe' if in_iframe else 'default content'}")
                debug_print(f"Current URL: {driver.current_url}")
                
                while waited < max_wait and not found_results:
                    time.sleep(wait_interval)
                    waited += wait_interval
                    
                    if waited % 2 == 0:  # Print status every 2 seconds
                        debug_print(f"  Waiting... ({waited:.1f}s)")
                    
                    # Check the current frame for success indicators
                    # Note: We might be in an iframe context, so we check the current frame first
                    try:
                        # Strategy 1: Look for "Thank you for voting!" message - the clearest success indicator
                        thank_you_elements = driver.find_elements(By.XPATH, 
                            "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'thank you for voting')]")
                        if thank_you_elements:
                            visible_thanks = [e for e in thank_you_elements if e.is_displayed()]
                            if visible_thanks:
                                debug_print(f"✓ Found {len(visible_thanks)} 'Thank you for voting!' message(s) in current frame")
                                found_results = True
                                time.sleep(2)  # Wait for results to fully render
                                result_page_source = driver.page_source
                                break
                    except Exception as e:
                        pass
                    
                    # Strategy 2: Check if URL changed (indicates redirect to results page)
                    current_url = driver.current_url
                    if current_url != initial_url:
                        debug_print(f"✓ Page URL changed to: {current_url}")
                        time.sleep(2)
                        result_page_source = driver.page_source
                        found_results = True
                        break
                    
                    # Strategy 3: Check for percentage displays (results page shows vote percentages)
                    try:
                        percentage_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '%')]")
                        if percentage_elements:
                            # Check if we have multiple percentages (results page has several athletes)
                            visible_percentages = [e for e in percentage_elements if e.is_displayed() and '%' in e.text]
                            if len(visible_percentages) > 3:  # Results page typically has 3+ percentages
                                debug_print(f"✓ Found {len(visible_percentages)} percentage displays (likely results)")
                                found_results = True
                                time.sleep(2)
                                result_page_source = driver.page_source
                                break
                    except:
                        pass
                    
                    # Strategy 4: Check if page source changed significantly (DOM update)
                    current_page_source = driver.page_source
                    if current_page_source != initial_page_source:
                        page_text_lower = current_page_source.lower()
                        # Look for success indicators in the page text
                        if 'thank you for voting' in page_text_lower:
                            debug_print(f"✓ Found 'Thank you for voting' in page source")
                            found_results = True
                            time.sleep(2)
                            result_page_source = current_page_source
                            break
                
                # If we didn't find results in the current frame, check other contexts
                # Results might be in the main page (default content) or in a different iframe
                if not found_results:
                    debug_print("\nResults not found in current frame. Checking all frames...")
                    
                    # Check default content first (main page, not inside any iframe)
                    if in_iframe:
                        debug_print("Checking default content...")
                        driver.switch_to.default_content()
                        time.sleep(1)
                        
                        try:
                            thank_you_elements = driver.find_elements(By.XPATH,
                                "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'thank you for voting')]")
                            visible_thanks = [e for e in thank_you_elements if e.is_displayed()]
                            if visible_thanks:
                                debug_print(f"✓ Found {len(visible_thanks)} 'Thank you for voting!' message(s) in default content")
                                found_results = True
                                time.sleep(2)
                                result_page_source = driver.page_source
                        except Exception as e:
                            debug_print(f"Error checking default content: {e}")
                    
                    # Check all iframes for results (results might appear in a different iframe)
                    if not found_results:
                        debug_print(f"Checking all {len(all_iframes)} iframes for results...")
                        # Iterate through all iframes we found earlier
                        for iframe, src, iframe_id in all_iframes:
                            try:
                                debug_print(f"  Checking iframe: {iframe_id} (src: {src[:50] if src else 'no src'})")
                                driver.switch_to.frame(iframe)
                                time.sleep(1)
                                
                                thank_you_elements = driver.find_elements(By.XPATH,
                                    "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'thank you for voting')]")
                                visible_thanks = [e for e in thank_you_elements if e.is_displayed()]
                                if visible_thanks:
                                    debug_print(f"✓ Found {len(visible_thanks)} 'Thank you for voting!' message(s) in iframe: {iframe_id}")
                                    found_results = True
                                    time.sleep(2)
                                    result_page_source = driver.page_source
                                    break
                                
                                driver.switch_to.default_content()
                            except Exception as e:
                                debug_print(f"  Error checking iframe {iframe_id}: {e}")
                                try:
                                    driver.switch_to.default_content()
                                except:
                                    pass
                
                # Fallback: If we still didn't find results, save current page state anyway
                # This allows us to manually inspect what happened or extract results later
                if not result_page_source:
                    debug_print("⚠ Results not found, saving current page state")
                    # Make sure we're in the right frame context before saving
                    if in_iframe and not found_results:
                        try:
                            driver.switch_to.frame(active_iframe)
                        except:
                            pass
                    result_page_source = driver.page_source
                
                # Save the result page HTML for later analysis and result extraction
                result_filename = 'vote_result.html'
                debug_print(f"Saving result page to {result_filename}...")
                with open(result_filename, 'w', encoding='utf-8') as f:
                    f.write(result_page_source)
                
                # Try to save a screenshot for visual verification
                try:
                    screenshot_filename = 'vote_result.png'
                    driver.save_screenshot(screenshot_filename)
                    debug_print(f"Screenshot saved to {screenshot_filename}")
                except Exception as screenshot_error:
                    debug_print(f"Could not save screenshot: {screenshot_error}")
                
                # Verify vote was successful by checking for success indicators in page text
                page_text = result_page_source.lower()
                if 'thank' in page_text or 'success' in page_text or 'voted' in page_text:
                    debug_print("✓ Vote appears to have been submitted successfully!")
                
                # Note: Performance timing and driver.quit() are now handled in finally block for guaranteed execution
                return True
            except Exception as e:
                display_error_message(f"Error clicking button: {e}")
                # Try JavaScript click as fallback
                try:
                    # Save the initial page state for comparison
                    initial_page_source = driver.page_source
                    initial_url = driver.current_url
                    
                    driver.execute_script("arguments[0].click();", vote_button)
                    debug_print("✓ Clicked using JavaScript")
                    debug_print("Waiting for vote to be processed...")
                    
                    # Wait for the results page - same logic as above
                    result_page_source = None
                    max_wait = 20
                    wait_interval = 0.5
                    waited = 0
                    found_results = False
                    
                    debug_print("Waiting for results page to appear...")
                    while waited < max_wait and not found_results:
                        time.sleep(wait_interval)
                        waited += wait_interval
                        
                        # Check current frame for "Thank you for voting!"
                        try:
                            thank_you_elements = driver.find_elements(By.XPATH,
                                "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'thank you for voting')]")
                            if thank_you_elements:
                                for elem in thank_you_elements:
                                    if elem.is_displayed():
                                        debug_print("✓ Found 'Thank you for voting!' message")
                                        found_results = True
                                        time.sleep(2)
                                        result_page_source = driver.page_source
                                        break
                            if found_results:
                                break
                        except:
                            pass
                        
                        # Check for percentages
                        try:
                            percentage_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '%')]")
                            visible_percentages = [e for e in percentage_elements if e.is_displayed() and '%' in e.text]
                            if len(visible_percentages) > 3:
                                debug_print(f"✓ Found {len(visible_percentages)} percentage displays")
                                found_results = True
                                time.sleep(2)
                                result_page_source = driver.page_source
                                break
                        except:
                            pass
                    
                    # Check other frames if needed (same logic as above)
                    if not found_results and in_iframe:
                        debug_print("Checking default content and other iframes...")
                        driver.switch_to.default_content()
                        time.sleep(2)
                        # Check default content and all iframes (same code as above)
                        for iframe, src, iframe_id in all_iframes:
                            try:
                                driver.switch_to.frame(iframe)
                                time.sleep(1)
                                thank_you_elements = driver.find_elements(By.XPATH,
                                    "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'thank you for voting')]")
                                if thank_you_elements:
                                    for elem in thank_you_elements:
                                        if elem.is_displayed():
                                            debug_print(f"✓ Found results in iframe: {iframe_id}")
                                            found_results = True
                                            time.sleep(2)
                                            result_page_source = driver.page_source
                                            break
                                if found_results:
                                    break
                                driver.switch_to.default_content()
                            except:
                                driver.switch_to.default_content()
                    
                    if not result_page_source:
                        debug_print("⚠ Results not found, saving current page state")
                        if in_iframe:
                            try:
                                driver.switch_to.frame(active_iframe)
                            except:
                                pass
                        result_page_source = driver.page_source
                    
                    # Save the result page
                    result_filename = 'vote_result.html'
                    debug_print(f"Saving result page to {result_filename}...")
                    with open(result_filename, 'w', encoding='utf-8') as f:
                        f.write(result_page_source)
                    
                    # Try to save a screenshot
                    try:
                        screenshot_filename = 'vote_result.png'
                        driver.save_screenshot(screenshot_filename)
                        debug_print(f"Screenshot saved to {screenshot_filename}")
                    except Exception as screenshot_error:
                        debug_print(f"Could not save screenshot: {screenshot_error}")
                    
                    # Check if vote was successful
                    page_text = result_page_source.lower()
                    if 'thank' in page_text or 'success' in page_text or 'voted' in page_text:
                        debug_print("✓ Vote appears to have been submitted successfully!")
                    
                    # Note: Performance timing and driver.quit() are now handled in finally block for guaranteed execution
                    return True
                except Exception as e2:
                    display_error_message(f"JavaScript click also failed: {e2}")
        else:
            # Use error message display instead of direct print
            display_error_message("Could not locate vote button for Cutler Whitaker")
            display_error_message("Page source saved to page_source.html for manual inspection")
        
        # Switch back to default content if we were in an iframe
        if in_iframe and driver is not None:
            try:
                driver.switch_to.default_content()
            except:
                pass
        
        # Note: Performance timing and driver.quit() are now handled in finally block for guaranteed execution
        return False
            
    except Exception as e:
        display_error_message(f"Selenium error: {e}")
        if debug_mode:
            import traceback
            traceback.print_exc()
        return False
    
    finally:
        # CRITICAL: Always print performance timing and clean up WebDriver
        # This ensures these messages appear even if exceptions occur
        vote_function_elapsed = time.time() - vote_function_start
        
        # Determine if this was a success or failure by checking if we have a result
        # (This is a best-effort check - the actual return value determines success/failure)
        try:
            if os.path.exists('vote_result.html'):
                # Check if result file indicates success
                try:
                    with open('vote_result.html', 'r', encoding='utf-8') as f:
                        result_content = f.read().lower()
                        if 'thank' in result_content or 'success' in result_content or 'voted' in result_content:
                            debug_print(f"[PERF] submit_vote_selenium() completed in {vote_function_elapsed:.2f} seconds")
                        else:
                            debug_print(f"[PERF] submit_vote_selenium() completed in {vote_function_elapsed:.2f} seconds (may have failed)")
                except:
                    debug_print(f"[PERF] submit_vote_selenium() completed in {vote_function_elapsed:.2f} seconds")
            else:
                debug_print(f"[PERF] submit_vote_selenium() completed in {vote_function_elapsed:.2f} seconds (failed)")
        except:
            # Fallback: always print timing even if we can't determine status
            debug_print(f"[PERF] submit_vote_selenium() completed in {vote_function_elapsed:.2f} seconds")
        
        # CRITICAL: Always clean up WebDriver to prevent memory leaks and orphaned processes
        # This ensures Chrome/ChromeDriver processes are terminated even on exceptions
        if driver is not None:
            try:
                driver.quit()
                debug_print("[CLEANUP] WebDriver cleaned up successfully")
            except Exception as cleanup_error:
                # If quit() fails, try to kill the process directly
                debug_print(f"[CLEANUP] WebDriver.quit() failed: {cleanup_error}")
                try:
                    # Attempt to kill Chrome processes as fallback
                    import gc
                    gc.collect()  # Force garbage collection
                except:
                    pass
        
        # Clean up service object if it exists
        if service is not None:
            try:
                service.stop()
            except:
                pass
        
        # Force garbage collection to help release Selenium objects
        import gc
        gc.collect()

def extract_voting_results(html_content):
    """
    Extract voting results (athlete names and percentages) from the results page HTML.
    
    This function uses multiple strategies to parse the HTML and extract voting results:
    1. Primary: Look for poll widget classes (pds-feedback-group, pds-answer-text, pds-feedback-per)
    2. Fallback: Search for text patterns matching "Name, info... XX.XX%"
    3. Last resort: Find percentage displays and extract nearby athlete names
    
    The function handles various HTML structures and formats, normalizes names,
    validates percentages, removes duplicates, and sorts by percentage descending.
    Also extracts the total number of votes cast from the page.
    
    Args:
        html_content (str): HTML content of the results page to parse
    
    Returns:
        tuple: (results, total_votes) where:
            - results: List of tuples containing (athlete_name, percentage) sorted by percentage
              in descending order. Example: [("Cutler Whitaker", 23.58), ("Dylan Papushak", 24.23)]
              Returns empty list if no results could be extracted.
            - total_votes: Integer representing total number of votes cast, or None if not found
    """
    results = []
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove script and style tags to avoid parsing CSS/JS as text content
        # This prevents false positives when searching for athlete names
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Strategy 1: Look for poll-specific structure used by many polling widgets
        # The structure typically uses classes like:
        # - pds-feedback-group: Container for each result
        # - pds-answer-text: Contains athlete name and info
        # - pds-feedback-per: Contains the percentage
        feedback_groups = soup.find_all(class_=re.compile(r'pds-feedback-group', re.I))
        
        for group in feedback_groups:
            try:
                # Find the athlete name in pds-answer-text
                answer_text_elem = group.find(class_=re.compile(r'pds-answer-text', re.I))
                if not answer_text_elem:
                    continue
                
                # Get the full text (name, grade, school, sport)
                full_text = answer_text_elem.get_text(strip=True)
                if not full_text:
                    continue
                
                # Extract just the athlete name (first part before first comma)
                # Format example: "Dylan Papushak, jr., Berea-Midpark (Ohio) football"
                # We only want "Dylan Papushak" from this string
                name = full_text.split(',')[0].strip()
                if not name or len(name) < 3:  # Skip if name is too short (likely invalid)
                    continue
                
                # Find the percentage element in this result group
                feedback_per_elem = group.find(class_=re.compile(r'pds-feedback-per', re.I))
                if not feedback_per_elem:
                    continue
                
                # Extract percentage text and parse the numeric value
                pct_text = feedback_per_elem.get_text(strip=True)
                pct_match = re.search(r'(\d+\.?\d*)%', pct_text)  # Match patterns like "23.58%"
                if not pct_match:
                    continue
                
                percentage = float(pct_match.group(1))
                
                # Validate percentage is within reasonable range (0-100%)
                if 0 <= percentage <= 100:
                    results.append((name, percentage))
                    
            except Exception as e:
                continue
        
        # Strategy 2: If primary method found no results, try regex pattern matching
        # This handles cases where the HTML structure is different but still follows
        # a predictable text pattern
        if not results:
            # Look for text patterns like "Name, info... XX.XX%"
            body_text = soup.get_text()
            
            # Pattern: Name followed by comma and info, then percentage
            # Example match: "Cutler Whitaker, sr., Mountain... 23.82%"
            # The regex captures: (1) First name, (2) Last name, (3) Percentage
            pattern = re.compile(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+),?\s+[^,]*,\s+[^,]*,\s*([^0-9]*?)\s*(\d+\.?\d*)%')
            matches = pattern.findall(body_text)
            
            for match in matches:
                name_part1 = match[0] if match[0] else ''
                name_part2 = match[1] if match[1] else ''
                percentage_str = match[2] if len(match) > 2 else ''
                
                # Try to reconstruct name
                if name_part1:
                    name = name_part1.strip()
                    if name_part2 and len(name_part2.strip()) > 2:
                        name += ' ' + name_part2.strip()
                    
                    try:
                        percentage = float(percentage_str)
                        if 0 <= percentage <= 100:  # Valid percentage range
                            results.append((name, percentage))
                    except:
                        pass
        
        # Strategy 3: Last resort - find any percentages and extract nearby names
        # This is a more aggressive approach that looks for any percentage in the page
        # and tries to find associated athlete names in the same element
        if not results:
            percentage_pattern = re.compile(r'(\d+\.?\d*)%')
            all_elements = soup.find_all(string=percentage_pattern)
            
            for text_node in all_elements:
                try:
                    # Skip if this is in a script or style context (would be CSS/JS, not real data)
                    parent = text_node.parent
                    if parent and parent.name in ['script', 'style']:
                        continue
                    
                    match = percentage_pattern.search(text_node)
                    if match:
                        percentage = float(match.group(1))
                        
                        # Only process reasonable percentages (0-100%)
                        if not (0 <= percentage <= 100):
                            continue
                        
                        # Look for athlete name in the parent element's text
                        # Check parent and siblings for text that looks like a name
                        if parent:
                            # Get all text from parent, but exclude CSS-like content
                            parent_text = parent.get_text(separator=' ', strip=True)
                            
                            # Pattern: Name, title, school... percentage
                            # Look for capitalized words (proper names) before the percentage
                            name_pattern = re.compile(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)[^0-9]*?(\d+\.?\d*)%')
                            name_match = name_pattern.search(parent_text)
                            
                            if name_match:
                                name = name_match.group(1).strip()
                                # Clean up - remove extra info after comma (e.g., "John Doe, jr." -> "John Doe")
                                name = name.split(',')[0].strip()
                                
                                # Filter out CSS selectors and other junk that might match the pattern
                                if (len(name) > 3 and 
                                    not name.startswith('#') and  # Not a CSS ID
                                    not name.startswith('.') and  # Not a CSS class
                                    ':' not in name and  # Not a CSS property
                                    '{' not in name):  # Not CSS syntax
                                    results.append((name, percentage))
                except:
                    continue
        
        # Remove duplicates and sort by percentage descending
        # Use case-insensitive name comparison to catch duplicates like "Cutler Whitaker" vs "cutler whitaker"
        seen = set()
        unique_results = []
        for name, pct in results:
            # Normalize name for comparison (lowercase, stripped)
            name_normalized = name.lower().strip()
            if name_normalized not in seen and len(name) > 3:  # Skip duplicates and invalid names
                seen.add(name_normalized)
                unique_results.append((name, pct))
        
        # Sort by percentage descending (highest votes first)
        unique_results.sort(key=lambda x: x[1], reverse=True)
        
        # Extract total votes count from the page
        # Look for patterns like "Total Votes: 58,836" or "Total Votes: 58836"
        total_votes = None
        try:
            # Search for "Total Votes" text in the HTML
            body_text = soup.get_text()
            # Pattern to match "Total Votes: 58,836" or "Total Votes: 58836" or "Total Votes 58,836"
            total_patterns = [
                re.compile(r'Total\s+Votes?\s*:?\s*([\d,]+)', re.IGNORECASE),
                re.compile(r'Total\s+Votes?\s*:?\s*(\d+)', re.IGNORECASE),
            ]
            
            for pattern in total_patterns:
                match = pattern.search(body_text)
                if match:
                    # Extract number and remove commas
                    total_votes_str = match.group(1).replace(',', '')
                    try:
                        total_votes = int(total_votes_str)
                        break
                    except ValueError:
                        continue
        except Exception as e:
            # If we can't extract total votes, that's okay - it's optional
            debug_print(f"Could not extract total votes: {e}")
        
    except Exception as e:
        display_error_message(f"Error extracting results: {e}")
        if debug_mode:
            import traceback
            traceback.print_exc()
        return [], None
    
    return unique_results, total_votes

def print_top_results(results, top_n=5, total_votes=None):
    """
    Print the top N voting results in a fixed area above thread lines.
    
    Displays athlete names and their vote percentages in a clean, readable format.
    The results are printed in a fixed area above all thread status lines.
    Also includes verification info if available.
    
    Args:
        results (list): List of tuples containing (athlete_name, percentage) sorted by percentage
        top_n (int): Number of top results to display (default: 5)
        total_votes (int, optional): Total number of votes cast across all candidates
    
    Returns:
        list: The results list passed in (for chaining), or None if no results
    """
    global _status_display_paused, _results_area_start, _results_area_height, _max_thread_lines
    global _ansi_supported, _is_windows, _verification_info_lines
    
    if not _display_initialized:
        _init_display_coordinator()
    
    # Pause status display updates while printing results
    with _status_lock:
        _status_display_paused = True
    time.sleep(0.1)  # Brief pause to ensure status thread sees the flag
    
    # Build results text
    result_lines = []
    result_lines.append("")  # Blank line to separate from startup command
    result_lines.append(f"TOP {min(top_n, len(results))} VOTING RESULTS:")
    
    if results:
        for i, (name, percentage) in enumerate(results[:top_n], 1):
            result_lines.append(f"{i}. {name:<40} {percentage:>6.2f}%")
    else:
        result_lines.append("(No results available)")
    
    if total_votes is not None:
        total_votes_formatted = f"{total_votes:,}"
        result_lines.append(f"Total Votes: {total_votes_formatted}")
    
    # Add separator before verification info
    result_lines.append("")  # Blank line
    result_lines.append("=" * 60)
    
    # Add verification info if available
    if _verification_info_lines:
        result_lines.extend(_verification_info_lines)
    else:
        # Reserve space for verification info (will be filled later)
        # Use fixed number of lines to prevent layout shift
        result_lines.append("VOTE VERIFICATION: (Waiting for first check...)")
        result_lines.append("=" * 60)
        result_lines.append("Our vote count:           (waiting...)")
        result_lines.append("Total votes on server:    (waiting...)")
        result_lines.append("Cutler's percentage:      (waiting...)")
        result_lines.append("Cutler's vote count:      (waiting...)")
        result_lines.append("")
        result_lines.append("Expected increase:        (waiting...)")
        result_lines.append("Actual increase:          (waiting...)")
        result_lines.append("Effectiveness:            (waiting...)")
        result_lines.append("=" * 60)
    
    # Add separator between results/verification and thread status
    result_lines.append("")  # Blank line
    result_lines.append("=" * 60)  # Separator line
    result_lines.append("")  # Blank line
    
    # Print results in fixed area (top of screen)
    with _display_lock:
        if _ansi_supported:
            # Move to top-left corner
            print('\033[H', end='', flush=True)
            
            # Clear and print each line in results area
            for i in range(_results_area_height):
                print('\033[K', end='', flush=True)  # Clear current line
                if i < len(result_lines):
                    # Print result line (with newline - this moves us to next line)
                    print(result_lines[i], flush=True)
                else:
                    # Clear remaining blank lines (print newline to move down)
                    print(flush=True)
        else:
            # Windows Command Prompt without ANSI support: print normally
            # Results will appear above threads, but will scroll
            # No ANSI escape codes are used here - just plain text
            for line in result_lines:
                print(line, flush=True)
    
    # Resume status display
    with _status_lock:
        _status_display_paused = False
    
    return results

def is_cutler_ahead(results):
    """
    Check if Cutler Whitaker is in first place in the voting results.
    
    This function determines if Cutler Whitaker is the top-ranked athlete by checking
    if the first result matches Cutler's name. It handles variations in name formatting
    (case-insensitive, partial matches).
    
    Args:
        results (list): List of tuples containing (athlete_name, percentage) sorted by percentage
    
    Returns:
        bool: True if Cutler Whitaker is in first place (results[0][0] matches TARGET_ATHLETE),
              False if he is not first, if results list is empty, or if results is None
    """
    if not results:
        return False
    
    # Check if first place is Cutler Whitaker
    # Use case-insensitive comparison to handle variations
    first_place_name = results[0][0].lower()
    cutler_name = TARGET_ATHLETE.lower()
    
    # Check for exact match or if both "cutler" and "whitaker" are in the name
    # This handles cases like "cutler whitaker" vs "Cutler Whitaker" vs "Cutler Whitaker, sr."
    if cutler_name in first_place_name or \
       ('cutler' in first_place_name and 'whitaker' in first_place_name):
        return True
    
    return False

def get_cutler_lead_percentage(results, lead_threshold):
    """
    Calculate Cutler's lead percentage over the next closest competitor.
    
    Args:
        results (list): List of tuples containing (athlete_name, percentage) sorted by percentage
        lead_threshold (float): Minimum lead percentage to trigger backoff
    
    Returns:
        tuple: (lead_percentage, is_above_threshold) where:
            - lead_percentage: Cutler's percentage lead over second place (or None if not in first)
            - is_above_threshold: True if lead is >= lead_threshold
    """
    if not results or len(results) < 2:
        return None, False
    
    # Check if Cutler is in first place
    first_place_name = results[0][0].lower()
    cutler_name = TARGET_ATHLETE.lower()
    
    if not (cutler_name in first_place_name or 
            ('cutler' in first_place_name and 'whitaker' in first_place_name)):
        return None, False
    
    # Cutler is in first place - calculate lead
    cutler_percentage = results[0][1]
    second_place_percentage = results[1][1]
    lead_percentage = cutler_percentage - second_place_percentage
    
    is_above_threshold = lead_percentage >= lead_threshold
    
    return lead_percentage, is_above_threshold

def signal_handler(sig, frame):
    """
    Handle Ctrl+C (SIGINT) gracefully to allow clean shutdown.
    
    When the user presses Ctrl+C, this handler sets the global shutdown_flag
    to True, which causes the main voting loop to exit cleanly after completing
    the current vote attempt. This prevents abrupt termination and allows the
    script to display a summary of votes submitted.
    
    Works on both Unix-like systems and Windows.
    
    Args:
        sig: Signal number (unused, required by signal handler signature)
        frame: Current stack frame (unused, required by signal handler signature)
    """
    global shutdown_flag
    # Don't print here - let the finally block handle all output after display is stopped
    # This prevents interference with the fixed display
    shutdown_flag = True
    # Don't call sys.exit() here - let the main loop's finally block handle cleanup
    # This ensures statistics are displayed and threads are properly shut down

def perform_vote_iteration(thread_id="Main"):
    """
    Perform a single voting iteration (vote submission and result processing).
    
    This function encapsulates the core voting logic so it can be reused
    by both the main thread and parallel voting threads.
    
    Args:
        thread_id (str): Identifier for the thread performing the vote (for logging)
    
    Returns:
        tuple: (success, results, cutler_ahead) where:
            - success: bool indicating if vote was submitted successfully
            - results: list of voting results or None
            - cutler_ahead: bool indicating if Cutler is in first place
    """
    global vote_count, consecutive_behind_count, standard_vote_count
    global initial_accelerated_vote_count, accelerated_vote_count, super_accelerated_vote_count
    
    # Track vote duration for performance monitoring
    vote_iteration_start = time.time()
    
    # Thread-safe increment of vote count
    with _counter_lock:
        vote_count += 1
        current_vote_num = vote_count
    
    # Update centralized status display with vote attempt message
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    update_thread_status(thread_id, 'message', current_vote_num, 
                        f"[{thread_id}] VOTE ATTEMPT #{current_vote_num} - {timestamp}")
    
    # Update to processing status
    update_thread_status(thread_id, 'processing', current_vote_num)
    
    # Submit vote using Selenium browser automation
    success = submit_vote_selenium()
    
    # Clear status after vote completes
    update_thread_status(thread_id, 'completed')
    
    # Get current timestamp for logging
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    
    # Initialize variables that may be used in both success and failure paths
    results = None
    total_votes = None  # Track total votes from server for verification
    cutler_ahead = False
    vote_type = "standard"  # Default vote type
    lead_percentage = None
    
    if success:
        # Update thread status with success message
        update_thread_status(thread_id, 'message', current_vote_num, 
                            f"[{thread_id}] ✓ Vote #{current_vote_num} submitted successfully!")
        
        # Try to extract and display results
        try:
            with open('vote_result.html', 'r', encoding='utf-8') as f:
                result_html = f.read()
            
            results, total_votes = extract_voting_results(result_html)
            if results:
                if thread_id == "Main":  # Only main thread prints results to avoid clutter
                    # Print results (includes verification info if available)
                    print_top_results(results, top_n=5, total_votes=total_votes)
                
                cutler_ahead = is_cutler_ahead(results)
                
                # Update consecutive behind counter for adaptive timing (thread-safe)
                with _counter_lock:
                    if cutler_ahead:
                        consecutive_behind_count = 0
                        standard_vote_count += 1
                        vote_type = "standard"
                        if thread_id == "Main":
                            update_thread_status("Main", 'message', current_vote_num, 
                                                f"[Main] ✓ {TARGET_ATHLETE} is in FIRST PLACE! Using standard interval.")
                    else:
                        consecutive_behind_count += 1
                        current_behind = consecutive_behind_count
                        if current_behind >= 10:
                            super_accelerated_vote_count += 1
                            vote_type = "super_accelerated"
                            if thread_id == "Main":
                                update_thread_status("Main", 'message', current_vote_num, 
                                                    f"[Main] ⚠ {TARGET_ATHLETE} has been behind for {current_behind} consecutive rounds. Using SUPER ACCELERATED voting!")
                        elif current_behind >= 5:
                            accelerated_vote_count += 1
                            vote_type = "accelerated"
                            if thread_id == "Main":
                                update_thread_status("Main", 'message', current_vote_num, 
                                                    f"[Main] ⚠ {TARGET_ATHLETE} has been behind for {current_behind} consecutive rounds. Using accelerated voting.")
                        else:
                            initial_accelerated_vote_count += 1
                            vote_type = "initial_accelerated"
                            if thread_id == "Main":
                                update_thread_status("Main", 'message', current_vote_num, 
                                                    f"[Main] ⚠ {TARGET_ATHLETE} is not in first place ({current_behind}/5 rounds behind). Using initial accelerated voting.")
                
                # Calculate lead percentage if Cutler is ahead (for logging)
                if cutler_ahead and results and len(results) >= 2:
                    cutler_percentage = results[0][1]
                    second_place_percentage = results[1][1]
                    lead_percentage = cutler_percentage - second_place_percentage
                
                # Note: Lead percentage checking and backoff adjustment happens in main() after this function returns
            else:
                if thread_id == "Main":
                    update_thread_status("Main", 'message', current_vote_num, 
                                        f"[Main] ⚠ Could not extract results from page")
                with _counter_lock:
                    standard_vote_count += 1
                    vote_type = "standard"
        except FileNotFoundError:
            if thread_id == "Main":
                update_thread_status("Main", 'message', current_vote_num, 
                                    f"[Main] ⚠ Result file not found, skipping result extraction")
            with _counter_lock:
                standard_vote_count += 1
                vote_type = "standard"
        except Exception as e:
            if thread_id == "Main":
                update_thread_status("Main", 'message', current_vote_num, 
                                    f"[Main] ⚠ Error extracting results: {e}")
            with _counter_lock:
                standard_vote_count += 1
                vote_type = "standard"
    else:
        # Update thread status with failure message
        update_thread_status(thread_id, 'message', current_vote_num, 
                            f"[{thread_id}] ⚠ Vote #{current_vote_num} failed")
        # For failed votes, determine vote type based on current behind count
        with _counter_lock:
            current_behind = consecutive_behind_count
            if current_behind >= 10:
                vote_type = "super_accelerated"
            elif current_behind >= 5:
                vote_type = "accelerated"
            elif current_behind >= 1:
                vote_type = "initial_accelerated"
            else:
                vote_type = "standard"
    
    # Determine if this vote was cast during exponential backoff
    # Backoff is active when Cutler is ahead, has a lead percentage, and the backoff multiplier is > 1.0
    # We check the multiplier BEFORE the main loop updates it, so we capture the state when this vote was cast
    is_backoff_active = False
    if cutler_ahead and lead_percentage is not None:
        # Check the current backoff multiplier (thread-safe)
        # This value reflects the multiplier state BEFORE this vote was cast
        # (since the main loop updates it after perform_vote_iteration returns)
        with lead_backoff_lock:
            current_backoff = lead_backoff_multiplier
        # If multiplier > 1.0, it means backoff was active when this vote cycle started
        # This vote was cast during a backoff period
        is_backoff_active = (current_backoff > 1.0)
    
    # Calculate vote duration (time from start to completion)
    vote_duration = time.time() - vote_iteration_start
    
    # Log vote to JSON file (thread-safe)
    with _counter_lock:
        current_behind_for_log = consecutive_behind_count
    log_vote_to_json(
        vote_num=current_vote_num,
        thread_id=thread_id,
        timestamp=timestamp,
        success=success,
        results=results,
        cutler_ahead=cutler_ahead if success else False,
        consecutive_behind_count=current_behind_for_log,
        vote_type=vote_type,
        lead_percentage=lead_percentage,
        is_backoff_vote=is_backoff_active,
        vote_duration=vote_duration
    )
    
    # Check if we should perform vote verification
    # Only main thread performs verification (to avoid race conditions)
    # Verification is triggered: after first vote, then every 500 votes
    # We check the GLOBAL vote_count (not current_vote_num) to catch thresholds hit by any thread
    global _last_verification_vote_count, _first_vote_completed
    if thread_id == "Main":
        # Mark first vote as completed
        if not _first_vote_completed:
            _first_vote_completed = True
        
        should_verify = False
        # Check the global vote_count (which includes votes from all threads)
        # This ensures we catch verification thresholds even if parallel threads hit them
        with _counter_lock:
            # Check if global vote_count is a multiple of 500 (or first vote)
            # This catches thresholds regardless of which thread hit them
            if vote_count == 1 or (vote_count % 500 == 0):
                # Double-check we haven't already verified this vote count
                if vote_count != _last_verification_vote_count:
                    should_verify = True
                    # Update last verification count immediately to prevent duplicate checks
                    _last_verification_vote_count = vote_count
        
        # Perform verification if needed (only on successful votes with results)
        if should_verify and success and results and total_votes is not None:
            # Find Cutler's percentage from results
            cutler_percentage = None
            for name, percentage in results:
                name_lower = name.lower()
                if 'cutler' in name_lower and 'whitaker' in name_lower:
                    cutler_percentage = percentage
                    break
            
            if cutler_percentage is not None:
                # Log verification to file and update display
                # Use global vote_count (not current_vote_num) to reflect total votes from all threads
                with _counter_lock:
                    global_vote_count = vote_count
                log_vote_verification(global_vote_count, total_votes, cutler_percentage, results)
                # Refresh the display to show updated verification info immediately
                # Re-print results with new verification info
                print_top_results(results, top_n=5, total_votes=total_votes)
    
    return success, results, cutler_ahead

def parallel_voting_thread(thread_index):
    """
    Parallel voting thread that runs when Cutler has been behind for a specified number of rounds.
    
    This thread performs the same voting operations as the main thread,
    using Super Accelerated timing (3-10 seconds) to help catch up.
    The thread stops automatically when Cutler gets back in the lead (unless force_parallel_mode is enabled).
    
    Args:
        thread_index (int): Index of this thread (0-based, used to access _parallel_active and _parallel_thresholds)
    """
    global shutdown_flag, _parallel_active, _parallel_thresholds, _force_parallel_mode
    
    thread_name = f"Parallel-{thread_index + 1}"
    threshold = _parallel_thresholds[thread_index] if thread_index < len(_parallel_thresholds) else 20 + (thread_index * 10)
    
    # Update thread status with starting message
    update_thread_status(thread_name, 'message', 0, f"[{thread_name}] 🚀 Starting parallel voting thread to accelerate votes!")
    
    while not shutdown_flag:
        # Check if we should continue parallel voting
        with _parallel_voting_lock:
            if thread_index < len(_parallel_active) and not _parallel_active[thread_index]:
                update_thread_status(thread_name, 'message', 0, f"[{thread_name}] ⏹ Stopping parallel voting thread (Cutler is ahead)")
                break
        
        # Check current behind count
        with _counter_lock:
            current_behind = consecutive_behind_count
        
        # Only continue if Cutler is still behind the threshold (unless forced)
        if current_behind < threshold and not _force_parallel_mode:
            update_thread_status(thread_name, 'message', 0, f"[{thread_name}] ⏹ Stopping parallel voting thread (Cutler catching up - below {threshold} rounds)")
            with _parallel_voting_lock:
                if thread_index < len(_parallel_active):
                    _parallel_active[thread_index] = False
            break
        
        # Perform vote using Super Accelerated timing (3-10 seconds)
        success, results, cutler_ahead = perform_vote_iteration(thread_id=thread_name)
        
        # If Cutler is now ahead, stop parallel voting (unless forced)
        if cutler_ahead and not _force_parallel_mode:
            with _parallel_voting_lock:
                if thread_index < len(_parallel_active):
                    _parallel_active[thread_index] = False
            update_thread_status(thread_name, 'message', 0, f"[{thread_name}] ⏹ Stopping parallel voting thread (Cutler is now ahead!)")
            break
        
        # Wait 3-10 seconds before next vote (Super Accelerated interval)
        if not shutdown_flag:
            wait_time = random.randint(3, 10)
            update_thread_status(thread_name, 'message', 0, f"[{thread_name}] Waiting {wait_time} seconds before next vote (SUPER ACCELERATED)...")
            
            waited = 0
            while waited < wait_time and not shutdown_flag:
                # Check if we should stop parallel voting
                with _parallel_voting_lock:
                    if thread_index < len(_parallel_active) and not _parallel_active[thread_index]:
                        break
                time.sleep(1)
                waited += 1
    
    update_thread_status(thread_name, 'message', 0, f"[{thread_name}] 🛑 Parallel voting thread stopped")

def initialize_parallel_threads(max_threads):
    """
    Initialize the parallel thread arrays for scalable thread management.
    
    This function sets up the data structures needed to support N parallel threads
    dynamically, without hardcoding individual thread variables.
    
    Args:
        max_threads (int): Maximum number of parallel threads to support
                           (not including main thread)
    """
    global _parallel_threads, _parallel_active, _parallel_thresholds
    
    _parallel_threads = []
    _parallel_active = []
    _parallel_thresholds = []
    
    for i in range(max_threads):
        _parallel_threads.append(None)
        _parallel_active.append(False)
        # Thresholds: 20, 30, 40, 50, 60, 70, 80, etc. (increment by 10 per thread)
        _parallel_thresholds.append(20 + (i * 10))

def main():
    """
    Main entry point for the voting tool.
    
    This function:
    1. Parses command-line arguments (debug mode)
    2. Sets up signal handlers for graceful shutdown
    3. Runs a continuous voting loop with adaptive timing
    4. Extracts and displays results after each vote
    5. Adjusts voting speed based on Cutler's position in the results
    6. Starts parallel voting thread when Cutler is behind 20+ rounds
    
    The voting loop continues until the user presses Ctrl+C, which triggers
    graceful shutdown via the signal handler.
    
    Adaptive Timing (Four-tier system):
    - Standard (Cutler ahead): 53-67 seconds between votes
    - Initial Accelerated (Cutler behind 1-4 rounds): 14-37 seconds between votes
    - Accelerated (Cutler behind 5-9 rounds): 7-16 seconds between votes
    - Super Accelerated (Cutler behind 10+ rounds): 3-10 seconds between votes
    
    Parallel Processing (Scalable Design):
    - Threads start automatically when Cutler is behind, with thresholds: 20, 30, 40, 50, 60, 70, 80, etc.
    - Threshold increments by 10 for each additional parallel thread
    - Default maximum: 8 total threads (1 main + 7 parallel), configurable via --max-threads
    - All parallel threads vote using Super Accelerated timing (3-10 seconds)
    - Parallel threads stop automatically when Cutler gets back in the lead or below threshold
    - Supports any number of threads (scalable design - no hardcoded limits)
    
    The script tracks vote counts by type and displays statistics on exit.
    """
    global shutdown_flag, debug_mode
    global _parallel_threads, _parallel_active, _parallel_thresholds
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Vote for Cutler Whitaker on Sports Illustrated poll')
    parser.add_argument('-debug', '--debug', action='store_true', 
                       help='Enable debug output (verbose logging)')
    parser.add_argument('--start-threads', type=int, default=1,
                       help='Number of threads to start with (1=main only, 2=main+1 parallel, etc.). '
                            'Useful if Cutler is already behind and you want to skip waiting for thresholds. '
                            'Default: 1. Maximum: 8 (1 main + 7 parallel).')
    parser.add_argument('--max-threads', type=int, default=8,
                       help='Maximum number of total threads (main + parallel). Default: 8. '
                            'This sets the maximum number of parallel threads that can be started. '
                            'Note: This affects the maximum --start-threads value.')
    parser.add_argument('--lead-threshold', type=float, default=15.0,
                       help='Percentage lead threshold to trigger backoff (default: 15.0). '
                            'When Cutler is ahead by this percentage or more, exponential backoff is used.')
    parser.add_argument('--save-top-results', action='store_true', default=False,
                       help='Save top 5 results for each vote in JSON file (default: False). '
                            'Disable to keep file size smaller on long runs.')
    parser.add_argument('--force-parallel', action='store_true', default=False,
                       help='Force parallel threads to stay active even when Cutler is ahead. '
                            'When enabled, parallel threads will continue running regardless of '
                            'Cutler\'s position or behind count. Useful for maximum voting speed.')
    parser.add_argument('--check-system', action='store_true', default=False,
                       help='Display system CPU information and thread count recommendations, then exit.')
    args = parser.parse_args()
    
    # Handle --check-system option
    if args.check_system:
        print(f"\n{'='*60}")
        print("SYSTEM CPU INFORMATION")
        print(f"{'='*60}\n")
        
        try:
            import multiprocessing
            # Get both physical cores and logical processors
            # Note: multiprocessing.cpu_count(logical=False) requires Python 3.8+
            # On older Python versions or some platforms, we'll use logical count for both
            try:
                physical_cores = multiprocessing.cpu_count(logical=False)  # Physical cores only (Python 3.8+)
            except (TypeError, AttributeError):
                # Fallback for Python < 3.8 or platforms where logical=False isn't supported
                # In this case, we can't distinguish physical from logical, so use the total count
                physical_cores = multiprocessing.cpu_count()
            logical_processors = multiprocessing.cpu_count()  # Total logical processors (includes hyperthreading)
            
            # Calculate recommendations
            safe_recommendation = min(logical_processors, physical_cores * 2)
            moderate_recommendation = min(logical_processors * 1.5, physical_cores * 3)
            aggressive_recommendation = logical_processors * 2
            
            print(f"Physical CPU Cores:        {physical_cores}")
            print(f"Logical Processors:        {logical_processors}")
            if physical_cores < logical_processors:
                print(f"Hyperthreading:            Enabled ({logical_processors // physical_cores}x per core)")
            else:
                print(f"Hyperthreading:            Not detected")
            print(f"\n{'='*60}")
            print("RECOMMENDED THREAD COUNTS")
            print(f"{'='*60}\n")
            print(f"Conservative (Safe):       --max-threads {int(safe_recommendation)}")
            print(f"   - Matches logical processors or 2x physical cores")
            print(f"   - Best balance of performance and stability")
            print(f"   - Recommended for most systems\n")
            print(f"Moderate:                  --max-threads {int(moderate_recommendation)}")
            print(f"   - 1.5x logical processors (up to 3x physical cores)")
            print(f"   - Good for systems with 4GB+ free RAM")
            print(f"   - May cause some CPU contention\n")
            print(f"Aggressive (Maximum):      --max-threads {int(aggressive_recommendation)}")
            print(f"   - 2x logical processors")
            print(f"   - Maximum voting speed")
            print(f"   - Requires 4GB+ free RAM and may cause system slowdown")
            print(f"   - Each Chrome instance uses ~200-500MB RAM\n")
            print(f"{'='*60}")
            print("MEMORY CONSIDERATIONS")
            print(f"{'='*60}\n")
            print(f"Each Chrome instance typically uses 200-500MB RAM.")
            print(f"Thread count estimates:")
            print(f"  - {int(safe_recommendation)} threads: ~{int(safe_recommendation * 0.3)}-{int(safe_recommendation * 0.5)}GB RAM")
            print(f"  - {int(moderate_recommendation)} threads: ~{int(moderate_recommendation * 0.3)}-{int(moderate_recommendation * 0.5)}GB RAM")
            print(f"  - {int(aggressive_recommendation)} threads: ~{int(aggressive_recommendation * 0.3)}-{int(aggressive_recommendation * 0.5)}GB RAM")
            print(f"\n{'='*60}\n")
            
        except Exception as e:
            print(f"Error detecting CPU information: {e}")
            print("Make sure you have Python's multiprocessing module available.\n")
        
        sys.exit(0)
    
    # Set debug mode based on command-line argument
    debug_mode = args.debug
    start_thread_count = args.start_threads
    max_threads = args.max_threads
    lead_threshold = args.lead_threshold
    
    # Validate thread counts
    if max_threads < 1:
        print("Error: --max-threads must be at least 1")
        sys.exit(1)
    if start_thread_count < 1:
        print("Error: --start-threads must be at least 1")
        sys.exit(1)
    if start_thread_count > max_threads:
        print(f"Error: --start-threads ({start_thread_count}) cannot exceed --max-threads ({max_threads})")
        sys.exit(1)
    
    # Detect CPU cores and provide recommendations
    try:
        import multiprocessing
        # Get both physical cores and logical processors
        # Note: multiprocessing.cpu_count(logical=False) requires Python 3.8+
        # On older Python versions or some platforms, we'll use logical count for both
        try:
            physical_cores = multiprocessing.cpu_count(logical=False)  # Physical cores only (Python 3.8+)
        except (TypeError, AttributeError):
            # Fallback for Python < 3.8 or platforms where logical=False isn't supported
            # In this case, we can't distinguish physical from logical, so use the total count
            physical_cores = multiprocessing.cpu_count()
        logical_processors = multiprocessing.cpu_count()  # Total logical processors (includes hyperthreading)
        
        # Calculate safe thread count recommendations
        # For I/O-bound tasks with Chrome, we can use 1-2x logical processors
        # But Chrome is resource-intensive, so be conservative
        safe_recommendation = min(logical_processors, physical_cores * 2)  # Up to logical processors, but conservative
        aggressive_recommendation = logical_processors * 2  # For maximum speed (I/O bound)
        
        if max_threads > logical_processors * 2:
            print(f"\n⚠ WARNING: Requested {max_threads} threads.")
            print(f"   System: {physical_cores} physical core(s), {logical_processors} logical processor(s)")
            print(f"   This exceeds recommended thread count ({logical_processors * 2}) and may cause:")
            print(f"   - High CPU usage and system slowdown")
            print(f"   - Memory pressure (each Chrome instance uses ~200-500MB)")
            print(f"   - Potential browser crashes")
            print(f"   Recommended: --max-threads {safe_recommendation} (safe) or {aggressive_recommendation} (aggressive)\n")
        elif max_threads > logical_processors:
            print(f"\n⚠ WARNING: Requested {max_threads} threads exceeds logical processors ({logical_processors}).")
            print(f"   System: {physical_cores} physical core(s), {logical_processors} logical processor(s)")
            print(f"   This may cause performance issues. Recommended: --max-threads {safe_recommendation}\n")
        elif max_threads <= logical_processors:
            if physical_cores < logical_processors:
                print(f"ℹ System: {physical_cores} physical core(s), {logical_processors} logical processor(s)")
                print(f"   Using {max_threads} threads (within logical processor limit).")
                if max_threads <= safe_recommendation:
                    print(f"   ✓ Thread count is within safe limits for this system.\n")
                else:
                    print(f"   ⚠ Consider reducing to {safe_recommendation} threads for optimal performance.\n")
            else:
                print(f"ℹ System: {physical_cores} CPU core(s). Using {max_threads} threads.\n")
    except Exception as e:
        # Fallback if multiprocessing is unavailable
        print("ℹ Could not detect CPU count. Using requested thread count.\n")
        if debug_mode:
            debug_print(f"CPU detection error: {e}")
    
    # Calculate maximum parallel threads (max_threads - 1 for main thread)
    max_parallel_threads = max_threads - 1
    
    # Initialize parallel thread arrays dynamically
    initialize_parallel_threads(max_parallel_threads)
    
    # Initialize thread line mapping for fixed display
    # Each thread gets a fixed line at the bottom: Main = line 0, Parallel-1 = line 1, etc.
    global _thread_line_map, _max_thread_lines
    _thread_line_map = {}
    _max_thread_lines = max_threads  # Reserve lines for all threads (main + parallel)
    
    # Map Main thread to line 0 (bottom)
    _thread_line_map["Main"] = 0
    
    # Map parallel threads to lines 1, 2, 3, ... (above Main)
    for i in range(max_parallel_threads):
        thread_name = f"Parallel-{i+1}"
        _thread_line_map[thread_name] = i + 1
    
    # Set global flags
    global _save_top_results, _force_parallel_mode
    _save_top_results = args.save_top_results
    _force_parallel_mode = args.force_parallel
    
    # Set up signal handler for graceful shutdown on Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    print(f"Voting tool for {TARGET_ATHLETE}")
    print(f"Target URL: {VOTE_URL}")
    print(f"Vote interval: {VOTE_INTERVAL} seconds")
    if debug_mode:
        print("Debug mode: ENABLED")
    if _force_parallel_mode:
        print("⚠ Force parallel mode: ENABLED (threads will stay active regardless of Cutler's position)")
    print(f"Press Ctrl+C to stop\n")
    
    # Initialize counters for tracking voting progress
    # These counters are thread-safe using _counter_lock
    # Reset all counters to 0 at start
    global vote_count, consecutive_behind_count, standard_vote_count
    global accelerated_vote_count, super_accelerated_vote_count, initial_accelerated_vote_count
    global lead_backoff_multiplier
    
    vote_count = 0  # Total number of vote attempts
    lead_backoff_multiplier = 1.0  # Reset backoff multiplier
    
    # Initialize consecutive_behind_count based on start-threads argument
    # This allows starting with parallel threads already active
    # Calculate threshold for the last thread that will be started
    if start_thread_count > 1:
        # Need threshold for the (start_thread_count - 1)th parallel thread (0-indexed)
        parallel_thread_index = start_thread_count - 2  # 0-indexed (start_thread_count=2 means index 0)
        if parallel_thread_index < len(_parallel_thresholds):
            initial_behind_count = _parallel_thresholds[parallel_thread_index]
        else:
            # Fallback: calculate threshold dynamically (20 + (index * 10))
            initial_behind_count = 20 + (parallel_thread_index * 10)
    else:
        # Start with 1 thread (main only) - normal start
        initial_behind_count = 0
    
    consecutive_behind_count = initial_behind_count  # Track consecutive rounds where Cutler is behind (for adaptive timing)
    
    # Reset vote type counts for statistics (thread-safe)
    standard_vote_count = 0  # Votes when Cutler is ahead
    accelerated_vote_count = 0  # Votes when Cutler is behind 5-9 rounds
    super_accelerated_vote_count = 0  # Votes when Cutler is behind 10+ rounds
    initial_accelerated_vote_count = 0  # Votes when Cutler is behind 1-4 rounds
    
    # Initialize session ID for JSON logging (unique per application run)
    # This prevents duplicate vote numbers from being confusing across restarts
    # Each restart gets a new session_id, but vote_number resets to 1 for each session
    global _current_session_id, _first_vote_completed, _last_verification_vote_count
    if _current_session_id is None:
        session_start_time = time.strftime('%Y-%m-%d %H:%M:%S')
        _current_session_id = f"{session_start_time}_{uuid.uuid4().hex[:8]}"
        debug_print(f"Session ID: {_current_session_id}")
    
    # Reset vote verification tracking for new session
    _first_vote_completed = False
    _last_verification_vote_count = 0
    
    # Start centralized status display
    start_status_display()
    
    # Track if we should delay parallel thread startup
    # Delay parallel threads until after main thread's first vote completes
    # This ensures vote_verification.json is created by the main thread first
    delay_parallel_startup = (start_thread_count > 1)
    
    try:
        # Main voting loop - continues until shutdown_flag is set (Ctrl+C)
        last_gc_time = time.time()  # Track last garbage collection time
        gc_interval = 300  # Run garbage collection every 5 minutes (300 seconds)
        
        while not shutdown_flag:
            # Periodic memory cleanup for long-running sessions
            current_time = time.time()
            if current_time - last_gc_time > gc_interval:
                import gc
                debug_print("[CLEANUP] Running periodic garbage collection...")
                gc.collect()
                last_gc_time = current_time
                debug_print("[CLEANUP] Garbage collection completed")
            
            # Perform vote iteration
            success, results, cutler_ahead = perform_vote_iteration(thread_id="Main")
            
            # If we're delaying parallel thread startup, start them now after first vote completes
            if delay_parallel_startup and _first_vote_completed:
                delay_parallel_startup = False
                num_parallel_threads = start_thread_count - 1  # Number of parallel threads to start
                with _parallel_voting_lock:
                    for i in range(num_parallel_threads):
                        if i < len(_parallel_active):
                            _parallel_active[i] = True
                            # Create thread with proper closure to capture index
                            # Use default parameter to capture the value at loop iteration time
                            _parallel_threads[i] = threading.Thread(
                                target=lambda idx=i: parallel_voting_thread(idx),
                                daemon=True
                            )
                            _parallel_threads[i].start()
            
            # Check lead percentage and adjust backoff if needed
            lead_percentage = None
            is_lead_high = False
            if results and cutler_ahead:
                lead_percentage, is_lead_high = get_cutler_lead_percentage(results, lead_threshold)
                
                # Apply exponential backoff if lead is too high
                with lead_backoff_lock:
                    if is_lead_high:
                        # Increase backoff multiplier exponentially (1.5x each time)
                        lead_backoff_multiplier = min(lead_backoff_multiplier * 1.5, MAX_BACKOFF_DELAY / 60.0)
                        # Update Main thread status with backoff message
                        update_thread_status("Main", 'message', vote_count, 
                                            f"[Main] ⚠ Backoff active (lead: {lead_percentage:.2f}%, multiplier: {lead_backoff_multiplier:.2f}x)")
                    else:
                        # Reset backoff when lead drops below threshold
                        if lead_backoff_multiplier > 1.0:
                            lead_backoff_multiplier = 1.0
                            # Update Main thread status with backoff reset message
                            update_thread_status("Main", 'message', vote_count, 
                                                f"[Main] ✓ Backoff reset (lead: {lead_percentage:.2f}%)")
            
            # Check if we should start/stop parallel voting thread
            with _counter_lock:
                current_behind_count = consecutive_behind_count
            
            # Manage parallel voting threads based on consecutive behind count (dynamic loop-based approach)
            with _parallel_voting_lock:
                # Loop through all available parallel thread slots
                for i in range(len(_parallel_active)):
                    threshold = _parallel_thresholds[i] if i < len(_parallel_thresholds) else 20 + (i * 10)
                    thread_name = f"Parallel-{i + 1}"
                    
                    # Start thread if threshold is met and thread is not already active
                    if current_behind_count >= threshold and not _parallel_active[i]:
                        _parallel_active[i] = True
                        if _parallel_threads[i] is None or not _parallel_threads[i].is_alive():
                            # Count how many threads are currently active
                            active_thread_count = 1 + sum(_parallel_active)  # 1 for main + sum of parallel
                            
                            # Create thread with proper closure to capture index
                            # Use default parameter to capture the value at loop iteration time
                            _parallel_threads[i] = threading.Thread(
                                target=lambda idx=i: parallel_voting_thread(idx),
                                daemon=True
                            )
                            _parallel_threads[i].start()
                    
                    # Stop thread if Cutler is ahead (unless forced)
                    elif cutler_ahead and _parallel_active[i] and not _force_parallel_mode:
                        _parallel_active[i] = False
                    
                    # Stop thread if behind count drops below threshold (unless forced)
                    elif current_behind_count < threshold and _parallel_active[i] and not _force_parallel_mode:
                        _parallel_active[i] = False
            
            # Determine wait time based on Cutler's position and consecutive behind count
            # This implements the four-tier adaptive timing system with exponential backoff for high leads
            if not shutdown_flag:
                with _counter_lock:
                    current_behind_count = consecutive_behind_count
                
                # Get current backoff multiplier
                with lead_backoff_lock:
                    current_backoff = lead_backoff_multiplier
                
                if results and not cutler_ahead:
                    # Cutler is behind - use faster voting intervals based on how long he's been behind
                    if current_behind_count >= 10:
                        # Been behind for 10+ rounds - use super accelerated speed (3-10 seconds)
                        base_wait_time = random.randint(3, 10)
                        wait_time = base_wait_time
                        update_thread_status("Main", 'message', vote_count, 
                                            f"[Main] Waiting {wait_time}s before next vote (SUPER ACCELERATED, {current_behind_count} rounds behind)")
                    elif current_behind_count >= 5:
                        # Been behind for 5-9 rounds - use accelerated speed (7-16 seconds)
                        base_wait_time = random.randint(7, 16)
                        wait_time = base_wait_time
                        update_thread_status("Main", 'message', vote_count, 
                                            f"[Main] Waiting {wait_time}s before next vote (ACCELERATED, {current_behind_count} rounds behind)")
                    else:
                        # Recently behind (1-4 rounds) - use initial accelerated interval (14-37 seconds)
                        base_wait_time = random.randint(14, 37)
                        wait_time = base_wait_time
                        update_thread_status("Main", 'message', vote_count, 
                                            f"[Main] Waiting {wait_time}s before next vote (INITIAL ACCELERATED, {current_behind_count} rounds behind)")
                else:
                    # Cutler is ahead or results unavailable - use standard interval (53-67 seconds)
                    base_wait_time = random.randint(53, 67)
                    
                    # Apply exponential backoff if lead is high
                    if is_lead_high and current_backoff > 1.0:
                        wait_time = min(int(base_wait_time * current_backoff), MAX_BACKOFF_DELAY)
                        update_thread_status("Main", 'message', vote_count, 
                                            f"[Main] Waiting {wait_time}s before next vote (STANDARD with BACKOFF: {current_backoff:.2f}x)")
                    else:
                        wait_time = base_wait_time
                        update_thread_status("Main", 'message', vote_count, 
                                            f"[Main] Waiting {wait_time}s before next vote (STANDARD)")
                
                # Wait in 1-second intervals so we can check shutdown_flag frequently
                # This allows responsive shutdown on Ctrl+C
                waited = 0
                while waited < wait_time and not shutdown_flag:
                    time.sleep(1)
                    waited += 1
    
    except KeyboardInterrupt:
        signal_handler(None, None)
    except Exception as e:
        print(f"\n⚠ Error in main loop: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Stop status display FIRST to prevent interference with final output
        stop_status_display()
        
        # Small delay to ensure display thread has fully stopped
        time.sleep(0.1)
        
        # Stop all parallel voting threads if they're running
        with _parallel_voting_lock:
            for i in range(len(_parallel_active)):
                _parallel_active[i] = False
        
        # Wait for parallel threads to finish (with timeout)
        for i in range(len(_parallel_threads)):
            if _parallel_threads[i] and _parallel_threads[i].is_alive():
                thread_name = f"Parallel-{i + 1}"
                # Use display_error_message for consistency, but it may not display if display is stopped
                # So we'll print directly after display is stopped
                pass  # Silently wait - don't print here to avoid interference
        
        # Wait for all threads with timeout
        for i in range(len(_parallel_threads)):
            if _parallel_threads[i] and _parallel_threads[i].is_alive():
                _parallel_threads[i].join(timeout=5)
        
        # Thread-safe read of all counters for final statistics
        with _counter_lock:
            final_vote_count = vote_count
            final_standard_count = standard_vote_count
            final_initial_accelerated_count = initial_accelerated_vote_count
            final_accelerated_count = accelerated_vote_count
            final_super_accelerated_count = super_accelerated_vote_count
        
        # Now print final summary - display is stopped, so normal printing is safe
        print(f"\n{'='*60}")
        print(f"Voting session ended")
        print(f"{'='*60}")
        print(f"VOTE STATISTICS:")
        print(f"  Total votes submitted: {final_vote_count}")
        print(f"  Standard votes (Cutler ahead): {final_standard_count}")
        print(f"  Initial accelerated votes (1-4 rounds behind): {final_initial_accelerated_count}")
        print(f"  Accelerated votes (5-9 rounds behind): {final_accelerated_count}")
        print(f"  Super accelerated votes (10+ rounds behind): {final_super_accelerated_count}")
        print(f"{'='*60}\n")

if __name__ == "__main__":
    main()

