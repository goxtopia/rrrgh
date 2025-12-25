from flask import Flask, render_template, session, jsonify, request
import json
import os
import random
import requests
import time

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cthulhu_fhtagn_dev_key')

CHAPTERS_DIR = 'data/chapters'
# Cache for chapters to avoid re-reading disk too often
CHAPTER_CACHE = {}
RANDOM_EVENTS = []

# In-memory storage for Live Mode sessions (simple dict for prototype)
# Key: session_id (from cookie/secret), Value: list of messages
LIVE_SESSIONS = {}

def load_random_events():
    global RANDOM_EVENTS
    path = 'data/random_events.json'
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                RANDOM_EVENTS = data.get('events', [])
            except json.JSONDecodeError:
                RANDOM_EVENTS = []

# Initial load
load_random_events()

def load_chapter(chapter_name):
    if app.debug or chapter_name not in CHAPTER_CACHE:
        path = os.path.join(CHAPTERS_DIR, f"{chapter_name}.json")
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            CHAPTER_CACHE[chapter_name] = json.load(f)
    return CHAPTER_CACHE[chapter_name]

@app.route('/')
def index():
    return render_template('game.html')

@app.route('/start', methods=['POST'])
def start_game():
    session.clear()
    load_random_events()

    # Default start: chapter01_arrival
    initial_chapter = 'chapter01_arrival'
    story_data = load_chapter(initial_chapter)

    if not story_data:
        # Fallback for compatibility if new files aren't ready
        initial_chapter = 'chapter1'
        story_data = load_chapter(initial_chapter)
        if not story_data:
            return jsonify({'error': 'Story data not found'}), 500

    session['current_chapter'] = initial_chapter

    # Random Start Node logic
    start_node = story_data['start_node']
    if isinstance(start_node, list):
        start_node = random.choice(start_node)

    session['current_node'] = start_node
    session['sanity'] = story_data.get('initial_state', {}).get('sanity', 100)
    session['inventory'] = story_data.get('initial_state', {}).get('inventory', [])
    session['stats'] = story_data.get('initial_state', {}).get('stats', {'str': 10, 'dex': 10, 'int': 10, 'cha': 10})
    session['mode'] = 'story'

    node_data = story_data['nodes'][start_node]
    return jsonify(get_response_payload(node_data))

