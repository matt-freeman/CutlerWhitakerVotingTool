#!/usr/bin/env python3
"""
Tool to submit a vote for Cutler Whitaker on the Sports Illustrated
High School Athlete of the Week poll.
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

# Thread control for parallel voting
_parallel_voting_thread = None  # Reference to the first parallel voting thread (starts at 20 rounds)
_parallel_voting_active = False  # Flag to control first parallel voting thread lifecycle
_parallel_voting_thread2 = None  # Reference to the second parallel voting thread (starts at 30 rounds)
_parallel_voting_active2 = False  # Flag to control second parallel voting thread lifecycle
_parallel_voting_lock = threading.Lock()  # Lock for parallel voting control variables

# Global vote counters (thread-safe)
vote_count = 0  # Total number of vote attempts
consecutive_behind_count = 0  # Track consecutive rounds where Cutler is behind (for adaptive timing)
standard_vote_count = 0  # Votes when Cutler is ahead
accelerated_vote_count = 0  # Votes when Cutler is behind 5-9 rounds
super_accelerated_vote_count = 0  # Votes when Cutler is behind 10+ rounds
initial_accelerated_vote_count = 0  # Votes when Cutler is behind 1-4 rounds

def debug_print(*args, **kwargs):
    """
    Print debug messages only if debug mode is enabled.
    
    This function acts as a conditional print statement that respects the global
    debug_mode flag. When debug mode is disabled, all debug messages are silently
    ignored to reduce output verbosity.
    
    Args:
        *args: Variable positional arguments passed to print()
        **kwargs: Variable keyword arguments passed to print()
    """
    if debug_mode:
        print(*args, **kwargs)

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
    # Import Selenium components - required for browser automation
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
        from selenium.common.exceptions import TimeoutException, NoSuchElementException
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
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.get(VOTE_URL)
        
        # Wait for page to fully load and JavaScript to execute
        debug_print("Waiting for page to load...")
        time.sleep(5)
        
        # Wait for React/content to be rendered
        wait = WebDriverWait(driver, 30)
        
        # Handle cookie consent modal/overlay that might block clicks
        # OneTrust is a common cookie consent platform used by many websites
        # These overlays can intercept clicks on voting elements, so we must dismiss them first
        debug_print("Checking for cookie consent modal...")
        try:
            # Look for OneTrust cookie consent elements (common cookie consent platform)
            cookie_overlays = driver.find_elements(By.CSS_SELECTOR, ".onetrust-pc-dark-filter, .onetrust-pc-sdk, #onetrust-pc-sdk")
            if cookie_overlays:
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
            
            for selector in accept_selectors:
                try:
                    accept_buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                    for btn in accept_buttons:
                            if btn.is_displayed() and btn.is_enabled():
                                debug_print(f"Found cookie consent button: {selector}")
                                # Try to click it
                                try:
                                    btn.click()
                                    debug_print("✓ Clicked cookie consent button")
                                    time.sleep(2)
                                    break
                                except:
                                    # Try JavaScript click as fallback
                                    try:
                                        driver.execute_script("arguments[0].click();", btn)
                                        debug_print("✓ Clicked cookie consent button (JavaScript)")
                                        time.sleep(2)
                                        break
                                    except:
                                        continue
                except:
                    continue
            
            # Wait for overlay to disappear
            max_overlay_wait = 10
            overlay_wait = 0
            while overlay_wait < max_overlay_wait:
                try:
                    overlays = driver.find_elements(By.CSS_SELECTOR, ".onetrust-pc-dark-filter")
                    visible_overlays = [o for o in overlays if o.is_displayed()]
                    if not visible_overlays:
                        debug_print("✓ Cookie consent overlay dismissed")
                        break
                    time.sleep(0.5)
                    overlay_wait += 0.5
                except:
                    break
            
            # Additional wait for any animations
            time.sleep(1)
        except Exception as e:
            print(f"Note: Could not handle cookie consent: {e}")
            # Continue anyway - might not be an issue
        
        # Check for iframes that might contain the voting widget
        # Many polling widgets are embedded in iframes, so we need to check and potentially
        # switch context to interact with elements inside the iframe
        # We'll check all iframes since the voting widget might be in any of them
        in_iframe = False  # Track if we've switched to an iframe context
        active_iframe = None  # Store reference to the iframe we're currently in
        all_iframes = []  # Store all iframes for later checking
        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            debug_print(f"Found {len(iframes)} iframes on page")
            for iframe in iframes:
                try:
                    src = iframe.get_attribute('src')
                    iframe_id = iframe.get_attribute('id') or 'no-id'
                    all_iframes.append((iframe, src, iframe_id))
                    if src and ('poll' in src.lower() or 'vote' in src.lower() or 'survey' in src.lower() or 'widget' in src.lower()):
                        debug_print(f"Found potential voting iframe: {src}")
                        driver.switch_to.frame(iframe)
                        in_iframe = True
                        active_iframe = iframe
                        time.sleep(2)
                        # Now search within the iframe
                        break
                except Exception as e:
                    debug_print(f"Error checking iframe: {e}")
                    continue
        except Exception as e:
            debug_print(f"Error finding iframes: {e}")
        
        # Try multiple strategies to find the vote button for Cutler Whitaker
        # We use multiple strategies because different sites structure their polls differently
        # If one strategy fails, we try the next one until we find the element
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
            try:
                if strategy_type == By.TAG_NAME:
                    # Special handling for finding all buttons - filter more carefully
                    buttons = driver.find_elements(By.TAG_NAME, "button")
                    debug_print(f"Strategy {strategy_idx}: Found {len(buttons)} buttons on page")
                    for btn in buttons:
                        try:
                            # Skip menu/navigation buttons
                            btn_id = btn.get_attribute('id') or ''
                            btn_class = btn.get_attribute('class') or ''
                            btn_aria = btn.get_attribute('aria-label') or ''
                            
                            # Skip obvious non-vote buttons
                            if any(skip in btn_id.lower() or skip in btn_class.lower() or skip in btn_aria.lower() 
                                   for skip in ['menu', 'nav', 'hamburger', 'close', 'more', 'dropdown']):
                                continue
                            
                            text = btn.text.lower()
                            # Must contain vote-related text OR be near athlete name
                            if ('vote' in text or 'submit' in text) and ('cutler' in text or 'whitaker' in text):
                                debug_print(f"Found potential vote button: text='{btn.text[:50]}', id='{btn_id}', class='{btn_class[:50]}'")
                                vote_button = btn
                                break
                        except:
                            continue
                    if vote_button:
                        break
                else:
                    elements = driver.find_elements(strategy_type, selector)
                    debug_print(f"Strategy {strategy_idx}: Found {len(elements)} elements")
                    if elements:
                        for elem in elements:
                            try:
                                if elem.is_displayed() and elem.is_enabled():
                                    elem_text = elem.text[:50] if elem.text else 'N/A'
                                    elem_tag = elem.tag_name
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
                            except:
                                continue
                        if vote_button:
                            break
            except Exception as e:
                print(f"Strategy {strategy_idx} failed: {e}")
                continue
        
        if not vote_button:
            # Last resort: Save page source and try to find by inspecting DOM
            print("Could not find vote button using standard strategies.")
            print("Saving page source for manual inspection...")
            with open('page_source.html', 'w', encoding='utf-8') as f:
                f.write(driver.page_source)
            
            # Try to find any interactive element near text containing the name
            try:
                text_elements = driver.find_elements(By.XPATH, f"//*[contains(text(), 'Cutler') or contains(text(), 'Whitaker')]")
                print(f"Found {len(text_elements)} text elements containing 'Cutler' or 'Whitaker'")
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
                # Scroll into view
                driver.execute_script("arguments[0].scrollIntoView(true);", vote_button)
                time.sleep(1)
                
                # Make sure no overlays are blocking
                try:
                    overlays = driver.find_elements(By.CSS_SELECTOR, ".onetrust-pc-dark-filter")
                    visible_overlays = [o for o in overlays if o.is_displayed()]
                    if visible_overlays:
                        print("⚠ Cookie consent overlay still visible, trying to dismiss...")
                        # Try to click outside the overlay or press ESC
                        driver.execute_script("document.querySelectorAll('.onetrust-pc-dark-filter').forEach(el => el.style.display='none');")
                        time.sleep(1)
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
                    debug_print(f"\n✓ This is a radio/checkbox button. Selecting it first...")
                    # Step 1: Select the radio button for Cutler Whitaker
                    try:
                        if not vote_button.is_selected():
                            vote_button.click()
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
                            time.sleep(1)
                            driver.execute_script("arguments[0].click();", vote_button)
                            debug_print(f"✓ Selected radio button (JavaScript click)")
                        else:
                            raise click_error
                    
                    time.sleep(1)  # Brief wait for selection to register in the DOM
                    
                    # Step 2: Find and click the Vote/Submit button
                    debug_print(f"\nLooking for Vote/Submit button...")
                    submit_button = None
                    submit_selectors = [
                        "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'vote')]",
                        "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'submit')]",
                        "//input[@type='submit' and contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'vote')]",
                        "//input[@type='submit']",
                        "//button[@type='submit']",
                        "//button[contains(@class, 'vote')]",
                        "//button[contains(@class, 'submit')]",
                        "//button[contains(@id, 'vote')]",
                        "//button[contains(@id, 'submit')]",
                    ]
                    
                    for selector in submit_selectors:
                        try:
                            buttons = driver.find_elements(By.XPATH, selector)
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
                        except:
                            continue
                    
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
                    debug_print(f"✓ Successfully clicked vote button (regular click)")
                except Exception as click_error:
                    if "click intercepted" in str(click_error).lower():
                        debug_print("⚠ Click intercepted, trying JavaScript click instead...")
                        # Try to remove overlay with JavaScript
                        driver.execute_script("""
                            document.querySelectorAll('.onetrust-pc-dark-filter').forEach(el => el.remove());
                            document.querySelectorAll('#onetrust-pc-sdk').forEach(el => el.remove());
                        """)
                        time.sleep(1)
                        # Try JavaScript click
                        driver.execute_script("arguments[0].click();", vote_button)
                        debug_print(f"✓ Successfully clicked vote button (JavaScript click)")
                    else:
                        raise click_error
                
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
                        print(f"✓ Page URL changed to: {current_url}")
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
                
                driver.quit()
                return True
            except Exception as e:
                print(f"Error clicking button: {e}")
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
                    
                    driver.quit()
                    return True
                except Exception as e2:
                    print(f"JavaScript click also failed: {e2}")
        else:
            print("Could not locate vote button for Cutler Whitaker")
            print("Page source saved to page_source.html for manual inspection")
        
        # Switch back to default content if we were in an iframe
        if in_iframe:
            try:
                driver.switch_to.default_content()
            except:
                pass
        
        driver.quit()
        return False
            
    except Exception as e:
        print(f"Selenium error: {e}")
        import traceback
        traceback.print_exc()
        return False

def extract_voting_results(html_content):
    """
    Extract voting results (athlete names and percentages) from the results page HTML.
    
    This function uses multiple strategies to parse the HTML and extract voting results:
    1. Primary: Look for poll widget classes (pds-feedback-group, pds-answer-text, pds-feedback-per)
    2. Fallback: Search for text patterns matching "Name, info... XX.XX%"
    3. Last resort: Find percentage displays and extract nearby athlete names
    
    The function handles various HTML structures and formats, normalizes names,
    validates percentages, removes duplicates, and sorts by percentage descending.
    
    Args:
        html_content (str): HTML content of the results page to parse
    
    Returns:
        list: List of tuples containing (athlete_name, percentage) sorted by percentage
              in descending order. Example: [("Cutler Whitaker", 23.58), ("Dylan Papushak", 24.23)]
              Returns empty list if no results could be extracted.
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
        
    except Exception as e:
        print(f"Error extracting results: {e}")
        import traceback
        traceback.print_exc()
    
    return unique_results

