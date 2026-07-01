// structure_chart.js - 结构K线图渲染
// 使用 TradingView Lightweight Charts
// 显示标准化K线（包含关系处理后）

import { setStatus, updatePriceDisplay, updateDataTime } from 'utils/dom.js';
import { formatVolume } from 'utils/format.js';

let priceChart = null;
let volumeChart = null;
let candlestickSeries = null;
let volumeSeries = null;
let currentInterval = '1m';

// 分页数据管理
let allCandleData = [];
let allVolumeData = [];
let earliestTime = null;
let isLoadingMore = false;

// 原始K线叠加状态
let overlayEnabled = false;
let overlaySeries = null;
let overlayData = [];

// 初始化图表 - 主图 + 副图结构
function initChart() {
    const container = document.getElementById('chart-container');
    
    // 确保容器有有效高度（若为0则用默认值600px）
    const totalHeight = Math.max(container.clientHeight || 0, 600);
    const priceHeight = Math.floor(totalHeight * 0.7);
    const volumeHeight = totalHeight - priceHeight;
    
    // 创建主图容器
    const priceContainer = document.createElement('div');
    priceContainer.id = 'price-chart';
    priceContainer.style.height = priceHeight + 'px';
    
    // 创建副图容器
    const volumeContainer = document.createElement('div');
    volumeContainer.id = 'volume-chart';
    volumeContainer.style.height = volumeHeight + 'px';
    
    container.innerHTML = '';
    container.appendChild(priceContainer);
    container.appendChild(volumeContainer);
    
    // 图表通用配置 (Bybit 风格)
    const chartOptions = {
        layout: {
            background: { type: 'solid', color: '#0d0d1a' },
            textColor: '#a0a0b8',
            fontSize: 12,
        },
        grid: {
            vertLines: { color: '#1a1a2e' },
            horzLines: { color: '#1a1a2e' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: {
                color: '#3b6eff',
                width: 1,
                style: LightweightCharts.LineStyle.Dashed,
                labelBackgroundColor: '#3b6eff',
            },
            horzLine: {
                color: '#3b6eff',
                width: 1,
                style: LightweightCharts.LineStyle.Dashed,
                labelBackgroundColor: '#3b6eff',
            },
        },
        rightPriceScale: {
            borderColor: '#2b2b4a',
            borderVisible: true,
        },
        timeScale: {
            borderColor: '#2b2b4a',
            timeVisible: true,
            secondsVisible: false,
            borderVisible: true,
        },
        handleScroll: {
            vertTouchDrag: false,
        },
    };
    
    // 主图 - K线图 (Bybit 色系: #0ECB81 绿 / #F6465D 红)
    priceChart = LightweightCharts.createChart(priceContainer, {
        ...chartOptions,
        width: container.clientWidth,
        height: priceHeight,
    });
    
    candlestickSeries = priceChart.addCandlestickSeries({
        upColor: '#0ecb81',
        downColor: '#f6465d',
        borderUpColor: '#0ecb81',
        borderDownColor: '#f6465d',
        wickUpColor: '#0ecb81',
        wickDownColor: '#f6465d',
    });
    
    // 副图 - 成交量图
    volumeChart = LightweightCharts.createChart(volumeContainer, {
        ...chartOptions,
        width: container.clientWidth,
        height: volumeHeight,
    });
    
    volumeSeries = volumeChart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: 'right',
    });
    
    // 同步两个图表的时间轴（用 LogicalRange 避免微小偏差导致的同步问题）
    let syncing = false;
    let syncTimer = null;
    
    function safeSyncCharts(sourceChart, targetChart, logicalRange) {
        if (syncing || !logicalRange) return;
        syncing = true;
        if (syncTimer) clearTimeout(syncTimer);
        try {
            targetChart.timeScale().setVisibleLogicalRange(logicalRange);
        } catch (e) {}
        syncTimer = setTimeout(() => { syncing = false; syncTimer = null; }, 50);
    }
    
    priceChart.timeScale().subscribeVisibleLogicalRangeChange((logicalRange) => {
        safeSyncCharts(priceChart, volumeChart, logicalRange);
    });
    
    volumeChart.timeScale().subscribeVisibleLogicalRangeChange((logicalRange) => {
        safeSyncCharts(volumeChart, priceChart, logicalRange);
    });
    
    // 响应窗口大小变化
    window.addEventListener('resize', () => {
        const newTotalHeight = container.clientHeight;
        const newPriceHeight = Math.floor(newTotalHeight * 0.7);
        const newVolumeHeight = newTotalHeight - newPriceHeight;
        
        priceContainer.style.height = newPriceHeight + 'px';
        volumeContainer.style.height = newVolumeHeight + 'px';
        
        priceChart.applyOptions({
            width: container.clientWidth,
            height: newPriceHeight,
        });
        volumeChart.applyOptions({
            width: container.clientWidth,
            height: newVolumeHeight,
        });
    });

    // 十字光标移动事件 - 显示OHLC信息，右侧标注当前K线high/low
    let highPriceLine = null;
    let lowPriceLine = null;
    priceChart.subscribeCrosshairMove((param) => {
        if (highPriceLine) { candlestickSeries.removePriceLine(highPriceLine); highPriceLine = null; }
        if (lowPriceLine) { candlestickSeries.removePriceLine(lowPriceLine); lowPriceLine = null; }
        if (param.time) {
            const data = param.seriesData.get(candlestickSeries);
            if (data) {
                updatePriceDisplay(data);
                updateOHLCDisplay(param.time, data);
                highPriceLine = candlestickSeries.createPriceLine({
                    price: data.high,
                    color: '#ffaa00',
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: 'H',
                });
                lowPriceLine = candlestickSeries.createPriceLine({
                    price: data.low,
                    color: '#00aaff',
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: 'L',
                });
            }
        } else {
            if (allCandleData.length > 0) {
                const latest = allCandleData[allCandleData.length - 1];
                updateOHLCDisplay(latest.time, latest);
            }
        }
    });
    
    // 监听时间轴变化 - 检测是否滚动到最左侧（防抖300ms）
    let loadMoreTimer = null;
    priceChart.timeScale().subscribeVisibleLogicalRangeChange((logicalRange) => {
        if (!logicalRange || isLoadingMore) return;
        if (logicalRange.from < 10) {
            clearTimeout(loadMoreTimer);
            loadMoreTimer = setTimeout(() => {
                loadMoreHistory();
            }, 300);
        }
    });
}

