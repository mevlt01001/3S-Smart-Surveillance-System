/**
 * Plain-language names for the technical values the analysis engine reports
 * (detector class names, rule conditions, event levels).
 */

import { lang, t } from "./i18n.js";

const CLASS_LABELS = {
  person: "Kişi",
  hardhat: "Baret",
  "no-hardhat": "Baretsiz kişi",
  "safety vest": "Yelek",
  "no-safety vest": "Yeleksiz kişi",
  mask: "Maske",
  "no-mask": "Maskesiz kişi",
  "safety cone": "Koni",
  machinery: "İş makinesi",
  vehicle: "Araç",
  car: "Araba",
  truck: "Kamyon",
  bus: "Otobüs",
  motorcycle: "Motosiklet",
  bicycle: "Bisiklet",
  forklift: "Forklift",
  backpack: "Sırt çantası",
  suitcase: "Bavul",
  handbag: "Çanta",
};

const CONDITION_LABELS = {
  zone_presence: "bölgede görülünce",
  zone_absence: "bölgede yokken",
  zone_intrusion: "bölgeye girince",
  loitering: "uzun süre bekleyince",
  line_crossing: "çizgiyi geçince",
  wrong_direction: "ters yönde gidince",
  count_above: "sayı sınırı aşılınca",
  count_below: "sayı sınırın altına düşünce",
  object_left: "sahipsiz kalınca",
};

/** Name of a detector class in the interface language; unknown classes are shown as reported. */
export const classLabel = (name) => {
  const label = CLASS_LABELS[String(name || "").toLowerCase()];
  return label ? t(label) : String(name || t("Nesne"));
};

const conditionLabel = (type) => (CONDITION_LABELS[type] ? t(CONDITION_LABELS[type]) : "");

/** Sentence describing what a compiled rule zone looks for, or "" when there is no plan yet. */
export function describePlan(summary) {
  if (!summary || !Array.isArray(summary.classes) || summary.classes.length === 0) return "";
  const subjects = summary.classes.map(classLabel).join(", ");
  const when = (summary.conditions || []).map(conditionLabel).filter(Boolean).join(", ");
  return when ? `${subjects} — ${when}` : subjects;
}

/* ------------------------------------------------- Sentences of the rule engine */
// The rule engine writes why an alarm fired in Turkish ("Bölgede görüldü: baretsiz kişi"). In English
// those few sentence shapes are recognised and rewritten; anything else is shown as written.
const lower = (text) => text.toLocaleLowerCase("tr");
const ENGLISH_NAME = new Map();
Object.entries(CLASS_LABELS).forEach(([name, label]) => {
  const english = t(label).toLowerCase();
  ENGLISH_NAME.set(lower(label), english);
  ENGLISH_NAME.set(name, english);
});
const englishNames = (list) => list.split(", ").map((name) => ENGLISH_NAME.get(lower(name.trim())) || name).join(", ");

const ALARM_SENTENCES = [
  [/^Bölgede görüldü: (.+)$/, (m) => `Seen in the zone: ${englishNames(m[1])}`],
  [/^İSG İhlali: (\d+) kişide eksik ekipman: (.+)$/, (m) => `Safety violation: equipment missing on ${m[1]} ${m[1] === "1" ? "person" : "people"}: ${englishNames(m[2])}`],
  [/^(.+) (\d+) saniyedir bölgede yok$/, (m) => `No ${englishNames(m[1])} in the zone for ${m[2]} s`],
  [/^(.+) (\d+) saniyedir bölgede bekliyor$/, (m) => `${englishNames(m[1])} waiting in the zone for ${m[2]} s`],
  [/^Bölgedeki sayı sınırı aşıldı: (\d+) (.+)$/, (m) => `Count limit reached in the zone: ${m[1]} ${englishNames(m[2])}`],
  [/^Bölgede olmaması gereken görüldü: (.+)$/, (m) => `Not allowed in the zone: ${englishNames(m[1])}`],
  [/^Hattı geçen var: (.+)$/, (m) => `Line crossed: ${englishNames(m[1])}`],
  [/^(.+): bölgede engel veya değişiklik var$/, (m) => `${m[1]}: obstruction or change in the zone`],
];

/** Why an alarm fired, in the interface language. */
export function alarmText(text) {
  if (lang !== "en" || !text) return text || "";
  return String(text).split(" | ").map((part) => {
    for (const [pattern, write] of ALARM_SENTENCES) {
      const match = pattern.exec(part);
      if (match) {
        const sentence = write(match);
        return sentence.charAt(0).toUpperCase() + sentence.slice(1);
      }
    }
    return part;
  }).join(" | ");
}

/** Severity levels shared by events and live tiles. */
const LEVELS = {
  critical: { label: "Kritik", badge: "is-danger" },
  warning: { label: "Uyarı", badge: "is-warn" },
  normal: { label: "Normal", badge: "is-ok" },
};

export const levelOf = (tier) => {
  const level = LEVELS[tier] || LEVELS.normal;
  return { ...level, label: t(level.label) };
};
