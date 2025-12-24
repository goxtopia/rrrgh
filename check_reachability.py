import json
import os
import collections

# Utility script to verify the connectivity of the game's story graph.
# Run this to ensure that all chapters are reachable and that specific endings can be achieved.

CHAPTERS_DIR = 'data/chapters'

def load_all_chapters():
    chapters = {}
    if not os.path.exists(CHAPTERS_DIR):
        print(f"Error: Directory {CHAPTERS_DIR} not found.")
        return {}

    for filename in os.listdir(CHAPTERS_DIR):
        if filename.endswith('.json'):
            chapter_name = filename[:-5]
            with open(os.path.join(CHAPTERS_DIR, filename), 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                    chapters[chapter_name] = data
                except json.JSONDecodeError as e:
                    print(f"Error decoding {filename}: {e}")
    return chapters

def build_graph(chapters):
    # Graph: key = (chapter_id, node_id), value = list of (next_chapter_id, next_node_id)
    adj = collections.defaultdict(list)

    for chap_name, chap_data in chapters.items():
        nodes = chap_data.get('nodes', {})
        for node_id, node_data in nodes.items():
            current = (chap_name, node_id)
            choices = node_data.get('choices', [])

            for choice in choices:
                # 1. Check Explicit Transitions
                next_chap = choice.get('next_chapter')
                next_node = choice.get('next_node')

                # If it's a Roll, we look at success/failure nodes instead of 'next_node' (which is often 'dummy')
                roll_targets = []
                if 'roll' in choice:
                    roll = choice['roll']
                    if 'success_node' in roll:
                        roll_targets.append(roll['success_node'])
                    if 'failure_node' in roll:
                        roll_targets.append(roll['failure_node'])

                # Determine targets
                target_definitions = []

                # If roll exists, we use roll targets within the SAME chapter (usually)
                if roll_targets:
                    for t in roll_targets:
                        target_definitions.append( (None, t) ) # None means same chapter
                else:
                    # Standard link
                    target_definitions.append( (next_chap, next_node) )

                for t_chap, t_node in target_definitions:
                    final_chap = t_chap if t_chap else chap_name

                    # Resolve Start Node if node is missing/None
                    if final_chap != chap_name and not t_node:
                        # Link to start of new chapter
                        if final_chap not in chapters:
                            print(f"WARNING: Link to missing chapter '{final_chap}' from {current}")
                            continue

                        starts = chapters[final_chap].get('start_node')
                        if isinstance(starts, list):
                            for s in starts:
                                adj[current].append( (final_chap, s) )
                        else:
                            adj[current].append( (final_chap, starts) )

                    elif t_node and t_node != 'dummy':
                        # Specific node
                        if isinstance(t_node, list):
                            for n in t_node:
                                adj[current].append( (final_chap, n) )
                        else:
                            adj[current].append( (final_chap, t_node) )

    return adj

def check_reachability():
    chapters = load_all_chapters()
    if not chapters: return

    adj = build_graph(chapters)

    start_chap = 'chapter01_arrival'
    if start_chap not in chapters:
        print("CRITICAL: Start chapter not found.")
        return

    start_nodes_def = chapters[start_chap].get('start_node')
    queue = collections.deque()
    visited = set()

    if isinstance(start_nodes_def, list):
        for s in start_nodes_def:
            visited.add((start_chap, s))
            queue.append((start_chap, s))
    else:
        visited.add((start_chap, start_nodes_def))
        queue.append((start_chap, start_nodes_def))

    while queue:
        curr = queue.popleft()
        for neighbor in adj[curr]:
            n_chap, n_node = neighbor
            if n_chap not in chapters: continue

            if n_node not in chapters[n_chap]['nodes']:
                print(f"DEAD LINK: From {curr} -> {neighbor}")
                continue

            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    expected_endings = [
        'end_scholar', 'end_hero', 'end_cult_leader',
        'end_sacrifice', 'end_shoot_crystal', 'end_bad'
    ]
    target_chap = 'chapter20_lighthouse_top'

    print("\n--- Reachability Report ---")
    all_ok = True
    for end in expected_endings:
        if (target_chap, end) in visited:
             print(f"[OK] {end}")
        else:
             print(f"[FAIL] {end}")
             all_ok = False

    if all_ok: print("\nALL REACHABLE.")
    else: print("\nSOME UNREACHABLE.")

if __name__ == "__main__":
    check_reachability()
