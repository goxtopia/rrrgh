from flask import Flask, render_template, session, jsonify, request
import json
import os
import random

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
    session['stats'] = story_data.get('initial_state', {}).get('stats', {'str': 10, 'dex': 10})

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

    payload = get_response_payload(next_node)
    if roll_message:
        payload['roll_message'] = roll_message
    return jsonify(payload)

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
            'inventory': session.get('inventory'),
            'attributes': session.get('stats', {})
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
