# Running Tests and the Voting Script

## Understanding Selenium in This Project

**Important**: Selenium is not a separate testing framework here. It's already built into `vote.py` and used to automate the browser for voting.

- `vote.py` uses Selenium internally to control a Chrome browser
- The test suite (`test_vote.py`) tests the core logic but NOT the Selenium parts
- "Manual testing" means running `vote.py` directly and watching it work

## Step 1: Install Prerequisites

Before running anything, make sure you have:

### 1. Install Python Dependencies
```bash
pip install -r requirements.txt
```

This installs:
- `selenium` - Browser automation library
- `beautifulsoup4` - HTML parsing
- `requests` - HTTP requests
- `pytest` - Test runner (for test_vote.py)

### 2. Install ChromeDriver

**macOS** (you're on macOS):
```bash
brew install chromedriver
```

**Verify ChromeDriver is installed:**
```bash
chromedriver --version
```

You should see something like: `ChromeDriver 120.0.6099.109`

**Alternative for macOS** (if brew doesn't work):
1. Download from: https://chromedriver.chromium.org/downloads
2. Extract the file
3. Move it to `/usr/local/bin/`:
   ```bash
   sudo mv chromedriver /usr/local/bin/
   sudo chmod +x /usr/local/bin/chromedriver
   ```

**Linux:**
```bash
# Download and install ChromeDriver
wget https://chromedriver.storage.googleapis.com/LATEST_RELEASE/chromedriver_linux64.zip
unzip chromedriver_linux64.zip
sudo mv chromedriver /usr/local/bin/
sudo chmod +x /usr/local/bin/chromedriver
```

**Windows:**
1. Download ChromeDriver from: https://chromedriver.chromium.org/downloads
2. Extract the `.exe` file
3. Add it to your system PATH, or place it in the same folder as `vote.py`

### 3. Verify Chrome is Installed

Selenium requires Google Chrome browser to be installed:
- **macOS**: Chrome should already be installed if you use it
- **Linux**: `sudo apt install google-chrome-stable` (or similar)
- **Windows**: Download from https://www.google.com/chrome/

## Step 2: Run the Voting Script (This Uses Selenium)

The voting script **already uses Selenium** - you just run it normally:

### Basic Run
```bash
python3 vote.py
```

This will:
1. Automatically open a headless Chrome browser (using Selenium)
2. Navigate to the voting page
3. Find and click the vote button for Cutler Whitaker
4. Capture the results
5. Repeat in a loop

### With Debug Mode (See Selenium Actions)
```bash
python3 vote.py -debug
```

This shows detailed output of what Selenium is doing:
- Page loading
- Element detection
- Cookie consent handling
- Button clicks
- Frame switching

### With Options
```bash
# Start with 3 threads immediately
python3 vote.py --start-threads 3

# Custom lead threshold
python3 vote.py --lead-threshold 20

# Combine options
python3 vote.py --start-threads 2 --lead-threshold 18 -debug
```

## Step 3: Run the Unit Tests (No Selenium)

The test suite tests the core logic, but **NOT** the Selenium browser automation:

```bash
# Run all tests
python3 -m pytest test_vote.py -v

# Run with coverage report
python3 -m pytest test_vote.py --cov=vote --cov-report=term-missing

# Run specific test class
python3 -m pytest test_vote.py::TestAdaptiveTiming -v
```

## Troubleshooting

### "Selenium not installed"
```bash
pip install selenium
```

### "ChromeDriver not found"
Make sure ChromeDriver is installed and in your PATH:
```bash
# Check if it's installed
chromedriver --version

# If not found, install it (see Step 1 above)
```

### "Chrome browser not found"
Install Google Chrome browser on your system.

### "Element not found" errors
- Try running with `-debug` to see what Selenium is doing
- The website structure may have changed
- Check `page_source.html` (created when script fails) to inspect the page

### Script runs but doesn't vote
- Check `vote_result.html` to see what page was captured
- Run with `-debug` to see detailed element detection
- The website may have anti-bot protection

## What Gets Tested Where

### Unit Tests (`test_vote.py`) - Automated ✅
- Result extraction from HTML
- Adaptive timing calculations
- Lead backoff logic
- Parallel thread management
- Command-line argument parsing
- Thread safety

### Manual Testing (Running `vote.py`) - Manual ✅
- Selenium browser automation
- Cookie consent handling
- Button clicking
- Iframe handling
- Result page capture
- Full voting loop integration

## Quick Start Checklist

1. ✅ Install dependencies: `pip install -r requirements.txt`
2. ✅ Install ChromeDriver: `brew install chromedriver` (macOS)
3. ✅ Verify ChromeDriver: `chromedriver --version`
4. ✅ Run the script: `python3 vote.py -debug`
5. ✅ Watch it vote! (Press Ctrl+C to stop)

## Understanding Headless Mode

By default, `vote.py` runs Chrome in **headless mode** (no visible browser window). This is configured in the code:

```python
chrome_options.add_argument('--headless')  # Run in background
```

If you want to **see the browser** for debugging, you can temporarily modify `vote.py`:
- Remove or comment out the `--headless` line
- The browser window will open and you can watch Selenium interact with the page

**Note**: This is useful for debugging but will slow down voting and make your screen cluttered.

## Summary

- **Selenium is already in the script** - just run `python3 vote.py`
- **Unit tests** test the logic, not Selenium
- **Manual testing** = running the script and watching it work
- Make sure ChromeDriver is installed before running

You don't need to write separate Selenium tests - the script IS the Selenium automation!

