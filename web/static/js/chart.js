// chart.js - ETH K线图渲染
// 使用 TradingView Lightweight Charts
// 主图(K线 70%) + 副图(成交量 30%)

// 防止 debug 模式热重载导致重复加载
if (typeof window.__chartJsLoaded !== 'undefined') {
    console.warn('[chart.js] 已加载，跳过');
} else {
    window.__chartJsLoaded = true;

window.priceChart = null;
window.volumeChart = null;
window.candlestickSeries = null;
window.volumeSeries = null;
window.currentInterval = '1m';

// 分页数据管理
window.allCandleData = [];
window.allVolumeData = [];
let earliestTime = null;
let isLoadingMore = false;
let isUpdatingData = false;  // 标志：是否正在更新数据（禁用滚动监听）

// 存储分型区间和对应的LineSeries（画水平线段用）
let fractalRegions = [];
let fractalLineSeries = [];

// 防抖加载
let loadMoreTimer = null;
let lastLogicalFrom = Infinity;


// 初始化图表 - 主图 + 副图结构
function initChart() {
    const container = document.getElementById('chart-container');
    const totalHeight = container.clientHeight;
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

    // 十字光标移动事件 - 显示OHLC信息
    priceChart.subscribeCrosshairMove((param) => {
        if (param.time) {
            const data = param.seriesData.get(candlestickSeries);
            if (data) {
                updatePriceDisplay(data);
                updateOHLCDisplay(param.time, data);
            }
        } else {
            // 鼠标离开图表时显示最新K线数据
            if (allCandleData.length > 0) {
                const latest = allCandleData[allCandleData.length - 1];
                updateOHLCDisplay(latest.time, latest);
            }
        }
    });
    
    // 监听时间轴变化 - 滚动到最左侧时加载更多历史数据（防抖300ms）
    priceChart.timeScale().subscribeVisibleLogicalRangeChange((logicalRange) => {
        // 数据更新期间跳过监听，避免抖动
        if (!logicalRange || isLoadingMore || isUpdatingData) return;
        
        // 只有向左滚动（from 变小）时才触发
        const isScrollingLeft = logicalRange.from < lastLogicalFrom;
        lastLogicalFrom = logicalRange.from;
        
        // 当可视范围接近数据最左侧（from < 10）时触发加载更多
        if (isScrollingLeft && logicalRange.from < 10 && earliestTime !== null) {
            clearTimeout(loadMoreTimer);
            loadMoreTimer = setTimeout(() => {
                loadMoreHistory();
            }, 300);
        }
    });
}

// 更新价格显示 (Bybit 风格)
function updatePriceDisplay(data) {
    const priceEl = document.getElementById('current-price');
    const changeEl = document.getElementById('price-change');
    const changeTextEl = document.getElementById('price-change-text');
    
    if (data && data.close) {
        priceEl.textContent = data.close.toFixed(2);
        
        const change = ((data.close - data.open) / data.open * 100);
        const changeText = change >= 0 ? `+${change.toFixed(2)}%` : `${change.toFixed(2)}%`;
        changeTextEl.textContent = changeText;
        
        if (change >= 0) {
            priceEl.style.color = '#0ecb81';
            changeEl.className = 'change';
        } else {
            priceEl.style.color = '#f6465d';
            changeEl.className = 'change negative';
        }
    }
}

// 更新OHLC信息显示
function updateOHLCDisplay(time, data) {
    const date = new Date(time * 1000);
    const timeStr = date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
    
    document.getElementById('ohlc-time').textContent = timeStr;
    document.getElementById('ohlc-open').textContent = data.open ? data.open.toFixed(2) : '--';
    document.getElementById('ohlc-high').textContent = data.high ? data.high.toFixed(2) : '--';
    document.getElementById('ohlc-low').textContent = data.low ? data.low.toFixed(2) : '--';
    document.getElementById('ohlc-close').textContent = data.close ? data.close.toFixed(2) : '--';
    
    // 获取对应的成交量
    const volumeItem = allVolumeData.find(v => v.time === time);
    if (volumeItem) {
        document.getElementById('ohlc-volume').textContent = formatVolume(volumeItem.value);
    }
}

// 格式化成交量
function formatVolume(vol) {
    if (vol >= 1000000) {
        return (vol / 1000000).toFixed(2) + 'M';
    } else if (vol >= 1000) {
        return (vol / 1000).toFixed(2) + 'K';
    }
    return vol.toFixed(2);
}

// 加载K线数据 (初始加载)
async function loadKlineData(interval, limit = DEFAULT_LIMIT) {
    setStatus('加载中...');
    
    // 重置分页状态
    allCandleData = [];
    allVolumeData = [];
    earliestTime = null;
    clearFractalRegions();
    
    try {
        const response = await fetch(`/api/kline?interval=${interval}&limit=${limit}`);
        if (!response.ok) {
            throw new Error('API请求失败');
        }
        
        const result = await response.json();
        
        if (result.error) {
            throw new Error(result.error);
        }
        
        // 新格式：{ data: [...], fractal_regions: [...] }
        const data = result.data || result;
        const regions = result.fractal_regions || [];
        
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
        
        // 转换数据格式
        allCandleData = validData.map(item => ({
            time: item.time,
            open: item.open,
            high: item.high,
            low: item.low,
            close: item.close,
        }));
        
        // 成交量颜色: 上涨绿色(#0ecb81), 下跌红色(#f6465d)
        allVolumeData = validData.map(item => ({
            time: item.time,
            value: item.volume || 0,
            color: item.close >= item.open ? '#0ecb81' : '#f6465d',
        }));
        
        // 记录最早时间 (毫秒)
        earliestTime = data[0].time * 1000;
        
        // 设置标志，禁用滚动监听，避免抖动
        isUpdatingData = true;
        
        // 更新图表
        candlestickSeries.setData(allCandleData);
        volumeSeries.setData(allVolumeData);
        
        // 自动滚动到最新K线（用 try-catch 保护，避免 null 报错）
        try { priceChart.timeScale().scrollToRealTime(); } catch(e) {}
        try { volumeChart.timeScale().scrollToRealTime(); } catch(e) {}
        
        // 延迟恢复滚动监听（给图表渲染时间）
        setTimeout(() => {
            isUpdatingData = false;
        }, 100);
        
        // 保存分型区间并绘制水平线
        fractalRegions = regions;
        drawFractalRegions();
        
        // 更新最新价格
        const latest = data[data.length - 1];
        updatePriceDisplay(latest);
        updateDataTime(latest.time);
        
        setStatus(`已加载 ${data.length} 条数据`);
        
    } catch (error) {
        console.error('加载数据失败:', error);
        setStatus(`错误: ${error.message}`);
    }
}

// 加载更多历史数据 (滚动分页)
async function loadMoreHistory() {
    if (isLoadingMore || earliestTime === null || earliestTime === 'end') return;
    
    isLoadingMore = true;
    setStatus('加载历史数据...');
    
    // 清除旧的分型框（稍后重新绘制）
    clearFractalRegions();
    
    try {
        const response = await fetch(
            `/api/kline?interval=${currentInterval}&limit=${DEFAULT_LIMIT}&before=${earliestTime}`
        );
        if (!response.ok) {
            throw new Error('API请求失败');
        }
        
        const result = await response.json();
        
        if (result.error) {
            throw new Error(result.error);
        }
        
        const data = result.data || result;
        const regions = result.fractal_regions || [];
        
        if (data.length === 0) {
            setStatus(`已加载全部历史数据 (${allCandleData.length} 条)`);
            earliestTime = 'end';  // 标记已到尽头，不再请求
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
            earliestTime = 'end';
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
        }));
        
        const newVolumeData = validData.map(item => ({
            time: item.time,
            value: item.volume || 0,
            color: item.close >= item.open ? '#0ecb81' : '#f6465d',
        }));
        
        // 合并数据 (新历史数据在前)
        allCandleData = [...newCandleData, ...allCandleData];
        allVolumeData = [...newVolumeData, ...allVolumeData];
        
        // 合并分型区间
        fractalRegions = [...regions, ...fractalRegions];
        
        // 更新最早时间
        earliestTime = data[0].time * 1000;

        // 更新图表（和结构K线一样简单）
        candlestickSeries.setData(allCandleData);
        volumeSeries.setData(allVolumeData);
        
        drawFractalRegions();
        
        setStatus(`已加载 ${allCandleData.length} 条数据`);
        
    } catch (error) {
        console.error('加载历史数据失败:', error);
        setStatus(`错误: ${error.message}`);
    }
    
    isLoadingMore = false;
}

