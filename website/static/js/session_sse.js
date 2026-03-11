/**
 * session_sse.js
 *
 *  • Opens an SSE connection to /session/<hash>/stream
 *  • On each 'state' event, updates:
 *      – The squad schedule calendar  (via squadScheduleData + rebuildCalendar)
 *      – Game vote tally cards
 *      – Chosen game banner
 *      – Squad confirmation pills
 *  • Reconnects automatically via EventSource built-in retry
 */

(function () {
  "use strict";

  const hash = window.squadScheduleHash;
  if (!hash) return;

  let es = null;

  function connect() {
    if (es) return;
    es = new EventSource(`/session/${hash}/stream`);

    es.addEventListener("state", (e) => {
      try {
        const data = JSON.parse(e.data);
        applyState(data);
      } catch (_) {}
    });

    es.addEventListener("gone", () => {
      es.close();
      es = null;
    });

    // Server closes after MAX_DURATION; reconnect seamlessly
    es.addEventListener("reconnect", () => {
      es.close();
      es = null;
      setTimeout(connect, 500);
    });

    es.onerror = () => {
      es.close();
      es = null;
      setTimeout(connect, 3000);
    };
  }

  connect();

  // ── state application ─────────────────────────────────────────────────────

  function applyState(data) {
    updateCalendar(data.availability);
    updateGameTally(data.game_tally, data.chosen_game);
    updateChosenGame(data.chosen_game);
    updateConfirmations(data.confirmations);
  }

  // ── calendar ──────────────────────────────────────────────────────────────

  function updateCalendar(availability) {
    if (!availability) return;

    // squadScheduleData is the global used by calendar.js
    // Update it and trigger a re-render if calendar.js exposes rebuildCalendar()
    window.squadScheduleData = availability;

    if (typeof window.rebuildCalendar === "function") {
      window.rebuildCalendar(availability);
    } else {
      // Fallback: dispatch a custom event that calendar.js can listen for
      document.dispatchEvent(
        new CustomEvent("synq:availability", { detail: availability })
      );
    }
  }

  // ── game tally ────────────────────────────────────────────────────────────

  function updateGameTally(tally, chosenGame) {
    if (!tally) return;
    const list = document.getElementById("game-tally-list");
    if (!list) return;

    // Update vote counts on existing cards; don't rebuild DOM
    // (preserves game cover images that game_covers.js may have loaded)
    tally.forEach(({ name, count }) => {
      const card = list.querySelector(`[data-game="${CSS.escape(name)}"]`);
      if (!card) return;
      const countEl = card.querySelector(".game-vote-count");
      if (countEl) {
        countEl.textContent = `${count} vote${count !== 1 ? "s" : ""}`;
      }
    });
  }

  // ── chosen game banner ────────────────────────────────────────────────────

  function updateChosenGame(chosenGame) {
    // Only reload the page if chosen_game changed and we're not already
    // showing it — a full reload is fine here because it's a rare, meaningful
    // state transition (host picks the game).
    const banner = document.querySelector("[data-chosen-game-name]");
    const currentShown = banner
      ? banner.dataset.chosenGameName
      : null;

    if (chosenGame && chosenGame !== currentShown) {
      // Reload so Jinja renders the locked banner correctly
      window.location.reload();
    }
    if (!chosenGame && currentShown) {
      window.location.reload(); // host cleared the game
    }
  }

  // ── confirmation pills ────────────────────────────────────────────────────

  const STATUS_CLASSES = {
    Yes: "s-yes",
    Maybe: "s-maybe",
    No: "s-no",
  };

  function updateConfirmations(confirmations) {
    if (!confirmations) return;

    document.querySelectorAll(".squad-card").forEach((card) => {
      const name = card.dataset.name;
      if (!name) return;
      const pill = card.querySelector(".status-pill");
      if (!pill) return;

      const status = confirmations[name] || null;
      pill.textContent = status || "No Response";

      // Reset classes
      pill.classList.remove("s-yes", "s-maybe", "s-no", "s-none");
      pill.classList.add(STATUS_CLASSES[status] || "s-none");
    });
  }
})();