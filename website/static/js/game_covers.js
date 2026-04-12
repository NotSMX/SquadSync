(function () {
    const RAWG_KEY = window.rawgApiKey;
    if (!RAWG_KEY) return;

    async function fetchCover(gameName) {
        const url = `https://api.rawg.io/api/games?key=${RAWG_KEY}&search=${encodeURIComponent(gameName)}&page_size=1`;
        try {
            const res = await fetch(url);
            const data = await res.json();
            return data.results?.[0]?.background_image || null;
        } catch {
            return null;
        }
    }

    async function applycover(card) {
        const img = card.querySelector('.game-cover-img');
        if (!img || img.dataset.loaded) return;

        const cover = await fetchCover(card.dataset.game);
        if (cover) {
            img.src = cover;
            img.style.display = 'block';
            img.dataset.loaded = 'true';
        }
    }

    function initGameCovers() {
        document.querySelectorAll('#game-tally-list [data-game]')
            .forEach(applycover);
    }

    function initChosenGame() {
        const chosenImg = document.getElementById('chosen-game-img');
        const chosenName = document.querySelector('.chosen-game-name');

        if (!chosenImg || !chosenName) return;

        fetchCover(chosenName.textContent).then(cover => {
            if (cover) {
                chosenImg.src = cover;
            }
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        initGameCovers();
        initChosenGame();
    });

    // expose for websocket updates
    window.applyGameCover = applycover;

})();