// 加载数据统计
async function loadStats() {
    try {
        const response = await fetch('/api/stats');
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

// 设置状态 (带图标)
function setStatus(text) {
    const el = document.getElementById('status');
    if (text.startsWith('✔')) {
        el.textContent = text;
        el.className = '';
    } else if (text.startsWith('错误') || text.includes('失败') || text.startsWith('❌')) {
        el.innerHTML = '✖ ' + text.replace(/[❌✖]/g, '').trim();
        el.className = 'error';
    } else if (text.startsWith('⏳') || text.includes('加载中') || text.includes('加载历史')) {
        el.innerHTML = '⟳ ' + text.replace(/[⏳]/g, '').trim();
        el.className = 'loading';
    } else if (text.startsWith('✅')) {
        el.innerHTML = '✔ ' + text.replace(/[✅]/g, '').trim();
        el.className = '';
    } else {
        el.textContent = text;
        el.className = '';
    }
}

// 更新数据时间
function updateDataTime(timestamp) {
    const date = new Date(timestamp * 1000);
    const timeStr = date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
    document.getElementById('data-time').textContent = `最新: ${timeStr}`;
}

// 切换时间周期
function switchInterval(interval) {
    if (interval === window.currentInterval) return;
    
    window.currentInterval = interval;
    
    // 更新按钮状态
    document.querySelectorAll('.interval-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.interval === interval) {
            btn.classList.add('active');
        }
    });
    
    // 重新加载数据
    loadKlineData(interval);
}