// structure_chart.js 特有的 OHLC 扩展：显示合并K线数
function updateOHLCDisplay(time, data) {
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

    if (volEl) {
        const volumeItem = allVolumeData.find(v => v.time === time);
        if (volumeItem) {
            volEl.textContent = formatVolume(volumeItem.value);
        }
    }

    // 显示合并K线数（structure_chart 特有）
    const sourceCountEl = document.getElementById('ohlc-source-count');
    if (sourceCountEl && data.source_count) {
        sourceCountEl.textContent = data.source_count;
    }
}

// 加载结构K线数据 (初始加载)
async function loadKlineData(interval, limit = DEFAULT_LIMIT) {
    setStatus('加载中...');
    
    // 重置分页状态
    allCandleData = [];
    allVolumeData = [];
    earliestTime = null;
    
    // 清除叠加图层
    if (overlaySeries) {
        priceChart.removeSeries(overlaySeries);
        overlaySeries = null;
        overlayData = [];
    }
    
    try {
        const response = await fetch(`/api/structure_kline?interval=${interval}&limit=${limit || DEFAULT_LIMIT}`);
        if (!response.ok) {
            throw new Error('API请求失败');
        }
        
        const data = await response.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        if (data.length === 0) {
            setStatus('暂无数据');
            return;
        }
        
        // 过滤空值数据
        const validData = data.filter(item => 
            item.time != null && 
            item.open != null && 
            item.high != null && 
            item.low != null && 
            item.close != null
        );
        
        if (validData.length === 0) {
            setStatus('暂无有效数据');
            return;
        }
        
        // 转换数据格式（保留source_count和fractal_label）
        allCandleData = validData.map(item => ({
            time: item.time,
            open: item.open,
            high: item.high,
            low: item.low,
            close: item.close,
            source_count: item.source_count,
            start_time: item.start_time,
            end_time: item.end_time,
            fractal_label: item.fractal_label || 0,
        }));
        
        // 成交量颜色: 上涨绿色(#0ecb81), 下跌红色(#f6465d)
        allVolumeData = validData.map(item => ({
            time: item.time,
            value: item.volume || 0,
            color: item.close >= item.open ? '#0ecb81' : '#f6465d',
        }));
        
        // 记录最早时间 (毫秒)
        earliestTime = data[0].start_time;
        
        // 更新图表
        candlestickSeries.setData(allCandleData);
        volumeSeries.setData(allVolumeData);
        
        // 自动滚动到最新K线
        priceChart.timeScale().scrollToRealTime();
        volumeChart.timeScale().scrollToRealTime();
        
        // 同步绘制分型标记
        drawFractalMarkers();
        
        // 更新最新价格
        const latest = allCandleData[allCandleData.length - 1];
        updatePriceDisplay(latest);
        updateDataTime(latest.time);
        
        setStatus(`已加载 ${data.length} 条结构K线`);
        
    } catch (error) {
        console.error('加载数据失败:', error);
        setStatus(`错误: ${error.message}`);
    }
}

