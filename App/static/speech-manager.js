/**
 * Speech Manager - Handles speech-to-text (STT) and text-to-speech (TTS).
 * Supports Web Speech API (browser) and Whisper (server-side) for STT.
 */
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

            this.webSpeechSupported = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
            this.synthesis = window.speechSynthesis || null;
            this.voiceMode = 'single';
            this.playbackVoiceIds = [];
            this.voiceIndex = 0;
            this.sttProvider = 'groq';
            this.sttModel = '';
            this.whisperModel = 'base';
            
            this._loadFromSettings();
            
            // Start offline check asynchronously but don't block constructor
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
                    this.offlineMode = this.offlineStatus.offline;
                    
                    // In offline mode, suggest Whisper if available (don't force change)
                    if (this.offlineMode && this.offlineStatus.whisper_available) {
                        if (this.sttEngine === 'web_speech_api') {
                            console.warn('[SpeechManager] Offline mode - Whisper recommended (Web Speech API requires internet)');
                        }
                    }
                } else {
                }
            } catch (e) {
                // Silent fail - offline check is optional
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
            } else {
                // Fallback to localStorage for migration
                this.sttEngine = localStorage.getItem('lt_stt_engine') || 'web_speech_api';
                this.sttProvider = localStorage.getItem('lt_stt_provider') || 'groq';
                this.sttModel = localStorage.getItem('lt_stt_model') || '';
                this.whisperModel = localStorage.getItem('lt_whisper_model') || 'base';
                this.voiceMode = localStorage.getItem('lt_voice_mode') || 'single';
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

        // Set the preferred microphone device ID (from enumerateDevices).
        // An empty string means "use the browser default".
        setDeviceId(deviceId) {
            const nextDeviceId = deviceId || '';
            if (this._deviceId === nextDeviceId) return;
            this._deviceId = nextDeviceId;

            // If the target device changed, force a fresh priming stream next start.
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
            this.sttEngine = engine;
            if (this.isListening) {
                this.stop();
            }
            
            // Save to settings
            if (window.updateSetting) {
                await window.updateSetting('stt_engine', this.sttEngine);
            }
        }

        start(language = 'en') {
            try {
                if (this.sttEngine === 'web_speech_api') {
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

        // ---- Web Speech API ----

        _startWebSpeech(language) {
            if (!this.webSpeechSupported) {
                this._emitError('Web Speech API not supported in this browser');
                return;
            }

            // Prevent multiple simultaneous recognition instances
            if (this.recognition && this.isListening && !this._isAutoRestarting) {
                this._stopWebSpeech();
            }

            this._manualStop = false;
            this._restartWebSpeech = true;
            this._networkRetryCount = 0;
            this._webSpeechLanguage = this._mapLanguageCode(language);
            if (this._webSpeechRestartTimer) {
                clearTimeout(this._webSpeechRestartTimer);
                this._webSpeechRestartTimer = null;
            }

            // If a specific device is requested, open a silent getUserMedia stream
            // with that deviceId first.  Chrome honours the most-recently-opened
            // audio device constraint and will route SpeechRecognition to it.
            const primeAndStart = () => {
                try {
                    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                    this.recognition = new SpeechRecognition();
                    this.recognition.continuous = true;
                    this.recognition.interimResults = true;
                    this.recognition.maxAlternatives = 1;
                    this.recognition.lang = this._webSpeechLanguage;
                    this._attachRecognitionHandlers();
                    
                    this.recognition.start();
                } catch (e) {
                    console.error('[SpeechManager] Recognition start failed:', e);
                    this._emitError(`Failed to start: ${e.message}`);
                }
            };

            const hasActivePrimingStream = this._primingStream &&
                this._primingDeviceId === this._deviceId &&
                this._primingStream.getAudioTracks().some(t => t.readyState === 'live');

            if (this._deviceId && !hasActivePrimingStream) {
                navigator.mediaDevices.getUserMedia({
                    audio: { deviceId: { exact: this._deviceId } },
                }).then(stream => {
                    this._primingStream = stream;
                    this._primingDeviceId = this._deviceId;
                    primeAndStart();
                }).catch(err => {
                    // Fall back to default device if the chosen one fails.
                    primeAndStart();
                });
            } else {
                primeAndStart();
            }
        }

        _attachRecognitionHandlers() {
            this.recognition.onstart = () => {
                this.isListening = true;
                // Only emit state change if not auto-restarting (prevents flicker)
                if (!this._isAutoRestarting) {
                    this._emitStateChange('listening');
                }
                this._isAutoRestarting = false;
            };

            this.recognition.onresult = (event) => {
                // Reset network retry counter on successful recognition
                this._networkRetryCount = 0;
                
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
                    // No speech detected - this is normal, just continue listening
                    return;
                }

                if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
                    this._restartWebSpeech = false;
                    this._isAutoRestarting = false;
                    this._emitError('Microphone permission was denied. Please allow microphone access for this site.');
                    return;
                }

                if (event.error === 'network') {
                    // Transient Google speech service blip — silent exponential backoff.
                    // Only surface an error to the UI after 3 consecutive failures.
                    this._networkRetryCount = (this._networkRetryCount || 0) + 1;
                    const count = this._networkRetryCount;
                    const backoffMs = count <= 3 ? 2000 : Math.min(count * 3000, 20000);

                    if (count >= 3) {
                        this._emitError('Speech recognition is having trouble reaching the network. Retrying\u2026');
                    }
                    // Keep auto-restart enabled and schedule retry
                    this._isAutoRestarting = true;
                    this._webSpeechRestartTimer = setTimeout(() => {
                        if (!this._manualStop && this.sttEngine === 'web_speech_api') {
                            this._startWebSpeech(this._webSpeechLanguage);
                        }
                    }, backoffMs);
                    return;
                }

                if (event.error === 'aborted') {
                    // \"aborted\" means another recognition session started — this is expected
                    // when switching between conversation sides. Don't restart or show error.
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
                // Check if this is an automatic restart or manual stop
                const isAutoRestart = !this._manualStop && this._restartWebSpeech && this.sttEngine === 'web_speech_api';
                
                if (isAutoRestart) {
                    // Keep listening state active during auto-restart (prevents flicker)
                    this._isAutoRestarting = true;
                    this._webSpeechRestartTimer = setTimeout(() => {
                        this._startWebSpeech(this._webSpeechLanguage);
                    }, 100); // Reduced delay for faster restart
                } else {
                    // Actually stopped
                    this.isListening = false;
                    this._emitStateChange('stopped');
                }
            };
        }

        _stopWebSpeech() {
            this._manualStop = true;
            this._restartWebSpeech = false;
            this._isAutoRestarting = false;
            if (this._webSpeechRestartTimer) {
                clearTimeout(this._webSpeechRestartTimer);
                this._webSpeechRestartTimer = null;
            }
            if (this.recognition) {
                this.recognition.stop();
                this.recognition = null;
            }
            this.isListening = false;
            this._releasePrimingStream();
        }

        // ---- Whisper (server-side) ----

        async _startWhisperRecording(language) {
            try {
                const audioConstraints = this._deviceId
                    ? { deviceId: { exact: this._deviceId } }
                    : true;
                
                const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });
                
                this.audioChunks = [];
                this.mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });

                this.mediaRecorder.ondataavailable = (e) => {
                    if (e.data.size > 0) {
                        this.audioChunks.push(e.data);
                    }
                };

                this.mediaRecorder.onstop = async () => {
                    stream.getTracks().forEach(t => t.stop());
                    const blob = new Blob(this.audioChunks, { type: 'audio/webm' });
                    if (this.sttEngine === 'ai_provider') {
                        await this._sendToProviderSTT(blob, language);
                    } else {
                        await this._sendToWhisper(blob, language);
                    }
                };

                this.mediaRecorder.start();
                this.isListening = true;
                this._emitStateChange('listening');
            } catch (e) {
                console.error('[SpeechManager] Whisper recording failed:', e);
                this._emitError(`Microphone access denied: ${e.message}`);
            }
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

        // ---- TTS ----

        speak(text, language = 'en') {
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

        // ---- Helpers ----

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

        _emitStateChange(state) {
            if (this.onStateChange) this.onStateChange(state);
        }

        getCapabilities() {
            return {
                webSpeechAPI: this.webSpeechSupported && !this.offlineMode,
                tts: !!this.synthesis,
                offline: this.offlineMode,
                whisperAvailable: this.offlineStatus?.whisper_available || false,
                recommendedEngine: this.offlineMode ? 'whisper' : 'web_speech_api',
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
