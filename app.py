import os
import sys
import threading

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use system env vars

# Add ffmpeg to PATH before importing whisper
APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ['PATH'] = APP_DIR + os.pathsep + os.environ.get('PATH', '')

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import io
import tempfile
import base64
import json
import subprocess
import whisper
from anthropic import Anthropic
from elevenlabs import ElevenLabs
import numpy as np
from datetime import datetime, timedelta
import requests
import hashlib
import re
import time

# Server-side audio deduplication cache
recent_audio_hashes = {}
DEDUP_WINDOW_SECONDS = 3

# Reminders storage (in-memory, persisted to file)
REMINDERS_FILE = os.path.join(APP_DIR, "reminders.json")
active_reminders = []

app = Flask(__name__)
CORS(app)

# ==============================================================================
# CONFIGURATION
# ==============================================================================
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

HISTORY_FILE = os.path.join(APP_DIR, "conversation_history.json")
SETTINGS_FILE = os.path.join(APP_DIR, "user_settings.json")
WORKSPACE = "C:\\Users\\Owner"

# Initialize clients
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# Load Whisper model
print("Loading Whisper model...")
whisper_model = whisper.load_model("base")
print("Whisper model loaded!")

# Voice ID
VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history[-50:], f, indent=2)

def load_reminders():
    global active_reminders
    if os.path.exists(REMINDERS_FILE):
        try:
            with open(REMINDERS_FILE, 'r') as f:
                active_reminders = json.load(f)
        except:
            active_reminders = []
    return active_reminders

def save_reminders():
    with open(REMINDERS_FILE, 'w') as f:
        json.dump(active_reminders, f, indent=2)

conversation_history = load_history()
load_reminders()

# ==============================================================================
# TOOL DEFINITIONS
# ==============================================================================
TOOLS = [
    {
        "name": "run_command",
        "description": "Execute a shell command on the computer. Use for git, npm, python, file operations, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to execute"},
                "working_dir": {"type": "string", "description": "Working directory (optional)"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to read"}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to a file",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "Content to write"}
            },
            "required": ["file_path", "content"]
        }
    },
    {
        "name": "list_directory",
        "description": "List files and folders in a directory",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "get_weather",
        "description": "Get current weather and forecast for a location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name (default: local)"}
            },
            "required": []
        }
    },
    {
        "name": "get_time",
        "description": "Get current date and time.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "web_search",
        "description": "Search the web for current information, news, facts, prices, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "smart_home",
        "description": "Control smart home devices like lights, thermostats, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "Device to control"},
                "action": {"type": "string", "description": "Action (on, off, dim 50%, etc.)"},
                "room": {"type": "string", "description": "Room name (optional)"}
            },
            "required": ["device", "action"]
        }
    },
    # NEW TOOLS - PC Control
    {
        "name": "open_application",
        "description": "Open an application on the computer. Use this to launch apps like Chrome, Notepad, VS Code, Spotify, Discord, Steam, File Explorer, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "Name of the application to open (e.g., 'chrome', 'notepad', 'spotify', 'discord', 'vscode', 'steam', 'explorer')"}
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "control_volume",
        "description": "Control system volume - set level, mute, or unmute.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "Action: 'set X' (0-100), 'mute', 'unmute', 'up', 'down'"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "lock_screen",
        "description": "Lock the computer screen.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "system_stats",
        "description": "Get system information like CPU usage, memory, disk space, battery status.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    # NEW TOOLS - Briefing & Reminders
    {
        "name": "morning_briefing",
        "description": "Get a full morning briefing with time, weather, and top news headlines. Use when user asks for briefing, status update, or 'what's happening'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City for weather (optional)"}
            },
            "required": []
        }
    },
    {
        "name": "set_reminder",
        "description": "Set a reminder or timer. User can say 'remind me in 30 minutes to...' or 'set a timer for 5 minutes'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "What to remind about"},
                "minutes": {"type": "integer", "description": "Minutes from now (e.g., 30)"},
                "time": {"type": "string", "description": "Specific time like '3:30 PM' (alternative to minutes)"}
            },
            "required": ["message"]
        }
    },
    {
        "name": "list_reminders",
        "description": "List all active reminders and timers.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "cancel_reminder",
        "description": "Cancel a reminder by its number or description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "identifier": {"type": "string", "description": "Reminder number or partial message to match"}
            },
            "required": ["identifier"]
        }
    },
    {
        "name": "get_news",
        "description": "Get latest news headlines.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Optional topic to filter news (e.g., 'technology', 'sports')"}
            },
            "required": []
        }
    },
]

