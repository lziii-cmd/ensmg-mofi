from django import template

register = template.Library()


@register.filter
def dict_key(d, key):
    """Return d[key], or None if key is not in d."""
    try:
        return d.get(key)
    except (AttributeError, TypeError):
        return None
