from collections import deque


def find_route(*, item_ids, start_by_item, target_by_item, scope_bases,
               external_occupants, base_active, eligible):
    """Find a deterministic sequence of one-item moves.

    The search treats ``external_occupants`` as fixed obstacles: only the
    relocation items may move.  A state is the tuple of current base ids in
    ``item_ids`` order.  BFS gives a stable, short route without requiring a
    caller to compare route lengths.
    """
    if not item_ids:
        return None

    start = tuple(start_by_item.get(item_id) for item_id in item_ids)
    goal = tuple(target_by_item.get(item_id) for item_id in item_ids)
    if any(base is None for base in start + goal):
        return None
    if len(set(start)) != len(start):
        return None

    item_set = set(item_ids)
    blocked = {base_id for base_id, installation_id in external_occupants.items()
               if installation_id not in item_set}
    scope = list(dict.fromkeys(scope_bases))

    initial = tuple(start)
    parents = {initial: None}
    queued = deque([initial])

    while queued:
        state = queued.popleft()
        if state == goal:
            break

        occupied = set(state)
        for index, installation_id in enumerate(item_ids):
            from_base = state[index]
            for to_base in scope:
                if to_base == from_base or to_base in occupied or to_base in blocked:
                    continue
                if not base_active(to_base):
                    continue
                if not eligible(installation_id, to_base):
                    continue
                next_state = list(state)
                next_state[index] = to_base
                next_state = tuple(next_state)
                if next_state in parents:
                    continue
                move = {
                    'installation_id': installation_id,
                    'from_base_id': from_base,
                    'to_base_id': to_base,
                }
                parents[next_state] = (state, move)
                queued.append(next_state)

    if goal not in parents:
        return None

    path = []
    state = goal
    while parents[state] is not None:
        previous, move = parents[state]
        path.append(move)
        state = previous
    path.reverse()
    return path
