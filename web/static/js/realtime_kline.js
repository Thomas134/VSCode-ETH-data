// 实时缠论数据模块
// 在 chart.js 之后加载

let isRealtimeMode = false;
let realtimeTimer = null;
let socket = null;
let currentInterval = '1m';

async function loadRealtimeKlineData(interval, limit = 500) {
    window.setStatus('⟳ 加载实时缠论数据...');
    console.log('[Realtime] 开始加载数据, interval=', interval);
    
    // 检查图表实例
    if (!window.candlestickSeries || !window.volumeSeries) {
        console.error('[Realtime] 图表实例未初始化!');
        window.setStatus('✖ 图表未初始化');
        return;
    }
    
    try {
        const url = `/api/kline/realtime?interval=${interval}&limit=${limit}`;
        console.log('[Realtime] 请求URL:', url);
        
        const response = await fetch(url);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const result = await response.json();
        console.log('[Realtime] 收到响应:', result);
        
        if (result.error) {
            throw new Error(result.error);
        }
        
        const data = result.data;
        console.log('[Realtime] 数据条数:', data.length);
        
        if (data.length === 0) {
            window.setStatus('✖ 无数据返回');
            return;
        }
        
        // 使用 window.xxx 访问 chart.js 的变量
        window.allCandleData = data.map(item => ({
            time: item.time,
            open: item.open,
            high: item.high,
            low: item.low,
            close: item.close,
        }));
        
        window.allVolumeData = data.map(item => ({
            time: item.time,
            value: item.volume || 0,
            color: item.close >= item.open ? '#0ecb81' : '#f6465d',
        }));
        
        console.log('[Realtime] 设置K线数据:', window.allCandleData.length, '条');
        console.log('[Realtime] 第一条:', window.allCandleData[0]);
        console.log('[Realtime] 最后一条:', window.allCandleData[window.allCandleData.length-1]);
        
        window.candlestickSeries.setData(window.allCandleData);
        window.volumeSeries.setData(window.allVolumeData);
        
        window.fractalRegions = result.fractal_regions || [];
        console.log('[Realtime] 分型区域:', window.fractalRegions.length, '个');
        window.drawFractalRegions();
        
        try { 
            window.priceChart.timeScale().scrollToRealTime(); 
        } catch(e) {}
        
        const latest = data[data.length - 1];
        window.updatePriceDisplay(latest);
        window.updateDataTime(latest.time);
        
        const realtimeMarker = result.is_realtime ? '⚡' : '';
        window.setStatus(`${realtimeMarker} 实时缠论: ${data.length}条 (${result.local_count}本地+${result.live_count}实时)`);
        
        if (isRealtimeMode) {
            startRealtimePolling(interval);
        }
        
    } catch (error) {
        console.error('加载实时数据失败:', error);
        window.setStatus(`✖ 错误: ${error.message}`);
        
        setTimeout(() => {
            window.setStatus('⟳ 回退到本地数据...');
            window.loadKlineData(interval);
        }, 2000);
    }
}

function startRealtimePolling(interval) {
    stopRealtimePolling();
    currentInterval = interval;
    
    // 使用 WebSocket 替代轮询
    console.log('[Realtime] 启动 WebSocket...');
    
    if (!socket) {
        socket = io();
        
        socket.on('connect', () => {
            console.log('[WebSocket] 已连接');
            socket.emit('subscribe_kline', { interval: currentInterval });
        });
        
        socket.on('disconnect', () => {
            console.log('[WebSocket] 已断开');
        });
        
        socket.on('kline_update', (data) => {
            if (data.interval === currentInterval) {
                handleWebSocketKline(data);
            }
        });
    } else {
        socket.emit('subscribe_kline', { interval: currentInterval });
    }
}

function stopRealtimePolling() {
    if (socket) {
        socket.disconnect();
        socket = null;
        console.log('[WebSocket] 已停止');
    }
}