// 加载更多历史数据 (分页)
async function loadMoreHistory() {
    if (isLoadingMore || !earliestTime) return;
    
    isLoadingMore = true;
    setStatus('加载历史数据...');
    
    try {
        const response = await fetch(
            `/api/structure_kline?interval=${currentInterval}&limit=${DEFAULT_LIMIT}&before=${earliestTime}`
        );
        if (!response.ok) {
            throw new Error('API请求失败');
        }
        
        const data = await response.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        if (data.length === 0) {
            setStatus(`已加载全部历史数据 (${allCandleData.length} 条)`);
            isLoadingMore = false;
            return;
        }
        
        // 过滤空值数据
        const validData = data.filter(item => 
            item.time != null && 
            item.open != null && 
            item.high != null && 
            item.low != null && 
            item.close != null
        );
        
        if (validData.length === 0) {
            setStatus(`已加载全部历史数据 (${allCandleData.length} 条)`);
            isLoadingMore = false;
            return;
        }
        
        // 转换新数据
        const newCandleData = validData.map(item => ({
            time: item.time,
            open: item.open,
            high: item.high,
            low: item.low,
            close: item.close,
            source_count: item.source_count,
            start_time: item.start_time,
            end_time: item.end_time,
            fractal_label: item.fractal_label || 0,
        }));
        
        const newVolumeData = validData.map(item => ({
            time: item.time,
            value: item.volume || 0,
            color: item.close >= item.open ? '#0ecb81' : '#f6465d',
        }));
        
        // 合并数据 (新历史数据在前)
        allCandleData = [...newCandleData, ...allCandleData];
        allVolumeData = [...newVolumeData, ...allVolumeData];
        
        // 更新最早时间
        earliestTime = data[0].start_time;
        
        // 更新图表
        candlestickSeries.setData(allCandleData);
        volumeSeries.setData(allVolumeData);
        
        // 同步绘制分型标记
        drawFractalMarkers();
        
        setStatus(`已加载 ${allCandleData.length} 条结构K线`);
        
    } catch (error) {
        console.error('加载历史数据失败:', error);
        setStatus(`错误: ${error.message}`);
    }
    
    isLoadingMore = false;
}

// 加载数据统计
async function loadStats() {
    try {
        const response = await fetch('/api/structure_stats');
        const stats = await response.json();
        
        let html = '';
        for (const [interval, data] of Object.entries(stats)) {
            if (data.count > 0) {
                html += `<div>${interval}: ${data.count}条</div>`;
            }
        }
        
        document.getElementById('data-stats').innerHTML = html || '暂无数据';
        
    } catch (error) {
        document.getElementById('data-stats').textContent = '加载失败';
    }
}



// 切换时间周期
function switchInterval(interval) {
    if (interval === currentInterval) return;
    
    currentInterval = interval;
    
    // 更新按钮状态
    document.querySelectorAll('.interval-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.interval === interval) {
            btn.classList.add('active');
        }
    });
    
    // 重置叠加状态
    overlayEnabled = false;
    const overlayBtn = document.getElementById('overlay-btn');
    if (overlayBtn) overlayBtn.classList.remove('active');
    
    // 重新加载数据
    loadKlineData(interval);
}

