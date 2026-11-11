/**
 * WARLOG AI Copilot • macOS x Samsung Bixby Operations Copilot
 * Features:
 * - macOS Frosted Liquid Glass Window + Traffic Light Controls
 * - Bixby Holographic Neon Glowing Orb & Live Fluid Soundwave
 * - Hands-Free Web Speech API Voice Recognition (🎙️)
 * - Intelligent Interactive Warehouse Cards (ANPR Plates, SKU Bins, Dock Balance)
 * - Direct 1-Click Action Execution (Dock Admission, Snapshot View, 3D Bin Navigation)
 * - Global Shortcut: Ctrl + Space / Cmd + Space
 */

(function () {
    'use strict';

    let isCopilotOpen = false;
    let isVoiceActive = false;
    let recognition = null;
    let isSpeaking = false;

    // Initialize Speech Recognition if supported in browser
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        try {
            recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = true;
            recognition.lang = 'en-US';

            recognition.onstart = function () {
                isVoiceActive = true;
                updateVoiceIndicator(true);
            };

            recognition.onresult = function (event) {
                let transcript = '';
                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    transcript += event.results[i][0].transcript;
                }
                const inputEl = document.getElementById('copilotInput');
                if (inputEl) inputEl.value = transcript;
            };

            recognition.onerror = function (event) {
                console.warn('Copilot Speech recognition error:', event.error);
                isVoiceActive = false;
                updateVoiceIndicator(false);
            };

            recognition.onend = function () {
                isVoiceActive = false;
                updateVoiceIndicator(false);
                const inputEl = document.getElementById('copilotInput');
                if (inputEl && inputEl.value.trim().length > 1) {
                    submitCopilotQuery(inputEl.value.trim());
                }
            };
        } catch (e) {
            console.debug('Speech recognition not available', e);
        }
    }

    function updateVoiceIndicator(recording) {
        const micBtn = document.getElementById('copilotMicBtn');
        const orbRing = document.getElementById('copilotOrbContainer');
        const soundwaveEl = document.getElementById('copilotSoundwave');
        if (micBtn) {
            if (recording) {
                micBtn.classList.add('recording-pulse');
                micBtn.style.background = 'linear-gradient(135deg, #ef4444, #f97316)';
                micBtn.innerHTML = '🔴';
            } else {
                micBtn.classList.remove('recording-pulse');
                micBtn.style.background = '';
                micBtn.innerHTML = '🎙️';
            }
        }
        if (soundwaveEl) {
            soundwaveEl.style.opacity = recording ? '1' : '0.4';
        }
    }

    window.toggleCopilot = function () {
        const panel = document.getElementById('warlogCopilotWindow');
        const launcher = document.getElementById('warlogCopilotLauncher');
        if (!panel) return;

        isCopilotOpen = !isCopilotOpen;
        if (isCopilotOpen) {
            panel.style.display = 'flex';
            panel.style.opacity = '0';
            panel.style.transform = 'translateY(16px) scale(0.96)';
            setTimeout(() => {
                panel.style.opacity = '1';
                panel.style.transform = 'translateY(0) scale(1)';
            }, 10);
            if (launcher) launcher.style.display = 'none';
            const inputEl = document.getElementById('copilotInput');
            if (inputEl) setTimeout(() => inputEl.focus(), 80);
        } else {
            panel.style.opacity = '0';
            panel.style.transform = 'translateY(16px) scale(0.96)';
            setTimeout(() => {
                panel.style.display = 'none';
                if (launcher) launcher.style.display = 'flex';
            }, 200);
            if (isVoiceActive && recognition) recognition.stop();
        }
    };

    window.toggleCopilotExpand = function () {
        const panel = document.getElementById('warlogCopilotWindow');
        if (panel) panel.classList.toggle('expanded');
    };

    window.toggleCopilotVoice = function () {
        if (!recognition) {
            alert('Voice recognition is not supported in this browser. Please use Chrome, Edge, or Safari.');
            return;
        }
        if (isVoiceActive) {
            recognition.stop();
        } else {
            try {
                recognition.start();
            } catch (err) {
                console.warn("Could not start recognition", err);
            }
        }
    };

    window.sendCopilotPreset = function (promptText) {
        const inputEl = document.getElementById('copilotInput');
        if (inputEl) inputEl.value = promptText;
        submitCopilotQuery(promptText);
    };

    window.submitCopilotQuery = async function (explicitText) {
        const inputEl = document.getElementById('copilotInput');
        const queryText = (explicitText || (inputEl ? inputEl.value : '')).trim();
        if (!queryText) return;

        if (inputEl) inputEl.value = '';

        appendUserMessage(queryText);
        showTypingIndicator();

        try {
            const res = await fetch('/api/copilot/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: queryText })
            });

            removeTypingIndicator();

            if (res.ok) {
                const data = await res.json();
                appendAssistantMessage(data.reply, data.cards || []);
                if (data.suggestions && data.suggestions.length) {
                    updatePromptPills(data.suggestions);
                }
            } else {
                appendAssistantMessage("I encountered an error querying the warehouse matrix. Please try again.", []);
            }
        } catch (err) {
            removeTypingIndicator();
            appendAssistantMessage(`Connection failure: ${err.message}`, []);
        }
    };

    function appendUserMessage(text) {
        const chatContainer = document.getElementById('copilotChatStream');
        if (!chatContainer) return;

        const row = document.createElement('div');
        row.style.cssText = 'display:flex; justify-content:flex-end; margin-bottom:12px;';
        row.innerHTML = `
            <div style="background:linear-gradient(135deg, rgba(37,99,235,0.85), rgba(79,70,229,0.85)); color:#ffffff; padding:8px 14px; border-radius:18px 18px 4px 18px; max-width:85%; font-size:0.78rem; line-height:1.45; border:1px solid rgba(255,255,255,0.12); box-shadow:0 4px 12px rgba(0,0,0,0.25);">
                ${escapeHtml(text)}
            </div>
        `;
        chatContainer.appendChild(row);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function showTypingIndicator() {
        const chatContainer = document.getElementById('copilotChatStream');
        if (!chatContainer) return;

        const typingId = 'copilotTypingIndicator';
        if (document.getElementById(typingId)) return;

        const row = document.createElement('div');
        row.id = typingId;
        row.style.cssText = 'display:flex; gap:10px; align-items:flex-start; margin-bottom:12px;';
        row.innerHTML = `
            <div class="copilot-bixby-orb-mini" style="width:26px; height:26px; border-radius:50%; padding:1.5px; shrink:0; display:flex; align-items:center; justify-content:center;">
                <div style="width:100%; height:100%; border-radius:50%; background:#090d16; display:flex; align-items:center; justify-content:center; color:#38bdf8; font-size:10px;">✦</div>
            </div>
            <div style="background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.08); border-radius:18px 18px 18px 4px; padding:10px 14px; display:flex; gap:4px; align-items:center;">
                <span class="typing-dot" style="animation: typingBounce 1.2s infinite ease-in-out; width:5px; height:5px; background:#38bdf8; border-radius:50%;"></span>
                <span class="typing-dot" style="animation: typingBounce 1.2s infinite ease-in-out 0.2s; width:5px; height:5px; background:#818cf8; border-radius:50%;"></span>
                <span class="typing-dot" style="animation: typingBounce 1.2s infinite ease-in-out 0.4s; width:5px; height:5px; background:#c084fc; border-radius:50%;"></span>
            </div>
        `;
        chatContainer.appendChild(row);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function removeTypingIndicator() {
        const el = document.getElementById('copilotTypingIndicator');
        if (el) el.remove();
    }

    function appendAssistantMessage(replyText, cards) {
        const chatContainer = document.getElementById('copilotChatStream');
        if (!chatContainer) return;

        const row = document.createElement('div');
        row.style.cssText = 'display:flex; gap:10px; align-items:flex-start; margin-bottom:14px;';

        let cardsHtml = '';
        if (cards && cards.length) {
            cardsHtml = cards.map(c => renderCardHtml(c)).join('');
        }

        row.innerHTML = `
            <div class="copilot-bixby-orb-mini" style="width:26px; height:26px; border-radius:50%; padding:1.5px; flex-shrink:0; display:flex; align-items:center; justify-content:center; margin-top:2px;">
                <div style="width:100%; height:100%; border-radius:50%; background:#090d16; display:flex; align-items:center; justify-content:center; color:#38bdf8; font-size:10px;">✦</div>
            </div>
            <div style="background:rgba(255,255,255,0.04); backdrop-filter:blur(14px); border:1px solid rgba(255,255,255,0.08); border-radius:18px 18px 18px 4px; padding:12px 14px; max-width:88%; box-shadow:0 4px 20px rgba(0,0,0,0.25);">
                <div style="color:var(--text-main, #f1f5f9); font-size:0.78rem; line-height:1.45; margin-bottom:${cardsHtml ? '10px' : '0'};">
                    ${formatMarkdown(replyText)}
                </div>
                ${cardsHtml}
            </div>
        `;

        chatContainer.appendChild(row);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function renderCardHtml(card) {
        const cType = card.type;
        if (cType === 'vehicle_card') {
            const isYellow = (card.vehicle_type || '').includes('Yellow');
            const isGreen = (card.vehicle_type || '').includes('Green');
            const plateBg = isGreen ? '#10b981' : (isYellow ? '#facc15' : '#f8fafc');
            const textCol = isGreen ? '#ffffff' : '#0f172a';

            const actionButtons = (card.actions || []).map(a => `
                <button type="button" onclick="executeCopilotAction('${a.action}', ${escapeJson(a.params)})" 
                    style="background:linear-gradient(135deg, rgba(16,185,129,0.9), rgba(5,150,105,0.9)); color:#fff; font-size:0.72rem; font-weight:600; padding:4px 10px; border-radius:20px; border:none; cursor:pointer; box-shadow:0 2px 8px rgba(16,185,129,0.3); transition:all 0.15s ease;">
                    ${a.label}
                </button>
            `).join('');

            return `
            <div style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.07); border-radius:12px; padding:10px; margin-top:8px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <div style="background:${plateBg}; color:${textCol}; border:1px solid #1e293b; border-radius:6px; padding:2px 8px; font-family:monospace; font-weight:800; font-size:0.80rem; letter-spacing:0.8px; display:inline-flex; align-items:center; gap:6px;">
                        <span style="background:#1e3a8a; color:#fff; padding:1px 4px; border-radius:2px; font-size:0.55rem; font-weight:bold;">IND</span>
                        <span>${escapeHtml(card.plate)}</span>
                    </div>
                    <span style="font-family:monospace; font-size:0.68rem; color:#34d399; background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.3); padding:2px 6px; border-radius:12px;">
                        ${escapeHtml(card.status_tag || card.status)}
                    </span>
                </div>
                <div style="font-size:0.72rem; color:#94a3b8; display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-bottom:8px;">
                    <div><span style="color:#64748b;">Dock:</span> <strong style="color:#f59e0b;">${escapeHtml(card.dock)}</strong></div>
                    <div><span style="color:#64748b;">PO:</span> <strong style="color:#c084fc;">${escapeHtml(card.po_number)}</strong></div>
                    <div style="grid-column:span 2;"><span style="color:#64748b;">Cargo:</span> <span style="color:#cbd5e1;">${escapeHtml(card.cargo)}</span></div>
                </div>
                ${actionButtons ? `<div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:6px;">${actionButtons}</div>` : ''}
            </div>
            `;
        } else if (cType === 'sku_locator_card') {
            const actionButtons = (card.actions || []).map(a => `
                <button type="button" onclick="executeCopilotAction('${a.action}', ${escapeJson(a.params)})" 
                    style="width:100%; background:rgba(56,189,248,0.12); color:#38bdf8; border:1px solid rgba(56,189,248,0.3); font-size:0.72rem; font-weight:600; padding:6px 10px; border-radius:8px; cursor:pointer; transition:all 0.15s ease;">
                    ${a.label} &rarr;
                </button>
            `).join('');

            return `
            <div style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.07); border-radius:12px; padding:10px; margin-top:8px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <strong style="color:#f1f5f9; font-size:0.78rem;">📦 ${escapeHtml(card.name)}</strong>
                    <span style="font-family:monospace; font-size:0.68rem; color:#38bdf8; background:rgba(56,189,248,0.15); border:1px solid rgba(56,189,248,0.3); padding:2px 6px; border-radius:12px;">${escapeHtml(card.sku_code)}</span>
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-bottom:8px;">
                    <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.05); padding:6px; border-radius:6px;">
                        <div style="font-size:0.65rem; color:#64748b; font-family:monospace;">BIN COORDINATES</div>
                        <div style="font-size:0.76rem; font-weight:bold; color:#34d399; margin-top:2px;">${escapeHtml(card.bin_location)}</div>
                    </div>
                    <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.05); padding:6px; border-radius:6px;">
                        <div style="font-size:0.65rem; color:#64748b; font-family:monospace;">ON-HAND STOCK</div>
                        <div style="font-size:0.76rem; font-weight:bold; color:#f8fafc; margin-top:2px;">${escapeHtml(card.quantity)}</div>
                    </div>
                </div>
                ${actionButtons}
            </div>
            `;
        } else if (cType === 'gate_queue_card') {
            const listItems = (card.items || []).map(it => `
                <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; border-bottom:1px solid rgba(255,255,255,0.05);">
                    <div style="display:flex; align-items:center; gap:6px;">
                        <span style="font-family:monospace; font-weight:700; color:#facc15; font-size:0.75rem;">${escapeHtml(it.plate)}</span>
                        <span style="font-size:0.68rem; color:#94a3b8;">(${escapeHtml(it.po || 'Walk-In')})</span>
                    </div>
                    <button type="button" onclick="executeCopilotAction('admit_dock', {id:'${it.id}', dock:'${it.dock}'})" 
                        style="background:rgba(16,185,129,0.2); color:#34d399; border:1px solid rgba(16,185,129,0.3); font-size:0.68rem; padding:2px 8px; border-radius:12px; cursor:pointer;">
                        Admit &rarr; ${escapeHtml(it.dock)}
                    </button>
                </div>
            `).join('');

            return `
            <div style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.07); border-radius:12px; padding:10px; margin-top:8px;">
                <div style="font-size:0.74rem; font-weight:bold; color:#cbd5e1; margin-bottom:6px;">${escapeHtml(card.title)}</div>
                ${listItems}
            </div>
            `;
        }
        } else if (cType === 'operations_summary_card') {
            const metricsHtml = (card.metrics || []).map(m => `
                <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); padding:8px; border-radius:8px; text-align:center;">
                    <div style="font-size:0.62rem; color:#94a3b8; font-family:monospace; text-transform:uppercase;">${escapeHtml(m.label)}</div>
                    <div style="font-size:0.85rem; font-weight:800; color:#38bdf8; margin-top:2px;">${escapeHtml(m.value)}</div>
                </div>
            `).join('');

            return `
            <div style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.07); border-radius:12px; padding:10px; margin-top:8px;">
                <div style="font-size:0.74rem; font-weight:bold; color:#cbd5e1; margin-bottom:8px;">📊 ${escapeHtml(card.title)}</div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
                    ${metricsHtml}
                </div>
            </div>
            `;
        } else if (cType === 'po_list_card') {
            const itemsHtml = (card.items || []).map(it => `
                <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; border-bottom:1px solid rgba(255,255,255,0.05); font-size:0.72rem;">
                    <div>
                        <strong style="color:#c084fc; font-family:monospace;">${escapeHtml(it.po_number)}</strong>
                        <div style="color:#94a3b8; font-size:0.65rem;">${escapeHtml(it.vendor)} • Plate: ${escapeHtml(it.plate)}</div>
                    </div>
                    <span style="font-size:0.65rem; color:#38bdf8; background:rgba(56,189,248,0.1); border:1px solid rgba(56,189,248,0.25); padding:2px 6px; border-radius:10px;">${escapeHtml(it.status)}</span>
                </div>
            `).join('');

            return `
            <div style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.07); border-radius:12px; padding:10px; margin-top:8px;">
                <div style="font-size:0.74rem; font-weight:bold; color:#cbd5e1; margin-bottom:6px;">📋 ${escapeHtml(card.title)}</div>
                ${itemsHtml}
            </div>
            `;
        } else if (cType === 'vendor_summary_card') {
            const itemsHtml = (card.items || []).map(it => `
                <div style="display:flex; justify-content:space-between; align-items:center; padding:5px 8px; border-bottom:1px solid rgba(255,255,255,0.05); font-size:0.72rem;">
                    <span style="color:#f1f5f9;">🏢 ${escapeHtml(it.name)}</span>
                    <span style="color:#34d399; font-weight:700; font-family:monospace;">${escapeHtml(it.shipments)} shipments</span>
                </div>
            `).join('');

            return `
            <div style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.07); border-radius:12px; padding:10px; margin-top:8px;">
                <div style="font-size:0.74rem; font-weight:bold; color:#cbd5e1; margin-bottom:6px;">👥 ${escapeHtml(card.title)}</div>
                ${itemsHtml}
            </div>
            `;
        } else if (cType === 'knowledge_card') {
            const pointsHtml = (card.points || []).map(p => `
                <li style="margin-bottom:3px; color:#cbd5e1;">${escapeHtml(p)}</li>
            `).join('');

            return `
            <div style="background:rgba(0,0,0,0.35); border:1px solid rgba(56,189,248,0.2); border-radius:12px; padding:10px; margin-top:8px;">
                <div style="font-size:0.76rem; font-weight:bold; color:#38bdf8; margin-bottom:2px;">${escapeHtml(card.title)}</div>
                ${card.subtitle ? `<div style="font-size:0.65rem; color:#94a3b8; margin-bottom:6px;">${escapeHtml(card.subtitle)}</div>` : ''}
                <ul style="font-size:0.70rem; padding-left:14px; margin:0;">
                    ${pointsHtml}
                </ul>
            </div>
            `;
        } else if (cType === 'dock_balance_card') {
            const docksHtml = (card.docks || []).map(d => `
                <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.05); padding:8px; border-radius:8px; text-align:center;">
                    <div style="font-size:0.68rem; font-weight:bold; color:#f59e0b;">${escapeHtml(d.name)}</div>
                    <div style="font-size:0.78rem; font-weight:800; color:#ffffff; margin-top:2px;">${escapeHtml(d.status)}</div>
                    <div style="font-size:0.65rem; color:#94a3b8; margin-top:2px;">${escapeHtml(d.active_trucks)} active</div>
                </div>
            `).join('');

            return `
            <div style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.07); border-radius:12px; padding:10px; margin-top:8px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span style="font-size:0.74rem; font-weight:bold; color:#cbd5e1;">⚓ ${escapeHtml(card.title)}</span>
                    <span style="font-size:0.68rem; color:#34d399;">Recommended: ${escapeHtml(card.suggested_dock)}</span>
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
                    ${docksHtml}
                </div>
            </div>
            `;
        } else if (cType === 'camera_matrix_card') {
            const camsHtml = (card.cameras || []).map(c => `
                <div style="display:flex; justify-content:space-between; align-items:center; padding:5px 8px; border-bottom:1px solid rgba(255,255,255,0.05); font-size:0.70rem;">
                    <div>
                        <strong style="color:#f1f5f9;">${escapeHtml(c.name)}</strong>
                        <span style="color:#64748b; font-size:0.65rem;"> (${escapeHtml(c.loc || c.id)})</span>
                    </div>
                    <span style="font-size:0.65rem; color:#34d399; font-weight:bold;">● ${escapeHtml(c.status)}</span>
                </div>
            `).join('');

            return `
            <div style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.07); border-radius:12px; padding:10px; margin-top:8px;">
                <div style="font-size:0.74rem; font-weight:bold; color:#cbd5e1; margin-bottom:6px;">🎥 ${escapeHtml(card.title)}</div>
                ${camsHtml}
            </div>
            `;
        } else if (cType === 'low_stock_audit_card') {
            const itemsHtml = (card.items || []).map(it => `
                <div style="display:flex; justify-content:space-between; align-items:center; padding:5px 8px; border-bottom:1px solid rgba(255,255,255,0.05); font-size:0.70rem;">
                    <div>
                        <strong style="color:#f87171;">⚠️ ${escapeHtml(it.name)}</strong>
                        <div style="font-family:monospace; color:#64748b; font-size:0.65rem;">${escapeHtml(it.code)}</div>
                    </div>
                    <div style="text-align:right;">
                        <span style="color:#ef4444; font-weight:bold;">${escapeHtml(it.stock)} ${escapeHtml(it.uom)}</span>
                        <div style="font-size:0.62rem; color:#94a3b8;">Min: ${escapeHtml(it.reorder)}</div>
                    </div>
                </div>
            `).join('');

            return `
            <div style="background:rgba(0,0,0,0.35); border:1px solid rgba(239,68,68,0.25); border-radius:12px; padding:10px; margin-top:8px;">
                <div style="font-size:0.74rem; font-weight:bold; color:#fca5a5; margin-bottom:6px;">${escapeHtml(card.title)}</div>
                ${itemsHtml}
            </div>
            `;
        } else if (cType === 'delivery_card') {
            return `
            <div style="background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.07); border-radius:12px; padding:10px; margin-top:8px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <strong style="color:#facc15; font-family:monospace; font-size:0.78rem;">🚛 ${escapeHtml(card.plate)}</strong>
                    <span style="font-size:0.65rem; color:#38bdf8; background:rgba(56,189,248,0.15); padding:2px 6px; border-radius:10px;">${escapeHtml(card.status)}</span>
                </div>
                <div style="font-size:0.70rem; color:#94a3b8; margin-bottom:6px;">
                    <div>PO: <strong style="color:#c084fc;">${escapeHtml(card.po_number)}</strong> • ${escapeHtml(card.vendor)}</div>
                    <div>Expected: <span style="color:#cbd5e1;">${escapeHtml(card.expected_date)}</span></div>
                </div>
            </div>
            `;
        }
        return '';
    }

    window.executeCopilotAction = async function (action, params) {
        if (action === 'open_po_studio') {
            if (typeof window.switchTab === 'function') window.switchTab('inbound-flow');
            return;
        }
        if (action === 'open_3d_bin') {
            if (typeof window.switchTab === 'function') window.switchTab('palletization');
            showToast(`Navigating to 3D Pallet & Rack Map for ${params.bin_code || 'Bin'}...`, 'info');
            return;
        }
        if (action === 'view_snapshot') {
            if (typeof window.openTruckImageModal === 'function') {
                window.openTruckImageModal('/static/' + params.photo, params.plate, params.id);
            }
            return;
        }
        if (action === 'open_gate_pass') {
            if (typeof window.switchTab === 'function') window.switchTab('gate-passes');
            return;
        }

        try {
            const res = await fetch('/api/copilot/action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: action, params: params })
            });
            const data = await res.json();
            if (data.success) {
                showToast(data.message, 'success');
                appendAssistantMessage(`✅ ${data.message}`, []);
                // Refresh gate passes grid if available
                if (typeof window.fetchGatePasses === 'function') window.fetchGatePasses();
            } else {
                showToast(data.message || 'Action failed', 'error');
            }
        } catch (e) {
            showToast('Action dispatch error: ' + e.message, 'error');
        }
    };

    function updatePromptPills(pills) {
        const container = document.getElementById('copilotPromptPills');
        if (!container || !pills || !pills.length) return;
        container.innerHTML = pills.map(p => `
            <span onclick="sendCopilotPreset('${escapeHtml(p)}')" 
                style="background:rgba(255,255,255,0.06); hover:background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.1); border-radius:20px; padding:4px 10px; font-size:0.70rem; color:#cbd5e1; cursor:pointer; white-space:nowrap; transition:all 0.15s ease;">
                ${escapeHtml(p)}
            </span>
        `).join('');
    }

    function formatMarkdown(text) {
        if (!text) return '';
        let s = escapeHtml(text);
        s = s.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        s = s.replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,0.4); padding:1px 4px; border-radius:4px; font-family:monospace; color:#38bdf8;">$1</code>');
        s = s.replace(/\n/g, '<br/>');
        return s;
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function escapeJson(obj) {
        if (!obj) return '{}';
        return JSON.stringify(obj).replace(/"/g, '&quot;');
    }

    // Global Keybindings: Ctrl + Space or Cmd + Space
    window.addEventListener('keydown', function (e) {
        if ((e.ctrlKey || e.metaKey) && e.code === 'Space') {
            e.preventDefault();
            toggleCopilot();
        }
    });

    // Enter Key to Submit Query
    document.addEventListener('DOMContentLoaded', function () {
        const inputEl = document.getElementById('copilotInput');
        if (inputEl) {
            inputEl.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    submitCopilotQuery();
                }
            });
        }
    });

})();
