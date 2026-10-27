/** Entry point: wires the shared chrome and registers the pages with the router. */

import { t, translatePage } from "./i18n.js";
import { registerAlias, registerView, startRouter } from "./router.js";
import { initShell } from "./shell.js";
import { initModals } from "./ui.js";
import * as live from "./live.js";
import * as events from "./events.js";
import * as rules from "./rules.js";
import * as reports from "./reports.js";
import * as cameras from "./cameras.js";
import * as settings from "./settings.js";

translatePage();
initModals();
initShell();

registerView("live", { title: t("Canlı İzleme"), ...live });
registerView("events", { title: t("Olaylar"), ...events });
registerView("rules", { title: t("Kurallar"), ...rules });
registerView("reports", { title: t("Raporlar"), ...reports });
registerView("cameras", { title: t("Kameralar"), ...cameras });
registerView("settings", { title: t("Ayarlar"), ...settings });
registerAlias("home", "cameras");

startRouter("live");
