"""Notes module — CRUD API + FTS5 search for reference notes."""

from core.module import Module


class NotesModule(Module):
    name = "notes"
    description = "Save, search (FTS5), update, delete reference notes"
    version = "0.1.0"
    routes = "modules.notes.routes"
    config_defaults = {
        "enabled": True,
    }
