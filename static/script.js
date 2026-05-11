/* ── Poker AI Frontend — Game Client ─────────────────────── */

let gameState = null;
let raiseMode = false;

// ── API Calls ────────────────────────────────────────────────
async function apiCall(endpoint, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    try {
        const res = await fetch(endpoint, opts);
        const data = await res.json();
        if (data.error && !data.players) {
            showToast(data.error);
            return null;
        }
        return data;
    } catch (e) {
        showToast('Connection error — is the server running?');
        return null;
    }
}

async function startNewGame() {
    hideModal();
    const data = await apiCall('/api/new-game', 'POST', {});
    if (data) { gameState = data; renderAll(); }
}

async function doAction(type, amount = 0) {
    hideRaiseControls();
    const data = await apiCall('/api/action', 'POST', { action: type, amount });
    if (data) { gameState = data; renderAll(); }
}

async function nextHand() {
    const data = await apiCall('/api/next-hand', 'POST', {});
    if (data) { gameState = data; renderAll(); }
}

function doCheckCall() {
    if (!gameState) return;
    const actions = gameState.available_actions;
    const checkAct = actions.find(a => a.type === 'check');
    const callAct = actions.find(a => a.type === 'call');
    if (checkAct) doAction('check', 0);
    else if (callAct) doAction('call', callAct.amount);
}

function doRaise() {
    raiseMode = !raiseMode;
    const ctrl = document.getElementById('raise-controls');
    if (raiseMode) {
        ctrl.classList.remove('hidden');
        setupRaiseSlider();
    } else {
        ctrl.classList.add('hidden');
    }
}

function setupRaiseSlider() {
    if (!gameState) return;
    const actions = gameState.available_actions;
    const raiseAct = actions.find(a => a.type === 'raise');
    const betAct = actions.find(a => a.type === 'bet');
    const act = raiseAct || betAct;
    if (!act) return;
    const slider = document.getElementById('raise-slider');
    slider.min = act.min;
    slider.max = act.max;
    slider.value = act.min;
    updateRaiseDisplay();
}

function updateRaiseDisplay() {
    const val = document.getElementById('raise-slider').value;
    document.getElementById('raise-amount-display').textContent = '$' + val;
}

function setRaisePreset(mult) {
    if (!gameState) return;
    const pot = gameState.pot;
    const actions = gameState.available_actions;
    const act = actions.find(a => a.type === 'raise') || actions.find(a => a.type === 'bet');
    if (!act) return;
    let val = Math.round(pot * mult);
    val = Math.max(act.min, Math.min(act.max, val));
    document.getElementById('raise-slider').value = val;
    updateRaiseDisplay();
}

function confirmRaise() {
    const amount = parseInt(document.getElementById('raise-slider').value);
    const actions = gameState.available_actions;
    const raiseAct = actions.find(a => a.type === 'raise');
    const betAct = actions.find(a => a.type === 'bet');
    if (raiseAct) doAction('raise', amount);
    else if (betAct) doAction('bet', amount);
    raiseMode = false;
}

function hideRaiseControls() {
    raiseMode = false;
    document.getElementById('raise-controls').classList.add('hidden');
}

// ── Rendering ────────────────────────────────────────────────
function renderAll() {
    if (!gameState) return;
    renderPlayers();
    renderCommunityCards();
    renderPot();
    renderActions();
    renderHistory();
    renderPhase();
    renderHandInfo();
    renderShowdown();
}

function createCardHTML(card, extraClass = '') {
    if (card.suit === 'back') {
        return `<div class="card ${extraClass} card-deal"><div class="card-inner"><div class="card-back"></div></div></div>`;
    }
    const suitClass = 'suit-' + card.suit;
    return `<div class="card revealed ${suitClass} ${extraClass} card-deal">
        <div class="card-inner">
            <div class="card-back"></div>
            <div class="card-front">
                <div class="card-corner card-corner-top">${card.rank}${card.symbol}</div>
                <div class="card-rank">${card.rank}</div>
                <div class="card-suit">${card.symbol}</div>
                <div class="card-corner card-corner-bottom">${card.rank}${card.symbol}</div>
            </div>
        </div>
    </div>`;
}

