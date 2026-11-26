def allowed_pads(backing, minimum, maximum, candidates, banned):
    """Read integer millimetres and return eligible pad identifiers in order."""
    excluded = set(banned)
    return [
        pad_id for pad_id, thickness in sorted(candidates.items())
        if pad_id not in excluded and minimum <= backing + thickness <= maximum
    ]
