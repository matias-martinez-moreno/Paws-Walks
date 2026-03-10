from django import template

register = template.Library()


@register.filter
def hora_corta(value):
    """Formatea time como HH:MM (sin segundos)."""
    if value is None:
        return ""
    try:
        return value.strftime("%H:%M")
    except (AttributeError, ValueError):
        return str(value)


@register.filter
def formato_cop(value):
    """Formatea un número como moneda COP con separador de miles (punto)."""
    if value is None:
        return ""
    try:
        num = int(value)
        return f"{num:,}".replace(",", ".")
    except (ValueError, TypeError):
        return str(value)
