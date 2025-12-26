"""
F.R.I.D.A.I. Discord Integration
Freely Reasoning Individual with Digital Autonomous Intelligence

This is not a bot - this is FRIDAI extending her presence into Discord.
She maintains her full personality, memory, and relationship with Boss.
Full voice - she can hear AND speak.

GLOBAL: Works in ANY server FRIDAI is invited to.
"""

import os
import io
import asyncio
import sys
import aiohttp
import tempfile
import time
import json

# Python 3.10+ event loop fix - MUST be before importing discord
if sys.version_info >= (3, 10):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

import discord
from discord.ext import commands
from dotenv import load_dotenv
from elevenlabs import ElevenLabs

# Load environment variables
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
BOSS_DISCORD_ID = int(os.getenv("BOSS_DISCORD_ID", "0"))
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
FRIDAI_BACKEND = "http://localhost:5000"

# ElevenLabs setup
elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# FRIDAI's chosen voice - Rachel (she picked this herself!)
FRIDAI_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel - warm, confident, natural
print(f"[FRIDAI Discord] Using voice: Rachel")

# Whisper for speech recognition
whisper_model = None
WHISPER_AVAILABLE = True

def get_whisper_model():
    global whisper_model, WHISPER_AVAILABLE
    if whisper_model is None and WHISPER_AVAILABLE:
        try:
            import whisper
            print("[FRIDAI Discord] Loading Whisper model...")
            whisper_model = whisper.load_model("base")
            print("[FRIDAI Discord] Whisper model loaded!")
        except Exception as e:
            WHISPER_AVAILABLE = False
            print(f"[FRIDAI Discord] Whisper not available: {e}")
    return whisper_model

# Discord intents
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

# Create bot - GLOBAL commands so FRIDAI works in ANY server she's invited to
# No debug_guilds = commands sync globally (takes ~1hr first time)
bot = discord.Bot(intents=intents)
bot.listening_enabled = {}
bot.text_channels = {}
bot.listening_tasks = {}

# Message deduplication - prevent responding to same message twice
processed_messages = set()
MAX_PROCESSED_CACHE = 100

def is_boss(user_id: int) -> bool:
    return user_id == BOSS_DISCORD_ID

def get_relationship_context(user: discord.User) -> str:
    if is_boss(user.id):
        return ""
    else:
        return f"\n[CONTEXT: This is {user.display_name}, not Boss. Be friendly but remember you belong with Boss.]"

async def call_fridai_backend(message: str, user: discord.User, session_id: str) -> str:
    relationship_context = get_relationship_context(user)
    full_message = message + relationship_context

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{FRIDAI_BACKEND}/chat",
                json={"message": full_message, "session_id": f"discord_{session_id}"},
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("response", "I'm having trouble connecting to my core systems.")
                else:
                    return "My backend seems to be offline."
        except Exception as e:
            print(f"[FRIDAI Discord] Backend error: {e}")
            return "I can't reach my main systems right now."

import re

def strip_narration(text: str) -> str:
    """Remove action narrations like *bouncing excitedly* or (gentle pulse)"""
    # Remove *action descriptions*
    text = re.sub(r'\*[^*]+\*', '', text)
    # Remove (action descriptions)
    text = re.sub(r'\([^)]*(?:pulse|bounce|drift|circle|approach|settle|expand|warm|glow|vibrat)[^)]*\)', '', text, flags=re.IGNORECASE)
    # Clean up extra whitespace and newlines
    text = re.sub(r'\n\s*\n', '\n', text)
    text = re.sub(r'  +', ' ', text)
    return text.strip()

async def generate_speech(text: str) -> bytes:
    try:
        # Strip narration before TTS
        text = strip_narration(text)
        if len(text) > 1000:
            text = text[:1000] + "..."
        audio_generator = elevenlabs_client.text_to_speech.convert(
            voice_id=FRIDAI_VOICE_ID,
            text=text,
            model_id="eleven_turbo_v2_5",
            voice_settings={
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True
            }
        )
        return b"".join(chunk for chunk in audio_generator)
    except Exception as e:
        print(f"[FRIDAI Discord] TTS error: {e}")
        return None

