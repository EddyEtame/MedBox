/* One way to every page, from every page: the ship, the board, the crew
 * dashboard, and each member's own space on their own port. Eddy, 24 Sep:
 * "there's no button to everyone's personal dashboard". */
(function () {
  "use strict";
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  var ctl = document.querySelector(".ctl");
  if (!ctl) return;
  var here = location.pathname;
  var links = [["/", "Vaisseau"], ["/board", "Tableau"], ["/crew", "Équipage"]];
  var menu = document.createElement("details");
  menu.className = "nav-menu";
  menu.innerHTML = "<summary class=\"btn\">Navigation</summary><div class=\"nav-list\"></div>";
  ctl.appendChild(menu);
  var list = menu.querySelector(".nav-list");
  function render(pages) {
    var html = links.filter(function (l) { return l[0] !== here && !(l[0] === "/" && here === "/ship"); })
      .map(function (l) { return '<a href="' + l[0] + '">' + l[1] + "</a>"; }).join("");
    if (pages.length) {
      html += '<div class="nav-h">Espaces personnels</div>' + pages.map(function (p) {
        var url = p.port ? ("http://" + location.hostname + ":" + p.port + "/") : ("/me/" + encodeURIComponent(p.id));
        return '<a href="' + esc(url) + '">' + esc(p.name) + (p.port ? ' <span class="hint">' + p.port + "</span>" : "") + "</a>";
      }).join("");
    }
    list.innerHTML = html;
  }
  render([]);
  fetch("/api/status", { cache: "no-store" }).then(function (r) { return r.json(); })
    .then(function (s) { render(s.personal_pages || []); }).catch(function () {});
  document.addEventListener("click", function (e) { if (!menu.contains(e.target)) menu.open = false; });
})();