@app.route('/choice', methods=['POST'])
def make_choice():
    # Detect Mode
    if session.get('mode') == 'live':
        return make_live_choice()

    current_chapter_name = session.get('current_chapter')
    current_node_id = session.get('current_node')
    choice_index = request.json.get('index')

    if not current_chapter_name or not current_node_id:
        return jsonify({'error': 'Game not started'}), 400

    # Special handling for virtual node 'RANDOM_EVENT_Active'
    # Handle return from Random Event (virtual node)
    if current_node_id == 'RANDOM_EVENT_Active':
        # We treat this as a special state where we expect to resume the journey.
        # However, the logic below for standard choice processing will fail because 'RANDOM_EVENT_Active' isn't in a file.
        # We handle the resume logic via the 'RESUME_JOURNEY' choice action later in this function
        # OR we can intercept it here if we simply want to force resume.
        pass

    # If in Random Event state, we construct a virtual node to process the 'Continue' choice
    if current_node_id == 'RANDOM_EVENT_Active':
        node = {
            "choices": [{"text": "Continue", "next_node": "RESUME_JOURNEY"}]
        }
        # The choice index should be 0
    else:
        story_data = load_chapter(current_chapter_name)
        if not story_data:
             return jsonify({'error': 'Chapter data missing'}), 500

        node = story_data['nodes'].get(current_node_id)

    if not node or choice_index is None:
        return jsonify({'error': 'Invalid state'}), 400

    try:
        choice_index = int(choice_index)
        valid_choices_map = []
        for idx, ch in enumerate(node['choices']):
             if check_condition(ch.get('condition')):
                 valid_choices_map.append(idx)

        if choice_index < 0 or choice_index >= len(valid_choices_map):
             return jsonify({'error': 'Invalid choice index'}), 400

        real_index = valid_choices_map[choice_index]
        choice = node['choices'][real_index]

    except (IndexError, ValueError):
         return jsonify({'error': 'Invalid choice'}), 400

    roll_message = None
    next_node_id = choice.get('next_node')
    next_chapter = choice.get('next_chapter')

    # Handle Dice Roll
    if 'roll' in choice:
        roll_data = choice['roll']
        # Default d20 if not specified
        dice_sides = 20
        if 'dice' in roll_data:
            try:
                # Parse "1d20" or just use number
                d_str = str(roll_data['dice']).lower()
                if 'd' in d_str:
                    parts = d_str.split('d')
                    dice_sides = int(parts[1])
                else:
                    dice_sides = int(d_str)
            except (ValueError, IndexError):
                dice_sides = 20

        roll_val = random.randint(1, dice_sides)

        # Add bonus from stat if specified
        bonus = 0
        bonus_stat = roll_data.get('bonus_stat')
        if bonus_stat:
            bonus = session.get('stats', {}).get(bonus_stat, 0)

        total_roll = roll_val + bonus

        # Determine target
        target = roll_data.get('target', 10)
        if isinstance(target, str):
            # Target is a stat name (e.g. 'str') -> Roll against stat (e.g. Roll <= STR)
            target = session.get('stats', {}).get(target, 10)

        # Determine success
        # Condition: 'gt' (roll > target) or 'lte' (roll <= target)
        condition = roll_data.get('condition', 'gt')
        success = False

        check_val = total_roll if bonus_stat else roll_val

        if condition == 'gt':
            success = check_val > target
            comparison_txt = ">"
        elif condition == 'lte':
            success = check_val <= target
            comparison_txt = "<="
        elif condition == 'gte':
            success = check_val >= target
            comparison_txt = ">="
        else:
            success = check_val >= target # Default

        roll_detail = f"{roll_val}+{bonus}" if bonus_stat else f"{roll_val}"
        roll_message = f"🎲 掷骰: {roll_detail} = {check_val} (目标 {comparison_txt} {target}) -> {'成功!' if success else '失败!'}"

        if success:
            next_node_id = roll_data['success_node']
        else:
            next_node_id = roll_data['failure_node']

    # Apply effects
    if 'effect' in choice:
        effects = choice['effect']
        if effects.get('reset'):
            return start_game()

        session['sanity'] = session.get('sanity', 100) + effects.get('sanity', 0)
        if 'add_item' in effects:
            inv = session.get('inventory', [])
            items_to_add = effects['add_item']

            # Handle both single string and list of strings
            if isinstance(items_to_add, list):
                for item in items_to_add:
                    if item not in inv:
                        inv.append(item)
            else:
                if items_to_add not in inv:
                    inv.append(items_to_add)

            session['inventory'] = inv

        if 'update_stats' in effects:
            stats = session.get('stats', {})
            for k, v in effects['update_stats'].items():
                stats[k] = stats.get(k, 10) + v
            session['stats'] = stats

    # Handle Transition

    # Handle Random Events (Interruption)
    # 15% chance, only if not switching chapters (to keep simple) and not a special node
    triggered_event = None
    if not next_chapter and RANDOM_EVENTS and random.random() < 0.15:
        # Don't trigger if the current choice specifically avoids it (optional flag)
        # Pick a random event
        event = random.choice(RANDOM_EVENTS)
        triggered_event = event
        # We don't change session['current_node'] permanently yet,
        # but we serve the event node. The event node MUST have a choice to "Continue"
        # which points to 'next_node_id' (we need to inject this).

        # Actually, a cleaner way is: The event is a transient node.
        # We construct a node on the fly.

        # Store where we were going
        session['resume_node'] = next_node_id
        session['resume_chapter'] = session.get('current_chapter')

        # Override destination to event
        # But wait, random events are generic. We construct the node data here.

        # We need to construct a "virtual" node.
        # This virtual node needs a choice that goes to 'resume_node'

        # Let's just handle it by returning the event payload directly
        # and setting a special 'interruption' state?
        # No, let's keep it consistent. We'll set current_node to "RANDOM_EVENT_X"
        # and store the return path.
        pass # implemented below

    if triggered_event:
        next_node = {
            "text": triggered_event['text'],
            "visual": triggered_event.get('visual', '⚠️'),
            "choices": [
                {
                    "text": "继续前进",
                    "next_node": next_node_id, # Resume path
                    "effect": triggered_event.get('effect', {})
                }
            ]
        }
        # We don't save this node ID in session as it's virtual,
        # but we update the client. When client clicks "Continue",
        # it sends index 0. We need to know we are in an event.
        # Simplest way: Set session['current_node'] to next_node_id (destination)
        # BUT return the Event content.
        # The choice in Event content points to... wait.
        # If we send the Event content, the client sees "Continue".
        # If client clicks "Continue" (index 0), it hits /choice.
        # /choice uses session['current_node'].
        # If we set session['current_node'] to the Destination, then /choice tries to load Destination.
        # Destination choice index 0 might be anything!

        # Solution: We need a temporary state or a dedicated Random Event handling flow.
        # OR: We skip the interruption logic for now and rely on "Variable Text" and "Random Start"
        # which are safer for the requested scope.
        # The prompt asked for "random interruption".

        # Let's try:
        # If triggered, we hijack the response.
        # We set a session flag 'pending_destination' = next_node_id
        # We set session['current_node'] = 'RANDOM_EVENT'
        # We define a 'RANDOM_EVENT' node in memory or handle it in load_chapter?
        # No, simpler:

        # We set next_node to the event data.
        # We make the choice in the event data point to a specific magic node ID "RESUME".
        # In make_choice, if next_node_id == "RESUME", we read 'pending_destination'.

        session['pending_destination'] = next_node_id
        session['pending_chapter'] = next_chapter if next_chapter else session.get('current_chapter')
        session['current_node'] = 'RANDOM_EVENT_Active'

        next_node = {
            "text": triggered_event['text'],
            "visual": triggered_event['visual'],
            "choices": [
                {
                    "text": "继续",
                    "next_node": "RESUME_JOURNEY",
                    "effect": triggered_event.get('effect', {})
                }
            ]
        }

    elif current_node_id == 'RANDOM_EVENT_Active' and choice.get('next_node') == 'RESUME_JOURNEY':
        # We are resuming
        next_node_id = session.get('pending_destination')
        next_chapter = session.get('pending_chapter')

        try:
            # If pending_destination was a list (random outcome), resolve it now
            if isinstance(next_node_id, list):
                next_node_id = random.choice(next_node_id)

            session['current_node'] = next_node_id
            session['current_chapter'] = next_chapter

            # Load the actual destination
            new_story_data = load_chapter(next_chapter)
            if not new_story_data:
                 print(f"ERROR: Pending chapter '{next_chapter}' not found. Current State: {session}")
                 return jsonify({'error': 'Pending chapter not found'}), 500

            # Handle case where next_node_id is missing or incorrect
            next_node = new_story_data['nodes'].get(next_node_id)
            if not next_node:
                # Fallback to chapter start if node is missing (safe recovery)
                print(f"WARNING: Node {next_node_id} not found in {next_chapter}. Falling back to start_node.")
                start_n = new_story_data['start_node']
                if isinstance(start_n, list): start_n = random.choice(start_n)
                session['current_node'] = start_n
                next_node = new_story_data['nodes'][start_n]

        except Exception as e:
            print(f"CRITICAL ERROR in RESUME_JOURNEY: {e}")
            print(f"Debug Info: pending_dest={next_node_id}, pending_chap={next_chapter}")
            # Reset game state to avoid softlock
            return jsonify({'error': 'Critical game state error. Restarting recommended.'}), 500

    elif next_chapter:
        # Switch Chapter
        new_story_data = load_chapter(next_chapter)
        if not new_story_data:
            return jsonify({'error': f'Chapter {next_chapter} not found'}), 500

        session['current_chapter'] = next_chapter
        # If next_node is not specified, use start_node of new chapter
        if not next_node_id:
            next_node_id = new_story_data['start_node']

        # Check for random start in new chapter too?
        if isinstance(next_node_id, list):
             next_node_id = random.choice(next_node_id)

        session['current_node'] = next_node_id
        next_node = new_story_data['nodes'].get(next_node_id)
    else:
        # Same Chapter
        if isinstance(next_node_id, list):
             next_node_id = random.choice(next_node_id)

        session['current_node'] = next_node_id
        next_node = story_data['nodes'].get(next_node_id)

    if not next_node:
         return jsonify({'error': f'Node {next_node_id} not found'}), 500

    payload = get_response_payload(next_node)
    if roll_message:
        payload['roll_message'] = roll_message
    return jsonify(payload)

