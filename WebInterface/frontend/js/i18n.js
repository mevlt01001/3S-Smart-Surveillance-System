/**
 * Interface language: Turkish (default) or English, chosen per device like the theme.
 *
 * Turkish is the source language. Every text is written in Turkish in the code and passed through
 * `t()`; in English mode `t()` looks the Turkish text up in the catalogue (i18n-en.js) and falls back
 * to the Turkish when an entry is missing. Static texts of index.html are translated once at start-up
 * by `translatePage()`. The system test checks that every text has an English entry.
 *
 *   t("Kural kaydedildi.")                 -> "Rule saved."
 *   t("{n} olay", { n: 3 })                -> "3 events"
 */

import EN from "./i18n-en.js";

const KEY = "aegis-lang";
const ATTRIBUTES = ["placeholder", "title", "aria-label", "alt"];

function stored() {
  try {
    return localStorage.getItem(KEY);
  } catch (_) {
    return null; // private window or blocked storage: Turkish
  }
}

/** "tr" or "en": the language of this page view (changing it reloads the page). */
export const lang = stored() === "en" ? "en" : "tr";

/** Locale for dates and numbers. */
export const locale = lang === "en" ? "en-GB" : "tr-TR";

document.documentElement.lang = lang;

/** The text in the interface language, with `{name}` placeholders filled from `params`. */
export function t(text, params) {
  let out = lang === "en" && Object.prototype.hasOwnProperty.call(EN, text) ? EN[text] : text;
  if (params) out = out.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
  return out;
}

/** Stores the choice for this device and reloads, so that every page is drawn in the new language. */
export function setLanguage(next) {
  try {
    localStorage.setItem(KEY, next === "en" ? "en" : "tr");
  } catch (_) {
    return; // nothing to remember the choice in
  }
  window.location.reload();
}

/**
 * Translates the static texts of the page: text nodes and the user-facing attributes. Texts are
 * matched as written in index.html, ignoring surrounding white space.
 */
export function translatePage(root = document.body) {
  if (lang !== "en") return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.nodeValue.trim();
    if (text && Object.prototype.hasOwnProperty.call(EN, text)) {
      node.nodeValue = node.nodeValue.replace(text, EN[text]);
    }
  }
  root.querySelectorAll(ATTRIBUTES.map((name) => `[${name}]`).join(",")).forEach((element) => {
    ATTRIBUTES.forEach((name) => {
      const value = element.getAttribute(name);
      if (value && Object.prototype.hasOwnProperty.call(EN, value.trim())) element.setAttribute(name, EN[value.trim()]);
    });
  });
}
