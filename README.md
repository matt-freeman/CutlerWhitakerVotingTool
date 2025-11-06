# Sports Illustrated Voting Tool

An automated tool to continuously submit votes for **Cutler Whitaker** on the Sports Illustrated High School Athlete of the Week poll. The tool runs in a continuous loop with adaptive timing based on voting results.

## Features

- **Automated voting**: Submits votes automatically using Selenium browser automation
- **Cookie consent handling**: Automatically dismisses cookie consent modals
- **Result extraction**: Extracts and displays the top 5 voting results after each vote
- **Adaptive timing**: Adjusts voting speed based on Cutler's position with four tiers:
  - **Ahead**: Random interval between 53-67 seconds (Standard)
  - **Behind (1-4 rounds)**: Random interval between 14-37 seconds (Initial Accelerated)
  - **Behind (5-9 rounds)**: Random interval between 7-16 seconds (Accelerated)
  - **Behind (10+ rounds)**: Random interval between 3-10 seconds (Super Accelerated)
- **Parallel processing**: When Cutler is behind, additional voting threads start automatically:
  - **20+ rounds**: Second thread starts (2x speed)
  - **30+ rounds**: Third thread starts (3x speed)
  - **40+ rounds**: Fourth thread starts (4x speed)
  - **50+ rounds**: Fifth thread starts (5x speed)
  - **60+ rounds**: Sixth thread starts (6x speed)
  - **70+ rounds**: Seventh thread starts (7x speed)
  - **80+ rounds**: Eighth thread starts (8x speed)
  - Additional threads continue at 90+, 100+, etc. (scalable design)
  - Default maximum: 8 total threads (1 main + 7 parallel), configurable via `--max-threads`
  - All parallel threads use Super Accelerated timing (3-10 seconds)
  - Threads automatically stop when Cutler gets ahead (unless `--force-parallel` is used)
  - **Scalable design**: Supports any number of threads without code changes
- **Force parallel mode**: Keep parallel threads active regardless of Cutler's position
- **Centralized status display**: Shows all active voting threads simultaneously with processing indicators
- **Exponential backoff**: Prevents pushing Cutler's lead too high with configurable threshold
- **JSON logging**: Logs all vote activity to `voting_activity.json` with summary statistics
- **Thread-safe operations**: All counters and file operations are thread-safe
- **Debug mode**: Optional verbose logging for troubleshooting
- **Graceful shutdown**: Handles Ctrl+C cleanly with statistics summary
- **Processing indicator**: Visual feedback showing the script is working

## Setup

1. **Install Python dependencies**:
```bash
pip install -r requirements.txt
```

2. **Install ChromeDriver** (required for Selenium):
   - **macOS**: `brew install chromedriver`
   - **Linux**: 
     - Download from https://chromedriver.chromium.org/
     - Install to `/usr/local/bin/chromedriver` or another location in PATH
     - Make executable: `chmod +x /usr/local/bin/chromedriver`
     - **For systems with old GLIBC versions** (e.g., Raspberry Pi with older OS):
       - Download ChromeDriver manually and place it in a known location
       - Set the `CHROMEDRIVER_PATH` environment variable:
         ```bash
         export CHROMEDRIVER_PATH=/path/to/chromedriver
         ```
   - **Windows**: 
     - Download `chromedriver.exe` from https://chromedriver.chromium.org/
     - Extract to a folder (e.g., `C:\chromedriver`)
     - Add that folder to your system PATH, OR
     - Set the `CHROMEDRIVER_PATH` environment variable:
       ```cmd
       set CHROMEDRIVER_PATH=C:\path\to\chromedriver.exe
       python vote.py
       ```
     - The script will also check common Windows locations automatically

## Usage

### Basic Usage

Run the voting script in continuous mode:
```bash
python3 vote.py
```

The script will:
1. Start a continuous voting loop
2. Submit a vote for Cutler Whitaker
3. Extract and display the top 5 voting results
4. Adjust wait time based on Cutler's position
5. Repeat until you press Ctrl+C

