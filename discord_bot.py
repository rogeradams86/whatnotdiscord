import discord
import asyncio
import os
import pickle
from discord.ext import tasks
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime, timedelta
import time

# ✅ Load bot token from environment variables (or hardcode for testing)
TOKEN = os.getenv("DISCORD_BOT_TOKEN")  
if TOKEN is None:
    print("❌ Bot token not found! Set the DISCORD_BOT_TOKEN environment variable.")
    exit()

# 🔹 Set your Discord Channel IDs
LIVE_CHANNEL_ID = 1224749411649851500  # Replace with your live notification channel ID
UPCOMING_SHOWS_CHANNEL_ID = 1351712166016974940  # ✅ Correct Upcoming Shows Channel ID

# 🔹 Set your Whatnot username
WHATNOT_USERNAME = "pokepals_uk"

# 🔹 Path to store session cookies (for bypassing Cloudflare)
COOKIES_FILE = "whatnot_cookies.pkl"

# Discord bot setup
intents = discord.Intents.default()
client = discord.Client(intents=intents)

# Track last detected live show and upcoming shows
last_live_show = None
notified_live_show = False
last_upcoming_shows = set()  # ✅ Track previously posted upcoming shows

def setup_driver():
    """Creates a Chrome WebDriver session with options."""
    options = webdriver.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

def save_cookies(driver):
    """Saves browser cookies to a file for session persistence."""
    with open(COOKIES_FILE, "wb") as file:
        pickle.dump(driver.get_cookies(), file)
    print("✅ Cookies saved!")

def load_cookies(driver):
    """Loads browser cookies from a file if available."""
    if not os.path.exists(COOKIES_FILE):
        print("⚠️ No cookies file found. Cloudflare challenge may appear.")
        return  # Skip loading if the file doesn't exist

    try:
        with open(COOKIES_FILE, "rb") as file:
            cookies = pickle.load(file)
            for cookie in cookies:
                driver.add_cookie(cookie)
        print("✅ Cookies loaded!")
    except (EOFError, pickle.UnpicklingError):
        print("⚠️ Cookies file is corrupted. Deleting and regenerating cookies...")
        os.remove(COOKIES_FILE)  # Delete corrupted file

def parse_show_time(raw_time):
    """
    Converts Whatnot's show time format into a sortable datetime object.
    """
    now = datetime.now()

    # ✅ Handle "Tomorrow"
    if "Tomorrow" in raw_time:
        try:
            show_time = datetime.strptime(raw_time.replace("Tomorrow", "").strip(), "%I:%M %p")
            return (now + timedelta(days=1)).replace(hour=show_time.hour, minute=show_time.minute, second=0)
        except ValueError:
            return now + timedelta(days=1)  # Default to tomorrow if parsing fails

    # ✅ Handle weekday formats like "Fri 8:30 PM"
    try:
        show_time = datetime.strptime(raw_time, "%a %I:%M %p")  # Example: "Fri 8:30 PM"

        # ✅ Find the next occurrence of this weekday
        days_ahead = (show_time.weekday() - now.weekday()) % 7
        if days_ahead == 0 and show_time.time() < now.time():  # If today but past time, push to next week
            days_ahead = 7
        
        return (now + timedelta(days=days_ahead)).replace(hour=show_time.hour, minute=show_time.minute, second=0)
    
    except ValueError:
        return now + timedelta(days=365)  # Default far future date for unrecognized formats

def scrape_live_show():
    """
    Scrapes Whatnot to detect if a live show is currently running.
    """
    url = f"https://www.whatnot.com/user/{WHATNOT_USERNAME}"

    driver = setup_driver()
    driver.get(url)
    load_cookies(driver)
    driver.refresh()
    time.sleep(10)  # ✅ Ensure page loads fully
    save_cookies(driver)

    try:
        print("🔍 Extracting live stream link...")

        # ✅ Find the "Live" banner
        live_element = driver.find_element(By.XPATH, "//div[contains(text(), 'Live')]")

        # ✅ Extract the live show link
        link_element = live_element.find_element(By.XPATH, "./ancestor::a")
        live_url = link_element.get_attribute("href")

        if live_url:
            print(f"✅ Live stream found: {live_url}")
            return live_url

    except Exception as e:
        print("❌ No live show found.")
        return None
    finally:
        driver.quit()

@tasks.loop(minutes=1)
async def check_for_live_show():
    """Checks if a live show is running and posts to Discord."""
    global last_live_show, notified_live_show

    channel = client.get_channel(LIVE_CHANNEL_ID)
    if not channel:
        print(f"❌ Channel not found: {LIVE_CHANNEL_ID}. Check the channel ID and bot permissions.")
        return

    live_show_url = await asyncio.to_thread(scrape_live_show)

    if live_show_url and live_show_url != last_live_show:
        last_live_show = live_show_url
        notified_live_show = False  # ✅ Reset notification flag if a new stream starts

    if live_show_url and not notified_live_show:
        notified_live_show = True  # ✅ Prevent multiple notifications per stream
        message = f"🚨 @everyone **{WHATNOT_USERNAME} is now LIVE!** 🚨\n🎥 Watch here: {live_show_url}"
        await channel.send(message)
    else:
        print("⚠️ No new live stream detected.")

async def scrape_upcoming_shows():
    """Scrapes and sorts upcoming shows properly."""
    # Mocking upcoming shows for now, this should contain proper Selenium scraping logic
    upcoming_shows = {
        "📅 **Cheap Singles Night**\n🕒 Fri 8:30 PM\n🔗 https://www.whatnot.com/live/example1",
        "📅 **Pokémon Booster Opening**\n🕒 Sat 7:00 PM\n🔗 https://www.whatnot.com/live/example2",
        "📅 **Rare Card Auction**\n🕒 Tomorrow 9:00 PM\n🔗 https://www.whatnot.com/live/example3"
    }
    
    return upcoming_shows

@tasks.loop(minutes=30)
async def check_for_upcoming_shows():
    """Checks for upcoming shows and posts only new ones to Discord."""
    global last_upcoming_shows

    channel = client.get_channel(UPCOMING_SHOWS_CHANNEL_ID)
    if not channel:
        print(f"❌ Channel not found: {UPCOMING_SHOWS_CHANNEL_ID}. Check the channel ID and bot permissions.")
        return

    upcoming_shows = await scrape_upcoming_shows()

    # ✅ Find new shows that haven't been posted yet
    new_shows = upcoming_shows - last_upcoming_shows

    if new_shows:
        last_upcoming_shows.update(new_shows)  # ✅ Track posted shows
        message = "**📅 Upcoming Shows:**\n\n" + "\n\n".join(new_shows)
        await channel.send(message)
    else:
        print("⚠️ No new upcoming shows found.")

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    check_for_upcoming_shows.start()
    check_for_live_show.start()  # ✅ Now checks for live streams too

# Run the bot
client.run(TOKEN)