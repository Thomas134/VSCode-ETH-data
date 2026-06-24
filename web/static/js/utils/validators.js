/**
 * validators.js - 通用表单校验工具
 * 
 * 提供统一的输入校验函数，校验失败时自动高亮错误框并设置状态信息。
 * 
 * 用法：
 *   const val = validateInput('bt-stoploss', '止损%', { min: 0.1, max: 100 });
 *   if (val === null) return;  // 校验失败，已自动提示
 *   
 *   const val2 = validateInput('bt-fee', '费率%', { min: 0 });
 *   if (val2 === null) return;
 *   const fee = val2 / 100;   // 按需转换
 */

// 错误信息显示回调（由 setStatus 注入，解耦状态栏依赖）
let statusReporter = null;

/**
 * 注入状态信息显示函数
 * @param {function(string): void} fn - 显示状态信息的函数
 */
function setStatusReporter(fn) {
    statusReporter = fn;
}

/**
 * 校验并读取一个输入框的数值
 * 
 * @param {string} id        - 元素ID
 * @param {string} label     - 显示名称（错误提示用）
 * @param {object} [opts]    - 选项
 * @param {boolean} [opts.required=true]  - 是否必填
 * @param {number}  [opts.min]            - 最小值（含）
 * @param {number}  [opts.max]            - 最大值（含）
 * @param {boolean} [opts.isInt=false]    - 是否强制整数
 * @param {boolean} [opts.positive=true]  - 是否必须为正数（设为 false 允许 0 和负数）
 * @returns {number|null} 校验通过返回数值，不通过返回 null
 */
function validateInput(id, label, opts = {}) {
    const el = document.getElementById(id);
    if (!el) {
        reportError(`找不到输入框 "${id}"`);
        return null;
    }

    const raw = el.value.trim();
    const required = opts.required !== false;

    // ── 空值检查 ──
    if (!raw) {
        if (!required) return null;
        reportError(`${label} 不能为空`);
        focusEl(el);
        return null;
    }

    // ── 数字解析 ──
    const num = opts.isInt ? parseInt(raw, 10) : parseFloat(raw);

    if (isNaN(num)) {
        reportError(`${label} 必须是一个有效数字，当前值: "${raw}"`);
        focusEl(el);
        return null;
    }

    if (!isFinite(num)) {
        reportError(`${label} 数值不合法 (Infinity)`);
        focusEl(el);
        return null;
    }

    // ── 检查原始值是否包含多余字符（如 "3.ss" parseFloat 会返回 3，但实际不合法）──
    // 把解析结果转回字符串，跟原始值去掉首尾空格后比较
    // 不一样说明用户输入了多余字符
    if (String(num) !== raw) {
        // 特殊情况：整数模式允许 "3" 等价于 3，但 "3.ss" 不行
        // 用正则限制：只能包含数字、小数点、负号（且只有一个）
        const sanitized = raw.replace(/^[-+]?\d*\.?\d*$/, '');
        if (sanitized.length > 0) {
            reportError(`${label} 包含了非法字符，当前值: "${raw}"`);
            focusEl(el);
            return null;
        }
    }

    // ── 正数检查 ──
    if (opts.positive !== false && num <= 0) {
        reportError(`${label} 必须大于 0，当前值: ${num}`);
        focusEl(el);
        return null;
    }

    // ── 范围检查 ──
    if (opts.min !== undefined && num < opts.min) {
        reportError(`${label} 不能小于 ${opts.min}，当前值: ${num}`);
        focusEl(el);
        return null;
    }

    if (opts.max !== undefined && num > opts.max) {
        reportError(`${label} 不能大于 ${opts.max}，当前值: ${num}`);
        focusEl(el);
        return null;
    }

    // ── 清除错误高亮 ──
    el.style.outline = '';
    return num;
}

/**
 * 校验下拉选择框
 * @param {string} id - 元素ID
 * @param {string} label - 显示名称
 * @param {string[]} validValues - 允许的值列表
 * @returns {string|null} 校验通过返回选中的值
 */
function validateSelect(id, label, validValues) {
    const el = document.getElementById(id);
    if (!el) {
        reportError(`找不到选择框 "${id}"`);
        return null;
    }

    const val = el.value;
    if (validValues && !validValues.includes(val)) {
        reportError(`${label} 选项不合法`);
        focusEl(el);
        return null;
    }

    return val;
}

