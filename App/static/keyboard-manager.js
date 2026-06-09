/**
 * Keyboard Manager - Virtual keyboard layouts for non-Latin scripts.
 * Supports Arabic, Hebrew, Cyrillic, Devanagari, CJK input methods, etc.
 */
(function () {
    'use strict';

    const LAYOUTS = {
        arabic: {
            name: 'Arabic',
            rows: [
                ['ض', 'ص', 'ث', 'ق', 'ف', 'غ', 'ع', 'ه', 'خ', 'ح', 'ج', 'د'],
                ['ش', 'س', 'ي', 'ب', 'ل', 'ا', 'ت', 'ن', 'م', 'ك', 'ط'],
                ['ئ', 'ء', 'ؤ', 'ر', 'لا', 'ى', 'ة', 'و', 'ز', 'ظ'],
            ],
        },
        hebrew: {
            name: 'Hebrew',
            rows: [
                ['ק', 'ר', 'א', 'ט', 'ו', 'ן', 'ם', 'פ'],
                ['ש', 'ד', 'ג', 'כ', 'ע', 'י', 'ח', 'ל', 'ך', 'ף'],
                ['ז', 'ס', 'ב', 'ה', 'נ', 'מ', 'צ', 'ת', 'ץ'],
            ],
        },
        cyrillic: {
            name: 'Cyrillic (Russian)',
            rows: [
                ['й', 'ц', 'у', 'к', 'е', 'н', 'г', 'ш', 'щ', 'з', 'х', 'ъ'],
                ['ф', 'ы', 'в', 'а', 'п', 'р', 'о', 'л', 'д', 'ж', 'э'],
                ['я', 'ч', 'с', 'м', 'и', 'т', 'ь', 'б', 'ю', 'ё'],
            ],
        },
        ukrainian: {
            name: 'Ukrainian',
            rows: [
                ['й', 'ц', 'у', 'к', 'е', 'н', 'г', 'ш', 'щ', 'з', 'х', 'ї'],
                ['ф', 'і', 'в', 'а', 'п', 'р', 'о', 'л', 'д', 'ж', 'є'],
                ['я', 'ч', 'с', 'м', 'и', 'т', 'ь', 'б', 'ю', 'ґ'],
            ],
        },
        devanagari: {
            name: 'Devanagari (Hindi)',
            rows: [
                ['क', 'ख', 'ग', 'घ', 'ङ', 'च', 'छ', 'ज', 'झ', 'ञ'],
                ['ट', 'ठ', 'ड', 'ढ', 'ण', 'त', 'थ', 'द', 'ध', 'न'],
                ['प', 'फ', 'ब', 'भ', 'म', 'य', 'र', 'ल', 'व', 'श'],
                ['ष', 'स', 'ह', 'अ', 'आ', 'इ', 'ई', 'उ', 'ऊ', 'ए'],
            ],
        },
        japanese: {
            name: 'Japanese (Hiragana)',
            rows: [
                ['あ', 'い', 'う', 'え', 'お', 'か', 'き', 'く', 'け', 'こ'],
                ['さ', 'し', 'す', 'せ', 'そ', 'た', 'ち', 'つ', 'て', 'と'],
                ['な', 'に', 'ぬ', 'ね', 'の', 'は', 'ひ', 'ふ', 'へ', 'ほ'],
                ['ま', 'み', 'む', 'め', 'も', 'や', 'ゆ', 'よ', 'ん', 'ー'],
            ],
        },
        korean: {
            name: 'Korean',
            rows: [
                ['ㅂ', 'ㅈ', 'ㄷ', 'ㄱ', 'ㅅ', 'ㅛ', 'ㅕ', 'ㅑ', 'ㅐ', 'ㅔ'],
                ['ㅁ', 'ㄴ', 'ㅇ', 'ㄹ', 'ㅎ', 'ㅗ', 'ㅓ', 'ㅏ', 'ㅣ'],
                ['ㅋ', 'ㅌ', 'ㅊ', 'ㅍ', 'ㅠ', 'ㅜ', 'ㅡ'],
            ],
        },
        thai: {
            name: 'Thai',
            rows: [
                ['ๅ', '/', '-', 'ภ', 'ถ', 'ุ', 'ึ', 'ค', 'ต', 'จ', 'ข', 'ช'],
                ['ๆ', 'ไ', 'ำ', 'พ', 'ะ', 'ั', 'ี', 'ร', 'น', 'ย', 'บ', 'ล'],
                ['ฟ', 'ห', 'ก', 'ด', 'เ', '้', '่', 'า', 'ส', 'ว', 'ง'],
            ],
        },
        greek: {
            name: 'Greek',
            rows: [
                ['ς', 'ε', 'ρ', 'τ', 'υ', 'θ', 'ι', 'ο', 'π'],
                ['α', 'σ', 'δ', 'φ', 'γ', 'η', 'ξ', 'κ', 'λ'],
                ['ζ', 'χ', 'ψ', 'ω', 'β', 'ν', 'μ'],
            ],
        },
    };

    class KeyboardManager {
        constructor() {
            this.currentLayout = null;
            this.targetInput = null;
            this.overlay = null;
            this.isOpen = false;
        }

        getLayouts() {
            return Object.entries(LAYOUTS).map(([id, layout]) => ({
                id, name: layout.name,
            }));
        }

        open(targetElement, layoutId) {
            this.targetInput = targetElement;
            this.currentLayout = layoutId || 'cyrillic';
            this.overlay = document.getElementById('keyboardOverlay');
            this._render();
            this.overlay.style.display = 'block';
            this.isOpen = true;
        }

        close() {
            if (this.overlay) {
                this.overlay.style.display = 'none';
            }
            this.isOpen = false;
        }

        setLayout(layoutId) {
            this.currentLayout = layoutId;
            this._render();
        }

        _render() {
            const layout = LAYOUTS[this.currentLayout];
            if (!layout) return;

            const keysContainer = document.getElementById('keyboardKeys');
            keysContainer.innerHTML = '';

            // Populate layout selector
            const layoutSelect = document.getElementById('keyboardLayout');
            layoutSelect.innerHTML = '';
            for (const [id, l] of Object.entries(LAYOUTS)) {
                const opt = document.createElement('option');
                opt.value = id;
                opt.textContent = l.name;
                if (id === this.currentLayout) opt.selected = true;
                layoutSelect.appendChild(opt);
            }

            // Render key rows
            for (const row of layout.rows) {
                const rowEl = document.createElement('div');
                rowEl.className = 'keyboard-row';
                for (const key of row) {
                    const btn = document.createElement('button');
                    btn.className = 'key-btn';
                    btn.textContent = key;
                    btn.addEventListener('click', () => this._insertChar(key));
                    rowEl.appendChild(btn);
                }
                keysContainer.appendChild(rowEl);
            }

            // Add utility row (backspace, space, enter)
            const utilRow = document.createElement('div');
            utilRow.className = 'keyboard-row';

            const backspace = document.createElement('button');
            backspace.className = 'key-btn wide';
            backspace.textContent = '⌫';
            backspace.addEventListener('click', () => this._backspace());

            const space = document.createElement('button');
            space.className = 'key-btn space';
            space.textContent = 'Space';
            space.addEventListener('click', () => this._insertChar(' '));

            const enter = document.createElement('button');
            enter.className = 'key-btn wide';
            enter.textContent = '↵';
            enter.addEventListener('click', () => this._insertChar('\n'));

            utilRow.appendChild(backspace);
            utilRow.appendChild(space);
            utilRow.appendChild(enter);
            keysContainer.appendChild(utilRow);
        }

        _insertChar(char) {
            if (!this.targetInput) return;
            const start = this.targetInput.selectionStart;
            const end = this.targetInput.selectionEnd;
            const val = this.targetInput.value;
            this.targetInput.value = val.slice(0, start) + char + val.slice(end);
            this.targetInput.selectionStart = this.targetInput.selectionEnd = start + char.length;
            this.targetInput.focus();
            this.targetInput.dispatchEvent(new Event('input', { bubbles: true }));
        }

        _backspace() {
            if (!this.targetInput) return;
            const start = this.targetInput.selectionStart;
            const end = this.targetInput.selectionEnd;
            const val = this.targetInput.value;
            if (start !== end) {
                this.targetInput.value = val.slice(0, start) + val.slice(end);
                this.targetInput.selectionStart = this.targetInput.selectionEnd = start;
            } else if (start > 0) {
                this.targetInput.value = val.slice(0, start - 1) + val.slice(start);
                this.targetInput.selectionStart = this.targetInput.selectionEnd = start - 1;
            }
            this.targetInput.focus();
            this.targetInput.dispatchEvent(new Event('input', { bubbles: true }));
        }

        suggestLayout(languageCode) {
            const map = {
                'ar': 'arabic', 'he': 'hebrew', 'ru': 'cyrillic', 'uk': 'ukrainian',
                'hi': 'devanagari', 'bn': 'devanagari', 'ja': 'japanese',
                'ko': 'korean', 'th': 'thai', 'el': 'greek', 'fa': 'arabic',
                'ur': 'arabic',
            };
            return map[languageCode] || null;
        }
    }

    window.KeyboardManager = KeyboardManager;

    document.addEventListener('DOMContentLoaded', () => {
        if (!window.keyboardManager) {
            window.keyboardManager = new KeyboardManager();
        }
    });
})();