function renderPlayers() {
    gameState.players.forEach((p, i) => {
        // Name & stack
        const nameEl = document.getElementById('name-' + i);
        const stackEl = document.getElementById('stack-' + i);
        if (nameEl) nameEl.textContent = p.name;
        if (stackEl) stackEl.textContent = '$' + p.stack;

        // Cards
        const cardsEl = document.getElementById('cards-' + i);
        if (cardsEl) {
            cardsEl.innerHTML = p.cards.map((c, ci) => {
                const delay = `style="animation-delay:${ci * 0.15}s"`;
                return createCardHTML(c).replace('class="card', `class="card`).replace('card-deal">', `card-deal" ${delay}>`);
            }).join('');
        }

        // Panel active state
        const panel = document.querySelector(`#seat-${i} .player-panel`);
        if (panel) {
            panel.classList.toggle('active-turn', p.is_active);
        }

        // Status badge
        const statusEl = document.getElementById('status-' + i);
        if (statusEl) {
            statusEl.className = 'player-status';
            if (p.status === 'folded') { statusEl.classList.add('folded'); statusEl.textContent = 'FOLDED'; }
            else if (p.status === 'all-in') { statusEl.classList.add('all-in'); statusEl.textContent = 'ALL IN'; }
            else if (p.status === 'out') { statusEl.classList.add('out'); statusEl.textContent = 'OUT'; }
        }

        // Dealer chip
        const dealerEl = document.getElementById('dealer-' + i);
        if (dealerEl) dealerEl.classList.toggle('visible', p.is_dealer);

        // Bet amount
        const betEl = document.getElementById('bet-' + i);
        if (betEl) {
            if (p.bet_amount > 0) {
                betEl.style.display = 'block';
                betEl.textContent = '$' + p.bet_amount;
            } else {
                betEl.style.display = 'none';
            }
        }

        // Winner highlight
        const seatEl = document.getElementById('seat-' + i);
        if (seatEl) seatEl.classList.remove('winner');
    });

    // Highlight winners at showdown
    if (gameState.is_hand_over && gameState.hand_winners.length > 0) {
        const lastWinners = gameState.hand_winners.filter(w => w.game === gameState.hand_number);
        lastWinners.forEach(w => {
            const idx = gameState.players.findIndex(p => p.name === w.winner);
            if (idx >= 0) document.getElementById('seat-' + idx)?.classList.add('winner');
        });
    }
}

function renderCommunityCards() {
    for (let i = 0; i < 5; i++) {
        const slot = document.getElementById('comm-' + i);
        if (!slot) continue;
        if (gameState.community_cards[i]) {
            const card = gameState.community_cards[i];
            slot.innerHTML = createCardHTML(card);
            slot.style.border = 'none';
            slot.style.background = 'none';
        } else {
            slot.innerHTML = '';
            slot.style.border = '';
            slot.style.background = '';
        }
    }
}

function renderPot() {
    const potVal = document.getElementById('pot-value');
    if (potVal) potVal.textContent = '$' + (gameState.pot || 0);

    // Chip visuals
    const chipStack = document.getElementById('pot-chip-stack');
    if (chipStack) {
        const pot = gameState.pot || 0;
        let chips = '';
        const colors = ['#e74c3c', '#3498db', '#27ae60', '#f39c12', '#1a1a2e'];
        const count = Math.min(Math.ceil(pot / 100), 8);
        for (let i = 0; i < count; i++) {
            const c = colors[i % colors.length];
            chips += `<div style="width:16px;height:16px;border-radius:50%;background:${c};border:2px solid rgba(255,255,255,0.3);box-shadow:0 2px 4px rgba(0,0,0,0.4);margin-left:${i > 0 ? '-4px' : '0'}"></div>`;
        }
        chipStack.innerHTML = chips;
    }
}

function renderActions() {
    const bar = document.getElementById('action-bar');
    const nextArea = document.getElementById('next-hand-area');

    if (gameState.is_hand_over) {
        bar.classList.add('hidden');
        nextArea.classList.remove('hidden');
        return;
    }

    nextArea.classList.add('hidden');

    if (gameState.available_actions.length > 0) {
        bar.classList.remove('hidden');
        const actions = gameState.available_actions;
        const hasFold = actions.find(a => a.type === 'fold');
        const hasCheck = actions.find(a => a.type === 'check');
        const hasCall = actions.find(a => a.type === 'call');
        const hasRaise = actions.find(a => a.type === 'raise');
        const hasBet = actions.find(a => a.type === 'bet');
        const hasAllin = actions.find(a => a.type === 'all_in');

        document.getElementById('btn-fold').classList.toggle('hidden', !hasFold);
        const ccBtn = document.getElementById('btn-check-call');
        const ccLabel = document.getElementById('check-call-label');
        if (hasCheck) {
            ccBtn.classList.remove('hidden');
            ccLabel.textContent = 'CHECK';
            ccBtn.className = 'action-btn btn-check';
        } else if (hasCall) {
            ccBtn.classList.remove('hidden');
            ccLabel.textContent = `CALL $${hasCall.amount}`;
            ccBtn.className = 'action-btn btn-check';
        } else {
            ccBtn.classList.add('hidden');
        }

        const raiseBtn = document.getElementById('btn-raise');
        const raiseLabel = document.getElementById('raise-label');
        if (hasRaise) {
            raiseBtn.classList.remove('hidden');
            raiseLabel.textContent = 'RAISE';
        } else if (hasBet) {
            raiseBtn.classList.remove('hidden');
            raiseLabel.textContent = 'BET';
        } else {
            raiseBtn.classList.add('hidden');
        }

        if (hasAllin) {
            document.getElementById('btn-allin').classList.remove('hidden');
            document.getElementById('allin-label').textContent = `ALL IN $${hasAllin.amount}`;
        } else {
            document.getElementById('btn-allin').classList.add('hidden');
        }
    } else {
        bar.classList.add('hidden');
    }
    hideRaiseControls();
}

