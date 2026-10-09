/**
 * Plain-language names for the technical values the analysis engine reports
 * (detector class names, rule conditions, event levels).
 */

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
export const classLabel = (name) => CLASS_LABELS[String(name || "").toLowerCase()] || String(name || "Nesne");

const conditionLabel = (type) => CONDITION_LABELS[type] || "";

/** Sentence describing what a compiled rule zone looks for, or "" when there is no plan yet. */
export function describePlan(summary) {
  if (!summary || !Array.isArray(summary.classes) || summary.classes.length === 0) return "";
  const subjects = summary.classes.map(classLabel).join(", ");
  const when = (summary.conditions || []).map(conditionLabel).filter(Boolean).join(", ");
  return when ? `${subjects} — ${when}` : subjects;
}

/** Severity levels shared by events and live tiles. */
const LEVELS = {
  critical: { label: "Kritik", badge: "is-danger" },
  warning: { label: "Uyarı", badge: "is-warn" },
  normal: { label: "Normal", badge: "is-ok" },
};

export const levelOf = (tier) => LEVELS[tier] || LEVELS.normal;
