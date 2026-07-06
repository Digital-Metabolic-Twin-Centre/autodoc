import os

from src.routers.widget_router import router

API_TOKEN = os.getenv("API_TOKEN")


def create_app():
    """Entry point that wires the widget router into the application."""
    return router