function renderHistory() {
    const list = document.getElementById('history-list');
    if (!list) return;
    let html = '';
    let lastPhase = '';
    gameState.action_history.forEach(h => {
        if (h.phase !== lastPhase) {
            html += `<div class="history-phase">${h.phase}</div>`;
            lastPhase = h.phase;
        }
        const amountStr = h.amount > 0 ? `$${h.amount}` : '';
        html += `<div class="history-item">
            <span class="h-player">${h.player}</span>
            <span class="h-action">${h.action}</span>
            <span class="h-amount">${amountStr}</span>
        </div>`;
    });
    list.innerHTML = html;
    list.scrollTop = list.scrollHeight;
}

function renderPhase() {
    const el = document.getElementById('phase-text');
    if (el) el.textContent = (gameState.phase || 'waiting').toUpperCase().replace('-', ' ');
}

function renderHandInfo() {
    const hn = document.getElementById('hand-number');
    if (hn) hn.textContent = '#' + (gameState.hand_number || 0);
    const ba = document.getElementById('blind-amount');
    if (ba) ba.textContent = '$' + (gameState.big_blind || 20);
}

function renderShowdown() {
    const area = document.getElementById('winner-announcement');
    if (!area) return;
    if (!gameState.is_hand_over) { area.textContent = ''; return; }
    const lastWinners = gameState.hand_winners.filter(w => w.game === gameState.hand_number);
    if (lastWinners.length > 0) {
        area.innerHTML = lastWinners.map(w =>
            `🏆 ${w.winner} wins $${w.amount}`
        ).join('<br>');
    } else {
        area.textContent = 'Hand Complete';
    }
}

// ── UI Helpers ───────────────────────────────────────────────
function hideModal() {
    const m = document.getElementById('welcome-modal');
    if (m) m.classList.add('hidden');
}

function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.remove('hidden');
    setTimeout(() => t.classList.add('hidden'), 3000);
}

// ── Keyboard Shortcuts ───────────────────────────────────────
document.addEventListener('keydown', e => {
    if (!gameState || gameState.is_hand_over) {
        if (e.key === 'Enter' || e.key === ' ') { nextHand(); e.preventDefault(); }
        return;
    }
    if (gameState.available_actions.length === 0) return;
    if (raiseMode && e.key === 'Enter') { confirmRaise(); return; }
    if (raiseMode && e.key === 'Escape') { doRaise(); return; }
    switch (e.key.toLowerCase()) {
        case 'f': doAction('fold'); break;
        case 'c': doCheckCall(); break;
        case 'r': doRaise(); break;
        case 'a': doAction('all_in'); break;
    }
});

// ── Particles ────────────────────────────────────────────────
function initParticles() {
    const canvas = document.getElementById('particles-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let w, h, particles = [];

    function resize() {
        w = canvas.width = window.innerWidth;
        h = canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener('resize', resize);

    for (let i = 0; i < 50; i++) {
        particles.push({
            x: Math.random() * w, y: Math.random() * h,
            vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3,
            r: Math.random() * 2 + 0.5, a: Math.random() * 0.4 + 0.1
        });
    }

    function draw() {
        ctx.clearRect(0, 0, w, h);
        particles.forEach(p => {
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(212,168,67,${p.a})`;
            ctx.fill();
            p.x += p.vx; p.y += p.vy;
            if (p.x < 0) p.x = w;
            if (p.x > w) p.x = 0;
            if (p.y < 0) p.y = h;
            if (p.y > h) p.y = 0;
        });
        requestAnimationFrame(draw);
    }
    draw();
}

initParticles();
