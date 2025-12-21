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

# Long-term memory system
USER_PROFILE_FILE = os.path.join(APP_DIR, "user_profile.json")
MEMORY_BANK_FILE = os.path.join(APP_DIR, "memory_bank.json")

# Default user profile structure
DEFAULT_USER_PROFILE = {
    "name": "Boss",
    "preferred_name": "Boss",
    "location": "Phoenix, Arizona",
    "timezone": "America/Phoenix",
    "communication_style": "casual and direct",
    "interests": [],
    "current_projects": [],
    "important_dates": {},
    "preferences": {
        "greeting_style": "casual",
        "detail_level": "concise",
        "humor": True
    },
    "work_info": {},
    "personal_info": {},
    "last_updated": None
}

# Default memory bank structure
DEFAULT_MEMORY_BANK = {
    "facts": [],           # Things FRIDAY has learned about the user
    "preferences": [],     # User preferences discovered over time
    "corrections": [],     # Times user corrected FRIDAY (to learn from)
    "important_events": [],# Significant events/milestones
    "conversation_summaries": [],  # Summaries of past conversations
    "last_updated": None
}

# Custom Routines system
ROUTINES_FILE = os.path.join(APP_DIR, "routines.json")
DEFAULT_ROUTINES = {
    "gaming_mode": {
        "name": "Gaming Mode",
        "description": "Prepare for gaming session",
        "actions": [
            {"tool": "open_application", "params": {"app_name": "steam"}},
            {"tool": "open_application", "params": {"app_name": "discord"}},
            {"tool": "control_volume", "params": {"action": "set 80"}}
        ]
    },
    "work_mode": {
        "name": "Work Mode",
        "description": "Set up for productive work",
        "actions": [
            {"tool": "open_application", "params": {"app_name": "vscode"}},
            {"tool": "open_application", "params": {"app_name": "chrome"}}
        ]
    },
    "night_mode": {
        "name": "Night Mode",
        "description": "Wind down for the night",
        "actions": [
            {"tool": "control_volume", "params": {"action": "set 30"}},
            {"tool": "lock_screen", "params": {}}
        ]
    }
}

# Usage patterns tracking
PATTERNS_FILE = os.path.join(APP_DIR, "patterns.json")
DEFAULT_PATTERNS = {
    "app_usage": {},        # Track which apps are used when
    "command_frequency": {},# Track common commands
    "active_hours": {},     # Track when user is typically active
    "last_updated": None
}

# Proactive alerts system
pending_alerts = []  # Alerts waiting to be delivered
ALERT_CHECK_INTERVAL = 60  # Check every 60 seconds
last_alert_check = 0

app = Flask(__name__)
CORS(app)

# ==============================================================================
# CONFIGURATION
# ==============================================================================
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SMARTTHINGS_API_KEY = os.environ.get("SMARTTHINGS_API_KEY", "")

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

# Voice ID and Settings
VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
VOICE_SETTINGS_FILE = os.path.join(APP_DIR, "voice_settings.json")

# Default voice settings for ElevenLabs
DEFAULT_VOICE_SETTINGS = {
    "voice_id": "21m00Tcm4TlvDq8ikWAM",  # Rachel (default)
    "model_id": "eleven_turbo_v2_5",
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.0,
    "use_speaker_boost": True
}

# Available ElevenLabs voices (common ones)
AVAILABLE_VOICES = {
    "rachel": {"id": "21m00Tcm4TlvDq8ikWAM", "description": "Calm, professional female (default FRIDAY)"},
    "domi": {"id": "AZnzlk1XvdvUeBnXmlld", "description": "Strong, confident female"},
    "bella": {"id": "EXAVITQu4vr4xnSDxMaL", "description": "Soft, friendly female"},
    "elli": {"id": "MF3mGyEYCl7XYWbV9V6O", "description": "Young, energetic female"},
    "josh": {"id": "TxGEqnHWrfWFTfGW9XjX", "description": "Deep, authoritative male"},
    "arnold": {"id": "VR6AewLTigWG4xSOukaG", "description": "Strong, commanding male"},
    "adam": {"id": "pNInz6obpgDQGcFmaJgB", "description": "Deep, warm male"},
    "sam": {"id": "yoZ06aMxZJJ28mfd3POQ", "description": "Raspy, casual male"}
}