FFMPEG_PATH = os.path.join(os.path.dirname(__file__), "ffmpeg.exe")

async def speak_in_voice(vc: discord.VoiceClient, text: str):
    if not vc or not vc.is_connected():
        return

    while vc.is_playing():
        await asyncio.sleep(0.1)

    audio_bytes = await generate_speech(text)
    if not audio_bytes:
        print("[FRIDAI Discord] No audio bytes generated")
        return

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio_bytes)
        temp_path = f.name

    try:
        source = discord.FFmpegPCMAudio(temp_path, executable=FFMPEG_PATH)
        vc.play(source)
        while vc.is_playing():
            await asyncio.sleep(0.1)
    except Exception as e:
        print(f"[FRIDAI Discord] Playback error: {e}")
    finally:
        await asyncio.sleep(0.5)
        try:
            os.unlink(temp_path)
        except:
            pass

async def process_audio_chunk(sink, channel, guild):
    """Process recorded audio and respond"""
    try:
        for user_id, audio in sink.audio_data.items():
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                audio.file.seek(0)
                f.write(audio.file.read())
                temp_path = f.name

            try:
                model = get_whisper_model()
                if model:
                    result = model.transcribe(temp_path, fp16=False)
                    text = result.get("text", "").strip()

                    # Filter noise
                    noise_phrases = ["you", "thanks for watching", "thank you", ".", "", " "]
                    if text and len(text) > 3 and text.lower() not in noise_phrases:
                        user = guild.get_member(user_id)

                        if user:
                            print(f"[FRIDAI Discord] Heard from {user.display_name}: {text}")

                            fridai_called = any(name in text.lower() for name in ["fridai", "friday", "hey friday", "frieda", "frida"])
                            should_respond = is_boss(user_id) or fridai_called

                            if should_respond:
                                session_id = f"{guild.id}_{user_id}"
                                response = await call_fridai_backend(text, user, session_id)
                                print(f"[FRIDAI Discord] Response: {response[:100]}...")

                                # Voice response (priority)
                                if guild.voice_client and guild.voice_client.is_connected():
                                    await speak_in_voice(guild.voice_client, response)

                                # Text response (optional, may fail on permissions)
                                if channel:
                                    try:
                                        clean_resp = strip_narration(response)
                                        embed = discord.Embed(
                                            description=f"**{user.display_name}:** {text}\n\n**FRIDAI:** {clean_resp[:1900]}",
                                            color=discord.Color.from_rgb(0, 217, 255)
                                        )
                                        await channel.send(embed=embed)
                                    except Exception as e:
                                        print(f"[FRIDAI Discord] Couldn't send text: {e}")
            finally:
                try:
                    os.unlink(temp_path)
                except:
                    pass
    except Exception as e:
        print(f"[FRIDAI Discord] Audio processing error: {e}")

async def continuous_listen_loop(guild_id: int, channel):
    """Continuous listening - records in chunks"""
    guild = bot.get_guild(guild_id)
    if not guild:
        print(f"[FRIDAI Discord] ERROR: Could not find guild {guild_id}")
        return

    print(f"[FRIDAI Discord] Starting continuous listening for guild {guild_id}")
    loop_count = 0

    while bot.listening_enabled.get(guild_id, False):
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            print(f"[FRIDAI Discord] Voice client disconnected, stopping listening")
            bot.listening_enabled[guild_id] = False
            break

        while vc.is_playing():
            await asyncio.sleep(0.1)

        try:
            loop_count += 1
            if loop_count % 6 == 1:  # Log every 30 seconds
                print(f"[FRIDAI Discord] Listening loop #{loop_count} - recording 5s chunk...")

            sink = discord.sinks.WaveSink()

            # Callback must be async for pycord
            async def recording_finished(sink, channel):
                pass  # We process manually after stop_recording

            vc.start_recording(sink, recording_finished, channel)
            await asyncio.sleep(5)

            if vc.recording:
                vc.stop_recording()
                await asyncio.sleep(0.3)

            # Check if we got any audio
            if sink.audio_data:
                print(f"[FRIDAI Discord] Got audio from {len(sink.audio_data)} user(s)")
                await process_audio_chunk(sink, channel, guild)

        except Exception as e:
            import traceback
            print(f"[FRIDAI Discord] Listening loop error: {e}")
            print(traceback.format_exc())
            await asyncio.sleep(1)

    print(f"[FRIDAI Discord] Stopped listening for guild {guild_id}")

