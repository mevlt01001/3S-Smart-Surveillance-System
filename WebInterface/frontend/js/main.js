/** Entry point: wires the shared chrome and registers the pages with the router. */

import { registerAlias, registerView, startRouter } from "./router.js";
import { initShell } from "./shell.js";
import { initModals } from "./ui.js";
import * as live from "./live.js";
import * as events from "./events.js";
import * as rules from "./rules.js";
import * as reports from "./reports.js";
import * as cameras from "./cameras.js";
import * as settings from "./settings.js";

initModals();
initShell();

registerView("live", { title: "Canlı İzleme", ...live });
registerView("events", { title: "Olaylar", ...events });
registerView("rules", { title: "Kurallar", ...rules });
registerView("reports", { title: "Raporlar", ...reports });
registerView("cameras", { title: "Kameralar", ...cameras });
registerView("settings", { title: "Ayarlar", ...settings });
registerAlias("home", "cameras");

startRouter("live");