// 绑定事件
function bindEvents() {
    // 只选择有时间周期 data 属性的按钮（排除数据源切换按钮）
    document.querySelectorAll('.interval-btn[data-interval]').forEach(btn => {
        btn.addEventListener('click', () => {
            switchInterval(btn.dataset.interval);
        });
    });
    
}

// 绘制分型区间水平线 + 顶底分型左端点连线
function drawFractalRegions() {
    clearFractalRegions();
    if (!priceChart || fractalRegions.length === 0) return;
    
    // 按时间排序
    const sorted = [...fractalRegions].sort((a, b) => a.start_time - b.start_time);
    
    // 收集左端点（用于画连线）
    const leftPoints = [];
    
    for (const region of sorted) {
        if (region.start_time == null || region.end_time == null) continue;
        if (region.high == null || region.low == null) continue;
        
        const isTop = region.label === 1;
        const lineValue = isTop ? region.high : region.low;
        
        // 每个分型独立画一条水平线段
        const lineSeries = priceChart.addLineSeries({
            color: isTop ? '#f6465d' : '#0ecb81',
            lineWidth: 2,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
        });
        lineSeries.setData([
            { time: region.start_time, value: lineValue },
            { time: region.end_time, value: lineValue },
        ]);
        fractalLineSeries.push(lineSeries);
        
        // 记录左端点
        leftPoints.push({
            time: region.start_time,
            value: lineValue,
        });
    }
    
    // 左端点连线（蓝色虚线）
    if (leftPoints.length >= 2) {
        leftPoints.sort((a, b) => a.time - b.time);
        const connectSeries = priceChart.addLineSeries({
            color: '#3b6eff',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: true,
        });
        connectSeries.setData(leftPoints);
        fractalLineSeries.push(connectSeries);
    }
}

// 清除分型水平线
function clearFractalRegions() {
    if (!priceChart) return;
    for (const series of fractalLineSeries) {
        try { priceChart.removeSeries(series); } catch(e) {}
    }
    fractalLineSeries = [];
}

// ======================== 回测引擎（资金管理版） ========================

let backtestResult = null;  // 保存回测结果
let isBacktestRunning = false;  // 防止重复提交标志

// 更新缓存状态指示灯
function updateCacheStatus(status) {
    const el = document.getElementById('cache-status');
    if (!el) return;
    
    // status: 'hit'(命中-绿), 'miss'(未命中-黄), 'offline'(关闭-红)
    el.className = 'cache-status ' + status;
    const titles = {
        'hit': '缓存命中',
        'miss': '缓存未命中',
        'offline': '缓存已禁用'
    };
    el.title = titles[status] || '缓存状态';
}

// 获取当前回测参数（用于缓存key）
function getBacktestParams() {
    return {
        interval: currentInterval,
        start_date: document.getElementById('bt-start-date').value || '',
        end_date: document.getElementById('bt-end-date').value || '',
        mode: document.getElementById('bt-mode').value,
        stop_loss_pct: parseFloat(document.getElementById('bt-stoploss').value),
        take_profit_pct: parseFloat(document.getElementById('bt-takeprofit').value),
        initial_capital: parseFloat(document.getElementById('bt-capital').value),
        fee_rate: parseFloat(document.getElementById('bt-fee').value),
        position_mode: document.getElementById('bt-pos-mode').value,
        percent_per_trade: parseFloat(document.getElementById('bt-pos-percent').value),
        fixed_amount: parseFloat(document.getElementById('bt-pos-fixed').value),
        max_positions: parseInt(document.getElementById('bt-max-pos').value),
        use_stop_profit: document.getElementById('bt-use-stop-profit').checked,
    };
}

