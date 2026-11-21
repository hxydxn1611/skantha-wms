/*
 * Palletization "Simple" mode (2026-11-18).
 *
 * Adds a 3-step guide (1 Pallet & product -> 2 Photo -> 3 Check & save) and a Simple / Advanced
 * switch on top of the existing Palletization screen. Simple mode only hides advanced panels
 * (pallet_simple.css) and uses plainer labels; every original button and function is the same
 * one underneath. Advanced shows the original screen unchanged. Each person's choice is
 * remembered in this browser. To remove: delete this file, css/pallet_simple.css and their
 * two lines in templates/index.html.
 */
(function () {
    'use strict';

    const KEY = 'warlog_pz_mode';
    const view = () => document.getElementById('palletization-view');
    // plain labels in Simple mode (originals are restored in Advanced)
    const LABELS = [
        ['btnRunWorkbenchCount', '<i class="fas fa-bolt"></i> Count now'],
        ['btnSealPallet', '<i class="fas fa-lock"></i> Seal pallet'],
    ];

    function getMode() {
        try { return localStorage.getItem(KEY) || 'advanced'; } catch (e) { return 'advanced'; }
    }

    function setMode(mode) {
        try { localStorage.setItem(KEY, mode); } catch (e) {}
        apply(mode);
    }

    function relabel(simple) {
        LABELS.forEach(([id, html]) => {
            const el = document.getElementById(id);
            if (!el) return;
            if (!el.dataset.pzsOriginal) el.dataset.pzsOriginal = el.innerHTML;
            el.innerHTML = simple ? html : el.dataset.pzsOriginal;
        });
        const apply = [...document.querySelectorAll('#palletization-view button')]
            .find(b => (b.getAttribute('onclick') || '').includes('applyVerifiedCountToActivePallet'));
        if (apply) {
            if (!apply.dataset.pzsOriginal) apply.dataset.pzsOriginal = apply.innerHTML;
            apply.innerHTML = simple ? '<i class="fas fa-check-double"></i> <span>Save count to pallet</span>' : apply.dataset.pzsOriginal;
        }
        const hero = document.getElementById('wbTotalBadge');
        const label = hero && hero.parentElement ? hero.parentElement.querySelector('span') : null;
        if (label) {
            if (!label.dataset.pzsOriginal) label.dataset.pzsOriginal = label.textContent;
            label.textContent = simple ? 'Counted' : label.dataset.pzsOriginal;
        }
    }

    function apply(mode) {
        const v = view();
        if (!v) return;
        const simple = mode !== 'advanced';
        v.classList.toggle('pz-simple', simple);
        document.querySelectorAll('.pzs-mode button').forEach(b => b.classList.toggle('is-on', b.dataset.mode === (simple ? 'simple' : 'advanced')));
        const hint = document.getElementById('pzsHint');
        if (hint) hint.style.display = simple ? '' : 'none';
        if (simple && typeof window.switchPalletSubTab === 'function') {
            try { window.switchPalletSubTab('wb'); } catch (e) {}
        }
        relabel(simple);
        refreshSteps();
    }

    // ------------------------------------------------------------------ step state (read from the screen)
    function textOf(id) { const el = document.getElementById(id); return el ? el.textContent.trim() : ''; }

    function state() {
        const palletId = textOf('palletMonitorId');
        const hasPallet = !!palletId && palletId !== '--' && !/^PLT-2026-0894$/.test(palletId);
        const preview = document.getElementById('wbPreviewImg');
        const result = document.getElementById('wbResultImg');
        const live = document.getElementById('wbCameraViewWrap');
        const hasPhoto = !!(preview && preview.getAttribute('src') && preview.offsetParent !== null)
            || !!(result && result.getAttribute('src'))
            || !!(live && live.offsetParent !== null);
        const counted = parseInt((textOf('wbTotalBadge').match(/\d+/) || ['0'])[0], 10) > 0;
        return { hasPallet, hasPhoto, counted };
    }

    function refreshSteps() {
        const bar = document.getElementById('pzsBar');
        if (!bar) return;
        const s = state();
        const done = [s.hasPallet, s.hasPhoto && s.counted ? true : s.hasPhoto, s.counted];
        const current = !s.hasPallet ? 0 : (!s.counted ? 1 : 2);
        bar.querySelectorAll('.pzs-step').forEach((el, i) => {
            el.classList.toggle('is-current', i === current);
            el.classList.toggle('is-done', i !== current && (i < current || done[i]));
        });
        bar.querySelectorAll('.pzs-line').forEach((el, i) => el.classList.toggle('is-done', i < current));
        const hint = document.getElementById('pzsHint');
        if (hint) {
            const msgs = [
                '<b>Step 1:</b> pick the pallet you are filling (or press <b>+ Build New Pallet</b>), then choose the product and whether you count <b>pieces, bundles or boxes</b>.',
                '<b>Step 2:</b> stand in front of the pallet with the whole stack in view, <b>upload a photo</b> or use the camera, then press <b>Count now</b>.',
                '<b>Step 3:</b> check the numbered markers (tap one to remove it, tap empty space to add one), then press <b>Save count to pallet</b>.',
            ];
            hint.querySelector('span').innerHTML = msgs[current];
        }
    }

    // ------------------------------------------------------------------ build the guide once
    function build() {
        const v = view();
        if (!v || document.getElementById('pzsBar')) return;
        const tabs = document.getElementById('pallet-tab-wb-btn');
        const anchor = tabs ? tabs.parentElement : document.getElementById('palletCountingWorkbench');
        if (!anchor || !anchor.parentElement) return;
        const step = (n, title, sub) => `<span class="pzs-step"><span class="pzs-step-num">${n}</span>
            <span>${title}<span class="pzs-step-sub">${sub}</span></span></span>`;
        const bar = document.createElement('div');
        bar.id = 'pzsBar';
        bar.className = 'pzs-bar';
        bar.innerHTML = `
            <div class="pzs-steps" aria-label="Palletization steps">
                ${step(1, 'Pallet &amp; product', 'what are you counting?')}
                <span class="pzs-line"></span>
                ${step(2, 'Photo', 'take or upload one')}
                <span class="pzs-line"></span>
                ${step(3, 'Check &amp; save', 'confirm the count')}
            </div>
            <div class="pzs-mode" role="group" aria-label="Screen mode">
                <button type="button" data-mode="simple"><i class="fas fa-wand-magic-sparkles"></i> Simple</button>
                <button type="button" data-mode="advanced"><i class="fas fa-sliders"></i> Advanced</button>
            </div>`;
        const hint = document.createElement('div');
        hint.id = 'pzsHint';
        hint.className = 'pzs-hint';
        hint.innerHTML = '<i class="fas fa-circle-info"></i><span></span>';
        anchor.parentElement.insertBefore(bar, anchor);
        anchor.parentElement.insertBefore(hint, anchor);
        bar.querySelectorAll('.pzs-mode button').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
        apply(getMode());
        // keep the step guide in step with the screen (cheap: only while Palletization is open)
        setInterval(() => { const vv = view(); if (vv && vv.classList.contains('active')) refreshSteps(); }, 1000);
    }

    if (document.readyState === 'complete') build();
    else window.addEventListener('load', build);
    window.warlogPalletMode = setMode;
})();