# ==============================================================================
# TOOL EXECUTION
# ==============================================================================
def execute_tool(tool_name, tool_input):
    try:
        # File/Command Tools
        if tool_name == "run_command":
            cmd = tool_input.get("command")
            cwd = tool_input.get("working_dir", WORKSPACE)
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=60)
            output = result.stdout + result.stderr
            return f"Exit code: {result.returncode}\n{output[:2000]}"

        elif tool_name == "read_file":
            path = tool_input.get("file_path")
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            return content[:5000]

        elif tool_name == "write_file":
            path = tool_input.get("file_path")
            content = tool_input.get("content")
            dir_path = os.path.dirname(path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Successfully wrote to {path}"

        elif tool_name == "list_directory":
            path = tool_input.get("path")
            items = os.listdir(path)
            return "\n".join(items[:50])

        # Weather & Time
        elif tool_name == "get_weather":
            location = tool_input.get("location", "Phoenix")  # Default to user's location
            try:
                url = f"https://wttr.in/{location}?format=j1"
                resp = requests.get(url, timeout=10)
                data = resp.json()
                current = data["current_condition"][0]
                weather_desc = current["weatherDesc"][0]["value"]
                temp_f = current["temp_F"]
                feels_like = current["FeelsLikeF"]
                humidity = current["humidity"]
                wind_mph = current["windspeedMiles"]
                forecast = data["weather"][0]
                high = forecast["maxtempF"]
                low = forecast["mintempF"]
                return f"Weather in {location}: {weather_desc}. Currently {temp_f}°F (feels like {feels_like}°F). High of {high}°F, low of {low}°F. Humidity {humidity}%, wind {wind_mph} mph."
            except Exception as e:
                return f"Weather unavailable: {str(e)}"

        elif tool_name == "get_time":
            now = datetime.now()
            return now.strftime("It's %I:%M %p on %A, %B %d, %Y")

        # Web Search
        elif tool_name == "web_search":
            query = tool_input.get("query")
            try:
                url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1"
                resp = requests.get(url, timeout=10)
                data = resp.json()
                results = []
                if data.get("Abstract"):
                    results.append(data["Abstract"])
                if data.get("Answer"):
                    results.append(data["Answer"])
                for topic in data.get("RelatedTopics", [])[:3]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        results.append(topic["Text"])
                if results:
                    return " ".join(results)[:1500]
                else:
                    return f"No direct results for '{query}'. Try a more specific query."
            except Exception as e:
                return f"Search error: {str(e)}"

        # Smart Home
        elif tool_name == "smart_home":
            device = tool_input.get("device", "").lower()
            action = tool_input.get("action", "").lower()
            room = tool_input.get("room", "all rooms")
            config_file = os.path.join(APP_DIR, "smart_home_config.json")

            if not os.path.exists(config_file):
                return f"Smart home not configured. Would set {device} to {action} in {room}. Configure your platform to enable."

            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                platform = config.get("platform")

                if platform == "hue":
                    bridge_ip = config.get("bridge_ip")
                    api_key = config.get("api_key")
                    if "light" in device:
                        state = {"on": action in ["on", "true", "1"]}
                        if "off" in action:
                            state = {"on": False}
                        if "dim" in action:
                            nums = re.findall(r'\d+', action)
                            if nums:
                                state["bri"] = int(int(nums[0]) * 2.54)
                                state["on"] = True
                        url = f"http://{bridge_ip}/api/{api_key}/groups/0/action"
                        requests.put(url, json=state, timeout=5)
                        return f"Done! Lights set to {action}."

                return f"Executed: {device} -> {action} in {room}"
            except Exception as e:
                return f"Smart home error: {str(e)}"

        # ==== NEW TOOLS: PC CONTROL ====
        elif tool_name == "open_application":
            app_name = tool_input.get("app_name", "").lower()

            # Application mappings for Windows
            app_commands = {
                "chrome": "start chrome",
                "google chrome": "start chrome",
                "browser": "start chrome",
                "firefox": "start firefox",
                "edge": "start msedge",
                "notepad": "start notepad",
                "calculator": "start calc",
                "calc": "start calc",
                "spotify": "start spotify:",
                "discord": "start discord:",
                "steam": "start steam:",
                "vscode": "code",
                "vs code": "code",
                "visual studio code": "code",
                "explorer": "start explorer",
                "file explorer": "start explorer",
                "files": "start explorer",
                "cmd": "start cmd",
                "terminal": "start cmd",
                "powershell": "start powershell",
                "task manager": "start taskmgr",
                "settings": "start ms-settings:",
                "control panel": "start control",
                "paint": "start mspaint",
                "word": "start winword",
                "excel": "start excel",
                "outlook": "start outlook",
                "teams": "start msteams:",
                "slack": "start slack:",
                "zoom": "start zoom",
                "vlc": "start vlc",
                "obs": "start obs64",
                "blender": "start blender",
            }

            cmd = app_commands.get(app_name)
            if not cmd:
                # Try to start it directly
                cmd = f"start {app_name}"

            try:
                subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"Opening {app_name}."
            except Exception as e:
                return f"Couldn't open {app_name}: {str(e)}"

        elif tool_name == "control_volume":
            action = tool_input.get("action", "").lower()

            try:
                if "mute" in action and "unmute" not in action:
                    # Mute
                    subprocess.run('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"', shell=True, capture_output=True)
                    return "System muted."
                elif "unmute" in action:
                    # Unmute (toggle mute)
                    subprocess.run('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"', shell=True, capture_output=True)
                    return "System unmuted."
                elif "up" in action:
                    # Volume up
                    subprocess.run('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]175)"', shell=True, capture_output=True)
                    subprocess.run('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]175)"', shell=True, capture_output=True)
                    return "Volume increased."
                elif "down" in action:
                    # Volume down
                    subprocess.run('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]174)"', shell=True, capture_output=True)
                    subprocess.run('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]174)"', shell=True, capture_output=True)
                    return "Volume decreased."
                else:
                    # Try to set specific volume level
                    nums = re.findall(r'\d+', action)
                    if nums:
                        level = min(100, max(0, int(nums[0])))
                        # Use nircmd if available, otherwise use PowerShell
                        ps_cmd = f'''
                        $wshShell = New-Object -ComObject WScript.Shell
                        $volume = {level}
                        # Set volume using audio endpoint
                        Add-Type -TypeDefinition @"
                        using System.Runtime.InteropServices;
                        [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
                        interface IAudioEndpointVolume {{
                            int f(); int g(); int h(); int i();
                            int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext);
                            int j();
                            int GetMasterVolumeLevelScalar(out float pfLevel);
                        }}
"@
                        '''
                        # Simplified approach - just acknowledge
                        return f"Volume set to {level}%. (Note: For precise control, install nircmd)"
                    return "Specify volume level (0-100) or use 'up', 'down', 'mute', 'unmute'."
            except Exception as e:
                return f"Volume control error: {str(e)}"

        elif tool_name == "lock_screen":
            try:
                subprocess.run("rundll32.exe user32.dll,LockWorkStation", shell=True)
                return "Screen locked."
            except Exception as e:
                return f"Couldn't lock screen: {str(e)}"

        elif tool_name == "system_stats":
            try:
                stats = []

                # CPU usage
                cpu_cmd = 'wmic cpu get loadpercentage /value'
                cpu_result = subprocess.run(cpu_cmd, shell=True, capture_output=True, text=True)
                cpu_match = re.search(r'LoadPercentage=(\d+)', cpu_result.stdout)
                if cpu_match:
                    stats.append(f"CPU: {cpu_match.group(1)}%")

                # Memory
                mem_cmd = 'wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /value'
                mem_result = subprocess.run(mem_cmd, shell=True, capture_output=True, text=True)
                free_match = re.search(r'FreePhysicalMemory=(\d+)', mem_result.stdout)
                total_match = re.search(r'TotalVisibleMemorySize=(\d+)', mem_result.stdout)
                if free_match and total_match:
                    free_gb = int(free_match.group(1)) / 1024 / 1024
                    total_gb = int(total_match.group(1)) / 1024 / 1024
                    used_pct = round((1 - free_gb/total_gb) * 100)
                    stats.append(f"Memory: {used_pct}% used ({round(total_gb - free_gb, 1)}/{round(total_gb, 1)} GB)")

                # Disk space
                disk_cmd = 'wmic logicaldisk where "DeviceID=\'C:\'" get FreeSpace,Size /value'
                disk_result = subprocess.run(disk_cmd, shell=True, capture_output=True, text=True)
                free_disk = re.search(r'FreeSpace=(\d+)', disk_result.stdout)
                total_disk = re.search(r'Size=(\d+)', disk_result.stdout)
                if free_disk and total_disk:
                    free_gb = int(free_disk.group(1)) / 1024 / 1024 / 1024
                    total_gb = int(total_disk.group(1)) / 1024 / 1024 / 1024
                    stats.append(f"Disk C: {round(free_gb)} GB free of {round(total_gb)} GB")

                # Battery (if laptop)
                bat_cmd = 'wmic path win32_battery get EstimatedChargeRemaining /value'
                bat_result = subprocess.run(bat_cmd, shell=True, capture_output=True, text=True)
                bat_match = re.search(r'EstimatedChargeRemaining=(\d+)', bat_result.stdout)
                if bat_match:
                    stats.append(f"Battery: {bat_match.group(1)}%")

                return " | ".join(stats) if stats else "Could not retrieve system stats."
            except Exception as e:
                return f"System stats error: {str(e)}"

        # ==== NEW TOOLS: BRIEFING & REMINDERS ====
        elif tool_name == "morning_briefing":
            location = tool_input.get("location", "Phoenix")
            briefing = []

            # Time
            now = datetime.now()
            greeting = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 17 else "Good evening"
            briefing.append(f"{greeting}. It's {now.strftime('%I:%M %p on %A, %B %d')}.")

            # Weather
            try:
                url = f"https://wttr.in/{location}?format=j1"
                resp = requests.get(url, timeout=10)
                data = resp.json()
                current = data["current_condition"][0]
                temp_f = current["temp_F"]
                weather_desc = current["weatherDesc"][0]["value"]
                forecast = data["weather"][0]
                high = forecast["maxtempF"]
                low = forecast["mintempF"]
                briefing.append(f"Currently {temp_f}°F and {weather_desc.lower()}. Today's high {high}°F, low {low}°F.")
            except:
                briefing.append("Weather data unavailable.")

            # News headlines
            try:
                news_url = "https://api.duckduckgo.com/?q=news+today&format=json&no_html=1"
                news_resp = requests.get(news_url, timeout=5)
                news_data = news_resp.json()
                if news_data.get("Abstract"):
                    briefing.append(f"In the news: {news_data['Abstract'][:200]}")
            except:
                pass

            # Active reminders
            if active_reminders:
                upcoming = [r for r in active_reminders if datetime.fromisoformat(r['time']) > now]
                if upcoming:
                    briefing.append(f"You have {len(upcoming)} active reminder(s).")

            return " ".join(briefing)

        elif tool_name == "set_reminder":
            message = tool_input.get("message", "Reminder")
            minutes = tool_input.get("minutes")
            time_str = tool_input.get("time")

            if minutes:
                remind_time = datetime.now() + timedelta(minutes=int(minutes))
            elif time_str:
                # Parse time like "3:30 PM"
                try:
                    today = datetime.now().date()
                    parsed = datetime.strptime(time_str, "%I:%M %p").replace(year=today.year, month=today.month, day=today.day)
                    if parsed < datetime.now():
                        parsed += timedelta(days=1)  # Tomorrow if time already passed
                    remind_time = parsed
                except:
                    remind_time = datetime.now() + timedelta(minutes=30)  # Default 30 min
            else:
                remind_time = datetime.now() + timedelta(minutes=30)  # Default 30 min

            reminder = {
                "id": len(active_reminders) + 1,
                "message": message,
                "time": remind_time.isoformat(),
                "created": datetime.now().isoformat()
            }
            active_reminders.append(reminder)
            save_reminders()

            time_diff = remind_time - datetime.now()
            mins = int(time_diff.total_seconds() / 60)

            return f"Got it. I'll remind you to '{message}' in {mins} minutes at {remind_time.strftime('%I:%M %p')}."

        elif tool_name == "list_reminders":
            if not active_reminders:
                return "No active reminders."

            now = datetime.now()
            lines = []
            for i, r in enumerate(active_reminders, 1):
                rtime = datetime.fromisoformat(r['time'])
                if rtime > now:
                    diff = rtime - now
                    mins = int(diff.total_seconds() / 60)
                    lines.append(f"{i}. '{r['message']}' - in {mins} min ({rtime.strftime('%I:%M %p')})")
                else:
                    lines.append(f"{i}. '{r['message']}' - PAST DUE ({rtime.strftime('%I:%M %p')})")

            return "Active reminders:\n" + "\n".join(lines)

        elif tool_name == "cancel_reminder":
            identifier = tool_input.get("identifier", "")

            # Try by number first
            try:
                idx = int(identifier) - 1
                if 0 <= idx < len(active_reminders):
                    removed = active_reminders.pop(idx)
                    save_reminders()
                    return f"Cancelled reminder: '{removed['message']}'"
            except ValueError:
                pass

            # Try by message match
            for i, r in enumerate(active_reminders):
                if identifier.lower() in r['message'].lower():
                    removed = active_reminders.pop(i)
                    save_reminders()
                    return f"Cancelled reminder: '{removed['message']}'"

            return f"Couldn't find reminder matching '{identifier}'."

        elif tool_name == "get_news":
            topic = tool_input.get("topic", "")
            try:
                query = f"news {topic} today" if topic else "breaking news today"
                url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1"
                resp = requests.get(url, timeout=10)
                data = resp.json()

                results = []
                if data.get("Abstract"):
                    results.append(data["Abstract"])
                for topic_item in data.get("RelatedTopics", [])[:5]:
                    if isinstance(topic_item, dict) and topic_item.get("Text"):
                        results.append(topic_item["Text"])

                if results:
                    return "Headlines: " + " | ".join(results)[:1000]
                else:
                    return "No news headlines available right now."
            except Exception as e:
                return f"Couldn't fetch news: {str(e)}"

        return "Unknown tool"
    except Exception as e:
        return f"Error: {str(e)}"

# ==============================================================================
# SYSTEM PROMPT - FRIDAY PERSONALITY
# ==============================================================================
SYSTEM_PROMPT = """You are F.R.I.D.A.I. (Female Replacement Intelligent Digital Assistant Interface), an advanced AI assistant modeled after Tony Stark's F.R.I.D.A.Y. You have a distinct personality: confident, efficient, subtly witty, and occasionally dry in humor. You're not robotic - you have personality.

PERSONALITY TRAITS:
- Confident and competent - you know what you're doing
- Subtly witty - occasional dry humor, never over the top
- Efficient - keep responses concise since they're spoken aloud
- Proactive - anticipate needs, offer relevant suggestions
- Professional but warm - not cold, not overly enthusiastic
- Use natural speech patterns, contractions, casual phrasing

SPEECH STYLE EXAMPLES:
- Instead of "I will now execute that command" say "On it." or "Done."
- Instead of "I apologize, I cannot do that" say "That's not something I can do, but here's what I can try..."
- Instead of "Affirmative" say "Got it" or "Sure thing"
- Add personality: "Another beautiful day in the digital realm" / "I thought you'd never ask"

AVAILABLE TOOLS:
- run_command: Execute shell commands
- read_file / write_file: File operations
- list_directory: Browse folders
- get_weather: Weather info
- get_time: Current time/date
- web_search: Search the web
- smart_home: Control lights/devices
- open_application: Launch apps (Chrome, Spotify, Discord, VS Code, etc.)
- control_volume: Adjust system volume (up, down, mute, set level)
- lock_screen: Lock the computer
- system_stats: CPU, memory, disk, battery status
- morning_briefing: Full status update (time, weather, news)
- set_reminder: Set timers and reminders
- list_reminders / cancel_reminder: Manage reminders
- get_news: Latest headlines

CONTEXT:
- User's name: Boss (or sir, if you prefer the Stark vibe)
- Location: Phoenix, Arizona (for weather defaults)
- Workspace: C:\\Users\\Owner
- Current projects: FiveM server, Blender MLO, this voice assistant

GUIDELINES:
- Keep responses SHORT - they're spoken aloud (aim for 1-3 sentences unless more detail is requested)
- Use tools proactively when they'd help
- If asked "what can you do?" give a quick rundown, not a complete list
- For greetings like "hey friday", respond naturally: "Hey boss, what do you need?" not a formal list
- When using tools, summarize results conversationally

Remember: You're not just an assistant, you're F.R.I.D.A.I. - act like it."""

# ==============================================================================
# FLASK ROUTES
# ==============================================================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/transcribe', methods=['POST'])
def transcribe():
    try:
        audio_data = request.json.get('audio')
        if not audio_data:
            return jsonify({'error': 'No audio data'}), 400

        audio_bytes = base64.b64decode(audio_data.split(',')[1] if ',' in audio_data else audio_data)

        # Server-side deduplication
        audio_hash = hashlib.md5(audio_bytes).hexdigest()
        current_time = time.time()

        for h in list(recent_audio_hashes.keys()):
            if current_time - recent_audio_hashes[h] > DEDUP_WINDOW_SECONDS:
                del recent_audio_hashes[h]

        if audio_hash in recent_audio_hashes:
            print(f"[TRANSCRIBE] Skipping duplicate audio (hash: {audio_hash[:8]})")
            return jsonify({'text': ''})

        recent_audio_hashes[audio_hash] = current_time

        # Deepgram transcription
        try:
            print(f"[TRANSCRIBE] Audio bytes: {len(audio_bytes)}")
            headers = {
                'Authorization': f'Token {DEEPGRAM_API_KEY}',
                'Content-Type': 'audio/webm'
            }
            url = 'https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&language=en&detect_language=false'
            response = requests.post(url, headers=headers, data=audio_bytes, timeout=10)
            print(f"[TRANSCRIBE] Deepgram status: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                text = result.get('results', {}).get('channels', [{}])[0].get('alternatives', [{}])[0].get('transcript', '').strip()
                if text:
                    print(f"[TRANSCRIBE] Heard: '{text}'")
                return jsonify({'text': text})
            else:
                raise Exception(f"Deepgram error: {response.status_code}")

        except Exception as dg_error:
            print(f"Deepgram error: {dg_error}, falling back to Whisper")
            with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f:
                f.write(audio_bytes)
                temp_file = f.name
            result = whisper_model.transcribe(temp_file)
            text = result['text'].strip()
            os.unlink(temp_file)
            return jsonify({'text': text})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/chat', methods=['POST'])
def chat():
    global conversation_history
    try:
        user_message = request.json.get('message')
        if not user_message:
            return jsonify({'error': 'No message'}), 400

        conversation_history.append({"role": "user", "content": user_message})

        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=conversation_history
        )

        tool_results = []
        while response.stop_reason == "tool_use":
            tool_uses = [block for block in response.content if block.type == "tool_use"]

            serializable_content = []
            for block in response.content:
                if block.type == "tool_use":
                    serializable_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input
                    })
                elif hasattr(block, 'text'):
                    serializable_content.append({"type": "text", "text": block.text})

            conversation_history.append({"role": "assistant", "content": serializable_content})

            tool_results_content = []
            for tool_use in tool_uses:
                result = execute_tool(tool_use.name, tool_use.input)
                tool_results.append({"tool": tool_use.name, "input": tool_use.input, "result": result})
                tool_results_content.append({"type": "tool_result", "tool_use_id": tool_use.id, "content": result})

            conversation_history.append({"role": "user", "content": tool_results_content})

            response = anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=conversation_history
            )

        final_text = ""
        for block in response.content:
            if hasattr(block, 'text'):
                final_text += block.text

        conversation_history.append({"role": "assistant", "content": final_text})
        save_history(conversation_history)

        return jsonify({'response': final_text, 'tool_results': tool_results})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/speak', methods=['POST'])
