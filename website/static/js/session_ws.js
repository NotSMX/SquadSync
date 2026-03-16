(function () {
    var sessionHash = window.squadScheduleHash;
    if (!sessionHash) return;

    var socket = io();

    socket.on('connect', function () {
        socket.emit('join', { session_hash: sessionHash });
    });

    socket.on('state_update', function (data) {
        handleStateUpdate(data);
    });

    function handleStateUpdate(data) {
        if (typeof window.rebuildCalendar === 'function') {
            window.rebuildCalendar(data.availability);
        }
        updateParticipants(data.participants);
        updateGameTally(data.game_tally);
        updateFinalTime(data.final_time);
        updateChosenGame(data.chosen_game);
        updateConfirmations(data.confirmations);
    }

    function updateParticipants(participants) {
        if (!participants) return;
        var list = document.getElementById('squad-list');
        if (!list) return;
        participants.forEach(function (name) {
            if (!list.querySelector('[data-name="' + CSS.escape(name) + '"]')) {
                var card = document.createElement('div');
                card.className = 'squad-card';
                card.setAttribute('data-name', name);
                var pill = document.createElement('div');
                pill.className = 'squad-pill';
                pill.textContent = name;
                card.appendChild(pill);
                list.appendChild(card);
            }
        });
    }

    function updateGameTally(tally) {
        if (!tally) return;
        var container = document.getElementById('game-tally-list');
        if (!container) return;
        var noVotes = document.getElementById('no-votes-msg');

        if (tally.length === 0) {
            if (noVotes) noVotes.style.display = '';
            container.querySelectorAll('.game-vote-card').forEach(function (el) { el.remove(); });
            return;
        }
        if (noVotes) noVotes.style.display = 'none';

        var existing = {};
        container.querySelectorAll('.game-vote-card').forEach(function (el) {
            existing[el.dataset.game] = el;
        });

        tally.forEach(function (item) {
            var key = item.name;
            if (existing[key]) {
                var countEl = existing[key].querySelector('.game-vote-count');
                if (countEl) countEl.textContent = item.count + (item.count !== 1 ? ' votes' : ' vote');
                delete existing[key];
            } else {
                var card = document.createElement('div');
                card.className = 'game-vote-card';
                card.dataset.game = key;

                var setBtn = '';
                if (window.squadIsHost && window.squadToken) {
                    setBtn = '<form action="/session/' + window.squadScheduleHash + '/set_game?token=' + window.squadToken + '" method="POST" class="mt-1">' +
                        '<input type="hidden" name="game_name" value="' + key + '">' +
                        '<button type="submit" class="btn btn-outline-success btn-med" style="font-size:0.7rem">Set ✓</button>' +
                        '</form>';
                }

                card.innerHTML = '<img class="game-cover-img" src="" alt="' + key + '" style="display:none;">' +
                    '<div class="game-vote-info">' +
                    '<span class="game-vote-name">' + key + '</span>' +
                    '<span class="game-vote-count">' + item.count + (item.count !== 1 ? ' votes' : ' vote') + '</span>' +
                    setBtn +
                    '</div>';
                container.appendChild(card);
                if (typeof window.applyGameCover === 'function') {
                    window.applyGameCover(card);
                }
            }
        });

        Object.values(existing).forEach(function (el) { el.remove(); });
    }

    function updateFinalTime(finalTime) {
        var marker = document.getElementById('final-time-marker');
        if (!marker) return;
        var current = marker.dataset.finalTime || '';
        var incoming = finalTime || '';
        if (incoming !== current) {
            marker.dataset.finalTime = incoming;
            location.reload();
        }
    }

    function updateChosenGame(chosenGame) {
        var marker = document.getElementById('chosen-game-marker');
        if (!marker) return;
        var current = marker.dataset.chosenGameName || '';
        var incoming = chosenGame || '';
        if (incoming !== current) {
            marker.dataset.chosenGameName = incoming;
            location.reload();
        }
    }

    function updateConfirmations(confirmations) {
        if (!confirmations) return;
        Object.keys(confirmations).forEach(function (name) {
            var status = confirmations[name];
            var card = document.querySelector('.squad-card[data-name="' + CSS.escape(name) + '"]');
            if (!card) return;
            var pill = card.querySelector('.status-pill');
            if (!pill) {
                pill = document.createElement('span');
                card.appendChild(pill);
            }
            pill.className = 'status-pill ' + (
                status === 'Yes' ? 's-yes' :
                status === 'Maybe' ? 's-maybe' :
                status === 'No' ? 's-no' : 's-none'
            );
            pill.textContent = status || 'No Response';
        });
    }
})();