(() => {
    'use strict';

    const app = document.getElementById('bmi-app');
    if (!app) return;

    const canBind = app.dataset.canBind === '1';
    const canApply = app.dataset.canApply === '1';
    const state = { sessionId: null, sessionName: '', location: '', activeLine: null, unknownLine: null, recent: [] };
    const $ = (id) => document.getElementById(id);

    async function rpc(route, params = {}) {
        const response = await fetch(route, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params, id: Date.now() }),
        });
        const payload = await response.json();
        if (payload.error) {
            const msg = payload.error.data?.message || payload.error.message || 'Ошибка сервера';
            throw new Error(msg);
        }
        return payload.result;
    }

    function screen(id) {
        document.querySelectorAll('.screen').forEach(el => el.classList.remove('active'));
        $(id).classList.add('active');
    }

    function toast(message, type = 'success') {
        const el = $('toast');
        el.textContent = message;
        el.className = `toast ${type}`;
        clearTimeout(toast.timer);
        toast.timer = setTimeout(() => el.classList.add('hidden'), 2500);
    }

    function error(message) { toast(message, 'error'); }
    function fmt(value) { return Number(value || 0).toLocaleString('ru-RU', { maximumFractionDigits: 3 }); }
    function hide(...ids) { ids.forEach(id => $(id).classList.add('hidden')); }
    function show(...ids) { ids.forEach(id => $(id).classList.remove('hidden')); }
    function resetItemPanels() {
        state.activeLine = null;
        state.unknownLine = null;
        hide('product-panel', 'unknown-panel', 'bind-panel');
        $('counted-input').value = '';
    }
    function focusBarcode() {
        $('barcode-input').value = '';
        $('barcode-input').focus();
    }
    function recent(label) {
        state.recent.unshift(label);
        state.recent = state.recent.slice(0, 8);
        const root = $('recent-lines');
        root.textContent = '';
        root.classList.remove('muted');
        state.recent.forEach(text => {
            const row = document.createElement('div');
            row.className = 'history-row';
            row.textContent = text;
            root.appendChild(row);
        });
    }

    async function start() {
        const locationId = $('location-select').value;
        if (!locationId) return error('Выберите локацию склада.');
        try {
            const out = await rpc('/mobile/inventory/start', { location_id: Number(locationId) });
            state.sessionId = out.session_id;
            state.sessionName = out.name;
            state.location = out.location;
            $('session-label').textContent = out.name;
            $('count-location').textContent = out.location;
            screen('screen-count');
            focusBarcode();
        } catch (e) { error(e.message); }
    }

    function fillProduct(out) {
        state.activeLine = out.line;
        state.unknownLine = null;
        hide('unknown-panel', 'bind-panel');
        show('product-panel');
        $('product-warning').classList.add('hidden');
        $('product-name').textContent = out.line.product_name || out.product?.name || '';
        $('product-meta').textContent = `${out.line.barcode} · ${out.line.category || ''}`;
        $('theoretical-qty').textContent = fmt(out.line.theoretical_qty);
        $('counted-input').value = out.line.counted_qty === null ? '' : out.line.counted_qty;
        $('counted-input').focus();
        $('counted-input').select();
        if (out.existing) {
            $('product-warning').textContent = 'Этот товар уже считался. Измените количество или оставьте прежнее.';
            $('product-warning').classList.remove('hidden');
        }
    }

    async function scan() {
        const barcode = $('barcode-input').value.trim();
        if (!barcode) return;
        try {
            const out = await rpc('/mobile/inventory/scan', { session_id: state.sessionId, barcode });
            if (!out.success) return error(out.message);
            if (out.status === 'not_found') {
                resetItemPanels();
                state.unknownLine = out.line;
                $('unknown-barcode').textContent = out.line.barcode;
                $('bind-open-btn').classList.toggle('hidden', !canBind);
                show('unknown-panel');
                return;
            }
            if (out.status === 'unsupported') {
                resetItemPanels();
                state.activeLine = out.line;
                show('product-panel');
                $('product-warning').textContent = out.message;
                $('product-warning').classList.remove('hidden');
                $('product-name').textContent = out.line.product_name;
                $('product-meta').textContent = out.line.barcode;
                $('theoretical-qty').textContent = '—';
                $('counted-input').disabled = true;
                $('save-qty-btn').disabled = true;
                return;
            }
            $('counted-input').disabled = false;
            $('save-qty-btn').disabled = false;
            fillProduct(out);
        } catch (e) { error(e.message); }
    }

    async function saveQty() {
        if (!state.activeLine) return;
        const raw = $('counted-input').value.trim();
        const counted = raw === '' ? null : Number(raw);
        if (raw !== '' && !Number.isFinite(counted)) return error('Введите корректное количество.');
        try {
            const out = await rpc('/mobile/inventory/set_qty', {
                session_id: state.sessionId,
                line_id: state.activeLine.id,
                counted_qty: counted,
            });
            if (!out.success) return error(out.message);
            const line = out.line;
            recent(`✓ ${line.product_name}: ${fmt(line.theoretical_qty)} → ${fmt(line.counted_qty)}`);
            toast('Сохранено');
            resetItemPanels();
            focusBarcode();
        } catch (e) { error(e.message); }
    }

    async function skip(line) {
        if (!line) return;
        try {
            await rpc('/mobile/inventory/skip', { session_id: state.sessionId, line_id: line.id });
            recent(`↷ Пропущено: ${line.product_name || line.barcode}`);
            toast('Пропущено', 'warning');
            resetItemPanels();
            $('counted-input').disabled = false;
            $('save-qty-btn').disabled = false;
            focusBarcode();
        } catch (e) { error(e.message); }
    }

    function adjustQty(delta) {
        if (!state.activeLine) return;
        const input = $('counted-input');
        const base = input.value === '' ? Number(state.activeLine.theoretical_qty || 0) : Number(input.value);
        input.value = Math.max(0, base + delta);
        input.focus();
    }

    async function searchProducts() {
        const query = $('product-search-input').value.trim();
        try {
            const out = await rpc('/mobile/inventory/search_product', { query });
            const root = $('product-results');
            root.textContent = '';
            if (!out.products.length) {
                root.textContent = 'Товары не найдены.';
                return;
            }
            out.products.forEach(product => {
                const item = document.createElement('div');
                item.className = 'result';
                const info = document.createElement('div');
                const title = document.createElement('strong');
                title.textContent = product.name;
                const meta = document.createElement('p');
                meta.textContent = product.barcode ? `Штрихкод: ${product.barcode}` : 'Штрихкод отсутствует';
                info.append(title, meta);
                const btn = document.createElement('button');
                btn.className = 'btn small ' + (product.can_bind_barcode ? 'primary' : 'secondary');
                btn.textContent = product.can_bind_barcode ? 'Выбрать' : 'Недоступен';
                btn.disabled = !product.can_bind_barcode;
                if (product.can_bind_barcode) btn.addEventListener('click', () => bindBarcode(product));
                item.append(info, btn);
                root.appendChild(item);
            });
        } catch (e) { error(e.message); }
    }

    async function bindBarcode(product) {
        const barcode = state.unknownLine?.barcode;
        if (!barcode) return;
        if (!window.confirm(`Привязать штрихкод ${barcode} к товару «${product.name}»?`)) return;
        try {
            const out = await rpc('/mobile/inventory/bind_barcode', {
                session_id: state.sessionId,
                barcode,
                product_id: product.id,
            });
            if (!out.success) return error(out.message);
            toast('Штрихкод привязан');
            fillProduct(out);
        } catch (e) { error(e.message); }
    }

    function renderSummary(summary) {
        const metrics = [
            ['Всего товаров', summary.total], ['Без изменений', summary.unchanged],
            ['Недостача', summary.shortage], ['Излишек', summary.surplus],
            ['Не найдено', summary.not_found], ['Новых привязок', summary.barcode_bound],
        ];
        const counters = $('summary-counters');
        counters.textContent = '';
        metrics.forEach(([label, value]) => {
            const block = document.createElement('div');
            block.innerHTML = `<strong>${value}</strong><span>${label}</span>`;
            counters.appendChild(block);
        });
        const body = $('summary-lines'); body.textContent = '';
        summary.lines.forEach(line => {
            const tr = document.createElement('tr');
            [line.product_name, fmt(line.theoretical_qty), fmt(line.counted_qty), (line.difference_qty > 0 ? '+' : '') + fmt(line.difference_qty)].forEach(value => {
                const td = document.createElement('td'); td.textContent = value; tr.appendChild(td);
            });
            if (line.difference_qty < 0) tr.className = 'negative';
            if (line.difference_qty > 0) tr.className = 'positive';
            body.appendChild(tr);
        });
        const bound = $('bound-summary');
        bound.textContent = '';
        if (summary.bound_lines.length) {
            bound.classList.remove('hidden');
            const title = document.createElement('h2'); title.textContent = 'Новые привязки штрихкодов'; bound.appendChild(title);
            summary.bound_lines.forEach(line => {
                const p = document.createElement('p'); p.textContent = `${line.barcode} → ${line.product_name}`; bound.appendChild(p);
            });
        } else bound.classList.add('hidden');
    }

    async function finish() {
        try {
            const out = await rpc('/mobile/inventory/finish', { session_id: state.sessionId });
            if (!out.success) return error(out.message);
            renderSummary(out.summary);
            screen('screen-review');
        } catch (e) { error(e.message); }
    }

    async function reopenCount() {
        try {
            await rpc('/mobile/inventory/reopen', { session_id: state.sessionId });
            screen('screen-count'); focusBarcode();
        } catch (e) { error(e.message); }
    }

    async function preview() {
        try {
            const out = await rpc('/mobile/inventory/preview_apply', { session_id: state.sessionId });
            const p = out.preview;
            const root = $('preview-lines'); root.textContent = '';
            p.rows.forEach(row => {
                const card = document.createElement('div');
                card.className = 'card preview-row ' + (row.blocked ? 'blocked' : 'ready');
                const title = document.createElement('h3'); title.textContent = row.product_name;
                const info = document.createElement('p');
                info.textContent = `При скане: ${fmt(row.scanned_qty)} · Сейчас Odoo: ${fmt(row.current_qty)} · Будет: ${fmt(row.counted_qty)} · Изменение: ${row.difference_from_current > 0 ? '+' : ''}${fmt(row.difference_from_current)}`;
                card.append(title, info);
                if (row.message) { const warning = document.createElement('p'); warning.className = 'notice'; warning.textContent = row.message; card.appendChild(warning); }
                root.appendChild(card);
            });
            $('preview-message').textContent = p.can_apply ? 'Проверка пройдена. Корректировку можно применить.' : 'Применение заблокировано: устраните конфликты или пересчитайте товары.';
            $('preview-message').className = 'notice ' + (p.can_apply ? 'success' : 'danger');
            $('apply-btn').classList.toggle('hidden', !p.can_apply || !canApply);
            if (p.can_apply && !canApply) $('preview-message').textContent += ' Применить может только менеджер склада.';
            screen('screen-preview');
        } catch (e) { error(e.message); }
    }

    async function applyInventory() {
        if (!window.confirm('Применить корректировку остатков в Odoo? Это изменит складские количества.')) return;
        try {
            const out = await rpc('/mobile/inventory/apply', { session_id: state.sessionId });
            if (!out.success) return error(out.message);
            renderSummary(out.summary);
            $('preview-message').textContent = 'Корректировка успешно применена.';
            toast('Остатки применены');
            screen('screen-review');
            $('preview-btn').classList.add('hidden');
            $('back-count-btn').classList.add('hidden');
        } catch (e) { error(e.message); }
    }

    async function cancelSession() {
        if (!window.confirm('Отменить эту сессию подсчёта? Привязанные штрихкоды останутся в карточках товаров.')) return;
        try {
            await rpc('/mobile/inventory/cancel', { session_id: state.sessionId });
            window.location.reload();
        } catch (e) { error(e.message); }
    }

    $('start-btn').addEventListener('click', start);
    $('barcode-input').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); scan(); } });
    $('counted-input').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); saveQty(); } });
    $('save-qty-btn').addEventListener('click', saveQty);
    $('minus-btn').addEventListener('click', () => adjustQty(-1));
    $('plus-btn').addEventListener('click', () => adjustQty(1));
    $('skip-btn').addEventListener('click', () => skip(state.activeLine));
    $('unknown-skip-btn').addEventListener('click', () => skip(state.unknownLine));
    $('bind-open-btn').addEventListener('click', () => { hide('unknown-panel'); show('bind-panel'); $('bind-barcode').textContent = state.unknownLine.barcode; $('product-search-input').focus(); });
    $('bind-back-btn').addEventListener('click', () => { hide('bind-panel'); show('unknown-panel'); });
    $('product-search-btn').addEventListener('click', searchProducts);
    $('product-search-input').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); searchProducts(); } });
    $('finish-btn').addEventListener('click', finish);
    $('back-count-btn').addEventListener('click', reopenCount);
    $('preview-btn').addEventListener('click', preview);
    $('preview-back-btn').addEventListener('click', () => screen('screen-review'));
    $('apply-btn').addEventListener('click', applyInventory);
    $('cancel-btn').addEventListener('click', cancelSession);
})();
