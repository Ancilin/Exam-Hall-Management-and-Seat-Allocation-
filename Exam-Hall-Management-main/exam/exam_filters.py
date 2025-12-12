from django import template

register = template.Library()

@register.filter
def index(sequence, position):
    """
    Returns the item at the given position from a sequence.
    """
    if isinstance(sequence, (list, tuple, str)):
        try:
            return sequence[int(position)]
        except (IndexError, ValueError):
            return None
    elif isinstance(sequence, dict):
        return sequence.get(position)
    return None