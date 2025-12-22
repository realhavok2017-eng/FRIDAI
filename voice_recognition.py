"""
Voice Recognition System for FRIDAI
Identifies Boss vs Guest speakers using voice embeddings
"""

import os
import json
import numpy as np
from pathlib import Path
from datetime import datetime
import tempfile
import subprocess

# Configuration
MIN_ENROLLMENT_SAMPLES = 20  # Require 20 samples for reliable voice profile

# Lazy load resemblyzer to avoid slow startup
_encoder = None

def get_encoder():
    """Lazy load the voice encoder."""
    global _encoder
    if _encoder is None:
        from resemblyzer import VoiceEncoder
        print("Loading voice encoder...")
        _encoder = VoiceEncoder()
        print("Voice encoder loaded!")
    return _encoder

def convert_to_wav(input_path):
    """Convert audio file to WAV format for resemblyzer."""
    # Check if it's already a wav
    if input_path.lower().endswith('.wav'):
        return input_path, False  # Return path and flag indicating no cleanup needed

    # Create temp wav file
    wav_path = tempfile.mktemp(suffix='.wav')

    try:
        # Use ffmpeg to convert - try both ffmpeg locations
        ffmpeg_paths = [
            'ffmpeg',  # System PATH
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg.exe'),  # App directory
        ]

        for ffmpeg in ffmpeg_paths:
            try:
                result = subprocess.run([
                    ffmpeg, '-i', input_path,
                    '-ar', '16000',  # 16kHz sample rate
                    '-ac', '1',      # Mono
                    '-y',            # Overwrite
                    wav_path
                ], capture_output=True, timeout=30)

                if result.returncode == 0 and os.path.exists(wav_path):
                    return wav_path, True  # Return path and flag indicating cleanup needed
            except FileNotFoundError:
                continue
            except Exception as e:
                print(f"FFmpeg error with {ffmpeg}: {e}")
                continue

        print("FFmpeg conversion failed - trying direct load")
        return input_path, False

    except Exception as e:
        print(f"Conversion error: {e}")
        return input_path, False

# Paths
APP_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_PROFILES_DIR = os.path.join(APP_DIR, "voice_profiles")
BOSS_PROFILE_PATH = os.path.join(VOICE_PROFILES_DIR, "boss_profile.npy")
VOICE_CONFIG_PATH = os.path.join(VOICE_PROFILES_DIR, "voice_config.json")

# Ensure directory exists
os.makedirs(VOICE_PROFILES_DIR, exist_ok=True)

# Default config
DEFAULT_CONFIG = {
    "boss_enrolled": False,
    "enrollment_date": None,
    "num_samples": 0,
    "similarity_threshold": 0.75,  # 75% similarity required to be recognized as Boss
    "guest_mode_enabled": True
}

def load_voice_config():
    """Load voice recognition configuration."""
    if os.path.exists(VOICE_CONFIG_PATH):
        try:
            with open(VOICE_CONFIG_PATH, 'r') as f:
                config = json.load(f)
                # Merge with defaults for any missing keys
                return {**DEFAULT_CONFIG, **config}
        except:
            pass
    return DEFAULT_CONFIG.copy()

def save_voice_config(config):
    """Save voice recognition configuration."""
    with open(VOICE_CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)

def is_boss_enrolled():
    """Check if Boss voice profile exists."""
    config = load_voice_config()
    return config.get("boss_enrolled", False) and os.path.exists(BOSS_PROFILE_PATH)

