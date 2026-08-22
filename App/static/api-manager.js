
(function () {
    'use strict';

    class LLMAPIManager {
        constructor() {
            this.providers = {
                ollama: { name: 'Ollama', type: 'local', requiresKey: false },
                lmstudio: { name: 'LM Studio', type: 'local', requiresKey: false },
                openai: { name: 'OpenAI', type: 'cloud', requiresKey: true },
                anthropic: { name: 'Anthropic', type: 'cloud', requiresKey: true },
                gemini: { name: 'Google Gemini', type: 'cloud', requiresKey: true },
                deepseek: { name: 'DeepSeek', type: 'cloud', requiresKey: true },
                cohere: { name: 'Cohere', type: 'cloud', requiresKey: true },
                groq: { name: 'Groq', type: 'cloud', requiresKey: true },
                grok: { name: 'Grok (X.AI)', type: 'cloud', requiresKey: true },
                mistral: { name: 'Mistral AI', type: 'cloud', requiresKey: true },
                perplexity: { name: 'Perplexity', type: 'cloud', requiresKey: true },
            };
            this.apiKeys = {};
            this.apiKeyPriority = 'client';
            this._loadFromSettings();
        }

        _loadFromSettings() {
            
            if (window.userSettings) {
                this.apiKeys = window.userSettings.api_keys || {};
                this.apiKeyPriority = window.userSettings.api_key_priority || 'client';
            } else {
                
                try {
                    this.apiKeys = JSON.parse(localStorage.getItem('lt_api_keys') || '{}');
                } catch { this.apiKeys = {}; }
                this.apiKeyPriority = localStorage.getItem('lt_api_key_priority') || 'client';
            }
        }

        async _saveToSettings() {
            if (window.updateSetting) {
                await window.updateSetting('api_keys', this.apiKeys);
                await window.updateSetting('api_key_priority', this.apiKeyPriority);
            }
        }

        async setApiKeyPriority(priority) {
            this.apiKeyPriority = priority === 'server' ? 'server' : 'client';
            await this._saveToSettings();
        }

        getApiKeyPriority() {
            return this.apiKeyPriority || 'client';
        }

        async saveApiKey(provider, key) {
            this.apiKeys[provider] = key;
            await this._saveToSettings();
        }

        getApiKey(provider) {
            return this.apiKeys[provider] || '';
        }

        async removeApiKey(provider) {
            delete this.apiKeys[provider];
            await this._saveToSettings();
        }

        getHeaders(provider, keySource = null) {
            const headers = { 'Content-Type': 'application/json' };
            const key = this.getApiKey(provider);
            if (key) {
                headers['X-API-Key'] = key;
            }
            headers['X-API-Key-Source'] = keySource || this.getApiKeyPriority();
            return headers;
        }

        categorizeError(error, provider) {
            const msg = (error.message || error.error || String(error)).toLowerCase();

            if (msg.includes('401') || msg.includes('auth') || msg.includes('api key') || msg.includes('unauthorized')) {
                return { category: 'auth', userMessage: 'Authentication failed. Check your API key.', retryable: false, technical: msg };
            }
            if (msg.includes('429') || msg.includes('rate limit') || msg.includes('quota')) {
                return { category: 'rate_limit', userMessage: 'Rate limit exceeded. Wait and retry.', retryable: true, technical: msg };
            }
            if (msg.includes('timeout')) {
                return { category: 'timeout', userMessage: 'Request timed out. Try again.', retryable: true, technical: msg };
            }
            if (msg.includes('connection') || msg.includes('network') || msg.includes('refused') || msg.includes('econnrefused')) {
                return { category: 'network', userMessage: `Cannot reach ${this.providers[provider]?.name || provider}. Is it running?`, retryable: true, technical: msg };
            }
            if (msg.includes('model') && (msg.includes('not found') || msg.includes('404'))) {
                return { category: 'model', userMessage: 'Model not found. Select a different model.', retryable: false, technical: msg };
            }
            return { category: 'unknown', userMessage: 'Translation failed. Check settings and try again.', retryable: true, technical: msg };
        }

        stripThinkingTags(text) {
            if (!text) return text;
            const patterns = [
                /<think>[\s\S]*?<\/think>/gi,
                /<thinking>[\s\S]*?<\/thinking>/gi,
                /<reasoning>[\s\S]*?<\/reasoning>/gi,
                /<internal>[\s\S]*?<\/internal>/gi,
                /<reflection>[\s\S]*?<\/reflection>/gi,
                /<scratchpad>[\s\S]*?<\/scratchpad>/gi,
                /\[thinking\][\s\S]*?\[\/thinking\]/gi,
            ];
            let result = text;
            for (const p of patterns) {
                result = result.replace(p, '');
            }
            return result.trim();
        }

        validateTranslation(original, translated, targetLanguage) {
            const issues = [];

            if (!translated || translated.trim().length === 0) {
                issues.push({ severity: 'error', message: 'Translation is empty' });
                return { valid: false, issues };
            }

            const origLen = original.trim().length;
            const transLen = translated.trim().length;

            if (transLen < origLen * 0.1 && origLen > 100) {
                issues.push({ severity: 'warning', message: 'Translation appears suspiciously short' });
            }

            if (original.trim() === translated.trim() && origLen > 50) {
                issues.push({ severity: 'warning', message: 'Translation is identical to original' });
            }

            const errorPatterns = [
                /^error:/i, /^sorry,?\s+i\s+ca(n't|nnot)/i, /^i\s+apologize/i,
                /^as\s+an\s+ai/i, /translation\s+failed/i,
            ];
            for (const p of errorPatterns) {
                if (p.test(translated)) {
                    issues.push({ severity: 'error', message: 'Translation contains error or refusal' });
                    return { valid: false, issues };
                }
            }

            const words = translated.split(/\s+/);
            if (words.length > 20) {
                const counts = {};
                words.forEach(w => {
                    const c = w.toLowerCase().replace(/[^\w]/g, '');
                    if (c.length > 3) counts[c] = (counts[c] || 0) + 1;
                });
                if (Math.max(...Object.values(counts)) > words.length * 0.3) {
                    issues.push({ severity: 'warning', message: 'Excessive word repetition detected' });
                }
            }

            const hasErrors = issues.some(i => i.severity === 'error');
            return {
                valid: !hasErrors, issues,
                warnings: issues.filter(i => i.severity === 'warning'),
                confidence: hasErrors ? 'low' : (issues.length > 0 ? 'medium' : 'high'),
            };
        }

        postProcessTranslation(text) {
            let processed = this.stripThinkingTags(text);
            const prefixes = [
                /^Here(?:'s| is) the translation[:\s]*/i,
                /^Translation[:\s]*/i,
                /^Translated text[:\s]*/i,
            ];
            prefixes.forEach(p => { processed = processed.replace(p, ''); });
            return processed.trim();
        }

        formatErrorMessage(error, provider) {
            const cat = this.categorizeError(error, provider);
            let msg = cat.userMessage;
            if (cat.retryable) msg += ' You can retry.';
            return { message: msg, category: cat.category, retryable: cat.retryable, technical: cat.technical };
        }
    }

    window.LLMAPIManager = LLMAPIManager;

    document.addEventListener('DOMContentLoaded', () => {
        if (!window.llmAPIManager) {
            window.llmAPIManager = new LLMAPIManager();
        }
    });
})();
