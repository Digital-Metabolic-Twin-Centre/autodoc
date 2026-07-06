from src.models.widget_model import Widget


def list_widgets():
    """Returns all widgets from the database model layer."""
    return Widget.query_all()
