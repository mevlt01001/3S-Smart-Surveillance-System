"""HTTP API of the backend, one module per subject."""

from . import cameras, events, live, reports, rules, settings, system

routers = [system.router, cameras.router, live.router, rules.router, events.router, reports.router, settings.router]
