// dom.js - DOM 操作工具函数

import { formatVolume, formatDateTime } from './format.js';

export function setStatus(text) {
    const el = document.getElementById('status');
    if (!el) return;

    const raw = text;
    if (raw.startsWith('\u2714')) {
        el.textContent = raw;
        el.className = '';
    } else if (raw.includes('\u9519\u8bef') || raw.includes('\u5931\u8d25') || raw.startsWith('\u274c')) {
        el.innerHTML = '\u2716 ' + raw.replace(/[\u274c\u2716]/g, '').trim();
        el.className = 'error';
    } else if (raw.includes('\u52a0\u8f7d') || raw.includes('\u53e0\u52a0')) {
        el.innerHTML = '\u27b3 ' + raw;
        el.className = 'loading';
    } else if (raw.startsWith('\u2705')) {
        el.innerHTML = '\u2714 ' + raw.replace(/[\u2705]/g, '').trim();
        el.className = '';
    } else {
        el.textContent = raw;
        el.className = '';
    }
}

export function updatePriceDisplay(data) {
    const priceEl = document.getElementById('current-price');
    const changeEl = document.getElementById('price-change');
    const changeTextEl = document.getElementById('price-change-text');

    if (!priceEl || !data || !data.close) return;

    priceEl.textContent = data.close.toFixed(2);

    const change = ((data.close - data.open) / data.open * 100);
    const changeText = change >= 0 ? `+${change.toFixed(2)}%` : `${change.toFixed(2)}%`;
    changeTextEl.textContent = changeText;

    if (change >= 0) {
        priceEl.style.color = '#0ecb81';
        if (changeEl) changeEl.className = 'change';
    } else {
        priceEl.style.color = '#f6465d';
        if (changeEl) changeEl.className = 'change negative';
    }
}

export function updateOHLCDisplay(time, data, volumeData) {
    const timeStr = formatDateTime(time);

    const timeEl = document.getElementById('ohlc-time');
    const openEl = document.getElementById('ohlc-open');
    const highEl = document.getElementById('ohlc-high');
    const lowEl = document.getElementById('ohlc-low');
    const closeEl = document.getElementById('ohlc-close');
    const volEl = document.getElementById('ohlc-volume');

    if (timeEl) timeEl.textContent = timeStr;
    if (openEl) openEl.textContent = data.open ? data.open.toFixed(2) : '--';
    if (highEl) highEl.textContent = data.high ? data.high.toFixed(2) : '--';
    if (lowEl) lowEl.textContent = data.low ? data.low.toFixed(2) : '--';
    if (closeEl) closeEl.textContent = data.close ? data.close.toFixed(2) : '--';

    if (volEl && volumeData) {
        const volumeItem = volumeData.find(v => v.time === time);
        if (volumeItem) {
            volEl.textContent = formatVolume(volumeItem.value);
        }
    }
}

export function updateDataTime(timestamp) {
    const el = document.getElementById('data-time');
    if (!el) return;
    const timeStr = formatDateTime(timestamp);
    el.textContent = `\u6700\u65b0: ${timeStr}`;
}

// 兼容：暴露到 window，供 realtime_kline.js 等旧代码使用
window.setStatus = setStatus;
window.updatePriceDisplay = updatePriceDisplay;
window.updateDataTime = updateDataTime;
window.updateOHLCDisplay = updateOHLCDisplay;
window.formatVolume = formatVolume;
window.formatDateTime = formatDateTime;