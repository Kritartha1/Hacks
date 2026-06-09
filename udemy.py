from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import threading

# ---- CONFIG ----
# Your Udemy Enterprise base URL (e.g., https://yourcompany.udemy.com)
ENTERPRISE_URL = "https://yourcompany.udemy.com"

# First lecture URLs for each course you want to complete
# Script will auto-navigate through all lectures in each course
COURSE_START_URLS = [
    "https://yourcompany.udemy.com/course/course-1/learn/lecture/111111",
    "https://yourcompany.udemy.com/course/course-2/learn/lecture/222222",
    "https://yourcompany.udemy.com/course/course-3/learn/lecture/333333",
    "https://yourcompany.udemy.com/course/course-4/learn/lecture/444444",
    "https://yourcompany.udemy.com/course/course-5/learn/lecture/555555",
]

# How many courses to run in parallel (keep ≤5 to avoid overloading RAM)
PARALLEL_WORKERS = 3

PLAYBACK_CHECK_INTERVAL = 10   # seconds between video progress checks
MAX_RESOURCE_WAIT       = 15   # seconds to stay on a resource before clicking Next
# ----------------

# --- CSS Selectors (tried in order, first match wins) ---
NEXT_BTN_SELECTORS = [
    "#go-to-next-item",                              # ✅ Your exact button — prioritized
    "button[data-purpose='next-and-complete-button']",
    "button[data-purpose='go-to-next-lecture']",
    "[aria-label='Go to next lecture']",
    "[aria-label='Next lecture']",
    "button[data-purpose='next-section-button']",
    ".curriculum-item-link--next-item button",
    "a[data-purpose='next-and-complete-button']",
    "button.next-button",
    "[class*='next'][class*='button']",
    "[class*='nextButton']",
]
MARK_COMPLETE_SELECTORS = [
    "button[data-purpose='mark-complete-button']",
    "button[data-purpose='complete-and-continue-button']",
    "[aria-label='Mark as complete']",
]
LOGIN_SUCCESS_INDICATORS = [
    "[data-purpose='user-avatar']",
    ".avatar-image",
    "[aria-label='User profile menu']",
    ".header--profile-img",
]

# --- Helpers ---

def make_driver(headless=False):
    options = webdriver.ChromeOptions()
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    options.add_argument("--mute-audio")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    if headless:
        # NOTE: headless may cause video issues — keep False for reliability
        options.add_argument("--headless=new")
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

def find_element_any(driver, selectors):
    for sel in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed():
                return el
        except:
            continue
    return None

def is_logged_in(driver):
    return find_element_any(driver, LOGIN_SUCCESS_INDICATORS) is not None

def wait_for_sso_login(driver):
    """Open enterprise URL and wait for user to complete SSO manually."""
    print("\n" + "="*60)
    print("🔐 SSO LOGIN REQUIRED")
    print("="*60)
    print(f"   Opening: {ENTERPRISE_URL}")
    print("   Please complete your SSO login in the browser window.")
    print("   Script will automatically continue once login is detected...")
    print("="*60 + "\n")

    driver.get(ENTERPRISE_URL)
    
    # Poll until logged in (up to 5 minutes)
    timeout = 300
    elapsed = 0
    while elapsed < timeout:
        if is_logged_in(driver):
            print("✅ SSO login detected! Continuing...\n")
            return True
        time.sleep(3)
        elapsed += 3
    
    # Fallback: ask user to press Enter
    print("⚠️  Auto-detection timed out.")
    input("   Press Enter manually once you've logged in... ")
    return True

def get_cookies(driver):
    """Extract all cookies from logged-in session."""
    return driver.get_cookies()

def inject_cookies(driver, cookies, url):
    """Inject cookies into a new driver session."""
    driver.get(url)  # must visit domain first before adding cookies
    time.sleep(2)
    for cookie in cookies:
        try:
            # Remove incompatible keys
            cookie.pop("sameSite", None)
            driver.add_cookie(cookie)
        except Exception as e:
            pass
    driver.refresh()
    time.sleep(4)

# --- Video / Navigation Logic ---

def is_video_lecture(driver):
    try:
        return driver.find_element(By.TAG_NAME, "video") is not None
    except:
        return False

def is_video_playing(driver):
    try:
        return driver.execute_script(
            "const v=document.querySelector('video'); return v&&!v.paused&&!v.ended&&v.readyState>2;"
        )
    except:
        return False

def is_video_ended(driver):
    try:
        return driver.execute_script(
            "const v=document.querySelector('video'); return v&&v.ended;"
        )
    except:
        return False

def get_remaining_seconds(driver):
    try:
        return driver.execute_script(
            "const v=document.querySelector('video'); return v?(v.duration-v.currentTime):0;"
        )
    except:
        return 0