@app.errorhandler(500)
def internal_error(error):
    app.logger.error('Server Error: %s', error)
    return jsonify({'error': 'Internal Server Error', 'details': str(error)}), 500

@app.errorhandler(400)
def bad_request(error):
    app.logger.error('Bad Request: %s', error)
    return jsonify({'error': 'Bad Request', 'details': str(error)}), 400

def get_response_payload(node):
    valid_choices = []
    # If node has 'choices' list of strings (Live Mode) vs objects (Story Mode)
    # We adapt here or handle it in live logic.
    if node.get('choices') and isinstance(node['choices'][0], dict):
        for ch in node['choices']:
            if check_condition(ch.get('condition')):
                valid_choices.append({'text': ch['text'], 'index': len(valid_choices)})
    elif node.get('choices'):
         # List of strings (from LLM)
         for ch in node['choices']:
             valid_choices.append({'text': ch, 'index': len(valid_choices)})

    # Handle Variable Text
    text_content = node['text']
    if isinstance(text_content, list):
        text_content = random.choice(text_content)

    return {
        'text': text_content,
        'visual': node.get('visual', ''),
        'choices': valid_choices,
        'stats': {
            'sanity': session.get('sanity'),
            'inventory': session.get('inventory'),
            'attributes': session.get('stats', {})
        }
    }