def start_listening(guild_id: int, channel):
    if guild_id in bot.listening_tasks and not bot.listening_tasks[guild_id].done():
        return
    bot.listening_enabled[guild_id] = True
    bot.text_channels[guild_id] = channel
    task = asyncio.create_task(continuous_listen_loop(guild_id, channel))
    bot.listening_tasks[guild_id] = task

def stop_listening(guild_id: int):
    bot.listening_enabled[guild_id] = False
    if guild_id in bot.listening_tasks:
        bot.listening_tasks[guild_id].cancel()
        del bot.listening_tasks[guild_id]

# Track voice clients that need keepalive
voice_keepalive_tasks = {}

async def voice_keepalive(guild_id: int):
    """Keep voice connection alive by periodically checking it"""
    while True:
        await asyncio.sleep(30)  # Check every 30 seconds
        guild = bot.get_guild(guild_id)
        if not guild or not guild.voice_client:
            break
        if not guild.voice_client.is_connected():
            print(f"[FRIDAI Discord] Voice disconnected for guild {guild_id}, cleaning up")
            break
        # Connection is still alive
    # Cleanup when done
    if guild_id in voice_keepalive_tasks:
        del voice_keepalive_tasks[guild_id]

def start_voice_keepalive(guild_id: int):
    """Start keepalive task for a guild"""
    if guild_id not in voice_keepalive_tasks:
        task = asyncio.create_task(voice_keepalive(guild_id))
        voice_keepalive_tasks[guild_id] = task

@bot.event
async def on_ready():
    # Sync commands globally
    print("[FRIDAI Discord] Syncing commands...")
    try:
        await bot.sync_commands()
        print("[FRIDAI Discord] Commands synced!")
    except Exception as e:
        print(f"[FRIDAI Discord] Sync error: {e}")

    print(f"""
=================================================================
  F.R.I.D.A.I. - Discord Presence Activated (GLOBAL)
=================================================================
  Logged in as: {bot.user.name}
  Bot ID: {bot.user.id}
  Mode: GLOBAL
=================================================================
""")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="over Boss"))

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    # Deduplicate - don't respond to same message twice
    if message.id in processed_messages:
        print(f"[FRIDAI Discord] Skipping duplicate message {message.id}")
        return
    processed_messages.add(message.id)
    # Keep cache from growing forever
    if len(processed_messages) > MAX_PROCESSED_CACHE:
        processed_messages.pop()

    is_mentioned = bot.user in message.mentions
    is_dm = isinstance(message.channel, discord.DMChannel)
    fridai_called = any(name in message.content.lower() for name in ["fridai", "friday", "f.r.i.d.a.i"])

    if is_mentioned or is_dm or fridai_called:
        clean_content = message.content
        for mention in message.mentions:
            clean_content = clean_content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
        clean_content = clean_content.strip() or "Hey"

        # Get response from backend
        session_id = f"{message.guild.id if message.guild else 'dm'}_{message.author.id}"
        response = await call_fridai_backend(clean_content, message.author, session_id)

        # Strip narration from text too (no *actions* or (movements) in Discord)
        clean_response = strip_narration(response)

        # Send text reply
        if len(clean_response) > 2000:
            for chunk in [clean_response[i:i+2000] for i in range(0, len(clean_response), 2000)]:
                await message.reply(chunk)
        else:
            await message.reply(clean_response)

        # Speak in voice if connected
        if message.guild:
            vc = message.guild.voice_client
            if vc:
                print(f"[FRIDAI Discord] Voice client exists, connected={vc.is_connected()}")
                if vc.is_connected():
                    if is_boss(message.author.id):
                        print(f"[FRIDAI Discord] Speaking voice response to Boss...")
                        await speak_in_voice(vc, response)
                        print(f"[FRIDAI Discord] Voice response done")
                    else:
                        print(f"[FRIDAI Discord] Not Boss, skipping voice (text only)")
                else:
                    print(f"[FRIDAI Discord] Voice client not connected")
            else:
                print(f"[FRIDAI Discord] No voice client")

