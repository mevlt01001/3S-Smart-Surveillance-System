/**
 * Colour theme of this device. Loaded as a plain script in <head>, before the stylesheets,
 * so the page is painted in the chosen theme from the first frame. The choice is a personal
 * convenience and stays in this browser; the page works the same when storage is unavailable.
 */
(function () {
  var KEY = "aegis-theme";
  // name -> colour of the browser's own bars on a phone (the page background of that theme)
  var THEMES = { light: "#14233a", navy: "#0e1a2b", dark: "#161a21" };
  var DEFAULT = "light";

  function stored() {
    try {
      return localStorage.getItem(KEY);
    } catch (_) {
      return null; // private window or blocked storage
    }
  }

  function apply(name) {
    var theme = THEMES[name] ? name : DEFAULT;
    document.documentElement.dataset.theme = theme;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", THEMES[theme]);
    return theme;
  }

  window.aegisTheme = {
    names: Object.keys(THEMES),
    get: function () {
      return document.documentElement.dataset.theme || DEFAULT;
    },
    set: function (name) {
      var theme = apply(name);
      try {
        localStorage.setItem(KEY, theme);
      } catch (_) {
        /* the theme still applies until the page is closed */
      }
      return theme;
    },
  };
  apply(stored());
})();
