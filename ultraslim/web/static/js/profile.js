/* Höhenprofil als Hauptanzeige (Game-Design-Dokument, Abschnitt 10.1).
 *
 * Keine Karte: Auf einer Karte verteilen sich 250 Fahrer über eine
 * gewundene Linie, deren Verlauf nichts über den Rennstand aussagt. Im
 * Profil ist die x-Achse die Distanz – Reihenfolge, Abstände und das
 * kommende Gelände sind auf einen Blick lesbar.
 *
 * Technisch ein einzelnes Canvas: Das Profil wird einmal als Pfad in ein
 * Offscreen-Canvas gerendert, pro Frame werden nur die Fahrerpunkte neu
 * gezeichnet. 250 Punkte auf Canvas sind unkritisch – als 250 DOM-Knoten
 * in SVG dagegen nicht.
 */

const GRADE_COLORS = [
  [-0.06, '#2f6fbf'], // Abfahrt
  [-0.02, '#3d7fd1'],
  [0.02, '#3f8f5a'],  // flach
  [0.05, '#9fa83c'],
  [0.08, '#d9853f'],
  [0.11, '#d9534f'],
  [1.0, '#ff3b30'],   // Steilrampe
];

function gradeColor(g) {
  for (const [limit, color] of GRADE_COLORS) if (g <= limit) return color;
  return '#ff3b30';
}

//: Kandidaten für den Abstand der Höhenlinien, in Metern.
const ELE_STEPS = [10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000];

