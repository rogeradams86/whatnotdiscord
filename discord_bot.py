import discord
import asyncio
import os
from discord.ext import tasks
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# Load token from environment variable
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN is None:
    print("❌ DISCORD_BOT_TOKEN not set!")
    exit()

# Discord channel IDs
LIVE_CHANNEL_ID = 1224749411649851500
UPCOMING_SHOWS_CHANNEL_ID = 1351712166016974940

# Your Whatnot username
WHATNOT_USERNAME = "pokepals_uk"

# Discord setup
intents = discord.Intents.default()
client = discord.Client(intents=intents)

# State
last_live_show = None
notified_live_show = False
last_upcoming_shows = set()

def parse_show_time(raw_time):
    now = datetime.now()

    if "Tomorrow" in raw_time:
        try:
            show_time = datetime.strptime(raw_time.replace("Tomorrow", "").strip(), "%I:%M %p")
            return (now + timedelta(days=1)).replace(hour=show_time.hour, minute=show_time.minute, second=0)
        except ValueError:
            return now + timedelta(days=1)

    try:
        show_time = datetime.strptime(raw_time, "%a %I:%M %p")
        days_ahead = (show_time.weekday() - now.weekday()) % 7
        if days_ahead == 0 and show_time.time() < now.time():
            days_ahead = 7
        return (now + timedelta(days=days_ahead)).replace(hour=show_time.hour, minute=show_time.minute, second=0)
    except ValueError:
        return now + timedelta(days=365)

def scrape_live_show():
    url = f"https://www.whatnot.com/user/{WHATNOT_USERNAME}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=60000)
            page.wait_for_timeout(5000)

            print("🔍 Looking for live banner...")
            live_elements = page.locator("text=Live ·").all()
            if live_elements:
                link = live_elements[0].locator("xpath=ancestor::a").first
                href = link.get_attribute("href")
                if href:
                    full_url = f"https://www.whatnot.com{href}" if href.startswith("/") else href
                    print(f"✅ Live stream URL: {full_url}")
                    browser.close()
                    return full_url

            print("❌ No live show found.")
            browser.close()
            return None

    except Exception as e:
        print(f"❌ Playwright error: {e}")
        return None

def scrape_upcoming_shows():
    url = f"https://www.whatnot.com/user/{WHATNOT_USERNAME}/shows"
    upcoming = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=60000)
            page.wait_for_timeout(5000)

            print("🔍 Scraping upcoming shows...")
            shows = page.locator("a[href*='/live/']").all()

            for show in shows:
                try:
                    link = show.get_attribute("href")
                    title_el = show.locator("xpath=../../following-sibling::div//div[contains(@class, 'text-400')]").first
                    time_el = show.locator("xpath=./div/div/div").first

                    title = title_el.inner_text().strip() if title_el else "Untitled"
                    raw_time = time_el.inner_text().strip() if time_el else "Unknown"
                    parsed_time = parse_show_time(raw_time)

                    full_url = f"https://www.whatnot.com{link}" if link.startswith("/") else link

                    upcoming.append((parsed_time, f"📅 **{title}**\n🕒 {raw_time}\n🔗 {full_url}"))
                except:
                    continue

            browser.close()
    except Exception as e:
        print(f"❌ Failed to scrape upcoming shows: {e}")

    # Sort and return formatted set
    upcoming.sort(key=lambda x: x[0])
    return set(show[1] for show in upcoming)

@tasks.loop(minutes=1)
async def check_for_live_show():
    global last_live_show, notified_live_show

    channel = client.get_channel(LIVE_CHANNEL_ID)
    if not channel:
        print(f"❌ Live channel {LIVE_CHANNEL_ID} not found.")
        return

    live_show_url = await asyncio.to_thread(scrape_live_show)

    if live_show_url and live_show_url != last_live_show:
        last_live_show = live_show_url
        notified_live_show = False

    if live_show_url and not notified_live_show:
        notified_live_show = True
        await channel.send(f"🚨 @everyone **{WHATNOT_USERNAME} is now LIVE!** 🚨\n🎥 {live_show_url}")
    else:
        print("⚠️ No new live stream detected.")

@tasks.loop(minutes=30)
async def check_for_upcoming_shows():
    global last_upcoming_shows

    channel = client.get_channel(UPCOMING_SHOWS_CHANNEL_ID)
    if not channel:
        print(f"❌ Upcoming channel {UPCOMING_SHOWS_CHANNEL_ID} not found.")
        return

    shows = await asyncio.to_thread(scrape_upcoming_shows)
    new_shows = shows - last_upcoming_shows

    if new_shows:
        last_upcoming_shows.update(new_shows)
        message = "**📅 Upcoming Shows:**\n\n" + "\n\n".join(new_shows)
        await channel.send(message)
    else:
        print("⚠️ No new upcoming shows found.")

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    check_for_live_show.start()
    check_for_upcoming_shows.start()

client.run(TOKEN)
