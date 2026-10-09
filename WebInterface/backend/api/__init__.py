"""HTTP API of the backend, one module per subject."""

from . import cameras, events, live, rules, settings, system

routers = [system.router, cameras.router, live.router, rules.router, events.router, settings.router]