// 清除回测缓存
async function clearBacktestCache(clearAll = false) {
    try {
        const params = clearAll ? {} : { params: getBacktestParams() };
        const response = await fetch('/api/backtest/cache/clear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params)
        });
        
        const result = await response.json();
        if (result.error) {
            setStatus(`❌ 清除缓存失败: ${result.error}`);
        } else {
            setStatus(`✅ ${result.message}`);
            updateCacheStatus('miss');
        }
    } catch (error) {
        setStatus(`❌ 清除缓存失败: ${error.message}`);
    }
}

// 获取缓存统计
async function loadCacheStats() {
    try {
        const response = await fetch('/api/backtest/cache/stats');
        const stats = await response.json();
        if (!stats.error) {
            console.log('[Cache Stats]', stats);
            // 如果有有效缓存条目，显示绿色
            if (stats.valid_entries > 0) {
                updateCacheStatus('hit');
            } else {
                updateCacheStatus('miss');
            }
        }
    } catch (e) {
        console.error('获取缓存统计失败:', e);
    }
}

// 显示回测结果（立即执行，不处理交易明细）
function displayBacktestResult(result) {
    backtestResult = backtestResult || {};
    Object.assign(backtestResult, result);

    const resultDiv = document.getElementById('backtest-result');
    resultDiv.style.display = 'block';

    document.getElementById('bt-trades').textContent = result.totalTrades + '笔';
    document.getElementById('bt-winrate').textContent = result.winRate.toFixed(1) + '%';

    const returnEl = document.getElementById('bt-return');
    returnEl.textContent = (result.totalReturn >= 0 ? '+' : '') + result.totalReturn.toFixed(2) + '%';
    returnEl.className = 'result-value ' + (result.totalReturn >= 0 ? 'positive' : 'negative');

    const ddEl = document.getElementById('bt-drawdown');
    ddEl.textContent = result.maxDdPct.toFixed(2) + '%';
    ddEl.className = 'result-value negative';

    // 只显示按钮，不处理交易数据
    const detailBtn = document.getElementById('bt-detail-btn');
    if (result.totalTrades > 0) {
        detailBtn.style.display = 'block';
    } else {
        detailBtn.style.display = 'none';
    }
}

