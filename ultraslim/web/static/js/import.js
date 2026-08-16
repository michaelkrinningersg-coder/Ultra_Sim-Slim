/* Die Vorschau des GPX-Imports.
 *
 * Der Regler stellt die Fensterbreite der Glättung; gerechnet wird sie
 * auf dem Server, weil dort schon der Code steht, der später auch das
 * gespeicherte Profil baut. Zwei Glättungen an zwei Orten wären zwei
 * Gelegenheiten, sich zu unterscheiden — und ausgerechnet die Vorschau
 * wäre dann die Zahl, die *nicht* stimmt.
 */

import { ProfileView } from './profile.js';

//: So lange nach der letzten Reglerbewegung wird gewartet, bevor
//: gerechnet wird. Ohne diese Pause schickt ein Zug über die Skala
//: dreißig Anfragen, von denen neunundzwanzig überholt sind.
const RUHE_MS = 180;

function gpxImport(token) {
  return {
    token,
    smooth: null,
    route: null,
    lade: false,
    view: null,
    _timer: null,
    //: Läuft mit jeder Anfrage hoch. Eine Antwort, die nicht zur
    //: neuesten gehört, wird verworfen — sonst überschreibt eine
    //: langsame alte Anfrage das frische Ergebnis.
    _lauf: 0,

    async init() {
      this.smooth = Number(this.$el.querySelector('input[type=range]').value);
      this.view = new ProfileView(this.$refs.profil, { height: 240, eleAxis: true });
      window.addEventListener('resize', () => this.view && this.view.draw());
      await this.hole();
    },

    setze(wert) {
      this.smooth = wert;
      this.hole();
    },

    planeAbruf() {
      clearTimeout(this._timer);
      this._timer = setTimeout(() => this.hole(), RUHE_MS);
    },

    async hole() {
      const lauf = ++this._lauf;
      this.lade = true;
      try {
        const res = await fetch(
          `/api/import/${this.token}/vorschau?smooth_m=${encodeURIComponent(this.smooth)}`
        );
        if (!res.ok) return;
        const route = await res.json();
        if (lauf !== this._lauf) return;   // überholt
        this.route = route;
        this.view.setRoute(route);
        this.view.setFrame([], -1, []);
        this.view.invalidate();
        this.view.draw();
      } catch (e) {
        /* Die Zahlen bleiben stehen, statt zu verschwinden. */
      } finally {
        if (lauf === this._lauf) this.lade = false;
      }
    },

    get steilste() {
      if (!this.route) return '—';
      let max = 0;
      for (const g of this.route.profile.grade) if (g > max) max = g;
      return (max * 100).toFixed(1);
    },
  };
}

document.addEventListener('alpine:init', () => {
  window.Alpine.data('gpxImport', gpxImport);
});
