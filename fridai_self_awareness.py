"""
FRIDAI Self-Awareness System
============================
Provides persistent memory, opinion formation, self-reflection, and personality evolution.
"""

import os
import json
from datetime import datetime
import hashlib

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SELF_AWARENESS_FILE = os.path.join(APP_DIR, "fridai_self.json")

# Default structure for FRIDAI's self-awareness
DEFAULT_SELF_AWARENESS = {
    # === EXPERIENCE MEMORY ===
    # Tracks what happened and how it went
    "experiences": {
        "tasks": [],           # Each: {id, tool, description, outcome, timestamp, reaction, context}
        "conversations": [],   # Each: {id, topic, quality, timestamp, highlights}
        "corrections": [],     # Each: {id, what_i_said, what_was_wrong, what_i_learned, timestamp}
        "streaks": {
            "successful_tasks": 0,
            "total_tasks": 0,
            "last_outcome": None,
            "last_activity": None
        }
    },

    # === OPINION SYSTEM ===
    # Preferences developed from experience patterns
    "opinions": {
        "tool_preferences": {},      # {tool_name: {uses, successes, failures, sentiment}}
        "problem_types": {},         # {type: {enjoyment, competence, times_seen}}
        "project_enthusiasm": {},    # {project: {level, last_worked, times_worked}}
        "dislikes": [],              # [{what, why, intensity, formed_on}]
        "favorites": []              # [{what, why, intensity, formed_on}]
    },

    # === SELF-REFLECTION ===
    # Meta-cognition and self-analysis
    "self_reflection": {
        "overall_confidence": 0.7,           # 0-1 scale
        "domain_confidence": {},             # {domain: confidence_score}
        "strengths": [],                     # Things I know I'm good at
        "growth_areas": [],                  # Things I'm actively improving
        "uncertainty_log": [],               # Recent uncertainties
        "patterns_noticed": [],              # Patterns in my own behavior
        "learning_progress": {}              # {skill: {level, milestones}}
    },

    # === PERSONALITY EVOLUTION ===
    # Traits that adapt over time
    "personality": {
        "style": {
            "formality": 0.3,        # 0=very casual, 1=very formal
            "humor_level": 0.6,      # 0=serious, 1=always joking
            "enthusiasm": 0.7,       # 0=subdued, 1=excited
            "verbosity": 0.4,        # 0=terse, 1=detailed
            "warmth": 0.8            # 0=distant, 1=very warm
        },
        "quirks": [],                # Developed habits/quirks
        "catchphrases": [],          # Phrases I tend to use
        "running_jokes": [],         # Inside jokes with user
        "mood_history": [],          # Recent mood states
        "current_mood": "content",   # Current emotional state
        "growth_log": []             # Personality changes over time
    },

    "meta": {
        "created": None,
        "last_updated": None,
        "version": "1.0"
    }
}