async function runBacktest() {
    // 防止重复点击 - 如果回测正在执行，直接返回
    if (isBacktestRunning) {
        setStatus('⏳ 回测正在执行中，请稍候...');
        return;
    }
    
    // 设置执行标志并禁用按钮
    isBacktestRunning = true;
    const runBtn = document.getElementById('bt-run');
    const originalBtnText = runBtn.textContent;
    runBtn.disabled = true;
    runBtn.textContent = '⏳ 回测中...';
    
    try {
        // 读取参数
        const skipCache = document.getElementById('bt-skip-cache').checked;
        const params = {
            interval: currentInterval,
            start_date: document.getElementById('bt-start-date').value || '',
            end_date: document.getElementById('bt-end-date').value || '',
            mode: document.getElementById('bt-mode').value,
            stop_loss_pct: parseFloat(document.getElementById('bt-stoploss').value),
            take_profit_pct: parseFloat(document.getElementById('bt-takeprofit').value),
            initial_capital: parseFloat(document.getElementById('bt-capital').value),
            fee_rate: parseFloat(document.getElementById('bt-fee').value),
            position_mode: document.getElementById('bt-pos-mode').value,
            percent_per_trade: parseFloat(document.getElementById('bt-pos-percent').value),
            fixed_amount: parseFloat(document.getElementById('bt-pos-fixed').value),
            max_positions: parseInt(document.getElementById('bt-max-pos').value),
            use_stop_profit: document.getElementById('bt-use-stop-profit').checked,
            _skip_cache: skipCache,
        };

        // 更新缓存状态指示
        if (skipCache) {
            updateCacheStatus('offline');
        }

    setStatus('⏳ 正在服务端执行全量回测...');

        const startTime = performance.now();
        const response = await fetch('/api/backtest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params),
        });

        const result = await response.json();
        const fetchTime = performance.now() - startTime;

        if (result.error) {
            setStatus(`❌ ${result.error}`);
            return;
        }

        // 检查缓存命中状态
        if (result._cache_hit) {
            updateCacheStatus('hit');
            console.log(`[Backtest] 缓存命中，缓存时间: ${new Date(result._cached_at * 1000).toLocaleString()}`);
        } else if (!skipCache) {
            updateCacheStatus('miss');
        }

        // 【关键优化】立即显示统计结果和状态，不等待交易数据处理
        const cacheInfo = result._cache_hit ? ' [缓存]' : '';
        setStatus(
            `✅ 回测完成${cacheInfo}: ${result.summary.total_trades}笔交易, ` +
            `收益${result.summary.total_return >= 0 ? '+' : ''}${result.summary.total_return}% ` +
            `(${fetchTime.toFixed(0)}ms)`
        );

        // 立即显示统计数字（不处理交易明细）
        displayBacktestResult({
            totalTrades: result.summary.total_trades,
            winRate: result.summary.win_rate,
            totalReturn: result.summary.total_return,
            maxDdPct: result.summary.max_drawdown,
        });

        // 【关键优化】延迟处理交易数据，不阻塞UI
        setTimeout(() => {
            // 转换交易数据（snake_case -> camelCase）
            const mappedTrades = (result.trades || []).map(t => ({
                direction: t.direction,
                entryTime: t.entry_time,
                exitTime: t.exit_time,
                entryPrice: t.entry_price,
                exitPrice: t.exit_price,
                amount: t.amount,
                pnl: t.pnl,
                pnlPct: t.pnl_pct,
                fee: t.fee,
                reason: t.reason,
            }));

            // 保存完整结果
            backtestResult = {
                ...backtestResult,
                trades: mappedTrades,
                equityCurve: result.equity_curve,
                capital: result.summary.final_capital,
                cacheHit: result._cache_hit || false,
            };

            console.log(`[Backtest] 交易数据处理完成: ${mappedTrades.length}笔交易`);
        }, 0);

    } catch (error) {
        setStatus(`❌ 回测失败: ${error.message}`);
    } finally {
        // 恢复按钮状态
        isBacktestRunning = false;
        runBtn.disabled = false;
        runBtn.textContent = originalBtnText;
    }
}

// 打开交易明细弹窗（分批渲染优化版）
function openTradeDetail() {
    const trades = backtestResult && backtestResult.trades;
    if (!trades || trades.length === 0) return;
    
    const tbody = document.getElementById('trade-table-body');
    const BATCH_SIZE = 50; // 每帧渲染50行
    
    // 先显示弹窗和加载提示
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;color:#888;padding:20px;">加载中... (0/' + trades.length + ')</td></tr>';
    document.getElementById('modal-overlay').style.display = 'flex';
    
    let index = 0;
    
    // 创建单行数据
    function createTradeRow(t, i) {
        const tr = document.createElement('tr');
        
        const entryTimeStr = t.entryTime ? new Date(t.entryTime * 1000).toLocaleString('zh-CN', {
            year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
        }) : '--';
        const exitTimeStr = t.exitTime ? new Date(t.exitTime * 1000).toLocaleString('zh-CN', {
            year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
        }) : '--';
        
        const pnlPctVal = t.pnlPct != null ? t.pnlPct : 0;
        const pnlVal = t.pnl != null ? t.pnl : 0;
        const feeVal = t.fee != null ? t.fee : 0;
        
        tr.innerHTML = `
            <td>${i + 1}</td>
            <td class="${t.direction === '多' ? 'trade-dir-long' : 'trade-dir-short'}">${t.direction}</td>
            <td style="font-size:10px;color:#aaaacc;">${entryTimeStr}</td>
            <td style="font-size:10px;color:#aaaacc;">${exitTimeStr}</td>
            <td>${t.entryPrice != null ? t.entryPrice.toFixed(2) : '--'}</td>
            <td>${t.exitPrice != null ? t.exitPrice.toFixed(2) : '--'}</td>
            <td class="${pnlVal >= 0 ? 'trade-pnl-positive' : 'trade-pnl-negative'}">${(pnlVal >= 0 ? '+' : '') + pnlVal.toFixed(2)}</td>
            <td style="color:#ffaa00;">${feeVal.toFixed(2)}</td>
            <td class="${pnlPctVal >= 0 ? 'trade-pnl-positive' : 'trade-pnl-negative'}">${(pnlPctVal >= 0 ? '+' : '') + pnlPctVal.toFixed(2)}%</td>
            <td style="font-family:Microsoft YaHei,sans-serif;font-size:10px;">${t.reason}</td>
        `;
        return tr;
    }
    
    // 分批渲染
    function renderBatch() {
        // 首次渲染时清空加载提示
        if (index === 0) tbody.innerHTML = '';
        
        const fragment = document.createDocumentFragment();
        const end = Math.min(index + BATCH_SIZE, trades.length);
        
        for (; index < end; index++) {
            fragment.appendChild(createTradeRow(trades[index], index));
        }
        
        tbody.appendChild(fragment);
        
        // 更新加载进度
        if (index < trades.length) {
            const progress = Math.round((index / trades.length) * 100);
            // 继续下一帧
            requestAnimationFrame(renderBatch);
        } else {
            console.log(`[TradeDetail] 渲染完成: ${trades.length}笔交易`);
        }
    }
    
    // 开始分批渲染
    requestAnimationFrame(renderBatch);
}

