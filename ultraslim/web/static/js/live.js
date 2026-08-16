/* Live-Telemetrie: Alpine-Komponente plus zwei Profil-Canvas.
 *
 * Der Client hält bewusst keinen eigenen Rennzustand. Er zeigt, was der
 * Server ihm schickt – dadurch kann er gar nicht versehentlich in die
 * Zukunft sehen. Auf dem Server gibt es die Zukunft auch nicht: Der
 * Generator der Engine ist nur so weit gezogen, wie die Uhr steht.
 *
 * Eine eng begrenzte Ausnahme gibt es: die *Anzeige* der Uhren. Der
 * Server schickt bei hohem Zeitraffer nur ein Bild je Sekunde, und dann
 * sprang die gefahrene Zeit in Blöcken von bis zu tausend Sekunden.
 * Zwischen zwei Bildern zählt der Client die Zeit deshalb selbst weiter
 * – mit dem Zeitraffer, den ihm der Server nennt, und gedeckelt auf den
 * Wert des nächsten Bildes. Er *rechnet* damit nichts: Positionen,
 * Rangfolge und Ereignisse kommen unverändert vom Server. Nur die
 * Ziffern laufen flüssig, statt zu springen.
 */

import { ProfileView } from './profile.js';

const SPEEDS = [1, 5, 10, 30, 60, 300, 1000];

/* Ereignisgruppen des Tickers.
 *
 * Zwei genügen in dieser Fassung: Es gibt weder Defekte noch Stürze
 * noch Hungeräste. Ein Typ, der hier nicht vorkommt, läuft immer mit –
 * ein neuer Ereignistyp soll nicht dadurch unsichtbar werden, dass
 * jemand vergessen hat, ihn einzutragen.
 */
const TICKER_GROUPS = [
  { key: 'zeit', label: 'Zeiten', types: ['BEST_TIME', 'SPLIT_PASSED'] },
  { key: 'start', label: 'Starts', types: ['START'] },
  { key: 'ziel', label: 'Ziel', types: ['FINISH'] },
];

const GROUP_OF_TYPE = new Map();
for (const group of TICKER_GROUPS) for (const t of group.types) GROUP_OF_TYPE.set(t, group.key);

/* Wählbare Spalten des Boards.
 *
 * Die feste Hälfte der Tabelle — Rang, Nummer, Fahrer, Team, Zeit,
 * Rückstand — beantwortet „wer liegt wo". Diese hier beantworten die
 * jeweils nächste Frage, und welche das ist, hängt vom Zuschauer ab:
 * am Berg das Tempo, vor einer Zeitmessung die Meter bis dorthin.
 */
const BOARD_COLUMNS = [
  { key: 'km', label: 'km', hint: 'gefahrene Kilometer' },
  { key: 'biscp', label: 'bis CP', hint: 'Meter bis zur nächsten Zeitmessung' },
  { key: 'trend', label: '±', hint: 'Plätze gewonnen oder verloren seit der Zeitmessung davor' },
  { key: 'tempo', label: 'km/h', hint: 'Momentangeschwindigkeit' },
  { key: 'leistung', label: 'W', hint: 'Tretleistung' },
];

//: Was ohne eigene Wahl steht.
const DEFAULT_COLUMNS = ['km', 'biscp'];

