/* Shared header/footer, header scroll state, mobile nav, active link and scroll reveals. */
(function () {
  const header = `<header class="site-header solid"><div class="wrap">
    <a class="brand" href="./"><span class="pill-logo" aria-hidden="true"></span><span><b>Science</b> of Placebo</span></a>
    <button class="nav-toggle" aria-label="Menu" aria-expanded="false" aria-controls="nav"><span></span></button>
    <nav class="nav" id="nav" aria-label="Main">
      <a href="feed.html">New papers</a>
      <a href="database.html">Database</a>
      <a href="bibliometrics.html">Bibliometrics</a>
      <a href="network.html">Researchers</a>
      <a href="newsevents.html">News &amp; events</a>
      <a href="resources.html">Resources</a>
      <a href="discuss.html">Discussion</a>
      <div class="menu"><a href="join.html" class="menu-btn" aria-haspopup="true" aria-expanded="false">Members ▾</a>
        <div class="menu-list"><a href="join.html">Join or sign in</a><a href="mylist.html">My list</a><a href="picks.html">Community picks</a></div></div>
      <a href="about.html">About</a>
    </nav></div></header>`;
  const footer = `<footer class="site-footer"><div class="wrap">
    <div><strong>Science of Placebo</strong>A curated, continuously updated bibliography of placebo and nocebo research, run by the Cognitive and Affective Neuroscience Lab at Dartmouth. Inspired by the <a href="https://jips.online/" target="_blank" rel="noopener">JIPS placebo database</a>. <span id="foot-updated"></span></div>
    <div><strong>Explore</strong><ul><li><a href="feed.html">New papers</a></li><li><a href="database.html">Database</a></li><li><a href="bibliometrics.html">Bibliometrics</a></li><li><a href="network.html">Researcher network</a></li><li><a href="news.html">In the news</a></li><li><a href="feed.xml">RSS feed</a></li></ul></div>
    <div><strong>Community</strong><ul><li><a href="events.html">Events</a></li><li><a href="resources.html">Resources</a></li><li><a href="discuss.html">Discussion</a></li><li><a href="mylist.html">My list</a></li><li><a href="join.html">Join the community</a></li><li><a href="https://github.com/torwager/scienceofplacebo">Source &amp; data on GitHub</a></li></ul></div>
    <div class="credit-row"><span class="credit">Designed by <a href="https://torwager.github.io" target="_blank" rel="noopener">Tor Wager</a> · <a href="http://canlab.science/" target="_blank" rel="noopener">CANlab</a></span></div>
  </div></footer>`;
  const h = document.getElementById("site-header"); if (h) h.outerHTML = header;
  const f = document.getElementById("site-footer"); if (f) f.outerHTML = footer;

  const hdr = document.querySelector(".site-header");
  const onScroll = () => hdr && hdr.classList.toggle("scrolled", window.scrollY > 8);
  window.addEventListener("scroll", onScroll, { passive: true }); onScroll();

  if (window.SOP) SOP.updateListBadge();
  const here = (location.pathname.split("/").pop() || "index.html");
  document.querySelectorAll(".nav a").forEach(a => { if (a.getAttribute("href") === here && !a.classList.contains("cta")) a.classList.add("active"); });

  const toggle = document.querySelector(".nav-toggle"), nav = document.getElementById("nav");
  if (toggle && nav) {
    toggle.addEventListener("click", () => { const open = nav.classList.toggle("open"); toggle.setAttribute("aria-expanded", String(open)); });
    nav.addEventListener("click", e => { if (e.target.tagName === "A") nav.classList.remove("open"); });
  }

  document.querySelectorAll(".menu-btn").forEach(b => b.addEventListener("click", e => { const m = b.parentElement; if (!m.classList.contains("open") && window.matchMedia("(hover: none)").matches) { e.preventDefault(); m.classList.add("open"); b.setAttribute("aria-expanded", "true"); } }));
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const rvs = document.querySelectorAll(".rv");
  if (reduce || !("IntersectionObserver" in window)) { rvs.forEach(el => el.classList.add("in")); return; }
  const io = new IntersectionObserver(entries => { entries.forEach(en => { if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); } }); }, { threshold: 0.12 });
  rvs.forEach(el => io.observe(el));
})();
