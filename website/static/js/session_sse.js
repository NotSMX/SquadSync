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
        updateParticipants(data.participants);
        updateGameTally(data.game_tally, data.chosen_game);
        updateChosenGame(data.chosen_game);
        updateFinalTime(data.final_time);
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
        if (!tally || chosenGame) return;
        const list = document.getElementById("game-tally-list");
        if (!list) return;

        // Remove cards for games no longer in tally
        list.querySelectorAll("[data-game]").forEach(card => {
            const stillExists = tally.some(({ name }) => name === card.dataset.game);
            if (!stillExists) card.remove();
        });

        // Hide "no votes" message once votes exist
        if (tally.length > 0) {
            const noVotes = document.getElementById("no-votes-msg");
            if (noVotes) noVotes.style.display = "none";
        }

        tally.forEach(({ name, count }) => {
            let card = list.querySelector(`[data-game="${CSS.escape(name)}"]`);
            if (!card) {
                const isHost = window.squadIsHost;
                const token = window.squadToken;
                const hash = window.squadScheduleHash;
                const setBtn = isHost ? `
                    <form action="/session/${hash}/set_game?token=${token}" method="POST" class="mt-1">
                        <input type="hidden" name="game_name" value="${name}">
                        <button type="submit" class="btn btn-outline-success btn-med" style="font-size:0.7rem">Set ✓</button>
                    </form>` : '';

                card = document.createElement("div");
                card.className = "game-vote-card";
                card.setAttribute("data-game", name);
                card.innerHTML = `
                    <img class="game-cover-img" src="" alt="${name}" style="display:none;">
                    <div class="game-vote-info">
                        <span class="game-vote-name">${name}</span>
                        <span class="game-vote-count"></span>
                        ${setBtn}
                    </div>`;
                list.appendChild(card);

                if (typeof window.applyGameCover === "function") {
                    window.applyGameCover(card);
                }
            }
            const countEl = card.querySelector(".game-vote-count");
            if (countEl) countEl.textContent = `${count} vote${count !== 1 ? "s" : ""}`;
        });
    }

    function updateParticipants(participants) {
        if (!participants) return;
        const squadList = document.getElementById("squad-list");
        if (!squadList) return;
        const colors = ["#3b82f6","#ef4444","#22c55e","#eab308","#a855f7","#f97316"];

        participants.forEach((name) => {
            if (!squadList.querySelector(`[data-name="${CSS.escape(name)}"]`)) {
                const color = colors[squadList.children.length % colors.length];
                const card = document.createElement("div");
                card.className = "squad-card";
                card.setAttribute("data-name", name);
                card.innerHTML = `<div class="squad-pill" style="background:${color};">${name}</div>`;
                squadList.appendChild(card);
            }
        });
    }


  // ── chosen game banner ────────────────────────────────────────────────────

    function updateChosenGame(chosenGame) {
        const marker = document.getElementById("chosen-game-marker");
        if (!marker) return;
        const currentShown = marker.dataset.chosenGameName || "";
        if (chosenGame && chosenGame !== currentShown) window.location.reload();
        if (!chosenGame && currentShown) window.location.reload();
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

    function updateFinalTime(finalTime) {
        const marker = document.getElementById("final-time-marker");
        if (!marker) return;
        const currentShown = marker.dataset.finalTime || "";

        if (finalTime && finalTime !== currentShown) {
            window.location.reload();
        }
        if (!finalTime && currentShown) {
            window.location.reload();
        }
    }
})();