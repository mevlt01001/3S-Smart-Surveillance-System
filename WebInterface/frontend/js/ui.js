/**
 * Shared interface helpers: safe HTML building, notifications, dialogs and small formatters.
 * Pages use these instead of talking to the DOM for cross-cutting concerns.
 */

/* ------------------------------------------------------------ HTML helpers */
const HTML_ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** Escapes a value for use inside HTML text or attribute values. */
export function escapeHTML(value) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/[&<>"']/g, (ch) => HTML_ENTITIES[ch]);
}

/** Markup of an icon from the sprite in index.html. */
export const icon = (name) => `<svg class="icon"><use href="#i-${name}"/></svg>`;

/** Replaces the content of `element` only when it actually changed (keeps hover / focus / scroll stable). */
export function setHTML(element, html) {
  if (!element || element.dataset.rendered === html) return;
  element.innerHTML = html;
  element.dataset.rendered = html;
}

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

/* -------------------------------------------------------------- Formatters */
export function formatDuration(seconds) {
  const total = Math.round(Number(seconds) || 0);
  if (total < 60) return `${total} sn`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return rest ? `${minutes} dk ${rest} sn` : `${minutes} dk`;
}

/** Hides the password of an rtsp:// or http:// address for on-screen display. */
export function maskCredentials(uri) {
  return String(uri || "").replace(/^([a-z][a-z0-9+.-]*:\/\/[^:@/\s]+):[^@/\s]*@/i, "$1:••••@");
}

/** Clipboard write that also works on plain-HTTP origins. */
export async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_) {
    /* fall through to the legacy path */
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch (_) {
    copied = false;
  }
  area.remove();
  return copied;
}

/** Triggers a browser download for in-memory content. */
export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Neutral placeholder for events whose image is not available. */
export const NO_IMAGE =
  "data:image/svg+xml," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180"><rect width="320" height="180" fill="#131822"/>` +
      `<g fill="none" stroke="#56627a" stroke-width="3"><rect x="126" y="62" width="68" height="50" rx="6"/><circle cx="160" cy="87" r="13"/></g>` +
      `<text x="160" y="140" fill="#56627a" font-family="sans-serif" font-size="13" text-anchor="middle">Görüntü yok</text></svg>`
  );

/* ------------------------------------------------------------------ Toasts */
const MAX_TOASTS = 4;
let toastHost = null;

/**
 * Shows a short, non-blocking message.
 * @param {string} message plain text
 * @param {"info"|"success"|"warning"|"error"} [type]
 * @param {number} [durationMs] 0 keeps the message until it is closed
 */
export function showToast(message, type = "info", durationMs = 4000) {
  if (!toastHost) {
    toastHost = document.createElement("div");
    toastHost.className = "toasts";
    document.body.appendChild(toastHost);
  }
  while (toastHost.children.length >= MAX_TOASTS) toastHost.firstElementChild.remove();

  const toast = document.createElement("div");
  toast.className = `toast is-${type}`;
  toast.setAttribute("role", type === "error" || type === "warning" ? "alert" : "status");

  const text = document.createElement("div");
  text.className = "toast-message";
  text.textContent = message;

  const close = document.createElement("button");
  close.type = "button";
  close.className = "toast-close";
  close.setAttribute("aria-label", "Kapat");
  close.textContent = "×";
  close.addEventListener("click", () => toast.remove());

  toast.append(text, close);
  toastHost.appendChild(toast);
  if (durationMs > 0) setTimeout(() => toast.remove(), durationMs);
}

/** Shows the reason of a failed action. */
export const showError = (prefix, err) =>
  showToast(`${prefix}: ${(err && err.message) || "bilinmeyen hata"}`, "error", 6000);

/* ------------------------------------------------------------------ Modals */
const focusBeforeModal = new WeakMap();

export function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  focusBeforeModal.set(modal, document.activeElement);
  modal.classList.add("is-open");
  const target = modal.querySelector("[autofocus]") || modal.querySelector(".modal-dialog");
  if (target) {
    if (!target.hasAttribute("tabindex") && target.classList.contains("modal-dialog")) target.tabIndex = -1;
    target.focus({ preventScroll: true });
  }
}

