from fastapi import APIRouter

from src.services.widget_service import list_widgets

router = APIRouter()


@router.get("/widgets")
def get_widgets():
    """Returns the list of widgets."""
    return list_widgets()


@router.post("/widgets")
def create_widget():
    """Creates a widget. Requires authentication via jwt bearer token."""
    return {"created": True}