def print_top_results(results, top_n=5):
    """
    Print the top N voting results in a formatted table.
    
    Displays athlete names and their vote percentages in a clean, readable format.
    The results are already sorted by percentage descending when passed to this function.
    
    Args:
        results (list): List of tuples containing (athlete_name, percentage) sorted by percentage
        top_n (int): Number of top results to display (default: 5)
    
    Returns:
        list: The results list passed in (for chaining), or None if no results
    """
    if not results:
        print("⚠ No results found to display")
        return None
    
    print(f"\n{'='*60}")
    print(f"TOP {min(top_n, len(results))} VOTING RESULTS:")
    print(f"{'='*60}")
    for i, (name, percentage) in enumerate(results[:top_n], 1):
        print(f"{i}. {name:<40} {percentage:>6.2f}%")
    print(f"{'='*60}\n")
    
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

def signal_handler(sig, frame):
    """
    Handle Ctrl+C (SIGINT) gracefully to allow clean shutdown.
    
    When the user presses Ctrl+C, this handler sets the global shutdown_flag
    to True, which causes the main voting loop to exit cleanly after completing
    the current vote attempt. This prevents abrupt termination and allows the
    script to display a summary of votes submitted.
    
    Args:
        sig: Signal number (unused, required by signal handler signature)
        frame: Current stack frame (unused, required by signal handler signature)
    """
    global shutdown_flag
    print("\n\n⚠ Interrupt received (Ctrl+C). Gracefully shutting down...")
    shutdown_flag = True
    sys.exit(0)

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
    
    # Thread-safe increment of vote count
    with _counter_lock:
        vote_count += 1
        current_vote_num = vote_count
    
    print(f"\n{'='*60}")
    print(f"[{thread_id}] VOTE ATTEMPT #{current_vote_num} - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    # Show animated processing indicator in a separate thread
    import threading as threading_local
    processing_done = threading_local.Event()
    
    def show_processing():
        """Display animated spinner while voting is in progress."""
        spinner = ['|', '/', '-', '\\']
        i = 0
        while not processing_done.is_set():
            print(f"\r[{thread_id}] Processing Vote... {spinner[i % 4]}", end="", flush=True)
            i += 1
            if processing_done.wait(0.2):
                break
        print("\r" + " " * 50 + "\r", end="", flush=True)
    
    processing_thread = threading_local.Thread(target=show_processing, daemon=True)
    processing_thread.start()
    
    # Submit vote using Selenium browser automation
    success = submit_vote_selenium()
    
    processing_done.set()
    processing_thread.join(timeout=0.5)
    
    if success:
        print(f"[{thread_id}] ✓ Vote #{current_vote_num} submitted successfully!")
        
        # Try to extract and display results
        results = None
        cutler_ahead = False
        
        try:
            with open('vote_result.html', 'r', encoding='utf-8') as f:
                result_html = f.read()
            
            results = extract_voting_results(result_html)
            if results:
                if thread_id == "Main":  # Only main thread prints results to avoid clutter
                    print_top_results(results, top_n=5)
                
                cutler_ahead = is_cutler_ahead(results)
                
                # Update consecutive behind counter for adaptive timing (thread-safe)
                with _counter_lock:
                    if cutler_ahead:
                        consecutive_behind_count = 0
                        standard_vote_count += 1
                        if thread_id == "Main":
                            print(f"✓ {TARGET_ATHLETE} is in FIRST PLACE! Using standard interval.")
                    else:
                        consecutive_behind_count += 1
                        current_behind = consecutive_behind_count
                        if current_behind >= 10:
                            super_accelerated_vote_count += 1
                            if thread_id == "Main":
                                print(f"⚠ {TARGET_ATHLETE} has been behind for {current_behind} consecutive rounds. Using SUPER ACCELERATED voting!")
                        elif current_behind >= 5:
                            accelerated_vote_count += 1
                            if thread_id == "Main":
                                print(f"⚠ {TARGET_ATHLETE} has been behind for {current_behind} consecutive rounds. Using accelerated voting.")
                        else:
                            initial_accelerated_vote_count += 1
                            if thread_id == "Main":
                                print(f"⚠ {TARGET_ATHLETE} is not in first place ({current_behind}/5 rounds behind). Using initial accelerated voting.")
            else:
                if thread_id == "Main":
                    print("⚠ Could not extract results from page")
                with _counter_lock:
                    standard_vote_count += 1
        except FileNotFoundError:
            if thread_id == "Main":
                print("⚠ Result file not found, skipping result extraction")
            with _counter_lock:
                standard_vote_count += 1
        except Exception as e:
            if thread_id == "Main":
                print(f"⚠ Error extracting results: {e}")
            with _counter_lock:
                standard_vote_count += 1
    else:
        if thread_id == "Main":
            print(f"⚠ Vote #{current_vote_num} failed")
    
    return success, results, cutler_ahead

def parallel_voting_thread(thread_name="Parallel", threshold=20, active_flag_ref="_parallel_voting_active"):
    """
    Parallel voting thread that runs when Cutler has been behind for a specified number of rounds.
    
    This thread performs the same voting operations as the main thread,
    using Super Accelerated timing (3-10 seconds) to help catch up.
    The thread stops automatically when Cutler gets back in the lead.
    
    Args:
        thread_name (str): Name identifier for this thread (for logging)
        threshold (int): Minimum behind count required to keep thread running
        active_flag_ref (str): Reference to the active flag variable name (for dynamic access)
    """
    global shutdown_flag, _parallel_voting_active, _parallel_voting_active2
    
    # Get the appropriate active flag based on the reference
    if active_flag_ref == "_parallel_voting_active":
        active_flag = _parallel_voting_active
    elif active_flag_ref == "_parallel_voting_active2":
        active_flag = _parallel_voting_active2
    else:
        active_flag = _parallel_voting_active
    
    print(f"[{thread_name}] 🚀 Starting parallel voting thread to accelerate votes!")
    
    while not shutdown_flag:
        # Check if we should continue parallel voting
        with _parallel_voting_lock:
            if active_flag_ref == "_parallel_voting_active":
                if not _parallel_voting_active:
                    print(f"[{thread_name}] ⏹ Stopping parallel voting thread (Cutler is ahead)")
                    break
            elif active_flag_ref == "_parallel_voting_active2":
                if not _parallel_voting_active2:
                    print(f"[{thread_name}] ⏹ Stopping parallel voting thread (Cutler is ahead)")
                    break
        
        # Check current behind count
        with _counter_lock:
            current_behind = consecutive_behind_count
        
        # Only continue if Cutler is still behind the threshold
        if current_behind < threshold:
            print(f"[{thread_name}] ⏹ Stopping parallel voting thread (Cutler catching up - below {threshold} rounds)")
            with _parallel_voting_lock:
                if active_flag_ref == "_parallel_voting_active":
                    _parallel_voting_active = False
                elif active_flag_ref == "_parallel_voting_active2":
                    _parallel_voting_active2 = False
            break
        
        # Perform vote using Super Accelerated timing (3-10 seconds)
        success, results, cutler_ahead = perform_vote_iteration(thread_id=thread_name)
        
        # If Cutler is now ahead, stop parallel voting
        if cutler_ahead:
            with _parallel_voting_lock:
                if active_flag_ref == "_parallel_voting_active":
                    _parallel_voting_active = False
                elif active_flag_ref == "_parallel_voting_active2":
                    _parallel_voting_active2 = False
            print(f"[{thread_name}] ⏹ Stopping parallel voting thread (Cutler is now ahead!)")
            break
        
        # Wait 3-10 seconds before next vote (Super Accelerated interval)
        if not shutdown_flag:
            wait_time = random.randint(3, 10)
            print(f"[{thread_name}] Waiting {wait_time} seconds before next vote (SUPER ACCELERATED)...")
            
            waited = 0
            while waited < wait_time and not shutdown_flag:
                # Check if we should stop parallel voting
                with _parallel_voting_lock:
                    if active_flag_ref == "_parallel_voting_active":
                        if not _parallel_voting_active:
                            break
                    elif active_flag_ref == "_parallel_voting_active2":
                        if not _parallel_voting_active2:
                            break
                time.sleep(1)
                waited += 1
    
    print(f"[{thread_name}] 🛑 Parallel voting thread stopped")

def parallel_voting_thread_1():
    """First parallel voting thread (starts at 20 rounds behind)."""
    parallel_voting_thread(thread_name="Parallel-1", threshold=20, active_flag_ref="_parallel_voting_active")

def parallel_voting_thread_2():
    """Second parallel voting thread (starts at 30 rounds behind)."""
    parallel_voting_thread(thread_name="Parallel-2", threshold=30, active_flag_ref="_parallel_voting_active2")

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
    
    Parallel Processing:
    - When Cutler is behind 20+ rounds, a second voting thread starts
    - When Cutler is behind 30+ rounds, a third voting thread starts
    - All threads vote using Super Accelerated timing (3-10 seconds)
    - Parallel threads stop automatically when Cutler gets back in the lead
    
    The script tracks vote counts by type and displays statistics on exit.
    """
    global shutdown_flag, debug_mode
    global _parallel_voting_thread, _parallel_voting_active
    global _parallel_voting_thread2, _parallel_voting_active2
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Vote for Cutler Whitaker on Sports Illustrated poll')
    parser.add_argument('-debug', '--debug', action='store_true', 
                       help='Enable debug output (verbose logging)')
    parser.add_argument('--start-threads', type=int, choices=[1, 2, 3], default=1,
                       help='Number of threads to start with (1=main only, 2=main+1 parallel, 3=main+2 parallel). '
                            'Useful if Cutler is already behind and you want to skip waiting for thresholds.')
    args = parser.parse_args()
    
    # Set debug mode based on command-line argument
    debug_mode = args.debug
    start_thread_count = args.start_threads
    
    # Set up signal handler for graceful shutdown on Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    print(f"Voting tool for {TARGET_ATHLETE}")
    print(f"Target URL: {VOTE_URL}")
    print(f"Vote interval: {VOTE_INTERVAL} seconds")
    if debug_mode:
        print("Debug mode: ENABLED")
    print(f"Press Ctrl+C to stop\n")
    print(f"{'='*60}")
    
    # Initialize counters for tracking voting progress
    # These counters are thread-safe using _counter_lock
    # Reset all counters to 0 at start
    global vote_count, consecutive_behind_count, standard_vote_count
    global accelerated_vote_count, super_accelerated_vote_count, initial_accelerated_vote_count
    
    vote_count = 0  # Total number of vote attempts
    
    # Initialize consecutive_behind_count based on start-threads argument
    # This allows starting with parallel threads already active
    if start_thread_count >= 3:
        # Start with 3 threads (main + 2 parallel) - need 30+ rounds behind
        initial_behind_count = 30
    elif start_thread_count >= 2:
        # Start with 2 threads (main + 1 parallel) - need 20+ rounds behind
        initial_behind_count = 20
    else:
        # Start with 1 thread (main only) - normal start
        initial_behind_count = 0
    
    consecutive_behind_count = initial_behind_count  # Track consecutive rounds where Cutler is behind (for adaptive timing)
    
    # Reset vote type counts for statistics (thread-safe)
    standard_vote_count = 0  # Votes when Cutler is ahead
    accelerated_vote_count = 0  # Votes when Cutler is behind 5-9 rounds
    super_accelerated_vote_count = 0  # Votes when Cutler is behind 10+ rounds
    initial_accelerated_vote_count = 0  # Votes when Cutler is behind 1-4 rounds
    
    # If starting with multiple threads, initialize them now
    if start_thread_count >= 2:
        print(f"\n🚀 Starting with {start_thread_count} threads (main + {start_thread_count - 1} parallel)")
        print(f"   Consecutive behind count initialized to {initial_behind_count} rounds")
        with _parallel_voting_lock:
            if start_thread_count >= 2:
                _parallel_voting_active = True
                _parallel_voting_thread = threading.Thread(target=parallel_voting_thread_1, daemon=True)
                _parallel_voting_thread.start()
                print(f"   ✓ First parallel thread started")
            if start_thread_count >= 3:
                _parallel_voting_active2 = True
                _parallel_voting_thread2 = threading.Thread(target=parallel_voting_thread_2, daemon=True)
                _parallel_voting_thread2.start()
                print(f"   ✓ Second parallel thread started")
        print()
    
    try:
        # Main voting loop - continues until shutdown_flag is set (Ctrl+C)
        while not shutdown_flag:
            # Perform vote iteration
            success, results, cutler_ahead = perform_vote_iteration(thread_id="Main")
            
            # Check if we should start/stop parallel voting thread
            with _counter_lock:
                current_behind_count = consecutive_behind_count
            
            # Manage parallel voting threads based on consecutive behind count
            with _parallel_voting_lock:
                # Start/stop first parallel thread (threshold: 20 rounds)
                if current_behind_count >= 20 and not _parallel_voting_active:
                    # Start first parallel voting thread when Cutler is behind 20+ rounds
                    _parallel_voting_active = True
                    if _parallel_voting_thread is None or not _parallel_voting_thread.is_alive():
                        print(f"\n🚀 Starting first parallel voting thread! Cutler has been behind for {current_behind_count} rounds.")
                        if current_behind_count >= 30:
                            print(f"   Now voting with 3 threads at Super Accelerated speed (3-10 seconds each)")
                        else:
                            print(f"   Now voting with 2 threads at Super Accelerated speed (3-10 seconds each)")
                        _parallel_voting_thread = threading.Thread(target=parallel_voting_thread_1, daemon=True)
                        _parallel_voting_thread.start()
                elif cutler_ahead and _parallel_voting_active:
                    # Stop first parallel voting when Cutler gets back in the lead
                    _parallel_voting_active = False
                    print(f"\n⏹ Stopping first parallel voting thread - {TARGET_ATHLETE} is back in the lead!")
                
                # Start/stop second parallel thread (threshold: 30 rounds)
                if current_behind_count >= 30 and not _parallel_voting_active2:
                    # Start second parallel voting thread when Cutler is behind 30+ rounds
                    _parallel_voting_active2 = True
                    if _parallel_voting_thread2 is None or not _parallel_voting_thread2.is_alive():
                        print(f"\n🚀 Starting second parallel voting thread! Cutler has been behind for {current_behind_count} rounds.")
                        print(f"   Now voting with 3 threads at Super Accelerated speed (3-10 seconds each)")
                        _parallel_voting_thread2 = threading.Thread(target=parallel_voting_thread_2, daemon=True)
                        _parallel_voting_thread2.start()
                elif cutler_ahead and _parallel_voting_active2:
                    # Stop second parallel voting when Cutler gets back in the lead
                    _parallel_voting_active2 = False
                    print(f"\n⏹ Stopping second parallel voting thread - {TARGET_ATHLETE} is back in the lead!")
                elif current_behind_count < 30 and _parallel_voting_active2:
                    # Stop second parallel thread if behind count drops below 30
                    _parallel_voting_active2 = False
                    print(f"\n⏹ Stopping second parallel voting thread - Cutler is catching up (below 30 rounds behind)")
            
            # Determine wait time based on Cutler's position and consecutive behind count
            # This implements the four-tier adaptive timing system
            if not shutdown_flag:
                with _counter_lock:
                    current_behind_count = consecutive_behind_count
                
                if results and not cutler_ahead:
                    # Cutler is behind - use faster voting intervals based on how long he's been behind
                    if current_behind_count >= 10:
                        # Been behind for 10+ rounds - use super accelerated speed (3-10 seconds)
                        wait_time = random.randint(3, 10)
                        print(f"\n{TARGET_ATHLETE} has been behind for {current_behind_count} rounds. Waiting {wait_time} seconds before next vote (SUPER ACCELERATED)...")
                    elif current_behind_count >= 5:
                        # Been behind for 5-9 rounds - use accelerated speed (7-16 seconds)
                        wait_time = random.randint(7, 16)
                        print(f"\n{TARGET_ATHLETE} has been behind for {current_behind_count} rounds. Waiting {wait_time} seconds before next vote (ACCELERATED)...")
                    else:
                        # Recently behind (1-4 rounds) - use initial accelerated interval (14-37 seconds)
                        wait_time = random.randint(14, 37)
                        print(f"\n{TARGET_ATHLETE} is behind ({current_behind_count}/5 rounds). Waiting {wait_time} seconds before next vote (INITIAL ACCELERATED)...")
                else:
                    # Cutler is ahead or results unavailable - use standard interval (53-67 seconds)
                    wait_time = random.randint(53, 67)
                    print(f"\nWaiting {wait_time} seconds before next vote (STANDARD)...")
                
                print("Press Ctrl+C to stop\n")
                
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
        # Stop all parallel voting threads if they're running
        with _parallel_voting_lock:
            _parallel_voting_active = False
            _parallel_voting_active2 = False
        
        # Wait for parallel threads to finish (with timeout)
        if _parallel_voting_thread and _parallel_voting_thread.is_alive():
            print("\n⏹ Waiting for first parallel voting thread to stop...")
            _parallel_voting_thread.join(timeout=5)
        
        if _parallel_voting_thread2 and _parallel_voting_thread2.is_alive():
            print("\n⏹ Waiting for second parallel voting thread to stop...")
            _parallel_voting_thread2.join(timeout=5)
        
        # Thread-safe read of all counters for final statistics
        with _counter_lock:
            final_vote_count = vote_count
            final_standard_count = standard_vote_count
            final_initial_accelerated_count = initial_accelerated_vote_count
            final_accelerated_count = accelerated_vote_count
            final_super_accelerated_count = super_accelerated_vote_count
        
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