/**
 * 校验日期输入
 * @param {string} id - 元素ID
 * @param {string} label - 显示名称
 * @param {boolean} [required=false] - 是否必填
 * @returns {string|null} 校验通过返回日期字符串 (YYYY-MM-DD)
 */
function validateDate(id, label, required = false) {
    const el = document.getElementById(id);
    if (!el) {
        reportError(`找不到日期输入框 "${id}"`);
        return null;
    }

    const raw = el.value.trim();
    if (!raw) {
        if (!required) return null;
        reportError(`${label} 不能为空`);
        focusEl(el);
        return null;
    }

    // 检查日期格式 YYYY-MM-DD
    if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
        reportError(`${label} 日期格式不正确，应为 YYYY-MM-DD`);
        focusEl(el);
        return null;
    }

    const d = new Date(raw);
    if (isNaN(d.getTime())) {
        reportError(`${label} 不是一个有效日期`);
        focusEl(el);
        return null;
    }

    return raw;
}

/**
 * 为表单输入框绑定实时校验，输入不合法时提交按钮变灰不可点击
 * 
 * @param {object} config
 * @param {string[]} config.inputIds     - 需要校验的输入框 ID 列表（不含可选字段）
 * @param {string}   config.buttonId     - 提交按钮 ID
 * @param {object}   [config.rules]      - 每个字段的自定义校验规则，key 为输入框 ID
 * @param {object}   [config.optionalIds] - 可选字段 ID 列表（为空时不触发校验报错）
 * 
 * 用法：
 *   bindFormValidation({
 *       inputIds: ['bt-stoploss', 'bt-takeprofit', 'bt-capital', 'bt-fee', 'bt-max-pos'],
 *       buttonId: 'bt-run',
 *       optionalIds: ['bt-pos-percent', 'bt-pos-fixed'],
 *   });
 */
function bindFormValidation(config) {
    const { inputIds, buttonId, rules = {}, optionalIds = [] } = config;
    const btn = document.getElementById(buttonId);
    if (!btn) return;

    const allIds = [...inputIds, ...optionalIds];

    function checkForm() {
        let allValid = true;

        for (const id of inputIds) {
            const el = document.getElementById(id);
            if (!el) { allValid = false; continue; }

            const raw = el.value.trim();
            const rule = rules[id] || {};
            const required = rule.required !== false;

            // 空值检查
            if (!raw) {
                if (required) { allValid = false; continue; }
                else continue;
            }

            // 数字解析
            const num = rule.isInt ? parseInt(raw, 10) : parseFloat(raw);
            if (isNaN(num) || !isFinite(num)) { allValid = false; continue; }

            // 检查原始值是否包含多余字符（如 "3.ss" 不合法）
            const sanitized = raw.replace(/^[-+]?\d*\.?\d*$/, '');
            if (sanitized.length > 0) { allValid = false; continue; }

            // 正数检查
            if (rule.positive !== false && num <= 0) { allValid = false; continue; }

            // 范围检查
            if (rule.min !== undefined && num < rule.min) { allValid = false; continue; }
            if (rule.max !== undefined && num > rule.max) { allValid = false; continue; }
        }

        // 勾选按钮
        btn.disabled = !allValid;
        btn.style.opacity = allValid ? '1' : '0.4';
        btn.style.cursor = allValid ? 'pointer' : 'not-allowed';
    }

    // 给所有输入框绑定 input 和 change 事件
    for (const id of allIds) {
        const el = document.getElementById(id);
        if (!el) continue;
        el.addEventListener('input', checkForm);
        el.addEventListener('change', checkForm);
    }

    // 初始检查一次
    checkForm();

    // 返回 checkForm 函数，方便外部在切换可见性等场景手动触发
    return checkForm;
}

// ── 内部辅助 ──

function reportError(msg) {
    if (statusReporter) {
        statusReporter(msg);
    } else {
        console.error('[校验失败]', msg);
    }
}

function focusEl(el) {
    el.style.outline = '2px solid #ff4444';
    el.style.outlineOffset = '1px';
    el.focus();
    el.select();
    // 3 秒后自动清除红色高亮
    setTimeout(() => {
        el.style.outline = '';
    }, 3000);
}