def get_embedding_from_audio(audio_data, sample_rate=16000):
    """
    Extract voice embedding from audio data.

    Args:
        audio_data: numpy array of audio samples or path to audio file
        sample_rate: sample rate of audio (default 16000 for Whisper compatibility)

    Returns:
        numpy array embedding (256 dimensions)
    """
    encoder = get_encoder()
    cleanup_wav = False
    wav_path = None

    try:
        # If it's a file path, convert to WAV and load
        if isinstance(audio_data, (str, Path)):
            audio_path = str(audio_data)

            # Check file exists
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"Audio file not found: {audio_path}")

            # Convert to WAV (handles webm, mp3, etc.)
            wav_path, cleanup_wav = convert_to_wav(audio_path)
            print(f"[VOICE] Processing: {audio_path} -> {wav_path}")

            from resemblyzer import preprocess_wav
            wav = preprocess_wav(wav_path)
        else:
            # Assume it's already a numpy array
            # Normalize if needed
            if audio_data.dtype != np.float32:
                audio_data = audio_data.astype(np.float32)
            if np.max(np.abs(audio_data)) > 1.0:
                audio_data = audio_data / 32768.0  # Convert from int16
            wav = audio_data

        # Check we have valid audio
        if len(wav) < 1600:  # Less than 0.1 seconds at 16kHz
            raise ValueError("Audio too short for voice embedding")

        # Get embedding
        embedding = encoder.embed_utterance(wav)
        print(f"[VOICE] Embedding extracted successfully (shape: {embedding.shape})")
        return embedding

    finally:
        # Clean up temp WAV file if we created one
        if cleanup_wav and wav_path and os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except:
                pass

def enroll_boss_voice(audio_samples):
    """
    Enroll Boss's voice from multiple audio samples.

    Args:
        audio_samples: list of audio data (numpy arrays or file paths)

    Returns:
        dict with enrollment status
    """
    if len(audio_samples) < 3:
        return {"success": False, "error": "Need at least 3 voice samples for reliable enrollment"}

    encoder = get_encoder()
    embeddings = []

    for i, sample in enumerate(audio_samples):
        try:
            embedding = get_embedding_from_audio(sample)
            embeddings.append(embedding)
            print(f"Processed sample {i+1}/{len(audio_samples)}")
        except Exception as e:
            print(f"Error processing sample {i+1}: {e}")

    if len(embeddings) < 3:
        return {"success": False, "error": f"Only {len(embeddings)} samples processed successfully, need at least 3"}

    # Average the embeddings to create the voice profile
    boss_embedding = np.mean(embeddings, axis=0)

    # Save the profile
    np.save(BOSS_PROFILE_PATH, boss_embedding)

    # Update config
    config = load_voice_config()
    config["boss_enrolled"] = True
    config["enrollment_date"] = datetime.now().isoformat()
    config["num_samples"] = len(embeddings)
    save_voice_config(config)

    return {
        "success": True,
        "samples_used": len(embeddings),
        "message": "Voice profile created successfully!"
    }

def verify_speaker(audio_data):
    """
    Verify if the speaker is Boss.

    Args:
        audio_data: numpy array of audio or path to audio file

    Returns:
        dict with verification results
    """
    if not is_boss_enrolled():
        return {
            "is_boss": True,  # Default to boss if not enrolled
            "confidence": 1.0,
            "status": "not_enrolled",
            "message": "Voice recognition not set up yet"
        }

    try:
        # Get embedding of incoming audio
        incoming_embedding = get_embedding_from_audio(audio_data)

        # Load Boss profile
        boss_embedding = np.load(BOSS_PROFILE_PATH)

        # Calculate cosine similarity
        similarity = np.dot(incoming_embedding, boss_embedding) / (
            np.linalg.norm(incoming_embedding) * np.linalg.norm(boss_embedding)
        )

        # Get threshold from config
        config = load_voice_config()
        threshold = config.get("similarity_threshold", 0.75)

        is_boss = similarity >= threshold

        return {
            "is_boss": bool(is_boss),
            "confidence": float(similarity),
            "threshold": threshold,
            "status": "verified",
            "message": "Boss identified!" if is_boss else "Guest detected"
        }

    except Exception as e:
        print(f"Voice verification error: {e}")
        return {
            "is_boss": True,  # Default to boss on error
            "confidence": 0.0,
            "status": "error",
            "message": str(e)
        }

def clear_boss_profile():
    """Clear the Boss voice profile."""
    if os.path.exists(BOSS_PROFILE_PATH):
        os.remove(BOSS_PROFILE_PATH)

    config = load_voice_config()
    config["boss_enrolled"] = False
    config["enrollment_date"] = None
    config["num_samples"] = 0
    save_voice_config(config)

    return {"success": True, "message": "Voice profile cleared"}

