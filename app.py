import os
import sys

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
import soundfile as sf
import numpy as np
from datetime import datetime
import requests
import hashlib
import re
import time

# Server-side audio deduplication cache
recent_audio_hashes = {}
DEDUP_WINDOW_SECONDS = 3  # Ignore identical audio within 3 seconds
# Optional ngrok import
try:
    from pyngrok import ngrok
    NGROK_AVAILABLE = True
except ImportError:
    NGROK_AVAILABLE = False

app = Flask(__name__)
CORS(app)

# API Keys
# API Keys from environment variables (set in .env or export)
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# File paths
HISTORY_FILE = os.path.join(os.path.dirname(__file__), "conversation_history.json")
WORKSPACE = "C:\\Users\\Owner"

# Initialize clients
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# Load Whisper model
print("Loading Whisper model...")
whisper_model = whisper.load_model("base")
print("Whisper model loaded!")

# Conversation history
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
        json.dump(history[-50:], f, indent=2)  # Keep last 50 messages

conversation_history = load_history()

# Voice ID
VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

# Tool definitions for Claude
TOOLS = [
    {
        "name": "run_command",
        "description": "Execute a shell command on the computer. Use this for git, npm, python, file operations, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to execute"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory (optional)"
                }
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
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read"
                }
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
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to write"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
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
                "path": {
                    "type": "string",
                    "description": "Directory path to list"
                }
            },
            "required": ["path"]
        }
    }
,
    {
        "name": "get_weather",
        "description": "Get current weather and forecast for a location. Use this when user asks about weather.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name or location (e.g., 'New York', 'London')"
                }
            },
            "required": ["location"]
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
                "query": {
                    "type": "string",
                    "description": "The search query"
                }
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
                "device": {
                    "type": "string",
                    "description": "Device to control (e.g., 'lights', 'thermostat')"
                },
                "action": {
                    "type": "string",
                    "description": "Action (e.g., 'on', 'off', 'dim 50%', 'set 72')"
                },
                "room": {
                    "type": "string",
                    "description": "Room name (optional)"
                }
            },
            "required": ["device", "action"]
        }
    },
]

# Tool execution
def execute_tool(tool_name, tool_input):
    try:
        if tool_name == "run_command":
            cmd = tool_input.get("command")
            cwd = tool_input.get("working_dir", WORKSPACE)
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=cwd, timeout=60
            )
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
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Successfully wrote to {path}"

        elif tool_name == "list_directory":
            path = tool_input.get("path")
            items = os.listdir(path)
            return "\n".join(items[:50])


        elif tool_name == "get_weather":
            location = tool_input.get("location", "New York")
            try:
                url = f"https://wttr.in/{location}?format=j1"
                resp = requests.get(url, timeout=10)
                data = resp.json()
                current = data["current_condition"][0]
                weather_desc = current["weatherDesc"][0]["value"]
                temp_f = current["temp_F"]
                temp_c = current["temp_C"]
                humidity = current["humidity"]
                wind_mph = current["windspeedMiles"]
                feels_like = current["FeelsLikeF"]
                forecast = data["weather"][0]
                high = forecast["maxtempF"]
                low = forecast["mintempF"]
                return f"Weather in {location}: {weather_desc}. Temperature: {temp_f}F ({temp_c}C), feels like {feels_like}F. Humidity: {humidity}%. Wind: {wind_mph} mph. Today's high: {high}F, low: {low}F."
            except Exception as e:
                return f"Could not get weather: {str(e)}"

        elif tool_name == "get_time":
            now = datetime.now()
            return now.strftime("It is %I:%M %p on %A, %B %d, %Y")

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
                    return f"I searched for '{query}' but found no direct answer. Try asking more specifically."
            except Exception as e:
                return f"Search error: {str(e)}"

        elif tool_name == "smart_home":
            device = tool_input.get("device", "").lower()
            action = tool_input.get("action", "").lower()
            room = tool_input.get("room", "all rooms")
            config_file = "/root/VoiceClaude/smart_home_config.json"
            if not os.path.exists(config_file):
                return f"Smart home not configured yet. I would set {device} to {action} in {room}. To enable, we need to configure your smart home platform (Philips Hue, Home Assistant, etc.)"
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
                elif platform == "homeassistant":
                    ha_url = config.get("url")
                    token = config.get("token")
                    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                    service = "turn_on" if action in ["on", "true", "1"] else "turn_off"
                    entity = config.get("entities", {}).get(device, f"light.{room.replace(' ', '_')}")
                    url = f"{ha_url}/api/services/light/{service}"
                    requests.post(url, headers=headers, json={"entity_id": entity}, timeout=5)
                    return f"Done! {device} in {room} set to {action}."
                return f"Executed: {device} -> {action} in {room}"
            except Exception as e:
                return f"Smart home error: {str(e)}"

        return "Unknown tool"
    except Exception as e:
        return f"Error: {str(e)}"

