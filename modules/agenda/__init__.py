"""Agenda module — query reminders as agenda items."""

from core.module import Module


class AgendaModule(Module):
    name = "agenda"
    description = "Query today/tomorrow/week agenda from saved reminders"
    version = "0.1.0"
    routes = "modules.agenda.routes"
    config_defaults = {
        "enabled": True,
    }