def check_condition(condition):
    if not condition: return True
    if 'has_item' in condition:
        item = condition['has_item']
        inv = session.get('inventory', [])
        # Support list of items (all required)
        if isinstance(item, list):
            for i in item:
                if i not in inv:
                    return False
        # Single item
        elif item not in inv:
            return False
    if 'min_sanity' in condition:
        if session.get('sanity', 0) < condition['min_sanity']:
            return False
    if 'max_sanity' in condition:
        if session.get('sanity', 0) > condition['max_sanity']:
            return False
    return True


# ================= LIVE MODE =================

@app.route('/live/setup', methods=['POST'])
def live_setup():
    data = request.json
    session.clear()
    session['mode'] = 'live'
    session['live_api_endpoint'] = data.get('endpoint', 'https://api.openai.com/v1')
    session['live_api_key'] = data.get('api_key')
    session['live_model'] = data.get('model', 'gpt-3.5-turbo')
    session['live_world'] = data.get('world_prompt') or open('WORLD_DESIGN.md', 'r').read()

    session['sanity'] = 100
    session['inventory'] = []
    session['stats'] = {'str': 10, 'dex': 10}

    # Init session history
    sid = os.urandom(8).hex()
    session['live_sid'] = sid
    LIVE_SESSIONS[sid] = []

    # Generate intro
    return generate_live_turn("GAME_START")