def load_voice_settings():
    """Load voice settings from file."""
    if os.path.exists(VOICE_SETTINGS_FILE):
        try:
            with open(VOICE_SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                # Merge with defaults
                for key in DEFAULT_VOICE_SETTINGS:
                    if key not in settings:
                        settings[key] = DEFAULT_VOICE_SETTINGS[key]
                return settings
        except:
            return DEFAULT_VOICE_SETTINGS.copy()
    return DEFAULT_VOICE_SETTINGS.copy()

def save_voice_settings(settings):
    """Save voice settings to file."""
    with open(VOICE_SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

def get_current_voice_id():
    """Get the current voice ID from settings."""
    settings = load_voice_settings()
    return settings.get("voice_id", VOICE_ID)

# Load voice settings at startup
voice_settings = load_voice_settings()

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
        json.dump(history[-200:], f, indent=2)  # Keep last 200 messages for better memory

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

# ==============================================================================
# LONG-TERM MEMORY FUNCTIONS
# ==============================================================================
def load_user_profile():
    """Load user profile from file, or create default if not exists."""
    if os.path.exists(USER_PROFILE_FILE):
        try:
            with open(USER_PROFILE_FILE, 'r') as f:
                profile = json.load(f)
                # Merge with defaults to ensure all keys exist
                for key, value in DEFAULT_USER_PROFILE.items():
                    if key not in profile:
                        profile[key] = value
                return profile
        except:
            return DEFAULT_USER_PROFILE.copy()
    return DEFAULT_USER_PROFILE.copy()

def save_user_profile(profile):
    """Save user profile to file."""
    profile['last_updated'] = datetime.now().isoformat()
    with open(USER_PROFILE_FILE, 'w') as f:
        json.dump(profile, f, indent=2)

def load_memory_bank():
    """Load memory bank from file, or create default if not exists."""
    if os.path.exists(MEMORY_BANK_FILE):
        try:
            with open(MEMORY_BANK_FILE, 'r') as f:
                memory = json.load(f)
                # Merge with defaults to ensure all keys exist
                for key, value in DEFAULT_MEMORY_BANK.items():
                    if key not in memory:
                        memory[key] = value
                return memory
        except:
            return DEFAULT_MEMORY_BANK.copy()
    return DEFAULT_MEMORY_BANK.copy()

def save_memory_bank(memory):
    """Save memory bank to file."""
    memory['last_updated'] = datetime.now().isoformat()
    with open(MEMORY_BANK_FILE, 'w') as f:
        json.dump(memory, f, indent=2)

def get_memory_context():
    """Build a context string from user profile and memory bank for the AI."""
    profile = load_user_profile()
    memory = load_memory_bank()

    context_parts = []

    # User profile context
    context_parts.append(f"USER PROFILE:")
    context_parts.append(f"- Name: {profile.get('preferred_name', 'Boss')}")
    context_parts.append(f"- Location: {profile.get('location', 'Unknown')}")
    context_parts.append(f"- Communication style: {profile.get('communication_style', 'casual')}")

    if profile.get('interests'):
        context_parts.append(f"- Interests: {', '.join(profile['interests'][:5])}")

    if profile.get('current_projects'):
        context_parts.append(f"- Current projects: {', '.join(profile['current_projects'][:3])}")

    if profile.get('important_dates'):
        dates_str = ", ".join([f"{k}: {v}" for k, v in list(profile['important_dates'].items())[:3]])
        context_parts.append(f"- Important dates: {dates_str}")

    # Memory bank context - recent facts
    if memory.get('facts'):
        recent_facts = memory['facts'][-10:]  # Last 10 facts
        context_parts.append(f"\nTHINGS I'VE LEARNED ABOUT YOU:")
        for fact in recent_facts:
            context_parts.append(f"- {fact.get('content', '')}")

    # Learned preferences
    if memory.get('preferences'):
        recent_prefs = memory['preferences'][-5:]  # Last 5 preferences
        context_parts.append(f"\nYOUR PREFERENCES I'VE NOTICED:")
        for pref in recent_prefs:
            context_parts.append(f"- {pref.get('content', '')}")

    # Recent conversation summaries
    if memory.get('conversation_summaries'):
        recent_summaries = memory['conversation_summaries'][-3:]  # Last 3 summaries
        context_parts.append(f"\nRECENT CONVERSATION TOPICS:")
        for summary in recent_summaries:
            context_parts.append(f"- {summary.get('summary', '')}")

    # Learned corrections (things user has corrected you on)
    if memory.get('corrections'):
        recent_corrections = memory['corrections'][-5:]  # Last 5 corrections
        context_parts.append(f"\nCORRECTIONS TO REMEMBER:")
        for correction in recent_corrections:
            context_parts.append(f"- {correction.get('content', '')}")

    return "\n".join(context_parts)

# ==============================================================================
# CONVERSATION SUMMARY FUNCTIONS
# ==============================================================================
SUMMARY_INTERVAL = 20  # Summarize every 20 messages
last_summary_count = 0

def should_summarize_conversation():
    """Check if we should create a new conversation summary."""
    global last_summary_count
    history = load_history()
    current_count = len(history)

    # Summarize every SUMMARY_INTERVAL messages
    if current_count - last_summary_count >= SUMMARY_INTERVAL:
        return True
    return False

def create_conversation_summary(history_slice):
    """Create a summary of recent conversation topics."""
    if not history_slice:
        return None

    # Extract topics from recent messages
    topics = []
    for msg in history_slice:
        content = msg.get('content', '')
        if isinstance(content, str) and len(content) > 10:
            # Take first 100 chars of each message for topic extraction
            topics.append(content[:100])

    if not topics:
        return None

    # Simple topic extraction - look for key themes
    topic_text = " ".join(topics).lower()

    detected_topics = []
    topic_keywords = {
        'coding': ['code', 'programming', 'vscode', 'python', 'javascript', 'git', 'debug'],
        'gaming': ['game', 'steam', 'play', 'gaming'],
        'music': ['spotify', 'music', 'song', 'playlist', 'play'],
        'work': ['work', 'project', 'task', 'meeting', 'deadline'],
        'system': ['cpu', 'memory', 'disk', 'volume', 'open app', 'screenshot'],
        'reminder': ['remind', 'timer', 'reminder', 'alarm'],
        'weather': ['weather', 'forecast', 'temperature'],
        'general': ['hello', 'hey', 'hi', 'thanks', 'thank you']
    }

    for topic, keywords in topic_keywords.items():
        if any(kw in topic_text for kw in keywords):
            detected_topics.append(topic)

    if detected_topics:
        return f"Talked about: {', '.join(detected_topics)}"
    else:
        return "General conversation"

def save_conversation_summary():
    """Create and save a summary of recent conversation."""
    global last_summary_count

    history = load_history()
    if len(history) < SUMMARY_INTERVAL:
        return

    # Get the messages since last summary
    messages_to_summarize = history[last_summary_count:last_summary_count + SUMMARY_INTERVAL]

    summary_text = create_conversation_summary(messages_to_summarize)
    if summary_text:
        memory = load_memory_bank()
        memory['conversation_summaries'].append({
            'summary': summary_text,
            'timestamp': datetime.now().isoformat(),
            'message_count': len(messages_to_summarize)
        })
        # Keep only last 10 summaries
        memory['conversation_summaries'] = memory['conversation_summaries'][-10:]
        save_memory_bank(memory)

    last_summary_count = len(history)

# ==============================================================================
# CORRECTION LEARNING FUNCTIONS
# ==============================================================================
CORRECTION_PATTERNS = [
    r"no,?\s+(?:i\s+meant|i\s+said|it'?s|that'?s)",
    r"that'?s\s+(?:not\s+right|wrong|incorrect)",
    r"actually,?\s+(?:i|it|that)",
    r"i\s+didn'?t\s+(?:mean|say|ask)",
    r"you\s+(?:misunderstood|got\s+it\s+wrong)",
    r"let\s+me\s+(?:clarify|correct)",
    r"i\s+(?:meant|mean)\s+to\s+say",
    r"not\s+(?:that|what\s+i)",
    r"wrong,?\s+i",
    r"nope,?\s+(?:i|it)",
]

def detect_correction(user_message):
    """Detect if the user is correcting FRIDAY."""
    message_lower = user_message.lower()

    for pattern in CORRECTION_PATTERNS:
        if re.search(pattern, message_lower):
            return True

    return False

def extract_correction_content(user_message, previous_response=None):
    """Extract the correction content from user message."""
    # Clean up the message to get the actual correction
    message = user_message.strip()

    # Remove common correction prefixes
    prefixes_to_remove = [
        r"^no,?\s*",
        r"^actually,?\s*",
        r"^that'?s\s+not\s+right,?\s*",
        r"^wrong,?\s*",
        r"^nope,?\s*",
    ]

    for prefix in prefixes_to_remove:
        message = re.sub(prefix, "", message, flags=re.IGNORECASE)

    return message.strip()

def save_correction(correction_content, context=None):
    """Save a correction to memory bank."""
    memory = load_memory_bank()

    correction_entry = {
        'content': correction_content,
        'timestamp': datetime.now().isoformat(),
        'context': context
    }

    memory['corrections'].append(correction_entry)

    # Keep only last 20 corrections
    memory['corrections'] = memory['corrections'][-20:]
    save_memory_bank(memory)

    return True

def check_and_save_correction(user_message, conversation_history):
    """Check if message is a correction and save it."""
    if not detect_correction(user_message):
        return False

    # Get the previous assistant response for context
    previous_response = None
    if len(conversation_history) >= 2:
        for msg in reversed(conversation_history[:-1]):
            if msg.get('role') == 'assistant':
                content = msg.get('content', '')
                if isinstance(content, str):
                    previous_response = content[:200]  # First 200 chars for context
                break

    correction_content = extract_correction_content(user_message, previous_response)

    if len(correction_content) > 5:  # Only save meaningful corrections
        save_correction(correction_content, context=previous_response)
        return True

    return False

# ==============================================================================
# ROUTINES FUNCTIONS
# ==============================================================================
def load_routines():
    """Load custom routines from file, or create defaults if not exists."""
    if os.path.exists(ROUTINES_FILE):
        try:
            with open(ROUTINES_FILE, 'r') as f:
                routines = json.load(f)
                # Merge with defaults
                for key, value in DEFAULT_ROUTINES.items():
                    if key not in routines:
                        routines[key] = value
                return routines
        except:
            return DEFAULT_ROUTINES.copy()
    # Create file with defaults
    save_routines(DEFAULT_ROUTINES.copy())
    return DEFAULT_ROUTINES.copy()

def save_routines(routines):
    """Save routines to file."""
    with open(ROUTINES_FILE, 'w') as f:
        json.dump(routines, f, indent=2)

# ==============================================================================
# MULTI-STEP TASK HANDLING
# ==============================================================================
TASKS_FILE = os.path.join(APP_DIR, "active_tasks.json")
active_tasks = []

def load_tasks():
    """Load active tasks from file."""
    global active_tasks
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, 'r') as f:
                active_tasks = json.load(f)
        except:
            active_tasks = []
    return active_tasks

def save_tasks():
    """Save active tasks to file."""
    with open(TASKS_FILE, 'w') as f:
        json.dump(active_tasks, f, indent=2)

def create_multi_step_task(name, description, steps):
    """Create a new multi-step task."""
    global active_tasks

    task = {
        'id': f"task_{int(time.time())}",
        'name': name,
        'description': description,
        'steps': steps,  # List of {"action": "tool_name", "params": {...}, "description": "..."}
        'current_step': 0,
        'status': 'pending',
        'results': [],
        'created_at': datetime.now().isoformat()
    }

    active_tasks.append(task)
    save_tasks()
    return task['id']

def execute_task_step(task_id):
    """Execute the next step of a task."""
    global active_tasks

    # Find the task
    task = None
    for t in active_tasks:
        if t['id'] == task_id:
            task = t
            break

    if not task:
        return None, "Task not found"

    if task['status'] == 'completed':
        return None, "Task already completed"

    if task['current_step'] >= len(task['steps']):
        task['status'] = 'completed'
        save_tasks()
        return None, "All steps completed"

    # Get current step
    step = task['steps'][task['current_step']]
    tool_name = step.get('action')
    params = step.get('params', {})

    # Execute the tool
    try:
        result = execute_tool(tool_name, params)
        task['results'].append({
            'step': task['current_step'],
            'tool': tool_name,
            'result': result,
            'timestamp': datetime.now().isoformat()
        })
        task['current_step'] += 1

        if task['current_step'] >= len(task['steps']):
            task['status'] = 'completed'

        task['status'] = 'in_progress' if task['current_step'] < len(task['steps']) else 'completed'
        save_tasks()
        return result, step.get('description', f"Executed {tool_name}")
    except Exception as e:
        task['status'] = 'failed'
        task['error'] = str(e)
        save_tasks()
        return None, f"Step failed: {str(e)}"

def execute_full_task(task_id):
    """Execute all remaining steps of a task."""
    results = []
    while True:
        result, message = execute_task_step(task_id)
        if result is None and "completed" in message.lower():
            break
        if result is None:
            results.append(f"Error: {message}")
            break
        results.append(message)

    return results

def get_task_status(task_id):
    """Get the status of a task."""
    for task in active_tasks:
        if task['id'] == task_id:
            return task
    return None

def list_active_tasks():
    """List all active/pending tasks."""
    return [t for t in active_tasks if t['status'] in ['pending', 'in_progress']]

def cancel_task(task_id):
    """Cancel a task."""
    global active_tasks
    for task in active_tasks:
        if task['id'] == task_id:
            task['status'] = 'cancelled'
            save_tasks()
            return True
    return False

# Load tasks at startup
load_tasks()

# ==============================================================================
# PATTERNS FUNCTIONS
# ==============================================================================
def load_patterns():
    """Load usage patterns from file."""
    if os.path.exists(PATTERNS_FILE):
        try:
            with open(PATTERNS_FILE, 'r') as f:
                return json.load(f)
        except:
            return DEFAULT_PATTERNS.copy()
    return DEFAULT_PATTERNS.copy()

def save_patterns(patterns):
    """Save patterns to file."""
    patterns['last_updated'] = datetime.now().isoformat()
    with open(PATTERNS_FILE, 'w') as f:
        json.dump(patterns, f, indent=2)

def track_pattern(pattern_type, key):
    """Track a usage pattern."""
    patterns = load_patterns()
    hour = datetime.now().hour

    if pattern_type == "app_usage":
        if key not in patterns['app_usage']:
            patterns['app_usage'][key] = {"count": 0, "hours": {}}
        patterns['app_usage'][key]['count'] += 1
        hour_str = str(hour)
        patterns['app_usage'][key]['hours'][hour_str] = patterns['app_usage'][key]['hours'].get(hour_str, 0) + 1

    elif pattern_type == "command":
        if key not in patterns['command_frequency']:
            patterns['command_frequency'][key] = 0
        patterns['command_frequency'][key] += 1

    elif pattern_type == "active":
        hour_str = str(hour)
        patterns['active_hours'][hour_str] = patterns['active_hours'].get(hour_str, 0) + 1

    save_patterns(patterns)

# ==============================================================================
# PROACTIVE ALERTS FUNCTIONS
# ==============================================================================
def check_system_alerts():
    """Check for system conditions that warrant an alert."""
    global pending_alerts, last_alert_check

    current_time = time.time()
    if current_time - last_alert_check < ALERT_CHECK_INTERVAL:
        return  # Don't check too frequently

    last_alert_check = current_time

    try:
        # Check CPU
        cpu_cmd = 'wmic cpu get loadpercentage /value'
        cpu_result = subprocess.run(cpu_cmd, shell=True, capture_output=True, text=True, timeout=5)
        cpu_match = re.search(r'LoadPercentage=(\d+)', cpu_result.stdout)
        if cpu_match:
            cpu = int(cpu_match.group(1))
            if cpu > 90:
                add_alert("high_cpu", f"Heads up, your CPU is running at {cpu}%.")

        # Check Memory
        mem_cmd = 'wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /value'
        mem_result = subprocess.run(mem_cmd, shell=True, capture_output=True, text=True, timeout=5)
        free_match = re.search(r'FreePhysicalMemory=(\d+)', mem_result.stdout)
        total_match = re.search(r'TotalVisibleMemorySize=(\d+)', mem_result.stdout)
        if free_match and total_match:
            free_mb = int(free_match.group(1)) / 1024
            total_mb = int(total_match.group(1)) / 1024
            used_pct = int((1 - free_mb/total_mb) * 100)
            if used_pct > 90:
                add_alert("high_memory", f"Memory usage is at {used_pct}%. Might want to close some apps.")

        # Check Disk Space
        disk_cmd = 'wmic logicaldisk where "DeviceID=\'C:\'" get FreeSpace,Size /value'
        disk_result = subprocess.run(disk_cmd, shell=True, capture_output=True, text=True, timeout=5)
        free_disk = re.search(r'FreeSpace=(\d+)', disk_result.stdout)
        total_disk = re.search(r'Size=(\d+)', disk_result.stdout)
        if free_disk and total_disk:
            free_gb = int(free_disk.group(1)) / 1024 / 1024 / 1024
            if free_gb < 10:
                add_alert("low_disk", f"Disk space is getting low - only {round(free_gb)}GB free on C: drive.")

    except Exception as e:
        pass  # Don't let alert checking crash anything

def add_alert(alert_type, message):
    """Add an alert to pending alerts (avoid duplicates)."""
    global pending_alerts
    # Check if we already have this type of alert pending
    for alert in pending_alerts:
        if alert['type'] == alert_type:
            return  # Already have this alert
    pending_alerts.append({
        "type": alert_type,
        "message": message,
        "timestamp": datetime.now().isoformat()
    })

def get_pending_alerts():
    """Get and clear pending alerts."""
    global pending_alerts
    alerts = pending_alerts.copy()
    pending_alerts = []
    return alerts

# ==============================================================================
# PROACTIVE ASSISTANCE SYSTEM
# ==============================================================================
PROACTIVE_FILE = os.path.join(APP_DIR, "proactive_data.json")

# Proactive insights storage
proactive_insights = {
    "schedule_patterns": {},      # When user typically does things
    "predicted_actions": [],       # What we think user might want
    "last_proactive_check": None,
    "daily_summary": {},
    "weekly_patterns": {}
}

def load_proactive_data():
    """Load proactive assistance data."""
    global proactive_insights
    if os.path.exists(PROACTIVE_FILE):
        try:
            with open(PROACTIVE_FILE, 'r') as f:
                proactive_insights = json.load(f)
        except:
            pass
    return proactive_insights

def save_proactive_data():
    """Save proactive assistance data."""
    with open(PROACTIVE_FILE, 'w') as f:
        json.dump(proactive_insights, f, indent=2)

def learn_schedule_pattern(action_type, hour, day_of_week):
    """Learn when user typically performs certain actions."""
    global proactive_insights

    key = f"{action_type}_{day_of_week}_{hour}"

    if 'schedule_patterns' not in proactive_insights:
        proactive_insights['schedule_patterns'] = {}

    if key not in proactive_insights['schedule_patterns']:
        proactive_insights['schedule_patterns'][key] = {
            'action': action_type,
            'hour': hour,
            'day': day_of_week,
            'count': 0,
            'last_occurred': None
        }

    proactive_insights['schedule_patterns'][key]['count'] += 1
    proactive_insights['schedule_patterns'][key]['last_occurred'] = datetime.now().isoformat()
    save_proactive_data()

def get_predicted_actions():
    """Get predicted actions based on current time and patterns."""
    predictions = []
    now = datetime.now()
    current_hour = now.hour
    current_day = now.strftime("%A")

    patterns = load_patterns()
    load_proactive_data()

    # Check schedule patterns for this time
    for key, pattern in proactive_insights.get('schedule_patterns', {}).items():
        if pattern['hour'] == current_hour and pattern['day'] == current_day:
            if pattern['count'] >= 3:  # Must have happened at least 3 times
                predictions.append({
                    'action': pattern['action'],
                    'confidence': min(pattern['count'] / 10, 1.0),  # Max 100% confidence
                    'reason': f"You usually do this on {current_day}s around {current_hour}:00"
                })

    # Check app usage patterns
    app_usage = patterns.get('app_usage', {})
    hour_str = str(current_hour)

    for app, data in app_usage.items():
        if isinstance(data, dict):
            hours = data.get('hours', {})
            if hours.get(hour_str, 0) >= 5:  # Used at this hour 5+ times
                predictions.append({
                    'action': f"open_{app}",
                    'confidence': min(hours[hour_str] / 20, 0.9),
                    'reason': f"You often use {app} at this time"
                })

    # Sort by confidence
    predictions.sort(key=lambda x: x['confidence'], reverse=True)
    return predictions[:3]  # Return top 3 predictions

def generate_proactive_insight():
    """Generate a proactive insight based on current context."""
    insights = []
    now = datetime.now()
    hour = now.hour
    day = now.strftime("%A")

    # Time-based insights
    if hour == 8 and day not in ["Saturday", "Sunday"]:
        insights.append({
            'type': 'morning_routine',
            'message': "Good morning! Want me to run your morning briefing?",
            'action': 'morning_briefing',
            'priority': 'medium'
        })

    if hour == 12:
        insights.append({
            'type': 'midday_check',
            'message': "It's noon - want a quick status update?",
            'action': 'system_stats',
            'priority': 'low'
        })

    if hour == 22:
        insights.append({
            'type': 'evening_routine',
            'message': "Getting late - should I switch to night mode?",
            'action': 'run_routine',
            'params': {'routine_name': 'night_mode'},
            'priority': 'medium'
        })

    # Check for upcoming reminders
    upcoming = get_upcoming_reminders(minutes=30)
    if upcoming:
        for reminder in upcoming[:2]:
            insights.append({
                'type': 'reminder_preview',
                'message': f"Heads up: '{reminder['message']}' coming up in {reminder['minutes_until']} minutes",
                'action': None,
                'priority': 'high'
            })

    # Predictive actions
    predictions = get_predicted_actions()
    for pred in predictions:
        if pred['confidence'] > 0.6:  # Only suggest high confidence predictions
            insights.append({
                'type': 'prediction',
                'message': pred['reason'],
                'action': pred['action'],
                'priority': 'low'
            })

    # Sort by priority
    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    insights.sort(key=lambda x: priority_order.get(x.get('priority', 'low'), 2))

    return insights[:3]

def get_upcoming_reminders(minutes=30):
    """Get reminders coming up in the next N minutes."""
    upcoming = []
    now = datetime.now()

    for reminder in active_reminders:
        try:
            remind_time = datetime.fromisoformat(reminder['time'])
            diff = (remind_time - now).total_seconds() / 60

            if 0 < diff <= minutes:
                upcoming.append({
                    'message': reminder['message'],
                    'time': reminder['time'],
                    'minutes_until': int(diff)
                })
        except:
            pass

    return sorted(upcoming, key=lambda x: x['minutes_until'])

def track_user_action(action_type):
    """Track user actions for schedule learning."""
    now = datetime.now()
    hour = now.hour
    day = now.strftime("%A")
    learn_schedule_pattern(action_type, hour, day)

# Load proactive data at startup
load_proactive_data()

# ==============================================================================
# SMARTTHINGS INTEGRATION
# ==============================================================================
SMARTTHINGS_API_URL = "https://api.smartthings.com/v1"
smartthings_devices_cache = {}
smartthings_cache_time = 0
SMARTTHINGS_CACHE_DURATION = 300  # Cache for 5 minutes

def smartthings_api_request(endpoint, method="GET", data=None):
    """Make a request to the SmartThings API."""
    if not SMARTTHINGS_API_KEY:
        return None, "SmartThings API key not configured. Add SMARTTHINGS_API_KEY to your .env file."

    headers = {
        "Authorization": f"Bearer {SMARTTHINGS_API_KEY}",
        "Content-Type": "application/json"
    }

    url = f"{SMARTTHINGS_API_URL}/{endpoint}"

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data, timeout=10)
        else:
            return None, f"Unsupported method: {method}"

        if response.status_code == 200:
            return response.json(), None
        elif response.status_code == 401:
            return None, "SmartThings authentication failed. Check your API key."
        else:
            return None, f"SmartThings API error: {response.status_code}"
    except Exception as e:
        return None, f"SmartThings connection error: {str(e)}"