### Debug Mode

Enable verbose logging for troubleshooting:
```bash
python3 vote.py -debug
```

This will show detailed information about:
- Page loading and cookie consent handling
- Element detection and button finding strategies
- Click operations and result detection
- Frame switching and error messages

## How It Works

### Voting Process

1. **Page Load**: Opens the voting page in a headless Chrome browser
2. **Cookie Consent**: Automatically dismisses cookie consent modals
3. **Element Detection**: Finds the radio button for Cutler Whitaker
4. **Vote Submission**: Selects the radio button and clicks the "Vote" button
5. **Result Extraction**: Captures and parses the results page
6. **Adaptive Timing**: Adjusts wait time based on Cutler's position

### Adaptive Timing System

The script uses a four-tier timing system that progressively increases voting frequency the longer Cutler stays behind:

- **Standard Mode** (Cutler in 1st place):
  - Random interval: 53-67 seconds
  - Message: "Cutler Whitaker is in FIRST PLACE! Using standard interval."
  - Tracked as: Standard votes

- **Initial Accelerated Mode** (Cutler behind, 1-4 rounds):
  - Random interval: 14-37 seconds
  - Message: "Cutler Whitaker is not in first place (X/5 rounds behind). Using initial accelerated voting."
  - Tracked as: Initial accelerated votes

- **Accelerated Mode** (Cutler behind, 5-9 rounds):
  - Random interval: 7-16 seconds
  - Message: "Cutler Whitaker has been behind for X consecutive rounds. Using accelerated voting."
  - Tracked as: Accelerated votes

- **Super Accelerated Mode** (Cutler behind, 10+ rounds):
  - Random interval: 3-10 seconds
  - Message: "Cutler Whitaker has been behind for X consecutive rounds. Using SUPER ACCELERATED voting!"
  - Tracked as: Super accelerated votes

The counter resets to 0 when Cutler returns to first place. The script tracks and displays vote statistics when exited, showing how many votes were cast in each category.

### Lead Backoff System

To prevent pushing Cutler's lead too high, the script includes an exponential backoff system:

- **Trigger**: When Cutler's lead over the second-place competitor exceeds a configurable threshold (default: 15%)
- **Behavior**: Exponential backoff gradually increases voting delay
  - Backoff multiplier starts at 1.0x (normal timing)
  - Increases by 1.5x each vote when lead is above threshold
  - Maximum delay capped at 5 minutes (300 seconds)
  - Backoff resets to 1.0x when lead drops below threshold
- **Configurable**: Use `--lead-threshold N` to set custom threshold (e.g., `--lead-threshold 20` for 20%)

Example: If standard interval is 60 seconds and backoff multiplier reaches 2.0x, the delay becomes 120 seconds. If it reaches 5.0x, the delay becomes 300 seconds (5 minutes max).

### Parallel Processing

When Cutler has been behind for extended periods, the script automatically starts additional voting threads to accelerate voting. The system uses a **scalable design** that supports any number of threads without code changes.

**Thread Thresholds** (automatic activation):
- **Parallel-1**: Starts at 20+ rounds behind (2x speed)
- **Parallel-2**: Starts at 30+ rounds behind (3x speed)
- **Parallel-3**: Starts at 40+ rounds behind (4x speed)
- **Parallel-4**: Starts at 50+ rounds behind (5x speed)
- **Parallel-5**: Starts at 60+ rounds behind (6x speed)
- **Parallel-6**: Starts at 70+ rounds behind (7x speed)
- **Parallel-7**: Starts at 80+ rounds behind (8x speed)
- Additional threads continue at 90+, 100+, etc. (threshold increments by 10 per thread)

