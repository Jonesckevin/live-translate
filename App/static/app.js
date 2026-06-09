/**
 * Live Translate - Main Application
 * Single-page UI with merged Translate + Conversation and modal utilities
 */
(function () {
    'use strict';

    // ========================================================================
    // State
    // ========================================================================

    let appConfig = {};
    let socket = null;
    let currentSessionId = null;
    let currentSessionTitle = '';
    let currentSessionIconUrl = '';
    let providerModelPreferences = {};
    const convMessages = { left: [], right: [] };
    const convLiveState = {
        left: createLiveState(),
        right: createLiveState(),
    };
    const convSpeechInstances = { left: null, right: null };
    let socketConnectedOnce = false;
    let lastSocketConnectAt = 0;
    let userSettings = {};
    let serviceStatusTimer = null;
    let requiresInitialSessionSelection = true;

    // ========================================================================
    // Settings Management
    // ========================================================================

    async function loadSettings() {
        try {
            const res = await fetch('/api/settings');
            if (res.ok) {
                userSettings = await res.json();
                
                // Expose globally for api-manager.js and speech-manager.js
                window.userSettings = userSettings;
                window.updateSetting = updateSetting;
                window.saveSettings = saveSettings;
                
                // Load provider model preferences from settings
                providerModelPreferences = userSettings.provider_models || {};
                
                // Migrate from localStorage if needed
                const hasLocalStorage = localStorage.getItem('aiAutoCorrect') !== null ||
                                       localStorage.getItem('lt_api_key_priority') !== null;
                
                if (hasLocalStorage) {
                    await migrateLocalStorageSettings();
                }
                
                // Reload api manager with new settings
                if (window.llmAPIManager) {
                    window.llmAPIManager._loadFromSettings();
                }
                
                return userSettings;
            } else {
                userSettings = {
                    ai_auto_correct: true,
                    api_key_priority: 'client',
                    header_title: 'Live Translate',
                    header_logo_data_url: '',
                    api_keys: {},
                    provider_models: {},
                    translation_engine: 'libretranslate',
                    translation_provider: 'anthropic',
                    translation_model: '',
                    stt_engine: 'web_speech_api',
                    voice_mode: 'single',
                    playback_voices: [],
                };
                window.userSettings = userSettings;
                window.updateSetting = updateSetting;
                window.saveSettings = saveSettings;
                return userSettings;
            }
        } catch (e) {
            console.error('Failed to load settings', e);
            window.userSettings = userSettings;
            window.updateSetting = updateSetting;
            window.saveSettings = saveSettings;
            return userSettings;
        }
    }

    async function saveSettings(newSettings = null) {
        try {
            const settings = newSettings || userSettings;
            const res = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings),
            });
            if (res.ok) {
                const data = await res.json();
                userSettings = data.settings;
                return true;
            }
            return false;
        } catch (e) {
            console.error('Failed to save settings', e);
            return false;
        }
    }

    async function updateSetting(key, value) {
        userSettings[key] = value;
        return await saveSettings();
    }

    async function resetSettings() {
        if (!confirm('Are you sure you want to reset ALL settings to defaults? This will clear all your preferences, API keys, and voice settings.')) {
            return false;
        }
        
        try {
            const res = await fetch('/api/settings/reset', { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                userSettings = data.settings;
                
                // Clear localStorage as well
                localStorage.clear();
                
                // Reload the page to apply defaults
                showToast('Settings reset to defaults. Reloading...', 'success', 2000);
                setTimeout(() => window.location.reload(), 2000);
                return true;
            }
            return false;
        } catch (e) {
            console.error('Failed to reset settings', e);
            showToast('Failed to reset settings', 'error');
            return false;
        }
    }

    async function migrateLocalStorageSettings() {
        const oldSettings = {
            ai_auto_correct: localStorage.getItem('aiAutoCorrect') === 'true',
            api_key_priority: localStorage.getItem('lt_api_key_priority') || 'client',
            stt_engine: localStorage.getItem('lt_stt_engine') || 'web_speech_api',
            voice_mode: localStorage.getItem('lt_voice_mode') || 'single',
        };

        try {
            const apiKeys = JSON.parse(localStorage.getItem('lt_api_keys') || '{}');
            oldSettings.api_keys = apiKeys;
        } catch (e) {}

        try {
            const models = JSON.parse(localStorage.getItem('lt_provider_models') || '{}');
            oldSettings.provider_models = models;
        } catch (e) {}

        try {
            const voices = JSON.parse(localStorage.getItem('lt_playback_voices') || '[]');
            oldSettings.playback_voices = voices;
        } catch (e) {}

        await saveSettings({ ...userSettings, ...oldSettings });
        console.log('Migrated localStorage settings to server');
    }

    function getAIAutoCorrectSetting() {
        return userSettings.ai_auto_correct !== false;
    }

    function initHeaderCustomization() {
        const titleText = document.getElementById('appTitleText');
        const logoWrap = document.getElementById('appTitleLogoWrap');
        const logoInput = document.getElementById('appTitleLogoFile');
        const defaultLogo = document.getElementById('defaultTitleLogo');
        const customLogo = document.getElementById('customTitleLogo');
        const defaultTitle = 'Live Translate';

        if (!titleText || !logoWrap || !logoInput || !defaultLogo || !customLogo) return;

        applyHeaderTitle(userSettings.header_title || defaultTitle);
        applyHeaderLogo(userSettings.header_logo_data_url || '');

        titleText.addEventListener('dblclick', () => {
            beginHeaderTitleEdit(titleText, defaultTitle);
        });

        logoWrap.addEventListener('dblclick', () => {
            logoInput.click();
        });

        logoWrap.addEventListener('contextmenu', async (event) => {
            event.preventDefault();
            const hasCustomLogo = !!(userSettings.header_logo_data_url || '').trim();
            if (!hasCustomLogo) {
                showToast('Logo is already using the default LT SVG', 'info');
                return;
            }

            applyHeaderLogo('');
            const saved = await updateSetting('header_logo_data_url', '');
            showToast(saved ? 'Header logo reset to default' : 'Failed to reset header logo', saved ? 'success' : 'error');
        });

        logoWrap.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                logoInput.click();
            }
        });

        logoInput.addEventListener('change', async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;

            if (!file.type.startsWith('image/')) {
                showToast('Please choose an image file', 'warning');
                logoInput.value = '';
                return;
            }

            const reader = new FileReader();

            reader.onload = async () => {
                const dataUrl = String(reader.result || '');
                if (!dataUrl) {
                    showToast('Unable to load image file', 'error');
                    logoInput.value = '';
                    return;
                }

                applyHeaderLogo(dataUrl);
                const saved = await updateSetting('header_logo_data_url', dataUrl);
                showToast(saved ? 'Header logo updated' : 'Failed to save header logo', saved ? 'success' : 'error');
                logoInput.value = '';
            };

            reader.onerror = () => {
                showToast('Unable to read image file', 'error');
                logoInput.value = '';
            };

            reader.readAsDataURL(file);
        });
    }

    function applyHeaderTitle(value) {
        const titleText = document.getElementById('appTitleText');
        if (!titleText) return;
        titleText.textContent = String(value || '').trim() || 'Live Translate';
    }

    function applyHeaderLogo(dataUrl) {
        const defaultLogo = document.getElementById('defaultTitleLogo');
        const customLogo = document.getElementById('customTitleLogo');
        if (!defaultLogo || !customLogo) return;

        if (dataUrl) {
            customLogo.src = dataUrl;
            customLogo.style.display = 'block';
            defaultLogo.style.display = 'none';
        } else {
            customLogo.removeAttribute('src');
            customLogo.style.display = 'none';
            defaultLogo.style.display = 'block';
        }
    }

    function beginHeaderTitleEdit(element, defaultTitle) {
        if (!element || element.isContentEditable) return;

        const previousValue = (element.textContent || defaultTitle).trim();
        element.contentEditable = 'true';
        element.classList.add('is-editing');
        element.focus();

        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(element);
        range.collapse(false);
        selection.removeAllRanges();
        selection.addRange(range);

        const onBlur = () => {
            void commit();
        };

        const onKeyDown = (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                element.blur();
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                cancel();
            }
        };

        const cleanup = () => {
            element.contentEditable = 'false';
            element.classList.remove('is-editing');
            element.removeEventListener('blur', onBlur);
            element.removeEventListener('keydown', onKeyDown);
        };

        const commit = async () => {
            const normalized = (element.textContent || '').replace(/\s+/g, ' ').trim() || defaultTitle;
            element.textContent = normalized;
            cleanup();

            if (normalized !== previousValue) {
                const saved = await updateSetting('header_title', normalized);
                showToast(saved ? 'Header title updated' : 'Failed to save header title', saved ? 'success' : 'error');
            }
        };

        const cancel = () => {
            element.textContent = previousValue;
            cleanup();
        };

        element.addEventListener('blur', onBlur);
        element.addEventListener('keydown', onKeyDown);
    }

    // ========================================================================
    // Init
    // ========================================================================

    document.addEventListener('DOMContentLoaded', async () => {
        await loadConfig();
        await loadSettings();
        initHeaderCustomization();
        initSocket();
        initModals();
        renderAISettings(); // Initialize header auto-correct toggle
        initConversationTab();
        initSessionsTab();
        initSettingsTab();
        startServiceStatusMonitor();
    });

    async function loadConfig() {
        try {
            const res = await fetch('/api/config');
            appConfig = await res.json();
        } catch (e) {
            console.error('Failed to load config', e);
            appConfig = {};
        }
    }

    function initSocket() {
        socket = io({
            transports: ['websocket'],
            upgrade: false,
            rememberUpgrade: true,
            reconnection: true,
            reconnectionAttempts: Infinity,
            reconnectionDelay: 500,
            reconnectionDelayMax: 4000,
            timeout: 10000,
        });
        socket.on('connect', () => {
            socketConnectedOnce = true;
            lastSocketConnectAt = Date.now();
            const transport = socket?.io?.engine?.transport?.name || 'unknown';
            console.log(`Socket connected (${transport})`);
        });
        socket.on('disconnect', (reason) => {
            const sinceLastConnectMs = Date.now() - lastSocketConnectAt;
            const isLikelyTransient =
                reason === 'transport close' &&
                (sinceLastConnectMs < 3000 || document.visibilityState === 'hidden');

            if (isLikelyTransient) {
                console.debug('Socket transient disconnect:', reason);
                return;
            }

            console.warn('Socket disconnected:', reason);
        });
        socket.on('connect_error', (err) => {
            const message = err?.message || String(err);
            const isUpgradeProbe = /websocket error/i.test(message);
            const isStartupNoise = !socketConnectedOnce && /timeout/i.test(message);

            if (isUpgradeProbe || isStartupNoise) {
                console.debug('Socket probe/startup noise:', message);
                return;
            }

            console.warn('Socket connection error:', message);
        });
        socket.on('translation_result', handleSocketTranslation);
    }

    // ========================================================================
    // Modals
    // ========================================================================

    function initModals() {
        const sessionsBtn = document.getElementById('openSessionsModal');
        const settingsBtn = document.getElementById('openSettingsModal');
        const sessionsModal = document.getElementById('sessionsModal');
        const settingsModal = document.getElementById('settingsModal');
        const helpModal = document.getElementById('helpModal');
        const closeSessionsBtn = document.getElementById('closeSessionsModal');
        const closeSettingsBtn = document.getElementById('closeSettingsModal');
        const closeHelpBtn = document.getElementById('closeHelpModal');
        const helpModalTitle = document.getElementById('helpModalTitle');
        const helpModalContent = document.getElementById('helpModalContent');

        const helpContent = {
            conversation: {
                title: 'Conversation Help',
                html: '<p>Use Conversation to translate two speakers in real-time.</p><ul><li>Pick language for each side.</li><li>Set translation engine/provider/model in Settings.</li><li>Use mic buttons for speech or type in the input area.</li><li>Use New Session before long exchanges if you want history saved together.</li></ul>',
            },
            sessions: {
                title: 'Session History Help',
                html: '<p>Sessions store previous translated exchanges.</p><ul><li>Refresh to load latest saved sessions.</li><li>Open a session to review message history.</li><li>Export to plain text for sharing.</li><li>Delete sessions you no longer need.</li></ul>',
            },
            settings: {
                title: 'Settings Help',
                html: '<p>Settings controls translation defaults, AI providers, speech behavior, and glossary management.</p><ul><li>Choose translation engine/provider/model defaults.</li><li>Configure provider credentials and preferred models.</li><li>Choose STT engine and playback voice behavior.</li><li>Import glossaries to enforce preferred terminology.</li></ul>',
            },
            providers: {
                title: 'AI Providers Help',
                html: '<p>Each provider can use server key, user key, and a preferred model.</p><ul><li>Set API key priority globally.</li><li>Save key per provider (if required).</li><li>Test provider connectivity after saving key.</li><li>Load models and choose a preferred default.</li></ul>',
            },
            speech: {
                title: 'Speech Settings Help',
                html: '<p>Speech settings control recognition and playback output.</p><ul><li>Web Speech API is browser-based.</li><li>Whisper is server-based and better for offline use.</li><li>Choose voice mode and select one or more playback voices.</li></ul>',
            },
            glossaries: {
                title: 'Glossary Help',
                html: '<p>Glossaries keep translations consistent for domain terms, names, and phrases.</p><ul><li>Prepare a CSV/JSON/TSV/TXT glossary file.</li><li>Set source and target language pair.</li><li>Import and verify entry count.</li><li>Delete old glossaries when terminology changes.</li></ul>',
            },
        };

        const openModal = (modal) => {
            if (!modal) return;
            modal.classList.add('active');
            modal.setAttribute('aria-hidden', 'false');
            document.body.classList.add('modal-open');
        };

        const closeModal = (modal) => {
            if (!modal) return;
            modal.classList.remove('active');
            modal.setAttribute('aria-hidden', 'true');
            if (!document.querySelector('.app-modal.active')) {
                document.body.classList.remove('modal-open');
            }
        };

        const openHelpModal = (topic) => {
            const info = helpContent[topic];
            if (!info || !helpModal || !helpModalTitle || !helpModalContent) return;
            helpModalTitle.textContent = info.title;
            helpModalContent.innerHTML = info.html;
            openModal(helpModal);
        };

        sessionsBtn?.addEventListener('click', () => openModal(sessionsModal));
        settingsBtn?.addEventListener('click', () => openModal(settingsModal));
        closeSessionsBtn?.addEventListener('click', () => closeModal(sessionsModal));
        closeSettingsBtn?.addEventListener('click', () => closeModal(settingsModal));
        closeHelpBtn?.addEventListener('click', () => closeModal(helpModal));

        document.querySelectorAll('[data-help-topic]').forEach((btn) => {
            btn.addEventListener('click', () => {
                openHelpModal(btn.dataset.helpTopic);
            });
        });

        [sessionsModal, settingsModal, helpModal].forEach(modal => {
            modal?.addEventListener('click', (e) => {
                if (e.target === modal) closeModal(modal);
            });
        });

        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape') return;
            closeModal(sessionsModal);
            closeModal(settingsModal);
            closeModal(helpModal);
        });
    }

    // ========================================================================
    // Shared Select Setup
    // ========================================================================

    function populateLanguageSelects() {
        const languages = appConfig.translation?.available_languages || [
            { code: 'auto', name: 'Auto Detect', source_only: true },
            { code: 'en', name: 'English' },
            { code: 'fr', name: 'French' },
            { code: 'es', name: 'Spanish' },
            { code: 'de', name: 'German' },
        ];

        const selectors = ['convLeftLang', 'convRightLang'];
        for (const selId of selectors) {
            const sel = document.getElementById(selId);
            if (!sel) continue;
            sel.innerHTML = '';
            for (const lang of languages) {
                if (lang.source_only && (selId === 'convLeftLang' || selId === 'convRightLang')) continue;
                const opt = document.createElement('option');
                opt.value = lang.code;
                opt.textContent = lang.name;
                sel.appendChild(opt);
            }
            // Log language list loaded
            if (selId === 'convLeftLang') {
                const options = Array.from(sel.querySelectorAll('option')).map(o => `${o.value}:${o.textContent}`).join(', ');
                console.log(`[Languages] LEFT panel options: ${options}`);
            }
        }

        const leftLang = document.getElementById('convLeftLang');
        const rightLang = document.getElementById('convRightLang');
        if (leftLang) {
            leftLang.value = 'en';
            console.log(`[Languages] LEFT panel initialized to: ${leftLang.value} (${leftLang.options[leftLang.selectedIndex]?.text})`);
        }
        if (rightLang) {
            rightLang.value = 'fr';
            console.log(`[Languages] RIGHT panel initialized to: ${rightLang.value} (${rightLang.options[rightLang.selectedIndex]?.text})`);
        }
    }

    function populateProviderSelects() {
        const providers = appConfig.llm?.providers || {};
        const selects = ['convProvider'];
        for (const selId of selects) {
            const sel = document.getElementById(selId);
            if (!sel) continue;
            sel.innerHTML = '';
            for (const [id, prov] of Object.entries(providers)) {
                const opt = document.createElement('option');
                opt.value = id;
                opt.textContent = prov.name;
                sel.appendChild(opt);
            }
        }
    }

    async function fetchModelsForProvider(provider) {
        const headers = window.llmAPIManager ? window.llmAPIManager.getHeaders(provider) : { 'Content-Type': 'application/json' };

        try {
            const res = await fetch('/api/llm/models', {
                method: 'POST',
                headers,
                body: JSON.stringify({ provider }),
            });
            const data = await res.json();
            return {
                models: Array.isArray(data.models) ? data.models : [],
                error: data.error || '',
            };
        } catch (e) {
            return {
                models: [],
                error: e.message || 'Error loading models',
            };
        }
    }

    async function loadModels(provider, selectId, preferredModel = '') {
        const sel = document.getElementById(selectId);
        sel.innerHTML = '<option>Loading...</option>';

        const result = await fetchModelsForProvider(provider);
        sel.innerHTML = '';

        if (result.models.length > 0) {
            for (const m of result.models) {
                const opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m;
                sel.appendChild(opt);
            }

            const preferred = preferredModel || getProviderModelPreference(provider);
            if (preferred && result.models.includes(preferred)) {
                sel.value = preferred;
            }
            return result.models;
        }

        const preferred = preferredModel || getProviderModelPreference(provider);
        if (preferred) {
            sel.innerHTML = `<option value="${preferred}">${preferred} (saved)</option>`;
            sel.value = preferred;
        } else {
            sel.innerHTML = '<option value="">No models found</option>';
        }

        if (result.error) showToast(result.error, 'warning');
        return [];
    }

    // ========================================================================
    // Conversation Tab
    // ========================================================================

    function initConversationTab() {
        populateLanguageSelects();
        populateProviderSelects();

        const engineSel = document.getElementById('convEngine');
        const providerSel = document.getElementById('convProvider');
        const modelSel = document.getElementById('convModel');

        const syncTranslationControls = () => {
            const isLLM = engineSel.value === 'llm';
            document.querySelectorAll('.translation-llm-controls').forEach(el => {
                el.style.display = isLLM ? 'flex' : 'none';
            });
        };

        const providerOptions = Array.from(providerSel.options).map(opt => opt.value);
        const savedEngine = userSettings.translation_engine || 'libretranslate';
        const savedProvider = userSettings.translation_provider || providerOptions[0] || '';

        if (Array.from(engineSel.options).some(opt => opt.value === savedEngine)) {
            engineSel.value = savedEngine;
        }
        if (savedProvider && providerOptions.includes(savedProvider)) {
            providerSel.value = savedProvider;
        }

        syncTranslationControls();

        engineSel.addEventListener('change', () => {
            syncTranslationControls();
            void updateSetting('translation_engine', engineSel.value);
        });

        providerSel.addEventListener('change', async (e) => {
            const provider = e.target.value;
            await updateSetting('translation_provider', provider);
            await loadModels(provider, 'convModel', getProviderModelPreference(provider));
            if (modelSel.value) {
                await updateSetting('translation_model', modelSel.value);
            }
        });

        modelSel.addEventListener('change', (e) => {
            const provider = providerSel.value;
            if (provider && e.target.value) {
                saveProviderModelPreference(provider, e.target.value);
                void updateSetting('translation_model', e.target.value);
            }
        });

        // Send buttons
        document.getElementById('convLeftSend').addEventListener('click', () => {
            void sendConvMessage('left');
        });
        document.getElementById('convRightSend').addEventListener('click', () => {
            void sendConvMessage('right');
        });

        // Enter to send
        document.getElementById('convLeftInput').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void sendConvMessage('left');
            }
        });
        document.getElementById('convRightInput').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void sendConvMessage('right');
            }
        });

        // Mic buttons
        setupConvMic('left');
        setupConvMic('right');

        // TTS buttons
        setupConvTTS('left');
        setupConvTTS('right');

        // Populate microphone device dropdowns (requires permission; try now
        // and re-populate after the first getUserMedia grant).
        populateMicDeviceSelects();

        // New session
        document.getElementById('convNewSession').addEventListener('click', async () => {
            try {
                const suggestedName = `Conversation ${new Date().toLocaleString()}`;
                const requestedName = prompt('Enter a name for the new session', suggestedName);
                if (requestedName === null) {
                    return;
                }

                const trimmedName = requestedName.trim();
                if (!trimmedName) {
                    showToast('Session name is required', 'warning');
                    return;
                }

                await ensureConversationSession(true, trimmedName);
                convMessages.left = [];
                convMessages.right = [];
                document.getElementById('convLeftMessages').innerHTML = '';
                document.getElementById('convRightMessages').innerHTML = '';
                showToast('New conversation started', 'success');
            } catch (e) {
                showToast('Failed to create session', 'error');
            }
        });

        const initialProvider = providerSel.value;
        if (initialProvider) {
            const preferredModel = userSettings.translation_model || getProviderModelPreference(initialProvider);
            void loadModels(initialProvider, 'convModel', preferredModel).then(() => {
                if (modelSel.value) {
                    void updateSetting('translation_model', modelSel.value);
                }
            });
        }

    }

    async function ensureConversationSession(forceNew = false, requestedTitle = '') {
        if (currentSessionId && !forceNew) {
            return currentSessionId;
        }

        if (!forceNew) {
            const existingSessions = await fetchSessions();
            if (existingSessions.length > 0) {
                promptUserToSelectSession();
                throw new Error('Please select a session to open');
            }
        }

        const leftLang = document.getElementById('convLeftLang')?.value || 'en';
        const rightLang = document.getElementById('convRightLang')?.value || 'fr';
        const fallbackTitle = requestedTitle || `Conversation ${new Date().toLocaleString()}`;

        const res = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: fallbackTitle,
                type: 'conversation',
                languages: [leftLang, rightLang],
            }),
        });

        if (!res.ok) {
            throw new Error('Failed to create session');
        }

        const data = await res.json();
        currentSessionId = data.id;
        currentSessionTitle = data.title || fallbackTitle;
        currentSessionIconUrl = data.icon_url || '';
        requiresInitialSessionSelection = false;
        updateActiveSessionSummary();
        await loadSessions();
        return currentSessionId;
    }

    async function fetchSessions() {
        const res = await fetch('/api/sessions');
        if (!res.ok) {
            throw new Error('Failed to load sessions');
        }

        const data = await res.json();
        return Array.isArray(data.sessions) ? data.sessions : [];
    }

    function promptUserToSelectSession() {
        const sessionsBtn = document.getElementById('openSessionsModal');
        sessionsBtn?.click();
    }

    function setupConvMic(side) {
        const micBtn = document.getElementById(`conv${cap(side)}Mic`);
        const micStateEl = document.getElementById(`conv${cap(side)}MicState`);
        const statusEl = document.getElementById(`conv${cap(side)}MicStatus`);
        const deviceSelect = document.getElementById(`conv${cap(side)}MicDevice`);
        const speechInst = new SpeechManager();
        const state = convLiveState[side];
        convSpeechInstances[side] = speechInst;
        let pendingIdleTimer = null;

        setMicButtonState(micBtn, 'idle', 'Start speaking', micStateEl);

        micBtn.addEventListener('click', () => {
            if (speechInst.isListening) {
                speechInst.stop();
                setMicButtonState(micBtn, 'idle', 'Start speaking', micStateEl);
                statusEl.textContent = '';
            } else {
                const lang = document.getElementById(`conv${cap(side)}Lang`).value;
                const otherSide = side === 'left' ? 'right' : 'left';
                const otherInst = convSpeechInstances[otherSide];
                const engine = window.speechManager?.sttEngine || 'web_speech_api';

                // Web Speech API only allows ONE active recognition per tab.
                // Block activation if the other side is already active with Web Speech.
                if (engine === 'web_speech_api' && otherInst?.isListening && otherInst.sttEngine === 'web_speech_api') {
                    showToast(
                        'Browser speech recognition can only use one microphone at a time. ' +
                        'To enable both sides simultaneously, go to Settings → STT Engine → Whisper.',
                        'warning',
                        8000
                    );
                    return;
                }

                resetLiveState(side);
                speechInst.setDeviceId(deviceSelect ? deviceSelect.value : '');
                speechInst.onResult = (result) => {
                    if (result.interim) {
                        state.interimText = result.interim.trim();
                        const liveText = `${state.finalText} ${state.interimText}`.trim();
                        queueLiveConversationTranslate(side, liveText, false);
                    }

                    if (result.isFinal && result.final) {
                        const finalChunk = result.final.trim();
                        if (finalChunk) {
                            state.finalText = `${state.finalText} ${finalChunk}`.trim();
                            state.interimText = '';
                            queueLiveConversationTranslate(side, state.finalText, true);
                        }
                    }
                };
                speechInst.onStateChange = (state) => {
                    if (pendingIdleTimer) {
                        clearTimeout(pendingIdleTimer);
                        pendingIdleTimer = null;
                    }

                    if (state === 'listening') {
                        setMicButtonState(micBtn, 'active', 'Start speaking', micStateEl);
                        return;
                    }

                    if (state === 'processing') {
                        statusEl.textContent = 'Processing...';
                        setMicButtonState(micBtn, 'disabled', 'Start speaking', micStateEl);
                        return;
                    }

                    // Delay idle transition to avoid visual flicker during seamless auto-restart.
                    pendingIdleTimer = setTimeout(() => {
                        setMicButtonState(
                            micBtn,
                            speechInst.isListening ? 'active' : 'idle',
                            'Start speaking',
                            micStateEl
                        );
                    }, 220);
                    if (state === 'stopped') statusEl.textContent = '';
                };
                speechInst.onError = (msg) => {
                    if (pendingIdleTimer) {
                        clearTimeout(pendingIdleTimer);
                        pendingIdleTimer = null;
                    }
                    setMicButtonState(micBtn, 'idle', 'Start speaking', micStateEl);
                    showToast(msg, 'error');
                };
                speechInst.setEngine(window.speechManager?.sttEngine || 'web_speech_api');
                speechInst.start(lang);
            }
        });
    }

    function setupConvTTS(side) {
        const ttsBtn = document.getElementById(`conv${cap(side)}TTS`);
        if (!ttsBtn) return;

        ttsBtn.addEventListener('click', () => {
            const messagesContainer = document.getElementById(`conv${cap(side)}Messages`);
            if (!messagesContainer) return;

            // Get all message bubbles (conv-message), find the last message
            const bubbles = messagesContainer.querySelectorAll('.conv-message');
            if (bubbles.length === 0) {
                showToast('No messages to read', 'info');
                return;
            }

            // Get the last bubble's text (the most recent message)
            const lastBubble = bubbles[bubbles.length - 1];
            const msgText = lastBubble.querySelector('.msg-text')?.textContent?.trim();
            if (!msgText) {
                showToast('No message text to read', 'info');
                return;
            }

            // Get the language for this side
            const langSelect = document.getElementById(`conv${cap(side)}Lang`);
            const lang = langSelect ? langSelect.value : 'en';

            // Use SpeechManager to speak the text
            if (window.speechManager) {
                ttsBtn.classList.add('reading');
                ttsBtn.disabled = true;
                
                try {
                    window.speechManager.speak(msgText, lang);
                    
                    // Reset button after a reasonable time
                    setTimeout(() => {
                        ttsBtn.classList.remove('reading');
                        ttsBtn.disabled = false;
                    }, 5000);
                } catch (e) {
                    showToast(`TTS error: ${e.message}`, 'error');
                    ttsBtn.classList.remove('reading');
                    ttsBtn.disabled = false;
                }
            } else {
                showToast('Speech synthesis not available', 'error');
            }
        });
    }

    // =========================================================================
    // Mic device enumeration
    // =========================================================================

    async function populateMicDeviceSelects() {
        const selects = [
            document.getElementById('convLeftMicDevice'),
            document.getElementById('convRightMicDevice'),
        ].filter(Boolean);
        if (!selects.length) return;

        try {
            // enumerateDevices may return empty labels until permission is granted.
            // Request a brief stream to unlock labels if we haven't already.
            let devices = await navigator.mediaDevices.enumerateDevices();
            const hasLabels = devices.some(d => d.kind === 'audioinput' && d.label);
            if (!hasLabels) {
                try {
                    const s = await navigator.mediaDevices.getUserMedia({ audio: true });
                    s.getTracks().forEach(t => t.stop());
                    devices = await navigator.mediaDevices.enumerateDevices();
                } catch {
                    // Permission denied — leave selects with just "Default microphone"
                    return;
                }
            }

            const mics = devices.filter(d => d.kind === 'audioinput');
            selects.forEach(sel => {
                // Remember current selection
                const prev = sel.value;
                // Rebuild options
                sel.innerHTML = '<option value="">Default microphone</option>';
                mics.forEach((mic, i) => {
                    const opt = document.createElement('option');
                    opt.value = mic.deviceId;
                    opt.textContent = mic.label || `Microphone ${i + 1}`;
                    sel.appendChild(opt);
                });
                // Restore previous selection if still valid
                if (prev && sel.querySelector(`option[value="${CSS.escape(prev)}"]`)) {
                    sel.value = prev;
                }
            });
        } catch (err) {
            console.debug('Could not enumerate audio devices:', err);
        }
    }

    function createLiveState() {
        return {
            finalText: '',
            interimText: '',
            lastSentText: '',
            latestRequestId: 0,
            inFlightRequestId: 0,
            isInFlight: false,
            pendingPayload: null,
            debounceTimer: null,
            sourceBubble: null,
            targetBubble: null,
        };
    }

    function resetLiveState(side) {
        const state = convLiveState[side];
        if (state.debounceTimer) {
            clearTimeout(state.debounceTimer);
            state.debounceTimer = null;
        }
        state.finalText = '';
        state.interimText = '';
        state.lastSentText = '';
        state.latestRequestId = 0;
        state.inFlightRequestId = 0;
        state.isInFlight = false;
        state.pendingPayload = null;
        state.sourceBubble = null;
        state.targetBubble = null;
    }

    function queueLiveConversationTranslate(side, text, isFinal) {
        const cleanText = (text || '').trim();
        if (!cleanText) return;

        if (!isFinal && cleanText.length < 3) return;

        const state = convLiveState[side];
        if (cleanText === state.lastSentText && !isFinal) return;

        if (state.debounceTimer) {
            clearTimeout(state.debounceTimer);
            state.debounceTimer = null;
        }

        if (isFinal) {
            sendLiveConversationTranslate(side, cleanText, true);
            return;
        }

        state.debounceTimer = setTimeout(() => {
            sendLiveConversationTranslate(side, cleanText, false);
        }, 250);
    }

    function sendLiveConversationTranslate(side, text, isFinal) {
        const state = convLiveState[side];
        const otherSide = side === 'left' ? 'right' : 'left';

        if (state.isInFlight) {
            state.pendingPayload = { text, isFinal };
            return;
        }

        state.lastSentText = text;
        upsertLiveBubble(side, 'original', text, !isFinal, 'sourceBubble');
        const existingTargetText = state.targetBubble?.querySelector('.msg-text')?.textContent?.trim();
        const targetPlaceholder = existingTargetText && existingTargetText !== 'Translating...'
            ? existingTargetText
            : 'Translating...';
        upsertLiveBubble(otherSide, 'translated', targetPlaceholder, !isFinal, 'targetBubble', side, !isFinal);

        const srcLang = document.getElementById(`conv${cap(side)}Lang`).value;
        const tgtLang = document.getElementById(`conv${cap(otherSide)}Lang`).value;
        
        // Debug logging
        console.log(`[Translation] Panel: ${side} (typing here) | Source Lang: ${srcLang} | Target Lang: ${tgtLang} | Text: "${text}"`);
        const engine = document.getElementById('convEngine').value;
        const provider = document.getElementById('convProvider').value;
        const model = document.getElementById('convModel')?.value || getProviderModelPreference(provider);
        const apiKey = window.llmAPIManager ? window.llmAPIManager.getApiKey(provider) : '';
        const apiKeySource = window.llmAPIManager ? window.llmAPIManager.getApiKeyPriority() : 'client';

        const requestId = ++state.latestRequestId;
        state.inFlightRequestId = requestId;
        state.isInFlight = true;
        socket.emit('translate', {
            text,
            source_language: srcLang,
            target_language: tgtLang,
            engine,
            provider,
            model,
            panel: side,
            api_key: apiKey,
            api_key_source: apiKeySource,
            live_mode: true,
            interim: !isFinal,
            request_id: requestId,
            ai_auto_correct: getAIAutoCorrectSetting(),
        });

        if (isFinal && currentSessionId) {
            fetch(`/api/sessions/${currentSessionId}/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    source_text: text,
                    source_language: srcLang,
                    target_language: tgtLang,
                    panel: side,
                }),
            }).catch(() => { });
        }
    }

    function upsertLiveBubble(side, type, text, isLive, key, sourceSide, isTranslating) {
        const state = sourceSide ? convLiveState[sourceSide] : convLiveState[side];
        let bubble = state[key];
        const container = document.getElementById(`conv${cap(side)}Messages`);

        if (!bubble || !container.contains(bubble)) {
            bubble = createConvBubble(side, text, type, isLive);
            state[key] = bubble;
            return;
        }

        const body = bubble.querySelector('.msg-text');
        const currentText = body ? body.textContent : bubble.firstChild?.textContent;
        if (currentText !== text) {
            bubble.classList.add('updating');
            if (body) {
                body.textContent = text;
            } else {
                bubble.firstChild.textContent = text;
            }
            setTimeout(() => bubble.classList.remove('updating'), 160);
        }
        bubble.classList.toggle('live', !!isLive);
        bubble.classList.toggle('is-translating', !!isTranslating);
    }

    async function sendConvMessage(side) {
        const input = document.getElementById(`conv${cap(side)}Input`);
        const text = input.value.trim();
        if (!text) return;
        input.value = '';

        try {
            await ensureConversationSession();
        } catch (e) {
            if (!currentSessionId) {
                showToast('Please select a session to open first.', 'warning');
            } else {
                showToast('Failed to prepare session', 'error');
            }
            return;
        }

        const srcLang = document.getElementById(`conv${cap(side)}Lang`).value;
        const otherSide = side === 'left' ? 'right' : 'left';
        const tgtLang = document.getElementById(`conv${cap(otherSide)}Lang`).value;
        const engine = document.getElementById('convEngine').value;
        const provider = document.getElementById('convProvider').value;
        const model = document.getElementById('convModel')?.value || getProviderModelPreference(provider);

        // Show original message on sender side
        addConvBubble(side, text, 'original');

        // Translate via socket for real-time
        const apiKey = window.llmAPIManager ? window.llmAPIManager.getApiKey(provider) : '';
        const apiKeySource = window.llmAPIManager ? window.llmAPIManager.getApiKeyPriority() : 'client';
        socket.emit('translate', {
            text, source_language: srcLang, target_language: tgtLang,
            engine, provider, model, panel: side, api_key: apiKey, api_key_source: apiKeySource,
            ai_auto_correct: getAIAutoCorrectSetting(),
        });

        // Message will be saved to session when translation is received (via handleSocketTranslation)
    }

    function handleSocketTranslation(data) {
        const panel = data.panel || 'left';
        const otherSide = panel === 'left' ? 'right' : 'left';

        if (data.live_mode) {
            const state = convLiveState[panel];
            if (typeof data.request_id === 'number' && data.request_id < state.latestRequestId) {
                return;
            }

            let translatedText = data.success ? data.translated_text : `⚠ ${data.error}`;
            if (data.success && window.llmAPIManager) {
                translatedText = window.llmAPIManager.postProcessTranslation(translatedText);
            }

            upsertLiveBubble(
                otherSide,
                'translated',
                translatedText,
                !!data.interim,
                'targetBubble',
                panel,
                !!data.interim && !!data.success
            );

            if (!data.interim) {
                if (state.sourceBubble) state.sourceBubble.classList.remove('live');
                if (state.targetBubble) state.targetBubble.classList.remove('live');
                state.sourceBubble = null;
                state.targetBubble = null;
                state.finalText = '';
                state.interimText = '';
                state.lastSentText = '';
            }

            if (typeof data.request_id === 'number' && data.request_id === state.inFlightRequestId) {
                state.isInFlight = false;
                state.inFlightRequestId = 0;

                if (state.pendingPayload) {
                    const pending = state.pendingPayload;
                    state.pendingPayload = null;
                    sendLiveConversationTranslate(panel, pending.text, pending.isFinal);
                }
            }
            return;
        }

        if (data.success) {
            let translated = data.translated_text;
            if (window.llmAPIManager) {
                translated = window.llmAPIManager.postProcessTranslation(translated);
            }
            addConvBubble(otherSide, translated, 'translated');
            
            // Update session with complete translation (source + translation)
            if (currentSessionId) {
                const srcLang = document.getElementById(`conv${cap(panel)}Lang`)?.value || 'en';
                const tgtLang = document.getElementById(`conv${cap(otherSide)}Lang`)?.value || 'fr';
                fetch(`/api/sessions/${currentSessionId}/messages`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        source_text: data.original_text || '',
                        translated_text: translated,
                        source_language: srcLang,
                        target_language: tgtLang,
                        engine: data.engine || 'libretranslate',
                        panel: panel,
                    }),
                }).catch(() => { });
            }
        } else {
            addConvBubble(otherSide, `⚠ ${data.error}`, 'translated');
            
            // Save failed translation attempt for session history
            if (currentSessionId) {
                const srcLang = document.getElementById(`conv${cap(panel)}Lang`)?.value || 'en';
                const tgtLang = document.getElementById(`conv${cap(otherSide)}Lang`)?.value || 'fr';
                fetch(`/api/sessions/${currentSessionId}/messages`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        source_text: data.original_text || '',
                        translated_text: `Error: ${data.error || 'Translation failed'}`,
                        source_language: srcLang,
                        target_language: tgtLang,
                        engine: data.engine || 'libretranslate',
                        panel: panel,
                    }),
                }).catch(() => { });
            }
        }
    }

    function addConvBubble(side, text, type) {
        createConvBubble(side, text, type, false);
    }

    function createConvBubble(side, text, type, isLive) {
        const container = document.getElementById(`conv${cap(side)}Messages`);
        const bubble = document.createElement('div');
        bubble.className = `conv-message ${type}`;
        if (isLive) {
            bubble.classList.add('live');
        }

        const body = document.createElement('div');
        body.className = 'msg-text';
        body.textContent = text;

        const meta = document.createElement('div');
        meta.className = 'msg-meta';
        meta.textContent = new Date().toLocaleTimeString();
        bubble.appendChild(body);
        bubble.appendChild(meta);
        container.appendChild(bubble);
        container.scrollTop = container.scrollHeight;
        return bubble;
    }

    // ========================================================================
    // Sessions Tab
    // ========================================================================

    function initSessionsTab() {
        document.getElementById('refreshSessions').addEventListener('click', loadSessions);
        document.getElementById('viewActiveSession').addEventListener('click', async () => {
            if (!currentSessionId) return;
            await openSession(currentSessionId);
        });
        document.getElementById('sessionIdenticonImage').addEventListener('click', triggerSessionIconUpload);
        document.getElementById('sessionDetailIcon').addEventListener('click', triggerSessionIconUpload);
        document.getElementById('sessionIconFile').addEventListener('change', async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            await uploadCurrentSessionIcon(file);
            event.target.value = '';
        });
        initSessionIconDropTargets();
        document.getElementById('sessionBack').addEventListener('click', () => {
            document.getElementById('sessionDetail').style.display = 'none';
            document.getElementById('sessionsList').style.display = 'flex';
        });
        document.getElementById('renameSession').addEventListener('click', renameCurrentSession);
        document.getElementById('deleteSession').addEventListener('click', deleteCurrentSession);
        document.getElementById('exportSession').addEventListener('click', exportCurrentSession);
        void loadSessions().then(() => {
            void promptForInitialSessionSelection();
        });
    }

    async function promptForInitialSessionSelection() {
        if (!requiresInitialSessionSelection || currentSessionId) return;

        try {
            const sessions = await fetchSessions();
            if (sessions.length === 0) {
                await ensureConversationSession(true);
                return;
            }

            promptUserToSelectSession();
            showToast('Select which session to open before starting conversation.', 'info', 5000);
        } catch {
            showToast('Failed to load sessions for initial selection', 'error');
        }
    }

    async function loadSessions(existingSessions = null) {
        try {
            const sessions = existingSessions || await fetchSessions();
            const list = document.getElementById('sessionsList');
            updateActiveSessionSummary();

            if (!sessions || sessions.length === 0) {
                list.innerHTML = '<div class="empty-state">No sessions yet. Start translating to create a session.</div>';
                return;
            }

            list.innerHTML = '';
            for (const s of sessions) {
                const iconSrc = getSessionIconSrc(s.id, s.title, s.icon_url);
                const item = document.createElement('div');
                item.className = `session-item${s.id === currentSessionId ? ' active' : ''}`;
                item.dataset.sessionId = s.id;
                item.innerHTML = `
                    <div class="session-item-left">
                        <img class="session-identicon-image session-list-identicon" src="${escapeHtml(iconSrc)}" alt="Session icon" />
                    </div>
                    <div class="session-item-info">
                        <div class="session-item-line">
                            <span class="session-item-title">${escapeHtml(s.title)}</span>
                            <span class="session-item-desc">${s.type} · ${s.message_count} messages · ${s.languages.join(', ')}</span>
                        </div>
                    </div>
                    <div class="session-item-side">
                        <div class="session-item-meta">${formatDate(s.updated_at)}</div>
                        <div class="session-item-actions">
                            ${s.id === currentSessionId ? '<span class="session-active-badge">Active</span>' : `<button class="btn-secondary btn-session-use" type="button">Use</button>`}
                            <button class="btn-secondary btn-session-manage" type="button">Manage</button>
                        </div>
                    </div>
                `;
                const useBtn = item.querySelector('.btn-session-use');
                useBtn?.addEventListener('click', async (event) => {
                    event.stopPropagation();
                    activateSession(s.id, s.title, s.icon_url);
                    await restoreSessionMessages(s.id);
                    await loadSessions(sessions);
                    // Close using modal state classes so reopen works reliably.
                    const sessionsModal = document.getElementById('sessionsModal');
                    sessionsModal?.classList.remove('active');
                    sessionsModal?.setAttribute('aria-hidden', 'true');
                    if (!document.querySelector('.app-modal.active')) {
                        document.body.classList.remove('modal-open');
                    }
                    document.getElementById('conversationSection').scrollIntoView({ behavior: 'smooth' });
                    showToast(`Loaded: ${s.title}`, 'success');
                });
                item.querySelector('.btn-session-manage')?.addEventListener('click', async (event) => {
                    event.stopPropagation();
                    await openSession(s.id);
                });
                item.addEventListener('click', async () => {
                    activateSession(s.id, s.title, s.icon_url);
                    await restoreSessionMessages(s.id);
                    await loadSessions();
                });
                list.appendChild(item);
            }
        } catch (e) {
            showToast('Failed to load sessions', 'error');
        }
    }

    async function restoreSessionMessages(sessionId) {
        /**Load session messages into the active conversation interface.*/
        try {
            const res = await fetch(`/api/sessions/${sessionId}`);
            if (!res.ok) return;
            const data = await res.json();
            
            // Clear existing conversation messages
            convMessages.left = [];
            convMessages.right = [];
            document.getElementById('convLeftMessages').innerHTML = '';
            document.getElementById('convRightMessages').innerHTML = '';
            
            // Restore messages in order
            for (const msg of (data.messages || [])) {
                const side = msg.panel || 'left';
                const otherSide = side === 'left' ? 'right' : 'left';
                
                // Add source message on the sending side
                createConvBubble(side, msg.source_text || '', 'original', false);
                
                // Add translated message on the receiving side
                createConvBubble(otherSide, msg.translated_text || '', 'translated', false);
            }
        } catch (e) {
            console.error('Failed to restore session messages:', e);
        }
    }

    async function openSession(sessionId) {
        try {
            const res = await fetch(`/api/sessions/${sessionId}`);
            const data = await res.json();
            activateSession(sessionId, data.title || '', data.icon_url || '');

            document.getElementById('sessionsList').style.display = 'none';
            document.getElementById('sessionDetail').style.display = 'block';
            document.getElementById('sessionTitle').textContent = data.title;
            highlightActiveSession(sessionId);

            const container = document.getElementById('sessionMessages');
            container.innerHTML = '';

            for (const msg of (data.messages || [])) {
                const el = document.createElement('div');
                el.className = 'session-msg';
                el.innerHTML = `
                    <div class="source">${escapeHtml(msg.source_text || '')}</div>
                    <div class="translation">${escapeHtml(msg.translated_text || '')}</div>
                    <div class="meta">${msg.source_language} → ${msg.target_language} · ${msg.engine || ''} · ${formatDate(msg.timestamp)}</div>
                `;
                container.appendChild(el);
            }
        } catch (e) {
            showToast('Failed to load session', 'error');
        }
    }

    function activateSession(sessionId, sessionTitle, iconUrl = '') {
        currentSessionId = sessionId;
        currentSessionTitle = sessionTitle || '';
        currentSessionIconUrl = iconUrl || '';
        requiresInitialSessionSelection = false;
        highlightActiveSession(sessionId);
        updateActiveSessionSummary();
    }

    function updateActiveSessionSummary() {
        const summary = document.getElementById('activeSessionSummary');
        const manageBtn = document.getElementById('viewActiveSession');
        const title = currentSessionTitle || 'No session selected';

        updateConversationSessionTitle(title);
        updateSessionIconDisplays();

        if (!summary || !manageBtn) return;

        summary.textContent = title;
        manageBtn.disabled = !currentSessionId;
    }

    function updateConversationSessionTitle(title) {
        const heading = document.getElementById('conversationSessionTitle');
        if (!heading) return;
        heading.textContent = title || 'No session selected';
    }

    function highlightActiveSession(sessionId) {
        document.querySelectorAll('.session-item').forEach((item) => {
            item.classList.toggle('active', item.dataset.sessionId === sessionId);
        });
    }

    async function renameCurrentSession() {
        if (!currentSessionId) return;

        const currentTitle = currentSessionTitle || document.getElementById('sessionTitle').textContent || '';
        const nextTitle = prompt('Rename session', currentTitle)?.trim();
        if (!nextTitle || nextTitle === currentTitle) return;

        try {
            const res = await fetch(`/api/sessions/${currentSessionId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: nextTitle }),
            });

            if (!res.ok) {
                throw new Error('Failed to rename session');
            }

            const data = await res.json();
            currentSessionTitle = data.title || nextTitle;
            document.getElementById('sessionTitle').textContent = currentSessionTitle;
            updateActiveSessionSummary();
            await loadSessions();
            highlightActiveSession(currentSessionId);
            showToast('Session renamed', 'success');
        } catch (e) {
            showToast('Failed to rename session', 'error');
        }
    }

    async function deleteCurrentSession() {
        if (!currentSessionId) return;
        const title = currentSessionTitle || document.getElementById('sessionTitle').textContent || 'this session';
        const deleteDataAndImage = confirm(
            `Delete session "${title}" and its icon image?\n\nPress OK to delete both (default).`
        );
        if (!deleteDataAndImage) {
            const deleteDataOnly = confirm(
                `Delete session "${title}" only and keep its icon file for manual cleanup later?`
            );
            if (!deleteDataOnly) return;
        }

        try {
            const deletedId = currentSessionId;
            const res = await fetch(
                `/api/sessions/${deletedId}?delete_icon=${deleteDataAndImage ? 'true' : 'false'}`,
                { method: 'DELETE' }
            );
            if (!res.ok) {
                throw new Error('Failed to delete session');
            }

            document.getElementById('sessionDetail').style.display = 'none';
            document.getElementById('sessionsList').style.display = 'flex';
            currentSessionId = null;
            currentSessionTitle = '';
            currentSessionIconUrl = '';
            requiresInitialSessionSelection = true;
            updateActiveSessionSummary();
            await promptForInitialSessionSelection();
            await loadSessions();
            showToast('Session deleted', 'success');
        } catch (e) {
            showToast('Failed to delete session', 'error');
        }
    }

    function exportCurrentSession() {
        const msgs = document.getElementById('sessionMessages');
        const text = msgs.innerText;
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `session-${currentSessionId}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    }

    function triggerSessionIconUpload() {
        if (!currentSessionId) {
            showToast('Select a session before uploading an icon.', 'warning');
            return;
        }
        const input = document.getElementById('sessionIconFile');
        input?.click();
    }

    function initSessionIconDropTargets() {
        const targets = [
            document.getElementById('sessionIconControl'),
            document.getElementById('sessionIdenticonImage'),
            document.getElementById('sessionDetailIcon'),
        ].filter(Boolean);

        targets.forEach((target) => {
            target.classList.add('session-icon-drop-target');

            target.addEventListener('dragover', (event) => {
                event.preventDefault();
                target.classList.add('drag-over');
            });

            target.addEventListener('dragenter', (event) => {
                event.preventDefault();
                target.classList.add('drag-over');
            });

            target.addEventListener('dragleave', () => {
                target.classList.remove('drag-over');
            });

            target.addEventListener('drop', async (event) => {
                event.preventDefault();
                target.classList.remove('drag-over');
                const file = event.dataTransfer?.files?.[0];
                if (!file) return;
                await uploadCurrentSessionIcon(file);
            });
        });
    }

    async function uploadCurrentSessionIcon(file) {
        if (!currentSessionId) {
            showToast('Select a session before uploading an icon.', 'warning');
            return;
        }

        if (!isSupportedSessionIconFile(file)) {
            showToast('Unsupported format. Use PNG, SVG, JPG, or GIF.', 'error');
            return;
        }

        const normalizedFile = await normalizeSessionIconFile(file);
        const fileToUpload = normalizedFile || file;

        const form = new FormData();
        form.append('file', fileToUpload);

        try {
            const res = await fetch(`/api/sessions/${currentSessionId}/icon`, {
                method: 'POST',
                body: form,
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.error || 'Failed to upload icon');
            }

            const session = data.session || {};
            currentSessionTitle = session.title || currentSessionTitle;
            currentSessionIconUrl = session.icon_url || currentSessionIconUrl;

            updateActiveSessionSummary();
            await loadSessions();
            if (document.getElementById('sessionDetail').style.display !== 'none') {
                await openSession(currentSessionId);
            }
            showToast('Session icon updated', 'success');
        } catch (e) {
            showToast(`Failed to update session icon: ${e.message || 'Error'}`, 'error');
        }
    }

    function isSupportedSessionIconFile(file) {
        if (!file) return false;
        const lower = (file.name || '').toLowerCase();
        return ['.png', '.svg', '.jpg', '.jpeg', '.gif'].some((ext) => lower.endsWith(ext));
    }

    async function normalizeSessionIconFile(file) {
        const mime = (file.type || '').toLowerCase();
        const shouldKeepOriginal = mime === 'image/svg+xml';
        if (shouldKeepOriginal) {
            return file;
        }

        try {
            const image = await loadImageForCanvas(file);
            const size = 256;
            const sourceSize = Math.min(image.width, image.height);
            const sx = Math.max(0, (image.width - sourceSize) / 2);
            const sy = Math.max(0, (image.height - sourceSize) / 2);

            const canvas = document.createElement('canvas');
            canvas.width = size;
            canvas.height = size;
            const ctx = canvas.getContext('2d');
            if (!ctx) {
                return file;
            }

            ctx.imageSmoothingEnabled = true;
            ctx.imageSmoothingQuality = 'high';
            ctx.clearRect(0, 0, size, size);
            ctx.drawImage(image, sx, sy, sourceSize, sourceSize, 0, 0, size, size);

            const blob = await new Promise((resolve) => {
                canvas.toBlob((result) => resolve(result), 'image/png', 0.92);
            });
            if (!blob) {
                return file;
            }

            const baseName = (file.name || 'session-icon').replace(/\.[^.]+$/, '');
            return new File([blob], `${baseName}.png`, {
                type: 'image/png',
                lastModified: Date.now(),
            });
        } catch {
            return file;
        }
    }

    async function loadImageForCanvas(file) {
        if ('createImageBitmap' in window) {
            return await createImageBitmap(file);
        }

        return await new Promise((resolve, reject) => {
            const url = URL.createObjectURL(file);
            const img = new Image();
            img.onload = () => {
                URL.revokeObjectURL(url);
                resolve(img);
            };
            img.onerror = () => {
                URL.revokeObjectURL(url);
                reject(new Error('Image decode failed'));
            };
            img.src = url;
        });
    }

    function getSessionIconSrc(sessionId, title, iconUrl = '') {
        if (iconUrl) {
            const cacheBuster = `cb=${Date.now()}`;
            return iconUrl.includes('?') ? `${iconUrl}&${cacheBuster}` : `${iconUrl}?${cacheBuster}`;
        }
        return buildIdenticonDataUri(sessionId || title || 'session');
    }

    function updateSessionIconDisplays() {
        const title = currentSessionTitle || 'No session selected';
        const iconSrc = getSessionIconSrc(currentSessionId || 'none', title, currentSessionIconUrl);

        const conversationIcon = document.getElementById('sessionIdenticonImage');
        if (conversationIcon) {
            conversationIcon.src = iconSrc;
            conversationIcon.alt = `${title} icon`;
        }

        const detailIcon = document.getElementById('sessionDetailIcon');
        if (detailIcon) {
            detailIcon.src = iconSrc;
            detailIcon.alt = `${title} icon`;
        }
    }

    function buildIdenticonDataUri(seed) {
        const value = String(seed || 'session');
        const hash = hashString(value);
        const hue = hash % 360;
        const accentHue = (hue + 36) % 360;
        const cells = [];
        const bitSeed = hashString(`${value}:cells`);

        for (let row = 0; row < 5; row += 1) {
            for (let col = 0; col < 3; col += 1) {
                const bitIndex = row * 3 + col;
                if (((bitSeed >> bitIndex) & 1) === 1) {
                    cells.push([col, row]);
                    if (col !== 2) {
                        cells.push([4 - col, row]);
                    }
                }
            }
        }

        const rects = cells
            .map(([x, y]) => `<rect x="${x * 12 + 8}" y="${y * 12 + 8}" width="10" height="10" rx="2"/>`)
            .join('');

        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="76" height="76" viewBox="0 0 76 76" role="img" aria-label="Session identicon"><defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="hsl(${hue} 72% 58%)"/><stop offset="100%" stop-color="hsl(${accentHue} 70% 45%)"/></linearGradient></defs><rect width="76" height="76" rx="16" fill="hsl(${hue} 20% 14%)"/><g fill="url(#g)">${rects}</g></svg>`;
        return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
    }

    function hashString(input) {
        let hash = 0;
        for (let i = 0; i < input.length; i += 1) {
            hash = ((hash << 5) - hash) + input.charCodeAt(i);
            hash |= 0;
        }
        return Math.abs(hash || 1);
    }

    // ========================================================================
    // Settings Tab
    // ========================================================================

    function initSettingsTab() {
        renderApiPrioritySettings();
        renderProviderConfigList();
        renderSpeechSettings();
        initGlossaryImport();
        loadGlossaries();
        initResetButton();
    }

    function initResetButton() {
        const resetBtn = document.getElementById('resetSettingsBtn');
        if (!resetBtn) return;

        resetBtn.addEventListener('click', async () => {
            await resetSettings();
        });
    }

    function renderAISettings() {
        const autoCorrectCheckbox = document.getElementById('aiAutoCorrectHeader');
        if (!autoCorrectCheckbox) return;

        // Load from userSettings
        autoCorrectCheckbox.checked = getAIAutoCorrectSetting();

        // Save on change
        autoCorrectCheckbox.addEventListener('change', async () => {
            await updateSetting('ai_auto_correct', autoCorrectCheckbox.checked);
            showToast(
                `AI Auto-Correct: ${autoCorrectCheckbox.checked ? 'Enabled' : 'Disabled'}`,
                'success'
            );
        });
    }

    function renderApiPrioritySettings() {
        const prioritySel = document.getElementById('apiKeyPriority');
        if (!prioritySel || !window.llmAPIManager) return;

        prioritySel.value = window.llmAPIManager.getApiKeyPriority();
        prioritySel.addEventListener('change', () => {
            window.llmAPIManager.setApiKeyPriority(prioritySel.value);
            showToast(
                `API key priority: ${prioritySel.value === 'server' ? 'Server first' : 'User first'}`,
                'success'
            );
        });
    }

    function renderProviderConfigList() {
        const container = document.getElementById('providerConfigList');
        const providers = appConfig.llm?.providers || {};
        const serverKeys = appConfig.server_api_keys || {};
        container.innerHTML = '';

        for (const [id, prov] of Object.entries(providers)) {
            const serverAvail = serverKeys[id]?.available;
            const clientKey = window.llmAPIManager?.getApiKey(id) || '';
            const preferredModel = getProviderModelPreference(id);
            const requiresKey = !!prov.requires_key;

            const item = document.createElement('div');
            item.className = 'provider-config-item';
            item.innerHTML = `
                <div class="provider-config-row">
                    <div class="provider-label-line">
                        <span class="provider-name">${prov.name}</span>
                        <span class="provider-type ${requiresKey ? 'tag-cloud' : 'tag-local'}">${requiresKey ? 'Cloud' : 'Local'}</span>
                        ${requiresKey ? `<span class="key-status ${serverAvail ? 'tag-active' : 'tag-inactive'}">${serverAvail ? 'Server key' : 'No server key'}</span>` : '<span class="key-status tag-neutral">No key</span>'}
                    </div>
                    <div class="provider-input-wrap">
                        ${requiresKey ? `<input type="password" placeholder="API Key" value="${clientKey}" data-provider="${id}">` : '<span class="provider-no-key">Local provider</span>'}
                    </div>
                    <div class="provider-model-wrap">
                        <select class="provider-model-select" data-provider="${id}">
                            <option value="">${preferredModel ? `${preferredModel} (saved)` : 'Preferred model'}</option>
                        </select>
                        <button class="btn-secondary load-provider-models" data-provider="${id}" title="Refresh Models">🔄</button>
                    </div>
                    <div class="provider-actions">
                        ${requiresKey ? `<button class="btn-secondary save-key" data-provider="${id}">Save</button>` : ''}
                        <button class="btn-secondary test-provider" data-provider="${id}">Test</button>
                        <span class="provider-status" id="provStatus_${id}">—</span>
                    </div>
                </div>
            `;
            container.appendChild(item);
        }

        container.querySelectorAll('.test-provider').forEach(btn => {
            btn.addEventListener('click', async () => {
                const prov = btn.dataset.provider;
                const statusEl = document.getElementById(`provStatus_${prov}`);
                statusEl.textContent = 'Testing...';
                statusEl.className = 'provider-status';
                statusEl.title = '';

                const headers = window.llmAPIManager ? window.llmAPIManager.getHeaders(prov) : { 'Content-Type': 'application/json' };
                try {
                    const res = await fetch('/api/llm/test', {
                        method: 'POST', headers,
                        body: JSON.stringify({ provider: prov }),
                    });
                    const data = await res.json();
                    if (data.connected) {
                        statusEl.textContent = 'Connected';
                        statusEl.className = 'provider-status connected';
                    } else {
                        const normalized = summarizeProviderError(data.error || 'Failed');
                        statusEl.textContent = normalized.short;
                        statusEl.className = 'provider-status disconnected';
                        statusEl.title = normalized.full;
                    }
                } catch (err) {
                    const normalized = summarizeProviderError(err?.message || 'Error');
                    statusEl.textContent = normalized.short;
                    statusEl.className = 'provider-status disconnected';
                    statusEl.title = normalized.full;
                }
            });
        });

        container.querySelectorAll('.save-key').forEach(btn => {
            btn.addEventListener('click', () => {
                const prov = btn.dataset.provider;
                const input = container.querySelector(`input[data-provider="${prov}"]`);
                if (!input) return;
                if (input.value) {
                    window.llmAPIManager.saveApiKey(prov, input.value);
                    showToast(`${prov} key saved`, 'success');
                } else {
                    window.llmAPIManager.removeApiKey(prov);
                    showToast(`${prov} key removed`, 'info');
                }
            });
        });

        container.querySelectorAll('.provider-model-select').forEach(sel => {
            const provider = sel.dataset.provider;
            const preferred = getProviderModelPreference(provider);
            if (preferred) {
                sel.innerHTML = '';
                const opt = document.createElement('option');
                opt.value = preferred;
                opt.textContent = preferred;
                sel.appendChild(opt);
                sel.value = preferred;
            }

            sel.addEventListener('change', () => {
                if (sel.value) {
                    saveProviderModelPreference(provider, sel.value);
                    showToast(`${provider} model set to ${sel.value}`, 'success');
                }
            });
        });

        container.querySelectorAll('.load-provider-models').forEach(btn => {
            btn.addEventListener('click', async () => {
                const provider = btn.dataset.provider;
                const sel = container.querySelector(`.provider-model-select[data-provider="${provider}"]`);
                if (!sel) return;

                const previousText = btn.textContent;
                btn.textContent = 'Loading...';
                btn.disabled = true;

                const result = await fetchModelsForProvider(provider);
                sel.innerHTML = '';

                if (result.models.length > 0) {
                    for (const model of result.models) {
                        const opt = document.createElement('option');
                        opt.value = model;
                        opt.textContent = model;
                        sel.appendChild(opt);
                    }

                    const preferred = getProviderModelPreference(provider);
                    if (preferred && result.models.includes(preferred)) {
                        sel.value = preferred;
                    }
                } else {
                    const preferred = getProviderModelPreference(provider);
                    const opt = document.createElement('option');
                    opt.value = preferred || '';
                    opt.textContent = preferred ? `${preferred} (saved)` : 'No models found';
                    sel.appendChild(opt);
                    if (result.error) showToast(result.error, 'warning');
                }

                btn.textContent = previousText;
                btn.disabled = false;
            });
        });
    }

    function renderSpeechSettings() {
        const sttSel = document.getElementById('sttEngine');
        const whisperInfo = document.getElementById('whisperInfo');
        const whisperModelRow = document.getElementById('whisperModelRow');
        const whisperModelSel = document.getElementById('whisperModel');
        const sttProviderRow = document.getElementById('sttProviderRow');
        const sttProviderSel = document.getElementById('sttProvider');
        const sttModelRow = document.getElementById('sttModelRow');
        const sttModelSel = document.getElementById('sttModel');
        const sttProviderInfo = document.getElementById('sttProviderInfo');
        const voiceModeSel = document.getElementById('voiceMode');
        const playbackVoicesSel = document.getElementById('playbackVoices');

        const sttSettings = window.speechManager?.getSTTSettings?.() || {
            engine: 'web_speech_api',
            provider: 'groq',
            model: '',
            whisperModel: (window.userSettings?.whisper_model || appConfig.speech?.whisper_model || 'base'),
        };

        const whisperModels = ['tiny', 'base', 'small', 'medium', 'large-v3'];

        if (whisperModelSel) {
            whisperModelSel.innerHTML = '';
            for (const model of whisperModels) {
                const opt = document.createElement('option');
                opt.value = model;
                opt.textContent = model;
                whisperModelSel.appendChild(opt);
            }

            const defaultWhisperModel = sttSettings.whisperModel || appConfig.speech?.whisper_model || 'base';
            whisperModelSel.value = whisperModels.includes(defaultWhisperModel) ? defaultWhisperModel : 'base';
        }

        sttSel.value = sttSettings.engine;

        const sttProviders = Object.entries(appConfig.llm?.providers || {})
            .filter(([, provider]) => provider.stt_supported);

        async function loadSTTModelsForProvider(providerId, preferredModel = '') {
            if (!sttModelSel) return;

            sttModelSel.innerHTML = '<option>Loading...</option>';
            const headers = window.llmAPIManager
                ? window.llmAPIManager.getHeaders(providerId)
                : { 'Content-Type': 'application/json' };

            try {
                const res = await fetch('/api/stt/models', {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ provider: providerId }),
                });
                const data = await res.json();
                const models = Array.isArray(data.models) ? data.models : [];
                sttModelSel.innerHTML = '';

                if (models.length === 0) {
                    sttModelSel.innerHTML = '<option value="">No STT models found</option>';
                    if (data.error) {
                        sttProviderInfo.style.display = 'block';
                        sttProviderInfo.innerHTML = `<p style="color: var(--warning);">${escapeHtml(data.error)}</p>`;
                    }
                    return;
                }

                for (const model of models) {
                    const opt = document.createElement('option');
                    opt.value = model;
                    opt.textContent = model;
                    sttModelSel.appendChild(opt);
                }

                const configuredDefault = appConfig.llm?.providers?.[providerId]?.stt_default_model || '';
                const nextModel = preferredModel || configuredDefault || models[0];
                if (models.includes(nextModel)) {
                    sttModelSel.value = nextModel;
                } else {
                    sttModelSel.value = models[0];
                }

                await window.speechManager?.setSTTModel(sttModelSel.value);
                sttProviderInfo.style.display = 'block';
                sttProviderInfo.innerHTML = '<p style="color: var(--success);">Provider STT will send recorded audio to the selected AI provider.</p>';
            } catch (e) {
                sttModelSel.innerHTML = '<option value="">Failed to load models</option>';
                sttProviderInfo.style.display = 'block';
                sttProviderInfo.innerHTML = `<p style="color: var(--warning);">${escapeHtml(e.message || 'Failed to load STT models')}</p>`;
            }
        }

        function syncSTTProviderVisibility() {
            const useProviderSTT = sttSel.value === 'ai_provider';
            const useWhisperSTT = sttSel.value === 'whisper';
            if (whisperModelRow) whisperModelRow.style.display = useWhisperSTT ? 'flex' : 'none';
            if (sttProviderRow) sttProviderRow.style.display = useProviderSTT ? 'flex' : 'none';
            if (sttModelRow) sttModelRow.style.display = useProviderSTT ? 'flex' : 'none';
            if (sttProviderInfo) sttProviderInfo.style.display = useProviderSTT ? 'block' : 'none';
        }

        if (sttProviderSel) {
            sttProviderSel.innerHTML = '';
            for (const [id, provider] of sttProviders) {
                const opt = document.createElement('option');
                opt.value = id;
                opt.textContent = provider.name;
                sttProviderSel.appendChild(opt);
            }

            if (sttProviders.length > 0) {
                const providerIds = sttProviders.map(([id]) => id);
                sttProviderSel.value = providerIds.includes(sttSettings.provider) ? sttSettings.provider : providerIds[0];
            }
        }

        if (appConfig.features?.whisper_enabled) {
            whisperInfo.innerHTML = '<p style="color: var(--success);">Whisper is available on this server.</p>';
        } else {
            whisperInfo.innerHTML = '<p style="color: var(--text-muted);">Whisper not enabled. Set WHISPER_ENABLED=true to activate.</p>';
            // Disable whisper option
            const whisperOpt = sttSel.querySelector('option[value="whisper"]');
            if (whisperOpt) whisperOpt.disabled = true;
        }

        syncSTTProviderVisibility();

        sttSel.addEventListener('change', async () => {
            if (window.speechManager) {
                await window.speechManager.setEngine(sttSel.value);
            }
            syncSTTProviderVisibility();
            if (sttSel.value === 'ai_provider' && sttProviderSel?.value) {
                await loadSTTModelsForProvider(sttProviderSel.value, window.speechManager?.getSTTSettings?.().model || '');
            }
        });

        sttProviderSel?.addEventListener('change', async () => {
            if (!window.speechManager) return;
            await window.speechManager.setSTTProvider(sttProviderSel.value);
            await loadSTTModelsForProvider(sttProviderSel.value, '');
        });

        sttModelSel?.addEventListener('change', async () => {
            if (!window.speechManager) return;
            await window.speechManager.setSTTModel(sttModelSel.value);
            showToast(`STT model set to ${sttModelSel.value}`, 'success');
        });

        whisperModelSel?.addEventListener('change', async () => {
            if (!window.speechManager) return;
            await window.speechManager.setWhisperModel(whisperModelSel.value);
            showToast(`Whisper model set to ${whisperModelSel.value}`, 'success');
        });

        if (sttSel.value === 'ai_provider' && sttProviderSel?.value) {
            void loadSTTModelsForProvider(sttProviderSel.value, sttSettings.model || '');
        }

        if (window.speechManager && voiceModeSel && playbackVoicesSel) {
            const availableVoices = window.speechManager.getAvailableVoices();
            const settings = window.speechManager.getPlaybackSettings();

            playbackVoicesSel.innerHTML = '';
            for (const voice of availableVoices) {
                const opt = document.createElement('option');
                opt.value = voice.id;
                opt.textContent = `${voice.name} (${voice.lang})${voice.default ? ' [Default]' : ''}`;
                if (settings.voiceIds.includes(voice.id)) {
                    opt.selected = true;
                }
                playbackVoicesSel.appendChild(opt);
            }

            voiceModeSel.value = settings.mode || 'single';

            voiceModeSel.addEventListener('change', () => {
                window.speechManager.setVoiceMode(voiceModeSel.value);
                showToast('Playback voice mode updated', 'success');
            });

            playbackVoicesSel.addEventListener('change', () => {
                const selected = Array.from(playbackVoicesSel.selectedOptions).map(opt => opt.value);
                window.speechManager.setPlaybackVoices(selected);
                showToast(`Selected ${selected.length} playback voice(s)`, 'success');
            });
        }
    }

    async function loadGlossaries() {
        try {
            const res = await fetch('/api/glossaries');
            const data = await res.json();
            const container = document.getElementById('glossaryList');
            container.innerHTML = '';

            if (!data.glossaries || data.glossaries.length === 0) {
                container.innerHTML = '<div class="empty-state" style="padding: 1rem; text-align: center; color: var(--text-muted);">No glossaries yet. Import one to get started.</div>';
                return;
            }

            for (const g of data.glossaries) {
                const item = document.createElement('div');
                item.className = 'glossary-item';
                item.innerHTML = `
                    <div class="glossary-item-info">
                        <div class="glossary-item-name">${escapeHtml(g.name)}</div>
                        <div class="glossary-item-meta">${g.source_language} → ${g.target_language} · ${g.entry_count} ${g.entry_count === 1 ? 'entry' : 'entries'}</div>
                    </div>
                    <div class="glossary-item-actions">
                        <button class="btn-danger glossary-delete-btn" data-id="${g.id}">🗑️ Delete</button>
                    </div>
                `;
                item.querySelector('.btn-danger').addEventListener('click', async () => {
                    if (confirm(`Delete glossary "${g.name}"?`)) {
                        await fetch(`/api/glossaries/${g.id}`, { method: 'DELETE' });
                        loadGlossaries();
                    }
                });
                container.appendChild(item);
            }
        } catch (e) {
            console.error('Failed to load glossaries', e);
        }
    }

    function initGlossaryImport() {
        const downloadBtn = document.getElementById('downloadGlossaryTemplate');
        const fileInput = document.getElementById('glossaryFile');
        const srcInput = document.getElementById('glossarySourceLang');
        const tgtInput = document.getElementById('glossaryTargetLang');
        if (downloadBtn) {
            downloadBtn.addEventListener('click', downloadGlossaryTemplate);
        }

        const triggerImportOnEnter = (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                void importGlossaryFromFile();
            }
        };

        [srcInput, tgtInput].forEach((input) => {
            input?.addEventListener('keydown', triggerImportOnEnter);
        });

        fileInput?.addEventListener('change', async () => {
            autoFillGlossaryLanguagePair();
            if (fileInput.files?.[0]) {
                await importGlossaryFromFile();
            }
        });
    }

    function autoFillGlossaryLanguagePair() {
        const srcInput = document.getElementById('glossarySourceLang');
        const tgtInput = document.getElementById('glossaryTargetLang');
        const leftLang = (document.getElementById('convLeftLang')?.value || '').trim();
        const rightLang = (document.getElementById('convRightLang')?.value || '').trim();

        if (srcInput && !srcInput.value.trim() && leftLang) {
            srcInput.value = leftLang;
        }
        if (tgtInput && !tgtInput.value.trim() && rightLang) {
            tgtInput.value = rightLang;
        }
    }

    async function downloadGlossaryTemplate() {
        const formatSel = document.getElementById('glossaryTemplateFormat');
        const format = formatSel?.value || 'csv';

        try {
            const res = await fetch(`/api/glossaries/template?format=${encodeURIComponent(format)}`);
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                throw new Error(data.error || 'Failed to download template');
            }

            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `glossary-template.${format}`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            showToast('Template downloaded', 'success');
        } catch (e) {
            showToast(`Failed to download template: ${e.message || 'Error'}`, 'error');
        }
    }

    async function importGlossaryFromFile() {
        const srcInput = document.getElementById('glossarySourceLang');
        const tgtInput = document.getElementById('glossaryTargetLang');
        const fileInput = document.getElementById('glossaryFile');
        const file = fileInput?.files?.[0];

        if (!file) {
            showToast('Select a glossary file first', 'error');
            return;
        }

        autoFillGlossaryLanguagePair();

        try {
            const form = new FormData();
            form.append('file', file);
            form.append('source_language', (srcInput?.value || '').trim());
            form.append('target_language', (tgtInput?.value || '').trim());

            const res = await fetch('/api/glossaries/import', {
                method: 'POST',
                body: form,
            });

            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.error || 'Import failed');
            }

            if (srcInput) srcInput.value = '';
            if (tgtInput) tgtInput.value = '';
            if (fileInput) fileInput.value = '';

            loadGlossaries();
            showToast(`Glossary imported (${data.entry_count || 0} entries)`, 'success');
        } catch (e) {
            showToast(`Failed to import glossary: ${e.message || 'Error'}`, 'error');
        }
    }

    // ========================================================================
    // Status Checks
    // ========================================================================

    function setServiceLoadingBanner(visible, message = '') {
        const banner = document.getElementById('serviceLoadingBanner');
        const text = document.getElementById('serviceLoadingText');
        if (!banner || !text) return;

        if (visible) {
            text.textContent = message || 'Services are still loading...';
            banner.style.display = 'flex';
            return;
        }

        banner.style.display = 'none';
    }

    async function startServiceStatusMonitor() {
        const startedAt = Date.now();

        const checkLoop = async () => {
            const status = await checkStatuses();
            const ready = status.socketConnected && status.libreAvailable;

            if (ready) {
                setServiceLoadingBanner(false);
                serviceStatusTimer = null;
                return;
            }

            const waitedSec = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
            const socketText = status.socketConnected ? 'connected' : 'connecting';
            const libreText = status.libreAvailable ? 'ready' : 'starting';
            const whisperText = status.whisperReachable
                ? (status.whisperEnabled ? 'enabled' : 'disabled')
                : 'checking';

            setServiceLoadingBanner(
                true,
                `Services are still loading (${waitedSec}s). Socket: ${socketText} · LibreTranslate: ${libreText} · Whisper: ${whisperText}`
            );

            serviceStatusTimer = setTimeout(checkLoop, 1500);
        };

        if (serviceStatusTimer) {
            clearTimeout(serviceStatusTimer);
            serviceStatusTimer = null;
        }
        await checkLoop();
    }

    async function checkStatuses() {
        const status = {
            socketConnected: !!socket?.connected,
            offlineKnown: false,
            offline: false,
            libreAvailable: false,
            whisperEnabled: false,
            whisperReachable: false,
        };

        // Offline Mode
        try {
            const res = await fetch('/api/offline-status');
            const data = await res.json();
            const indicator = document.getElementById('offlineIndicator');
            status.offlineKnown = true;
            status.offline = !!data.offline;
            if (data.offline) {
                indicator.style.display = 'inline-block';
                indicator.title = 'Running in offline mode - Using Whisper STT and local services only';
            } else {
                indicator.style.display = 'none';
            }
        } catch {
            // If we can't check, assume online
            document.getElementById('offlineIndicator').style.display = 'none';
        }

        // LibreTranslate
        try {
            const res = await fetch('/api/libretranslate/status');
            const data = await res.json();
            const dot = document.getElementById('libreStatus');
            status.libreAvailable = !!data.available;
            dot.className = data.available ? 'status-dot online' : 'status-dot offline';
            dot.title = data.available ? 'LibreTranslate: Online' : `LibreTranslate: ${data.error || 'Offline'}`;
        } catch {
            document.getElementById('libreStatus').className = 'status-dot offline';
        }

        // Whisper
        try {
            const res = await fetch('/api/whisper/status');
            const data = await res.json();
            const dot = document.getElementById('whisperStatus');
            status.whisperReachable = true;
            status.whisperEnabled = !!data.enabled;
            if (data.enabled) {
                dot.className = 'status-dot online';
                dot.title = `Whisper: Enabled (${data.model})`;
            } else {
                dot.className = 'status-dot';
                dot.title = 'Whisper: Disabled';
            }
        } catch {
            document.getElementById('whisperStatus').className = 'status-dot';
        }

        return status;
    }

    // ========================================================================
    // Utilities
    // ========================================================================

    function showToast(message, type = 'info', duration = 4000) {
        const container = document.getElementById('toastContainer');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), duration);
    }

    function setMicButtonState(button, state, label, stateBadge) {
        if (!button) return;

        const nextState = state || 'idle';
        const baseLabel = label || 'Start speaking';

        button.dataset.state = nextState;
        button.classList.toggle('active', nextState === 'active');
        button.classList.toggle('recording', nextState === 'active');
        button.setAttribute('aria-pressed', nextState === 'active' ? 'true' : 'false');

        if (stateBadge) {
            stateBadge.classList.toggle('active', nextState === 'active');
            stateBadge.classList.toggle('disabled', nextState === 'disabled');
            stateBadge.textContent =
                nextState === 'active' ? 'Active' : (nextState === 'disabled' ? 'Disabled' : 'Not active');
        }

        if (nextState === 'disabled') {
            button.disabled = true;
            button.title = `${baseLabel} (Disabled)`;
            return;
        }

        button.disabled = false;
        button.title = `${baseLabel} (${nextState === 'active' ? 'Active' : 'Not active'})`;
    }

    function summarizeProviderError(message) {
        const full = String(message || 'Error');
        const lower = full.toLowerCase();

        if (lower.includes('connection refused') || lower.includes('failed to establish a new connection')) {
            return { short: 'Connection refused', full };
        }
        if (lower.includes('timeout')) {
            return { short: 'Timeout', full };
        }
        if (lower.includes('401') || lower.includes('unauthorized') || lower.includes('api key')) {
            return { short: 'Auth error', full };
        }
        if (lower.includes('404') || lower.includes('not found')) {
            return { short: 'Not found', full };
        }
        if (lower.includes('429') || lower.includes('rate')) {
            return { short: 'Rate limited', full };
        }

        if (full.length > 28) {
            return { short: `${full.slice(0, 25)}...`, full };
        }
        return { short: full, full };
    }

    async function saveProviderModelPreference(provider, model) {
        providerModelPreferences[provider] = model;
        await updateSetting('provider_models', providerModelPreferences);
        syncProviderModelToMainSelectors(provider, model);
    }

    function getProviderModelPreference(provider) {
        return providerModelPreferences[provider]
            || appConfig.llm?.providers?.[provider]?.default_model
            || '';
    }

    function syncProviderModelToMainSelectors(provider, model) {
        const convProvider = document.getElementById('convProvider');
        const convModel = document.getElementById('convModel');

        if (convProvider && convModel && convProvider.value === provider) {
            ensureSelectHasOption(convModel, model);
            convModel.value = model;
        }
    }

    function ensureSelectHasOption(selectEl, value) {
        if (!value) return;
        if (Array.from(selectEl.options).some(opt => opt.value === value)) return;
        const opt = document.createElement('option');
        opt.value = value;
        opt.textContent = value;
        selectEl.appendChild(opt);
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function formatDate(iso) {
        if (!iso) return '';
        try {
            return new Date(iso).toLocaleString();
        } catch { return iso; }
    }

    function cap(str) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }

})();