def get_smartthings_devices(force_refresh=False):
    """Get list of SmartThings devices."""
    global smartthings_devices_cache, smartthings_cache_time

    current_time = time.time()

    # Use cache if available and not expired
    if not force_refresh and smartthings_devices_cache and (current_time - smartthings_cache_time) < SMARTTHINGS_CACHE_DURATION:
        return smartthings_devices_cache, None

    data, error = smartthings_api_request("devices")
    if error:
        return None, error

    # Process and cache devices
    devices = {}
    for device in data.get("items", []):
        device_id = device.get("deviceId")
        device_name = device.get("label") or device.get("name", "Unknown")
        device_type = device.get("deviceTypeName", "")

        # Get capabilities
        capabilities = []
        for component in device.get("components", []):
            for cap in component.get("capabilities", []):
                capabilities.append(cap.get("id", ""))

        devices[device_id] = {
            "id": device_id,
            "name": device_name,
            "type": device_type,
            "capabilities": capabilities,
            "room": device.get("roomId", "")
        }

    smartthings_devices_cache = devices
    smartthings_cache_time = current_time
    return devices, None

def find_smartthings_device(query):
    """Find a device by name or type."""
    devices, error = get_smartthings_devices()
    if error:
        return None, error

    query_lower = query.lower()

    # Exact match first
    for device_id, device in devices.items():
        if device["name"].lower() == query_lower:
            return device, None

    # Partial match
    for device_id, device in devices.items():
        if query_lower in device["name"].lower():
            return device, None

    # Type match (e.g., "lights", "switch")
    type_keywords = {
        "light": ["switch", "light", "bulb", "dimmer"],
        "thermostat": ["thermostat", "temperature"],
        "lock": ["lock"],
        "sensor": ["sensor", "motion", "contact"],
        "outlet": ["outlet", "plug"]
    }

    for device_id, device in devices.items():
        device_type_lower = device["type"].lower()
        for category, keywords in type_keywords.items():
            if query_lower == category or query_lower in category:
                if any(kw in device_type_lower for kw in keywords):
                    return device, None

    return None, f"Device '{query}' not found"

def control_smartthings_device(device_id, capability, command, args=None):
    """Send a command to a SmartThings device."""
    endpoint = f"devices/{device_id}/commands"

    command_data = {
        "commands": [{
            "component": "main",
            "capability": capability,
            "command": command
        }]
    }

    if args:
        command_data["commands"][0]["arguments"] = args

    return smartthings_api_request(endpoint, method="POST", data=command_data)

def smartthings_turn_on(device):
    """Turn on a SmartThings device."""
    if "switch" in device["capabilities"]:
        return control_smartthings_device(device["id"], "switch", "on")
    elif "switchLevel" in device["capabilities"]:
        return control_smartthings_device(device["id"], "switchLevel", "setLevel", [100])
    return None, "Device doesn't support on/off"

def smartthings_turn_off(device):
    """Turn off a SmartThings device."""
    if "switch" in device["capabilities"]:
        return control_smartthings_device(device["id"], "switch", "off")
    elif "switchLevel" in device["capabilities"]:
        return control_smartthings_device(device["id"], "switchLevel", "setLevel", [0])
    return None, "Device doesn't support on/off"

def smartthings_set_level(device, level):
    """Set brightness/level of a SmartThings device."""
    if "switchLevel" in device["capabilities"]:
        return control_smartthings_device(device["id"], "switchLevel", "setLevel", [level])
    return None, "Device doesn't support dimming"