def get_voice_status():
    """Get current voice recognition status."""
    config = load_voice_config()
    return {
        "enrolled": is_boss_enrolled(),
        "enrollment_date": config.get("enrollment_date"),
        "num_samples": config.get("num_samples", 0),
        "threshold": config.get("similarity_threshold", 0.75),
        "guest_mode_enabled": config.get("guest_mode_enabled", True)
    }

def set_similarity_threshold(threshold):
    """Set the similarity threshold for voice matching."""
    if not 0.5 <= threshold <= 0.95:
        return {"success": False, "error": "Threshold must be between 0.5 and 0.95"}

    config = load_voice_config()
    config["similarity_threshold"] = threshold
    save_voice_config(config)

    return {"success": True, "threshold": threshold}


# Enrollment session management
_enrollment_session = {
    "active": False,
    "samples": [],
    "start_time": None
}

def start_enrollment_session():
    """Start a voice enrollment session."""
    global _enrollment_session
    _enrollment_session = {
        "active": True,
        "samples": [],
        "start_time": datetime.now().isoformat()
    }
    return {
        "success": True,
        "message": f"Enrollment session started. Please provide {MIN_ENROLLMENT_SAMPLES} voice samples by talking to me normally.",
        "samples_needed": MIN_ENROLLMENT_SAMPLES
    }

def add_enrollment_sample(audio_data):
    """Add a voice sample to the enrollment session."""
    global _enrollment_session

    if not _enrollment_session["active"]:
        return {"success": False, "error": "No active enrollment session"}

    try:
        # Just store the embedding, not the raw audio
        embedding = get_embedding_from_audio(audio_data)
        _enrollment_session["samples"].append(embedding)

        count = len(_enrollment_session["samples"])
        remaining = max(0, MIN_ENROLLMENT_SAMPLES - count)
        can_complete = count >= MIN_ENROLLMENT_SAMPLES

        if can_complete:
            message = f"Sample {count} recorded! You have enough samples - tell me to complete enrollment when ready."
        else:
            message = f"Sample {count}/{MIN_ENROLLMENT_SAMPLES} recorded. {remaining} more needed."

        print(f"[VOICE ENROLL] {message}")

        return {
            "success": True,
            "samples_collected": count,
            "samples_needed": remaining,
            "can_complete": can_complete,
            "message": message
        }
    except Exception as e:
        print(f"[VOICE ENROLL] Error adding sample: {e}")
        return {"success": False, "error": str(e)}

def complete_enrollment():
    """Complete the enrollment session and create the voice profile."""
    global _enrollment_session

    if not _enrollment_session["active"]:
        return {"success": False, "error": "No active enrollment session"}

    samples = _enrollment_session["samples"]
    if len(samples) < MIN_ENROLLMENT_SAMPLES:
        return {"success": False, "error": f"Need at least {MIN_ENROLLMENT_SAMPLES} samples, only have {len(samples)}"}

    # Average the embeddings
    boss_embedding = np.mean(samples, axis=0)

    # Save the profile
    np.save(BOSS_PROFILE_PATH, boss_embedding)

    # Update config
    config = load_voice_config()
    config["boss_enrolled"] = True
    config["enrollment_date"] = datetime.now().isoformat()
    config["num_samples"] = len(samples)
    save_voice_config(config)

    # Clear session
    _enrollment_session = {"active": False, "samples": [], "start_time": None}

    return {
        "success": True,
        "samples_used": len(samples),
        "message": f"Voice profile created with {len(samples)} samples! I'll now recognize your voice."
    }

def cancel_enrollment():
    """Cancel the current enrollment session."""
    global _enrollment_session
    _enrollment_session = {"active": False, "samples": [], "start_time": None}
    return {"success": True, "message": "Enrollment cancelled"}

def is_enrollment_active():
    """Check if enrollment session is active."""
    return _enrollment_session.get("active", False)

def get_enrollment_status():
    """Get current enrollment session status."""
    collected = len(_enrollment_session.get("samples", []))
    return {
        "active": _enrollment_session.get("active", False),
        "samples_collected": collected,
        "samples_needed": max(0, MIN_ENROLLMENT_SAMPLES - collected),
        "samples_required": MIN_ENROLLMENT_SAMPLES,
        "can_complete": collected >= MIN_ENROLLMENT_SAMPLES
    }