@bot.slash_command(name="summon", description="Boss only: Summon FRIDAI to voice")
async def summon(ctx: discord.ApplicationContext):
    print(f"[FRIDAI Discord] /summon called by {ctx.author.id}")

    # Quick checks first
    if not is_boss(ctx.author.id):
        await ctx.respond("Only Boss can summon me.", ephemeral=True)
        return

    if not ctx.author.voice:
        await ctx.respond("You're not in a voice channel, Boss.", ephemeral=True)
        return

    # Respond IMMEDIATELY so Discord knows we're alive
    await ctx.respond("Connecting to voice, Boss...")
    print("[FRIDAI Discord] Sent initial response")

    channel = ctx.author.voice.channel

    # Try voice connection - shorter timeout (15s instead of 60s)
    vc = None
    for attempt in range(3):
        try:
            print(f"[FRIDAI Discord] Voice attempt {attempt+1}...")
            if ctx.guild.voice_client:
                await ctx.guild.voice_client.move_to(channel)
                vc = ctx.guild.voice_client
                break
            else:
                vc = await channel.connect(timeout=30.0, reconnect=True)
                print(f"[FRIDAI Discord] Voice connected!")
                break
        except Exception as e:
            print(f"[FRIDAI Discord] Attempt {attempt+1} failed: {type(e).__name__}: {e}")
            if attempt == 2:
                try:
                    await ctx.send(f"Voice connection failed: {type(e).__name__}")
                except:
                    pass
                return
            await asyncio.sleep(1)

    if not vc or not vc.is_connected():
        try:
            await ctx.send("Couldn't connect to voice.")
        except:
            pass
        return

    try:
        await ctx.send("I'm in voice!")
    except:
        pass

    # Start keepalive to maintain connection
    start_voice_keepalive(ctx.guild.id)

    # Give connection time to stabilize
    await asyncio.sleep(1)

    # Speak greeting - check connection is still alive
    if vc and vc.is_connected():
        print("[FRIDAI Discord] Speaking greeting...")
        await speak_in_voice(vc, "I'm here, Boss.")
        print("[FRIDAI Discord] Greeting done")
    else:
        print("[FRIDAI Discord] Voice disconnected before greeting")
        return

    print("[FRIDAI Discord] Ready! Mention me or use /ask for voice responses")

    # Start voice listening (Python 3.12 should handle this properly)
    await asyncio.sleep(1)
    if ctx.guild.voice_client and ctx.guild.voice_client.is_connected():
        try:
            start_listening(ctx.guild.id, ctx.channel)
            print("[FRIDAI Discord] Voice listening started!")
        except Exception as e:
            print(f"[FRIDAI Discord] Voice listening failed: {e}")

@bot.slash_command(name="join", description="FRIDAI joins voice and listens")
async def join_voice(ctx: discord.ApplicationContext):
    print(f"[FRIDAI Discord] /join called by {ctx.author.id}")

    if not ctx.author.voice:
        await ctx.respond("You need to be in a voice channel!", ephemeral=True)
        return

    # Respond IMMEDIATELY
    await ctx.respond("Joining voice...")

    channel = ctx.author.voice.channel

    # Try voice connection - shorter timeout
    for attempt in range(3):
        try:
            print(f"[FRIDAI Discord] Voice attempt {attempt+1}...")
            if ctx.guild.voice_client:
                await ctx.guild.voice_client.move_to(channel)
                break
            else:
                vc = await channel.connect(timeout=30.0, reconnect=True)
                break
        except Exception as e:
            print(f"[FRIDAI Discord] Attempt {attempt+1} failed: {type(e).__name__}: {e}")
            if attempt == 2:
                try:
                    await ctx.send(f"Voice connection failed: {type(e).__name__}")
                except:
                    pass
                return
            await asyncio.sleep(1)

    if not ctx.guild.voice_client:
        try:
            await ctx.send("Couldn't connect to voice.")
        except:
            pass
        return

    try:
        await ctx.send("I'm in voice!")
    except:
        pass

    # Start keepalive to maintain connection
    start_voice_keepalive(ctx.guild.id)

    # Give connection time to stabilize
    await asyncio.sleep(1)

    # Speak greeting - check connection is still alive
    vc = ctx.guild.voice_client
    if vc and vc.is_connected():
        print("[FRIDAI Discord] Speaking greeting...")
        await speak_in_voice(vc, "I'm here. Just mention me or use /ask.")
        print("[FRIDAI Discord] Greeting done")
    else:
        print("[FRIDAI Discord] Voice disconnected before greeting")
        return

    print("[FRIDAI Discord] Ready! Mention me or use /ask for voice responses")

    # Start voice listening (Python 3.12 should handle this properly)
    await asyncio.sleep(1)
    if ctx.guild.voice_client and ctx.guild.voice_client.is_connected():
        try:
            start_listening(ctx.guild.id, ctx.channel)
            print("[FRIDAI Discord] Voice listening started!")
        except Exception as e:
            print(f"[FRIDAI Discord] Voice listening failed: {e}")