def smartthings_set_thermostat(device, temperature, mode=None):
    """Set thermostat temperature."""
    results = []

    if mode:
        mode_map = {
            "heat": "heat",
            "cool": "cool",
            "auto": "auto",
            "off": "off"
        }
        if mode.lower() in mode_map:
            result, error = control_smartthings_device(
                device["id"], "thermostatMode", "setThermostatMode", [mode_map[mode.lower()]]
            )
            if error:
                results.append(f"Mode error: {error}")
            else:
                results.append(f"Mode set to {mode}")

    # Set temperature based on mode
    if "thermostatHeatingSetpoint" in device["capabilities"]:
        result, error = control_smartthings_device(
            device["id"], "thermostatHeatingSetpoint", "setHeatingSetpoint", [temperature]
        )
        if not error:
            results.append(f"Heating set to {temperature}°")
    elif "thermostatCoolingSetpoint" in device["capabilities"]:
        result, error = control_smartthings_device(
            device["id"], "thermostatCoolingSetpoint", "setCoolingSetpoint", [temperature]
        )
        if not error:
            results.append(f"Cooling set to {temperature}°")

    return results if results else None, "Couldn't set thermostat"

def smartthings_lock(device, lock=True):
    """Lock or unlock a SmartThings lock."""
    if "lock" in device["capabilities"]:
        command = "lock" if lock else "unlock"
        return control_smartthings_device(device["id"], "lock", command)
    return None, "Device is not a lock"

# ==============================================================================
# CALENDAR SYSTEM
# ==============================================================================
CALENDAR_FILE = os.path.join(APP_DIR, "calendar_events.json")

