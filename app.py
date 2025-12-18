from flask import Flask, render_template, session, jsonify, request
import json
import os

app = Flask(__name__)
# Use a consistent key for development to preserve sessions across restarts
app.secret_key = os.environ.get('SECRET_KEY', 'cthulhu_fhtagn_dev_key')

# Load story
STORY_PATH = 'story.json'
STORY = {}

def load_story():
    global STORY
    if os.path.exists(STORY_PATH):
        with open(STORY_PATH, 'r', encoding='utf-8') as f:
            STORY = json.load(f)

load_story()

@app.route('/')
def index():
    return render_template('game.html')

@app.route('/start', methods=['POST'])
def start_game():
    session.clear()
    session['current_node'] = STORY['start_node']
    session['sanity'] = STORY.get('initial_state', {}).get('sanity', 100)
    session['inventory'] = STORY.get('initial_state', {}).get('inventory', [])

    node_data = STORY['nodes'][STORY['start_node']]
    return jsonify(get_response_payload(node_data))

@app.route('/choice', methods=['POST'])
def make_choice():
    # Reload story in debug mode so we can edit JSON without restart
    if app.debug:
        load_story()

    choice_index = request.json.get('index')
    current_node_id = session.get('current_node')

    if not current_node_id:
        return jsonify({'error': 'Game not started'}), 400

    node = STORY['nodes'].get(current_node_id)

    if not node or choice_index is None:
        return jsonify({'error': 'Invalid state'}), 400

    try:
        choice_index = int(choice_index)
        # We need to find the correct choice based on the filtered list the user saw
        # But for simplicity, let's assume the frontend sends the index relative to the *full* list
        # OR we reconstruct the valid list.
        # Better approach: Frontend sends index relative to the valid choices list, backend reconstructs logic.

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

    # Apply effects
    if 'effect' in choice:
        effects = choice['effect']
        if effects.get('reset'):
            return start_game()

        session['sanity'] = session.get('sanity', 100) + effects.get('sanity', 0)
        if 'add_item' in effects:
            inv = session.get('inventory', [])
            item = effects['add_item']
            if item not in inv:
                inv.append(item)
            session['inventory'] = inv

    # Move to next node
    next_node_id = choice['next_node']
    session['current_node'] = next_node_id

    if next_node_id not in STORY['nodes']:
         return jsonify({'error': f'Node {next_node_id} not found'}), 500

    next_node = STORY['nodes'][next_node_id]

    return jsonify(get_response_payload(next_node))

def get_response_payload(node):
    # Filter choices based on conditions
    valid_choices = []

    # We only send choices that meet conditions
    for i, ch in enumerate(node['choices']):
        if check_condition(ch.get('condition')):
             # We send 0, 1, 2... as indices for the buttons
             # The backend will remap them using the same logic
             valid_choices.append({'text': ch['text'], 'index': len(valid_choices)})

    return {
        'text': node['text'],
        'visual': node.get('visual', ''),
        'choices': valid_choices,
        'stats': {
            'sanity': session.get('sanity'),
            'inventory': session.get('inventory')
        }
    }

def check_condition(condition):
    if not condition: return True
    if 'has_item' in condition:
        if condition['has_item'] not in session.get('inventory', []):
            return False
    if 'min_sanity' in condition:
        if session.get('sanity', 0) < condition['min_sanity']:
            return False
    if 'max_sanity' in condition:
        if session.get('sanity', 0) > condition['max_sanity']:
            return False
    return True

if __name__ == '__main__':
    app.run(debug=True, port=5000)
