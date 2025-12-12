# exam/templatetags/exam_extras.py

from django import template

# Register the library instance
register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Looks up a dictionary value by its key.
    Usage: {{ my_dict|get_item:key_name }}
    """
    return dictionary.get(key)