**Default Configuration**:
- Maximum threads: **8 total** (1 main + 7 parallel)
- Configurable via `--max-threads` argument (see [Command Line Options](#command-line-options))

**Behavior**:
- Each parallel thread uses Super Accelerated timing (3-10 seconds between votes)
- All threads use the same voting logic and thread-safe counters
- Threads automatically stop when Cutler returns to first place or drops below their threshold
- Threads share result extraction and timing logic, working together seamlessly

**Scalable Design Benefits**:
- No hardcoded thread limits - supports any number of threads
- Thresholds calculated automatically (20, 30, 40, 50, 60, 70, 80, ...)
- Easy to scale up or down by changing `--max-threads`
- No code changes needed to add more threads

**Force Parallel Mode**: Use the `--force-parallel` flag to keep parallel threads active even when Cutler is ahead. This maintains maximum voting speed regardless of position. See [Command Line Options](#command-line-options) below.

### Output Files

The script generates the following files:

- `vote_result.html`: HTML of the results page after each vote
- `vote_result.png`: Screenshot of the results page (if screenshot capture works)
- `page_source.html`: Page source saved when manual inspection is needed
- `voting_activity.json`: Comprehensive log of all voting activity with:
  - Summary statistics (total votes, votes by type, exponential backoff votes)
  - Individual vote entries with timestamps, thread IDs, success status, and results
  - Optional top 5 results for each vote (enabled with `--save-top-results`)
  - Historical totals preservation (supports manual editing of historical data)

## Output Example

```
============================================================
VOTE ATTEMPT #1 - 2025-11-03 14:28:33
============================================================
Processing Vote... |
✓ Vote #1 submitted successfully!

============================================================
TOP 5 VOTING RESULTS:
============================================================
1. Dylan Papushak                             24.23%
2. Cutler Whitaker                            23.58%
3. Owen Eastgate                              19.45%
4. Chance Fischer                              11.13%
5. Niko Kokosioulis                            8.34%
============================================================

⚠ Cutler Whitaker is not in first place (1/5 rounds behind). Using initial accelerated voting.

Cutler Whitaker is behind (1/5 rounds). Waiting 28 seconds before next vote (INITIAL ACCELERATED)...
Press Ctrl+C to stop
```

## Exit Statistics

When you stop the script (Ctrl+C), it displays a summary of voting statistics:

```
============================================================
Voting session ended
============================================================
VOTE STATISTICS:
  Total votes submitted: 15
  Standard votes (Cutler ahead): 8
  Initial accelerated votes (1-4 rounds behind): 3
  Accelerated votes (5-9 rounds behind): 2
  Super accelerated votes (10+ rounds behind): 2
============================================================
```

## JSON Logging

The script automatically logs all voting activity to `voting_activity.json`. This file contains:

- **Summary Section**: Aggregated statistics including:
  - Total votes submitted (successful votes only)
  - Standard votes count
  - Initial accelerated votes count
  - Accelerated votes count
  - Super accelerated votes count
  - Exponential backoff votes count

- **Individual Vote Entries**: Each vote includes:
  - Vote number (sequential per session)
  - Session ID (unique identifier for this run)
  - Thread ID (Main, Parallel-1, Parallel-2, etc.)
  - Timestamp
  - Success status
  - Cutler's position and percentage
  - Consecutive behind count
  - Vote type
  - Lead percentage (if Cutler is ahead)
  - Exponential backoff flag
  - Top 5 results (optional, if `--save-top-results` is enabled)

**Historical Totals Preservation**: The JSON file supports manually editing the summary section to include historical totals from previous runs. The script will preserve these totals and increment them correctly as new votes are added. This allows you to maintain cumulative statistics across multiple sessions.

**File Size Management**: By default, `top_5_results` are not saved to keep file size manageable. Use `--save-top-results` only when you need detailed historical data.

## Command Line Options

- `-debug` or `--debug`: Enable debug output (verbose logging)
  - Shows detailed information about page loading, element detection, cookie handling, and voting operations
  - Useful for troubleshooting when votes aren't being submitted correctly

- `--start-threads N`: Start with N threads already active (default: 1)
  - `1`: Main thread only (normal start)
  - `2`: Main + 1 parallel thread (starts as if Cutler is 20+ rounds behind)
  - `3`: Main + 2 parallel threads (starts as if Cutler is 30+ rounds behind)
  - `4`: Main + 3 parallel threads (starts as if Cutler is 40+ rounds behind)
  - `5`: Main + 4 parallel threads (starts as if Cutler is 50+ rounds behind)
  - `6`: Main + 5 parallel threads (starts as if Cutler is 60+ rounds behind)
  - `7`: Main + 6 parallel threads (starts as if Cutler is 70+ rounds behind)
  - `8`: Main + 7 parallel threads (starts as if Cutler is 80+ rounds behind)
  - Can be any number up to `--max-threads` value
  - Useful if you know Cutler is already behind and want to skip waiting for thresholds
  - Automatically initializes the `consecutive_behind_count` to match the thread count

- `--max-threads N`: Maximum number of total threads (main + parallel) (default: 8)
  - Sets the maximum number of parallel threads that can be started
  - Default: 8 (1 main + 7 parallel)
  - Can be set to any number (e.g., 10, 15, 20, etc.)
  - Must be >= `--start-threads` value
  - Example: `--max-threads 10` allows up to 10 total threads (1 main + 9 parallel)
  - The scalable design supports any number of threads without code changes

- `--lead-threshold N`: Percentage lead threshold to trigger exponential backoff (default: 15.0)
  - When Cutler's lead exceeds this percentage, the script uses exponential backoff
  - Backoff increases delay gradually up to 5 minutes maximum
  - Backoff resets to normal timing when lead drops below threshold
  - Useful to prevent pushing Cutler's lead too high
  - Example: `--lead-threshold 20` sets the threshold to 20%

- `--save-top-results`: Save top 5 results for each vote in JSON file (default: False)
  - When enabled, each vote entry includes the top 5 voting results
  - Increases JSON file size, so use only when you need detailed historical data
  - Default behavior (False) keeps file size smaller on long runs
  - Example: `python3 vote.py --save-top-results`

- `--force-parallel`: Force parallel threads to stay active even when Cutler is ahead
  - When enabled, parallel threads continue running regardless of Cutler's position
  - Threads will not stop automatically when Cutler gets ahead or behind count drops
  - Useful for maximum voting speed regardless of position
  - Threads will still stop when you press Ctrl+C
  - Example: `python3 vote.py --start-threads 5 --force-parallel`

### Example Usage

**Basic usage:**
```bash
python3 vote.py
```

**Start with 8 threads immediately (default maximum, skip waiting for thresholds):**
```bash
python3 vote.py --start-threads 8
```

**Support up to 10 threads and start with 5:**
```bash
python3 vote.py --max-threads 10 --start-threads 5
```

**Start with 3 threads, force them to stay active, and enable debug mode:**
```bash
python3 vote.py --start-threads 3 --force-parallel -debug
```

**Maximum speed mode (8 threads, force parallel, no backoff):**
```bash
python3 vote.py --start-threads 8 --force-parallel --lead-threshold 100
```

**Start with 2 threads and 20% lead threshold:**
```bash
python3 vote.py --start-threads 2 --lead-threshold 20
```

**Save top 5 results in JSON and enable debug mode:**
```bash
python3 vote.py --save-top-results -debug
```

**Maximum speed mode (5 threads, force parallel, no backoff):**
```bash
python3 vote.py --start-threads 5 --force-parallel --lead-threshold 100
```

**Combine multiple options:**
```bash
python3 vote.py --start-threads 2 --lead-threshold 18 --save-top-results -debug
```

## Stopping the Script

Press **Ctrl+C** to stop the script gracefully. The script will:
- Finish the current vote attempt
- Display a summary of total votes submitted
- Exit cleanly

## Troubleshooting

### Script can't find the vote button

- The page structure may have changed
- Check `page_source.html` for manual inspection
- Try running with `-debug` flag to see detailed element detection

### ChromeDriver not found or GLIBC compatibility issues

- **Standard installation**:
  - Ensure ChromeDriver is installed and in your PATH
  - On macOS: `brew install chromedriver`
  - Verify with: `chromedriver --version`

- **For systems with old GLIBC versions** (e.g., Raspberry Pi, older Linux distributions):
  - The script will automatically check for ChromeDriver in common locations
  - If you get a GLIBC error, manually install ChromeDriver:
    1. Download ChromeDriver from https://chromedriver.chromium.org/
    2. Place it in a location like `/usr/local/bin/chromedriver`
    3. Make it executable: `chmod +x /usr/local/bin/chromedriver`
    4. Or set the `CHROMEDRIVER_PATH` environment variable:
       ```bash
       export CHROMEDRIVER_PATH=/path/to/chromedriver
       python3 vote.py
       ```
  - The script checks these locations automatically:
    - `/usr/local/bin/chromedriver`
    - `/usr/bin/chromedriver`
    - `/opt/chromedriver/chromedriver`
    - `~/chromedriver`
    - `./chromedriver` (in the script directory)

### Results not displaying correctly

- The HTML structure of the results page may have changed
- Check `vote_result.html` to see the actual page structure

### Votes being filtered or rate limited

The script includes several anti-detection measures:
- **Random User-Agent rotation**: Each request appears to come from a different browser
- **Randomized viewport sizes**: Varies screen resolution to avoid fingerprinting
- **Browser fingerprint masking**: Hides automation indicators
- **Natural timing patterns**: Random delays between votes

**Important Note about IP Addresses:**
- HTTP headers (like `X-Forwarded-For`) **cannot** change your actual source IP address
- The server always sees the real IP address of your connection
- To actually change your IP address, you need:
  - **VPN service**: Changes your entire network connection IP
  - **Proxy server**: Routes traffic through a different IP (use `--proxy` flag)
  - **Rotating proxy service**: Automatically switches IPs (requires paid service)

**Using a Proxy:**
```bash
# Set proxy via environment variable
export PROXY_URL=http://proxy.example.com:8080
python3 vote.py

# Or use command-line argument
python3 vote.py --proxy http://proxy.example.com:8080

# For SOCKS5 proxy
python3 vote.py --proxy socks5://proxy.example.com:1080
```

**Recommended Solutions for IP Rotation:**
1. **VPN Service**: Use a VPN that allows server switching (NordVPN, ExpressVPN, etc.)
2. **Rotating Proxy Service**: Services like Bright Data, Smartproxy, or Oxylabs
3. **Residential Proxy**: More expensive but appears as real residential IPs
4. **Slower Voting**: Increase delays between votes (modify timing in code or use `--lead-threshold` to slow down)

**Current Anti-Detection Features:**
- ✅ Random User-Agent strings (10+ different browsers/devices)
- ✅ Randomized viewport sizes
- ✅ Browser fingerprint masking
- ✅ Natural timing patterns with random delays
- ✅ Headless mode with automation hiding
- ⚠️ IP address cannot be changed via headers (requires VPN/proxy)
- The extraction function may need to be updated

### Cookie consent blocking clicks

- The script should automatically handle this
- If issues persist, check debug output for cookie consent messages
- You may need to manually accept cookies once in a browser to set preferences

## Requirements

- Python 3.6+
- Chrome browser
- ChromeDriver
- Dependencies listed in `requirements.txt`:
  - `requests`
  - `beautifulsoup4`
  - `selenium`

## Notes

- The script runs in a continuous loop until stopped
- Voting intervals are randomized to avoid predictable patterns
- The script automatically handles cookie consent and page overlays
- Results are extracted and displayed after each successful vote
- The script saves HTML and screenshots for verification
- All counters and file operations are thread-safe for concurrent voting
- Centralized status display shows all active threads simultaneously
- JSON logging preserves historical totals when manually edited
- Parallel threads automatically stop when Cutler gets ahead (unless `--force-parallel` is used)
- Exponential backoff prevents pushing Cutler's lead too high

## License

This tool is for educational purposes only. Use responsibly and in accordance with the website's terms of service.
