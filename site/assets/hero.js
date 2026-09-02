/* The placebo pill hero.
   A plain two-tone capsule sits over a colorful clinical scene. Moving the cursor (or a finger) over the
   capsule punches soft circular windows into the plain veil, revealing the picture beneath; each window
   lingers for ~7 s and fades, so a curious reader can uncover the whole scene. Dependency-free canvas. */
(function () {
  const pill = document.getElementById("pill");
  const canvas = document.getElementById("veil");
  if (!pill || !canvas) return;
  const ctx = canvas.getContext("2d");
  const LIFE = 7000;          // ms a reveal window stays open
  const FADE = 1400;          // ms of fade at the end of its life
  const RADIUS = 0.17;        // reveal radius as a fraction of the capsule height... scaled below
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let W = 0, H = 0, dpr = 1, points = [], raf = null, lastMove = 0, idle = true;

  function resize() {
    const r = pill.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.max(1, Math.round(r.width)); H = Math.max(1, Math.round(r.height));
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + "px"; canvas.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw(performance.now());
  }

  function veil() {
    // two-tone capsule: chalk white left half, pill-blue right half, seam + gloss
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, W, H);
    const dark = document.documentElement.getAttribute("data-theme") === "dark" ||
      (!document.documentElement.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
    const left = ctx.createLinearGradient(0, 0, 0, H);
    left.addColorStop(0, dark ? "#e9e6dd" : "#fffdf7"); left.addColorStop(.55, dark ? "#d7d3c8" : "#f3efe6"); left.addColorStop(1, dark ? "#bdb8ab" : "#ddd8cc");
    const right = ctx.createLinearGradient(0, 0, 0, H);
    right.addColorStop(0, "#9dbbdc"); right.addColorStop(.55, "#6f8fb0"); right.addColorStop(1, "#4a6a90");
    ctx.fillStyle = left; ctx.fillRect(0, 0, W / 2, H);
    ctx.fillStyle = right; ctx.fillRect(W / 2, 0, W / 2, H);
    // seam
    ctx.fillStyle = "rgba(26,35,50,.18)"; ctx.fillRect(W / 2 - 1, 0, 2, H);
    // gloss highlight along the top
    const gloss = ctx.createLinearGradient(0, 0, 0, H * .5);
    gloss.addColorStop(0, "rgba(255,255,255,.55)"); gloss.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = gloss;
    ctx.beginPath(); ctx.ellipse(W * .5, H * .16, W * .42, H * .12, 0, 0, Math.PI * 2); ctx.fill();
    // soft inner shadow at the bottom edge for roundness
    const shade = ctx.createLinearGradient(0, H * .6, 0, H);
    shade.addColorStop(0, "rgba(26,35,50,0)"); shade.addColorStop(1, "rgba(26,35,50,.22)");
    ctx.fillStyle = shade; ctx.fillRect(0, H * .6, W, H * .4);
  }

  function draw(now) {
    veil();
    points = points.filter(p => now - p.t < LIFE);
    ctx.globalCompositeOperation = "destination-out";
    const R = Math.max(70, H * 0.42);
    for (const p of points) {
      const age = now - p.t;
      const life = age > LIFE - FADE ? Math.max(0, (LIFE - age) / FADE) : 1;
      const grow = Math.min(1, age / 220);               // quick bloom on arrival
      const r = R * (0.6 + 0.4 * grow);
      const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r);
      g.addColorStop(0, `rgba(0,0,0,${life})`);
      g.addColorStop(0.55, `rgba(0,0,0,${life * 0.95})`);
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";
    pill.classList.toggle("revealing", points.length > 0);
    if (points.length) raf = requestAnimationFrame(draw); else raf = null;
  }

  function reveal(x, y) {
    const r = canvas.getBoundingClientRect();
    const px = x - r.left, py = y - r.top;
    if (px < 0 || py < 0 || px > W || py > H) return;
    const now = performance.now();
    // throttle: one point per ~14px of travel keeps the trail continuous without flooding
    const last = points[points.length - 1];
    if (last && Math.hypot(last.x - px, last.y - py) < 14 && now - last.t < 120) return;
    points.push({ x: px, y: py, t: now });
    if (points.length > 400) points.shift();
    lastMove = now; idle = false;
    if (!raf) raf = requestAnimationFrame(draw);
  }

  pill.addEventListener("pointermove", e => reveal(e.clientX, e.clientY));
  pill.addEventListener("pointerdown", e => reveal(e.clientX, e.clientY));
  pill.addEventListener("touchmove", e => { const t = e.touches[0]; if (t) reveal(t.clientX, t.clientY); }, { passive: true });

  // A gentle ambient peek before the first interaction, so the hero hints at what it hides.
  if (!reduce) {
    setTimeout(() => {
      if (idle) {
        const r = canvas.getBoundingClientRect();
        reveal(r.left + W * 0.62, r.top + H * 0.5);
      }
    }, 2200);
  }
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(resize, 120); });
  const mq = window.matchMedia("(prefers-color-scheme: dark)"); if (mq.addEventListener) mq.addEventListener("change", () => draw(performance.now()));
  resize();
})();
