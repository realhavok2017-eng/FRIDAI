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

### Better Solution
- Use Python 3.12 for stable Discord voice (if voice is critical)

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
