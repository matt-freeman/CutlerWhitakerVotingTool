# Installing an Older ChromeDriver Version

If you're experiencing slowness with the latest ChromeDriver (142.x), you can try an older version.

## Quick Method: Download Specific Version

1. **Check your Chrome version:**
   ```bash
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version
   ```
   Note the major version number (e.g., 142)

2. **Download an older ChromeDriver:**
   - Go to: https://googlechromelabs.github.io/chrome-for-testing/
   - Or use direct download for version 141:
     ```bash
     # For macOS ARM64 (Apple Silicon)
     curl -O https://storage.googleapis.com/chrome-for-testing-public/141.0.7052.58/mac-arm64/chromedriver-mac-arm64.zip
     
     # For macOS Intel
     curl -O https://storage.googleapis.com/chrome-for-testing-public/141.0.7052.58/mac-x64/chromedriver-mac-x64.zip
     ```

3. **Extract and install:**
   ```bash
   # For ARM64
   unzip chromedriver-mac-arm64.zip
   chmod +x chromedriver-mac-arm64/chromedriver
   sudo mv chromedriver-mac-arm64/chromedriver /usr/local/bin/chromedriver-old
   # Or use a different location:
   mkdir -p ~/chromedriver-old
   mv chromedriver-mac-arm64/chromedriver ~/chromedriver-old/chromedriver
   chmod +x ~/chromedriver-old/chromedriver
   ```

4. **Use the older version with vote.py:**
   ```bash
   export CHROMEDRIVER_PATH=~/chromedriver-old/chromedriver
   python3 vote.py
   ```

## Method 2: Uninstall Homebrew Version and Install Manually

1. **Uninstall Homebrew ChromeDriver:**
   ```bash
   brew uninstall chromedriver
   ```

2. **Download and install specific version manually** (see Method 1 above)

3. **Add to PATH or use CHROMEDRIVER_PATH:**
   ```bash
   # Add to PATH (add to ~/.zshrc or ~/.bash_profile)
   export PATH="$HOME/chromedriver-old:$PATH"
   
   # Or use environment variable (recommended)
   export CHROMEDRIVER_PATH=~/chromedriver-old/chromedriver
   ```

## Method 3: Use Homebrew to Install Specific Version

Unfortunately, Homebrew doesn't make it easy to install older versions. You'd need to:
1. Find the old formula version
2. Install from that specific commit

This is more complex, so Method 1 or 2 is recommended.

## Testing Different Versions

You can keep multiple versions and switch between them:

```bash
# Create a directory for old versions
mkdir -p ~/chromedriver-versions

# Download version 141
curl -O https://storage.googleapis.com/chrome-for-testing-public/141.0.7052.58/mac-arm64/chromedriver-mac-arm64.zip
unzip chromedriver-mac-arm64.zip
mv chromedriver-mac-arm64/chromedriver ~/chromedriver-versions/chromedriver-141
chmod +x ~/chromedriver-versions/chromedriver-141

# Download version 140
curl -O https://storage.googleapis.com/chrome-for-testing-public/140.0.6961.0/mac-arm64/chromedriver-mac-arm64.zip
unzip chromedriver-mac-arm64.zip
mv chromedriver-mac-arm64/chromedriver ~/chromedriver-versions/chromedriver-140
chmod +x ~/chromedriver-versions/chromedriver-140

# Test version 141
export CHROMEDRIVER_PATH=~/chromedriver-versions/chromedriver-141
python3 vote.py

# Test version 140
export CHROMEDRIVER_PATH=~/chromedriver-versions/chromedriver-140
python3 vote.py
```

## Recommended Versions to Try

- **Version 141** (most recent stable before 142)
- **Version 140** 
- **Version 139**

These should still work with Chrome 142, as ChromeDriver is usually backward compatible within a few versions.

## Note

The script will automatically use the ChromeDriver specified in `CHROMEDRIVER_PATH` environment variable, so you don't need to modify the code.