function handleWebSocketKline(data) {
    // 更新最后一根K线或添加新K线
    const time = data.time;
    const lastIndex = window.allCandleData.length - 1;
    
    if (lastIndex >= 0 && window.allCandleData[lastIndex].time === time) {
        // 更新现有K线
        const kline = {
            time: data.time,
            open: data.open,
            high: data.high,
            low: data.low,
            close: data.close,
        };
        
        window.allCandleData[lastIndex] = kline;
        window.candlestickSeries.update(kline);
        
        const volume = {
            time: data.time,
            value: data.volume || 0,
            color: data.close >= data.open ? '#0ecb81' : '#f6465d',
        };
        window.allVolumeData[lastIndex] = volume;
        window.volumeSeries.update(volume);
        
        window.updatePriceDisplay(kline);
    } else if (lastIndex < 0 || time > window.allCandleData[lastIndex].time) {
        // 新K线
        const kline = {
            time: data.time,
            open: data.open,
            high: data.high,
            low: data.low,
            close: data.close,
        };
        
        window.allCandleData.push(kline);
        window.candlestickSeries.update(kline);
        
        const volume = {
            time: data.time,
            value: data.volume || 0,
            color: data.close >= data.open ? '#0ecb81' : '#f6465d',
        };
        window.allVolumeData.push(volume);
        window.volumeSeries.update(volume);
        
        console.log('[WebSocket] 新K线:', new Date(time * 1000).toLocaleTimeString());
    }
}

function updateRealtimeCandles(newData) {
    let hasUpdate = false;
    
    for (const kline of newData) {
        const time = kline.time;
        const lastIndex = window.allCandleData.length - 1;
        
        let existingIndex = -1;
        for (let i = lastIndex; i >= 0 && i > lastIndex - 15; i--) {
            if (window.allCandleData[i].time === time) {
                existingIndex = i;
                break;
            }
        }
        
        if (existingIndex >= 0) {
            const oldClose = window.allCandleData[existingIndex].close;
            window.allCandleData[existingIndex] = {
                time: kline.time,
                open: kline.open,
                high: kline.high,
                low: kline.low,
                close: kline.close,
            };
            
            if (oldClose !== kline.close) {
                window.candlestickSeries.update(window.allCandleData[existingIndex]);
                
                window.allVolumeData[existingIndex] = {
                    time: kline.time,
                    value: kline.volume || 0,
                    color: kline.close >= kline.open ? '#0ecb81' : '#f6465d',
                };
                window.volumeSeries.update(window.allVolumeData[existingIndex]);
                
                hasUpdate = true;
                
                if (existingIndex === lastIndex) {
                    window.updatePriceDisplay(kline);
                }
            }
        } else if (time > window.allCandleData[lastIndex]?.time) {
            window.allCandleData.push({
                time: kline.time,
                open: kline.open,
                high: kline.high,
                low: kline.low,
                close: kline.close,
            });
            
            window.candlestickSeries.update(window.allCandleData[window.allCandleData.length - 1]);
            
            window.allVolumeData.push({
                time: kline.time,
                value: kline.volume || 0,
                color: kline.close >= kline.open ? '#0ecb81' : '#f6465d',
            });
            window.volumeSeries.update(window.allVolumeData[window.allVolumeData.length - 1]);
            
            console.log('[Realtime] 新K线:', new Date(time * 1000).toLocaleTimeString());
            hasUpdate = true;
        }
    }
    
    if (hasUpdate) {
        window.setStatus('⚡ 实时更新');
    }
}

function toggleRealtimeMode(enabled) {
    // 检查是否初始化完成
    if (!window.currentInterval) {
        console.error('[Realtime] chart.js 尚未初始化完成，请稍后再试');
        window.setStatus && window.setStatus('⟳ 初始化中，请稍候...');
        return;
    }
    
    isRealtimeMode = enabled;
    
    // 更新按钮样式
    const btnLocal = document.getElementById('btn-source-local');
    const btnRealtime = document.getElementById('btn-source-realtime');
    const statusDiv = document.getElementById('realtime-status');
    
    if (btnLocal) btnLocal.classList.toggle('active', !enabled);
    if (btnRealtime) btnRealtime.classList.toggle('active', enabled);
    if (statusDiv) statusDiv.style.display = enabled ? 'block' : 'none';
    
    if (enabled) {
        stopRealtimePolling();
        loadRealtimeKlineData(window.currentInterval);
    } else {
        stopRealtimePolling();
        window.loadKlineData(window.currentInterval);
    }
}