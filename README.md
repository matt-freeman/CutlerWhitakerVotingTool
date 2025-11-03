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
- **Parallel processing**: When Cutler is behind 20+ consecutive rounds, additional voting threads start automatically:
  - **20+ rounds**: Second thread starts (2x speed)
  - **30+ rounds**: Third thread starts (3x speed)
- **Debug mode**: Optional verbose logging for troubleshooting
- **Graceful shutdown**: Handles Ctrl+C cleanly
- **Processing indicator**: Visual feedback showing the script is working

## Setup

1. **Install Python dependencies**:
```bash
pip install -r requirements.txt
```

2. **Install ChromeDriver** (required for Selenium):
   - **macOS**: `brew install chromedriver`
   - **Linux**: Download from https://chromedriver.chromium.org/
   - **Windows**: Download from https://chromedriver.chromium.org/ and add to PATH

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

### Parallel Processing

When Cutler has been behind for extended periods, the script automatically starts additional voting threads to accelerate voting:

- **First Parallel Thread** (starts at 20+ rounds behind):
  - Trigger: 20 consecutive rounds behind
  - Behavior: Second thread starts voting using Super Accelerated timing (3-10 seconds)
  - Result: Approximately **2x voting speed** (main + 1 parallel thread)
  - Auto-stop: Stops automatically when Cutler returns to first place or drops below 20 rounds behind

- **Second Parallel Thread** (starts at 30+ rounds behind):
  - Trigger: 30 consecutive rounds behind
  - Behavior: Third thread starts voting using Super Accelerated timing (3-10 seconds)
  - Result: Approximately **3x voting speed** (main + 2 parallel threads)
  - Auto-stop: Stops automatically when Cutler returns to first place or drops below 30 rounds behind

All parallel threads use the same voting logic and thread-safe counters as the main thread, ensuring accurate vote tracking and statistics. All threads share the same result extraction and timing logic, working together seamlessly to catch up quickly when Cutler falls behind.

### Output Files

The script generates the following files:

- `vote_result.html`: HTML of the results page after each vote
- `vote_result.png`: Screenshot of the results page (if screenshot capture works)
- `page_source.html`: Page source saved when manual inspection is needed

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

## Command Line Options

- `-debug` or `--debug`: Enable debug output (verbose logging)
- `--start-threads N`: Start with N threads already active (1, 2, or 3)
  - `1`: Main thread only (default, normal start)
  - `2`: Main + 1 parallel thread (starts as if Cutler is 20+ rounds behind)
  - `3`: Main + 2 parallel threads (starts as if Cutler is 30+ rounds behind)
  - Useful if you know Cutler is already behind and want to skip waiting for thresholds

### Example Usage

Start with 3 threads immediately (skip waiting for thresholds):
```bash
python3 vote.py --start-threads 3
```

Start with 2 threads and debug mode:
```bash
python3 vote.py --start-threads 2 -debug
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

### ChromeDriver not found

- Ensure ChromeDriver is installed and in your PATH
- On macOS: `brew install chromedriver`
- Verify with: `chromedriver --version`

### Results not displaying correctly

- The HTML structure of the results page may have changed
- Check `vote_result.html` to see the actual page structure
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

## License

This tool is for educational purposes only. Use responsibly and in accordance with the website's terms of service.