def force_play(driver):
    """Start video and set to 2x speed."""
    try:
        driver.execute_script("""
            const v = document.querySelector('video');
            if (v) {
                v.play();
                v.playbackRate = 2.0;
            }
        """)
    except:
        pass
    
    # Also click the play button as fallback
    try:
        btn = driver.find_element(By.CSS_SELECTOR,
            "button[data-purpose='play-button'], .vjs-play-control, button.play-btn")
        btn.click()
        # Set speed again after click (player may reset it)
        driver.execute_script("""
            setTimeout(() => {
                const v = document.querySelector('video');
                if (v) v.playbackRate = 2.0;
            }, 1000);
        """)
    except:
        pass

def click_next(driver, label=""):
    btn = find_element_any(driver, NEXT_BTN_SELECTORS)
    if btn:
        driver.execute_script("arguments[0].click();", btn)
        print(f"  {label} ➡️  Next lecture clicked")
        return True
    print(f"  {label} ⚠️  Next button not found (may be last lecture)")
    return False

def handle_resource(driver, label):
    """Handle non-video content pages."""
    print(f"  {label} 📄 Resource page — waiting {MAX_RESOURCE_WAIT}s...")
    time.sleep(MAX_RESOURCE_WAIT)

    # Mark complete if button exists
    btn = find_element_any(driver, MARK_COMPLETE_SELECTORS)
    if btn:
        driver.execute_script("arguments[0].click();", btn)
        print(f"  {label} ✅ Marked complete")
        time.sleep(2)

    click_next(driver, label)

def run_course(driver, start_url, label):
    """
    Navigate and complete an entire course.
    label = e.g. "[Course 1]" for log readability
    """
    print(f"\n{'='*55}")
    print(f"  {label} 🚀 Starting: {start_url[:70]}")
    print(f"{'='*55}")

    driver.get(start_url)
    time.sleep(6)

    lecture_num = 0

    while True:
        lecture_num += 1
        try:
            title = driver.title[:55]
        except:
            title = "..."
        print(f"\n  {label} 📖 [{lecture_num}] {title}")

        time.sleep(4)  # let page fully load

        if is_video_lecture(driver):
            print(f"  {label} 🎬 Video — playing...")
            force_play(driver)

            # Wait for video to end
            while True:
                time.sleep(PLAYBACK_CHECK_INTERVAL)
                if is_video_ended(driver):
                    print(f"  {label} ✅ Video done")
                    time.sleep(4)  # Udemy auto-advances after video ends
                    break
                remaining = get_remaining_seconds(driver)
                if remaining > 0:
                    mins, secs = divmod(int(remaining), 60)
                    print(f"  {label} ⏱️  {mins}m {secs}s remaining")
                # Resume if paused (idle detection / tab switching pause)
                if not is_video_playing(driver) and not is_video_ended(driver):
                    print(f"  {label} ▶️  Paused — resuming...")
                    force_play(driver)
        else:
            handle_resource(driver, label)

        time.sleep(3)

        # If no Next button, we're at the last lecture
        if not find_element_any(driver, NEXT_BTN_SELECTORS):
            print(f"\n  {label} 🏁 Course complete! ({lecture_num} items)")
            break

# --- Parallel Runner ---

def worker(cookies, url, worker_id):
    label = f"[Course {worker_id}]"
    driver = make_driver(headless=False)
    try:
        print(f"\n{label} 🌐 Injecting session cookies...")
        inject_cookies(driver, cookies, url.split("/learn/")[0])
        time.sleep(2)

        if not is_logged_in(driver):
            print(f"{label} ⚠️  Cookie injection may have failed — check this window")
            time.sleep(10)

        run_course(driver, url, label)
    except Exception as e:
        print(f"{label} ❌ Error: {e}")
    finally:
        print(f"{label} 🔒 Closing window")
        driver.quit()

def main():
    # Step 1: Open one browser for SSO login
    login_driver = make_driver(headless=False)
    login_driver.maximize_window()
    wait_for_sso_login(login_driver)

    # Step 2: Capture the session cookies
    cookies = get_cookies(login_driver)
    print(f"🍪 Captured {len(cookies)} session cookies")
    login_driver.quit()

    # Step 3: Launch parallel workers
    print(f"\n🚀 Launching {PARALLEL_WORKERS} parallel course windows...\n")

    threads = []
    for i, url in enumerate(COURSE_START_URLS):
        t = threading.Thread(
            target=worker,
            args=(cookies, url, i + 1),
            daemon=True
        )
        threads.append(t)
        t.start()
        time.sleep(4)  # stagger starts to avoid race conditions

        # Limit to PARALLEL_WORKERS at a time
        active = [t for t in threads if t.is_alive()]
        while len(active) >= PARALLEL_WORKERS:
            time.sleep(10)
            active = [t for t in threads if t.is_alive()]

    # Wait for all to finish
    for t in threads:
        t.join()

    print("\n\n🎉 All courses completed!")

if __name__ == "__main__":
    main()