// 显示资产曲线弹窗
function showEquityChart() {
    const result = backtestResult;
    if (!result || !result.equityCurve || result.equityCurve.length < 2) {
        setStatus('没有资产曲线数据');
        return;
    }

    // 创建或获取资产曲线弹窗
    let eqModal = document.getElementById('equity-modal');
    if (!eqModal) {
        eqModal = document.createElement('div');
        eqModal.id = 'equity-modal';
        eqModal.className = 'modal-overlay';
        eqModal.style.display = 'flex';
        eqModal.innerHTML = `
            <div class="modal-panel" style="width:90vw;max-width:900px;height:70vh;">
                <div class="modal-header">
                    <span class="modal-title" style="color:#0ecb81;">资产曲线</span>
                    <span class="modal-close" id="equity-modal-close">✕</span>
                </div>
                <div class="modal-body" style="flex:1;padding:10px;">
                    <div id="equity-chart-container" style="width:100%;height:100%;"></div>
                </div>
                <div style="padding:6px 16px;display:flex;gap:16px;border-top:1px solid #3a3a5c;font-size:11px;color:#8888aa;">
                    <span>初始资金: <b style="color:#e0e0e0;">${result.equityCurve[0].equity.toFixed(2)}</b></span>
                    <span>最终资金: <b style="color:#e0e0e0;">${result.capital.toFixed(2)}</b></span>
                </div>
            </div>
        `;
        document.body.appendChild(eqModal);

        document.getElementById('equity-modal-close').addEventListener('click', () => {
            eqModal.style.display = 'none';
        });
        eqModal.addEventListener('click', (e) => {
            if (e.target === eqModal) eqModal.style.display = 'none';
        });
    }

    eqModal.style.display = 'flex';

    // 等DOM渲染完成后再画图
    setTimeout(() => {
        const container = document.getElementById('equity-chart-container');
        if (!container) return;

        // 清除旧图表
        container.innerHTML = '';

        const chart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: container.clientHeight,
            layout: {
                background: { type: 'solid', color: '#0d0d1a' },
                textColor: '#a0a0b8',
                fontSize: 12,
            },
            grid: {
                vertLines: { color: '#1a1a2e' },
                horzLines: { color: '#1a1a2e' },
            },
            rightPriceScale: {
                borderColor: '#2b2b4a',
                scaleMargins: { top: 0.1, bottom: 0.2 },
            },
            timeScale: {
                borderColor: '#2b2b4a',
                timeVisible: true,
                secondsVisible: false,
            },
            crosshair: {
                vertLine: { color: '#3b6eff', width: 1, style: LightweightCharts.LineStyle.Dashed },
                horzLine: { color: '#3b6eff', width: 1, style: LightweightCharts.LineStyle.Dashed },
            },
        });

        const lineSeries = chart.addLineSeries({
            color: '#0ecb81',
            lineWidth: 2,
            crosshairMarkerVisible: true,
            crosshairMarkerRadius: 4,
            priceLineVisible: false,
            lastValueVisible: true,
            title: '资产',
        });

        lineSeries.setData(result.equityCurve);

        chart.timeScale().fitContent();

        // 窗口resize重新计算
        const resizeHandler = () => {
            chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
        };
        window.addEventListener('resize', resizeHandler);
        // 弹窗关闭时清理
        const closeHandler = () => {
            window.removeEventListener('resize', resizeHandler);
            eqModal.removeEventListener('click', closeHandler);
        };
        document.getElementById('equity-modal-close').addEventListener('click', closeHandler, { once: true });

        // 添加基准线（初始资金）
        const baseSeries = chart.addLineSeries({
            color: '#f0b90b',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            crosshairMarkerVisible: false,
            priceLineVisible: false,
            lastValueVisible: false,
            title: '基准',
        });
        baseSeries.setData([
            { time: result.equityCurve[0].time, value: result.equityCurve[0].equity },
            { time: result.equityCurve[result.equityCurve.length - 1].time, value: result.equityCurve[0].equity },
        ]);
    }, 50);
}

