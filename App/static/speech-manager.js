
(function () {
    'use strict';

    class SpeechManager {
        constructor() {
            this.sttEngine = 'web_speech_api';
            this.recognition = null;
            this.isListening = false;
            this._manualStop = false;
            this._restartWebSpeech = false;
            this._webSpeechLanguage = 'en-US';
            this._webSpeechRestartTimer = null;
            this._networkRetryTimer = null;
            this._networkRetryPending = false;
            this._deviceId = '';
            this._primingStream = null;
            this._primingDeviceId = '';
            this._isAutoRestarting = false;
            this.mediaRecorder = null;
            this.audioChunks = [];
            this.onResult = null;
            this.onError = null;
            this.onStateChange = null;
            this.offlineMode = false;
            this.offlineStatus = null;
            this._offlineCheckComplete = false;
            this.speechMode = 'standard';

            this.webSpeechSupported = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
            this.synthesis = window.speechSynthesis || null;
            this.voiceMode = 'single';
            this.playbackVoiceIds = [];
            this.voiceIndex = 0;
            this.sttProvider = 'groq';
            this.sttModel = '';
            this.whisperModel = 'base';
            
            this._loadFromSettings();

            // The engine the user chose is kept intact (sttPreference); these
            // track the engine actually in use. They diverge once the browser
            // engine has been abandoned for the local one, which is a
            // per-session override and never rewrites the stored preference.
            this.sttPreference = this.sttEngine;
            this._engineFallback = false;
            this._whisperAvail = null;
            this._startLanguage = 'en';
            // Non-error feedback (e.g. the automatic switch to the local
            // engine). Wired to a toast by app.js; optional.
            this.onNotice = null;

            // On-device (offline) recognition - Chromium 138+ / Edge expose
            // processLocally, SpeechRecognition.available() and .install().
            this._onDeviceProbe = null;
            this._onDeviceProbeLang = '';
            this._onDeviceInstalling = false;
            this._onDeviceInstallPromise = null;
            this._onDeviceActive = false;
            // Serialises start attempts. A click, an auto-restart and a network
            // retry can all be in flight at once, and two live recognitions
            // would fight over the microphone (audible as stop/start stutter).
            this._startToken = 0;
            this._resumeTimes = [];
            
            
            this._checkOfflineStatus().catch(e => {
                this._offlineCheckComplete = true;
            });

            if (this.synthesis && this.synthesis.onvoiceschanged !== undefined) {
                this.synthesis.onvoiceschanged = () => {
                    this._ensureValidPlaybackVoices();
                };
            }
        }

        async _checkOfflineStatus() {
            try {
                const response = await fetch('/api/offline-status');
                if (response.ok) {
                    this.offlineStatus = await response.json();
                    this.offlineMode = !!this.offlineStatus.offline;
                    this._whisperAvail = !!this.offlineStatus.whisper_available;
                    this.speechMode = window.userSettings?.speech_mode || 'standard';
                    
                    
                } else {
                }
            } catch (e) {
                
            } finally {
                this._offlineCheckComplete = true;
            }
        }

        _loadFromSettings() {
            if (window.userSettings) {
                this.sttEngine = window.userSettings.stt_engine || 'web_speech_api';
                this.sttProvider = window.userSettings.stt_provider || 'groq';
                this.sttModel = window.userSettings.stt_model || '';
                this.whisperModel = window.userSettings.whisper_model || 'base';
                this.voiceMode = window.userSettings.voice_mode || 'single';
                this.playbackVoiceIds = window.userSettings.playback_voices || [];
                this.speechMode = window.userSettings.speech_mode || 'standard';
            } else {
                
                this.sttEngine = localStorage.getItem('lt_stt_engine') || 'web_speech_api';
                this.sttProvider = localStorage.getItem('lt_stt_provider') || 'groq';
                this.sttModel = localStorage.getItem('lt_stt_model') || '';
                this.whisperModel = localStorage.getItem('lt_whisper_model') || 'base';
                this.voiceMode = localStorage.getItem('lt_voice_mode') || 'single';
                this.speechMode = localStorage.getItem('lt_speech_mode') || 'standard';
                try {
                    const raw = localStorage.getItem('lt_playback_voices');
                    this.playbackVoiceIds = raw ? JSON.parse(raw) : [];
                } catch {
                    this.playbackVoiceIds = [];
                }
            }
        }

        async _saveToSettings() {
            if (window.updateSetting) {
                await window.updateSetting('voice_mode', this.voiceMode);
                await window.updateSetting('playback_voices', this.playbackVoiceIds);
            }
        }

        async setSTTProvider(provider) {
            this.sttProvider = provider || 'groq';
            if (window.updateSetting) {
                await window.updateSetting('stt_provider', this.sttProvider);
            }
        }

        async setSTTModel(model) {
            this.sttModel = model || '';
            if (window.updateSetting) {
                await window.updateSetting('stt_model', this.sttModel);
            }
        }

        async setWhisperModel(model) {
            this.whisperModel = model || 'base';
            if (window.updateSetting) {
                await window.updateSetting('whisper_model', this.whisperModel);
            }
        }

        getSTTSettings() {
            return {
                engine: this.sttEngine,
                provider: this.sttProvider,
                model: this.sttModel,
                whisperModel: this.whisperModel,
            };
        }

        async _ensureValidPlaybackVoices() {
            const voiceMap = new Map(this.getAvailableVoices().map(v => [v.id, v]));
            this.playbackVoiceIds = this.playbackVoiceIds.filter(id => voiceMap.has(id));
            await this._saveToSettings();
        }

        async setVoiceMode(mode) {
            const allowed = ['single', 'alternate', 'random'];
            this.voiceMode = allowed.includes(mode) ? mode : 'single';
            await this._saveToSettings();
        }

        async setPlaybackVoices(voiceIds) {
            this.playbackVoiceIds = Array.isArray(voiceIds) ? voiceIds : [];
            await this._ensureValidPlaybackVoices();
        }

        getPlaybackSettings() {
            return {
                mode: this.voiceMode,
                voiceIds: [...this.playbackVoiceIds],
            };
        }

        getAvailableVoices() {
            if (!this.synthesis) return [];
            const voices = this.synthesis.getVoices() || [];
            return voices.map(v => ({
                id: v.voiceURI,
                name: v.name,
                lang: v.lang,
                default: v.default,
            }));
        }

        
        
        setDeviceId(deviceId) {
            const nextDeviceId = deviceId || '';
            if (this._deviceId === nextDeviceId) return;
            this._deviceId = nextDeviceId;

            
            if (this._primingStream && this._primingDeviceId !== nextDeviceId) {
                this._releasePrimingStream();
            }
        }

        _releasePrimingStream() {
            if (this._primingStream) {
                this._primingStream.getTracks().forEach(t => t.stop());
                this._primingStream = null;
            }
            this._primingDeviceId = '';
        }

        async setEngine(engine) {
            const next = engine || 'web_speech_api';
            // app.js re-applies the stored preference before every start, so
            // only a genuine change counts as the user picking an engine - and
            // only that clears an active local-engine fallback.
            const preferenceChanged = next !== this.sttPreference;
            this.sttPreference = next;
            if (preferenceChanged) {
                this._engineFallback = false;
            }
            this.sttEngine = (this._engineFallback && next === 'web_speech_api') ? 'whisper' : next;

            if (this.isListening) {
                this.stop();
            }

            if (preferenceChanged && window.updateSetting) {
                await window.updateSetting('stt_engine', this.sttPreference);
            }
        }

        /** True while the browser engine has been swapped for the local one. */
        get fallbackActive() {
            return this._engineFallback;
        }

        start(language = 'en') {
            try {
                this._startLanguage = language || 'en';

                if (this.sttEngine === 'web_speech_api') {
                    // _startWebSpeech() picks between the browser's on-device
                    // recogniser, its cloud service and the server-side engine.
                    return this._startWebSpeech(language);
                } else if (this.sttEngine === 'whisper' || this.sttEngine === 'ai_provider') {
                    return this._startWhisperRecording(language);
                } else {
                    this._emitError('Unknown STT engine: ' + this.sttEngine);
                }
            } catch (e) {
                console.error('[SpeechManager] Start failed:', e);
                this._emitError('Failed to start speech recognition: ' + e.message);
            }
        }

        /** 'en-US' / 'EN' -> 'en'. 'auto' is passed through for Whisper. */
        _toIsoCode(code) {
            const value = String(code || '').trim();
            if (!value || value === 'auto') return 'auto';
            return value.split('-')[0].toLowerCase();
        }

        /** Whether this browser can recognise speech without its cloud service. */
        _onDeviceSupported() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            return !!(SpeechRecognition &&
                'processLocally' in SpeechRecognition.prototype &&
                typeof SpeechRecognition.available === 'function');
        }

        /**
         * Ask the browser whether `lang` can be recognised on-device:
         * 'available' (installed), 'downloadable', 'downloading' or
         * 'unavailable'. Probes are cached per language and time-bounded, so an
         * unresponsive implementation cannot stall the microphone.
         */
        async _resolveOnDeviceAvailability(lang) {
            if (!this._onDeviceSupported()) return 'unavailable';
            if (this._onDeviceProbeLang === lang && this._onDeviceProbe) {
                return this._onDeviceProbe;
            }

            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            let state = 'unavailable';
            try {
                state = await Promise.race([
                    SpeechRecognition.available({ langs: [lang], processLocally: true }),
                    new Promise((resolve) => setTimeout(() => resolve('unavailable'), 1500)),
                ]) || 'unavailable';
            } catch (e) {
                state = 'unavailable';
            }

            this._onDeviceProbe = state;
            this._onDeviceProbeLang = lang;
            return state;
        }

        /**
         * UI helper: describe on-device support for a language so Settings can
         * tell the user whether "Browser" recognition works without internet.
         */
        async describeOnDeviceSupport(language) {
            const bcp47 = this._mapLanguageCode(language || 'en');
            if (!this._onDeviceSupported()) {
                return { supported: false, state: 'unavailable', lang: bcp47 };
            }
            const state = await this._resolveOnDeviceAvailability(bcp47);
            return { supported: true, state, lang: bcp47 };
        }

        /**
         * Probe the browser's on-device model ahead of time. `available()` needs
         * no user activation, and having the answer cached is what lets a later
         * microphone click call install() *synchronously* - Chromium rejects it
         * from a non-gesture context while the pack is 'downloadable', which is
         * the first-run state on Chrome and Edge.
         */
        primeOnDeviceAvailability(language) {
            if (!this._onDeviceSupported()) return Promise.resolve('unavailable');
            return this._resolveOnDeviceAvailability(this._mapLanguageCode(language || this._startLanguage));
        }

        /**
         * Wait (bounded) for an in-progress on-device download to finish.
         */
        async _awaitOnDeviceReady(lang, budgetMs = 8000) {
            const deadline = Date.now() + budgetMs;
            for (;;) {
                const state = await this._resolveOnDeviceAvailability(lang);
                if (state === 'available') return true;
                if (state !== 'downloading' || Date.now() >= deadline) return false;
                await new Promise((resolve) => setTimeout(resolve, 500));
            }
        }

        /**
         * Download the on-device language pack (once per language). Chromium
         * requires transient user activation, so this must be reached from a
         * click without an intervening await (see _startWebSpeech).
         */
        async _installOnDevicePack(lang) {
            // A download already running is shared rather than duplicated.
            if (this._onDeviceInstallPromise) return this._onDeviceInstallPromise;

            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition || typeof SpeechRecognition.install !== 'function') return false;

            this._onDeviceInstalling = true;
            this._emitNotice(
                `Downloading the on-device speech model for ${this._toIsoCode(lang)}. ` +
                'After this one-time download, browser speech works without internet.',
                'info'
            );

            this._onDeviceInstallPromise = (async () => {
                try {
                    const installed = await SpeechRecognition.install({ langs: [lang], processLocally: true });
                    this._onDeviceProbe = installed ? 'available' : 'unavailable';
                    this._onDeviceProbeLang = lang;
                    return !!installed;
                } catch (e) {
                    // NotAllowedError = the gesture was gone; the next click can
                    // retry now that the state is cached.
                    console.warn('[SpeechManager] On-device model install failed:', e);
                    this._onDeviceProbe = 'downloadable';
                    this._onDeviceProbeLang = lang;
                    return false;
                } finally {
                    this._onDeviceInstalling = false;
                    this._onDeviceInstallPromise = null;
                }
            })();

            return this._onDeviceInstallPromise;
        }

        /**
         * Whether to bypass the browser engine for the server-side one.
         *
         * An on-device recogniser works offline, so it always wins; otherwise
         * only a *completed* offline probe is trusted (until it lands, the
         * browser engine is attempted and the network-error handler falls back
         * reactively, which keeps the common online path instant).
         */
        _prefersLocalEngine(onDeviceUsable) {
            if (this._engineFallback) return true;
            if (onDeviceUsable) return false;
            return !!(this._offlineCheckComplete && this.offlineMode && this._whisperAvail === true);
        }

        /**
         * Resolve whether the server can transcribe locally. The offline probe
         * usually answers this at startup; otherwise ask /api/whisper/status.
         */
        async _resolveWhisperAvailability() {
            if (this._whisperAvail === null) {
                try {
                    const response = await fetch('/api/whisper/status');
                    if (response.ok) {
                        const data = await response.json();
                        this._whisperAvail = !!data.enabled;
                    }
                } catch (e) {
                    // Leave it unknown; the caller keeps retrying the browser engine.
                }
            }
            return this._whisperAvail === true;
        }

        /**
         * Swap the browser engine for the local one for the rest of the
         * session. The stored preference is deliberately left alone so the
         * browser engine can be used again once its service is reachable.
         */
        _startLocalEngine(language, notice) {
            this._engineFallback = true;
            this._abandonWebSpeech();
            this.sttEngine = 'whisper';
            if (notice) this._emitNotice(notice, 'warning');
            // Whisper wants an ISO-639-1 code; Web Speech hands us BCP-47.
            return this._startWhisperRecording(this._toIsoCode(language || this._startLanguage));
        }

        /**
         * Drop the current recognition without emitting errors or state
         * changes: its handlers are detached first so the trailing onend/onerror
         * cannot restart it or report a spurious "stopped".
         */
        _abandonWebSpeech() {
            this._restartWebSpeech = false;
            this._isAutoRestarting = false;
            this._networkRetryPending = false;
            if (this._webSpeechRestartTimer) {
                clearTimeout(this._webSpeechRestartTimer);
                this._webSpeechRestartTimer = null;
            }
            if (this._networkRetryTimer) {
                clearTimeout(this._networkRetryTimer);
                this._networkRetryTimer = null;
            }

            this._startToken++;          // invalidate any in-flight start attempt
            this._teardownRecognition();
            this.isListening = false;
            this._releasePrimingStream();
        }

        /** Back off and retry the browser engine (no local engine available). */
        _scheduleNetworkRetry(count) {
            const backoffMs = count <= 3 ? 2000 : Math.min(count * 3000, 20000);

            if (count >= 3) {
                this._emitError('Speech recognition is having trouble reaching the network. Retrying\u2026');
            }
            // Use a dedicated timer so the onend restart (which fires right
            // after) does not overwrite this backoff and cause duplicate
            // recognition.start() calls.
            this._isAutoRestarting = true;
            this._networkRetryPending = true;
            if (this._networkRetryTimer) clearTimeout(this._networkRetryTimer);
            this._networkRetryTimer = setTimeout(() => {
                this._networkRetryPending = false;
                this._networkRetryTimer = null;
                if (!this._manualStop && this.sttEngine === 'web_speech_api') {
                    // Same reasoning as the onend resume: the engine is already
                    // decided, so skip the probe and restart straight away.
                    this._startWebSpeech(this._webSpeechLanguage, { resume: true });
                }
            }, backoffMs);
        }

        stop() {
            try {
                if (this.sttEngine === 'web_speech_api') {
                    this._stopWebSpeech();
                } else if (this.sttEngine === 'whisper' || this.sttEngine === 'ai_provider') {
                    this._stopWhisperRecording();
                }
            } catch (e) {
                console.error('[SpeechManager] Stop failed:', e);
            }
        }

        

        async _startWebSpeech(language, options = {}) {
            if (!this.webSpeechSupported) {
                this._emitError('Web Speech API not supported in this browser');
                return;
            }

            
            if (this.recognition && this.isListening && !this._isAutoRestarting) {
                this._stopWebSpeech();
            }

            const token = ++this._startToken;

            this._manualStop = false;
            this._restartWebSpeech = true;
            // NOTE: _networkRetryCount is intentionally NOT reset here so that
            // network-error backoff can escalate; it resets on a successful
            // result (see onresult).
            this._webSpeechLanguage = this._mapLanguageCode(language);
            if (this._webSpeechRestartTimer) {
                clearTimeout(this._webSpeechRestartTimer);
                this._webSpeechRestartTimer = null;
            }
            if (this._networkRetryTimer) {
                clearTimeout(this._networkRetryTimer);
                this._networkRetryTimer = null;
            }
            this._networkRetryPending = false;

            // A fresh user-initiated start deserves a clean flapping budget.
            if (!options.resume) this._resumeTimes = [];

            // Resuming after the browser ended a session (silence timeout): the
            // engine was already chosen, so re-probing - or worse, waiting on a
            // model download - would drop seconds of audio. Restart immediately.
            if (options.resume) {
                this._createAndStartRecognition(this._onDeviceActive, token);
                return;
            }

            // Prefer the browser's own on-device recogniser: that is the only
            // way this engine works without internet access. Its language pack
            // usually has to be downloaded once (Chromium/Edge expose install()).
            let useOnDevice = false;
            if (this._onDeviceSupported()) {
                const cached = this._onDeviceProbeLang === this._webSpeechLanguage
                    ? this._onDeviceProbe
                    : null;

                // Start the download *before* the first await: install() only
                // works while the click's user activation is still live.
                const pendingInstall = cached === 'downloadable'
                    ? this._installOnDevicePack(this._webSpeechLanguage)
                    : null;

                if (cached === 'available') {
                    useOnDevice = true;
                } else if (cached === 'downloading') {
                    useOnDevice = await this._awaitOnDeviceReady(this._webSpeechLanguage);
                } else if (pendingInstall) {
                    useOnDevice = await pendingInstall;
                } else if (cached === null) {
                    const state = await this._resolveOnDeviceAvailability(this._webSpeechLanguage);
                    if (state === 'available') {
                        useOnDevice = true;
                    } else if (state === 'downloadable' || state === 'downloading') {
                        useOnDevice = await this._installOnDevicePack(this._webSpeechLanguage);
                        if (!useOnDevice) {
                            this._emitNotice(
                                'The on-device speech model still needs downloading - ' +
                                'press the microphone once more to fetch it (this attempt used the online engine).',
                                'info'
                            );
                        }
                    }
                }
            }

            // A stop() - or a newer start attempt - that landed while the
            // probe/install was in flight wins.
            if (this._manualStop || token !== this._startToken) return;

            // Without an on-device pack this engine needs its vendor's cloud
            // service, which an offline deployment cannot reach - prefer the
            // local engine there instead of failing first.
            if (this._prefersLocalEngine(useOnDevice)) {
                const notice = this._engineFallback
                    ? null
                    : 'Offline: using the server-side Whisper engine for speech recognition.';
                return this._startLocalEngine(language || this._startLanguage, notice);
            }

            this._onDeviceActive = useOnDevice;

            const primeAndStart = () => {
                this._createAndStartRecognition(this._onDeviceActive, token);
            };

            const hasActivePrimingStream = this._primingStream &&
                this._primingDeviceId === this._deviceId &&
                this._primingStream.getAudioTracks().some(t => t.readyState === 'live');

            if (this._deviceId && !hasActivePrimingStream) {
                navigator.mediaDevices.getUserMedia({
                    audio: { deviceId: { exact: this._deviceId } },
                }).then(stream => {
                    if (token !== this._startToken || this._manualStop) {
                        stream.getTracks().forEach(t => t.stop());
                        return;
                    }
                    this._primingStream = stream;
                    this._primingDeviceId = this._deviceId;
                    primeAndStart();
                }).catch(err => {
                    
                    primeAndStart();
                });
            } else {
                primeAndStart();
            }
        }

        /**
         * Track how often the browser engine restarts itself. A recogniser that
         * ends immediately, over and over, is broken (pack missing, service
         * blocked) and hammering it produces exactly the on/off stutter users
         * notice - so give up and say so instead of flapping.
         */
        _noteResumeAttempt() {
            const now = Date.now();
            this._resumeTimes = (this._resumeTimes || []).filter(t => now - t < 10000);
            this._resumeTimes.push(now);
            if (this._resumeTimes.length > 8) {
                this._resumeTimes = [];
                this._restartWebSpeech = false;
                this.isListening = false;
                this._emitError('Browser speech keeps stopping. Try another STT Engine in Settings, or check the microphone.');
                this._emitStateChange('stopped');
                return false;
            }
            return true;
        }

        /**
         * Detach and abort the live recognition, if any. Two recognitions must
         * never run at once: each opens its own capture of the microphone, and
         * the overlapping sessions are heard as stuttering input.
         */
        _teardownRecognition() {
            const recognition = this.recognition;
            this.recognition = null;
            if (!recognition) return;
            recognition.onstart = null;
            recognition.onresult = null;
            recognition.onerror = null;
            recognition.onend = null;
            try { recognition.abort(); } catch (e) { /* already stopped */ }
        }

        /**
         * Create the recognition and start it. `token` guards against a newer
         * attempt (or a stop) having superseded this one while an await was in
         * flight.
         */
        _createAndStartRecognition(useOnDevice, token) {
            if (token !== undefined && (token !== this._startToken || this._manualStop)) return;

            this._teardownRecognition();
            try {
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                this.recognition = new SpeechRecognition();
                this.recognition.continuous = true;
                this.recognition.interimResults = true;
                this.recognition.maxAlternatives = 1;
                this.recognition.lang = this._webSpeechLanguage;
                if (this._onDeviceSupported()) {
                    // Set in both directions: the browser default is cloud.
                    try {
                        this.recognition.processLocally = useOnDevice;
                    } catch (e) { /* older builds reject the assignment */ }
                }
                this._attachRecognitionHandlers();
                this.recognition.start();
            } catch (e) {
                console.error('[SpeechManager] Recognition start failed:', e);
                this._emitError(`Failed to start: ${e.message}`);
            }
        }

        _attachRecognitionHandlers() {
            this.recognition.onstart = () => {
                this.isListening = true;
                
                if (!this._isAutoRestarting) {
                    this._emitStateChange('listening');
                }
                this._isAutoRestarting = false;
            };

            this.recognition.onresult = (event) => {
                
                this._networkRetryCount = 0;
                // Real audio arrived: this session is healthy, so forget past
                // restart attempts (see _noteResumeAttempt).
                this._resumeTimes = [];
                
                let interim = '';
                let final = '';
                for (let i = event.resultIndex; i < event.results.length; i++) {
                    const transcript = event.results[i][0].transcript;
                    if (event.results[i].isFinal) {
                        final += transcript;
                    } else {
                        interim += transcript;
                    }
                }
                
                if (this.onResult) {
                    this.onResult({ final, interim, isFinal: !!final });
                }
            };

            this.recognition.onerror = (event) => {
                if (event.error === 'no-speech') {
                    
                    return;
                }

                if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
                    this._restartWebSpeech = false;
                    this._isAutoRestarting = false;
                    this._emitError('Microphone permission was denied. Please allow microphone access for this site.');
                    return;
                }

                if (event.error === 'network') {
                    this._networkRetryCount = (this._networkRetryCount || 0) + 1;
                    const count = this._networkRetryCount;

                    // Retrying a dead service is pointless when this deployment
                    // can transcribe locally, so switch engines instead. Only
                    // fall back to grey-zone retrying if Whisper is unavailable.
                    if (!this._engineFallback && !this._manualStop) {
                        this._resolveWhisperAvailability().then((available) => {
                            if (this._manualStop || this._engineFallback) return;
                            if (available) {
                                this._startLocalEngine(
                                    this._startLanguage,
                                    'Browser speech cannot reach its online service. Switched to the ' +
                                    'server-side Whisper engine, which works offline. Change this in ' +
                                    'Settings \u2192 STT Engine.'
                                );
                            } else {
                                this._scheduleNetworkRetry(count);
                            }
                        }).catch(() => this._scheduleNetworkRetry(count));
                        return;
                    }

                    this._scheduleNetworkRetry(count);
                    return;
                }

                if (event.error === 'language-not-supported' && this._onDeviceActive) {
                    // The pack is not actually installed ('downloadable' before the
                    // download completes). Drop to the online engine for this
                    // attempt, but allow the next click to install the pack and
                    // try on-device again - only a pack the browser reported as
                    // installed and still rejected is treated as unsupported.
                    console.warn('[SpeechManager] On-device model unavailable for', this._webSpeechLanguage);
                    this._onDeviceActive = false;
                    if (this._onDeviceProbe === 'available') {
                        this._onDeviceProbe = 'unavailable';
                    } else {
                        this._onDeviceProbe = null;
                        this._onDeviceProbeLang = '';
                    }
                    this._isAutoRestarting = true;
                    if (this._webSpeechRestartTimer) clearTimeout(this._webSpeechRestartTimer);
                    this._webSpeechRestartTimer = setTimeout(() => {
                        this._startWebSpeech(this._webSpeechLanguage);
                    }, 100);
                    return;
                }

                if (event.error === 'aborted') {
                    
                    
                    this._restartWebSpeech = false;
                    this._isAutoRestarting = false;
                    return;
                }

                if (event.error === 'audio-capture') {
                    console.error('[SpeechManager] Audio capture failed');
                    this._emitError('Microphone error: Could not capture audio. Please check your microphone.');
                    return;
                }

                console.error(`[SpeechManager] Unhandled error: ${event.error}`);
                this._emitError(`Speech recognition error: ${event.error}`);
            };

            this.recognition.onend = () => {
                const isAutoRestart = !this._manualStop && this._restartWebSpeech && this.sttEngine === 'web_speech_api';
                if (!isAutoRestart) {
                    this.isListening = false;
                    this._emitStateChange('stopped');
                    return;
                }

                this._isAutoRestarting = true;
                // If a network-retry backoff is already pending, do not schedule
                // a second restart here (avoids duplicate start).
                if (this._networkRetryPending) return;

                // Chromium ends a `continuous` session on a silence timeout, so
                // resuming is routine - and every millisecond spent here is
                // audio nobody hears. Resume on the next task with the engine
                // already decided rather than re-running the whole start path.
                if (!this._noteResumeAttempt()) return;
                if (this._webSpeechRestartTimer) clearTimeout(this._webSpeechRestartTimer);
                this._webSpeechRestartTimer = setTimeout(() => {
                    this._startWebSpeech(this._webSpeechLanguage, { resume: true });
                }, 0);
            };
        }

        _stopWebSpeech() {
            this._manualStop = true;
            this._restartWebSpeech = false;
            this._isAutoRestarting = false;
            this._networkRetryPending = false;
            if (this._webSpeechRestartTimer) {
                clearTimeout(this._webSpeechRestartTimer);
                this._webSpeechRestartTimer = null;
            }
            if (this._networkRetryTimer) {
                clearTimeout(this._networkRetryTimer);
                this._networkRetryTimer = null;
            }
            if (this.recognition) {
                this.recognition.stop();
                this.recognition = null;
            }
            this.isListening = false;
            this._releasePrimingStream();
        }

        

        async _startWhisperRecording(language) {
            if (this.isListening) return; // avoid double-recording on rapid clicks
            this.isListening = true;
            let stream = null;
            try {
                const audioConstraints = this._deviceId
                    ? { deviceId: { exact: this._deviceId } }
                    : true;

                stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });

                this.audioChunks = [];
                const mimeType = this._pickSupportedMimeType();
                this.mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
                const blobType = mimeType || 'audio/webm';

                this.mediaRecorder.ondataavailable = (e) => {
                    if (e.data.size > 0) {
                        this.audioChunks.push(e.data);
                    }
                };

                this.mediaRecorder.onstop = async () => {
                    stream.getTracks().forEach(t => t.stop());
                    stream = null;
                    const blob = new Blob(this.audioChunks, { type: blobType });
                    if (this.sttEngine === 'ai_provider') {
                        await this._sendToProviderSTT(blob, language);
                    } else {
                        await this._sendToWhisper(blob, language);
                    }
                };

                this.mediaRecorder.start();
                this._emitStateChange('listening');
            } catch (e) {
                this.isListening = false;
                if (stream) {
                    stream.getTracks().forEach(t => t.stop());
                }
                console.error('[SpeechManager] Whisper recording failed:', e);
                this._emitError(`Microphone access denied: ${e.message}`);
            }
        }

        _pickSupportedMimeType() {
            if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
                return 'audio/webm';
            }
            const candidates = [
                'audio/webm',
                'audio/webm;codecs=opus',
                'audio/mp4',
                'audio/mp4;codecs=mp4a.40.2',
            ];
            for (const mime of candidates) {
                if (MediaRecorder.isTypeSupported(mime)) {
                    return mime;
                }
            }
            return '';
        }

        _stopWhisperRecording() {
            if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
                this.mediaRecorder.stop();
            }
            this.isListening = false;
            this._emitStateChange('processing');
        }

        async _sendToWhisper(blob, language) {
            try {
                const formData = new FormData();
                formData.append('audio', blob, 'recording.webm');
                if (language && language !== 'auto') {
                    formData.append('language', language);
                }
                if (this.whisperModel) {
                    formData.append('whisper_model', this.whisperModel);
                }

                const response = await fetch('/api/whisper/transcribe', {
                    method: 'POST',
                    body: formData,
                });
                const data = await response.json();

                if (data.success && this.onResult) {
                    this.onResult({ final: data.text, interim: '', isFinal: true });
                } else if (data.error) {
                    this._emitError(data.error);
                }
            } catch (e) {
                this._emitError(`Whisper transcription failed: ${e.message}`);
            }
            this._emitStateChange('stopped');
        }

        async _sendToProviderSTT(blob, language) {
            try {
                if (!this.sttProvider || !this.sttModel) {
                    this._emitError('Select an STT provider and model in Settings first');
                    this._emitStateChange('stopped');
                    return;
                }

                const formData = new FormData();
                formData.append('audio', blob, 'recording.webm');
                formData.append('provider', this.sttProvider);
                formData.append('model', this.sttModel);
                if (language && language !== 'auto') {
                    formData.append('language', language);
                }

                const headers = window.llmAPIManager
                    ? window.llmAPIManager.getHeaders(this.sttProvider)
                    : {};
                delete headers['Content-Type'];

                const response = await fetch('/api/stt/transcribe', {
                    method: 'POST',
                    headers,
                    body: formData,
                });
                const data = await response.json();

                if (data.success && this.onResult) {
                    this.onResult({ final: data.text, interim: '', isFinal: true });
                } else if (data.error) {
                    this._emitError(data.error);
                }
            } catch (e) {
                this._emitError(`Provider STT failed: ${e.message}`);
            }
            this._emitStateChange('stopped');
        }

        

        speak(text, language = 'en', onEnd = null) {
            if (!this.synthesis) return;
            this.synthesis.cancel();

            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = this._mapLanguageCode(language);
            utterance.rate = 0.9;
            utterance.pitch = 1;

            const voices = this.synthesis.getVoices();
            const selectedVoices = voices.filter(v => this.playbackVoiceIds.includes(v.voiceURI));
            const voice = this._pickVoiceForPlayback(selectedVoices, voices, language);
            if (voice) utterance.voice = voice;

            utterance.onend = () => { if (typeof onEnd === 'function') onEnd(); };
            utterance.onerror = () => { if (typeof onEnd === 'function') onEnd(); };

            this.synthesis.speak(utterance);
        }

        _pickVoiceForPlayback(selectedVoices, allVoices, language) {
            const langPrefix = (language || '').toLowerCase();
            const filteredSelected = selectedVoices.length > 0
                ? selectedVoices.filter(v => v.lang.toLowerCase().startsWith(langPrefix))
                : [];

            const pool = filteredSelected.length > 0
                ? filteredSelected
                : (selectedVoices.length > 0 ? selectedVoices : allVoices.filter(v => v.lang.toLowerCase().startsWith(langPrefix)));

            if (!pool || pool.length === 0) {
                return allVoices[0] || null;
            }

            if (this.voiceMode === 'random') {
                const idx = Math.floor(Math.random() * pool.length);
                return pool[idx];
            }

            if (this.voiceMode === 'alternate' && pool.length > 1) {
                const idx = this.voiceIndex % pool.length;
                this.voiceIndex += 1;
                return pool[idx];
            }

            return pool[0];
        }

        stopSpeaking() {
            if (this.synthesis) this.synthesis.cancel();
        }

        

        _mapLanguageCode(code) {
            const map = {
                'auto': 'en-US', 'en': 'en-US', 'fr': 'fr-FR', 'de': 'de-DE',
                'es': 'es-ES', 'it': 'it-IT', 'pt': 'pt-BR', 'ru': 'ru-RU',
                'uk': 'uk-UA', 'zh': 'zh-CN', 'ja': 'ja-JP', 'ko': 'ko-KR',
                'ar': 'ar-SA', 'hi': 'hi-IN', 'nl': 'nl-NL', 'pl': 'pl-PL',
                'sv': 'sv-SE', 'tr': 'tr-TR', 'th': 'th-TH', 'vi': 'vi-VN',
            };
            return map[code] || code;
        }

        _emitError(msg) {
            console.error('[SpeechManager]', msg);
            if (this.onError) this.onError(msg);
        }

        _emitNotice(msg, type = 'info') {
            if (this.onNotice) this.onNotice(msg, type);
        }

        _emitStateChange(state) {
            if (this.onStateChange) this.onStateChange(state);
        }

        getCapabilities() {
            return {
                webSpeechAPI: this.webSpeechSupported && !this.offlineMode && !this._engineFallback,
                tts: !!this.synthesis,
                offline: this.offlineMode,
                offlineReady: this.offlineStatus?.ready || false,
                offlineReason: this.offlineStatus?.reason || '',
                whisperAvailable: this._whisperAvail === true,
                onDeviceSupported: this._onDeviceSupported(),
                onDeviceState: this._onDeviceProbe || 'unknown',
                onDeviceActive: this._onDeviceActive,
                recommendedEngine: (this.offlineMode || this._engineFallback) ? 'whisper' : 'web_speech_api',
                fallbackActive: this._engineFallback,
                speechMode: this.speechMode,
            };
        }
    }

    window.SpeechManager = SpeechManager;

    document.addEventListener('DOMContentLoaded', () => {
        if (!window.speechManager) {
            window.speechManager = new SpeechManager();
        }
    });
})();