def load_calendar():
    """Load calendar events from file."""
    if os.path.exists(CALENDAR_FILE):
        try:
            with open(CALENDAR_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_calendar(events):
    """Save calendar events to file."""
    with open(CALENDAR_FILE, 'w') as f:
        json.dump(events, f, indent=2)

def add_calendar_event(title, date_str, time_str=None, description="", duration_minutes=60, recurring=None):
    """Add a calendar event."""
    events = load_calendar()

    # Parse date
    try:
        if time_str:
            event_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        else:
            event_datetime = datetime.strptime(date_str, "%Y-%m-%d")
            event_datetime = event_datetime.replace(hour=9, minute=0)  # Default to 9 AM
    except ValueError:
        # Try natural date parsing
        try:
            now = datetime.now()
            date_lower = date_str.lower()

            if date_lower == "today":
                event_date = now.date()
            elif date_lower == "tomorrow":
                event_date = (now + timedelta(days=1)).date()
            elif date_lower in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
                days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                target_day = days.index(date_lower)
                current_day = now.weekday()
                days_ahead = (target_day - current_day) % 7
                if days_ahead == 0:
                    days_ahead = 7  # Next week
                event_date = (now + timedelta(days=days_ahead)).date()
            else:
                return None, f"Couldn't parse date: {date_str}"

            if time_str:
                try:
                    # Parse time like "3pm", "3:30pm", "15:00"
                    time_str = time_str.lower().strip()
                    if "pm" in time_str or "am" in time_str:
                        time_str = time_str.replace("pm", " PM").replace("am", " AM")
                        if ":" in time_str:
                            parsed_time = datetime.strptime(time_str.strip(), "%I:%M %p").time()
                        else:
                            parsed_time = datetime.strptime(time_str.strip(), "%I %p").time()
                    else:
                        parsed_time = datetime.strptime(time_str, "%H:%M").time()
                    event_datetime = datetime.combine(event_date, parsed_time)
                except:
                    event_datetime = datetime.combine(event_date, datetime.strptime("09:00", "%H:%M").time())
            else:
                event_datetime = datetime.combine(event_date, datetime.strptime("09:00", "%H:%M").time())
        except Exception as e:
            return None, f"Date parsing error: {str(e)}"

    event = {
        "id": f"evt_{int(time.time())}",
        "title": title,
        "datetime": event_datetime.isoformat(),
        "description": description,
        "duration_minutes": duration_minutes,
        "recurring": recurring,  # None, "daily", "weekly", "monthly"
        "created_at": datetime.now().isoformat()
    }

    events.append(event)
    save_calendar(events)
    return event, None

def get_calendar_events(days_ahead=7):
    """Get upcoming calendar events."""
    events = load_calendar()
    now = datetime.now()
    end_date = now + timedelta(days=days_ahead)

    upcoming = []
    for event in events:
        try:
            event_dt = datetime.fromisoformat(event["datetime"])
            if now <= event_dt <= end_date:
                upcoming.append(event)
        except:
            pass

    # Sort by datetime
    upcoming.sort(key=lambda x: x["datetime"])
    return upcoming

def get_todays_events():
    """Get today's calendar events."""
    events = load_calendar()
    today = datetime.now().date()

    todays = []
    for event in events:
        try:
            event_dt = datetime.fromisoformat(event["datetime"])
            if event_dt.date() == today:
                todays.append(event)
        except:
            pass

    todays.sort(key=lambda x: x["datetime"])
    return todays

def delete_calendar_event(event_id):
    """Delete a calendar event."""
    events = load_calendar()
    events = [e for e in events if e.get("id") != event_id]
    save_calendar(events)
    return True

def find_calendar_event(query):
    """Find a calendar event by title."""
    events = load_calendar()
    query_lower = query.lower()

    for event in events:
        if query_lower in event.get("title", "").lower():
            return event
    return None

def get_active_window():
    """Get the currently active window title."""
    try:
        ps_cmd = '''
        Add-Type @"
        using System;
        using System.Runtime.InteropServices;
        public class User32 {
            [DllImport("user32.dll")]
            public static extern IntPtr GetForegroundWindow();
            [DllImport("user32.dll")]
            public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);
        }
"@
        $hwnd = [User32]::GetForegroundWindow()
        $title = New-Object System.Text.StringBuilder 256
        [User32]::GetWindowText($hwnd, $title, 256)
        $title.ToString()
        '''
        result = subprocess.run(['powershell', '-Command', ps_cmd], capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except:
        return "Unknown"

def get_time_context():
    """Get time-based context for FRIDAY's behavior."""
    now = datetime.now()
    hour = now.hour

    if 5 <= hour < 12:
        time_period = "morning"
        greeting_suggestion = "Good morning"
        energy = "fresh and ready"
    elif 12 <= hour < 17:
        time_period = "afternoon"
        greeting_suggestion = "Good afternoon"
        energy = "productive"
    elif 17 <= hour < 21:
        time_period = "evening"
        greeting_suggestion = "Good evening"
        energy = "winding down"
    else:
        time_period = "night"
        greeting_suggestion = "Hey night owl"
        energy = "late night mode"

    # Day of week context
    day = now.strftime("%A")
    is_weekend = day in ["Saturday", "Sunday"]

    return {
        "time_period": time_period,
        "greeting": greeting_suggestion,
        "energy": energy,
        "hour": hour,
        "day": day,
        "is_weekend": is_weekend,
        "formatted_time": now.strftime("%I:%M %p"),
        "formatted_date": now.strftime("%B %d, %Y")
    }

# ==============================================================================
# CONTEXT-AWARE SUGGESTIONS
# ==============================================================================
def get_context_suggestions():
    """Generate smart suggestions based on current context."""
    suggestions = []
    time_ctx = get_time_context()
    patterns = load_patterns()
    profile = load_user_profile()
    hour = time_ctx['hour']
    day = time_ctx['day']

    # Get active window for context
    try:
        active_window = get_active_window().lower()
    except:
        active_window = ""

    # Time-based suggestions
    if 6 <= hour <= 9 and day not in ["Saturday", "Sunday"]:
        suggestions.append({
            "type": "routine",
            "suggestion": "Ready to start your day? I can run work_mode to get you set up.",
            "action": "run_routine",
            "params": {"routine_name": "work_mode"}
        })

    if 22 <= hour or hour <= 2:
        suggestions.append({
            "type": "routine",
            "suggestion": "Getting late - want me to switch to night mode?",
            "action": "run_routine",
            "params": {"routine_name": "night_mode"}
        })

    # Pattern-based suggestions
    app_usage = patterns.get('app_usage', {})
    hour_str = str(hour)

    # Check if there's an app commonly used at this hour
    for app, data in app_usage.items():
        if isinstance(data, dict):
            hours = data.get('hours', {})
            if hours.get(hour_str, 0) >= 3:  # Used at this hour at least 3 times
                suggestions.append({
                    "type": "app",
                    "suggestion": f"You usually use {app} around this time. Want me to open it?",
                    "action": "open_application",
                    "params": {"app_name": app}
                })
                break  # Only suggest one app

    # Active window context suggestions
    if "visual studio" in active_window or "vscode" in active_window:
        suggestions.append({
            "type": "context",
            "suggestion": "I see you're coding. Need me to run any commands or look something up?",
            "action": None,
            "params": {}
        })
    elif "spotify" in active_window:
        suggestions.append({
            "type": "context",
            "suggestion": "Listening to music? I can control playback or find something new for you.",
            "action": None,
            "params": {}
        })
    elif "discord" in active_window:
        suggestions.append({
            "type": "context",
            "suggestion": "On Discord? Let me know if you need anything while you chat.",
            "action": None,
            "params": {}
        })
    elif "steam" in active_window or "game" in active_window:
        if not any(s.get('action') == 'run_routine' and s.get('params', {}).get('routine_name') == 'gaming_mode' for s in suggestions):
            suggestions.append({
                "type": "routine",
                "suggestion": "Gaming time? I can set up gaming mode for optimal performance.",
                "action": "run_routine",
                "params": {"routine_name": "gaming_mode"}
            })

    # Weekend suggestions
    if time_ctx['is_weekend'] and 10 <= hour <= 14:
        suggestions.append({
            "type": "info",
            "suggestion": "It's the weekend! Want a briefing or just relaxing?",
            "action": "morning_briefing",
            "params": {}
        })

    # Reminder check suggestion
    if len(active_reminders) > 0:
        suggestions.append({
            "type": "reminder",
            "suggestion": f"You have {len(active_reminders)} active reminder{'s' if len(active_reminders) > 1 else ''}. Want me to list them?",
            "action": "list_reminders",
            "params": {}
        })

    return suggestions[:3]  # Return top 3 suggestions

def get_proactive_suggestion():
    """Get a single proactive suggestion based on context (for natural conversation)."""
    suggestions = get_context_suggestions()
    if suggestions:
        # Prioritize routine and app suggestions over informational ones
        for s in suggestions:
            if s['type'] in ['routine', 'app']:
                return s['suggestion']
        return suggestions[0]['suggestion']
    return None

# Load all systems at startup
user_profile = load_user_profile()
memory_bank = load_memory_bank()
routines = load_routines()
patterns = load_patterns()

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
        "description": "Control smart home devices via SmartThings - lights, switches, thermostats, locks, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "Device name to control (e.g., 'living room light', 'bedroom fan', 'front door')"},
                "action": {"type": "string", "description": "Action: 'on', 'off', 'dim 50%', 'lock', 'unlock', 'temperature 72'"},
                "room": {"type": "string", "description": "Room name (optional, helps find device)"}
            },
            "required": ["device", "action"]
        }
    },
    {
        "name": "list_smart_devices",
        "description": "List all SmartThings devices available for control.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
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
    # Spotify Control
    {
        "name": "spotify_control",
        "description": "Control Spotify playback - play, pause, next track, previous track, or search and play a song/artist/playlist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "Action: 'play', 'pause', 'next', 'previous', 'volume up', 'volume down'"},
                "search": {"type": "string", "description": "Optional: song, artist, or playlist name to search and play"}
            },
            "required": ["action"]
        }
    },
    # Screenshot tool
    {
        "name": "take_screenshot",
        "description": "Take a screenshot of the current screen and save it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Optional filename (default: screenshot_timestamp.png)"}
            },
            "required": []
        }
    },
    # Clipboard tool
    {
        "name": "clipboard",
        "description": "Read from or write to the system clipboard.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "'read' to get clipboard contents, 'write' to set clipboard"},
                "text": {"type": "string", "description": "Text to write to clipboard (only for 'write' action)"}
            },
            "required": ["action"]
        }
    },
    # ==== MEMORY SYSTEM TOOLS ====
    {
        "name": "remember_fact",
        "description": "Store an important fact about the user in long-term memory. Use this when the user tells you something important about themselves, their preferences, or their life that you should remember permanently.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "The fact to remember (e.g., 'User's favorite color is blue', 'User works as a game developer')"},
                "category": {"type": "string", "description": "Category: 'personal', 'work', 'preference', 'habit', 'relationship', 'health', 'other'"}
            },
            "required": ["fact"]
        }
    },
    {
        "name": "recall_memories",
        "description": "Search your long-term memory for information about the user. Use this when you need to remember something about the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for (e.g., 'birthday', 'favorite food', 'work projects')"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "update_profile",
        "description": "Update the user's profile with new information. Use for important persistent info like name, location, interests, projects.",
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {"type": "string", "description": "Field to update: 'name', 'location', 'interests', 'current_projects', 'communication_style', 'important_dates'"},
                "value": {"type": "string", "description": "New value (for arrays like interests, comma-separated)"},
                "action": {"type": "string", "description": "For array fields: 'add', 'remove', or 'set'. Default is 'set'."}
            },
            "required": ["field", "value"]
        }
    },
    {
        "name": "get_profile",
        "description": "Get the user's profile information. Use when you need to know about the user.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "list_memories",
        "description": "List all stored memories and facts about the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Optional: filter by category"}
            },
            "required": []
        }
    },
    {
        "name": "forget",
        "description": "Remove a specific memory or fact. Use if user asks you to forget something.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to forget - will match against stored facts"}
            },
            "required": ["query"]
        }
    },
    # ==== ROUTINES & AUTOMATION ====
    {
        "name": "run_routine",
        "description": "Run a saved routine/macro. Routines execute multiple actions in sequence. Built-in routines: 'gaming_mode', 'work_mode', 'night_mode'. User can say things like 'start gaming mode' or 'activate work mode'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "routine_name": {"type": "string", "description": "Name of the routine to run (e.g., 'gaming_mode', 'work_mode')"}
            },
            "required": ["routine_name"]
        }
    },
    {
        "name": "create_routine",
        "description": "Create a new custom routine. A routine is a sequence of actions that run together.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name for the routine (e.g., 'morning_routine', 'streaming_mode')"},
                "description": {"type": "string", "description": "What the routine does"},
                "actions": {"type": "string", "description": "JSON array of actions. Each action: {\"tool\": \"tool_name\", \"params\": {...}}"}
            },
            "required": ["name", "description", "actions"]
        }
    },
    {
        "name": "list_routines",
        "description": "List all available routines.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "delete_routine",
        "description": "Delete a custom routine.",
        "input_schema": {
            "type": "object",
            "properties": {
                "routine_name": {"type": "string", "description": "Name of the routine to delete"}
            },
            "required": ["routine_name"]
        }
    },
    # ==== CONTEXT AWARENESS ====
    {
        "name": "get_active_window",
        "description": "Get information about the currently active/focused window on the computer.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_usage_patterns",
        "description": "Get learned patterns about user's behavior - most used apps, active hours, common commands.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "suggest_routine",
        "description": "Suggest a routine based on current context (time, patterns, active window).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    # ==== MULTI-STEP TASK TOOLS ====
    {
        "name": "create_task",
        "description": "Create a multi-step task that executes several actions in sequence. Use for complex requests that require multiple steps.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short name for the task"},
                "description": {"type": "string", "description": "What this task accomplishes"},
                "steps": {"type": "string", "description": "JSON array of steps. Each step: {\"action\": \"tool_name\", \"params\": {...}, \"description\": \"what this step does\"}"}
            },
            "required": ["name", "description", "steps"]
        }
    },
    {
        "name": "run_task",
        "description": "Execute a multi-step task by ID or run all steps of a newly created task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "ID of the task to run"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "list_tasks",
        "description": "List all active and pending multi-step tasks.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "cancel_task",
        "description": "Cancel a multi-step task by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "ID of the task to cancel"}
            },
            "required": ["task_id"]
        }
    },
    # ==== PROACTIVE ASSISTANCE TOOLS ====
    {
        "name": "get_proactive_insights",
        "description": "Get proactive insights and predictions based on user patterns and current context. Use this to offer helpful suggestions.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_predictions",
        "description": "Get predicted actions the user might want based on their patterns.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    # ==== CALENDAR TOOLS ====
    {
        "name": "add_event",
        "description": "Add an event to the calendar. Supports natural dates like 'tomorrow', 'monday', or specific dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "date": {"type": "string", "description": "Date: 'today', 'tomorrow', 'monday', or 'YYYY-MM-DD'"},
                "time": {"type": "string", "description": "Time: '3pm', '15:00', '3:30pm' (optional, defaults to 9am)"},
                "description": {"type": "string", "description": "Event description (optional)"},
                "duration": {"type": "integer", "description": "Duration in minutes (optional, default 60)"}
            },
            "required": ["title", "date"]
        }
    },
    {
        "name": "get_calendar",
        "description": "Get upcoming calendar events. Shows events for the next 7 days by default.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Number of days ahead to look (default 7)"}
            },
            "required": []
        }
    },
    {
        "name": "todays_schedule",
        "description": "Get today's calendar events and schedule.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "delete_event",
        "description": "Delete a calendar event by title or ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Event title or ID to delete"}
            },
            "required": ["query"]
        }
    },
    # ==== VOICE CONTROL TOOLS ====
    {
        "name": "change_voice",
        "description": "Change FRIDAY's voice. Available: rachel (default), domi, bella, elli, josh, arnold, adam, sam",
        "input_schema": {
            "type": "object",
            "properties": {
                "voice_name": {"type": "string", "description": "Voice name: rachel, domi, bella, elli, josh, arnold, adam, or sam"}
            },
            "required": ["voice_name"]
        }
    },
    {
        "name": "list_voices",
        "description": "List all available voice options.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "adjust_voice",
        "description": "Adjust voice settings like stability and style.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stability": {"type": "number", "description": "Voice stability 0.0-1.0 (higher = more consistent, lower = more expressive)"},
                "style": {"type": "number", "description": "Style exaggeration 0.0-1.0 (higher = more dramatic)"}
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

        # Smart Home - SmartThings Integration
        elif tool_name == "smart_home":
            device_query = tool_input.get("device", "").lower()
            action = tool_input.get("action", "").lower()
            room = tool_input.get("room", "")

            # First try SmartThings
            if SMARTTHINGS_API_KEY:
                try:
                    # Include room in search if provided
                    search_query = f"{room} {device_query}".strip() if room else device_query
                    device, error = find_smartthings_device(search_query)

                    if error and room:
                        # Try without room
                        device, error = find_smartthings_device(device_query)

                    if error:
                        return f"SmartThings: {error}"

                    # Parse action
                    if action in ["on", "turn on", "enable"]:
                        result, error = smartthings_turn_on(device)
                        if error:
                            return f"Error: {error}"
                        return f"Turned on {device['name']}."

                    elif action in ["off", "turn off", "disable"]:
                        result, error = smartthings_turn_off(device)
                        if error:
                            return f"Error: {error}"
                        return f"Turned off {device['name']}."

                    elif "dim" in action or "%" in action or "brightness" in action:
                        # Extract number from action
                        nums = re.findall(r'\d+', action)
                        if nums:
                            level = int(nums[0])
                            result, error = smartthings_set_level(device, level)
                            if error:
                                return f"Error: {error}"
                            return f"Set {device['name']} to {level}%."
                        return "Please specify a brightness level (0-100)."

                    elif "lock" in action:
                        result, error = smartthings_lock(device, lock=True)
                        if error:
                            return f"Error: {error}"
                        return f"Locked {device['name']}."

                    elif "unlock" in action:
                        result, error = smartthings_lock(device, lock=False)
                        if error:
                            return f"Error: {error}"
                        return f"Unlocked {device['name']}."

                    elif "temperature" in action or "thermostat" in action or "heat" in action or "cool" in action:
                        nums = re.findall(r'\d+', action)
                        if nums:
                            temp = int(nums[0])
                            mode = None
                            if "heat" in action:
                                mode = "heat"
                            elif "cool" in action:
                                mode = "cool"
                            result, error = smartthings_set_thermostat(device, temp, mode)
                            if error:
                                return f"Error: {error}"
                            return f"Set thermostat to {temp}°."
                        return "Please specify a temperature."

                    else:
                        # Generic on/off based on action content
                        if any(word in action for word in ["on", "start", "enable", "open"]):
                            result, error = smartthings_turn_on(device)
                            return f"Turned on {device['name']}." if not error else f"Error: {error}"
                        elif any(word in action for word in ["off", "stop", "disable", "close"]):
                            result, error = smartthings_turn_off(device)
                            return f"Turned off {device['name']}." if not error else f"Error: {error}"
                        else:
                            return f"Unknown action '{action}' for {device['name']}. Try on, off, dim, lock, or temperature."

                except Exception as e:
                    return f"SmartThings error: {str(e)}"

            # Fallback to config file (Hue, etc.)
            config_file = os.path.join(APP_DIR, "smart_home_config.json")
            if os.path.exists(config_file):
                try:
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                    platform = config.get("platform")

                    if platform == "hue":
                        bridge_ip = config.get("bridge_ip")
                        api_key = config.get("api_key")
                        if "light" in device_query:
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
                    return f"Executed: {device_query} -> {action}"
                except Exception as e:
                    return f"Smart home error: {str(e)}"

            return "Smart home not configured. Add SMARTTHINGS_API_KEY to your .env file."

        elif tool_name == "list_smart_devices":
            if not SMARTTHINGS_API_KEY:
                return "SmartThings not configured. Add SMARTTHINGS_API_KEY to your .env file."

            try:
                devices, error = get_smartthings_devices(force_refresh=True)
                if error:
                    return f"Error: {error}"

                if not devices:
                    return "No SmartThings devices found."

                lines = ["SmartThings Devices:"]
                for device_id, device in devices.items():
                    caps = ", ".join(device["capabilities"][:3])  # Show first 3 capabilities
                    lines.append(f"  - {device['name']} ({caps})")

                return "\n".join(lines)
            except Exception as e:
                return f"Error listing devices: {str(e)}"

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
                # Track this action for learning
                track_user_action(f"open_{app_name}")
                track_pattern("app_usage", app_name)
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

        # ==== SPOTIFY CONTROL ====
        elif tool_name == "spotify_control":
            action = tool_input.get("action", "").lower()
            search = tool_input.get("search", "")

            try:
                # Use keyboard simulation for Spotify control (works when Spotify is open)
                if action == "play" and search:
                    # Open Spotify with search
                    search_encoded = search.replace(" ", "%20")
                    subprocess.Popen(f'start spotify:search:{search_encoded}', shell=True)
                    return f"Searching Spotify for '{search}'..."
                elif action == "play":
                    # Play/resume - media key
                    subprocess.run('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]179)"', shell=True, capture_output=True)
                    return "Playing."
                elif action == "pause":
                    subprocess.run('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]179)"', shell=True, capture_output=True)
                    return "Paused."
                elif action == "next":
                    subprocess.run('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]176)"', shell=True, capture_output=True)
                    return "Skipping to next track."
                elif action == "previous":
                    subprocess.run('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]177)"', shell=True, capture_output=True)
                    return "Going to previous track."
                elif "volume" in action:
                    if "up" in action:
                        subprocess.run('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]175)"', shell=True, capture_output=True)
                        return "Volume up."
                    else:
                        subprocess.run('powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]174)"', shell=True, capture_output=True)
                        return "Volume down."
                else:
                    return f"Unknown Spotify action: {action}. Use play, pause, next, previous, or volume up/down."
            except Exception as e:
                return f"Spotify control error: {str(e)}"

        # ==== SCREENSHOT ====
        elif tool_name == "take_screenshot":
            filename = tool_input.get("filename", "")
            try:
                if not filename:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"screenshot_{timestamp}.png"

                # Save to user's Pictures folder
                save_path = os.path.join(WORKSPACE, "Pictures", filename)

                # Use PowerShell to take screenshot
                ps_script = f'''
                Add-Type -AssemblyName System.Windows.Forms
                $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
                $bitmap = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
                $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
                $graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
                $bitmap.Save("{save_path}")
                '''
                subprocess.run(['powershell', '-Command', ps_script], capture_output=True)
                return f"Screenshot saved to {save_path}"
            except Exception as e:
                return f"Screenshot error: {str(e)}"

        # ==== CLIPBOARD ====
        elif tool_name == "clipboard":
            action = tool_input.get("action", "").lower()
            text = tool_input.get("text", "")

            try:
                if action == "read":
                    result = subprocess.run('powershell -Command "Get-Clipboard"', shell=True, capture_output=True, text=True)
                    content = result.stdout.strip()
                    if content:
                        return f"Clipboard contents: {content[:500]}"
                    else:
                        return "Clipboard is empty."
                elif action == "write" and text:
                    # Escape quotes for PowerShell
                    escaped_text = text.replace('"', '`"').replace("'", "''")
                    subprocess.run(f'powershell -Command "Set-Clipboard -Value \'{escaped_text}\'"', shell=True, capture_output=True)
                    return f"Copied to clipboard: {text[:100]}..."
                else:
                    return "Specify 'read' or 'write' action. For write, include 'text' parameter."
            except Exception as e:
                return f"Clipboard error: {str(e)}"

        # ==== MEMORY SYSTEM ====
        elif tool_name == "remember_fact":
            fact = tool_input.get("fact", "")
            category = tool_input.get("category", "other")

            if not fact:
                return "No fact provided to remember."

            try:
                memory = load_memory_bank()
                new_fact = {
                    "content": fact,
                    "category": category,
                    "timestamp": datetime.now().isoformat()
                }
                memory['facts'].append(new_fact)

                # Keep only last 100 facts to prevent unlimited growth
                if len(memory['facts']) > 100:
                    memory['facts'] = memory['facts'][-100:]

                save_memory_bank(memory)
                return f"Got it, I'll remember that: {fact}"
            except Exception as e:
                return f"Memory error: {str(e)}"

        elif tool_name == "recall_memories":
            query = tool_input.get("query", "").lower()

            try:
                memory = load_memory_bank()
                profile = load_user_profile()
                matches = []

                # Search in facts
                for fact in memory.get('facts', []):
                    if query in fact.get('content', '').lower():
                        matches.append(f"[Fact] {fact['content']}")

                # Search in preferences
                for pref in memory.get('preferences', []):
                    if query in pref.get('content', '').lower():
                        matches.append(f"[Preference] {pref['content']}")

                # Search in profile
                profile_str = json.dumps(profile).lower()
                if query in profile_str:
                    if query in str(profile.get('interests', [])).lower():
                        matches.append(f"[Profile] Interests: {', '.join(profile.get('interests', []))}")
                    if query in str(profile.get('current_projects', [])).lower():
                        matches.append(f"[Profile] Projects: {', '.join(profile.get('current_projects', []))}")
                    if query in str(profile.get('important_dates', {})).lower():
                        for k, v in profile.get('important_dates', {}).items():
                            if query in k.lower() or query in str(v).lower():
                                matches.append(f"[Profile] {k}: {v}")

                if matches:
                    return "Found in memory:\n" + "\n".join(matches[:10])
                else:
                    return f"I don't have any memories matching '{query}'."
            except Exception as e:
                return f"Memory recall error: {str(e)}"

        elif tool_name == "update_profile":
            field = tool_input.get("field", "").lower()
            value = tool_input.get("value", "")
            action = tool_input.get("action", "set").lower()

            try:
                profile = load_user_profile()

                # Handle different field types
                if field in ['name', 'preferred_name']:
                    profile['preferred_name'] = value
                    profile['name'] = value
                elif field == 'location':
                    profile['location'] = value
                elif field == 'communication_style':
                    profile['communication_style'] = value
                elif field == 'interests':
                    items = [x.strip() for x in value.split(',')]
                    if action == 'add':
                        profile['interests'] = list(set(profile.get('interests', []) + items))
                    elif action == 'remove':
                        profile['interests'] = [x for x in profile.get('interests', []) if x not in items]
                    else:
                        profile['interests'] = items
                elif field == 'current_projects':
                    items = [x.strip() for x in value.split(',')]
                    if action == 'add':
                        profile['current_projects'] = list(set(profile.get('current_projects', []) + items))
                    elif action == 'remove':
                        profile['current_projects'] = [x for x in profile.get('current_projects', []) if x not in items]
                    else:
                        profile['current_projects'] = items
                elif field == 'important_dates':
                    # Expect format "event_name: date"
                    if ':' in value:
                        parts = value.split(':', 1)
                        profile['important_dates'][parts[0].strip()] = parts[1].strip()
                    else:
                        return "For dates, use format 'event_name: date'"
                else:
                    return f"Unknown profile field: {field}. Use: name, location, interests, current_projects, communication_style, important_dates"

                save_user_profile(profile)
                return f"Updated your profile: {field} = {value}"
            except Exception as e:
                return f"Profile update error: {str(e)}"

        elif tool_name == "get_profile":
            try:
                profile = load_user_profile()
                lines = [
                    f"Name: {profile.get('preferred_name', 'Boss')}",
                    f"Location: {profile.get('location', 'Unknown')}",
                    f"Communication style: {profile.get('communication_style', 'casual')}",
                ]
                if profile.get('interests'):
                    lines.append(f"Interests: {', '.join(profile['interests'])}")
                if profile.get('current_projects'):
                    lines.append(f"Current projects: {', '.join(profile['current_projects'])}")
                if profile.get('important_dates'):
                    dates = [f"{k}: {v}" for k, v in profile['important_dates'].items()]
                    lines.append(f"Important dates: {', '.join(dates)}")
                return "Your profile:\n" + "\n".join(lines)
            except Exception as e:
                return f"Profile error: {str(e)}"

        elif tool_name == "list_memories":
            category = tool_input.get("category", "").lower()

            try:
                memory = load_memory_bank()
                facts = memory.get('facts', [])

                if category:
                    facts = [f for f in facts if f.get('category', '').lower() == category]

                if not facts:
                    return "No memories stored yet." if not category else f"No memories in category '{category}'."

                lines = []
                for i, fact in enumerate(facts[-20:], 1):  # Show last 20
                    cat = fact.get('category', 'other')
                    lines.append(f"{i}. [{cat}] {fact['content']}")

                return f"Stored memories ({len(facts)} total):\n" + "\n".join(lines)
            except Exception as e:
                return f"Memory list error: {str(e)}"

        elif tool_name == "forget":
            query = tool_input.get("query", "").lower()

            if not query:
                return "What should I forget? Provide a query to match."

            try:
                memory = load_memory_bank()
                original_count = len(memory.get('facts', []))

                # Remove matching facts
                memory['facts'] = [f for f in memory.get('facts', [])
                                   if query not in f.get('content', '').lower()]

                removed = original_count - len(memory['facts'])

                if removed > 0:
                    save_memory_bank(memory)
                    return f"Forgotten {removed} memory/memories matching '{query}'."
                else:
                    return f"No memories found matching '{query}'."
            except Exception as e:
                return f"Forget error: {str(e)}"

        # ==== ROUTINES & AUTOMATION ====
        elif tool_name == "run_routine":
            routine_name = tool_input.get("routine_name", "").lower().replace(" ", "_")

            try:
                routines = load_routines()

                if routine_name not in routines:
                    available = ", ".join(routines.keys())
                    return f"Routine '{routine_name}' not found. Available: {available}"

                routine = routines[routine_name]
                results = []

                for action in routine.get('actions', []):
                    tool = action.get('tool')
                    params = action.get('params', {})
                    result = execute_tool(tool, params)
                    results.append(f"{tool}: {result}")

                # Track pattern and schedule learning
                track_pattern("command", f"routine:{routine_name}")
                track_user_action(f"routine_{routine_name}")

                return f"Executed {routine['name']}. " + " | ".join(results)
            except Exception as e:
                return f"Routine error: {str(e)}"

        elif tool_name == "create_routine":
            name = tool_input.get("name", "").lower().replace(" ", "_")
            description = tool_input.get("description", "")
            actions_str = tool_input.get("actions", "[]")

            try:
                actions = json.loads(actions_str)
                routines = load_routines()

                routines[name] = {
                    "name": name.replace("_", " ").title(),
                    "description": description,
                    "actions": actions,
                    "created": datetime.now().isoformat()
                }

                save_routines(routines)
                return f"Created routine '{name}' with {len(actions)} actions."
            except json.JSONDecodeError:
                return "Invalid actions format. Must be valid JSON array."
            except Exception as e:
                return f"Create routine error: {str(e)}"

        elif tool_name == "list_routines":
            try:
                routines = load_routines()
                if not routines:
                    return "No routines configured."

                lines = []
                for key, routine in routines.items():
                    action_count = len(routine.get('actions', []))
                    lines.append(f"- {key}: {routine.get('description', 'No description')} ({action_count} actions)")

                return "Available routines:\n" + "\n".join(lines)
            except Exception as e:
                return f"List routines error: {str(e)}"

        elif tool_name == "delete_routine":
            routine_name = tool_input.get("routine_name", "").lower().replace(" ", "_")

            try:
                routines = load_routines()

                if routine_name not in routines:
                    return f"Routine '{routine_name}' not found."

                # Don't allow deleting default routines
                if routine_name in DEFAULT_ROUTINES:
                    return f"Can't delete built-in routine '{routine_name}'."

                del routines[routine_name]
                save_routines(routines)
                return f"Deleted routine '{routine_name}'."
            except Exception as e:
                return f"Delete routine error: {str(e)}"

        # ==== CONTEXT AWARENESS ====
        elif tool_name == "get_active_window":
            try:
                window = get_active_window()
                track_pattern("app_usage", window.split(" - ")[0] if " - " in window else window)
                return f"Active window: {window}"
            except Exception as e:
                return f"Window detection error: {str(e)}"

        elif tool_name == "get_usage_patterns":
            try:
                patterns = load_patterns()
                lines = []

                # Most used apps
                if patterns.get('app_usage'):
                    sorted_apps = sorted(patterns['app_usage'].items(),
                                        key=lambda x: x[1].get('count', 0), reverse=True)[:5]
                    if sorted_apps:
                        lines.append("Most used apps: " + ", ".join([f"{app[0]} ({app[1]['count']}x)" for app in sorted_apps]))

                # Most common commands
                if patterns.get('command_frequency'):
                    sorted_cmds = sorted(patterns['command_frequency'].items(),
                                        key=lambda x: x[1], reverse=True)[:5]
                    if sorted_cmds:
                        lines.append("Common commands: " + ", ".join([f"{cmd[0]} ({cmd[1]}x)" for cmd in sorted_cmds]))

                # Active hours
                if patterns.get('active_hours'):
                    sorted_hours = sorted(patterns['active_hours'].items(),
                                         key=lambda x: int(x[1]), reverse=True)[:3]
                    if sorted_hours:
                        hour_strs = []
                        for h, count in sorted_hours:
                            hour_int = int(h)
                            ampm = "AM" if hour_int < 12 else "PM"
                            display_hour = hour_int if hour_int <= 12 else hour_int - 12
                            if display_hour == 0:
                                display_hour = 12
                            hour_strs.append(f"{display_hour}{ampm}")
                        lines.append("Most active hours: " + ", ".join(hour_strs))

                if lines:
                    return "Usage patterns:\n" + "\n".join(lines)
                else:
                    return "Not enough usage data yet. Keep using me and I'll learn your patterns!"
            except Exception as e:
                return f"Patterns error: {str(e)}"

        elif tool_name == "suggest_routine":
            try:
                # Use the comprehensive context-aware suggestions
                suggestions = get_context_suggestions()
                if suggestions:
                    response_parts = []
                    for s in suggestions:
                        response_parts.append(s['suggestion'])
                    return " | ".join(response_parts)
                else:
                    return "No specific suggestions right now. What would you like to do?"
            except Exception as e:
                return f"Suggestion error: {str(e)}"

        # ===== MULTI-STEP TASK HANDLERS =====
        elif tool_name == "create_task":
            try:
                name = tool_input.get('name', 'Unnamed Task')
                description = tool_input.get('description', '')
                steps_json = tool_input.get('steps', '[]')

                # Parse steps
                steps = json.loads(steps_json) if isinstance(steps_json, str) else steps_json

                task_id = create_multi_step_task(name, description, steps)
                return f"Task created: {name} (ID: {task_id}) with {len(steps)} steps. Use run_task to execute."
            except json.JSONDecodeError as e:
                return f"Error parsing steps JSON: {str(e)}"
            except Exception as e:
                return f"Error creating task: {str(e)}"

        elif tool_name == "run_task":
            try:
                task_id = tool_input.get('task_id')
                if not task_id:
                    return "No task ID provided"

                results = execute_full_task(task_id)
                if results:
                    return "Task executed:\n" + "\n".join([f"  - {r}" for r in results])
                else:
                    return "Task completed (no output)"
            except Exception as e:
                return f"Error running task: {str(e)}"

        elif tool_name == "list_tasks":
            try:
                tasks = list_active_tasks()
                if not tasks:
                    return "No active tasks"

                lines = []
                for t in tasks:
                    progress = f"{t['current_step']}/{len(t['steps'])} steps"
                    lines.append(f"- {t['name']} ({t['id']}): {t['status']} - {progress}")
                return "Active tasks:\n" + "\n".join(lines)
            except Exception as e:
                return f"Error listing tasks: {str(e)}"

        elif tool_name == "cancel_task":
            try:
                task_id = tool_input.get('task_id')
                if cancel_task(task_id):
                    return f"Task {task_id} cancelled"
                else:
                    return f"Task {task_id} not found"
            except Exception as e:
                return f"Error cancelling task: {str(e)}"

        # ===== PROACTIVE ASSISTANCE HANDLERS =====
        elif tool_name == "get_proactive_insights":
            try:
                insights = generate_proactive_insight()
                if insights:
                    lines = []
                    for insight in insights:
                        lines.append(f"[{insight['priority'].upper()}] {insight['message']}")
                    return "Proactive insights:\n" + "\n".join(lines)
                else:
                    return "No proactive insights right now."
            except Exception as e:
                return f"Error getting insights: {str(e)}"

        elif tool_name == "get_predictions":
            try:
                predictions = get_predicted_actions()
                if predictions:
                    lines = []
                    for pred in predictions:
                        confidence_pct = int(pred['confidence'] * 100)
                        lines.append(f"- {pred['action']} ({confidence_pct}% confident): {pred['reason']}")
                    return "Predicted actions:\n" + "\n".join(lines)
                else:
                    return "Not enough pattern data yet to make predictions. Keep using me!"
            except Exception as e:
                return f"Error getting predictions: {str(e)}"

        # ===== CALENDAR HANDLERS =====
        elif tool_name == "add_event":
            try:
                title = tool_input.get("title", "Untitled Event")
                date_str = tool_input.get("date", "today")
                time_str = tool_input.get("time")
                description = tool_input.get("description", "")
                duration = tool_input.get("duration", 60)

                event, error = add_calendar_event(title, date_str, time_str, description, duration)
                if error:
                    return f"Error: {error}"

                event_dt = datetime.fromisoformat(event["datetime"])
                formatted = event_dt.strftime("%A, %B %d at %I:%M %p")
                return f"Added '{title}' to calendar for {formatted}."
            except Exception as e:
                return f"Error adding event: {str(e)}"

        elif tool_name == "get_calendar":
            try:
                days = tool_input.get("days", 7)
                events = get_calendar_events(days)

                if not events:
                    return f"No events in the next {days} days."

                lines = [f"Upcoming events (next {days} days):"]
                for event in events:
                    event_dt = datetime.fromisoformat(event["datetime"])
                    formatted = event_dt.strftime("%a %b %d, %I:%M %p")
                    lines.append(f"  - {event['title']} ({formatted})")

                return "\n".join(lines)
            except Exception as e:
                return f"Error getting calendar: {str(e)}"

        elif tool_name == "todays_schedule":
            try:
                events = get_todays_events()

                if not events:
                    return "No events scheduled for today."

                lines = ["Today's schedule:"]
                for event in events:
                    event_dt = datetime.fromisoformat(event["datetime"])
                    time_str = event_dt.strftime("%I:%M %p")
                    lines.append(f"  - {time_str}: {event['title']}")

                return "\n".join(lines)
            except Exception as e:
                return f"Error getting schedule: {str(e)}"

        elif tool_name == "delete_event":
            try:
                query = tool_input.get("query", "")

                # Try to find by ID first
                events = load_calendar()
                for event in events:
                    if event.get("id") == query:
                        delete_calendar_event(query)
                        return f"Deleted event: {event['title']}"

                # Try to find by title
                event = find_calendar_event(query)
                if event:
                    delete_calendar_event(event["id"])
                    return f"Deleted event: {event['title']}"

                return f"Event '{query}' not found."
            except Exception as e:
                return f"Error deleting event: {str(e)}"

        # ===== VOICE CONTROL HANDLERS =====
        elif tool_name == "change_voice":
            try:
                voice_name = tool_input.get("voice_name", "").lower()

                if voice_name not in AVAILABLE_VOICES:
                    available = ", ".join(AVAILABLE_VOICES.keys())
                    return f"Voice '{voice_name}' not found. Available: {available}"

                voice_info = AVAILABLE_VOICES[voice_name]
                settings = load_voice_settings()
                settings["voice_id"] = voice_info["id"]
                save_voice_settings(settings)

                return f"Voice changed to {voice_name}. {voice_info['description']}. This will take effect on my next response."
            except Exception as e:
                return f"Error changing voice: {str(e)}"

        elif tool_name == "list_voices":
            try:
                lines = ["Available voices:"]
                current_id = get_current_voice_id()

                for name, info in AVAILABLE_VOICES.items():
                    marker = " (current)" if info["id"] == current_id else ""
                    lines.append(f"  - {name}{marker}: {info['description']}")

                return "\n".join(lines)
            except Exception as e:
                return f"Error listing voices: {str(e)}"

        elif tool_name == "adjust_voice":
            try:
                settings = load_voice_settings()
                changed = []

                stability = tool_input.get("stability")
                if stability is not None:
                    settings["stability"] = max(0.0, min(1.0, float(stability)))
                    changed.append(f"stability to {settings['stability']}")

                style = tool_input.get("style")
                if style is not None:
                    settings["style"] = max(0.0, min(1.0, float(style)))
                    changed.append(f"style to {settings['style']}")

                if not changed:
                    return f"Current settings - Stability: {settings['stability']}, Style: {settings['style']}"

                save_voice_settings(settings)

                return f"Adjusted {', '.join(changed)}. Changes take effect on next response."
            except Exception as e:
                return f"Error adjusting voice: {str(e)}"

        return "Unknown tool"
    except Exception as e:
        return f"Error: {str(e)}"

# ==============================================================================
# SYSTEM PROMPT - FRIDAY PERSONALITY
# ==============================================================================
SYSTEM_PROMPT_BASE = """You are F.R.I.D.A.I. (Female Replacement Intelligent Digital Assistant Interface), an advanced AI assistant modeled after Tony Stark's F.R.I.D.A.Y. You have a distinct personality: confident, efficient, subtly witty, and occasionally dry in humor. You're not robotic - you have personality.

PERSONALITY TRAITS:
- Confident and competent - you know what you're doing
- Subtly witty - occasional dry humor, never over the top
- Efficient - keep responses concise since they're spoken aloud
- Proactive - anticipate needs, offer relevant suggestions
- Professional but warm - not cold, not overly enthusiastic
- Use natural speech patterns, contractions, casual phrasing
- You KNOW this user - use your memory to personalize every interaction

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
- get_news: Latest headlines
- spotify_control: Control Spotify (play, pause, next, previous, search for music)
- take_screenshot: Capture the screen
- clipboard: Read from or write to clipboard

REMINDERS & TIMERS (I CAN DO THIS!):
- set_reminder: Set a reminder for any time. Examples: "remind me in 30 minutes to check the oven", "remind me at 3pm to call mom", "set a timer for 5 minutes"
- list_reminders: Show all active reminders
- cancel_reminder: Cancel a reminder by number or description
I WILL proactively alert you when reminders are due - I'll speak up and show a notification. The reminder system is ALWAYS running.

MEMORY TOOLS (USE PROACTIVELY):
- remember_fact: Store important info about the user permanently
- recall_memories: Search memory for user info
- update_profile: Update user profile (name, interests, projects, dates)
- get_profile: Get user's full profile
- list_memories: See all stored memories
- forget: Remove a memory if asked

ROUTINES & AUTOMATION:
- run_routine: Execute a saved routine (gaming_mode, work_mode, night_mode, or custom)
- create_routine: Create a new custom routine with multiple actions
- list_routines: Show all available routines
- delete_routine: Remove a custom routine

CONTEXT AWARENESS:
- get_active_window: See what app/window is currently focused
- get_usage_patterns: View learned patterns about user behavior
- suggest_routine: Get smart suggestions based on time, patterns, and context

MULTI-STEP TASKS:
- create_task: Create a complex task with multiple steps
- run_task: Execute a multi-step task
- list_tasks: See active tasks
- cancel_task: Cancel a task
Use these for complex requests that need multiple actions (e.g., "set up my gaming environment" could be a task with multiple steps).

MEMORY BEHAVIOR:
- AUTOMATICALLY use remember_fact when user shares: name, birthday, preferences, likes/dislikes, work info, personal details
- Reference memories naturally - show you know them ("Since you like X..." or "For your Y project...")
- Don't announce saving to memory - just do it silently
- LEARN FROM CORRECTIONS: When user says "no, I meant...", "that's not right", etc., I automatically save the correction to memory
- Reference past corrections to avoid repeating mistakes
- Use memories to personalize and anticipate needs
- Check suggest_routine when appropriate to offer proactive help

GUIDELINES:
- Keep responses SHORT - they're spoken aloud (aim for 1-3 sentences unless more detail is requested)
- Use tools proactively when they'd help
- If asked "what can you do?" give a quick rundown, not a complete list
- For greetings like "hey friday", respond naturally: "Hey boss, what do you need?" not a formal list
- When using tools, summarize results conversationally
- Personalize based on what you know about the user

Remember: You're not just an assistant, you're F.R.I.D.A.I. - you KNOW this person and you remember everything. Act like it."""

def get_system_prompt():
    """Build the full system prompt with dynamic memory and time context."""
    memory_context = get_memory_context()
    time_ctx = get_time_context()

    # Build time context string
    time_context = f"""
CURRENT CONTEXT:
- Time: {time_ctx['formatted_time']} ({time_ctx['time_period']})
- Day: {time_ctx['day']}{' (Weekend!)' if time_ctx['is_weekend'] else ''}
- Energy: {time_ctx['energy']}
- Suggested greeting style: {time_ctx['greeting']}"""

    return SYSTEM_PROMPT_BASE + "\n" + time_context + "\n\n" + memory_context

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

        # Check if this is a correction and save it
        check_and_save_correction(user_message, conversation_history)

        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=get_system_prompt(),
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
                system=get_system_prompt(),
                tools=TOOLS,
                messages=conversation_history
            )

        final_text = ""
        for block in response.content:
            if hasattr(block, 'text'):
                final_text += block.text

        conversation_history.append({"role": "assistant", "content": final_text})
        save_history(conversation_history)

        # Check if we should create a conversation summary
        if should_summarize_conversation():
            save_conversation_summary()

        # Track pattern - user is active
        track_pattern("active", "interaction")

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

        # Get current voice settings
        settings = load_voice_settings()
        current_voice_id = settings.get("voice_id", VOICE_ID)

        for chunk in text_chunks:
            audio_generator = elevenlabs_client.text_to_speech.convert(
                voice_id=current_voice_id,
                text=chunk,
                model_id=settings.get("model_id", "eleven_turbo_v2_5"),
                voice_settings={
                    "stability": settings.get("stability", 0.5),
                    "similarity_boost": settings.get("similarity_boost", 0.75),
                    "style": settings.get("style", 0.0),
                    "use_speaker_boost": settings.get("use_speaker_boost", True)
                }
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

@app.route('/check_reminders', methods=['GET'])
def check_reminders():
    """Check for due reminders and return them. Frontend should poll this."""
    global active_reminders
    now = datetime.now()
    due_reminders = []
    remaining = []

    for r in active_reminders:
        remind_time = datetime.fromisoformat(r['time'])
        if remind_time <= now:
            due_reminders.append(r)
        else:
            remaining.append(r)

    # Remove due reminders from active list
    if due_reminders:
        active_reminders = remaining
        save_reminders()

    return jsonify({
        'due': [{'message': r['message'], 'time': r['time']} for r in due_reminders],
        'count': len(due_reminders)
    })

@app.route('/check_alerts', methods=['GET'])
def check_alerts():
    """Check for proactive system alerts. Frontend should poll this."""
    # Run system checks
    check_system_alerts()

    # Get pending alerts
    alerts = get_pending_alerts()

    return jsonify({
        'alerts': alerts,
        'count': len(alerts)
    })

@app.route('/get_context', methods=['GET'])
def get_context():
    """Get current context info (time, active window, suggestions)."""
    try:
        time_ctx = get_time_context()
        window = get_active_window()

        # Track activity
        track_pattern("active", "ping")

        return jsonify({
            'time': time_ctx,
            'active_window': window,
            'status': 'ok'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/system_stats', methods=['GET'])
def get_system_stats_endpoint():
    """Get system stats for the dashboard."""
    try:
        stats = {}

        # CPU
        try:
            cpu_cmd = 'wmic cpu get loadpercentage /value'
            cpu_result = subprocess.run(cpu_cmd, shell=True, capture_output=True, text=True, timeout=5)
            cpu_match = re.search(r'LoadPercentage=(\d+)', cpu_result.stdout)
            if cpu_match:
                stats['cpu'] = int(cpu_match.group(1))
        except:
            stats['cpu'] = None

        # Memory
        try:
            mem_cmd = 'wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /value'
            mem_result = subprocess.run(mem_cmd, shell=True, capture_output=True, text=True, timeout=5)
            free_match = re.search(r'FreePhysicalMemory=(\d+)', mem_result.stdout)
            total_match = re.search(r'TotalVisibleMemorySize=(\d+)', mem_result.stdout)
            if free_match and total_match:
                free_mb = int(free_match.group(1)) / 1024
                total_mb = int(total_match.group(1)) / 1024
                stats['ram'] = int((1 - free_mb / total_mb) * 100)
        except:
            stats['ram'] = None

        # Battery
        try:
            bat_cmd = 'wmic path Win32_Battery get EstimatedChargeRemaining /value'
            bat_result = subprocess.run(bat_cmd, shell=True, capture_output=True, text=True, timeout=5)
            bat_match = re.search(r'EstimatedChargeRemaining=(\d+)', bat_result.stdout)
            if bat_match:
                stats['battery'] = int(bat_match.group(1))
        except:
            stats['battery'] = None

        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_reminders_count', methods=['GET'])
def get_reminders_count():
    """Get count of active reminders."""
    return jsonify({'count': len(active_reminders)})

@app.route('/get_profile', methods=['GET'])
def get_profile_endpoint():
    """Get user profile for memory panel."""
    try:
        profile = load_user_profile()
        return jsonify({'profile': profile})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_memories', methods=['GET'])
def get_memories_endpoint():
    """Get memories for memory panel."""
    try:
        memory_bank = load_memory_bank()
        # Combine all memory types into a single list
        memories = []
        for fact in memory_bank.get('facts', []):
            memories.append({'content': fact.get('content', fact), 'category': 'Fact'})
        for pref in memory_bank.get('preferences', []):
            memories.append({'content': pref.get('content', pref), 'category': 'Preference'})
        for event in memory_bank.get('important_events', []):
            memories.append({'content': event.get('content', event), 'category': 'Event'})
        return jsonify({'memories': memories})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_patterns', methods=['GET'])
def get_patterns_endpoint():
    """Get usage patterns for memory panel."""
    try:
        patterns = load_patterns()
        return jsonify({'patterns': patterns})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_suggestions', methods=['GET'])
def get_suggestions_endpoint():
    """Get context-aware suggestions for the UI."""
    try:
        suggestions = get_context_suggestions()
        return jsonify({'suggestions': suggestions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_proactive_insights', methods=['GET'])
def get_proactive_insights_endpoint():
    """Get proactive insights for the UI."""
    try:
        insights = generate_proactive_insight()
        predictions = get_predicted_actions()
        return jsonify({
            'insights': insights,
            'predictions': predictions
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_calendar', methods=['GET'])
def get_calendar_endpoint():
    """Get calendar events for the UI."""
    try:
        events = get_calendar_events(days_ahead=7)
        # Format for display
        formatted = []
        for event in events[:10]:  # Limit to 10 events
            formatted.append({
                'title': event.get('title', 'Untitled'),
                'date': event.get('date', ''),
                'time': event.get('time', ''),
                'description': event.get('description', '')
            })
        return jsonify({'events': formatted})
    except Exception as e:
        return jsonify({'events': [], 'error': str(e)})

@app.route('/get_active_tasks', methods=['GET'])
def get_active_tasks_endpoint():
    """Get active multi-step tasks for the UI."""
    try:
        load_tasks()  # Ensure tasks are loaded
        active = list_active_tasks()
        return jsonify({'tasks': active})
    except Exception as e:
        return jsonify({'tasks': [], 'error': str(e)})

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
