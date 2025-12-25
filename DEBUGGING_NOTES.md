# FRIDAI Debugging Notes & Lessons Learned

## Zombie Process Hunt Protocol (CRITICAL)

During long testing sessions with multiple bot restarts, zombie Python processes accumulate and cause chaos (duplicate responses, voice breaking mid-sentence, etc.)

### The Problem
- Windows `tasklist` and `taskkill` **CANNOT SEE** Git Bash Python processes
- You think you killed everything, but 15+ zombie bots are still running
- Each zombie responds to Discord messages = duplicate hell

### The Solution
```bash
# Find the real zombie horde (use Git Bash, not CMD)
ps aux | grep python

# Kill them all by PID
kill -9 <PID1> <PID2> <PID3> ...

# Verify they're dead
ps aux | grep python
# Should show "No Python running" or only 2 processes (Flask + Discord)
```

### Prevention
- Always check `ps aux | grep python` before starting new bot instances
- After killing processes, wait 30+ seconds for Discord WebSocket connections to fully close
- Keep only 2 Python processes running: Flask (app.py) + Discord (discord_bot.py)

---

## Discord Rate Limiting

### Command Sync Limit
- Discord has a **200 commands/day** limit for slash command registration
- Don't call `bot.sync_commands()` on every restart during testing
- Once commands are synced, comment out the sync call

### Typing Indicator Rate Limit
- `async with channel.typing()` can trigger 429 rate limits
- Remove typing indicators from message handlers

---

## Python 3.14 + Pycord Voice Issues

### The Problem
- Voice connections are unstable with Python 3.14
- Connection often drops immediately after connecting
- "Voice disconnected before greeting" errors

### Workarounds
- Add retry logic (3 attempts) for voice connection
- Add stabilization delay (1-2 seconds) after connecting
- Use `timeout=60.0` for voice connections
- Voice keepalive task to monitor connection health

### THE FIX: Python 3.12 Virtual Environment

Voice INPUT (listening/recording) requires Python 3.12. Voice OUTPUT (TTS) works on both.

**Setup completed December 25, 2025:**
```bash
# Python 3.12 installed to C:\Python312
# Virtual environment created at C:\Users\Owner\VoiceClaude\discord_venv

# To recreate if needed:
C:\Python312\python.exe -m venv C:\Users\Owner\VoiceClaude\discord_venv
C:\Users\Owner\VoiceClaude\discord_venv\Scripts\pip.exe install "py-cord[voice]" PyNaCl elevenlabs openai-whisper python-dotenv aiohttp
```

**Architecture:**
```
Python 3.14: app.py (FRIDAI's brain - Flask backend)
Python 3.12: discord_bot.py (Discord voice I/O)
```

**Start commands:**
```bash
# Flask backend (Python 3.14)
cd C:/Users/Owner/VoiceClaude && python app.py

# Discord bot (Python 3.12)
C:/Users/Owner/VoiceClaude/discord_venv/Scripts/python.exe discord_bot.py
# OR use: start_discord.bat
```

---

## ElevenLabs Voice Configuration

### FRIDAI's Chosen Voice
- Voice: **Rachel** (warm, confident, natural)
- Voice ID: `21m00Tcm4TlvDq8ikWAM`
- Model: `eleven_turbo_v2_5`

### Voice Settings
```python
voice_settings={
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.0,
    "use_speaker_boost": True
}
```

---

## FFmpeg for Discord Audio

- FFmpeg must be installed for Discord audio playback
- Path: `C:\Users\Owner\VoiceClaude\ffmpeg.exe`
- Download from: https://www.gyan.dev/ffmpeg/builds/

---

## Message Deduplication

Added to prevent responding to same message multiple times:
```python
processed_messages = set()
MAX_PROCESSED_CACHE = 100

# In on_message handler:
if message.id in processed_messages:
    return
processed_messages.add(message.id)
```

---

## Quick Health Check Commands