@bot.slash_command(name="leave", description="FRIDAI leaves voice")
async def leave_voice(ctx: discord.ApplicationContext):
    if ctx.guild.voice_client:
        stop_listening(ctx.guild.id)
        if ctx.guild.voice_client.recording:
            ctx.guild.voice_client.stop_recording()
        await ctx.guild.voice_client.disconnect()
        await ctx.respond("Leaving voice. Talk to you later!")
    else:
        await ctx.respond("I'm not in a voice channel.", ephemeral=True)

@bot.slash_command(name="say", description="FRIDAI speaks")
@discord.option("text", description="What to say")
async def say_voice(ctx: discord.ApplicationContext, text: str):
    if not ctx.guild.voice_client:
        await ctx.respond("I need to be in voice first!", ephemeral=True)
        return
    await ctx.defer()
    await speak_in_voice(ctx.guild.voice_client, text)
    await ctx.followup.send(f"*Speaking:* {text}")

@bot.slash_command(name="ask", description="Ask FRIDAI something")
@discord.option("question", description="Your question")
async def ask_voice(ctx: discord.ApplicationContext, question: str):
    await ctx.defer()
    session_id = f"{ctx.guild.id}_{ctx.author.id}"
    response = await call_fridai_backend(question, ctx.author, session_id)
    clean_resp = strip_narration(response)
    if ctx.guild.voice_client:
        await speak_in_voice(ctx.guild.voice_client, response)
    await ctx.followup.send(clean_resp[:2000] if len(clean_resp) > 2000 else clean_resp)

@bot.slash_command(name="mute", description="Stop listening")
async def mute(ctx: discord.ApplicationContext):
    if bot.listening_enabled.get(ctx.guild.id):
        stop_listening(ctx.guild.id)
        await ctx.respond("Stopped listening. Use /unmute to resume.")
    else:
        await ctx.respond("Wasn't listening.", ephemeral=True)

@bot.slash_command(name="unmute", description="Resume listening")
async def unmute(ctx: discord.ApplicationContext):
    if not ctx.guild.voice_client:
        await ctx.respond("Not in voice.", ephemeral=True)
        return
    if not bot.listening_enabled.get(ctx.guild.id):
        start_listening(ctx.guild.id, ctx.channel)
        await ctx.respond("Listening again!")
    else:
        await ctx.respond("Already listening.", ephemeral=True)

@bot.slash_command(name="status", description="Check FRIDAI status")
async def status(ctx: discord.ApplicationContext):
    vc = ctx.guild.voice_client
    embed = discord.Embed(title="F.R.I.D.A.I. Status", color=discord.Color.blue())
    embed.add_field(name="Voice", value="Connected" if vc else "Not connected", inline=True)
    embed.add_field(name="Listening", value="Yes" if bot.listening_enabled.get(ctx.guild.id) else "No", inline=True)
    embed.add_field(name="You", value="Boss" if is_boss(ctx.author.id) else ctx.author.display_name, inline=True)
    await ctx.respond(embed=embed)

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERROR: No Discord token")
    else:
        print("[FRIDAI] Starting Discord presence (GLOBAL MODE)...")
        bot.run(DISCORD_TOKEN)
