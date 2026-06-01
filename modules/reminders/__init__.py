"""Reminders module — CRUD API for one-shot reminders."""

from core.module import Module


class RemindersModule(Module):
    name = "reminders"
    description = "Create, list, cancel one-shot reminders"
    version = "0.1.0"
    routes = "modules.reminders.routes"
    config_defaults = {
        "enabled": True,
        "default_alert_before_minutes": 10,  # minutes before event to send reminder
    }