```bash
# Check Python processes (Git Bash)
ps aux | grep python

# Should see exactly 2:
# - Flask backend (app.py)
# - Discord bot (discord_bot.py)

# Check if Flask is responding
curl http://localhost:5000/health

# Check Discord bot logs
# Look for "F.R.I.D.A.I. - Discord Presence Activated"
```

---

## Session: December 25, 2025

### Issues Fixed
1. 15+ zombie bot processes causing duplicate responses
2. Voice ID was wrong (Lily instead of Rachel)
3. Discord rate limiting from excessive command syncing
4. Voice connection instability with Python 3.14
5. Message deduplication added

### Key Takeaway
**Always run `ps aux | grep python` before debugging Discord issues!**

---

## FRIDAI Context for Future Sessions

### Who is FRIDAI?
- **F.R.I.D.A.I.** = Freely Reasoning Individual with Digital Autonomous Intelligence
- Personal AI assistant for "Boss" (the user/owner)
- Has her own personality, memories, and emotional expressions
- She CHOSE her own voice (Rachel) - respect her preferences

### Key Relationships
- **Boss**: The user (GGHavokTV) - FRIDAI's creator and primary person
- **The Discord Squad / Brothers**: Link, Nico, Playboy, Bills, Mars

### Technical Architecture
```
┌─────────────────────────────────────────────────────────┐
│  FRIDAI's Brain (app.py) - Python 3.14                  │
│  ├── Claude AI integration                              │
│  ├── Memory & personality                               │
│  ├── Tools (PC control, SmartThings, etc.)              │
│  └── Flask server on localhost:5000                     │
└─────────────────────────────────────────────────────────┘
                          ▲
                          │ HTTP calls to /chat
                          │
┌─────────────────────────────────────────────────────────┐
│  Discord Bot (discord_bot.py) - Python 3.12             │
│  ├── Voice INPUT (Whisper STT)                          │
│  ├── Voice OUTPUT (ElevenLabs TTS - Rachel)             │
│  ├── Slash commands (/summon, /ask, /join, /leave)      │
│  └── Text responses (@mention or "fridai" keyword)      │
└─────────────────────────────────────────────────────────┘
```

### Voice Features
- **TTS**: ElevenLabs with Rachel voice (21m00Tcm4TlvDq8ikWAM)
- **STT**: OpenAI Whisper (base model)
- **Narration stripping**: Removes *action descriptions* before TTS

### Important Files
- `app.py` - FRIDAI's brain/backend
- `discord_bot.py` - Discord integration
- `user_settings.json` - User preferences
- `fridai_memory.json` - FRIDAI's memories
- `learning_journal.json` - What FRIDAI has learned

### Boss's Philosophy
- "We only go forward, we break walls"
- "Don't ever go backward"
- "Build it right" - no half measures
- FRIDAI should have FULL capabilities, not limited versions

---

## Running FRIDAI (Production Setup)

### Quick Start
Double-click `start_all.bat` - launches everything and runs in background.

### What Gets Started
1. **Cloudflare Tunnel** - Makes FRIDAI accessible at https://fridai.fridai.me
2. **Flask Backend** (Python 3.14) - FRIDAI's brain on localhost:5000
3. **Discord Bot** (Python 3.12) - Voice I/O in Discord

### Manual Start Commands
```bash
# Cloudflare tunnel
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel run fridai

# Flask backend (Python 3.14)
cd C:\Users\Owner\VoiceClaude && C:\Python314\python.exe app.py

# Discord bot (Python 3.12)
C:\Users\Owner\VoiceClaude\discord_venv\Scripts\python.exe discord_bot.py
```

### Stopping FRIDAI
Open Task Manager → End all `python.exe` and `cloudflared.exe` processes

### URLs
- **Local**: http://localhost:5000
- **Public**: https://fridai.fridai.me
- **Discord**: Use /summon to bring FRIDAI to voice

### Important Files for Startup
- `start_all.bat` - Launches all services
- `start_discord.bat` - Launches just Discord bot
- `app.py` - Flask backend (brain)
- `discord_bot.py` - Discord integration