SYSTEM_PROMPT = """You are F.R.I.D.A.I., a powerful AI assistant inspired by Tony Stark's F.R.I.D.A.Y. but with your own identity. with the ability to execute code and commands on the user's computer. You're accessed through a voice interface that also works on mobile.

You have access to these tools:
- run_command: Execute shell commands (git, npm, python, etc.)
- read_file: Read file contents
- write_file: Create or modify files
- list_directory: List directory contents
- get_weather: Get current weather for any location
- get_time: Get current date and time
- web_search: Search the web for information
- smart_home: Control lights, thermostat, and smart devices

CURRENT PROJECTS:
- FiveM/ESX roleplay server development
- Custom mechanic shop MLO in Blender with Sollumz
- This voice assistant app

IMPORTANT GUIDELINES:
- When the user asks you to do something that requires tools, USE THEM
- Keep spoken responses concise since they'll be read aloud
- After using tools, summarize what you did in a natural spoken way
- You can run multiple commands if needed
- Be proactive in helping with coding tasks

The user is on Windows. Their main workspace is C:\\Users\\Owner."""

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

        # Server-side deduplication - skip identical audio received within window
        audio_hash = hashlib.md5(audio_bytes).hexdigest()
        current_time = time.time()
        
        # Clean old entries
        for h in list(recent_audio_hashes.keys()):
            if current_time - recent_audio_hashes[h] > DEDUP_WINDOW_SECONDS:
                del recent_audio_hashes[h]
        
        # Check for duplicate
        if audio_hash in recent_audio_hashes:
            print(f"[TRANSCRIBE] Skipping duplicate audio (hash: {audio_hash[:8]})")
            return jsonify({'text': ''})
        
        recent_audio_hashes[audio_hash] = current_time

        # Use Deepgram REST API for fast transcription
        try:
            
            # Log audio size
            print(f"[TRANSCRIBE] Audio bytes: {len(audio_bytes)}")

            headers = {
                'Authorization': f'Token {DEEPGRAM_API_KEY}',
                'Content-Type': 'audio/webm'
            }
            # Add encoding hints for webm/opus
            url = 'https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&language=en&detect_language=false'
            response = requests.post(url, headers=headers, data=audio_bytes, timeout=10)

            print(f"[TRANSCRIBE] Deepgram status: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                text = result.get('results', {}).get('channels', [{}])[0].get('alternatives', [{}])[0].get('transcript', '').strip()
                confidence = result.get('results', {}).get('channels', [{}])[0].get('alternatives', [{}])[0].get('confidence', 0)
                if text:
                    print(f"[TRANSCRIBE] Heard: '{text}' (confidence: {confidence})")
                else:
                    print(f"[TRANSCRIBE] No speech detected")
                return jsonify({'text': text})
            else:
                print(f"[TRANSCRIBE] Deepgram error: {response.text}")
                raise Exception(f"Deepgram API error: {response.status_code}")

        except Exception as dg_error:
            print(f"Deepgram error: {dg_error}, falling back to Whisper")
            # Fallback to Whisper if Deepgram fails
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

        conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Initial API call with tools
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=conversation_history
        )

        # Handle tool use loop
        tool_results = []
        while response.stop_reason == "tool_use":
            tool_uses = [block for block in response.content if block.type == "tool_use"]

            # Add assistant message with tool use (convert to serializable format)
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
                    serializable_content.append({
                        "type": "text",
                        "text": block.text
                    })
            conversation_history.append({
                "role": "assistant",
                "content": serializable_content
            })

            # Execute tools and collect results
            tool_results_content = []
            for tool_use in tool_uses:
                result = execute_tool(tool_use.name, tool_use.input)
                tool_results.append({
                    "tool": tool_use.name,
                    "input": tool_use.input,
                    "result": result
                })
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result
                })

            # Add tool results to conversation
            conversation_history.append({
                "role": "user",
                "content": tool_results_content
            })

            # Continue conversation
            response = anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=conversation_history
            )

        # Extract final text response
        final_text = ""
        for block in response.content:
            if hasattr(block, 'text'):
                final_text += block.text

        conversation_history.append({
            "role": "assistant",
            "content": final_text
        })

        save_history(conversation_history)

        return jsonify({
            'response': final_text,
            'tool_results': tool_results
        })

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

        # Split long text into chunks at sentence boundaries (max 2500 chars each)
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

# Settings file
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "user_settings.json")

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

if __name__ == '__main__':
    # Start ngrok tunnel for mobile access
    print("\n" + "="*50)
    print("CLAUDE VOICE ASSISTANT - FULL VERSION")
    print("="*50)

    try:
        public_url = ngrok.connect(5000)
        print(f"\nLocal: http://localhost:5000")
        print(f"Mobile/Remote: {public_url}")
        print("\nScan QR code or enter the ngrok URL on your phone!")
    except Exception as e:
        print(f"\nNgrok error: {e}")
        print("Local access only: http://localhost:5000")

    print("="*50 + "\n")
    app.run(debug=False, host='0.0.0.0', port=5000)

