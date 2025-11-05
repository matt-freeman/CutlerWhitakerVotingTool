# Quick Start Guide - Mac

This guide will get you up and running in just a few minutes.

## Files You Need

When sharing this script, include these files:
- `vote.py` - The main voting script
- `requirements.txt` - Python dependencies list
- `QUICK_START.md` - This guide (optional but helpful)

That's it! The script will create other files (like `voting_activity.json`) automatically when it runs.

## Step-by-Step Setup (Mac)

### Step 1: Check Python Installation

Open Terminal and check if Python 3 is installed:

```bash
python3 --version
```

You should see something like `Python 3.9.0` or higher. If you get an error, install Python 3 from [python.org](https://www.python.org/downloads/) or use Homebrew:

```bash
brew install python3
```

### Step 2: Install ChromeDriver

ChromeDriver is required for the script to work. Install it using Homebrew:

```bash
brew install chromedriver
```

**Important on macOS:** After installing, macOS Gatekeeper will need to verify ChromeDriver. Follow these steps:

1. **Verify ChromeDriver and trigger the security check:**
   ```bash
   chromedriver --version
   ```
   
   **What to expect:**
   - First time: macOS may show a security dialog saying ChromeDriver can't be opened
   - You'll see options like "Move to Trash", "Cancel", and possibly "Open"
   - **Click "Open"** (you may need to enter your password)
   - This completes the Gatekeeper verification

2. **If you see a security dialog when running `chromedriver --version`:**
   - **Option 1 (Recommended):** Click "Open" in the dialog
     - Enter your password if prompted
     - This permanently allows ChromeDriver to run
   - **Option 2:** Go to System Settings → Privacy & Security
     - Scroll down to find the message about ChromeDriver being blocked
     - Click "Allow Anyway"
     - Then run `chromedriver --version` again to complete verification

3. **Verify it's working:**
   ```bash
   chromedriver --version
   ```
   
   You should see a version number without any dialogs (e.g., "ChromeDriver 120.0.6099.109")
   
   **If you still see a dialog:**
   - Click "Open" and enter your password
   - This is macOS Gatekeeper's final verification step
   - After this, ChromeDriver will work without prompts

**Why this happens:**
- macOS Gatekeeper checks if software is signed/notarized by the developer
- ChromeDriver from Homebrew may not be fully signed, so macOS requires explicit approval
- Running `chromedriver --version` actually executes it, which triggers the verification
- Once you approve it, macOS remembers and won't prompt again

**Note:** If you don't have Homebrew installed, install it first:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### Step 3: Install Python Dependencies

Navigate to the folder where you saved the files, then install the required libraries:

```bash
cd /path/to/folder/with/vote.py
pip3 install -r requirements.txt
```

If you get a permission error, use:
```bash
pip3 install --user -r requirements.txt
```

### Step 4: Run the Script

You're ready to go! Run the script:

```bash
python3 vote.py
```

The script will start voting automatically. Press `Ctrl+C` to stop it gracefully.

## Common Options

### Start with multiple threads (faster voting)
```bash
python3 vote.py --start-threads 3
```

### Enable debug mode (see detailed output)
```bash
python3 vote.py -debug
```

### Force parallel mode (keep all threads active)
```bash
python3 vote.py --start-threads 8 --force-parallel
```

## Troubleshooting

### "Command not found: python3"
- Install Python 3 from [python.org](https://www.python.org/downloads/)
- Or use Homebrew: `brew install python3`

### "Command not found: brew"
- Install Homebrew first (see Step 2 above)

### "ChromeDriver not found" or script hangs
- Make sure you installed ChromeDriver: `brew install chromedriver`
- **Verify ChromeDriver works and complete macOS verification:**
  ```bash
  chromedriver --version
  ```
  - If you see a macOS security dialog, click "Open" and enter your password
  - This is required for macOS Gatekeeper to verify ChromeDriver
  - After approving, you should see a version number (e.g., "ChromeDriver 120.0.6099.109")
  - If you still see dialogs, keep clicking "Open" until it works

- **If macOS keeps showing security dialogs:**
  - Go to System Settings → Privacy & Security
  - Look for any messages about ChromeDriver being blocked
  - Click "Allow Anyway" if you see it
  - Then run `chromedriver --version` again to complete verification

- **If the script hangs at "Processing Vote...":**
  - Try running with `--no-headless` to see what's happening:
    ```bash
    python3 vote.py --no-headless
    ```
  - This will show the Chrome browser window so you can see if there are any errors
  - Check if Chrome is actually installed and up to date:
    ```bash
    /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version
    ```
  - Make sure ChromeDriver version matches your Chrome version

- **If ChromeDriver still won't run:**
  - Try removing the quarantine attribute:
    ```bash
    # Apple Silicon Mac
    xattr -d com.apple.quarantine /opt/homebrew/bin/chromedriver
    
    # Intel Mac
    xattr -d com.apple.quarantine /usr/local/bin/chromedriver
    ```
  - Then run `chromedriver --version` again to trigger verification

- If still having issues, you can manually specify the path:
  ```bash
  export CHROMEDRIVER_PATH=/opt/homebrew/bin/chromedriver
  python3 vote.py
  ```

### "Module not found" errors
- Make sure you ran `pip3 install -r requirements.txt`
- Try using `pip3 install --user -r requirements.txt` if you get permission errors

### "Permission denied" when installing
- Use the `--user` flag: `pip3 install --user -r requirements.txt`
- Or use `sudo` (not recommended): `sudo pip3 install -r requirements.txt`

## What the Script Does

- Automatically votes for Cutler Whitaker every 53-67 seconds (when he's ahead)
- Speeds up voting (3-10 seconds between votes) when he's behind
- Automatically starts additional threads when needed (up to 8 total threads)
- Shows the top 5 voting results after each vote
- Logs all activity to `voting_activity.json`
- Displays statistics when you stop the script

## Need More Help?

See `README.md` for detailed documentation on all features and options.