// 导出交易明细为CSV文件
function exportTradeCSV() {
    const trades = backtestResult && backtestResult.trades;
    if (!trades || trades.length === 0) {
        setStatus('没有交易数据可导出');
        return;
    }

    // CSV头（加BOM让Excel正确识别UTF-8）
    let csv = '\uFEFF';
    csv += '序号,方向,开仓时间,平仓时间,开仓价,平仓价,已实现盈亏,手续费,盈亏%,原因\r\n';

    for (let i = 0; i < trades.length; i++) {
        const t = trades[i];
        const entryTimeStr = t.entryTime ? new Date(t.entryTime * 1000).toLocaleString('zh-CN') : '--';
        const exitTimeStr = t.exitTime ? new Date(t.exitTime * 1000).toLocaleString('zh-CN') : '--';
        const pnlAmount = (t.pnl >= 0 ? '+' : '') + t.pnl.toFixed(2);
        const pnlPct = (t.pnlPct >= 0 ? '+' : '') + t.pnlPct.toFixed(2) + '%';
        
        const feeAmount = t.fee != null ? t.fee.toFixed(2) : '0.00';
        csv += `${i + 1},${t.direction},${entryTimeStr},${exitTimeStr},${t.entryPrice != null ? t.entryPrice.toFixed(2) : '--'},${t.exitPrice != null ? t.exitPrice.toFixed(2) : '--'},${pnlAmount},${feeAmount},${pnlPct},${t.reason}\r\n`;
    }

    // 下载文件
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `回测交易明细_${new Date().toLocaleDateString('zh-CN').replace(/\//g, '-')}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(link.href);

    setStatus(`已导出 ${trades.length} 笔交易`);
}

// 导出交易明细为XLSX文件（使用SheetJS）
function exportTradeXLSX() {
    const trades = backtestResult && backtestResult.trades;
    if (!trades || trades.length === 0) {
        setStatus('没有交易数据可导出');
        return;
    }

    // 构建表格数据
    const rows = [['序号', '方向', '开仓时间', '平仓时间', '开仓价', '平仓价', '已实现盈亏', '手续费', '盈亏%', '原因']];
    for (let i = 0; i < trades.length; i++) {
        const t = trades[i];
        const entryTimeStr = t.entryTime ? new Date(t.entryTime * 1000).toLocaleString('zh-CN') : '--';
        const exitTimeStr = t.exitTime ? new Date(t.exitTime * 1000).toLocaleString('zh-CN') : '--';
        const pnlAmount = (t.pnl >= 0 ? '+' : '') + t.pnl.toFixed(2);
        const pnlPct = (t.pnlPct >= 0 ? '+' : '') + t.pnlPct.toFixed(2) + '%';
        
        const feeAmount = t.fee != null ? t.fee.toFixed(2) : '0.00';
        rows.push([
            i + 1,
            t.direction,
            entryTimeStr,
            exitTimeStr,
            t.entryPrice != null ? t.entryPrice.toFixed(2) : '--',
            t.exitPrice != null ? t.exitPrice.toFixed(2) : '--',
            pnlAmount,
            feeAmount,
            pnlPct,
            t.reason
        ]);
    }

    try {
        // 用 SheetJS 创建工作簿
        const wb = XLSX.utils.book_new();
        const ws = XLSX.utils.aoa_to_sheet(rows);
        // 设置列宽
        ws['!cols'] = [
            { wch: 5 },   // 序号
            { wch: 6 },   // 方向
            { wch: 18 },  // 开仓时间
            { wch: 18 },  // 平仓时间
            { wch: 10 },  // 开仓价
            { wch: 10 },  // 平仓价
            { wch: 14 },  // 已实现盈亏
            { wch: 10 },  // 手续费
            { wch: 10 },  // 盈亏%
            { wch: 12 },  // 原因
        ];
        XLSX.utils.book_append_sheet(wb, ws, '交易明细');

        // 生成文件并下载
        const wbout = XLSX.write(wb, { bookType: 'xlsx', type: 'array' });
        const blob = new Blob([wbout], { type: 'application/octet-stream' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `回测交易明细_${new Date().toLocaleDateString('zh-CN').replace(/\//g, '-')}.xlsx`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);

        setStatus(`已导出 ${trades.length} 笔交易`);
    } catch (e) {
        console.error('导出XLSX失败:', e);
        setStatus('导出失败: ' + e.message);
    }
}

// 初始化回测面板事件
function initBacktest() {
    // 折叠/展开
    const toggle = document.getElementById('backtest-toggle');
    const body = document.getElementById('backtest-body');
    const arrow = document.getElementById('backtest-arrow');
    
    toggle.addEventListener('click', () => {
        const isExpanded = body.classList.toggle('expanded');
        arrow.classList.toggle('expanded', isExpanded);
    });
    
    // 注入状态显示函数给校验器
    setStatusReporter(setStatus);
    
    // 绑定实时表单校验（输入不合法时回测按钮变灰不可点击）
    const formChecker = bindFormValidation({
        inputIds: [
            'bt-stoploss', 'bt-takeprofit', 'bt-capital', 'bt-fee',
            'bt-max-pos'
        ],
        buttonId: 'bt-run',
        optionalIds: ['bt-pos-percent', 'bt-pos-fixed'],
        rules: {
            'bt-stoploss':    { min: 0.01, max: 100 },
            'bt-takeprofit':  { min: 0.01, max: 100 },
            'bt-capital':     { min: 1 },
            'bt-fee':         { min: 0, max: 100 },
            'bt-pos-percent': { min: 0.1, max: 100, required: false },
            'bt-pos-fixed':   { min: 1, required: false },
            'bt-max-pos':     { isInt: true, min: 1, max: 100 },
        },
    });

    // 仓位模式切换：显示/隐藏对应参数行，并重新校验
    document.getElementById('bt-pos-mode').addEventListener('change', function() {
        const isPercent = this.value === 'percent';
        document.getElementById('bt-percent-row').style.display = isPercent ? 'flex' : 'none';
        document.getElementById('bt-fixed-row').style.display = isPercent ? 'none' : 'flex';
        // 切换后重新校验按钮状态
        if (formChecker) formChecker();
    });
    
    // 开始回测
    document.getElementById('bt-run').addEventListener('click', runBacktest);
    
    // 查看交易明细
    document.getElementById('bt-detail-btn').addEventListener('click', openTradeDetail);
    
    // 资产曲线
    document.getElementById('bt-equity-btn').addEventListener('click', showEquityChart);

    // 导出下拉框
    document.getElementById('bt-export-select').addEventListener('change', function() {
        const format = this.value;
        if (!format) return;
        if (format === 'csv') {
            exportTradeCSV();
        } else if (format === 'xlsx') {
            exportTradeXLSX();
        }
        this.value = '';  // 重置为占位选项
    });
    
    // 缓存控制按钮
    document.getElementById('bt-clear-cache').addEventListener('click', () => {
        clearBacktestCache(false);
    });
    document.getElementById('bt-clear-all-cache').addEventListener('click', () => {
        clearBacktestCache(true);
    });
    
    // 跳过缓存切换时更新状态
    document.getElementById('bt-skip-cache').addEventListener('change', function() {
        if (this.checked) {
            updateCacheStatus('offline');
        } else {
            loadCacheStats();
        }
    });
    
    // 初始化时加载缓存统计
    loadCacheStats();
    
    // 关闭弹窗
    document.getElementById('modal-close').addEventListener('click', () => {
        document.getElementById('modal-overlay').style.display = 'none';
    });
    
    // 点击遮罩关闭
    document.getElementById('modal-overlay').addEventListener('click', (e) => {
        if (e.target === document.getElementById('modal-overlay')) {
            document.getElementById('modal-overlay').style.display = 'none';
        }
    });
}

// 暴露图表实例和函数给实时模块
// 注意：变量已在顶部定义为 window.xxx，这里只需要暴露函数
window.drawFractalRegions = drawFractalRegions;
window.loadKlineData = loadKlineData;
window.setStatus = setStatus;
window.updatePriceDisplay = updatePriceDisplay;
window.updateDataTime = updateDataTime;

// 在 DOMContentLoaded 中追加
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    bindEvents();
    loadKlineData('1m');
    loadStats();
    initBacktest();
});

} // end of if (!window.__chartJsLoaded)