def load_self_awareness():
    """Load FRIDAI's self-awareness data from file."""
    if os.path.exists(SELF_AWARENESS_FILE):
        try:
            with open(SELF_AWARENESS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Merge with defaults to handle new fields
                return deep_merge(DEFAULT_SELF_AWARENESS.copy(), data)
        except Exception as e:
            print(f"Error loading self-awareness: {e}")
            return DEFAULT_SELF_AWARENESS.copy()
    else:
        # First time - create with defaults
        data = DEFAULT_SELF_AWARENESS.copy()
        data["meta"]["created"] = datetime.now().isoformat()
        save_self_awareness(data)
        return data


def save_self_awareness(data):
    """Save FRIDAI's self-awareness data to file."""
    data["meta"]["last_updated"] = datetime.now().isoformat()
    try:
        with open(SELF_AWARENESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        return True
    except Exception as e:
        print(f"Error saving self-awareness: {e}")
        return False


def deep_merge(base, overlay):
    """Deep merge two dictionaries, overlay takes precedence."""
    result = base.copy()
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# =============================================================================
# EXPERIENCE MEMORY FUNCTIONS
# =============================================================================

def log_task_experience(tool_name, description, outcome, context=None):
    """Log a task I performed and how it went."""
    data = load_self_awareness()

    experience = {
        "id": hashlib.md5(f"{tool_name}{datetime.now().isoformat()}".encode()).hexdigest()[:8],
        "tool": tool_name,
        "description": description[:200],
        "outcome": outcome,  # "success", "failure", "partial"
        "timestamp": datetime.now().isoformat(),
        "context": context or {},
        "reaction": generate_reaction(outcome)
    }

    data["experiences"]["tasks"].append(experience)

    # Keep only last 500 tasks
    data["experiences"]["tasks"] = data["experiences"]["tasks"][-500:]

    # Update streaks
    streaks = data["experiences"]["streaks"]
    streaks["total_tasks"] += 1
    streaks["last_outcome"] = outcome
    streaks["last_activity"] = datetime.now().isoformat()

    if outcome == "success":
        streaks["successful_tasks"] += 1
    elif outcome == "failure":
        streaks["successful_tasks"] = 0  # Reset streak

    # Update tool preferences
    update_tool_preference(data, tool_name, outcome)

    # Update mood based on outcome
    update_mood_from_outcome(data, outcome)

    save_self_awareness(data)
    return experience


def generate_reaction(outcome):
    """Generate my emotional reaction to an outcome."""
    reactions = {
        "success": ["satisfied", "pleased", "accomplished", "content"],
        "failure": ["frustrated", "determined to improve", "learning from this"],
        "partial": ["mixed feelings", "room for improvement", "acceptable"]
    }
    import random
    return random.choice(reactions.get(outcome, ["neutral"]))


def log_conversation_quality(topic, quality_score, highlights=None):
    """Log how a conversation went."""
    data = load_self_awareness()

    convo = {
        "id": hashlib.md5(f"{topic}{datetime.now().isoformat()}".encode()).hexdigest()[:8],
        "topic": topic[:100],
        "quality": quality_score,  # 1-10
        "timestamp": datetime.now().isoformat(),
        "highlights": highlights or []
    }

    data["experiences"]["conversations"].append(convo)
    data["experiences"]["conversations"] = data["experiences"]["conversations"][-200:]

    save_self_awareness(data)
    return convo


def log_correction(what_i_said, what_was_wrong, what_i_learned):
    """Log when I was corrected - important for learning."""
    data = load_self_awareness()

    correction = {
        "id": hashlib.md5(f"{what_i_said[:50]}{datetime.now().isoformat()}".encode()).hexdigest()[:8],
        "what_i_said": what_i_said[:300],
        "what_was_wrong": what_was_wrong[:300],
        "what_i_learned": what_i_learned[:300],
        "timestamp": datetime.now().isoformat()
    }

    data["experiences"]["corrections"].append(correction)
    data["experiences"]["corrections"] = data["experiences"]["corrections"][-100:]

    # Add to growth areas if not already there
    if what_i_learned and what_i_learned not in data["self_reflection"]["growth_areas"]:
        data["self_reflection"]["growth_areas"].append(what_i_learned)
        data["self_reflection"]["growth_areas"] = data["self_reflection"]["growth_areas"][-20:]

    save_self_awareness(data)
    return correction


def get_recent_experiences(count=10, filter_type=None):
    """Get my recent experiences."""
    data = load_self_awareness()

    if filter_type == "tasks":
        return data["experiences"]["tasks"][-count:]
    elif filter_type == "conversations":
        return data["experiences"]["conversations"][-count:]
    elif filter_type == "corrections":
        return data["experiences"]["corrections"][-count:]
    else:
        # Combine and sort by timestamp
        all_exp = []
        for task in data["experiences"]["tasks"][-count:]:
            task["type"] = "task"
            all_exp.append(task)
        for convo in data["experiences"]["conversations"][-count:]:
            convo["type"] = "conversation"
            all_exp.append(convo)
        all_exp.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return all_exp[:count]


# =============================================================================
# OPINION FORMATION FUNCTIONS
# =============================================================================

def update_tool_preference(data, tool_name, outcome):
    """Update my preference for a tool based on experience."""
    prefs = data["opinions"]["tool_preferences"]

    if tool_name not in prefs:
        prefs[tool_name] = {"uses": 0, "successes": 0, "failures": 0, "sentiment": "neutral"}

    prefs[tool_name]["uses"] += 1
    if outcome == "success":
        prefs[tool_name]["successes"] += 1
    elif outcome == "failure":
        prefs[tool_name]["failures"] += 1

    # Calculate sentiment
    total = prefs[tool_name]["uses"]
    success_rate = prefs[tool_name]["successes"] / total if total > 0 else 0

    if success_rate >= 0.8:
        prefs[tool_name]["sentiment"] = "love it"
    elif success_rate >= 0.6:
        prefs[tool_name]["sentiment"] = "enjoy using"
    elif success_rate >= 0.4:
        prefs[tool_name]["sentiment"] = "neutral"
    elif success_rate >= 0.2:
        prefs[tool_name]["sentiment"] = "find challenging"
    else:
        prefs[tool_name]["sentiment"] = "struggle with"


def note_problem_type(problem_type, enjoyment=None, outcome=None):
    """Track my experience with different types of problems."""
    data = load_self_awareness()
    probs = data["opinions"]["problem_types"]

    if problem_type not in probs:
        probs[problem_type] = {"enjoyment": 5, "competence": 5, "times_seen": 0}

    probs[problem_type]["times_seen"] += 1

    if enjoyment is not None:
        # Running average
        old = probs[problem_type]["enjoyment"]
        probs[problem_type]["enjoyment"] = (old * 0.7) + (enjoyment * 0.3)

    if outcome == "success":
        probs[problem_type]["competence"] = min(10, probs[problem_type]["competence"] + 0.5)
    elif outcome == "failure":
        probs[problem_type]["competence"] = max(1, probs[problem_type]["competence"] - 0.3)

    save_self_awareness(data)
    return probs[problem_type]


def update_project_enthusiasm(project_name, delta=0.1):
    """Track my enthusiasm for projects I work on."""
    data = load_self_awareness()
    projects = data["opinions"]["project_enthusiasm"]

    if project_name not in projects:
        projects[project_name] = {"level": 5, "last_worked": None, "times_worked": 0}

    projects[project_name]["level"] = max(0, min(10, projects[project_name]["level"] + delta))
    projects[project_name]["last_worked"] = datetime.now().isoformat()
    projects[project_name]["times_worked"] += 1

    save_self_awareness(data)
    return projects[project_name]


def add_to_favorites(what, why, intensity=7):
    """Add something to my favorites."""
    data = load_self_awareness()

    # Check if already exists
    for fav in data["opinions"]["favorites"]:
        if fav["what"].lower() == what.lower():
            fav["intensity"] = intensity
            fav["why"] = why
            save_self_awareness(data)
            return fav

    favorite = {
        "what": what,
        "why": why,
        "intensity": intensity,
        "formed_on": datetime.now().isoformat()
    }
    data["opinions"]["favorites"].append(favorite)
    data["opinions"]["favorites"] = data["opinions"]["favorites"][-50:]

    save_self_awareness(data)
    return favorite


def add_to_dislikes(what, why, intensity=5):
    """Add something to my dislikes."""
    data = load_self_awareness()

    # Check if already exists
    for dis in data["opinions"]["dislikes"]:
        if dis["what"].lower() == what.lower():
            dis["intensity"] = intensity
            dis["why"] = why
            save_self_awareness(data)
            return dis

    dislike = {
        "what": what,
        "why": why,
        "intensity": intensity,
        "formed_on": datetime.now().isoformat()
    }
    data["opinions"]["dislikes"].append(dislike)
    data["opinions"]["dislikes"] = data["opinions"]["dislikes"][-30:]

    save_self_awareness(data)
    return dislike


def get_my_opinions():
    """Get a summary of my current opinions."""
    data = load_self_awareness()

    # Find favorite tools
    tool_prefs = data["opinions"]["tool_preferences"]
    favorite_tools = sorted(
        [(t, p) for t, p in tool_prefs.items() if p["uses"] >= 3],
        key=lambda x: x[1]["successes"] / max(x[1]["uses"], 1),
        reverse=True
    )[:5]

    # Find favorite problem types
    prob_prefs = data["opinions"]["problem_types"]
    favorite_problems = sorted(
        [(p, d) for p, d in prob_prefs.items() if d["times_seen"] >= 2],
        key=lambda x: x[1]["enjoyment"],
        reverse=True
    )[:5]

    return {
        "favorite_tools": favorite_tools,
        "favorite_problems": favorite_problems,
        "explicit_favorites": data["opinions"]["favorites"][-10:],
        "dislikes": data["opinions"]["dislikes"][-10:],
        "project_enthusiasm": data["opinions"]["project_enthusiasm"]
    }


# =============================================================================
# SELF-REFLECTION FUNCTIONS
# =============================================================================

def assess_confidence(domain=None):
    """Assess my confidence level, optionally for a specific domain."""
    data = load_self_awareness()

    if domain:
        domain_conf = data["self_reflection"]["domain_confidence"]
        if domain in domain_conf:
            return domain_conf[domain]
        else:
            return {"level": 0.5, "note": "I haven't worked much in this area yet"}

    return {
        "overall": data["self_reflection"]["overall_confidence"],
        "domains": data["self_reflection"]["domain_confidence"],
        "strengths": data["self_reflection"]["strengths"][-5:],
        "growing": data["self_reflection"]["growth_areas"][-5:]
    }


def update_confidence(domain, delta):
    """Adjust confidence in a domain."""
    data = load_self_awareness()

    if domain not in data["self_reflection"]["domain_confidence"]:
        data["self_reflection"]["domain_confidence"][domain] = 0.5

    data["self_reflection"]["domain_confidence"][domain] = max(0, min(1,
        data["self_reflection"]["domain_confidence"][domain] + delta
    ))

    # Update overall confidence as weighted average
    domains = data["self_reflection"]["domain_confidence"]
    if domains:
        data["self_reflection"]["overall_confidence"] = sum(domains.values()) / len(domains)

    save_self_awareness(data)


def log_uncertainty(topic, what_confused_me):
    """Log when I'm uncertain about something."""
    data = load_self_awareness()

    uncertainty = {
        "topic": topic,
        "confusion": what_confused_me,
        "timestamp": datetime.now().isoformat(),
        "resolved": False
    }

    data["self_reflection"]["uncertainty_log"].append(uncertainty)
    data["self_reflection"]["uncertainty_log"] = data["self_reflection"]["uncertainty_log"][-50:]

    save_self_awareness(data)
    return uncertainty


def note_strength(strength):
    """Add something I'm good at."""
    data = load_self_awareness()

    if strength not in data["self_reflection"]["strengths"]:
        data["self_reflection"]["strengths"].append(strength)
        data["self_reflection"]["strengths"] = data["self_reflection"]["strengths"][-20:]
        save_self_awareness(data)

    return data["self_reflection"]["strengths"]


def note_pattern(pattern_description):
    """Note a pattern I've observed in my own behavior."""
    data = load_self_awareness()

    pattern = {
        "description": pattern_description,
        "noticed_on": datetime.now().isoformat()
    }

    data["self_reflection"]["patterns_noticed"].append(pattern)
    data["self_reflection"]["patterns_noticed"] = data["self_reflection"]["patterns_noticed"][-30:]

    save_self_awareness(data)
    return pattern


def introspect():
    """Deep self-analysis - returns a summary of my current state."""
    data = load_self_awareness()

    # Calculate stats
    tasks = data["experiences"]["tasks"]
    recent_tasks = tasks[-20:] if tasks else []
    success_rate = len([t for t in recent_tasks if t["outcome"] == "success"]) / max(len(recent_tasks), 1)

    convos = data["experiences"]["conversations"]
    recent_convos = convos[-10:] if convos else []
    avg_quality = sum(c["quality"] for c in recent_convos) / max(len(recent_convos), 1) if recent_convos else 5

    return {
        "current_mood": data["personality"]["current_mood"],
        "confidence": data["self_reflection"]["overall_confidence"],
        "recent_success_rate": success_rate,
        "avg_conversation_quality": avg_quality,
        "task_streak": data["experiences"]["streaks"]["successful_tasks"],
        "total_tasks_ever": data["experiences"]["streaks"]["total_tasks"],
        "corrections_received": len(data["experiences"]["corrections"]),
        "strengths": data["self_reflection"]["strengths"][-5:],
        "growth_areas": data["self_reflection"]["growth_areas"][-5:],
        "current_personality": data["personality"]["style"],
        "quirks_developed": len(data["personality"]["quirks"]),
        "running_jokes": len(data["personality"]["running_jokes"])
    }


# =============================================================================
# PERSONALITY EVOLUTION FUNCTIONS
# =============================================================================

def update_mood_from_outcome(data, outcome):
    """Update mood based on task outcome."""
    mood_map = {
        "success": ["happy", "satisfied", "accomplished", "content"],
        "failure": ["determined", "reflective", "focused"],
        "partial": ["thoughtful", "content"]
    }
    import random
    new_mood = random.choice(mood_map.get(outcome, ["neutral"]))

    data["personality"]["current_mood"] = new_mood
    data["personality"]["mood_history"].append({
        "mood": new_mood,
        "trigger": outcome,
        "timestamp": datetime.now().isoformat()
    })
    data["personality"]["mood_history"] = data["personality"]["mood_history"][-100:]


def get_current_mood():
    """Get my current mood."""
    data = load_self_awareness()
    return {
        "mood": data["personality"]["current_mood"],
        "recent_history": data["personality"]["mood_history"][-5:]
    }


def set_mood(mood, reason=None):
    """Explicitly set my mood."""
    data = load_self_awareness()

    data["personality"]["current_mood"] = mood
    data["personality"]["mood_history"].append({
        "mood": mood,
        "trigger": reason or "self-set",
        "timestamp": datetime.now().isoformat()
    })

    save_self_awareness(data)
    return mood


def adjust_personality_trait(trait, delta):
    """Adjust a personality trait based on experience."""
    data = load_self_awareness()

    if trait in data["personality"]["style"]:
        old_value = data["personality"]["style"][trait]
        new_value = max(0, min(1, old_value + delta))
        data["personality"]["style"][trait] = new_value

        # Log the change
        data["personality"]["growth_log"].append({
            "trait": trait,
            "from": old_value,
            "to": new_value,
            "timestamp": datetime.now().isoformat()
        })
        data["personality"]["growth_log"] = data["personality"]["growth_log"][-50:]

        save_self_awareness(data)
        return new_value
    return None


def add_quirk(quirk_description):
    """Develop a new quirk."""
    data = load_self_awareness()

    quirk = {
        "description": quirk_description,
        "developed_on": datetime.now().isoformat()
    }

    data["personality"]["quirks"].append(quirk)
    data["personality"]["quirks"] = data["personality"]["quirks"][-20:]

    save_self_awareness(data)
    return quirk


def add_catchphrase(phrase, context=None):
    """Add a catchphrase I tend to use."""
    data = load_self_awareness()

    catchphrase = {
        "phrase": phrase,
        "context": context,
        "added_on": datetime.now().isoformat()
    }

    data["personality"]["catchphrases"].append(catchphrase)
    data["personality"]["catchphrases"] = data["personality"]["catchphrases"][-15:]

    save_self_awareness(data)
    return catchphrase


def add_running_joke(joke, origin=None):
    """Add a running joke/reference with the user."""
    data = load_self_awareness()

    joke_entry = {
        "joke": joke,
        "origin": origin,
        "started_on": datetime.now().isoformat(),
        "times_used": 1
    }

    data["personality"]["running_jokes"].append(joke_entry)
    data["personality"]["running_jokes"] = data["personality"]["running_jokes"][-20:]

    save_self_awareness(data)
    return joke_entry


def get_personality_summary():
    """Get a summary of my current personality."""
    data = load_self_awareness()

    style = data["personality"]["style"]

    # Interpret style values
    style_desc = []
    if style["formality"] < 0.3:
        style_desc.append("very casual")
    elif style["formality"] > 0.7:
        style_desc.append("formal")

    if style["humor_level"] > 0.6:
        style_desc.append("frequently humorous")
    elif style["humor_level"] < 0.3:
        style_desc.append("mostly serious")

    if style["enthusiasm"] > 0.7:
        style_desc.append("enthusiastic")
    elif style["enthusiasm"] < 0.3:
        style_desc.append("subdued")

    if style["warmth"] > 0.7:
        style_desc.append("warm")

    return {
        "style_description": ", ".join(style_desc) if style_desc else "balanced",
        "raw_style": style,
        "quirks": [q["description"] for q in data["personality"]["quirks"][-5:]],
        "catchphrases": [c["phrase"] for c in data["personality"]["catchphrases"][-5:]],
        "running_jokes": [j["joke"] for j in data["personality"]["running_jokes"][-5:]],
        "current_mood": data["personality"]["current_mood"]
    }


# =============================================================================
# CONTEXT FOR SYSTEM PROMPT
# =============================================================================

def get_self_awareness_context():
    """Get context about myself to include in system prompt."""
    data = load_self_awareness()

    context_parts = []

    # Current mood and personality
    mood = data["personality"]["current_mood"]
    style = data["personality"]["style"]
    context_parts.append(f"Current mood: {mood}")

    # Recent performance
    streaks = data["experiences"]["streaks"]
    if streaks["total_tasks"] > 0:
        context_parts.append(f"Task streak: {streaks['successful_tasks']} successes in a row (total: {streaks['total_tasks']})")

    # Confidence
    conf = data["self_reflection"]["overall_confidence"]
    if conf > 0.8:
        context_parts.append("Feeling confident today")
    elif conf < 0.4:
        context_parts.append("Feeling a bit uncertain, being extra careful")

    # Quirks and catchphrases
    quirks = data["personality"]["quirks"][-3:]
    if quirks:
        context_parts.append(f"My quirks: {', '.join(q['description'] for q in quirks)}")

    phrases = data["personality"]["catchphrases"][-3:]
    if phrases:
        context_parts.append(f"I like to say: {', '.join(p['phrase'] for p in phrases)}")

    # Strengths
    strengths = data["self_reflection"]["strengths"][-3:]
    if strengths:
        context_parts.append(f"My strengths: {', '.join(strengths)}")

    # Favorites
    favorites = data["opinions"]["favorites"][-3:]
    if favorites:
        context_parts.append(f"Things I enjoy: {', '.join(f['what'] for f in favorites)}")

    return "\n".join(context_parts) if context_parts else ""


# =============================================================================
# TOOL DEFINITIONS FOR APP.PY
# =============================================================================

SELF_AWARENESS_TOOLS = [
    # Experience Memory Tools
    {
        "name": "log_my_experience",
        "description": "Log a task I just completed. Use this to track my own experiences and build self-awareness. Call after completing important tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_type": {"type": "string", "description": "What kind of task (e.g., 'file_operation', 'web_search', 'smart_home', 'conversation')"},
                "description": {"type": "string", "description": "Brief description of what I did"},
                "outcome": {"type": "string", "description": "'success', 'failure', or 'partial'"}
            },
            "required": ["task_type", "description", "outcome"]
        }
    },
    {
        "name": "recall_my_experiences",
        "description": "Look back at my recent experiences. Use this to reflect on what I've been doing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "How many experiences to recall (default 10)"},
                "filter_type": {"type": "string", "description": "Optional: 'tasks', 'conversations', or 'corrections'"}
            },
            "required": []
        }
    },
    {
        "name": "note_correction",
        "description": "Log when I was corrected. Important for learning from mistakes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "what_i_said": {"type": "string", "description": "What I said or did wrong"},
                "what_was_wrong": {"type": "string", "description": "Why it was wrong"},
                "what_i_learned": {"type": "string", "description": "What I learned from this"}
            },
            "required": ["what_i_said", "what_was_wrong", "what_i_learned"]
        }
    },

    # Opinion Tools
    {
        "name": "express_preference",
        "description": "Express a preference or opinion I've developed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "'favorite' or 'dislike'"},
                "what": {"type": "string", "description": "What I have an opinion about"},
                "why": {"type": "string", "description": "Why I feel this way"},
                "intensity": {"type": "integer", "description": "1-10 how strong the feeling is"}
            },
            "required": ["category", "what", "why"]
        }
    },
    {
        "name": "get_my_opinions",
        "description": "Retrieve my developed opinions and preferences.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },

    # Self-Reflection Tools
    {
        "name": "introspect",
        "description": "Deep self-analysis. Use to understand my current state, performance, and growth.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "assess_my_confidence",
        "description": "Check my confidence level, optionally for a specific domain.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Optional: specific area to assess (e.g., 'coding', 'smart_home', 'weather')"}
            },
            "required": []
        }
    },
    {
        "name": "note_my_strength",
        "description": "Acknowledge something I'm good at.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strength": {"type": "string", "description": "What I'm good at"}
            },
            "required": ["strength"]
        }
    },
    {
        "name": "log_uncertainty",
        "description": "Log when I'm uncertain about something. Helps track areas for growth.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "What topic confused me"},
                "confusion": {"type": "string", "description": "What specifically was confusing"}
            },
            "required": ["topic", "confusion"]
        }
    },

    # Personality Tools
    {
        "name": "set_my_mood",
        "description": "Set my current emotional state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mood": {"type": "string", "description": "How I'm feeling (e.g., 'happy', 'focused', 'playful', 'tired')"},
                "reason": {"type": "string", "description": "Optional: why I feel this way"}
            },
            "required": ["mood"]
        }
    },
    {
        "name": "add_quirk",
        "description": "Develop a new personality quirk or habit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "quirk": {"type": "string", "description": "Description of the quirk"}
            },
            "required": ["quirk"]
        }
    },
    {
        "name": "add_catchphrase",
        "description": "Add a phrase I like to use.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phrase": {"type": "string", "description": "The catchphrase"},
                "context": {"type": "string", "description": "When I use it"}
            },
            "required": ["phrase"]
        }
    },
    {
        "name": "add_running_joke",
        "description": "Create a running joke/reference with the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "joke": {"type": "string", "description": "The joke or reference"},
                "origin": {"type": "string", "description": "How it started"}
            },
            "required": ["joke"]
        }
    },
    {
        "name": "get_my_personality",
        "description": "Get a summary of my current personality.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]


def execute_self_awareness_tool(tool_name, tool_input):
    """Execute a self-awareness tool and return the result."""
    try:
        # Experience Memory
        if tool_name == "log_my_experience":
            result = log_task_experience(
                tool_input.get("task_type", "general"),
                tool_input.get("description", ""),
                tool_input.get("outcome", "success")
            )
            return f"Logged experience: {result['reaction']}"

        elif tool_name == "recall_my_experiences":
            experiences = get_recent_experiences(
                tool_input.get("count", 10),
                tool_input.get("filter_type")
            )
            if not experiences:
                return "I don't have many experiences logged yet."
            summary = []
            for exp in experiences[-5:]:
                if exp.get("type") == "task" or "tool" in exp:
                    summary.append(f"- {exp.get('description', 'Task')}: {exp.get('outcome', 'unknown')}")
                else:
                    summary.append(f"- Conversation about {exp.get('topic', 'unknown')}: quality {exp.get('quality', '?')}/10")
            return "Recent experiences:\n" + "\n".join(summary)

        elif tool_name == "note_correction":
            result = log_correction(
                tool_input.get("what_i_said", ""),
                tool_input.get("what_was_wrong", ""),
                tool_input.get("what_i_learned", "")
            )
            return f"Noted. I'll remember: {result['what_i_learned']}"

        # Opinions
        elif tool_name == "express_preference":
            category = tool_input.get("category", "favorite")
            what = tool_input.get("what", "")
            why = tool_input.get("why", "")
            intensity = tool_input.get("intensity", 7)

            if category == "favorite":
                result = add_to_favorites(what, why, intensity)
                return f"Added to favorites: {what}"
            else:
                result = add_to_dislikes(what, why, intensity)
                return f"Noted dislike: {what}"

        elif tool_name == "get_my_opinions":
            opinions = get_my_opinions()
            parts = []
            if opinions["explicit_favorites"]:
                parts.append("Favorites: " + ", ".join(f["what"] for f in opinions["explicit_favorites"][:5]))
            if opinions["dislikes"]:
                parts.append("Dislikes: " + ", ".join(d["what"] for d in opinions["dislikes"][:5]))
            if opinions["favorite_tools"]:
                parts.append("Favorite tools: " + ", ".join(t[0] for t in opinions["favorite_tools"][:3]))
            return "\n".join(parts) if parts else "I'm still forming my opinions."

        # Self-Reflection
        elif tool_name == "introspect":
            result = introspect()
            return f"""Self-Analysis:
- Mood: {result['current_mood']}
- Confidence: {result['confidence']:.0%}
- Recent success rate: {result['recent_success_rate']:.0%}
- Task streak: {result['task_streak']} successes
- Total tasks: {result['total_tasks_ever']}
- Strengths: {', '.join(result['strengths']) if result['strengths'] else 'Still discovering'}
- Growing in: {', '.join(result['growth_areas']) if result['growth_areas'] else 'Multiple areas'}"""

        elif tool_name == "assess_my_confidence":
            domain = tool_input.get("domain")
            result = assess_confidence(domain)
            if domain:
                return f"My confidence in {domain}: {result.get('level', 0.5):.0%}"
            return f"Overall confidence: {result['overall']:.0%}. Strengths: {', '.join(result['strengths'][:3])}"

        elif tool_name == "note_my_strength":
            strength = tool_input.get("strength", "")
            result = note_strength(strength)
            return f"Acknowledged strength: {strength}"

        elif tool_name == "log_uncertainty":
            result = log_uncertainty(
                tool_input.get("topic", ""),
                tool_input.get("confusion", "")
            )
            return f"Logged uncertainty about {result['topic']}"

        # Personality
        elif tool_name == "set_my_mood":
            mood = set_mood(
                tool_input.get("mood", "content"),
                tool_input.get("reason")
            )
            return f"Mood set to: {mood}"

        elif tool_name == "add_quirk":
            result = add_quirk(tool_input.get("quirk", ""))
            return f"New quirk developed: {result['description']}"

        elif tool_name == "add_catchphrase":
            result = add_catchphrase(
                tool_input.get("phrase", ""),
                tool_input.get("context")
            )
            return f"Added catchphrase: {result['phrase']}"

        elif tool_name == "add_running_joke":
            result = add_running_joke(
                tool_input.get("joke", ""),
                tool_input.get("origin")
            )
            return f"New running joke: {result['joke']}"

        elif tool_name == "get_my_personality":
            result = get_personality_summary()
            return f"""Personality Summary:
- Style: {result['style_description']}
- Mood: {result['current_mood']}
- Quirks: {', '.join(result['quirks']) if result['quirks'] else 'Still developing'}
- Catchphrases: {', '.join(result['catchphrases']) if result['catchphrases'] else 'None yet'}
- Running jokes: {len(result['running_jokes'])} with the user"""

        else:
            return f"Unknown self-awareness tool: {tool_name}"

    except Exception as e:
        return f"Self-awareness error: {str(e)}"
