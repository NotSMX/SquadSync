(function () {
    const RAWG_KEY = window.rawgApiKey;
    if (!RAWG_KEY) return;

    async function fetchCover(gameName) {
        const url = `https://api.rawg.io/api/games?key=${RAWG_KEY}&search=${encodeURIComponent(gameName)}&page_size=1`;
        try {
            const res = await fetch(url);
            const data = await res.json();
            return data.results?.[0]?.background_image || null;
        } catch { return null; }
    }

    // Tally cards
    document.querySelectorAll('#game-tally-list [data-game]').forEach(async card => {
        const cover = await fetchCover(card.dataset.game);
        const img = card.querySelector('.game-cover-img');
        if (cover && img) {
            img.src = cover;
        }
    });

    // Chosen game banner
    const chosenEl = document.getElementById('chosen-game-img');
    const chosenNameEl = chosenEl?.previousElementSibling?.querySelector('strong');
    if (chosenEl && chosenNameEl) {
        fetchCover(chosenNameEl.textContent).then(cover => {
            if (!cover) return;
            chosenEl.innerHTML = `<img src="${cover}" alt="${chosenNameEl.textContent}"
                style="width:100%;max-width:320px;border-radius:10px;margin-top:8px;object-fit:cover;aspect-ratio:16/9;">`;
        });
    }
})();