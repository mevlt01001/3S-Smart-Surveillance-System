# Smart Surveillance System Documentation

This directory describes the whole system, from operating it to changing its code. The chapters reflect
the code as it is; when you change a behaviour, update the chapter that describes it in the same commit —
documentation that drifts from the code is worse than none.

The documentation exists in two languages with the same content: English here, Turkish in
[`tr/`](tr/README.md) (Türkçe belgeler). A change to one belongs in the other.

| Chapter | Content | Audience |
| :--- | :--- | :--- |
| [01 — Overview](01-overview.md) | What the system does, its components, terminology | Everyone |
| [02 — Installation and start-up](02-installation.md) | Requirements, first installation, starting and stopping, ports | Whoever installs it |
| [03 — User guide](03-user-guide.md) | Every page of the interface, step by step; themes and language | Operators |
| [04 — Architecture](04-architecture.md) | Processes, threads, data flow, design decisions | Developers |
| [05 — Backend modules](05-backend.md) | The role and interface of every module in `WebInterface/backend` | Developers |
| [06 — API reference](06-api.md) | All HTTP / WebSocket / SSE endpoints with example requests and responses | Developers, integrators |
| [07 — Frontend](07-frontend.md) | Structure of `WebInterface/frontend`, conventions, interface language, colour roles and themes, adding a page | Developers |
| [08 — Rules and analysis](08-rules-and-analysis.md) | Rule compilation, capabilities and limits, working hours, tracking, condition types, event life cycle, summaries | Developers |
| [09 — Data and configuration](09-data-and-configuration.md) | Files on disk, record formats, every setting, environment variables | Developers, installers |
| [10 — Development and testing](10-development-and-testing.md) | Workflow, system check, accuracy measurement and its first results, recipes for common changes | Developers |
| [11 — Troubleshooting](11-troubleshooting.md) | Causes and fixes by symptom, known limits | Everyone |

Where to start:

- **Operating the system:** 03, then 11 when something looks wrong.
- **Installing it:** 02 and 09.
- **Taking over development:** 01, 04 and 10 first; 05–08 as reference.
