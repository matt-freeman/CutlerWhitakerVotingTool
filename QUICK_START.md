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

### "ChromeDriver not found"
- Make sure you installed ChromeDriver: `brew install chromedriver`
- Verify it's installed: `chromedriver --version`
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

