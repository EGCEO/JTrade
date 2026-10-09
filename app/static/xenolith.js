/* ═══════════════════════════════════════════════════════════════════════════
   XENOLITH LEDGER — 3-D Interaction Layer
   Background particles, parallax tilt, sound, etch-in, execution ring.
   Self-contained IIFE — does not modify any existing app code.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var IS_TOUCH = ('ontouchstart' in window) || navigator.maxTouchPoints > 0;

  /* ── 1. Background Canvas: Etched Grid + Drifting Particles ──────────────── */
  var canvas, ctx, particles = [], gridPulse = 0, dpr = 1;

  function initCanvas() {
    if (REDUCED) return;
    canvas = document.createElement('canvas');
    canvas.id = 'xenolith-canvas';
    document.body.appendChild(canvas);
    ctx = canvas.getContext('2d');
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);
    spawnParticles();
    animateCanvas();
  }

  function resizeCanvas() {
    if (!canvas) return;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = window.innerWidth * dpr;
    canvas.height = window.innerHeight * dpr;
    canvas.style.width = window.innerWidth + 'px';
    canvas.style.height = window.innerHeight + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function spawnParticles() {
    var count = window.innerWidth < 768 ? 18 : 40;
    particles = [];
    for (var i = 0; i < count; i++) {
      particles.push({
        x: Math.random() * window.innerWidth,
        y: Math.random() * window.innerHeight,
        vx: (Math.random() - 0.5) * 0.15,
        vy: (Math.random() - 0.5) * 0.15,
        r: Math.random() * 1.5 + 0.5,
        a: Math.random() * 0.3 + 0.05,
        hue: Math.random() > 0.7 ? 'amber' : 'teal'
      });
    }
  }

  function animateCanvas() {
    if (!ctx) return;
    var w = window.innerWidth, h = window.innerHeight;
    ctx.clearRect(0, 0, w, h);

    // Etched grid lines
    var gridSize = 48;
    var gridAlpha = 0.03 + gridPulse * 0.06;
    ctx.strokeStyle = 'rgba(0, 224, 196, ' + gridAlpha + ')';
    ctx.lineWidth = 1;
    for (var x = 0; x < w; x += gridSize) {
      ctx.beginPath();
      ctx.moveTo(x, 0); ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (var y = 0; y < h; y += gridSize) {
      ctx.beginPath();
      ctx.moveTo(0, y); ctx.lineTo(w, y);
      ctx.stroke();
    }
    if (gridPulse > 0) gridPulse *= 0.95;

    // Drifting particles
    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0) p.x = w; if (p.x > w) p.x = 0;
      if (p.y < 0) p.y = h; if (p.y > h) p.y = 0;

      var color = p.hue === 'amber' ? '255, 182, 39' : '0, 224, 196';
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + color + ', ' + p.a + ')';
      ctx.shadowBlur = 6;
      ctx.shadowColor = 'rgba(' + color + ', ' + (p.a * 0.5) + ')';
      ctx.fill();
      ctx.shadowBlur = 0;
    }
    requestAnimationFrame(animateCanvas);
  }

  function pulseGrid() {
    gridPulse = 1;
  }

  /* ── 2. Sound System: Web Audio API ──────────────────────────────────────── */
  var audioCtx = null;
  var muted = localStorage.getItem('xenolith-muted') === '1';

  function ensureAudio() {
    if (!audioCtx) {
      try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      } catch (e) { return null; }
    }
    if (audioCtx.state === 'suspended') audioCtx.resume();
    return audioCtx;
  }

  function playPing() {
    if (muted || REDUCED) return;
    var ac = ensureAudio();
    if (!ac) return;
    var now = ac.currentTime;
    // Sharp resonant ping: two harmonic sine oscillators
    [1200, 2400].forEach(function (freq, idx) {
      var osc = ac.createOscillator();
      var gain = ac.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, now);
      gain.gain.setValueAtTime(0, now);
      gain.gain.linearRampToValueAtTime(idx === 0 ? 0.15 : 0.06, now + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);
      osc.connect(gain).connect(ac.destination);
      osc.start(now);
      osc.stop(now + 0.4);
    });
  }

  function playDissonant() {
    if (muted || REDUCED) return;
    var ac = ensureAudio();
    if (!ac) return;
    var now = ac.currentTime;
    // Low dissonant tone: three detuned oscillators
    [110, 116, 122].forEach(function (freq) {
      var osc = ac.createOscillator();
      var gain = ac.createGain();
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(freq, now);
      gain.gain.setValueAtTime(0, now);
      gain.gain.linearRampToValueAtTime(0.08, now + 0.05);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.9);
      osc.connect(gain).connect(ac.destination);
      osc.start(now);
      osc.stop(now + 0.9);
    });
  }

  /* ── 3. Mute Toggle Button ───────────────────────────────────────────────── */
  function initMuteToggle() {
    var btn = document.createElement('button');
    btn.id = 'xenolith-mute';
    btn.title = 'Toggle Xenolith sound effects';
    btn.textContent = muted ? '🔇' : '🔊';
    if (muted) btn.classList.add('muted');
    btn.addEventListener('click', function () {
      muted = !muted;
      localStorage.setItem('xenolith-muted', muted ? '1' : '0');
      btn.textContent = muted ? '🔇' : '🔊';
      btn.classList.toggle('muted', muted);
      if (!muted) playPing();
    });
    document.body.appendChild(btn);
  }

  /* ── 4. Parallax Tilt (event delegation, non-touch only) ─────────────────── */
  if (!IS_TOUCH && !REDUCED) {
    document.addEventListener('mousemove', function (e) {
      var el = e.target.closest('.card, .stat-card, .bot-card');
      if (!el) return;
      var rect = el.getBoundingClientRect();
      var cx = rect.left + rect.width / 2;
      var cy = rect.top + rect.height / 2;
      var dx = (e.clientX - cx) / rect.width;
      var dy = (e.clientY - cy) / rect.height;
      var maxTilt = 3;
      el.style.transform =
        'perspective(800px) rotateX(' + (-dy * maxTilt).toFixed(2) + 'deg) rotateY(' + (dx * maxTilt).toFixed(2) + 'deg)';
    });
    document.addEventListener('mouseleave', function () {
      document.querySelectorAll('.card, .stat-card, .bot-card').forEach(function (el) {
        el.style.transform = '';
      });
    });
  }

  /* ── 5. Alert Interception: ping on fills, dissonant on errors ──────────── */
  var _origAlert = window.alert;
  window.alert = function (msg) {
    var m = typeof msg === 'string' ? msg : String(msg);
    if (m.indexOf('✅') !== -1 || m.indexOf('successfully') !== -1) {
      playPing();
      triggerShockwave();
    }
    if (m.indexOf('⚠️') !== -1 || m.indexOf('Error') !== -1 ||
        m.indexOf('failed') !== -1 || m.indexOf('error') !== -1) {
      playDissonant();
    }
    return _origAlert.call(window, msg);
  };

  /* ── 6. Execution Core: Rotating Ring + Shockwave ───────────────────────── */
  var execRing = null;

  function triggerExecRing() {
    if (REDUCED) return;
    removeExecRing();
    execRing = document.createElement('div');
    execRing.className = 'xenolith-exec-ring';
    document.body.appendChild(execRing);
  }

  function lockExecRing() {
    if (execRing) execRing.classList.add('locked');
  }

  function triggerShockwave() {
    if (REDUCED) return;
    lockExecRing();
    var sw = document.createElement('div');
    sw.className = 'xenolith-shockwave';
    document.body.appendChild(sw);
    setTimeout(function () { sw.remove(); }, 700);
    setTimeout(removeExecRing, 400);
  }

  function removeExecRing() {
    if (execRing) { execRing.remove(); execRing = null; }
    var existing = document.querySelector('.xenolith-exec-ring');
    if (existing) existing.remove();
  }

  /* ── 7. MutationObserver: etch-in, warning shimmer, exec ring ───────────── */
  var prevRowCount = 0;

  function processMutations() {
    // Etch-in: new table rows
    var rows = document.querySelectorAll('#page-content table tbody tr');
    if (rows.length > prevRowCount && prevRowCount > 0) {
      var newCount = rows.length - prevRowCount;
      for (var i = rows.length - newCount; i < rows.length; i++) {
        if (rows[i] && !rows[i].classList.contains('xenolith-etched')) {
          rows[i].classList.add('xenolith-etch');
          rows[i].classList.add('xenolith-etched');
          (function (r) {
            setTimeout(function () { r.classList.remove('xenolith-etch'); }, 1500);
          })(rows[i]);
        }
      }
      pulseGrid();
    }
    prevRowCount = rows.length;

    // Warning shimmer on error pills
    document.querySelectorAll('.pill-error, .pill-rejected, .pill-offline').forEach(function (el) {
      if (!el.classList.contains('xenolith-warning')) {
        el.classList.add('xenolith-warning');
      }
    });

    // Execution ring when modal at step 3
    var step3 = document.getElementById('execConfirmText');
    if (step3 && !document.querySelector('.xenolith-exec-ring')) {
      triggerExecRing();
    }
    if (!document.getElementById('execModalOverlay')) {
      removeExecRing();
    }
  }

  var observer = null;
  function initObserver() {
    var target = document.getElementById('app');
    if (!target) { setTimeout(initObserver, 200); return; }
    observer = new MutationObserver(function () {
      // Debounce with microtask
      if (observer._tick) return;
      observer._tick = true;
      Promise.resolve().then(function () {
        observer._tick = false;
        processMutations();
      });
    });
    observer.observe(target, { childList: true, subtree: true });
    // Also observe body for modal (modal is appended to body, not #app)
    var bodyObserver = new MutationObserver(function () {
      if (observer._tick) return;
      observer._tick = true;
      Promise.resolve().then(function () {
        observer._tick = false;
        processMutations();
      });
    });
    bodyObserver.observe(document.body, { childList: true, subtree: false });
  }

  /* ── 8. Opportunity Pulse: poll for new opps to pulse bot grid ───────────── */
  var prevOppCount = -1;
  function pollOpportunities() {
    if (!token) return;
    fetch('/api/opportunities?limit=1', {
      headers: { 'Authorization': 'Bearer ' + token }
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var count = data.length;
        if (prevOppCount >= 0 && count > prevOppCount) {
          // New opportunity detected
          pulseGrid();
          var bg = document.querySelector('.bot-grid');
          if (bg) {
            bg.classList.remove('xenolith-pulse');
            void bg.offsetWidth; // force reflow
            bg.classList.add('xenolith-pulse');
            setTimeout(function () { bg.classList.remove('xenolith-pulse'); }, 1600);
          }
        }
        prevOppCount = count;
      })
      .catch(function () {});
  }

  /* ── 9. Init ─────────────────────────────────────────────────────────────── */
  function init() {
    initCanvas();
    initMuteToggle();
    initObserver();
    if (!REDUCED) {
      setInterval(pollOpportunities, 8000);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