export class ProfileView {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} opts  { window_m: null = Gesamtstrecke, sonst Ausschnittbreite }
   */
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.windowM = opts.windowM || null;
    this.height = opts.height || 150;
    this.showLabels = opts.showLabels !== false;
    // Der Streckeneditor zeichnet Splits und Servicepunkte selbst: Dort
    // sind sie anfassbar und müssen bei jedem Mausschritt neu liegen,
    // hier stecken sie im vorgerenderten Untergrund.
    this.showMarkers = opts.showMarkers !== false;
    // Höhenachse: nur dort sinnvoll, wo der Ausschnitt einen kleinen
    // Höhenbereich aufspannt. Im Übersichtsband über 2500 km stünden
    // fünf Beschriftungen für eine Kurve, die ohnehin alles zeigt.
    this.eleAxis = opts.eleAxis === true;
    this.route = null;
    this.positions = [];
    this.focus = -1;
    this.neighbours = new Set();
    this.conditions = [];
    this.viewStart = 0;
    this.viewEnd = 0;
    this.padX = 6;
    this.padLeft = 6;
    this.padTop = 6;
    this.padBottom = 12;
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this._base = null;      // vorgerendertes Profil
    this._baseKey = '';
    this.onSeek = null;     // Klick auf das Profil
    this.onHover = null;

    canvas.addEventListener('mousemove', (e) => this._hover(e));
    canvas.addEventListener('mouseleave', () => this.onHover && this.onHover(null));
    canvas.addEventListener('click', (e) => this._click(e));
    window.addEventListener('resize', () => { this._baseKey = ''; this.draw(); });
  }

  setRoute(route) {
    this.route = route;
    this._baseKey = '';
    this.viewStart = 0;
    this.viewEnd = route.distance_m;
  }

  /** Untergrund verwerfen – nötig, wenn sich Marker geändert haben. */
  invalidate() { this._baseKey = ''; }

  setFrame(positions, focusEntry, neighbourIds) {
    this.positions = positions;
    this.focus = focusEntry;
    this.neighbours = new Set(neighbourIds || []);
  }

  /** Rasterschrittweite in Metern. Das Profil liegt gleichmäßig. */
  get step() { return (this.route && this.route.profile.step_m) || 100; }

  /** Sichtfenster aus der Fokusposition ableiten. */
  _updateWindow() {
    if (!this.route) return;
    if (!this.windowM) {
      this.viewStart = 0;
      this.viewEnd = this.route.distance_m;
      return;
    }
    const focusPos = this.positions.find((p) => p[0] === this.focus);
    const centre = focusPos ? focusPos[1] : 0;
    const half = this.windowM / 2;
    let lo = centre - half;
    let hi = centre + half;
    if (lo < 0) { hi -= lo; lo = 0; }
    if (hi > this.route.distance_m) {
      lo = Math.max(0, lo - (hi - this.route.distance_m));
      hi = this.route.distance_m;
    }
    this.viewStart = lo;
    this.viewEnd = hi;
  }

  _layout() {
    const cssW = this.canvas.clientWidth || 800;
    const cssH = this.height;
    if (this.canvas.width !== Math.round(cssW * this.dpr) || this.canvas.height !== Math.round(cssH * this.dpr)) {
      this.canvas.width = Math.round(cssW * this.dpr);
      this.canvas.height = Math.round(cssH * this.dpr);
      this.canvas.style.height = cssH + 'px';
      this._baseKey = '';
    }
    return { w: cssW, h: cssH };
  }

  x(dist) {
    const { w } = this._size;
    const span = Math.max(this.viewEnd - this.viewStart, 1);
    return ((dist - this.viewStart) / span) * (w - this.padLeft - this.padX) + this.padLeft;
  }

  y(ele) {
    const { h } = this._size;
    const span = Math.max(this.eleMax - this.eleMin, 20);
    return h - this.padBottom - ((ele - this.eleMin) / span) * (h - this.padBottom - this.padTop);
  }

  distAt(px) {
    const { w } = this._size;
    const span = this.viewEnd - this.viewStart;
    return this.viewStart + ((px - this.padLeft) / (w - this.padLeft - this.padX)) * span;
  }

  /** Profil, Anstiege, Splits und Servicepunkte einmal vorrendern. */
  _renderBase() {
    const key = `${this.viewStart.toFixed(0)}|${this.viewEnd.toFixed(0)}|${this.canvas.width}`;
    if (key === this._baseKey && this._base) return;

    const { w, h } = this._size;
    const off = document.createElement('canvas');
    off.width = this.canvas.width;
    off.height = this.canvas.height;
    const c = off.getContext('2d');
    c.scale(this.dpr, this.dpr);

    const p = this.route.profile;
    const lo = this._indexBefore(this.viewStart);
    const hi = this._indexAfter(this.viewEnd);

    let mn = Infinity, mx = -Infinity;
    for (let i = lo; i <= hi; i++) { mn = Math.min(mn, p.ele_m[i]); mx = Math.max(mx, p.ele_m[i]); }
    const pad = Math.max((mx - mn) * 0.15, 12);
    this.eleMin = mn - pad;
    this.eleMax = mx + pad;

    c.fillStyle = '#0d121c';
    c.fillRect(0, 0, w, h);

    if (this.eleAxis) this._drawEleAxis(c, w, h);

    // Anstiege schraffiert hinterlegen
    for (const climb of this.route.climbs) {
      if (climb.dist_end_m < this.viewStart || climb.dist_start_m > this.viewEnd) continue;
      const x0 = this.x(climb.dist_start_m);
      const x1 = this.x(climb.dist_end_m);
      c.fillStyle = 'rgba(217,83,79,.10)';
      c.fillRect(x0, this.padTop, Math.max(x1 - x0, 1), h - this.padTop - this.padBottom);
      if (!this.showLabels || x1 - x0 <= 26) continue;
      // Die Kategorie allein sagt "hier ist ein Anstieg". Länge und
      // Höhenmeter sagen, was er kostet — und genau das ist die Zahl,
      // über die im Fernsehen geredet wird. Nur so viel, wie in den
      // Balken passt: Ein abgeschnittener Text ist schlechter als eine
      // kurze Beschriftung.
      const width = x1 - x0;
      const long = `${climb.category} · ${(climb.length_m / 1000).toFixed(1)} km · ${Math.round(climb.ascent_m)} hm`;
      const mid = `${climb.category} · ${(climb.length_m / 1000).toFixed(1)} km`;
      c.font = '600 10px system-ui, sans-serif';
      const label = c.measureText(long).width + 8 < width ? long
        : c.measureText(mid).width + 8 < width ? mid : climb.category;
      c.fillStyle = '#e08a86';
      c.textAlign = 'center';
      c.fillText(label, (x0 + x1) / 2, this.padTop + 10);
      // Gipfelkante: Ohne sie liest man den Anstieg als Fläche, nicht
      // als Ziel. Der Punkt, auf den es ankommt, ist die rechte Kante.
      c.beginPath();
      c.moveTo(x1, this.padTop);
      c.lineTo(x1, h - this.padBottom);
      c.strokeStyle = 'rgba(224,138,134,.45)';
      c.lineWidth = 1;
      c.stroke();
    }

    // Profilfläche, segmentweise nach Steigung eingefärbt
    const baseY = h - this.padBottom;
    const step = this.step;
    for (let i = lo; i < hi; i++) {
      const x0 = this.x(i * step);
      const x1 = this.x((i + 1) * step);
      c.beginPath();
      c.moveTo(x0, baseY);
      c.lineTo(x0, this.y(p.ele_m[i]));
      c.lineTo(x1, this.y(p.ele_m[i + 1]));
      c.lineTo(x1, baseY);
      c.closePath();
      c.fillStyle = gradeColor(p.grade[i]);
      c.globalAlpha = 0.55;
      c.fill();
      c.globalAlpha = 1;
    }
    // Grenzlinie
    c.beginPath();
    for (let i = lo; i <= hi; i++) {
      const xx = this.x(i * step);
      const yy = this.y(p.ele_m[i]);
      i === lo ? c.moveTo(xx, yy) : c.lineTo(xx, yy);
    }
    c.strokeStyle = '#dbe4f5';
    c.lineWidth = 1.1;
    c.stroke();

    // Splits
    c.font = '9px ui-monospace, monospace';
    for (const split of (this.showMarkers ? this.route.splits : [])) {
      if (split.dist_m < this.viewStart || split.dist_m > this.viewEnd) continue;
      const xx = this.x(split.dist_m);
      c.beginPath();
      c.moveTo(xx, this.padTop);
      c.lineTo(xx, baseY);
      c.strokeStyle = split.kind === 'summit' ? 'rgba(255,194,71,.55)'
        : split.kind === 'finish' ? 'rgba(74,222,128,.7)' : 'rgba(120,140,180,.28)';
      c.lineWidth = split.kind === 'interval' ? 1 : 1.5;
      c.stroke();
      if (this.showLabels && split.kind !== 'interval') {
        c.fillStyle = split.kind === 'finish' ? '#4ade80' : '#ffc247';
        c.textAlign = 'left';
        c.fillText(split.kind === 'finish' ? 'Ziel' : '▲', xx + 2, this.padTop + 9);
      }
    }

    // Kilometerachse
    c.fillStyle = '#5c6880';
    c.font = '9px ui-monospace, monospace';
    c.textAlign = 'center';
    const span = this.viewEnd - this.viewStart;
    const stepKm = span > 900000 ? 200 : span > 400000 ? 100 : span > 120000 ? 25 : span > 40000 ? 10 : 5;
    for (let km = Math.ceil(this.viewStart / 1000 / stepKm) * stepKm; km * 1000 <= this.viewEnd; km += stepKm) {
      c.fillText(String(km), this.x(km * 1000), h - 2);
    }

    this._base = off;
    this._baseKey = key;
  }

  /** Höhenlinien mit Meterangabe – und die Grenze, ab der Höhe kostet.
   *
   * Ohne Achse ist das Profil eine Form ohne Maßstab: Dieselbe Zacke
   * bedeutet im Ausschnitt einmal dreißig und einmal dreihundert
   * Höhenmeter. Die 1500er-Linie ist keine Verzierung, sondern eine
   * Modellgrenze — darüber verliert der Fahrer messbar Leistung, und
   * auf den Dolomiten liegt ein Fünftel der Strecke darüber.
   */
  _drawEleAxis(c, w, h) {
    const span = Math.max(this.eleMax - this.eleMin, 20);
    const step = ELE_STEPS.find((s) => span / s <= 6) || ELE_STEPS[ELE_STEPS.length - 1];
    c.font = '9px ui-monospace, monospace';
    c.textAlign = 'right';
    for (let ele = Math.ceil(this.eleMin / step) * step; ele <= this.eleMax; ele += step) {
      const yy = this.y(ele);
      c.beginPath();
      c.moveTo(this.padLeft, yy);
      c.lineTo(w - this.padX, yy);
      c.strokeStyle = 'rgba(120,140,180,.16)';
      c.lineWidth = 1;
      c.stroke();
      c.fillStyle = '#5c6880';
      c.fillText(String(Math.round(ele)), this.padLeft - 4, yy + 3);
    }
  }

  /* Das Raster ist gleichmäßig, der Index also eine Division.
   *
   * Vorher standen hier zwei lineare Suchen über das Distanzarray. Bei
   * tausend Kilometern sind das zehntausend Punkte, und ``_eleAt``
   * läuft je Bild einmal pro Fahrer — dreihundert lineare Suchen über
   * zehntausend Einträge, dreimal je Sekunde. Mit gleichmäßigem Raster
   * ist beides eine Rechnung statt einer Schleife.
   */
  _lastIndex() { return this.route.profile.ele_m.length - 1; }

  _indexBefore(value) {
    return Math.min(Math.max(Math.floor(value / this.step), 0), this._lastIndex());
  }

  _indexAfter(value) {
    return Math.min(Math.max(Math.ceil(value / this.step), 0), this._lastIndex());
  }

  draw() {
    if (!this.route) return;
    this._size = this._layout();
    this.padX = 6;
    this.padLeft = this.eleAxis ? 34 : 6;
    this.padTop = 6;
    this.padBottom = 12;
    this._updateWindow();
    this._renderBase();

    const ctx = this.ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.drawImage(this._base, 0, 0);
    ctx.scale(this.dpr, this.dpr);

    // Zustände des Fokusfahrers als Balken unter der Profillinie:
    // "Magenprobleme km 1180-1290" wird dadurch sichtbar statt nur wirksam.
    const barY = this._size.h - this.padBottom + 1;
    for (const c of this.conditions) {
      const x0 = this.x(c.start_dist_m);
      const x1 = this.x(c.end_dist_m);
      if (x1 < this.padX || x0 > this._size.w - this.padX) continue;
      ctx.fillStyle = c.active ? 'rgba(248,113,122,.85)' : 'rgba(248,113,122,.35)';
      ctx.fillRect(x0, barY, Math.max(x1 - x0, 2), 3);
    }

    const p = this.route.profile;
    let focusPoint = null;
    // Erst der graue Rest, dann die Nachbarn, zuletzt der Fokus – so
    // liegt der wichtige Punkt garantiert obenauf.
    for (const pass of [0, 1, 2]) {
      for (const [id, dist, , state] of this.positions) {
        if (dist < this.viewStart - 500 || dist > this.viewEnd + 500) continue;
        const isFocus = id === this.focus;
        const isNear = this.neighbours.has(id);
        const which = isFocus ? 2 : isNear ? 1 : 0;
        if (which !== pass) continue;

        const xx = this.x(dist);
        const yy = this.y(this._eleAt(p, dist)) - 3;
        ctx.beginPath();
        ctx.arc(xx, yy, isFocus ? 5 : isNear ? 3 : 2, 0, Math.PI * 2);
        if (isFocus) {
          ctx.fillStyle = state === 1 ? '#f8717a' : '#ffc247';
          focusPoint = [xx, yy];
        } else if (isNear) {
          ctx.fillStyle = 'rgba(232,237,247,.75)';
        } else {
          ctx.fillStyle = 'rgba(143,156,181,.42)';
        }
        ctx.fill();
      }
    }
    if (focusPoint) {
      ctx.beginPath();
      ctx.arc(focusPoint[0], focusPoint[1], 8.5, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(255,194,71,.55)';
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }

    // Steht der Fokusfahrer im Anstieg, zählt nur eine Zahl: wie weit
    // noch bis oben. Sie gehört nicht in den vorgerenderten Untergrund,
    // weil sie sich mit jedem Bild ändert.
    if (this.showLabels) this._drawClimbCountdown(ctx);

    // Im Übersichtsband zeigt ein Rahmen, wo der Detailausschnitt liegt.
    if (this.detailRange && !this.windowM) {
      const [a, b] = this.detailRange;
      ctx.strokeStyle = 'rgba(255,194,71,.6)';
      ctx.lineWidth = 1;
      ctx.strokeRect(this.x(a), this.padTop, Math.max(this.x(b) - this.x(a), 2), this._size.h - this.padTop - this.padBottom);
    }
  }

  /** „noch 4,2 km bis oben" am Gipfel des Anstiegs, in dem er gerade ist. */
  _drawClimbCountdown(ctx) {
    const pos = this.positions.find((p) => p[0] === this.focus);
    if (!pos) return;
    const dist = pos[1];
    const climb = this.route.climbs.find(
      (cl) => dist >= cl.dist_start_m && dist < cl.dist_end_m
    );
    if (!climb) return;
    const remaining = climb.dist_end_m - dist;
    const text = remaining < 1000
      ? `noch ${Math.round(remaining)} m`
      : `noch ${(remaining / 1000).toFixed(1)} km`;
    const xx = Math.min(this.x(climb.dist_end_m), this._size.w - this.padX);
    ctx.font = '600 10px system-ui, sans-serif';
    ctx.textAlign = 'right';
    const width = ctx.measureText(text).width;
    ctx.fillStyle = 'rgba(13,18,28,.8)';
    ctx.fillRect(xx - width - 6, this.padTop + 16, width + 5, 13);
    ctx.fillStyle = '#ffc247';
    ctx.fillText(text, xx - 3, this.padTop + 26);
  }

  /** Höhe an beliebiger Distanz, linear zwischen zwei Rasterpunkten. */
  _eleAt(p, dist) {
    const step = this.step;
    const last = this._lastIndex();
    const i = Math.min(Math.max(Math.floor(dist / step), 0), last);
    const j = Math.min(i + 1, last);
    if (j === i) return p.ele_m[i];
    const f = (dist - i * step) / step;
    return p.ele_m[i] + f * (p.ele_m[j] - p.ele_m[i]);
  }

  _nearest(dist) {
    let best = null, bestD = Infinity;
    for (const pos of this.positions) {
      const d = Math.abs(pos[1] - dist);
      if (d < bestD) { bestD = d; best = pos; }
    }
    return bestD < (this.viewEnd - this.viewStart) / 60 ? best : null;
  }

  _hover(e) {
    if (!this.onHover || !this.route) return;
    const rect = this.canvas.getBoundingClientRect();
    const dist = this.distAt(e.clientX - rect.left);
    const near = this._nearest(dist);
    this.onHover({ dist, entry: near, clientX: e.clientX, clientY: e.clientY });
  }

  _click(e) {
    if (!this.route) return;
    const rect = this.canvas.getBoundingClientRect();
    const dist = this.distAt(e.clientX - rect.left);
    const near = this._nearest(dist);
    if (this.onSeek) this.onSeek(dist, near ? near[0] : null);
  }
}