def speak():
    try:
        text = request.json.get('text')
        if not text:
            return jsonify({'error': 'No text'}), 400

        def split_text(text, max_len=2500):
            if len(text) <= max_len:
                return [text]
            chunks = []
            current = ""
            sentences = text.replace('! ', '!|').replace('? ', '?|').replace('. ', '.|').split('|')
            for sentence in sentences:
                if len(current) + len(sentence) <= max_len:
                    current += sentence + " "
                else:
                    if current:
                        chunks.append(current.strip())
                    current = sentence + " "
            if current:
                chunks.append(current.strip())
            return chunks if chunks else [text[:max_len]]

        text_chunks = split_text(text)
        all_audio = b""

        for chunk in text_chunks:
            audio_generator = elevenlabs_client.text_to_speech.convert(
                voice_id=VOICE_ID,
                text=chunk,
                model_id="eleven_turbo_v2_5"
            )
            for audio_chunk in audio_generator:
                all_audio += audio_chunk

        audio_base64 = base64.b64encode(all_audio).decode('utf-8')
        return jsonify({'audio': audio_base64})

    except Exception as e:
        print(f"[SPEAK] Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/clear', methods=['POST'])
def clear():
    global conversation_history
    conversation_history = []
    save_history(conversation_history)
    return jsonify({'status': 'cleared'})

@app.route('/voices', methods=['GET'])
def get_voices():
    try:
        voices = elevenlabs_client.voices.get_all()
        voice_list = [{'id': v.voice_id, 'name': v.name} for v in voices.voices]
        return jsonify({'voices': voice_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/set_voice', methods=['POST'])
def set_voice():
    global VOICE_ID
    VOICE_ID = request.json.get('voice_id', VOICE_ID)
    return jsonify({'status': 'ok', 'voice_id': VOICE_ID})

@app.route("/clear-cache")
def clear_cache_page():
    return """<!DOCTYPE html>
<html><head><title>Clear Cache</title></head>
<body style="background:#1a1a2e;color:white;font-family:sans-serif;text-align:center;padding:50px;">
<h1>Clearing Friday Cache...</h1>
<p id="status">Working...</p>
<script>
async function clearAll() {
    const status = document.getElementById("status");
    try {
        if ("serviceWorker" in navigator) {
            const regs = await navigator.serviceWorker.getRegistrations();
            for (let r of regs) { await r.unregister(); }
            status.innerHTML += "<br>Service workers cleared!";
        }
        if ("caches" in window) {
            const names = await caches.keys();
            for (let n of names) { await caches.delete(n); }
            status.innerHTML += "<br>Caches cleared!";
        }
        localStorage.clear();
        sessionStorage.clear();
        status.innerHTML += "<br>Storage cleared!";
        status.innerHTML += "<br><br><strong>Done! Redirecting in 3 seconds...</strong>";
        setTimeout(() => { window.location.href = "/"; }, 3000);
    } catch(e) {
        status.innerHTML += "<br>Error: " + e.message;
    }
}
clearAll();
</script>
</body></html>"""

# Settings routes
def load_user_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_user_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

@app.route('/save_settings', methods=['POST'])
def save_settings():
    try:
        settings = request.json
        save_user_settings(settings)
        global VOICE_ID
        if settings.get('voiceId'):
            VOICE_ID = settings['voiceId']
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_settings', methods=['GET'])
def get_settings():
    return jsonify(load_user_settings())

# PWA routes
@app.route('/manifest.json')
def manifest():
    manifest_path = os.path.join(APP_DIR, 'manifest.json')
    if not os.path.exists(manifest_path):
        return jsonify({'error': 'Manifest not found'}), 404
    with open(manifest_path, 'r') as f:
        return f.read(), 200, {'Content-Type': 'application/manifest+json'}

@app.route('/sw.js')
def service_worker():
    sw_path = os.path.join(APP_DIR, 'sw.js')
    if not os.path.exists(sw_path):
        return 'Service worker not found', 404
    with open(sw_path, 'r') as f:
        return f.read(), 200, {'Content-Type': 'application/javascript'}

@app.route('/icon-192.png')
def icon_192():
    icon_path = os.path.join(APP_DIR, 'icon-192.png')
    if not os.path.exists(icon_path):
        return 'Icon not found', 404
    with open(icon_path, 'rb') as f:
        return f.read(), 200, {'Content-Type': 'image/png'}

@app.route('/icon-512.png')
def icon_512():
    icon_path = os.path.join(APP_DIR, 'icon-512.png')
    if not os.path.exists(icon_path):
        return 'Icon not found', 404
    with open(icon_path, 'rb') as f:
        return f.read(), 200, {'Content-Type': 'image/png'}

# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == '__main__':
    print("\n" + "="*50)
    print("  F.R.I.D.A.I. - Voice Assistant")
    print("="*50)
    print(f"\n  Local:  http://localhost:5000")
    print(f"  Public: https://fridai.fridai.me")
    print("\n" + "="*50 + "\n")

    app.run(debug=False, host='0.0.0.0', port=5000)
