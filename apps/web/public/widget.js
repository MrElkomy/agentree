/*! Agentree website widget loader.
 * <script src="https://<agentree-origin>/widget.js" data-agentree="<slug>" async></script>
 * Adds a chat button that opens the business's Agentree chat in an iframe served by Agentree.
 * Dependency-free, makes no requests of its own, and never reads or changes host page data.
 * Which websites may show the chat is enforced by the iframe's CSP frame-ancestors header.
 */
(function () {
  "use strict";
  if (window.Agentree && window.Agentree.loaded) return;

  var script =
    document.currentScript || document.querySelector("script[data-agentree][src*='/widget.js']");
  if (!script) return;
  var slug = script.getAttribute("data-agentree") || "";
  // Same rule as the backend's slug validation.
  if (!/^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$/.test(slug) || slug.indexOf("--") !== -1) {
    if (window.console) console.warn("Agentree widget: invalid data-agentree value");
    return;
  }
  var origin;
  try {
    origin = new URL(script.src, location.href).origin;
  } catch {
    return;
  }

  // Mirrors the app's --color-brand token; host pages cannot read our stylesheet.
  var ACCENT = "#0052fc";
  var rtl = (document.documentElement.getAttribute("dir") || "").toLowerCase() === "rtl";
  var side = rtl ? "left" : "right";
  var open = false;
  var frame = null;

  function css(el, styles) {
    for (var k in styles) el.style.setProperty(k, styles[k]);
  }

  var button = document.createElement("button");
  button.type = "button";
  button.setAttribute("aria-label", "Open chat");
  button.setAttribute("aria-expanded", "false");
  button.innerHTML =
    '<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" focusable="false">' +
    '<path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 17h-8l-5 3.5V17H5a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 5 5z" ' +
    'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>';
  css(button, {
    position: "fixed",
    bottom: "20px",
    width: "56px",
    height: "56px",
    border: "0",
    "border-radius": "50%",
    background: ACCENT,
    color: "#fff",
    cursor: "pointer",
    display: "flex",
    "align-items": "center",
    "justify-content": "center",
    "box-shadow": "0 6px 20px rgba(0,0,0,.22)",
    "z-index": "2147483000",
    padding: "0",
    margin: "0",
  });
  button.style.setProperty(side, "20px");

  function ensureFrame() {
    if (frame) return frame;
    frame = document.createElement("iframe");
    frame.src = origin + "/w/" + encodeURIComponent(slug);
    frame.title = "Chat";
    frame.setAttribute("allow", "");
    frame.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
    css(frame, {
      position: "fixed",
      bottom: "88px",
      width: "min(380px, calc(100vw - 24px))",
      height: "min(600px, calc(100vh - 100px))",
      border: "0",
      "border-radius": "12px",
      "box-shadow": "0 12px 40px rgba(0,0,0,.25)",
      background: "#fff",
      "z-index": "2147483000",
      display: "none",
    });
    frame.style.setProperty(side, "12px");
    document.body.appendChild(frame);
    return frame;
  }

  function setOpen(next) {
    open = next;
    ensureFrame().style.display = open ? "block" : "none";
    button.setAttribute("aria-expanded", open ? "true" : "false");
    button.setAttribute("aria-label", open ? "Close chat" : "Open chat");
    if (open) frame.focus();
    else button.focus();
  }

  button.addEventListener("click", function () {
    setOpen(!open);
  });
  document.addEventListener("keydown", function (e) {
    if (open && e.key === "Escape") setOpen(false);
  });
  // Close requests from our iframe only (exact origin and window); the message carries no data.
  window.addEventListener("message", function (e) {
    if (!frame || e.origin !== origin || e.source !== frame.contentWindow) return;
    if (e.data && e.data.type === "agentree:close" && open) setOpen(false);
  });

  function mount() {
    document.body.appendChild(button);
  }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);

  window.Agentree = {
    loaded: true,
    open: function () {
      setOpen(true);
    },
    close: function () {
      setOpen(false);
    },
  };
})();