// 绑定事件
function bindEvents() {
    document.querySelectorAll('.interval-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            switchInterval(btn.dataset.interval);
        });
    });
    
    // 原始K线叠加开关
    const overlayBtn = document.getElementById('overlay-btn');
    if (overlayBtn) {
        overlayBtn.addEventListener('click', toggleOverlay);
    }
}

// 切换原始K线叠加显示
async function toggleOverlay() {
    overlayEnabled = !overlayEnabled;
    const btn = document.getElementById('overlay-btn');
    
    if (overlayEnabled) {
        btn.classList.add('active');
        await loadOverlayData();
    } else {
        btn.classList.remove('active');
        clearOverlay();
    }
}

// 加载原始K线数据用于叠加
async function loadOverlayData() {
    if (allCandleData.length === 0) return;
    
    setStatus('加载原始K线...');
    
    // 获取当前结构K线的时间范围
    const startTime = allCandleData[0].start_time;
    const endTime = allCandleData[allCandleData.length - 1].end_time;
    
    try {
        const response = await fetch(
            `/api/source_kline?interval=${currentInterval}&start=${startTime}&end=${endTime}`
        );
        
        if (!response.ok) {
            throw new Error('加载原始K线失败');
        }
        
        const data = await response.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        if (data.length === 0) {
            setStatus('无原始K线数据');
            return;
        }
        
        // 转换数据格式
        overlayData = data.map(item => ({
            time: item.time,
            open: item.open,
            high: item.high,
            low: item.low,
            close: item.close,
        }));
        
        // 创建叠加K线系列（灰色半透明）
        if (!overlaySeries) {
            overlaySeries = priceChart.addCandlestickSeries({
                upColor: 'rgba(150, 150, 150, 0.4)',
                downColor: 'rgba(100, 100, 100, 0.4)',
                borderUpColor: 'rgba(150, 150, 150, 0.6)',
                borderDownColor: 'rgba(100, 100, 100, 0.6)',
                wickUpColor: 'rgba(150, 150, 150, 0.6)',
                wickDownColor: 'rgba(100, 100, 100, 0.6)',
            });
        }
        
        overlaySeries.setData(overlayData);
        
        setStatus(`已叠加 ${data.length} 条原始K线`);
        
    } catch (error) {
        console.error('加载原始K线失败:', error);
        setStatus(`错误: ${error.message}`);
    }
}

// 清除叠加K线
function clearOverlay() {
    if (overlaySeries) {
        priceChart.removeSeries(overlaySeries);
        overlaySeries = null;
        overlayData = [];
    }
    setStatus(`已加载 ${allCandleData.length} 条结构K线`);
}

// 绘制顶底分型标记（只取最近2000根K线，避免数据量过大导致渲染问题）
function drawFractalMarkers() {
    if (!candlestickSeries || allCandleData.length === 0) return;
    
    try {
        const markers = [];
        // 只处理最近的部分数据，避免 markers 过多
        const startIdx = Math.max(0, allCandleData.length - 2000);
        
        for (let i = startIdx; i < allCandleData.length; i++) {
            const item = allCandleData[i];
            if (!item || item.time == null) continue;
            
            if (item.fractal_label === 1) {
                markers.push({
                    time: item.time,
                    position: 'aboveBar',
                    color: '#f6465d',
                    shape: 'arrowDown',
                    text: '\u25B2',
                    size: 1,
                });
            } else if (item.fractal_label === -1) {
                markers.push({
                    time: item.time,
                    position: 'belowBar',
                    color: '#0ecb81',
                    shape: 'arrowUp',
                    text: '\u25BC',
                    size: 1,
                });
            }
        }
        
        candlestickSeries.setMarkers(markers);
    } catch (e) {
        console.warn('绘制分型标记失败:', e.message);
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    bindEvents();
    
    // 直接加载数据，requestAnimationFrame 会确保图表渲染时序
    loadKlineData('1m');
    loadStats();
});