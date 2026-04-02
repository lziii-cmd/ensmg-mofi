from django import template

register = template.Library()


@register.filter
def fr_money(value):
    """Format a number as French-style money: 1 234 567 (narrow no-break space as thousands separator)."""
    try:
        value = int(round(float(value)))
    except (TypeError, ValueError):
        return value
    # Format with narrow no-break space (\u202f) as thousands separator
    return "{:,}".format(value).replace(",", "\u202f")
