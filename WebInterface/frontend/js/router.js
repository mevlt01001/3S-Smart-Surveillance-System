/**
 * Hash router: one view is visible at a time and each view owns a small lifecycle
 * ({ mount, unmount, canLeave }). The address bar, the back button and bookmarks all work.
 */

const views = new Map();
const aliases = new Map();
let activeName = null;
let switching = false;

/**
 * @param {string} name       hash of the view (`#name`) and suffix of its section id (`view-name`)
 * @param {{title: string, mount: (params: object) => void, unmount?: () => void,
 *          canLeave?: () => Promise<boolean> | boolean}} view
 */
export function registerView(name, view) {
  views.set(name, view);
}

/** Keeps old bookmarks working after a view was renamed. */
export function registerAlias(oldName, name) {
  aliases.set(oldName, name);
}

function resolve(name) {
  const target = aliases.get(name) || name;
  return views.has(target) ? target : null;
}

/** Shows a view. `params` are handed to its `mount` (for example the camera to focus on). */
export async function navigate(name, params = {}) {
  const target = resolve(name);
  if (!target || switching) return;
  if (target === activeName) {
    views.get(target).mount(params);
    return;
  }
  switching = true;
  try {
    const current = views.get(activeName);
    if (current && current.canLeave && !(await current.canLeave())) {
      history.replaceState(null, "", `#${activeName}`);
      return;
    }
    if (current && current.unmount) current.unmount();

    activeName = target;
    const view = views.get(target);
    views.forEach((_, viewName) => {
      const section = document.getElementById(`view-${viewName}`);
      if (section) section.hidden = viewName !== target;
    });
    document.querySelectorAll(".nav-item").forEach((item) => {
      const isActive = item.dataset.view === target;
      item.classList.toggle("is-active", isActive);
      if (isActive) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    });
    document.getElementById("page-title").textContent = view.title;
    document.title = `${view.title} · Smart Surveillance System`;
    document.getElementById("content").scrollTop = 0;
    if (location.hash !== `#${target}`) history.pushState(null, "", `#${target}`);

    view.mount(params);
  } finally {
    switching = false;
  }
}

/** Starts routing; `fallback` is shown when the address names no known view. */
export function startRouter(fallback) {
  const fromHash = () => resolve(location.hash.slice(1)) || fallback;
  window.addEventListener("hashchange", () => navigate(fromHash()));
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.preventDefault();
      navigate(item.dataset.view);
    });
  });
  navigate(fromHash());
}