def make_live_choice():
    choice_index = request.json.get('index')
    sid = session.get('live_sid')
    if not sid or sid not in LIVE_SESSIONS:
        return jsonify({'error': 'Live session expired'}), 400

    history = LIVE_SESSIONS[sid]
    # Get last assistant message to find choices
    last_msg = next((m for m in reversed(history) if m['role'] == 'assistant'), None)

    user_action = "Continue"
    if last_msg:
        try:
            content = json.loads(last_msg['content'])
            choices = content.get('choices', [])
            if choice_index is not None and 0 <= int(choice_index) < len(choices):
                user_action = choices[int(choice_index)]
        except:
            pass

    return generate_live_turn(user_action)

def generate_live_turn(user_input):
    sid = session.get('live_sid')
    history = LIVE_SESSIONS[sid]

    # Construct System Prompt if new
    if not history:
        world = session.get('live_world', '')
        sys_prompt = f"""You are the Keeper of Arcane Lore (Game Master) for a retro Cthulhu text adventure.
        World Context: {world}

        Output MUST be valid JSON with this structure:
        {{
            "text": "Narrative description...",
            "visual": "Emoji string (2-4 chars)",
            "choices": ["Choice 1", "Choice 2", ...],
            "update_stats": {{ "sanity": -5, "add_item": "key" }} (Optional)
        }}

        Rules:
        1. Keep descriptions atmospheric but concise (under 200 words).
        2. Provide 2-4 meaningful choices.
        3. Use 'update_stats' to modify player state.
        4. If the user makes a choice that requires a roll, perform the check yourself based on their stats (STR {session['stats']['str']}, DEX {session['stats']['dex']}, SAN {session['sanity']}) and describe the result in the next narrative.
        5. Visuals should be simple emoji combinations like "🌫️⚓" or "🐙😱".
        """
        history.append({"role": "system", "content": sys_prompt})

    # Add User Input
    history.append({"role": "user", "content": f"Player Action: {user_input}. Current State: Sanity {session['sanity']}, Inventory {session['inventory']}"})

    # Call API
    api_key = session.get('live_api_key')
    endpoint = session.get('live_api_endpoint')
    model = session.get('live_model')

    response_json = {}

    if not api_key:
        # MOCK MODE
        time.sleep(1) # Simulate latency
        response_json = {
            "text": "[MOCK MODE] The LLM API Key is missing. You find yourself in a void of simulation. The Keeper is silent.",
            "visual": "🤖🚫",
            "choices": ["Restart Setup"],
            "update_stats": {}
        }
        if user_input == "GAME_START":
             response_json["text"] = "[MOCK MODE] You stand at the edge of the digital abyss. This is a simulation because no API Key was provided."
    else:
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            # Handle potential trailing slash issues
            url = f"{endpoint.rstrip('/')}/chat/completions"

            payload = {
                "model": model,
                "messages": history,
                "temperature": 0.7
            }

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            r.raise_for_status()
            res_data = r.json()
            content_str = res_data['choices'][0]['message']['content']

            # Extract JSON from potential markdown code blocks
            if "```json" in content_str:
                content_str = content_str.split("```json")[1].split("```")[0].strip()
            elif "```" in content_str:
                content_str = content_str.split("```")[1].strip()

            response_json = json.loads(content_str)
            history.append({"role": "assistant", "content": content_str})

        except Exception as e:
             response_json = {
                "text": f"The Keeper's voice is distorted (API Error: {str(e)})",
                "visual": "⚠️🔌",
                "choices": ["Try Again"],
                "update_stats": {}
            }

    # Process updates
    if 'update_stats' in response_json:
        updates = response_json['update_stats']
        session['sanity'] = session.get('sanity', 100) + updates.get('sanity', 0)

        item = updates.get('add_item')
        if item:
            inv = session.get('inventory', [])
            if item not in inv:
                inv.append(item)
            session['inventory'] = inv

    return jsonify(get_response_payload(response_json))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
