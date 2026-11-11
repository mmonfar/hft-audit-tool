/* Live record screen. Fetches only from this server (same origin). No outside call. */
(function () {
  var q = new URLSearchParams(location.search);
  var run = q.get("run") || "";
  var fixedUpto = q.get("upto");
  var noFold = q.has("nofold");
  var app = document.getElementById("app");
  var state = { upto: fixedUpto === null ? null : parseInt(fixedUpto, 10), speed: parseInt(q.get("speed") || "30", 10), playing: false, timer: null, folded: false, lost: false };
  var LOST = '<section class="errbanner"><h2>Connection to the local server stopped. Reload this page.</h2></section>';

  function url() {
    var u = "/view?run=" + encodeURIComponent(run) + "&speed=" + state.speed;
    if (state.upto !== null) { u += "&upto=" + state.upto; }
    if (q.has("show")) { u += "&show=" + encodeURIComponent(q.get("show")); }
    return u;
  }
  function openIds() {
    return Array.prototype.map.call(app.querySelectorAll("details.drawer[open]"), function (d) { return d.getAttribute("data-keep"); });
  }
  function setPlay() {
    var b = app.querySelector('[data-action="play"]');
    if (b) { b.textContent = state.playing ? "Pause" : "Play"; }
  }
  function schedule(rec) {
    clearTimeout(state.timer);
    if (fixedUpto !== null || !state.playing) { return; }
    var upto = parseInt(rec.getAttribute("data-upto"), 10);
    var max = parseInt(rec.getAttribute("data-n"), 10);
    if (upto >= max) { state.playing = false; setPlay(); return; }
    state.timer = setTimeout(function () { state.upto = upto + 1; load(); }, parseInt(rec.getAttribute("data-delay"), 10));
  }
  function show(htmlText) {
    var keep = openIds();
    var narrow = window.matchMedia("(max-width:700px)").matches;
    var rw = app.querySelector("details.railwrap");
    if (rw && state.railOpen === undefined) { state.railOpen = false; }
    else if (rw) { state.railOpen = rw.open; }
    app.innerHTML = htmlText;
    keep.forEach(function (k) {
      var d = app.querySelector('details.drawer[data-keep="' + k + '"]');
      if (d) { d.setAttribute("open", ""); }
    });
    var rw2 = app.querySelector("details.railwrap");
    if (rw2) { if (state.railOpen) { rw2.setAttribute("open", ""); } else { rw2.removeAttribute("open"); } }
    var fold = app.querySelector("details.dropfold");
    if (fold && !noFold) {
      if (state.folded) { fold.removeAttribute("open"); }
      else { setTimeout(function () { state.folded = true; fold.removeAttribute("open"); }, 3000); }
    }
    var rows = app.querySelectorAll("table.ledger tbody tr");
    if (rows.length > 1) {
      var disputed = app.querySelector("table.ledger tbody tr .b-disputed");
      var target = disputed ? disputed.closest("tr") : rows[rows.length - 1];
      var box = app.querySelector(".scroll");
      if (box) {
        /* start on a full row, never on a cut one */
        var top = function (r) { return r.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop; };
        var want = disputed ? top(target) : box.scrollHeight;
        var start = 0;
        Array.prototype.forEach.call(rows, function (r) { var t = top(r); if (t <= want + 1) { start = t; } });
        box.scrollTop = Math.max(start - 2, 0);
      }
    }
    sel(state.pinned || null);
    var rec = app.querySelector("#rec");
    if (rec && rec.getAttribute("data-mode") === "replay") { setPlay(); schedule(rec); }
  }
  /* Box and ledger row link both ways. Display only: the referee judges on text. Instant, no animation. */
  function sel(n) {
    Array.prototype.forEach.call(app.querySelectorAll(".on"), function (e) { e.classList.remove("on"); });
    Array.prototype.forEach.call(app.querySelectorAll(".body,.redesign"), function (w) { if (n) { w.classList.add("has-sel"); } else { w.classList.remove("has-sel"); } });
    if (n) {
      Array.prototype.forEach.call(app.querySelectorAll('[data-n="' + n + '"]'), function (e) { e.classList.add("on"); });
    }
  }
  function pick(e, fromBox) {
    var t = e.target.closest("[data-n]");
    if (!t) { return null; }
    var n = t.getAttribute("data-n");
    sel(n);
    if (fromBox && window.matchMedia("(min-width:701px)").matches && t.classList.contains("bx")) {
      var row = app.querySelector('tr[data-n="' + n + '"]');
      if (row) { row.scrollIntoView({ block: "nearest" }); }
    }
    return n;
  }
  app.addEventListener("mouseover", function (e) { pick(e, true); });
  app.addEventListener("focusin", function (e) { pick(e, false); });
  app.addEventListener("mouseout", function (e) {
    var t = e.target.closest("[data-n]");
    if (t && !t.contains(e.relatedTarget)) { sel(state.pinned || null); }
  });
  app.addEventListener("focusout", function () { sel(state.pinned || null); });
  app.addEventListener("click", function (e) {
    var t = e.target.closest("[data-n]");
    if (t && !e.target.closest("button")) {
      var n = t.getAttribute("data-n");
      state.pinned = state.pinned === n ? null : n;
      sel(state.pinned);
      if (e.target.closest(".hint")) { var sg = app.querySelector(".stage"); if (sg) { sg.scrollIntoView({ block: "center" }); } }
    } else if (!t && e.target.closest(".stage,.rstage")) { state.pinned = null; sel(null); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { state.pinned = null; sel(null); var zl = document.getElementById("zoomlayer"); if (zl && zl.getAttribute("data-from") === "after") { closeAfter(); } else { closeZoom(); } }
    else if (e.key === "Enter" && e.target.closest && e.target.closest("[data-n]")) { e.target.click(); }
  });
  function closeZoom() {
    var z = document.getElementById("zoomlayer");
    if (z) { z.parentNode.removeChild(z); var b = app.querySelector(".enlarge"); if (b) { b.focus(); } }
  }
  function openZoom() {
    var stage = app.querySelector(".stage");
    if (!stage || document.getElementById("zoomlayer")) { return; }
    var z = document.createElement("div");
    z.id = "zoomlayer"; z.className = "zoomlayer"; z.setAttribute("role", "dialog"); z.setAttribute("aria-label", "Design, enlarged");
    z.innerHTML = '<div class="zbar"><p>Pinch to zoom. Boxes stay on the image.</p><button type="button" data-action="closezoom">Close</button></div><div class="zbody"></div>';
    var zb = z.querySelector(".zbody");
    zb.appendChild(stage.cloneNode(true));
    var row = app.querySelector('table.ledger tbody tr[data-n="' + (state.pinned || "1") + '"]') || app.querySelector("table.ledger tbody tr[data-n]");
    if (row) {
      var tb = document.createElement("table"); tb.className = "ledger";
      var tbody = document.createElement("tbody"); var c = row.cloneNode(true); c.classList.add("on");
      tbody.appendChild(c); tb.appendChild(tbody); zb.appendChild(tb);
    }
    document.body.appendChild(z);
    z.querySelector("button").focus();
  }
  /* Enlarge the redesign: After at open, Before on the switch. Tag always on top. Instant switch. */
  function openAfter() {
    var sec = app.querySelector(".redesign");
    var after = sec && sec.querySelector(".rstage");
    var before = app.querySelector(".body .stage");
    if (!after || document.getElementById("zoomlayer")) { return; }
    var cap = sec.querySelector(".cap");
    var z = document.createElement("div");
    z.id = "zoomlayer"; z.className = "zoomlayer"; z.setAttribute("role", "dialog"); z.setAttribute("aria-label", "Illustrative redesign, enlarged");
    z.innerHTML = '<p class="rtag">' + sec.querySelector(".rtag").textContent + '</p>' +
      '<div class="zbar"><p>' + (window.matchMedia('(pointer:coarse), (max-width:700px)').matches ? 'Pinch to zoom. ' : '') + 'Numbers stay on the image.</p><button type="button" data-action="closezoom">Close</button></div>' +
      '<div class="zbody"><div class="zswitch" role="group" aria-label="Show"><span>Show:</span>' +
      '<button type="button" data-zv="before" aria-pressed="false">Before</button>' +
      '<button type="button" data-zv="after" aria-pressed="true">&#10003; After</button></div>' +
      '<div class="zafter"></div><div class="zbefore zhide"></div><p class="cap"></p></div>';
    var zb = z.querySelector(".zbody");
    zb.querySelector(".zafter").appendChild(after.cloneNode(true));
    if (before) { zb.querySelector(".zbefore").appendChild(before.cloneNode(true)); }
    z.querySelector(".cap").textContent = cap.getAttribute("data-cap-after");
    var list = sec.querySelector(".rlist").cloneNode(true);
    zb.appendChild(list);
    var close2 = document.createElement("button"); close2.type = "button"; close2.setAttribute("data-action", "closezoom"); close2.textContent = "Close";
    close2.style.cssText = "width:100%;color:var(--slate);border-color:var(--slate);margin:12px 0";
    zb.appendChild(close2);
    z.setAttribute("data-from", "after");
    document.body.appendChild(z);
    z.querySelector("button").focus();
  }
  function closeAfter() {
    var z = document.getElementById("zoomlayer");
    if (z) { z.parentNode.removeChild(z); var b = app.querySelector(".redesign .enlarge"); if (b) { b.focus(); } }
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) { return; }
    var act = b.getAttribute("data-action");
    if (act === "closezoom") {
      var zl = document.getElementById("zoomlayer");
      if (zl && zl.getAttribute("data-from") === "after") { closeAfter(); } else { closeZoom(); }
    } else if (act === "enlarge-after") { openAfter(); }
    else if (b.getAttribute("data-zv")) {
      var zz = document.getElementById("zoomlayer"), v = b.getAttribute("data-zv"), a = v === "after";
      zz.querySelector(".zafter").classList.toggle("zhide", !a);
      zz.querySelector(".zbefore").classList.toggle("zhide", a);
      zz.querySelector('[data-zv="after"]').setAttribute("aria-pressed", a ? "true" : "false");
      zz.querySelector('[data-zv="before"]').setAttribute("aria-pressed", a ? "false" : "true");
      zz.querySelector('[data-zv="after"]').innerHTML = a ? "&#10003; After" : "After";
      zz.querySelector('[data-zv="before"]').innerHTML = a ? "Before" : "&#10003; Before";
      var c = app.querySelector(".redesign .cap");
      zz.querySelector(".zbody > .cap").textContent = c.getAttribute(a ? "data-cap-after" : "data-cap-before");
    }
  });
  function load() {
    fetch(url(), { cache: "no-store" }).then(function (r) { return r.text(); }).then(function (t) {
      state.lost = false; show(t);
    }).catch(function () { app.insertAdjacentHTML("afterbegin", LOST); });
  }
  app.addEventListener("click", function (e) {
    var t = e.target.closest("button");
    if (!t) { return; }
    var rec = app.querySelector("#rec");
    if (t.getAttribute("data-action") === "enlarge") { openZoom(); return; }
    if (t.getAttribute("data-action") === "play") {
      state.playing = !state.playing;
      if (state.playing && parseInt(rec.getAttribute("data-upto"), 10) >= parseInt(rec.getAttribute("data-n"), 10)) { state.upto = 0; load(); }
      else { setPlay(); schedule(rec); }
    } else if (t.getAttribute("data-speed")) {
      state.speed = parseInt(t.getAttribute("data-speed"), 10);
      if (state.upto === null) { state.upto = 0; }
      load();
    }
  });
  load();
  if (run && fixedUpto === null) {
    /* LIVE: the server pushes a row, then the page asks for a fresh view. REPLAY ignores this. */
    try {
      var es = new EventSource("/events?run=" + encodeURIComponent(run));
      es.onmessage = function () {
        var rec = app.querySelector("#rec");
        if (rec && rec.getAttribute("data-mode") === "live") { load(); }
      };
      es.onerror = function () {
        var rec = app.querySelector("#rec");
        if (rec && rec.getAttribute("data-mode") === "live" && !state.lost) {
          state.lost = true;
          app.insertAdjacentHTML("afterbegin", LOST);
        }
      };
    } catch (err) { state.lost = false; }
  }
})();