/** Closes a modal and notifies listeners through a `modal:closed` event on the element. */
export function closeModal(modalId) {
  const modal = typeof modalId === "string" ? document.getElementById(modalId) : modalId;
  if (!modal || !modal.classList.contains("is-open")) return;
  modal.classList.remove("is-open");
  modal.dispatchEvent(new CustomEvent("modal:closed"));
  const previous = focusBeforeModal.get(modal);
  if (previous && document.contains(previous)) previous.focus({ preventScroll: true });
}

export const isAnyModalOpen = () => Boolean(document.querySelector(".modal.is-open"));

/** Wires the behaviour every modal shares: close buttons, backdrop click and Esc. */
export function initModals() {
  document.addEventListener("click", (event) => {
    const modal = event.target.closest(".modal");
    if (!modal) return;
    if (event.target === modal || event.target.closest("[data-close]")) closeModal(modal);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const open = $$(".modal.is-open");
    if (!open.length) return;
    event.preventDefault();
    event.stopPropagation();
    closeModal(open[open.length - 1]);
  }, true);
}

/**
 * Asks the user to confirm an action.
 * @param {{title: string, message: string, confirmText?: string, danger?: boolean}} options
 * @returns {Promise<boolean>}
 */
export function confirmDialog({ title, message, confirmText = "Onayla", danger = false }) {
  return new Promise((resolve) => {
    const modal = document.createElement("div");
    modal.className = "modal is-open";
    modal.setAttribute("role", "alertdialog");
    modal.setAttribute("aria-modal", "true");
    modal.innerHTML = `
      <div class="modal-dialog">
        <header class="modal-header"><h2>${escapeHTML(title)}</h2></header>
        <div class="modal-body"><p class="confirm-message">${escapeHTML(message)}</p></div>
        <footer class="modal-footer">
          <span class="toolbar-spacer"></span>
          <button type="button" class="btn" data-answer="no">Vazgeç</button>
          <button type="button" class="btn ${danger ? "btn-danger" : "btn-primary"}" data-answer="yes">${escapeHTML(confirmText)}</button>
        </footer>
      </div>`;
    const previous = document.activeElement;

    const finish = (answer) => {
      modal.remove();
      if (previous && document.contains(previous)) previous.focus({ preventScroll: true });
      resolve(answer);
    };
    modal.addEventListener("click", (event) => {
      const button = event.target.closest("[data-answer]");
      if (button) finish(button.dataset.answer === "yes");
    });
    // Emitted by the shared handlers for Esc and for a click on the backdrop
    modal.addEventListener("modal:closed", () => finish(false));

    document.body.appendChild(modal);
    // A destructive action never has the confirm button pre-selected
    modal.querySelector(`[data-answer="${danger ? "no" : "yes"}"]`).focus();
  });
}

/** Shows an image full-screen; a click or Esc closes it. */
export function showImage(src, caption = "") {
  const box = document.createElement("div");
  box.className = "modal lightbox is-open";
  box.innerHTML = `<img src="${escapeHTML(src)}" alt="">${caption ? `<span class="lightbox-caption">${escapeHTML(caption)}</span>` : ""}`;
  box.addEventListener("click", () => box.remove());
  box.addEventListener("modal:closed", () => box.remove());
  document.body.appendChild(box);
}

/* ------------------------------------------------------------ Small widgets */
/** Makes a `.segmented` button group behave as a single-choice control. */
export function bindSegmented(group, attribute, onChange) {
  group.addEventListener("click", (event) => {
    const button = event.target.closest(`button[data-${attribute}]`);
    if (button && group.contains(button)) onChange(button.dataset[attribute]);
  });
  return (value) => {
    $$("button", group).forEach((button) => button.classList.toggle("is-active", button.dataset[attribute] === value));
  };
}

/** Runs `task` while the button is disabled and shows `busyText`; restores it afterwards. */
export async function withBusy(button, busyText, task) {
  if (!button) return task();
  const original = button.innerHTML;
  button.disabled = true;
  button.textContent = busyText;
  try {
    return await task();
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}
