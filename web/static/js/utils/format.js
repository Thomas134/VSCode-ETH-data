// format.js - 格式化工具函数

export function formatVolume(vol) {
    if (vol >= 1000000) {
        return (vol / 1000000).toFixed(2) + 'M';
    } else if (vol >= 1000) {
        return (vol / 1000).toFixed(2) + 'K';
    }
    return vol.toFixed(2);
}

export function formatDateTime(timestamp) {
    const date = new Date(timestamp * 1000);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

export function formatPriceChange(close, open) {
    const change = ((close - open) / open * 100);
    return change >= 0 ? `+${change.toFixed(2)}%` : `${change.toFixed(2)}%`;
}