function hms(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const total = Math.round(Math.abs(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function gap(seconds) {
  if (seconds === null || seconds === undefined) return '';
  const sign = seconds >= 0 ? '+' : '−';
  const total = Math.round(Math.abs(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${sign}${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${sign}${m}:${String(s).padStart(2, '0')}`;
}

function raceLive(raceId) {
  return {
    raceId,
    token: null,
    route: null,
    startlist: [],
    frame: null,
    ticker: [],
    speeds: SPEEDS,
    tickerGroups: TICKER_GROUPS,
    //: Abgewählte Gruppen. Als Liste statt als Set, damit Alpine die
    //: Änderung sieht — Reaktivität geht über Set-Methoden verloren.
    tickerOff: [],
    focusOnly: false,
    allColumns: BOARD_COLUMNS,
    columns: [...DEFAULT_COLUMNS],
    showColumnPicker: false,
    filter: '',
    groupBy: 'keine',
    tooltip: null,
    error: null,
    overview: null,
    detail: null,
    source: null,
    //: Stand der letzten Serverzeit und wann sie eintraf – daraus
    //: interpoliert der Client zwischen zwei Bildern.
    clockBase: 0,
    clockStamp: 0,
    tickNow: 0,
    //: Grober Takt für Rangfolge und Höhenprofil, siehe ``sortDelta``.
    sortNow: 0,
    raf: null,
    _collapsed: [],
    _sortStamp: 0,
    _drawStamp: 0,
    _neighbours: [],

    get focus() { return this.frame ? this.frame.focus : null; },

    //: Rennuhr, zwischen zwei Bildern selbst weitergezählt.
    get liveWall() {
      if (!this.frame) return 0;
      if (!this.frame.playing) return this.frame.t_wall;
      const speed = this.frame.speed;
      // Bildabstand des Servers, hier gespiegelt. Weiter als bis kurz
      // hinter das nächste erwartete Bild darf die Anzeige nicht
      // vorlaufen — sonst korrigiert sie sich sichtbar rückwärts.
      const interval = speed <= 10 ? 0.25 : speed <= 60 ? 0.5 : 1.0;
      const ahead = Math.max((this.tickNow - this.clockStamp) / 1000, 0) * speed;
      return Math.min(
        this.clockBase + Math.min(ahead, interval * 1.2 * speed),
        this.frame.horizon_s
      );
    },
    //: Um so viel ist die Anzeige dem letzten Bild voraus.
    get liveDelta() {
      return this.frame ? this.liveWall - this.frame.t_wall : 0;
    },

    /* Derselbe Vorlauf, aber nur viermal je Sekunde neu.
     *
     * Ziffern dürfen mit dem Bildschirmtakt laufen — das ist eine
     * Textänderung. Die Tabelle *umzusortieren* heißt, vierzig
     * Tabellenzeilen im DOM zu verschieben, und das sechzigmal je
     * Sekunde wäre Arbeit für nichts: Schneller als das Auge folgen kann
     * muss keine Rangliste sein.
     */
    get sortDelta() {
      if (!this.frame || !this.frame.playing) return 0;
      const speed = this.frame.speed;
      const interval = speed <= 10 ? 0.25 : speed <= 60 ? 0.5 : 1.0;
      const ahead = Math.max((this.sortNow - this.clockStamp) / 1000, 0) * speed;
      return Math.min(ahead, interval * 1.2 * speed);
    },
    get liveOwnTime() {
      if (!this.focus) return null;
      // Nur mitzählen, solange er wirklich unterwegs ist. Wer noch nicht
      // gestartet ist, steht bei null — seine Uhr läuft nicht, und
      // mitzuzählen hieße, ihm Zeit anzudichten, die es nicht gibt. Wer
      // im Ziel ist, hat eine feste Zeit.
      return this.focus.own_time_s + (this.focus.state === 0 ? this.liveDelta : 0);
    },
    //: Kilometer des Fokusfahrers, mitlaufend wie im Board.
    get focusDist() {
      if (!this.focus) return 0;
      return this.focus.dist_m + (this.focus.v_kmh / 3.6) * this.liveDelta;
    },
    get focusRemaining() {
      if (!this.focus) return 0;
      return Math.max(this.focus.dist_m + this.focus.remaining_m - this.focusDist, 0);
    },

    get latest() { return this.visibleTicker.slice(0, 10); },
    get visibleTicker() {
      return this.ticker.filter((e) => {
        if (this.focusOnly && !e.focus) return false;
        const group = GROUP_OF_TYPE.get(e.type);
        return !group || !this.tickerOff.includes(group);
      });
    },
    //: Wie viele Meldungen die Filter gerade wegnehmen — ohne das wirkt
    //: ein leerer Ticker wie ein hängengebliebener Server.
    get tickerHidden() { return this.ticker.length - this.visibleTicker.length; },
    groupOn(key) { return !this.tickerOff.includes(key); },
    toggleGroup(key) {
      this.tickerOff = this.groupOn(key)
        ? [...this.tickerOff, key]
        : this.tickerOff.filter((k) => k !== key);
      this.rememberFilter();
    },
    showAllGroups() { this.tickerOff = []; this.focusOnly = false; this.rememberFilter(); },
    toggleFocusOnly() { this.focusOnly = !this.focusOnly; this.rememberFilter(); },

    get board() { return this.frame ? this.frame.board : null; },

    /* Die Tabellenzeilen — in der Splitwertung zwischen zwei Bildern
     * selbst nachsortiert.
     *
     * Der Server ordnet nach dem Stand seines letzten Bildes. Wessen Uhr
     * noch läuft, dessen Zeit wächst aber weiter, und bei 1000× sind
     * das zwischen zwei Bildern über sechzehn Minuten — die Rangfolge
     * stimmte dann eine ganze Sekunde lang sichtbar nicht. Hier wandert
     * ein Fahrer nach unten, sobald seine laufende Uhr eine gefahrene
     * Zeit überholt, und nicht erst beim nächsten Bild.
     *
     * Sortiert wird nur innerhalb des Ausschnitts, den der Server
     * geschickt hat, und die Rangnummern dieses Ausschnitts werden neu
     * verteilt. Wer über den Rand hinauswandert, wird beim nächsten Bild
     * eingefangen.
     */
    get rows() {
      const raw = this.board ? this.board.rows : [];
      if (!this.isSplitMode || !this.frame || this.frame.sort !== 'zeit' || this.frame.sort_desc) {
        return raw;
      }
      if (!raw.some((r) => r.running)) return raw;

      const delta = this.sortDelta;
      const zeit = (r) =>
        r.t_s === null ? Infinity : r.t_s + (r.running ? delta : 0);
      const raenge = raw.map((r) => r.rank).sort((a, b) => a - b);
      return raw
        .slice()
        .sort((a, b) => zeit(a) - zeit(b))
        .map((r, i) => (r.rank === raenge[i] ? r : { ...r, rank: raenge[i] }));
    },
    get pinnedRows() { return this.board && this.board.pinned ? this.board.pinned : []; },
    //: Der Abstand zwischen den beiden angehefteten Fahrern — das
    //: einzige, was ein Duell wirklich ausmacht.
    get pinnedGap() {
      const [a, b] = this.pinnedRows;
      if (!a || !b || a.t_s === null || b.t_s === null) return null;
      return this.rowTime(b) - this.rowTime(a);
    },
    get visibleColumns() {
      return BOARD_COLUMNS.filter((c) => this.columns.includes(c.key));
    },
    get filteredStart() {
      const q = this.filter.trim().toLowerCase();
      if (!q) return this.startlist;
      return this.startlist.filter(
        (r) => r.name.toLowerCase().includes(q) || r.team.toLowerCase().includes(q) || String(r.bib) === q
      );
    },
    //: Die Startliste gefaltet.
    //:
    //: Dreihundert flache Zeilen mit Textsuche sind kein Verzeichnis,
    //: sondern eine Schriftrolle: Man findet darin nur, wovon man den
    //: Namen schon weiß. Nach Team oder Nation gruppiert beantwortet
    //: sie auch „wer fährt eigentlich für Ortlieb–Cube".
    get startGroups() {
      const rows = this.filteredStart;
      if (this.groupBy === 'keine') return [{ key: '', label: '', rows }];
      const buckets = new Map();
      for (const r of rows) {
        const key = this.groupBy === 'team' ? r.team : r.nation;
        if (!buckets.has(key)) buckets.set(key, []);
        buckets.get(key).push(r);
      }
      return [...buckets.entries()]
        .sort((a, b) => a[0].localeCompare(b[0], 'de'))
        .map(([key, group]) => ({ key, label: key || '—', rows: group }));
    },
    groupOpen(key) { return !this._collapsed.includes(key); },
    toggleGroupFold(key) {
      this._collapsed = this._collapsed.includes(key)
        ? this._collapsed.filter((k) => k !== key)
        : [...this._collapsed, key];
    },
    setGroupBy(mode) { this.groupBy = mode; this._collapsed = []; this.rememberFilter(); },

    hms, gap,

    //: Welche der beiden Zeiten eine Tickermeldung zeigt.
    //:
    //: Bei einer Zwischenzeit ist die Eigenzeit die Nachricht — „nach
    //: 2:31:07 durch KP 1" ist das Ergebnis. Bei einem Start ist sie
    //: null und sagt nichts; dort zählt die Rennuhr, also wann er
    //: losgerollt ist.
    tickerTime(e) {
      return hms(e.type === 'START' ? e.t_wall : e.t_s);
    },

    //: Laufende Uhren zählen zwischen zwei Bildern mit, gemessene
    //: Zeiten stehen fest.
    rowTime(row) {
      return row.running ? row.t_s + this.liveDelta : row.t_s;
    },

    /* Die gefahrenen Kilometer, zwischen zwei Bildern weitergeschrieben.
     *
     * Bei 1000× schickt der Server ein Bild je Sekunde, und dazwischen
     * legt ein Fahrer über acht Kilometer zurück. Ohne diese Zeile
     * sprang die Spalte im Sekundentakt um acht Kilometer und stand
     * dazwischen still. Gerechnet wird nichts: Der Vorlauf ist auf das
     * nächste erwartete Bild gedeckelt, genau wie bei der Uhr.
     */
    rowDist(row) {
      return row.dist_km + (row.v_kmh * this.liveDelta) / 3600;
    },

    //: Meter bis zur nächsten Zeitmessung — mitlaufend aus demselben
    //: Grund wie die Kilometer.
    //:
    //: Unter 10 km in Metern, darüber in Kilometern — 47 000 m liest
    //: niemand, 800 m dagegen genau dann, wenn es darauf ankommt. Wer
    //: im Ziel ist oder noch wartet, bekommt einen Strich: Eine 0 wäre
    //: in beiden Fällen falsch.
    toNext(row) {
      const roh = row && row.to_next_m;
      if (roh === null || roh === undefined) return '–';
      const m = Math.round(Math.max(roh - (row.v_kmh / 3.6) * this.liveDelta, 0));
      return m < 10000 ? `${m} m` : `${(m / 1000).toFixed(1)} km`;
    },

    cell(key, row) {
      switch (key) {
        case 'km': return this.rowDist(row).toFixed(1);
        case 'biscp': return this.toNext(row);
        case 'trend':
          return row.trend > 0 ? `▲${row.trend}` : row.trend < 0 ? `▼${-row.trend}` : '–';
        case 'tempo': return row.v_kmh.toFixed(1);
        case 'leistung': return row.power_w || '–';
        default: return '';
      }
    },

    cellClass(key, row) {
      if (key === 'trend') return row.trend > 0 ? 'pos' : row.trend < 0 ? 'neg' : 'faint';
      return '';
    },

    toggleColumn(key) {
      this.columns = this.columns.includes(key)
        ? this.columns.filter((k) => k !== key)
        : [...this.columns, key];
      this.rememberFilter();
    },
    resetColumns() { this.columns = [...DEFAULT_COLUMNS]; this.rememberFilter(); },

    sortBy(key) { this.control('sort', key); },
    sortMark(key) {
      if (!this.frame || this.frame.sort !== key) return '';
      return this.frame.sort_desc ? ' ▾' : ' ▴';
    },
    isPinned(entryId) {
      return !!(this.frame && this.frame.pinned && this.frame.pinned.includes(entryId));
    },
    togglePin(entryId) { this.control('pin', entryId); },

    //: Nur in der Splitwertung wächst der Rückstand mit der Uhr: Dort
    //: ist die Bestzeit gemessen und steht zwischen zwei Bildern fest,
    //: also wächst der Rückstand eines noch fahrenden Verfolgers um
    //: genau dieselbe Sekundenzahl wie seine Uhr. Ohne das sprang die
    //: Spalte im Takt der Bilder: bei 60× einmal je halbe Sekunde um
    //: eine halbe Minute.
    //:
    //: In der virtuellen Rangliste fährt der Führende weiter. Der
    //: Abstand ist dort eine Schätzung aus dem Streckenvorsprung und
    //: kommt mit jedem Bild neu — mitzuzählen hieße, ihn doppelt zu
    //: berechnen.
    rowGap(row) {
      if (row.gap_s === null || row.gap_s === undefined) return null;
      return this.isSplitMode && row.running ? row.gap_s + this.liveDelta : row.gap_s;
    },
    get isSplitMode() { return !!(this.frame && this.frame.mode === 'split'); },

    async init() {
      this.restoreFilter();
      try {
        const [routeRes, listRes, sessionRes] = await Promise.all([
          fetch(`/api/race/${this.raceId}/route`),
          fetch(`/api/race/${this.raceId}/startlist`),
          fetch(`/api/race/${this.raceId}/session`, { method: 'POST' }),
        ]);
        this.route = await routeRes.json();
        this.startlist = (await listRes.json()).entries;
        this.token = (await sessionRes.json()).token;
        await this.restore();
      } catch (e) {
        this.error = 'Renndaten konnten nicht geladen werden.';
        return;
      }

      this.overview = new ProfileView(this.$refs.overview, { height: 90, showLabels: false });
      this.detail = new ProfileView(this.$refs.detail, {
        height: 190, windowM: 40000, eleAxis: true,
      });
      for (const view of [this.overview, this.detail]) {
        view.setRoute(this.route);
        view.onSeek = (dist) => this.control('distance', dist);
        view.onHover = (info) => this.showTooltip(info);
      }
      this.connect();
      await this.refresh();
      this.tick();
    },

    /* Drei Takte in einer Schleife, weil sie unterschiedlich teuer sind.
     *
     * Die Ziffern laufen mit dem Bildschirm — das ist eine
     * Textänderung. Die Rangfolge wird viermal je Sekunde neu geordnet,
     * weil sie vierzig Tabellenzeilen im DOM verschiebt. Das Profil
     * wird fünfzehnmal je Sekunde neu gezeichnet, weil es einen Canvas
     * neu aufbaut.
     */
    tick() {
      const now = performance.now();
      this.tickNow = now;
      if (now - this._sortStamp > 250) {
        this._sortStamp = now;
        this.sortNow = now;
      }
      if (now - this._drawStamp > 66) {
        this._drawStamp = now;
        this.drawProfile();
      }
      this.raf = requestAnimationFrame(() => this.tick());
    },

    /* Das Höhenprofil, mit weitergeschriebenen Positionen.
     *
     * Ohne das hüpfen die Punkte bei hohem Zeitraffer im Sekundentakt
     * über das Profil, statt zu fahren. Der Untergrund wird dabei nicht
     * neu gerendert — er hängt am Bildausschnitt, nicht an den Fahrern.
     */
    drawProfile() {
      if (!this.frame || !this.overview || !this.detail) return;
      const d = this.liveDelta;
      const pos =
        d > 0.05
          ? this.frame.positions.map(([id, dist, kmh, st]) => [
              id, dist + (kmh / 3.6) * d, kmh, st,
            ])
          : this.frame.positions;
      for (const view of [this.overview, this.detail]) {
        view.setFrame(pos, this.frame.focus.entry_id, this._neighbours);
      }
      this.detail._updateWindow();
      this.overview.detailRange = [this.detail.viewStart, this.detail.viewEnd];
      this.overview.draw();
      this.detail.draw();
    },

    //: Wohin der Betrachter zuletzt geschaut hat. Ohne das beginnt die
    //: Wiedergabe nach jedem Seitenwechsel wieder von vorn.
    get memoryKey() { return `ultraslim:playback:${this.raceId}`; },
    //: Die Anzeigefilter gehören dem Betrachter, nicht dem Rennen —
    //: deshalb rennübergreifend und in ``localStorage``.
    filterKey: 'ultraslim:ticker',

    restoreFilter() {
      try {
        const saved = JSON.parse(localStorage.getItem(this.filterKey) || 'null');
        if (!saved) return;
        if (Array.isArray(saved.off)) this.tickerOff = saved.off;
        if (Array.isArray(saved.columns)) {
          // Gegen die bekannten Spalten filtern: Ein gespeicherter
          // Schlüssel, den es nicht mehr gibt, würde sonst eine leere
          // Spalte in die Tabelle setzen.
          this.columns = saved.columns.filter((k) => BOARD_COLUMNS.some((c) => c.key === k));
        }
        if (typeof saved.groupBy === 'string') this.groupBy = saved.groupBy;
        this.focusOnly = !!saved.focusOnly;
      } catch (e) { /* dann eben ungefiltert */ }
    },

    rememberFilter() {
      try {
        localStorage.setItem(this.filterKey, JSON.stringify({
          off: this.tickerOff,
          focusOnly: this.focusOnly,
          columns: this.columns,
          groupBy: this.groupBy,
        }));
      } catch (e) { /* privater Modus */ }
    },

    async restore() {
      let saved = null;
      try { saved = JSON.parse(sessionStorage.getItem(this.memoryKey) || 'null'); } catch (e) { saved = null; }
      if (!saved || typeof saved.t !== 'number') return;
      // Reihenfolge zählt: erst Fahrer und Zeitmessung, dann die Uhr —
      // sonst springt das Board beim Fokuswechsel zurück.
      const send = (action, value) => this.send(action, value);
      if (Number.isInteger(saved.focus)) await send('focus', saved.focus);
      if (saved.autoFocus) await send('auto_focus', true);
      if (saved.mode === 'split') await send('mode', 'split');
      if (Number.isInteger(saved.split)) await send('split', saved.split);
      if (saved.speed) await send('speed', saved.speed);
      await send('seek', saved.t);
      if (saved.playing) await send('play', true);
    },

    remember() {
      if (!this.frame) return;
      try {
        sessionStorage.setItem(this.memoryKey, JSON.stringify({
          t: this.frame.t_wall,
          speed: this.frame.speed,
          focus: this.frame.focus.entry_id,
          mode: this.frame.mode,
          split: this.frame.board && this.frame.board.split ? this.frame.board.split.idx : null,
          playing: this.frame.playing,
          autoFocus: this.frame.auto_focus,
        }));
      } catch (e) { /* privater Modus: dann eben ohne Gedächtnis */ }
    },

    connect() {
      if (this.source) this.source.close();
      this.source = new EventSource(`/api/playback/${this.token}/stream`);
      this.source.addEventListener('frame', (e) => this.apply(JSON.parse(e.data)));
      this.source.onerror = () => { this.error = 'Verbindung zum Server unterbrochen.'; };
    },

    async refresh() {
      const res = await fetch(`/api/playback/${this.token}/frame`);
      this.apply(await res.json());
    },

    apply(frame) {
      this.error = null;
      this.frame = frame;
      // Uhr am Serverwert neu verankern.
      this.clockBase = frame.t_wall;
      this.clockStamp = performance.now();
      this.tickNow = this.clockStamp;
      if (frame.ticker.length) {
        // Stabiler Schlüssel statt laufender Nummer: Der erste Abruf und
        // das erste Bild des Ereignisstroms überlappen sich, und ohne
        // Schlüssel stünde jede Meldung doppelt im Ticker.
        const seen = new Set(this.ticker.map((e) => e.key));
        const fresh = frame.ticker
          .map((e) => ({ ...e, key: `${e.entry_id}|${e.type}|${e.t_s}` }))
          .filter((e) => !seen.has(e.key));
        if (fresh.length) this.ticker = [...fresh.reverse(), ...this.ticker].slice(0, 120);
      }
      this._neighbours = frame.board.rows.map((r) => r.entry_id);
      this.drawProfile();
      this.remember();
    },

    send(action, value) {
      return fetch(`/api/playback/${this.token}/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, value }),
      });
    },

    async control(action, value) {
      const res = await this.send(action, value);
      if (res.ok) await this.refresh();
    },

    //: Klick auf eine Tickermeldung: hinschauen, wo sie passiert ist.
    //:
    //: Erst der Fahrer, dann die Uhr — in der anderen Reihenfolge zöge
    //: das Board beim Fokuswechsel wieder auf die zuletzt passierte
    //: Zeitmessung des neuen Fahrers. Und angehalten wird dabei: Bei
    //: 1000× wäre der Moment im nächsten Bild schon eine Viertelstunde
    //: her.
    //: Gesprungen wird auf die Rennuhr des Ereignisses, nicht auf die
    //: Eigenzeit: Beim Einzelstart liegen zwischen beiden bis zu fünfzig
    //: Stunden.
    async jumpTo(event) {
      await this.send('focus', event.entry_id);
      await this.send('pause');
      await this.control('seek', event.t_wall);
    },

    setFocus(entryId) { this.control('focus', entryId); },
    setSplit(idx) { this.control('split', Number(idx)); },
    setSpeed(v) { this.control('speed', Number(v)); },
    toggleMode() { this.control('mode', this.frame.mode === 'virtual' ? 'split' : 'virtual'); },
    seekFraction(f) { this.control('seek', f * this.frame.horizon_s); },

    showTooltip(info) {
      if (!info || !info.entry) { this.tooltip = null; return; }
      const [id, dist, kmh] = info.entry;
      const rider = this.startlist.find((r) => r.entry_id === id);
      if (!rider) { this.tooltip = null; return; }
      const row = this.rows.find((r) => r.entry_id === id);
      this.tooltip = {
        x: info.clientX + 12,
        y: info.clientY + 12,
        text: `#${rider.bib} ${rider.name}\n${rider.team}\n${rider.ftp_w} W · ${rider.weight_kg} kg`
          + `\nkm ${(dist / 1000).toFixed(1)} · ${kmh} km/h`
          + (row && row.rank ? `\nRang ${row.rank}` : ''),
      };
    },

    stateLabel(state) {
      return state === 2 ? 'im Ziel' : state === -1 ? 'wartet auf Start' : 'fährt';
    },

    destroy() {
      if (this.source) this.source.close();
      if (this.raf) cancelAnimationFrame(this.raf);
    },
  };
}

document.addEventListener('alpine:init', () => {
  window.Alpine.data('raceLive', raceLive);
});
