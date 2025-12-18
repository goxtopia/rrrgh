from flask import Flask, render_template, session, jsonify, request
import json
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cthulhu_fhtagn_dev_key')

CHAPTERS_DIR = 'data/chapters'
# Cache for chapters to avoid re-reading disk too often
CHAPTER_CACHE = {}

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
    # Default start: chapter1
    initial_chapter = 'chapter1'
    story_data = load_chapter(initial_chapter)

    if not story_data:
        return jsonify({'error': 'Story data not found'}), 500

    session['current_chapter'] = initial_chapter
    session['current_node'] = story_data['start_node']
    session['sanity'] = story_data.get('initial_state', {}).get('sanity', 100)
    session['inventory'] = story_data.get('initial_state', {}).get('inventory', [])

    node_data = story_data['nodes'][story_data['start_node']]
    return jsonify(get_response_payload(node_data))

@app.route('/choice', methods=['POST'])
def make_choice():
    current_chapter_name = session.get('current_chapter')
    current_node_id = session.get('current_node')

    if not current_chapter_name or not current_node_id:
        return jsonify({'error': 'Game not started'}), 400

    story_data = load_chapter(current_chapter_name)
    if not story_data:
         return jsonify({'error': 'Chapter data missing'}), 500

    node = story_data['nodes'].get(current_node_id)
    choice_index = request.json.get('index')

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

    # Handle Transition
    next_chapter = choice.get('next_chapter')
    next_node_id = choice.get('next_node')

    if next_chapter:
        # Switch Chapter
        new_story_data = load_chapter(next_chapter)
        if not new_story_data:
            return jsonify({'error': f'Chapter {next_chapter} not found'}), 500

        session['current_chapter'] = next_chapter
        # If next_node is not specified, use start_node of new chapter
        if not next_node_id:
            next_node_id = new_story_data['start_node']

        session['current_node'] = next_node_id
        next_node = new_story_data['nodes'].get(next_node_id)
    else:
        # Same Chapter
        session['current_node'] = next_node_id
        next_node = story_data['nodes'].get(next_node_id)

    if not next_node:
         return jsonify({'error': f'Node {next_node_id} not found'}), 500

    return jsonify(get_response_payload(next_node))

def get_response_payload(node):
    valid_choices = []
    for ch in node['choices']:
        if check_condition(ch.get('condition')):
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
