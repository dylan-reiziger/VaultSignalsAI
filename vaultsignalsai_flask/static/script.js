const state = {
  authMode: 'login',
  member: null,
  cryptoData: {},
  liveDesk: {
    topCoins: [],
    selectedCoin: null,
    selectedCoinId: '',
    chart: [],
    source: null,
  },
  pricingMatrixGbp: null,
  promoPlansGbp: null,
  currencies: [],
  exchangeRates: { GBP: 1 },
  activeCurrency: {
    code: document.body?.dataset.defaultCurrencyCode || 'GBP',
    symbol: document.body?.dataset.currencySymbol || '£',
    locale: 'en-GB',
    source: 'default',
  },
  signals: [],
  alertCooldown: new Map(),
};

let authForm;
let authMessage;
let submitBtn;
let usernameGroup;
let fullNameGroup;
let addressGroup;
let zipcodeGroup;
let discordTagGroup;
let discordLevelGroup;
let discordUsernameInput;
let signupDiscordTagSelect;
let discordVerificationHint;
let memberStatus;
let tabButtons;
let tierButtons;
let heroCreateAccount;
let loginTriggers;
let liveDeskCoins;
let liveDeskFeedStatus;
let liveDeskTrackedCount;
let liveDeskMarketLeader;
let liveDeskMarketLeaderMeta;
let liveDeskFeedMode;
let liveDeskFeedModeMeta;
let liveDeskSelectedName;
let liveDeskSelectedMeta;
let liveDeskSelectedPrice;
let liveDeskSelectedChange;
let liveDeskMarketCap;
let liveDeskVolume;
let liveDeskHigh;
let liveDeskLow;
let liveDeskChart;
let switchPersonal;
let switchBusiness;
let feedbackTriggers;
let feedbackModal;
let feedbackModalClose;
let feedbackForm;
let feedbackMessage;
let menuToggle;
let navLinks;
let authModal;
let authModalClose;
let rememberLoginGroup;
let rememberLogin;
let dataConsentGroup;
let dataConsent;
let authUnverifiedActions;
let resendVerificationBtn;
let changeUnverifiedEmailBtn;
let verifyTokenInput;
let verifyTokenBtn;
let tickerContent;
let pageTabs;
let tabPanels;
let billingForm;
let billingMessage;
let billingTier;
let billingCycle;
let billingDiscordTag;
let billingSignals;
let billingQuote;
let miniTierButtons;
let orderSummaryTierName;
let orderSummarySignals;
let orderSummaryCycle;
let priceCtaButtons;
let checkoutModal;
let checkoutModalClose;
let checkoutStep1;
let checkoutStep2;
let checkoutStep3;
let stepChips;
let billingNextToStep2;
let billingBackToStep1;
let billingNextToStep3;
let billingBackToStep2;
let checkoutStep2Lock;
let checkoutStep3Lock;
let checkoutStep2Content;
let checkoutStep3Content;
let step2RequiredNote;
let step3RequiredNote;
let paymentMethodBar;
let paymentMethodButtons;
let billingFullName;
let billingCompany;
let billingAddress;
let billingZip;
let billingCountry;
let reviewTier;
let reviewSignals;
let reviewCycle;
let reviewMethod;
let reviewTag;
let reviewSubtotal;
let reviewTax;
let reviewPrice;
let termsAgree;
let currencySelectors;
let currencyNoteEls;
let memberPortalLinks;
let logoutButtons;
let signalsWelcome;
let signalsSummary;
let signalsFeed;
let signalsEmpty;
let purchaseTiers;
let signalAiScanner;
let signalsMarketSelect;
let openMarketBtn;
let alertToastStack;
let currentCheckoutStep = 1;
let selectedPaymentMethod = 'creditcard';
let marketItems = [];
const marketHistory = new Map();
const MAX_MARKET_HISTORY_POINTS = 32;
let liveDeskRefreshHandle;
let liveDeskEventSource;
let liveDeskStreamKey = '';
let signalCountdownHandle;

// ── CONFIG CONSTANTS ──────────────────────────────────────────────
const VAT_RATE = Number(document.body?.dataset.vatRate || '0.21');
const DEFAULT_PROMO_PLANS_GBP = {
  starter: { monthly: 19, annual_monthly: 16, annual_total: 192 },
  business: { monthly: 29, annual_monthly: 24, annual_total: 288 },
};
const CHECKOUT_CYCLE_SUMMARY_LABELS = {
  weekly: 'Weekly billing',
  monthly: 'Monthly billing',
  quarterly: 'Quarterly billing',
  annual: 'Annual billing',
  lifetime: 'Lifetime access',
};
const CHECKOUT_CYCLE_REVIEW_LABELS = {
  weekly: 'Weekly',
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  annual: 'Annual',
  lifetime: 'Lifetime',
};
const PAYMENT_LABELS = {
  creditcard: 'Credit Card',
  ideal: 'iDEAL',
  paypal: 'PayPal',
};
const MARKET_ALERT_ABS_MOVE_THRESHOLD = 1.4;
const MARKET_ALERT_DROP_THRESHOLD = -0.8;
const MARKET_ALERT_RISE_THRESHOLD = 1.0;
const MARKET_ALERT_COOLDOWN_MS = 8 * 60 * 1000;
const BITVAVO_MARKETS_BASE = 'https://bitvavo.com/en/markets';

function getActiveCurrency() {
  return state.activeCurrency || { code: 'GBP', locale: 'en-GB', symbol: '£' };
}

function formatCurrencyAmount(amount, options = {}) {
  if (typeof amount !== 'number' || Number.isNaN(amount)) {
    return 'N/A';
  }
  const currency = getActiveCurrency();
  return new Intl.NumberFormat(currency.locale || 'en-GB', {
    style: 'currency',
    currency: currency.code || 'GBP',
    minimumFractionDigits: options.minimumFractionDigits ?? 2,
    maximumFractionDigits: options.maximumFractionDigits ?? 2,
  }).format(amount);
}

function convertCurrency(amount, fromCode, toCode) {
  if (typeof amount !== 'number' || Number.isNaN(amount)) {
    return null;
  }
  const fromRate = state.exchangeRates?.[fromCode] || (fromCode === 'GBP' ? 1 : null);
  const toRate = state.exchangeRates?.[toCode] || (toCode === 'GBP' ? 1 : null);
  if (!fromRate || !toRate) {
    return null;
  }
  const gbpAmount = amount / fromRate;
  return gbpAmount * toRate;
}

function convertFromGbp(amount) {
  return convertCurrency(amount, 'GBP', getActiveCurrency().code) ?? amount;
}

function formatCheckoutMoney(amount) {
  return formatCurrencyAmount(amount);
}

function fetchFresh(url, options = {}) {
  return fetch(url, {
    ...options,
    cache: options.cache ?? 'no-store',
  });
}

function buildLiveDeskFallbackPayload(coinId = '') {
  const normalizedCoinId = String(coinId || '').trim().toLowerCase();
  const topCoins = getLiveCryptoItems().map((coin) => ({
    ...coin,
    high_24h: Number(coin.high_24h || coin.price || 0),
    low_24h: Number(coin.low_24h || coin.price || 0),
  }));
  const selectedCoin = topCoins.find((coin) => String(coin.id || '').trim().toLowerCase() === normalizedCoinId) || topCoins[0] || null;

  return {
    topCoins,
    selectedCoin,
    selectedCoinId: selectedCoin?.id || '',
    chart: [],
    source: {
      provider: 'Ticker fallback',
      apiKeyConfigured: false,
      fallback: true,
      windowHours: 24,
    },
  };
}
// ──────────────────────────────────────────────────────────────────

const PRICING_MATRIX_GBP = {};

// Crypto Ticker
async function initCryptoTicker() {
  try {
    const response = await fetchFresh('/api/crypto-data');
    if (response.ok) {
      const data = await response.json();
      state.cryptoData = data;
      updateTicker();
      
      // Also populate market feed
      populateMarketFeed(data);
    }
  } catch (error) {
    console.error('Ticker init error:', error);
  }
}

function populateMarketFeed(data) {
  marketItems = [
    ...(data.crypto || []),
    ...(data.stocks || [])
  ];

  recordMarketSnapshot(data.crypto || []);
  detectSignalAlerts(data.crypto || []);
  renderSignalAiScanner();
}

function getBitvavoMarketUrl(symbol = 'btc') {
  const normalized = String(symbol || 'btc').trim().toLowerCase();
  return `${BITVAVO_MARKETS_BASE}/${normalized}-eur`;
}

function ensureAlertToastStack() {
  if (alertToastStack) return alertToastStack;
  alertToastStack = document.createElement('div');
  alertToastStack.className = 'alert-toast-stack';
  document.body.appendChild(alertToastStack);
  return alertToastStack;
}

function pushWebsiteAlert(message, kind = 'drop') {
  const stack = ensureAlertToastStack();
  const toast = document.createElement('article');
  toast.className = `alert-toast ${kind}`;
  const title = document.createElement('strong');
  title.textContent = kind === 'drop' ? 'Early Drop Alert' : 'Momentum Alert';
  const body = document.createElement('p');
  body.textContent = String(message || '');
  toast.append(title, body);
  stack.appendChild(toast);

  window.setTimeout(() => {
    toast.classList.add('closing');
    window.setTimeout(() => toast.remove(), 250);
  }, 6400);

  if (document.visibilityState === 'hidden' && 'Notification' in window && Notification.permission === 'granted') {
    new Notification('VaultSignalsAI Alert', { body: message });
  }
}

function maybeTriggerBrowserNotificationPermission() {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {});
  }
}

function detectSignalAlerts(cryptoItems) {
  const now = Date.now();
  cryptoItems.forEach((item) => {
    const symbol = item.symbol || item.id;
    const history = marketHistory.get(symbol) || [];
    if (!symbol || history.length < 6) {
      return;
    }

    const start = history[history.length - 6];
    const end = history[history.length - 1];
    if (!start || !end) return;

    const pctMove = ((end - start) / start) * 100;
    const cooldownKey = `${symbol}:${pctMove < 0 ? 'drop' : 'rise'}`;
    const lastAlert = state.alertCooldown.get(cooldownKey) || 0;
    if (now - lastAlert < MARKET_ALERT_COOLDOWN_MS) {
      return;
    }

    const recentThree = history.slice(-3);
    const consecutiveDrop = recentThree[0] > recentThree[1] && recentThree[1] > recentThree[2];
    const bigMove = Math.abs(pctMove) >= MARKET_ALERT_ABS_MOVE_THRESHOLD;
    const preDrop = pctMove <= MARKET_ALERT_DROP_THRESHOLD && consecutiveDrop;
    const sharpRise = pctMove >= MARKET_ALERT_RISE_THRESHOLD;

    if (!(bigMove || preDrop || sharpRise)) {
      return;
    }

    const priceText = getCanvasPriceLabel(end);
    if (preDrop) {
      pushWebsiteAlert(`${symbol} shows accelerated sell pressure (${pctMove.toFixed(2)}% / min window). Current ${priceText}.`, 'drop');
      state.alertCooldown.set(`${symbol}:drop`, now);
      return;
    }

    if (sharpRise) {
      pushWebsiteAlert(`${symbol} is moving fast upward (${pctMove.toFixed(2)}% / min window). Current ${priceText}.`, 'rise');
      state.alertCooldown.set(`${symbol}:rise`, now);
      return;
    }

    if (pctMove <= -MARKET_ALERT_ABS_MOVE_THRESHOLD) {
      pushWebsiteAlert(`${symbol} is dropping quickly (${pctMove.toFixed(2)}% / min window). Current ${priceText}.`, 'drop');
      state.alertCooldown.set(`${symbol}:drop`, now);
    }
  });
}

function updateTicker() {
  const data = state.cryptoData;
  let html = '';
  
  if (data.crypto) {
    data.crypto.forEach(item => {
      const change = item.change || 0;
      const changeClass = change >= 0 ? 'change-up' : 'change-down';
      const changeSymbol = change >= 0 ? '▲' : '▼';
      const label = escapeHtml(String(item.pair || item.symbol || '--'));
      const price = Number(item.price);
      const priceLabel = Number.isFinite(price)
        ? `$${price.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
        : '--';
      
      html += `
        <span>
          <strong>${label}</strong>
          <span class="price">${priceLabel}</span>
          <span class="${changeClass}">${changeSymbol} ${Math.abs(change).toFixed(2)}%</span>
        </span>
      `;
    });
  }
  
  if (tickerContent && html) {
    tickerContent.innerHTML = html + html;
  }
}

function normalizeLiveDeskChartPoints(points, maxPoints = 240) {
  const cutoff = Date.now() - (24 * 60 * 60 * 1000);
  const filtered = (Array.isArray(points) ? points : [])
    .map((point) => ({ timestamp: Number(point.timestamp), price: Number(point.price) }))
    .filter((point) => Number.isFinite(point.timestamp) && Number.isFinite(point.price) && point.timestamp >= cutoff)
    .sort((left, right) => left.timestamp - right.timestamp);

  if (filtered.length <= maxPoints) {
    return filtered;
  }

  const step = Math.ceil(filtered.length / maxPoints);
  const sampled = filtered.filter((_, index) => index % step === 0);
  const lastPoint = filtered[filtered.length - 1];
  if (sampled[sampled.length - 1]?.timestamp !== lastPoint.timestamp) {
    sampled.push(lastPoint);
  }
  return sampled;
}

function applyLiveDeskTick(tick) {
  const coinId = String(tick?.id || '').trim().toLowerCase();
  const price = Number(tick?.price);
  const change = Number(tick?.change_24h);
  const marketCap = Number(tick?.market_cap);
  if (!coinId || !Number.isFinite(price)) {
    return;
  }

  const topCoins = Array.isArray(state.liveDesk.topCoins) ? state.liveDesk.topCoins : [];
  const coinIndex = topCoins.findIndex((coin) => String(coin.id || '').toLowerCase() === coinId);
  if (coinIndex === -1) {
    return;
  }

  const currentCoin = topCoins[coinIndex];
  const updatedCoin = {
    ...currentCoin,
    price,
    change: Number.isFinite(change) ? change : currentCoin.change,
    market_cap: Number.isFinite(marketCap) ? marketCap : currentCoin.market_cap,
    high_24h: Math.max(Number(currentCoin.high_24h || price), price),
    low_24h: Math.min(Number(currentCoin.low_24h || price), price),
  };

  const nextCoins = [...topCoins];
  nextCoins[coinIndex] = updatedCoin;
  nextCoins.sort((left, right) => Number(right.market_cap || 0) - Number(left.market_cap || 0));
  state.liveDesk.topCoins = nextCoins;

  if (coinId === String(state.liveDesk.selectedCoinId || '').toLowerCase()) {
    state.liveDesk.selectedCoin = updatedCoin;
    const nextChart = normalizeLiveDeskChartPoints([
      ...(Array.isArray(state.liveDesk.chart) ? state.liveDesk.chart : []),
      { timestamp: Date.now(), price },
    ]);
    state.liveDesk.chart = nextChart;
  } else if (!state.liveDesk.selectedCoin && nextCoins[0]) {
    state.liveDesk.selectedCoin = nextCoins[0];
    state.liveDesk.selectedCoinId = nextCoins[0].id || '';
  }

  state.liveDesk.source = {
    ...(state.liveDesk.source || {}),
    liveStreamActive: true,
    fallback: false,
    windowHours: 24,
  };
  renderLiveDesk();
}

function ensureLiveDeskStream() {
  const ids = (Array.isArray(state.liveDesk.topCoins) ? state.liveDesk.topCoins : [])
    .map((coin) => String(coin.id || '').trim().toLowerCase())
    .filter(Boolean);

  if (!ids.length || typeof EventSource === 'undefined') {
    return;
  }

  const streamKey = ids.join(',');
  if (liveDeskEventSource && liveDeskStreamKey === streamKey) {
    return;
  }

  if (liveDeskEventSource) {
    liveDeskEventSource.close();
  }

  liveDeskStreamKey = streamKey;
  liveDeskEventSource = new EventSource(`/stream?ids=${encodeURIComponent(streamKey)}`);

  liveDeskEventSource.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      applyLiveDeskTick(payload);
    } catch (error) {
      console.error('Live desk stream parse error:', error);
    }
  };

  liveDeskEventSource.onopen = () => {
    state.liveDesk.source = {
      ...(state.liveDesk.source || {}),
      liveStreamActive: true,
      windowHours: 24,
    };
    renderLiveDesk();
  };

  liveDeskEventSource.onerror = () => {
    state.liveDesk.source = {
      ...(state.liveDesk.source || {}),
      liveStreamActive: false,
    };
    renderLiveDesk();
  };
}

function formatSignedPercent(value) {
  const numericValue = Number(value) || 0;
  return `${numericValue >= 0 ? '+' : ''}${formatNumber(numericValue, 2)}%`;
}

function buildLiveDeskChartPaths(points, width = 640, height = 220, padding = 18) {
  const prices = points.map((point) => point.price);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const range = Math.max(maxPrice - minPrice, maxPrice * 0.003, 1);

  const mappedPoints = points.map((point, index) => {
    const x = padding + (index / Math.max(1, points.length - 1)) * (width - (padding * 2));
    const y = height - padding - (((point.price - minPrice) / range) * (height - (padding * 2)));
    return { x, y, price: point.price, timestamp: point.timestamp };
  });

  const linePath = mappedPoints
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(' ');
  const areaPath = `${linePath} L ${mappedPoints[mappedPoints.length - 1].x.toFixed(2)} ${(height - padding).toFixed(2)} L ${mappedPoints[0].x.toFixed(2)} ${(height - padding).toFixed(2)} Z`;

  return { mappedPoints, linePath, areaPath };
}

function renderLiveDeskChart(chartPoints, selectedCoin) {
  if (!liveDeskChart) return;

  const points = (Array.isArray(chartPoints) ? chartPoints : [])
    .map((point) => ({ timestamp: Number(point.timestamp), price: Number(point.price) }))
    .filter((point) => Number.isFinite(point.timestamp) && Number.isFinite(point.price));

  if (points.length < 2) {
    liveDeskChart.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="rgba(255,255,255,0.58)" font-size="16">Live chart unavailable</text>';
    return;
  }

  const width = 640;
  const height = 220;
  const positive = Number(selectedCoin?.change || 0) >= 0;
  const strokeColor = positive ? '#7af0b6' : '#ff9e9e';
  const fillFrom = positive ? 'rgba(122,240,182,0.24)' : 'rgba(255,158,158,0.24)';
  const fillTo = positive ? 'rgba(122,240,182,0.02)' : 'rgba(255,158,158,0.02)';
  const { mappedPoints, linePath, areaPath } = buildLiveDeskChartPaths(points, width, height);
  const lastPoint = mappedPoints[mappedPoints.length - 1];
  const firstLabel = new Date(points[0].timestamp).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  const lastLabel = new Date(points[points.length - 1].timestamp).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  const gridLines = [0.16, 0.38, 0.60, 0.82]
    .map((ratio) => `<line x1="18" y1="${(height * ratio).toFixed(2)}" x2="622" y2="${(height * ratio).toFixed(2)}" stroke="rgba(255,255,255,0.08)" stroke-width="1" stroke-dasharray="4 8"></line>`)
    .join('');

  liveDeskChart.innerHTML = `
    <defs>
      <linearGradient id="heroLiveChartFill" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${fillFrom}" />
        <stop offset="100%" stop-color="${fillTo}" />
      </linearGradient>
    </defs>
    ${gridLines}
    <path d="${areaPath}" fill="url(#heroLiveChartFill)"></path>
    <path d="${linePath}" fill="none" stroke="${strokeColor}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></path>
    <circle cx="${lastPoint.x.toFixed(2)}" cy="${lastPoint.y.toFixed(2)}" r="5.5" fill="${strokeColor}" stroke="rgba(5,5,5,0.85)" stroke-width="2.5"></circle>
    <text x="18" y="206" fill="rgba(255,255,255,0.48)" font-size="12">${firstLabel}</text>
    <text x="560" y="206" fill="rgba(255,255,255,0.48)" font-size="12">${lastLabel}</text>
  `;
}

function renderLiveDesk() {
  const topCoins = Array.isArray(state.liveDesk.topCoins) ? state.liveDesk.topCoins : [];
  const selectedCoin = state.liveDesk.selectedCoin || topCoins[0] || null;
  const leaderCoin = topCoins[0] || null;
  const source = state.liveDesk.source || {};
  const providerLabel = String(source.provider || 'Market').trim();
  const marketCapPrefix = source.estimatedMarketCap ? 'Est. market cap' : 'Top market cap';

  if (liveDeskFeedStatus) {
    const hasApiKey = Boolean(source.apiKeyConfigured);
    const isFallback = Boolean(source.fallback);
    const isLive = Boolean(source.liveStreamActive);
    liveDeskFeedStatus.textContent = isLive
      ? `${providerLabel} live stream`
      : (isFallback ? `${providerLabel} cached feed` : (hasApiKey ? `${providerLabel} keyed feed` : `${providerLabel} public feed`));
    liveDeskFeedStatus.classList.toggle('is-keyed', isLive || (hasApiKey && !isFallback));
    liveDeskFeedStatus.classList.toggle('is-public', !isLive && (!hasApiKey || isFallback));
  }

  if (liveDeskTrackedCount) {
    liveDeskTrackedCount.textContent = topCoins.length ? String(topCoins.length) : '--';
  }

  if (liveDeskMarketLeader) {
    liveDeskMarketLeader.textContent = leaderCoin ? leaderCoin.symbol : '--';
  }

  if (liveDeskMarketLeaderMeta) {
    liveDeskMarketLeaderMeta.textContent = leaderCoin
      ? `${marketCapPrefix} ${formatCompactMoney(leaderCoin.market_cap)}.`
      : 'The market leader will load here.';
  }

  if (liveDeskFeedMode) {
    liveDeskFeedMode.textContent = source.liveStreamActive ? 'Streaming' : (source.apiKeyConfigured ? 'Keyed' : providerLabel);
  }

  if (liveDeskFeedModeMeta) {
    liveDeskFeedModeMeta.textContent = source.liveStreamActive
      ? `${providerLabel} server-sent events keep the desk updating live while the 24H chart stays open.`
      : source.fallback
      ? `${providerLabel} fallback keeps the desk visible with live ticker data and a real 24H chart.`
      : (source.apiKeyConfigured
        ? `${providerLabel} feed is running through the backend key for the 24H desk.`
        : 'Server-side CoinGecko feed without exposing keys in the browser.');
  }

  if (liveDeskCoins) {
    if (!topCoins.length) {
      liveDeskCoins.innerHTML = '<div class="hero-terminal-empty">No live major coins available right now.</div>';
    } else {
      liveDeskCoins.innerHTML = topCoins.slice(0, 4).map((coin) => {
        const change = Number(coin.change || 0);
        const isActive = coin.id === state.liveDesk.selectedCoinId;
        const safeCoinId = escapeHtml(String(coin.id || ''));
        const safeSymbol = escapeHtml(String(coin.symbol || '--'));
        const safeName = escapeHtml(String(coin.name || 'Unknown'));
        const safeRank = Number.isFinite(Number(coin.rank)) ? String(Number(coin.rank)) : '--';
        return `
          <button class="hero-live-coin ${isActive ? 'is-active' : ''}" type="button" data-live-coin="${safeCoinId}">
            <span class="hero-live-coin-head">
              <span class="hero-live-coin-symbol">${safeSymbol}</span>
              <span class="hero-live-coin-rank">#${safeRank}</span>
            </span>
            <span class="hero-live-coin-name">${safeName}</span>
            <strong class="hero-live-coin-price">${getCanvasPriceLabel(coin.price)}</strong>
            <span class="hero-live-coin-change ${change >= 0 ? 'is-up' : 'is-down'}">${formatSignedPercent(change)}</span>
          </button>
        `;
      }).join('');
    }
  }

  if (liveDeskSelectedName) {
    liveDeskSelectedName.textContent = selectedCoin ? selectedCoin.name : 'Unavailable';
  }

  if (liveDeskSelectedMeta) {
    liveDeskSelectedMeta.textContent = selectedCoin
      ? `${selectedCoin.symbol}/USD • ${providerLabel} 24H chart • rank #${selectedCoin.rank || '--'}`
      : 'Top market-cap 24H chart will render here.';
  }

  if (liveDeskSelectedPrice) {
    liveDeskSelectedPrice.textContent = selectedCoin ? getCanvasPriceLabel(selectedCoin.price) : '--';
  }

  if (liveDeskSelectedChange) {
    const changeValue = Number(selectedCoin?.change || 0);
    liveDeskSelectedChange.textContent = selectedCoin ? formatSignedPercent(changeValue) : '--';
    liveDeskSelectedChange.className = `hero-live-chart-change ${changeValue >= 0 ? 'is-up' : 'is-down'}`;
  }

  if (liveDeskMarketCap) {
    liveDeskMarketCap.textContent = selectedCoin ? formatCompactMoney(selectedCoin.market_cap) : '--';
  }

  if (liveDeskVolume) {
    liveDeskVolume.textContent = selectedCoin ? formatCompactMoney(selectedCoin.volume) : '--';
  }

  if (liveDeskHigh) {
    liveDeskHigh.textContent = selectedCoin ? getCanvasPriceLabel(selectedCoin.high_24h) : '--';
  }

  if (liveDeskLow) {
    liveDeskLow.textContent = selectedCoin ? getCanvasPriceLabel(selectedCoin.low_24h) : '--';
  }

  renderLiveDeskChart(state.liveDesk.chart, selectedCoin);
}

async function loadLiveDesk(coinId = '') {
  if (!liveDeskCoins && !liveDeskChart) {
    return;
  }

  try {
    const query = coinId ? `?coin_id=${encodeURIComponent(coinId)}` : '';
    const response = await fetchFresh(`/api/live-desk${query}`);
    if (!response.ok) {
      throw new Error(`Live desk request failed: ${response.status}`);
    }
    const payload = await response.json();
    const resolvedPayload = Array.isArray(payload.topCoins) && payload.topCoins.length
      ? payload
      : buildLiveDeskFallbackPayload(coinId || payload.selectedCoinId || '');

    state.liveDesk = {
      topCoins: resolvedPayload.topCoins || [],
      selectedCoin: resolvedPayload.selectedCoin || null,
      selectedCoinId: resolvedPayload.selectedCoinId || '',
      chart: resolvedPayload.chart || [],
      source: {
        ...(resolvedPayload.source || {}),
        liveStreamActive: Boolean(state.liveDesk.source?.liveStreamActive),
      },
    };
    ensureLiveDeskStream();
    renderLiveDesk();
  } catch (error) {
    console.error('Live desk error:', error);
    const fallbackPayload = buildLiveDeskFallbackPayload(coinId);
    if (fallbackPayload.topCoins.length) {
      state.liveDesk = {
        ...fallbackPayload,
        source: {
          ...(fallbackPayload.source || {}),
          liveStreamActive: false,
        },
      };
      renderLiveDesk();
      return;
    }
    if (liveDeskCoins) {
      liveDeskCoins.innerHTML = '<div class="hero-terminal-empty">Could not load the live crypto desk.</div>';
    }
    if (liveDeskChart) {
      liveDeskChart.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="rgba(255,255,255,0.58)" font-size="16">Chart unavailable</text>';
    }
  }
}

// Refresh ticker every 10 seconds is initialized after DOM is ready in setupPage.

function setAuthMode(mode) {
  state.authMode = mode;
  tabButtons.forEach((btn) => btn.classList.toggle('active', btn.dataset.mode === mode));
  const isSignup = mode === 'signup';
  usernameGroup?.classList.toggle('hidden', !isSignup);
  fullNameGroup?.classList.toggle('hidden', !isSignup);
  addressGroup?.classList.toggle('hidden', !isSignup);
  zipcodeGroup?.classList.toggle('hidden', !isSignup);
  discordTagGroup?.classList.toggle('hidden', !isSignup);
  discordLevelGroup?.classList.toggle('hidden', !isSignup);
  rememberLoginGroup?.classList.toggle('hidden', false);
  dataConsentGroup?.classList.toggle('hidden', !isSignup);
  if (!isSignup && dataConsent) {
    dataConsent.checked = false;
  }
  setUnverifiedActionsVisible(false);
  if (submitBtn) {
    submitBtn.textContent = isSignup ? 'Create Member Account' : 'Log Into Account';
  }
  if (!isSignup) {
    setMessage('Enter your email and password to log in.');
  } else {
    setMessage('Enter your details to create an account. Consent to data storage is required, and paid signals unlock only after you buy a tier.');
  }
}

function applyDiscordVerificationUI() {
  if (!signupDiscordTagSelect || !discordVerificationHint) return;
  const status = state.member?.discordVerificationStatus || 'pending';
  const resolvedTag = state.member?.discordTag || '';

  if (!state.member) {
    signupDiscordTagSelect.value = '';
    discordVerificationHint.textContent = 'Tag level is assigned only after system checks your Discord membership.';
    return;
  }

  if (resolvedTag) {
    signupDiscordTagSelect.value = resolvedTag;
  } else {
    signupDiscordTagSelect.value = '';
  }

  if (status === 'verified' && resolvedTag) {
    discordVerificationHint.textContent = `System verified. Active Discord level: ${resolvedTag.replace('_', ' ')}.`;
    return;
  }
  if (status === 'not_connected') {
    discordVerificationHint.textContent = 'No Discord username linked yet. Add your username and save it to start verification.';
    return;
  }
  discordVerificationHint.textContent = 'Discord membership found not yet verified in registry. Level will update automatically once verified.';
}

function setMessage(message, ok = false) {
  if (!authMessage) return;
  authMessage.textContent = message;
  authMessage.style.borderColor = ok ? 'rgba(242,193,78,0.35)' : 'rgba(255,255,255,0.1)';
  authMessage.style.color = ok ? '#f7d98b' : 'rgba(255,255,255,0.72)';
}

function setUnverifiedActionsVisible(visible) {
  if (!authUnverifiedActions) return;
  authUnverifiedActions.classList.toggle('hidden', !visible);
}

async function resendVerificationForCurrentEmail() {
  const email = document.getElementById('email')?.value?.trim() || '';
  if (!email) {
    setMessage('Enter your email first so we can resend verification.');
    return;
  }
  try {
    const response = await fetch('/api/auth/resend-verification', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    const result = await response.json();
    if (!response.ok) {
      setMessage(result.message || 'Could not resend verification email.');
      return;
    }
    const message = result.verificationUrl ? `${result.message} ${result.verificationUrl}` : result.message;
    setMessage(message, true);
    setUnverifiedActionsVisible(true);
  } catch {
    setMessage('Could not reach server while resending verification.');
  }
}

async function changeUnverifiedEmailForCurrentUser() {
  const currentEmail = document.getElementById('email')?.value?.trim() || '';
  const password = document.getElementById('password')?.value || '';
  if (!currentEmail || !password) {
    setMessage('Enter your current email and password first.');
    return;
  }

  const newEmail = window.prompt('Enter your new email address:');
  if (!newEmail || !newEmail.trim()) {
    return;
  }

  try {
    const response = await fetch('/api/auth/change-unverified-email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: currentEmail,
        password,
        newEmail: newEmail.trim(),
      }),
    });
    const result = await response.json();
    if (!response.ok) {
      setMessage(result.message || 'Could not change email.');
      return;
    }

    const emailInput = document.getElementById('email');
    if (emailInput && result.newEmail) {
      emailInput.value = result.newEmail;
    }
    const message = result.verificationUrl ? `${result.message} ${result.verificationUrl}` : result.message;
    setMessage(message, true);
    setUnverifiedActionsVisible(true);
  } catch {
    setMessage('Could not reach server while changing email.');
  }
}

async function verifyTokenFromInput() {
  const token = verifyTokenInput?.value?.trim() || '';
  if (!token) {
    setMessage('Paste a verification token or verify URL first.');
    return;
  }
  try {
    const response = await fetch('/api/auth/verify-token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
    const result = await response.json();
    if (!response.ok) {
      setMessage(result.message || 'Could not verify token.');
      return;
    }
    setMessage(result.message || 'Email verified successfully.', true);
    setUnverifiedActionsVisible(false);
    if (verifyTokenInput) {
      verifyTokenInput.value = '';
    }
  } catch {
    setMessage('Could not reach server while verifying token.');
  }
}

function getPricingMatrix() {
  return state.pricingMatrixGbp || PRICING_MATRIX_GBP;
}

function getPromoPlans() {
  return state.promoPlansGbp || DEFAULT_PROMO_PLANS_GBP;
}

function updateMemberActions() {
  const isMember = Boolean(state.member);
  memberPortalLinks?.forEach((link) => {
    link.classList.toggle('hidden', !isMember);
  });
  loginTriggers?.forEach((button) => {
    button.classList.toggle('hidden', isMember);
  });
  logoutButtons?.forEach((button) => {
    button.classList.toggle('hidden', !isMember);
  });
}

function populateCurrencySelectors() {
  if (!currencySelectors?.length) return;
  const currency = getActiveCurrency();
  currencySelectors.forEach((selector) => {
    selector.innerHTML = '';
    state.currencies.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.code;
      option.textContent = `${item.code} · ${item.label}`;
      option.selected = item.code === currency.code;
      selector.appendChild(option);
    });
  });
  currencyNoteEls?.forEach((note) => {
    note.textContent = `Auto suggestion source: ${currency.source || 'default'}. Raw IP addresses are not stored for this setting.`;
  });
}

function applyViewMode(viewMode) {
  const normalized = ['normal', 'compact', 'advanced'].includes(viewMode) ? viewMode : 'normal';
  document.body.dataset.viewMode = normalized;
}

function applyBootstrapData(payload) {
  state.member = payload.user || null;
  state.currencies = payload.currencies || [];
  state.exchangeRates = payload.exchangeRates || { GBP: 1 };
  state.pricingMatrixGbp = payload.pricingMatrixGbp || PRICING_MATRIX_GBP;
  state.promoPlansGbp = payload.promoPlansGbp || DEFAULT_PROMO_PLANS_GBP;
  state.activeCurrency = payload.currency || getActiveCurrency();
  applyViewMode(state.member?.viewMode || 'normal');
  populateCurrencySelectors();
  updateMemberStatus();
  updateMemberActions();
  hydrateBillingFromMember();
  refreshBillingQuote();
  renderCheckoutReview();
  updateCheckoutLocks();
  setPricingMode(switchBusiness?.classList.contains('active') ? 'business' : 'personal');
}

async function bootstrapSessionState() {
  try {
    const response = await fetchFresh('/api/session');
    if (!response.ok) {
      return;
    }
    const result = await response.json();
    applyBootstrapData(result);
    await loadMemberSignals();
  } catch (error) {
    console.error('Session bootstrap error:', error);
  }
}

async function handleCurrencyChange(event) {
  const currencyCode = event.target.value;
  try {
    const response = await fetch('/api/preferences/currency', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ currencyCode }),
    });
    const result = await response.json();
    if (!response.ok) {
      return;
    }
    state.activeCurrency = result.currency;
    state.exchangeRates = result.exchangeRates || state.exchangeRates;
    window.dispatchEvent(new CustomEvent('vaultsignals:currency-changed', {
      detail: {
        currency: state.activeCurrency,
        exchangeRates: state.exchangeRates,
      },
    }));
    populateCurrencySelectors();
    refreshBillingQuote();
    renderCheckoutReview();
    setPricingMode(switchBusiness?.classList.contains('active') ? 'business' : 'personal');
    await loadMemberSignals();
  } catch (error) {
    console.error('Currency preference update failed:', error);
  }
}

async function handleLogout(event) {
  event.preventDefault();
  try {
    const response = await fetch('/api/logout', { method: 'POST' });
    const result = await response.json();
    if (!response.ok) {
      setMessage(result.message || 'Could not log out.');
      return;
    }
    state.member = null;
    updateMemberStatus();
    updateMemberActions();
    updateCheckoutLocks();
    setMessage(result.message || 'Logged out.', true);
    await bootstrapSessionState();
  } catch (error) {
    setMessage('Could not reach the server to log out.');
  }
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function getSignalRiskRewardLabel(signal) {
  const entry = Number(signal?.entryPrice || 0);
  const target = Number(signal?.targetPrice || 0);
  const stop = Number(signal?.stopPrice || 0);
  if (!Number.isFinite(entry) || !Number.isFinite(target) || !Number.isFinite(stop)) {
    return '--';
  }
  const reward = Math.abs(target - entry);
  const risk = Math.abs(entry - stop);
  if (reward <= 0 || risk <= 0) {
    return '--';
  }
  return `${formatNumber(reward / risk, 2)}R`;
}

function setSignalsWelcome(primaryText, secondaryText = '') {
  if (!signalsWelcome) return;

  if (!secondaryText) {
    signalsWelcome.textContent = primaryText;
    return;
  }

  signalsWelcome.innerHTML = `
    <span class="signals-welcome-primary">${escapeHtml(primaryText)}</span>
    <span class="signals-welcome-secondary">${escapeHtml(secondaryText)}</span>
  `;
}

function formatDuration(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (days > 0) {
    return `${days}d ${String(hours).padStart(2, '0')}h ${String(minutes).padStart(2, '0')}m`;
  }

  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function getSignalCountdownState(signal) {
  const startsAt = Date.parse(signal.signalStartsAtUtc || '');
  const endsAt = Date.parse(signal.signalEndsAtUtc || '');
  const now = Date.now();

  if (!Number.isFinite(startsAt) || !Number.isFinite(endsAt)) {
    return { label: 'Timing window', value: 'Pending', status: 'pending' };
  }

  if (now < startsAt) {
    return { label: 'Starts in', value: formatDuration(startsAt - now), status: 'pending' };
  }

  if (now <= endsAt) {
    return { label: 'Window closes in', value: formatDuration(endsAt - now), status: 'live' };
  }

  return { label: 'Signal window', value: 'Closed', status: 'closed' };
}

function refreshSignalCountdowns() {
  document.querySelectorAll('[data-signal-countdown]').forEach((node) => {
    const signal = {
      signalStartsAtUtc: node.dataset.signalStart || '',
      signalEndsAtUtc: node.dataset.signalEnd || '',
    };
    const countdown = getSignalCountdownState(signal);
    const labelNode = node.querySelector('[data-signal-countdown-label]');
    const valueNode = node.querySelector('[data-signal-countdown-value]');
    if (labelNode) {
      labelNode.textContent = countdown.label;
    }
    if (valueNode) {
      valueNode.textContent = countdown.value;
    }
    node.dataset.timerState = countdown.status;
  });
}

function ensureSignalCountdownTimer() {
  if (signalCountdownHandle) {
    window.clearInterval(signalCountdownHandle);
    signalCountdownHandle = null;
  }

  if (!document.querySelector('[data-signal-countdown]')) {
    return;
  }

  refreshSignalCountdowns();
  signalCountdownHandle = window.setInterval(refreshSignalCountdowns, 1000);
}

function buildSignalAiScannerSummary() {
  const summary = state.cryptoData.summary || {};
  const cryptoItems = getLiveCryptoItems();
  if (!cryptoItems.length) {
    return null;
  }

  const totalAssets = Number(summary.tracked_assets || cryptoItems.length || 0);
  const positiveCount = Number(summary.positive_count || cryptoItems.filter((item) => Number(item.change ?? item.change_24h ?? 0) >= 0).length);
  const breadthRatio = totalAssets ? (positiveCount / totalAssets) : 0;
  const changes = cryptoItems.map((item) => Number(item.change ?? item.change_24h ?? 0)).filter((value) => Number.isFinite(value));
  const avgChange = changes.length ? changes.reduce((sum, value) => sum + value, 0) / changes.length : 0;
  const avgAbsChange = changes.length ? changes.reduce((sum, value) => sum + Math.abs(value), 0) / changes.length : 0;
  const leader = [...cryptoItems].sort((left, right) => Math.abs(Number(right.change ?? right.change_24h ?? 0)) - Math.abs(Number(left.change ?? left.change_24h ?? 0)))[0] || null;

  const shortWindowMoves = cryptoItems.map((item) => {
    const historyKey = item.symbol || item.id;
    const points = marketHistory.get(historyKey) || [];
    if (points.length < 6) {
      return null;
    }
    const start = Number(points[0]);
    const end = Number(points[points.length - 1]);
    if (!Number.isFinite(start) || !Number.isFinite(end) || start === 0) {
      return null;
    }
    return ((end - start) / start) * 100;
  }).filter((value) => Number.isFinite(value));
  const avgShortMove = shortWindowMoves.length ? shortWindowMoves.reduce((sum, value) => sum + value, 0) / shortWindowMoves.length : (avgChange / 6);

  let biasLabel = 'Mixed market watch';
  if (breadthRatio >= 0.65 && (avgChange > 0 || avgShortMove > 0)) {
    biasLabel = 'Bullish continuation watch';
  } else if (breadthRatio <= 0.35 && (avgChange < 0 || avgShortMove < 0)) {
    biasLabel = 'Bearish continuation watch';
  }

  const slopeLabel = avgShortMove >= 0.25
    ? 'Rising short-window slopes'
    : (avgShortMove <= -0.25 ? 'Falling short-window slopes' : 'Balanced short-window slopes');
  const volatilityLabel = avgAbsChange >= 4
    ? 'Volatility expansion'
    : (avgAbsChange >= 2 ? 'Active volatility' : 'Compressed volatility');
  const timingWindow = avgAbsChange >= 4
    ? '15-30 minute expansion window'
    : (Math.abs(avgShortMove) >= 0.35 ? '30-60 minute directional window' : '45-90 minute confirmation window');
  const updatedAt = Number(summary.updated_at || 0);
  const updatedLabel = updatedAt
    ? new Date(updatedAt * 1000).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
    : 'Waiting';

  return {
    biasLabel,
    slopeLabel,
    volatilityLabel,
    timingWindow,
    breadthLabel: `${positiveCount}/${totalAssets} tracked assets positive`,
    leaderName: leader ? `${leader.symbol || leader.id} ${formatSignedPercent(Number(leader.change ?? leader.change_24h ?? 0))}` : 'Waiting for leader',
    avgShortMove,
    updatedLabel,
  };
}

function renderSignalAiScanner() {
  if (!signalAiScanner) {
    return;
  }

  const scanner = buildSignalAiScannerSummary();
  if (!scanner) {
    signalAiScanner.innerHTML = `
      <article class="panel-card signal-ai-card signal-ai-card--lead">
        <span class="signal-ai-kicker">Live engine</span>
        <h3>Waiting for market feed</h3>
        <p>The AI scanner will populate once live crypto breadth and momentum data are loaded.</p>
      </article>
    `;
    return;
  }

  signalAiScanner.innerHTML = `
    <article class="panel-card signal-ai-card signal-ai-card--lead">
      <span class="signal-ai-kicker">Probability engine</span>
      <h3>${escapeHtml(scanner.biasLabel)}</h3>
      <p>The AI watches breadth, slope changes, volatility expansion, and leadership rotation across tracked crypto markets to score likely move windows before confirmation.</p>
      <div class="signal-ai-disclaimer">This is a probability model, not a guarantee. It reads live pressure and timing windows rather than promising the next candle with certainty.</div>
      <span class="signal-ai-updated">Updated ${escapeHtml(scanner.updatedLabel)}</span>
    </article>
    <article class="panel-card signal-ai-card">
      <span class="signal-ai-metric-label">Breadth</span>
      <strong>${escapeHtml(scanner.breadthLabel)}</strong>
      <p>Cross-market participation tells the AI whether moves are broad or isolated.</p>
    </article>
    <article class="panel-card signal-ai-card">
      <span class="signal-ai-metric-label">Slope read</span>
      <strong>${escapeHtml(scanner.slopeLabel)}</strong>
      <p>Short-window line changes are scored for rising or fading pressure across tracked majors.</p>
    </article>
    <article class="panel-card signal-ai-card">
      <span class="signal-ai-metric-label">Timing window</span>
      <strong>${escapeHtml(scanner.timingWindow)}</strong>
      <p>${escapeHtml(scanner.volatilityLabel)} with an average micro-move of ${formatSignedPercent(scanner.avgShortMove)}.</p>
    </article>
    <article class="panel-card signal-ai-card signal-ai-card--leader">
      <span class="signal-ai-metric-label">Momentum leader</span>
      <strong>${escapeHtml(scanner.leaderName)}</strong>
      <p>The AI uses relative leadership to judge whether momentum is rotating or concentrating.</p>
    </article>
  `;
}

function renderSignalsPage(payload) {
  if (!signalsFeed || !signalsSummary || !signalsWelcome || !signalsEmpty) return;

  if (!payload || !payload.member) {
    ensureSignalCountdownTimer();
    signalsWelcome.textContent = 'Log in to open your signal board and review the tiers attached to your account.';
    signalsSummary.innerHTML = `
      <article class="panel-card signal-summary-card signal-summary-card--focus">
        <span class="signal-summary-label">Signal access</span>
        <div class="signal-summary-value">0<small>signals/day</small></div>
        <p class="signal-summary-copy">Sign in to load your paid tiers, active setups, and member-only market routes.</p>
        <div class="signal-summary-pills">
          <span class="signal-summary-pill signal-summary-pill--muted">Member login required</span>
        </div>
      </article>
      <article class="panel-card signal-summary-card">
        <span class="signal-summary-label">Board format</span>
        <div class="signal-summary-value">5<small>signal fields</small></div>
        <p class="signal-summary-copy">Every live setup is presented with entry, target, stop, thesis, and route in a single card.</p>
        <div class="signal-summary-pills">
          <span class="signal-summary-pill">Entry</span>
          <span class="signal-summary-pill">Target</span>
          <span class="signal-summary-pill">Stop</span>
        </div>
      </article>
      <article class="panel-card signal-summary-card signal-summary-card--route">
        <span class="signal-summary-label">Upgrade path</span>
        <div class="signal-summary-value">Live<small>tier options</small></div>
        <p class="signal-summary-copy">Upgrade cards remain available below so you can compare tiers before logging in.</p>
        <div class="signal-summary-pills">
          <span class="signal-summary-pill signal-summary-pill--soft">Preview available</span>
        </div>
      </article>
    `;
    signalsFeed.innerHTML = '';
    const emptyTitle = signalsEmpty.querySelector('h3');
    const emptyCopy = signalsEmpty.querySelector('p');
    if (emptyTitle) {
      emptyTitle.textContent = 'Log in to unlock your member board';
    }
    if (emptyCopy) {
      emptyCopy.textContent = 'Your active signals will appear here once you sign in. Upgrade tiers remain available below.';
    }
    signalsEmpty.classList.remove('hidden');
    return;
  }

  setSignalsWelcome(
    `Welcome back, ${payload.member.fullName || payload.member.username}.`,
    'Here is your curated signal board for today.'
  );
  const portfolio = payload.portfolio || { purchases: [], signalsPerDay: 0, activeTiers: 0 };
  const activeSignals = Array.isArray(payload.signals) ? payload.signals : [];
  const purchasePills = Array.isArray(portfolio.purchases) && portfolio.purchases.length
    ? portfolio.purchases.slice(0, 4).map((purchase) => `<span class="signal-summary-pill">${escapeHtml(purchase.tierName)}</span>`).join('')
    : '<span class="signal-summary-pill signal-summary-pill--muted">No active paid tiers</span>';
  const unlockedAssets = [...new Set(activeSignals.map((signal) => String(signal.assetSymbol || '').toUpperCase()).filter(Boolean))];
  const marketPills = unlockedAssets.length
    ? unlockedAssets.slice(0, 5).map((assetSymbol) => `<span class="signal-summary-pill signal-summary-pill--soft">${escapeHtml(assetSymbol)}</span>`).join('')
    : '<span class="signal-summary-pill signal-summary-pill--soft">Waiting for unlocked setups</span>';
  const currencyNote = escapeHtml(payload.currency?.privacyNote || 'Displayed in your selected member currency.');
  signalsSummary.innerHTML = `
    <article class="panel-card signal-summary-card signal-summary-card--focus">
      <span class="signal-summary-label">Unlocked flow</span>
      <div class="signal-summary-value">${portfolio.signalsPerDay || 0}<small>signals/day</small></div>
      <p class="signal-summary-copy">${portfolio.activeTiers || 0} paid tier${portfolio.activeTiers === 1 ? '' : 's'} currently attached to this member account.</p>
      <div class="signal-summary-pills">${purchasePills}</div>
    </article>
    <article class="panel-card signal-summary-card">
      <span class="signal-summary-label">Active board</span>
      <div class="signal-summary-value">${activeSignals.length}<small>setups live</small></div>
      <p class="signal-summary-copy">${activeSignals.length ? 'Your unlocked signal flow is ready for quick review and route handoff.' : 'No setups are visible yet in this member view.'}</p>
      <div class="signal-summary-pills">${marketPills}</div>
    </article>
    <article class="panel-card signal-summary-card signal-summary-card--route">
      <span class="signal-summary-label">Display & route</span>
      <div class="signal-summary-value">${escapeHtml(payload.currency.code)}<small>member currency</small></div>
      <p class="signal-summary-copy">${currencyNote}</p>
      <div class="market-route-row">
        <select id="signalsMarketSelect" class="currency-select market-select" aria-label="Select crypto market">
          <option value="bitvavo">Bitvavo</option>
        </select>
        <button id="openMarketBtn" class="primary-btn" type="button">Open selected market</button>
      </div>
    </article>
  `;

  signalsMarketSelect = document.getElementById('signalsMarketSelect');
  openMarketBtn = document.getElementById('openMarketBtn');
  openMarketBtn?.addEventListener('click', () => {
    const firstSignal = activeSignals[0];
    const symbol = firstSignal?.assetSymbol || 'btc';
    window.open(getBitvavoMarketUrl(symbol), '_blank', 'noopener,noreferrer');
  });

  if (!activeSignals.length) {
    signalsFeed.innerHTML = '';
    signalsEmpty.classList.remove('hidden');
    ensureSignalCountdownTimer();
    return;
  }

  signalsEmpty.classList.add('hidden');
  signalsFeed.innerHTML = activeSignals.map((signal) => {
    const assetSymbol = escapeHtml(String(signal.assetSymbol || 'Asset').toUpperCase());
    const direction = escapeHtml(signal.direction || 'Long');
    const directionClass = String(signal.direction || 'long').toLowerCase() === 'short' ? 'is-short' : 'is-long';
    const cardToneClass = directionClass === 'is-short' ? 'member-signal-card--short' : 'member-signal-card--long';
    const sessionLabel = escapeHtml(signal.sessionLabel || 'All-day session');
    const marketLabel = escapeHtml(signal.market || `${assetSymbol}/USD`);
    const confidenceLabel = escapeHtml(signal.confidenceLabel || 'Structured');
    const thesis = escapeHtml(signal.thesis || 'No execution note provided.');
    const statusLabel = escapeHtml(signal.status || 'published');
    const riskRewardLabel = getSignalRiskRewardLabel(signal);
    const countdown = getSignalCountdownState(signal);
    const startsAtLabel = signal.signalStartsAtUtc
      ? new Date(signal.signalStartsAtUtc).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) + ' UTC'
      : `${escapeHtml(signal.signalTimeUtc || '--:--')} UTC`;

    return `
      <article class="panel-card member-signal-card ${cardToneClass}">
        <div class="member-signal-topline">
          <span class="signal-tier-pill">Tier ${signal.tierNumber}</span>
          <span class="signal-session-pill">${sessionLabel}</span>
          <span class="signal-direction-pill ${directionClass}">${direction}</span>
        </div>
        <div class="member-signal-head">
          <div class="member-signal-title">
            <h3>${assetSymbol}</h3>
            <p>${marketLabel}</p>
          </div>
          <span class="signal-confidence">${confidenceLabel}</span>
        </div>
        <div class="member-signal-timing">
          <article class="member-signal-timebox">
            <span>Signal time</span>
            <strong>${startsAtLabel}</strong>
          </article>
          <article class="member-signal-timebox member-signal-timebox--countdown" data-signal-countdown data-signal-start="${escapeHtml(signal.signalStartsAtUtc || '')}" data-signal-end="${escapeHtml(signal.signalEndsAtUtc || '')}" data-timer-state="${escapeHtml(countdown.status)}">
            <span data-signal-countdown-label>${escapeHtml(countdown.label)}</span>
            <strong data-signal-countdown-value>${escapeHtml(countdown.value)}</strong>
          </article>
        </div>
        <div class="member-signal-prices">
          <article class="member-signal-price member-signal-price--entry"><span>Entry</span><strong>${formatCurrencyAmount(signal.entryPrice)}</strong></article>
          <article class="member-signal-price member-signal-price--target"><span>Target</span><strong>${formatCurrencyAmount(signal.targetPrice)}</strong></article>
          <article class="member-signal-price member-signal-price--stop"><span>Stop</span><strong>${formatCurrencyAmount(signal.stopPrice)}</strong></article>
        </div>
        <div class="member-signal-meta">
          <span class="signal-stat-pill signal-stat-pill--rr">R:R ${riskRewardLabel}</span>
          <span class="signal-stat-pill signal-stat-pill--status">${statusLabel}</span>
          <span class="signal-stat-pill signal-stat-pill--route">Direct route</span>
        </div>
        <div class="member-signal-thesis">
          <span>Execution note</span>
          <p>${thesis}</p>
        </div>
        <div class="member-signal-actions">
          <a class="bitvavo-btn member-market-btn" href="${getBitvavoMarketUrl(signal.assetSymbol)}" target="_blank" rel="noreferrer">
            <span class="member-market-btn-label">Open ${assetSymbol} on Bitvavo</span>
            <span class="member-market-btn-meta">${sessionLabel}</span>
          </a>
        </div>
      </article>
    `;
  }).join('');
  ensureSignalCountdownTimer();
}

function getTierPresentation(tierNumber, signalsPerDay) {
  const presentations = {
    1: {
      badge: 'Focused',
      headline: 'Built for members who want a cleaner single setup each day.',
      note: 'A restrained daily flow with enough context to keep decision quality high.',
      toneClass: 'signal-tier-card--starter',
    },
    2: {
      badge: 'Balanced',
      headline: 'A steadier signal rhythm for members who want broader session coverage.',
      note: 'Balanced flow across the day without turning the board into noise.',
      toneClass: 'signal-tier-card--balanced',
    },
    3: {
      badge: 'Priority',
      headline: 'Higher coverage for active traders who want more opportunity flow.',
      note: 'Best fit for members who review the board repeatedly through the session.',
      toneClass: 'signal-tier-card--priority',
    },
  };

  return presentations[tierNumber] || {
    badge: signalsPerDay >= 5 ? 'Priority' : 'Focused',
    headline: 'Structured access designed for disciplined signal consumption.',
    note: 'Use the tier that matches the pace you can execute consistently.',
    toneClass: 'signal-tier-card--starter',
  };
}

async function loadMemberSignals() {
  if (!signalsFeed) return;
  try {
    const response = await fetchFresh('/api/member/signals');
    const result = await response.json();
    if (!response.ok) {
      renderSignalsPage(null);
      return;
    }
    state.signals = result.signals || [];
    renderSignalsPage(result);
  } catch (error) {
    renderSignalsPage(null);
  } finally {
    await loadPurchaseTiers();
  }
}

async function loadPurchaseTiers() {
  if (!purchaseTiers) return;
  try {
    const response = await fetchFresh('/api/member/purchase-tiers');
    const result = await response.json();
    if (!response.ok) return;
    renderPurchaseTiers(result);
  } catch (error) {
    console.error('Failed to load purchase tiers:', error);
  }
}

function renderPurchaseTiers(payload) {
  if (!purchaseTiers) return;
  const tiers = Array.isArray(payload?.tiers) ? payload.tiers : [];
  if (!tiers.length) {
    purchaseTiers.innerHTML = `
      <article class="panel-card member-empty-state">
        <h3>No upgrade tiers available</h3>
        <p>Pricing options will appear here when the tier catalogue is loaded.</p>
      </article>
    `;
    return;
  }

  purchaseTiers.innerHTML = tiers.map((tier) => {
    const presentation = getTierPresentation(Number(tier.tierNumber || 0), Number(tier.signalsPerDay || 0));
    const tierName = escapeHtml(tier.tierName);
    const description = escapeHtml(tier.description || 'Unlock a stronger signal flow for this member account.');
    const signalsPerDay = Number(tier.signalsPerDay || 0);
    const displayPrice = Number(tier.displayPrice || 0);
    const priceLabel = `${escapeHtml(payload.currency.symbol)}${displayPrice.toFixed(2)}`;
    const tierFeatures = [
      `${signalsPerDay} daily signal${signalsPerDay === 1 ? '' : 's'}`,
      signalsPerDay >= 5 ? 'Highest board coverage' : (signalsPerDay >= 3 ? 'Balanced session flow' : 'Focused starter flow'),
      'Member dashboard access',
      'Direct market route',
    ];
    return `
      <article class="panel-card signal-tier-card ${presentation.toneClass}">
        <div class="tier-band">
          <span class="tier-kicker">Tier ${tier.tierNumber}</span>
          <span class="tier-status-pill">${presentation.badge}</span>
        </div>
        <div class="tier-head">
          <div>
            <h3>${tierName}</h3>
            <p class="tier-headline">${presentation.headline}</p>
          </div>
          <span class="tier-density-pill">${signalsPerDay}/day</span>
        </div>
        <p class="tier-description">${description}</p>
        <div class="tier-feature-list">
          ${tierFeatures.map((feature) => `<span class="tier-feature-pill">${escapeHtml(feature)}</span>`).join('')}
        </div>
        <div class="tier-pricing">
          <strong class="price">${priceLabel}</strong>
          <span class="billing-cycle">per month</span>
        </div>
        <p class="tier-card-note">${presentation.note}</p>
        <button class="primary-btn buy-tier-btn" data-tier-number="${tier.tierNumber}" type="button">
          Unlock ${tierName}
        </button>
      </article>
    `;
  }).join('');
  
  // Add click handlers to buy buttons
  purchaseTiers.querySelectorAll('.buy-tier-btn').forEach((btn) => {
    btn.addEventListener('click', () => handleBuyTier(tiers, parseInt(btn.dataset.tierNumber)));
  });
}

async function handleBuyTier(tiers, tierNumber) {
  const tier = tiers.find(t => t.tierNumber === tierNumber);
  if (!tier) return;

  if (!state.member) {
    setMessage('Log in to unlock a signal tier from the board.');
    openAuthModal('login');
    return;
  }
  
  try {
    const response = await fetch('/api/member/purchases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tierNumber: tier.tierNumber,
        tierName: tier.tierName,
        planName: 'Monthly',
        billingCycle: 'monthly',
        billingMethod: 'paypal',
        priceGbp: tier.priceGbp,
        signalsPerDay: tier.signalsPerDay,
      }),
    });
    
    const result = await response.json();
    if (!response.ok) {
      setMessage(result.message || 'Purchase failed. Please try again.', false);
      return;
    }
    
    setMessage(result.message || 'Purchase successful!', true);
    await loadMemberSignals();
  } catch (error) {
    setMessage('Could not process purchase.', false);
  }
}

function openAuthModal(mode = 'login') {
  setAuthMode(mode);
  setMessage(mode === 'login' ? 'Log in to access member-only checkout.' : 'Create an account to unlock tier checkout.');
  authModal?.classList.remove('hidden');
}

function closeAuthModal() {
  authModal?.classList.add('hidden');
}

function openFeedbackModal() {
  if (!feedbackModal || !feedbackForm || !feedbackMessage) return;
  feedbackMessage.textContent = '';
  feedbackForm.reset();
  feedbackModal.classList.remove('hidden');
}

function closeFeedbackModal() {
  feedbackModal.classList.add('hidden');
}

async function handleFeedbackSubmit(event) {
  event.preventDefault();
  const email = document.getElementById('feedbackEmail').value.trim();
  const topic = document.getElementById('feedbackTopic').value.trim();
  const question = document.getElementById('feedbackQuestion').value.trim();

  if (!email || !topic || !question) {
    feedbackMessage.textContent = 'Please provide email, topic and question.';
    return;
  }

  try {
    const response = await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, topic, question }),
    });
    const result = await response.json();
    if (!response.ok) {
      feedbackMessage.textContent = result.message || 'Could not send feedback.';
      feedbackMessage.style.borderColor = 'rgba(255,255,255,0.1)';
      feedbackMessage.style.color = 'rgba(255,255,255,0.72)';
      return;
    }
    feedbackMessage.textContent = result.message || 'Thank you! Your feedback has been received.';
    feedbackMessage.style.borderColor = 'rgba(76,239,120,0.5)';
    feedbackMessage.style.color = '#4ce88e';
    feedbackForm.reset();
  } catch {
    feedbackMessage.textContent = 'Could not reach the server. Please try again later.';
  }
}

function updateMemberStatus() {
  if (!memberStatus) return;

  if (state.member) {
    const roleLabel = state.member.isAdmin ? 'Admin account' : 'Member account';
    const verificationText = state.member.discordVerificationStatus === 'verified'
      ? `Discord level: ${state.member.discordTag || 'verified'}`
      : 'Discord level pending system verification';
    memberStatus.textContent = `${roleLabel}: ${state.member.email} · ${verificationText}`;
    memberStatus.classList.add('active');
    memberStatus.classList.remove('hidden');
  } else {
    memberStatus.textContent = '';
    memberStatus.classList.remove('active');
    memberStatus.classList.add('hidden');
  }
  applyDiscordVerificationUI();
}

function setPageSection(targetId, shouldScroll = true) {
  if (targetId === 'auth' || targetId === 'account') {
    openAuthModal('login');
    return;
  }

  if (targetId === 'feedback') {
    openFeedbackModal();
    return;
  }

  pageTabs.forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.target === targetId);
  });
  tabPanels.forEach((panel) => {
    panel.classList.toggle('active', panel.id === targetId);
  });

  const section = document.getElementById(targetId);
  if (section && shouldScroll) {
    section.scrollIntoView({ behavior: 'smooth' });
  }
}

function markRevealItems(selector, stepDelay = 55, maxDelay = 280) {
  const nodes = document.querySelectorAll(selector);
  nodes.forEach((node, index) => {
    const delayMs = Math.min(index * stepDelay, maxDelay);
    node.classList.add('reveal-item');
    node.style.setProperty('--reveal-delay', `${delayMs}ms`);
  });
}

function initRevealMotion() {
  const sections = Array.from(document.querySelectorAll('section'));

  markRevealItems('.pricing-page-hero', 0, 0);
  markRevealItems('.hero-spotlight', 0, 0);
  markRevealItems('.hero-proof-list li', 50, 180);
  markRevealItems('.feature-grid > article', 65, 230);
  markRevealItems('.split-section > article', 95, 240);
  markRevealItems('.pricing-grid > article', 80, 220);
  markRevealItems('.tier-cube-grid > article', 52, 280);
  markRevealItems('.price-trust-bar > span', 45, 180);
  markRevealItems('.banner-card', 0, 0);

  const extraRevealItems = Array.from(document.querySelectorAll('.reveal-item'));
  const revealTargets = [...new Set([...sections, ...extraRevealItems])];
  if (!revealTargets.length) {
    return;
  }

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduceMotion || typeof IntersectionObserver !== 'function') {
    revealTargets.forEach((target) => {
      if (target.classList.contains('section')) {
        target.classList.add('visible');
      }
      target.classList.add('is-visible');
    });
    return;
  }

  const observer = new IntersectionObserver((entries, currentObserver) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) {
        return;
      }

      const target = entry.target;
      if (target.classList.contains('section')) {
        target.classList.add('visible');
      }
      target.classList.add('is-visible');
      currentObserver.unobserve(target);
    });
  }, {
    root: null,
    threshold: 0.16,
    rootMargin: '0px 0px -10% 0px',
  });

  revealTargets.forEach((target) => observer.observe(target));
}

async function handleAuthSubmit(event) {
  event.preventDefault();

  const formData = new FormData(authForm);
  const email = formData.get('email')?.trim() || '';
  const password = formData.get('password') || '';
  const rememberMe = Boolean(formData.get('rememberLogin'));

  let payload = { email, password };
  if (state.authMode === 'signup') {
    const consentToDataStorage = Boolean(formData.get('dataConsent'));
    if (!consentToDataStorage) {
      setMessage('You must consent to Vault Signals storing your submitted account data before creating an account.');
      return;
    }
    payload = {
      username: formData.get('username')?.trim() || '',
      fullName: formData.get('fullName')?.trim() || '',
      email,
      password,
      rememberMe,
      zipcode: formData.get('zipcode')?.trim() || '',
      address: formData.get('address')?.trim() || '',
      discordUsername: formData.get('discordUsername')?.trim() || '',
      consentToDataStorage,
    };
  } else {
    payload = { email, password, rememberMe };
  }

  const endpoint = state.authMode === 'signup' ? '/api/accounts' : '/api/login';

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const rawResult = await response.text();
    let result = {};
    if (rawResult) {
      try {
        result = JSON.parse(rawResult);
      } catch {
        result = { message: rawResult };
      }
    }

    if (!response.ok) {
      if (state.authMode === 'signup' && response.status === 409) {
        setMessage((result.message || 'Account already exists.') + ' Switching to login...', true);
        setUnverifiedActionsVisible(false);
        setAuthMode('login');
        const emailInput = document.getElementById('email');
        if (emailInput) emailInput.value = email;
        return;
      }
      setUnverifiedActionsVisible(false);
      setMessage(result.message || `Request failed (${response.status}).`);
      return;
    }

    state.member = result.user;
    if (result.currency) {
      state.activeCurrency = result.currency;
    }
    setMessage(result.message, true);
    setUnverifiedActionsVisible(false);
    updateMemberStatus();
    updateMemberActions();
    hydrateBillingFromMember();
    updateCheckoutLocks();
    renderCheckoutReview();
    authForm.reset();
    closeAuthModal();
    populateCurrencySelectors();
    setPricingMode(switchBusiness?.classList.contains('active') ? 'business' : 'personal');
    await loadMemberSignals();
    window.location.assign('/dashboard');

  } catch (error) {
    const runningOnFlaskLocalhost = window.location.protocol === 'http:' && (window.location.host === '127.0.0.1:5000' || window.location.host === 'localhost:5000');
    if (!runningOnFlaskLocalhost) {
      setMessage('Could not reach the server. Open the app from http://127.0.0.1:5000 (not Live Server or file preview), then try again.');
      return;
    }
    setMessage('Could not reach the server. Make sure the Python app is running on http://127.0.0.1:5000.');
  }
}

function setBillingMessage(message, ok = false) {
  if (!billingMessage) return;
  billingMessage.textContent = message;
  billingMessage.style.borderColor = ok ? 'rgba(76,239,120,0.5)' : 'rgba(255,255,255,0.1)';
  billingMessage.style.color = ok ? '#84f5a9' : 'rgba(255,255,255,0.78)';
}

function getMatrixPrice(tier, tag, cycle) {
  const tierData = getPricingMatrix()[tier];
  if (!tierData || !tierData[tag]) return null;
  const price = tierData[tag][cycle];
  return typeof price === 'number' ? price : null;
}

function refreshBillingQuote() {
  if (!billingTier || !billingDiscordTag || !billingCycle || !billingQuote || !billingSignals) return;

  const tier = Number(billingTier.value);
  const tag = billingDiscordTag.value || 'final';
  const cycle = billingCycle.value;

  billingSignals.value = String(tier);

  const price = getMatrixPrice(tier, tag, cycle);

  if (orderSummaryTierName) orderSummaryTierName.textContent = `Tier ${tier}`;
  if (orderSummarySignals) orderSummarySignals.textContent = String(tier);
  if (orderSummaryCycle) orderSummaryCycle.textContent = CHECKOUT_CYCLE_SUMMARY_LABELS[cycle] || cycle;

  if (price === null) {
    billingQuote.textContent = 'Selected combination is not available.';
    billingQuote.style.borderColor = 'rgba(255,255,255,0.22)';
    billingQuote.style.color = 'rgba(255,255,255,0.8)';
    return;
  }

  billingQuote.textContent = `Estimated price: ${formatCheckoutMoney(convertFromGbp(price))}`;
  billingQuote.style.borderColor = 'rgba(76,239,120,0.35)';
  billingQuote.style.color = '#84f5a9';
}

function hydrateBillingFromMember() {
  if (!state.member) return;
  if (billingDiscordTag && state.member.discordTag) {
    billingDiscordTag.value = state.member.discordTag;
  }
  if (billingFullName && state.member.fullName) {
    billingFullName.value = state.member.fullName;
  }
  refreshBillingQuote();
}

function setCheckoutStep(step) {
  currentCheckoutStep = step;
  checkoutStep1?.classList.toggle('active', step === 1);
  checkoutStep2?.classList.toggle('active', step === 2);
  checkoutStep3?.classList.toggle('active', step === 3);

  stepChips?.forEach((chip) => {
    const chipStep = Number(chip.dataset.stepChip);
    chip.classList.toggle('active', chipStep === step);
  });
}

function updateCheckoutLocks() {
  const isLoggedIn = Boolean(state.member);

  checkoutStep2Lock?.classList.toggle('hidden', isLoggedIn);
  checkoutStep3Lock?.classList.toggle('hidden', isLoggedIn);
  checkoutStep2Content?.classList.toggle('locked', !isLoggedIn);
  paymentMethodBar?.classList.toggle('locked', !isLoggedIn);
  checkoutStep3Content?.classList.toggle('locked', !isLoggedIn);

  if (step2RequiredNote) {
    step2RequiredNote.textContent = isLoggedIn ? '' : 'Account required';
  }
  if (step3RequiredNote) {
    step3RequiredNote.textContent = isLoggedIn ? '' : 'Account required';
  }
}

function renderCheckoutReview() {
  const tier = Number(billingTier?.value || 1);
  const cycle = billingCycle?.value || 'weekly';
  const tag = billingDiscordTag?.value || 'final';
  const tagLabel = tag === 'final' ? 'Standard (no discount)' : tag.replace('_', ' ');
  const price = getMatrixPrice(tier, tag, cycle);
  const subtotal = price === null ? 0 : price;
  const tax = subtotal * VAT_RATE;
  const total = subtotal + tax;
  const convertedSubtotal = price === null ? null : convertFromGbp(subtotal);
  const convertedTax = price === null ? null : convertFromGbp(tax);
  const convertedTotal = price === null ? null : convertFromGbp(total);

  if (reviewTier) reviewTier.textContent = `Tier ${tier}`;
  if (reviewSignals) reviewSignals.textContent = String(tier);
  if (reviewCycle) reviewCycle.textContent = CHECKOUT_CYCLE_REVIEW_LABELS[cycle] || cycle;
  if (reviewMethod) reviewMethod.textContent = PAYMENT_LABELS[selectedPaymentMethod] || selectedPaymentMethod;
  if (reviewTag) reviewTag.textContent = tagLabel;
  if (reviewSubtotal) reviewSubtotal.textContent = convertedSubtotal === null ? 'N/A' : formatCheckoutMoney(convertedSubtotal);
  if (reviewTax) reviewTax.textContent = convertedTax === null ? 'N/A' : formatCheckoutMoney(convertedTax);
  if (reviewPrice) reviewPrice.textContent = convertedTotal === null ? 'N/A' : formatCheckoutMoney(convertedTotal);
}

function openCheckoutModal(pickedTier = null) {
  if (pickedTier && billingTier) {
    billingTier.value = String(pickedTier);
  }
  refreshBillingQuote();
  renderCheckoutReview();
  updateCheckoutLocks();
  setCheckoutStep(1);
  checkoutModal?.classList.remove('hidden');
}

function closeCheckoutModal() {
  checkoutModal?.classList.add('hidden');
}

async function handleBillingSubmit(event) {
  event.preventDefault();

  if (!state.member) {
    setBillingMessage('Log in first, then complete billing.');
    openAuthModal('login');
    return;
  }

  const tierNumber = Number(billingTier?.value || '0');
  const cycleValue = billingCycle?.value || '';
  const discordTag = billingDiscordTag?.value || 'final';
  const payloadBillingName = billingFullName?.value.trim() || '';
  const payloadBillingCompany = billingCompany?.value.trim() || '';
  const payloadBillingAddress = billingAddress?.value.trim() || '';
  const payloadBillingZip = billingZip?.value.trim() || '';
  const payloadBillingCountry = billingCountry?.value.trim() || '';
  const termsAccepted = Boolean(termsAgree?.checked);

  if (!tierNumber || !cycleValue) {
    setBillingMessage('Please complete all billing fields.');
    return;
  }

  if (!payloadBillingName || !payloadBillingAddress || !payloadBillingZip || !payloadBillingCountry) {
    setBillingMessage('Please complete billing name and full address details.');
    setCheckoutStep(2);
    return;
  }

  if (!termsAccepted) {
    setBillingMessage('You must agree to the terms and conditions before ordering.');
    setCheckoutStep(3);
    return;
  }

  const price = getMatrixPrice(tierNumber, discordTag, cycleValue);
  if (price === null) {
    setBillingMessage('This combination is not available. Try another duration or tier.');
    return;
  }

  try {
    const response = await fetch('/api/purchase', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: state.member.email,
        tierNumber,
        tierName: `Tier ${tierNumber}`,
        billingCycle: cycleValue,
        discordTag,
        billingName: payloadBillingName,
        billingCompany: payloadBillingCompany,
        billingAddress: payloadBillingAddress,
        billingZip: payloadBillingZip,
        billingCountry: payloadBillingCountry,
        billingMethod: selectedPaymentMethod,
        termsAgree: termsAccepted,
      }),
    });

    const result = await response.json();
    if (!response.ok) {
      setBillingMessage(result.message || 'Could not create billing order.');
      return;
    }

    setBillingMessage(result.message || `Purchase confirmed at ${formatCheckoutMoney(convertFromGbp(price))}.`, true);
    setCheckoutStep(3);
    if (result.paymentUrl) {
      window.open(result.paymentUrl, '_blank', 'noopener,noreferrer');
    }
    await loadMemberSignals();
  } catch (error) {
    setBillingMessage('Could not connect to server for billing checkout.');
  }
}

async function handleTierClick(event) {
  const tierName = event.currentTarget.dataset.tier;

  if (!state.member) {
    setMessage('Create or log into your member account before choosing a tier.');
    openAuthModal('signup');
    return;
  }

  try {
    const response = await fetch('/api/purchase', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: state.member.email, tierName }),
    });

    const result = await response.json();
    if (!response.ok) {
      setMessage(result.message || 'Could not add tier.');
      return;
    }

    setMessage(`${result.message} Checkout routing can be connected next.`, true);
    document.getElementById('checkout').scrollIntoView({ behavior: 'smooth' });
  } catch (error) {
    setMessage('Could not save the selected tier.');
  }
}

function initMenu() {
  if (!menuToggle || !navLinks) return;
  menuToggle.setAttribute('aria-expanded', 'false');

  const closeMenu = () => {
    navLinks.classList.remove('open');
    menuToggle.setAttribute('aria-expanded', 'false');
  };

  menuToggle.addEventListener('click', (event) => {
    event.stopPropagation();
    const isOpen = navLinks.classList.toggle('open');
    menuToggle.setAttribute('aria-expanded', String(isOpen));
  });

  navLinks.querySelectorAll('a').forEach((link) => {
    link.addEventListener('click', closeMenu);
  });

  document.addEventListener('click', (event) => {
    if (!navLinks.classList.contains('open')) return;
    if (!event.target.closest('.navbar')) {
      closeMenu();
    }
  });
}


let canvas;
let ctx;
let particles = [];
const particleCount = 80;
let backgroundMode = 4; // 4 = full stock market background

function resizeCanvas() {
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
}

function initParticles() {
  particles = Array.from({ length: particleCount }, () => ({
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    size: Math.random() * 2.4 + 0.6,
    speed: Math.random() * 0.7 + 0.2,
    drift: (Math.random() - 0.5) * 0.25,
    alpha: Math.random() * 0.45 + 0.2,
  }));
}

function setBackgroundMode(mode) {
  backgroundMode = mode;
}

function drawBackgroundAnimation() {
  if (backgroundMode === 4) {
    drawStockMarketBackground();
  } else if (backgroundMode === 1) {
    drawMode1();
  } else if (backgroundMode === 2) {
    drawMode2();
  } else if (backgroundMode === 3) {
    drawMode3();
  }

  window.requestAnimationFrame(drawBackgroundAnimation);
}

function isReloadNavigation() {
  try {
    const navEntries = performance.getEntriesByType('navigation');
    if (navEntries && navEntries.length > 0) {
      return navEntries[0].type === 'reload';
    }
  } catch {
    // Ignore and fallback to legacy API below.
  }

  return Boolean(performance.navigation && performance.navigation.type === 1);
}

function redirectToHomeOnHardReload() {
  if (!isReloadNavigation()) return false;

  const pathname = window.location.pathname || '/';
  const allowReloadPaths = [
    '/',
    '/index.html',
    '/price',
    '/about-us',
    '/terms-and-conditions',
    '/your-signals',
    '/settings',
    '/account/dashboard',
    '/account/profile',
    '/pro',
    '/pro-mode',
  ];
  const isServerRenderedPath = allowReloadPaths.includes(pathname) || pathname.startsWith('/community/account/');
  if (isServerRenderedPath) return false;

  window.location.replace('/');
  return true;
}

function setupPage() {
  if (redirectToHomeOnHardReload()) {
    return;
  }

  if ('scrollRestoration' in window.history) {
    window.history.scrollRestoration = 'manual';
  }
  window.scrollTo({ top: 0, left: 0, behavior: 'auto' });

  authForm = document.getElementById('authForm');
  authMessage = document.getElementById('authMessage');
  submitBtn = document.getElementById('submitBtn');
  rememberLoginGroup = document.getElementById('rememberLoginGroup');
  rememberLogin = document.getElementById('rememberLogin');
  dataConsentGroup = document.getElementById('dataConsentGroup');
  dataConsent = document.getElementById('dataConsent');
  usernameGroup = document.getElementById('usernameGroup');
  fullNameGroup = document.getElementById('fullNameGroup');
  addressGroup = document.getElementById('addressGroup');
  zipcodeGroup = document.getElementById('zipcodeGroup');
  discordTagGroup = document.getElementById('discordTagGroup');
  discordLevelGroup = document.getElementById('discordLevelGroup');
  discordUsernameInput = document.getElementById('discordUsername');
  signupDiscordTagSelect = document.getElementById('discordTag');
  discordVerificationHint = document.getElementById('discordVerificationHint');
  memberStatus = document.getElementById('memberStatus');
  tabButtons = document.querySelectorAll('.tab-btn');
  tierButtons = document.querySelectorAll('.tier-btn');
  heroCreateAccount = document.getElementById('heroCreateAccount');
  loginTriggers = document.querySelectorAll('[data-login-trigger]');
  liveDeskCoins = document.getElementById('liveDeskCoins');
  liveDeskFeedStatus = document.getElementById('liveDeskFeedStatus');
  liveDeskTrackedCount = document.getElementById('liveDeskTrackedCount');
  liveDeskMarketLeader = document.getElementById('liveDeskMarketLeader');
  liveDeskMarketLeaderMeta = document.getElementById('liveDeskMarketLeaderMeta');
  liveDeskFeedMode = document.getElementById('liveDeskFeedMode');
  liveDeskFeedModeMeta = document.getElementById('liveDeskFeedModeMeta');
  liveDeskSelectedName = document.getElementById('liveDeskSelectedName');
  liveDeskSelectedMeta = document.getElementById('liveDeskSelectedMeta');
  liveDeskSelectedPrice = document.getElementById('liveDeskSelectedPrice');
  liveDeskSelectedChange = document.getElementById('liveDeskSelectedChange');
  liveDeskMarketCap = document.getElementById('liveDeskMarketCap');
  liveDeskVolume = document.getElementById('liveDeskVolume');
  liveDeskHigh = document.getElementById('liveDeskHigh');
  liveDeskLow = document.getElementById('liveDeskLow');
  liveDeskChart = document.getElementById('liveDeskChart');
  switchPersonal = document.getElementById('switchPersonal');
  switchBusiness = document.getElementById('switchBusiness');
  feedbackTriggers = document.querySelectorAll('[data-feedback-trigger]');
  feedbackModal = document.getElementById('feedbackModal');
  feedbackModalClose = document.getElementById('feedbackModalClose');
  feedbackForm = document.getElementById('feedbackForm');
  feedbackMessage = document.getElementById('feedbackMessage');
  authModal = document.getElementById('authModal');
  authModalClose = document.getElementById('authModalClose');
  authUnverifiedActions = document.getElementById('authUnverifiedActions');
  resendVerificationBtn = document.getElementById('resendVerificationBtn');
  changeUnverifiedEmailBtn = document.getElementById('changeUnverifiedEmailBtn');
  verifyTokenInput = document.getElementById('verifyTokenInput');
  verifyTokenBtn = document.getElementById('verifyTokenBtn');
  currencySelectors = document.querySelectorAll('[data-currency-selector]');
  currencyNoteEls = document.querySelectorAll('[data-currency-note]');
  memberPortalLinks = document.querySelectorAll('[data-member-portal-link]');
  logoutButtons = document.querySelectorAll('[data-logout-button]');
  menuToggle = document.getElementById('menuToggle');
  navLinks = document.getElementById('navLinks');
  tickerContent = document.getElementById('tickerContent');
  pageTabs = document.querySelectorAll('.page-tab');
  tabPanels = document.querySelectorAll('.tab-panel');
  billingForm = document.getElementById('billingForm');
  billingMessage = document.getElementById('billingMessage');
  billingTier = document.getElementById('billingTier');
  billingCycle = document.getElementById('billingCycle');
  billingDiscordTag = document.getElementById('billingDiscordTag');
  billingSignals = document.getElementById('billingSignals');
  billingQuote = document.getElementById('billingQuote');
    orderSummaryTierName = document.getElementById('orderSummaryTierName');
    orderSummarySignals  = document.getElementById('orderSummarySignals');
    orderSummaryCycle    = document.getElementById('orderSummaryCycle');
  miniTierButtons = document.querySelectorAll('.mini-tier-btn');
  priceCtaButtons = document.querySelectorAll('.price-cta-btn[data-tier-pick]');
  checkoutModal = document.getElementById('checkoutModal');
  checkoutModalClose = document.getElementById('checkoutModalClose');
  checkoutStep1 = document.getElementById('checkoutStep1');
  checkoutStep2 = document.getElementById('checkoutStep2');
  checkoutStep3 = document.getElementById('checkoutStep3');
  stepChips = document.querySelectorAll('.step-chip');
  billingNextToStep2 = document.getElementById('billingNextToStep2');
  billingBackToStep1 = document.getElementById('billingBackToStep1');
  billingNextToStep3 = document.getElementById('billingNextToStep3');
  billingBackToStep2 = document.getElementById('billingBackToStep2');
  checkoutStep2Lock = document.getElementById('checkoutStep2Lock');
  checkoutStep3Lock = document.getElementById('checkoutStep3Lock');
  checkoutStep2Content = document.getElementById('checkoutStep2Content');
  checkoutStep3Content = document.getElementById('checkoutStep3Content');
  step2RequiredNote = document.getElementById('step2RequiredNote');
  step3RequiredNote = document.getElementById('step3RequiredNote');
  paymentMethodBar = document.getElementById('paymentMethodBar');
  paymentMethodButtons = document.querySelectorAll('.payment-method-btn');
  billingFullName = document.getElementById('billingFullName');
  billingCompany = document.getElementById('billingCompany');
  billingAddress = document.getElementById('billingAddress');
  billingZip = document.getElementById('billingZip');
  billingCountry = document.getElementById('billingCountry');
  reviewTier = document.getElementById('reviewTier');
  reviewSignals = document.getElementById('reviewSignals');
  reviewCycle = document.getElementById('reviewCycle');
  reviewMethod = document.getElementById('reviewMethod');
  reviewTag = document.getElementById('reviewTag');
  reviewSubtotal = document.getElementById('reviewSubtotal');
  reviewTax = document.getElementById('reviewTax');
  reviewPrice = document.getElementById('reviewPrice');
  termsAgree = document.getElementById('termsAgree');
  signalsWelcome = document.getElementById('signalsWelcome');
  signalsSummary = document.getElementById('signalsSummary');
  signalsFeed = document.getElementById('signalsFeed');
  signalsEmpty = document.getElementById('signalsEmpty');
  purchaseTiers = document.getElementById('purchaseTiers');
  signalAiScanner = document.getElementById('signalAiScanner');
  canvas = document.getElementById('marketCanvas');
  if (canvas) {
    ctx = canvas.getContext('2d');
  }

  if (canvas && ctx) {
    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();
    initParticles();
    window.requestAnimationFrame(drawBackgroundAnimation);
  }

  initRevealMotion();

  initMenu();

  initCryptoTicker();
  setInterval(initCryptoTicker, 10000);
  if (liveDeskCoins || liveDeskChart) {
    loadLiveDesk();
    if (!liveDeskRefreshHandle) {
      liveDeskRefreshHandle = window.setInterval(() => {
        loadLiveDesk(state.liveDesk.selectedCoinId || '');
      }, 60000);
    }
  }

  tabButtons.forEach((btn) => {
    btn.addEventListener('click', () => setAuthMode(btn.dataset.mode));
  });
  resendVerificationBtn?.addEventListener('click', resendVerificationForCurrentEmail);
  changeUnverifiedEmailBtn?.addEventListener('click', changeUnverifiedEmailForCurrentUser);
  verifyTokenBtn?.addEventListener('click', verifyTokenFromInput);

  currencySelectors?.forEach((selector) => selector.addEventListener('change', handleCurrencyChange));
  logoutButtons?.forEach((button) => button.addEventListener('click', handleLogout));

  authForm?.addEventListener('submit', handleAuthSubmit);
  tierButtons.forEach((btn) => btn.addEventListener('click', handleTierClick));

  pageTabs.forEach((btn) => {
    btn.addEventListener('click', () => setPageSection(btn.dataset.target));
  });

  feedbackTriggers?.forEach((trigger) => {
    trigger.addEventListener('click', (event) => {
      event.preventDefault();
      openFeedbackModal();
    });
  });

  liveDeskCoins?.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-live-coin]');
    if (!trigger) {
      return;
    }
    const coinId = trigger.dataset.liveCoin || '';
    if (!coinId || coinId === state.liveDesk.selectedCoinId) {
      return;
    }
    loadLiveDesk(coinId);
  });

  feedbackModalClose?.addEventListener('click', closeFeedbackModal);
  feedbackForm?.addEventListener('submit', handleFeedbackSubmit);

  heroCreateAccount?.addEventListener('click', (event) => {
    event.preventDefault();
    openAuthModal('signup');
  });

  loginTriggers?.forEach((trigger) => {
    trigger.addEventListener('click', (event) => {
      event.preventDefault();
      openAuthModal('login');
    });
  });

  authModalClose?.addEventListener('click', closeAuthModal);
  authModal?.addEventListener('click', (event) => {
    if (event.target === authModal) {
      closeAuthModal();
    }
  });

  feedbackModal?.addEventListener('click', (event) => {
    if (event.target === feedbackModal) {
      closeFeedbackModal();
    }
  });

  switchPersonal?.addEventListener('click', () => setPricingMode('personal'));
  switchBusiness?.addEventListener('click', () => setPricingMode('business'));

  billingForm?.addEventListener('submit', handleBillingSubmit);
  billingTier?.addEventListener('change', refreshBillingQuote);
  billingTier?.addEventListener('change', renderCheckoutReview);
  billingCycle?.addEventListener('change', refreshBillingQuote);
  billingCycle?.addEventListener('change', renderCheckoutReview);
  billingDiscordTag?.addEventListener('change', refreshBillingQuote);
  billingDiscordTag?.addEventListener('change', renderCheckoutReview);
  checkoutModalClose?.addEventListener('click', closeCheckoutModal);
  checkoutModal?.addEventListener('click', (event) => {
    if (event.target === checkoutModal) {
      closeCheckoutModal();
    }
  });

  billingNextToStep2?.addEventListener('click', () => {
    if (!state.member) {
      setBillingMessage('Log in first to continue to billing details.');
      openAuthModal('login');
      updateCheckoutLocks();
      setCheckoutStep(2);
      return;
    }
    setCheckoutStep(2);
  });

  billingBackToStep1?.addEventListener('click', () => setCheckoutStep(1));

  billingNextToStep3?.addEventListener('click', () => {
    if (!state.member) {
      setBillingMessage('Account required before review and payment.');
      openAuthModal('login');
      updateCheckoutLocks();
      setCheckoutStep(3);
      return;
    }
    renderCheckoutReview();
    setCheckoutStep(3);
  });

  billingBackToStep2?.addEventListener('click', () => setCheckoutStep(2));

  paymentMethodButtons?.forEach((btn) => {
    btn.addEventListener('click', () => {
      selectedPaymentMethod = btn.dataset.paymentMethod || 'creditcard';
      paymentMethodButtons.forEach((item) => item.classList.toggle('active', item === btn));
      renderCheckoutReview();
    });
  });

  miniTierButtons?.forEach((btn) => {
    btn.addEventListener('click', () => {
      const pickedTier = btn.dataset.tierPick;
      if (billingTier && pickedTier) {
        billingTier.value = pickedTier;
        openCheckoutModal(pickedTier);
      }
    });
  });

  priceCtaButtons?.forEach((btn) => {
    btn.addEventListener('click', () => {
      const pickedTier = btn.dataset.tierPick;
      if (billingTier && pickedTier) {
        billingTier.value = pickedTier;
        openCheckoutModal(pickedTier);
      }
    });
  });

  const navAnchors = document.querySelectorAll('.nav-links a');
  navAnchors.forEach((link) => {
    if (link.id === 'navLoginLink') {
      link.addEventListener('click', (event) => {
        event.preventDefault();
        openAuthModal('login');
      });
      return;
    }

    link.addEventListener('click', (event) => {
      const href = link.getAttribute('href');
      if (href && href.startsWith('#')) {
        event.preventDefault();
        const targetId = href.replace('#', '');
        if (targetId === 'home') {
          window.scrollTo({ top: 0, behavior: 'smooth' });
        } else {
          setPageSection(targetId);
        }
      }
    });
  });

  setAuthMode('signup');
  setPageSection('homeSection', false);
  setPricingMode('personal');
  maybeTriggerBrowserNotificationPermission();
  updateMemberStatus();
  updateMemberActions();
  hydrateBillingFromMember();
  refreshBillingQuote();
  renderCheckoutReview();
  updateCheckoutLocks();
  bootstrapSessionState();

  // Final safety pass: keep initial load pinned to top with header visible.
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
  });
}

function setPricingMode(mode) {
  if (!switchPersonal || !switchBusiness) return;

  switchPersonal.classList.toggle('active', mode === 'personal');
  switchBusiness.classList.toggle('active', mode === 'business');

  const plusCard = document.getElementById('plusCard');
  const businessCard = document.getElementById('businessCard');
  const pricingCycleNote = document.getElementById('pricingCycleNote');
  const plusSave = document.getElementById('plusSave');
  const businessSave = document.getElementById('businessSave');
  const promoPlans = getPromoPlans();
  const starter = promoPlans.starter || DEFAULT_PROMO_PLANS_GBP.starter;
  const business = promoPlans.business || DEFAULT_PROMO_PLANS_GBP.business;

  if (!plusCard || !businessCard) return;

  if (mode === 'personal') {
    plusCard.querySelector('.price-value').innerHTML = `${formatCheckoutMoney(convertFromGbp(starter.monthly))}<span>/month</span>`;
    plusCard.querySelector('.price-sub').textContent = 'Monthly billing (includes VAT)';
    plusCard.querySelector('.price-tagline').textContent = 'Start simple with 1 signal/day';
    if (plusSave) plusSave.textContent = `or ${formatCheckoutMoney(convertFromGbp(starter.annual_monthly))}/mo billed annually`;

    businessCard.querySelector('.price-value').innerHTML = `${formatCheckoutMoney(convertFromGbp(business.monthly))}<span>/month</span>`;
    businessCard.querySelector('.price-sub').textContent = 'Monthly billing (includes VAT)';
    businessCard.querySelector('.price-tagline').textContent = 'Blue business plan for teams';
    if (businessSave) businessSave.textContent = `or ${formatCheckoutMoney(convertFromGbp(business.annual_monthly))}/mo billed annually`;

    if (pricingCycleNote) pricingCycleNote.textContent = 'Monthly billing selected. Cancel anytime.';
  } else {
    const tier1YearSave = starter.monthly * 12 - starter.annual_total;
    const busiYearSave = business.monthly * 12 - business.annual_total;
    plusCard.querySelector('.price-value').innerHTML = `${formatCheckoutMoney(convertFromGbp(starter.annual_monthly))}<span>/month</span>`;
    plusCard.querySelector('.price-sub').textContent = `Billed annually at ${formatCheckoutMoney(convertFromGbp(starter.annual_total))}`;
    plusCard.querySelector('.price-tagline').textContent = 'Starter annual plan with lower cost';
    if (plusSave) plusSave.textContent = `Save ${formatCheckoutMoney(convertFromGbp(tier1YearSave))} per year`;

    businessCard.querySelector('.price-value').innerHTML = `${formatCheckoutMoney(convertFromGbp(business.annual_monthly))}<span>/month</span>`;
    businessCard.querySelector('.price-sub').textContent = `Billed annually at ${formatCheckoutMoney(convertFromGbp(business.annual_total))}`;
    businessCard.querySelector('.price-tagline').textContent = 'Business annual plan with best team value';
    if (businessSave) businessSave.textContent = `Save ${formatCheckoutMoney(convertFromGbp(busiYearSave))} per year`;

    if (pricingCycleNote) pricingCycleNote.textContent = 'Annual billing selected. Best value for committed traders.';
  }

  renderTierCubePrices();
}

function renderTierCubePrices() {
  const tierCards = document.querySelectorAll('.tier-cube[data-tier]');
  tierCards.forEach((card) => {
    const tier = Number(card.dataset.tier || '0');
    const priceNode = card.querySelector('.tier-cube-price');
    if (!tier || !priceNode) {
      return;
    }
    const monthlyPrice = getMatrixPrice(tier, 'final', 'monthly');
    if (monthlyPrice === null) {
      return;
    }
    priceNode.innerHTML = `${formatCheckoutMoney(convertFromGbp(monthlyPrice))}<span>/month</span>`;
  });
}

document.addEventListener('DOMContentLoaded', setupPage);

function drawStockMarketBackground() {
  const bg = ctx.createLinearGradient(0, 0, 0, canvas.height);
  bg.addColorStop(0, '#01040b');
  bg.addColorStop(0.5, '#030a15');
  bg.addColorStop(1, '#050b13');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const now = Date.now();
  for (let i = 0; i < 16; i++) {
    const x = (i * 120 + (now / 16)) % canvas.width;
    ctx.fillStyle = `rgba(24, 255, 124, ${0.08 + (Math.sin(now / 330 + i) + 1) / 20})`;
    ctx.fillRect(x, 0, 1.2, canvas.height);
    ctx.fillRect(x + 1, 0, 1.2, canvas.height);
  }

  ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
  ctx.lineWidth = 1;
  const grid = 70;
  for (let x = 0; x < canvas.width; x += grid) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, canvas.height);
    ctx.stroke();
  }
  for (let y = 0; y < canvas.height; y += grid) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(canvas.width, y);
    ctx.stroke();
  }

  drawCandlestickSeries(now);

  const time = now / 1000;
  const featuredMarkets = getLiveCryptoItems();
  for (let i = 0; i < 6; i++) {
    drawPriceLine(i, time);
  }

  drawFloatingData(time);
  drawMarketSummaryPanel();
  drawMarketTickerTape(time);

  ctx.fillStyle = 'rgba(255,255,255,0.9)';
  ctx.font = 'bold 19px Arial';
  ctx.fillText('CRYPTO MARKET LIVE', 24, 42);
  ctx.fillStyle = 'rgba(34,255,180,0.75)';
  ctx.font = '14px Arial';
  if (featuredMarkets.length) {
    const headline = featuredMarkets.slice(0, 2).map((item) => {
      const change = Number(item.change) || 0;
      return `${item.symbol} ${getCanvasPriceLabel(item.price)} ${change >= 0 ? '+' : ''}${formatNumber(change, 2)}%`;
    }).join('   ');
    ctx.fillText(headline, 24, 64);
  } else {
    ctx.fillText('Fetching live crypto market data...', 24, 64);
  }
}

function drawCandlestickSeries(now) {
  const candleCount = 26;
  const candleWidth = Math.max(4, Math.floor(canvas.width / candleCount / 2));
  const baseY = canvas.height * 0.70;
  const heightRange = canvas.height * 0.20;

  for (let i = 0; i < candleCount; i++) {
    const x = ((i * (candleWidth + 6)) + (now / 8)) % (canvas.width + candleWidth) - candleWidth;
    const volatility = (Math.sin(now / 790 + i) + 1) / 2;
    const pctBase = 0.4 + (i / candleCount) * 0.08 + Math.sin(now / 980 + i / 1.5) * 0.06;
    const open = baseY - (pctBase * heightRange);
    const close = baseY - ((pctBase + (volatility - 0.5) * 0.08) * heightRange);
    const high = Math.min(open, close) - (8 + Math.abs(Math.cos(now / 540 + i) * 16));
    const low = Math.max(open, close) + (8 + Math.abs(Math.sin(now / 660 + i) * 12));

    const bull = close >= open;
    const shadowColor = bull ? 'rgba(76,239,120,0.7)' : 'rgba(239,76,76,0.75)';
    const bodyColor = bull ? 'rgba(76,239,120,0.35)' : 'rgba(239,76,76,0.35)';

    ctx.strokeStyle = shadowColor;
    ctx.fillStyle = bodyColor;
    ctx.lineWidth = 1.4;

    ctx.beginPath();
    ctx.moveTo(x + candleWidth / 2, high);
    ctx.lineTo(x + candleWidth / 2, low);
    ctx.stroke();

    ctx.fillRect(x, Math.min(open, close), candleWidth, Math.max(1, Math.abs(close - open)));
    ctx.strokeRect(x, Math.min(open, close), candleWidth, Math.max(1, Math.abs(close - open)));
  }
}

function drawPriceLine(index, time) {
  const baseY = canvas.height * (0.2 + (index / 8) * 0.6);
  const amplitude = 40 + index * 10;
  const frequency = 0.002 + index * 0.0005;
  const phase = index * 0.5;

  ctx.beginPath();
  ctx.strokeStyle = `rgba(76, 239, 120, ${0.3 + index * 0.1})`;
  ctx.lineWidth = 2;

  for (let x = 0; x < canvas.width; x += 2) {
    const y = baseY + Math.sin(x * frequency + time + phase) * amplitude + Math.sin(x * 0.01 + time * 2) * 20;
    if (x === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function formatNumber(value, decimals = 2) {
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function formatCompactCurrency(value) {
  const numericValue = Number(value) || 0;
  if (numericValue >= 1_000_000_000_000) return `$${formatNumber(numericValue / 1_000_000_000_000, 2)}T`;
  if (numericValue >= 1_000_000_000) return `$${formatNumber(numericValue / 1_000_000_000, 2)}B`;
  if (numericValue >= 1_000_000) return `$${formatNumber(numericValue / 1_000_000, 2)}M`;
  if (numericValue >= 1_000) return `$${formatNumber(numericValue / 1_000, 2)}K`;
  if (numericValue >= 1) return `$${formatNumber(numericValue, 2)}`;
  return `$${formatNumber(numericValue, 4)}`;
}

function getCanvasPriceLabel(value) {
  const numericValue = Number(value) || 0;
  if (numericValue >= 1000) return `$${formatNumber(numericValue, 0)}`;
  if (numericValue >= 1) return `$${formatNumber(numericValue, 2)}`;
  return `$${formatNumber(numericValue, 4)}`;
}

function getLiveCryptoItems() {
  if (!Array.isArray(state.cryptoData.crypto)) return [];
  return state.cryptoData.crypto.filter((item) => Number.isFinite(Number(item.price)));
}

function getResponsiveMarketCount() {
  if (!canvas) return 4;
  if (canvas.width < 640) return 3;
  if (canvas.width < 960) return 4;
  return 6;
}

function recordMarketSnapshot(items) {
  items.forEach((item) => {
    const key = item.symbol || item.id;
    const numericPrice = Number(item.price);
    if (!key || !Number.isFinite(numericPrice)) return;

    const points = marketHistory.get(key) || [];
    points.push(numericPrice);
    if (points.length > MAX_MARKET_HISTORY_POINTS) {
      points.shift();
    }
    marketHistory.set(key, points);
  });
}

function drawSparkline(x, y, width, height, points, positive) {
  const usablePoints = points.filter((point) => Number.isFinite(Number(point)));
  if (usablePoints.length < 2) return;

  const minValue = Math.min(...usablePoints);
  const maxValue = Math.max(...usablePoints);
  const range = Math.max(maxValue - minValue, maxValue * 0.003, 1);

  ctx.beginPath();
  usablePoints.forEach((point, index) => {
    const px = x + (index / (usablePoints.length - 1)) * width;
    const normalized = (point - minValue) / range;
    const py = y + height - (normalized * height);
    if (index === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.strokeStyle = positive ? 'rgba(76, 239, 120, 0.88)' : 'rgba(239, 76, 76, 0.88)';
  ctx.lineWidth = 1.8;
  ctx.stroke();
}

function drawMarketSummaryPanel() {
  const summary = state.cryptoData.summary;
  if (!summary || !summary.tracked_assets) return;

  const panelWidth = canvas.width < 700 ? 170 : 220;
  const panelHeight = canvas.width < 700 ? 86 : 98;
  const panelX = canvas.width - panelWidth - 24;
  const panelY = 24;

  ctx.fillStyle = 'rgba(5, 12, 20, 0.62)';
  ctx.fillRect(panelX, panelY, panelWidth, panelHeight);
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
  ctx.lineWidth = 1;
  ctx.strokeRect(panelX, panelY, panelWidth, panelHeight);

  ctx.fillStyle = 'rgba(255,255,255,0.92)';
  ctx.font = 'bold 13px Arial';
  ctx.fillText('Market Snapshot', panelX + 12, panelY + 20);

  ctx.fillStyle = 'rgba(180, 255, 210, 0.78)';
  ctx.font = '12px Arial';
  ctx.fillText(`Cap ${formatCompactCurrency(summary.market_cap)}`, panelX + 12, panelY + 42);
  ctx.fillText(`24h Vol ${formatCompactCurrency(summary.volume_24h)}`, panelX + 12, panelY + 60);

  ctx.fillStyle = 'rgba(255,255,255,0.75)';
  ctx.fillText(`BTC Dom ${formatNumber(summary.btc_dominance || 0, 2)}%`, panelX + 12, panelY + 78);
  ctx.fillText(`${summary.positive_count || 0}/${summary.tracked_assets} green`, panelX + 110, panelY + 78);
}

function drawMarketTickerTape(time) {
  const cryptoItems = getLiveCryptoItems();
  if (!cryptoItems.length) return;

  const tape = cryptoItems.slice(0, 8).map((item) => {
    const change = Number(item.change) || 0;
    return `${item.symbol} ${getCanvasPriceLabel(item.price)} ${change >= 0 ? '+' : ''}${formatNumber(change, 2)}%`;
  }).join('   |   ');

  const tapeSpeed = ((time * 1000) / 18) % (canvas.width * 2);
  ctx.fillStyle = 'rgba(180, 255, 210, 0.64)';
  ctx.font = '13px monospace';
  ctx.fillText(tape, -tapeSpeed, canvas.height - 22);
  ctx.fillText(tape, canvas.width - tapeSpeed, canvas.height - 22);
}

function drawFallbackFloatingData(time) {
  const symbols = ['BTC', 'ETH', 'BNB', 'SOL', 'ADA', 'DOT', 'XRP', 'LTC'];
  const basePrices = [43567, 2893, 345, 112, 1.34, 4.56, 0.63, 78];

  symbols.forEach((symbol, i) => {
    const x = 80 + (canvas.width - 160) / symbols.length * i;
    const y = 112 + Math.sin(time * 1.4 + i) * 24;

    ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
    ctx.font = 'bold 15px Arial';
    ctx.fillText(symbol, x, y);

    const price = basePrices[i] + Math.sin(time * (1.2 + i * 0.12)) * (basePrices[i] * 0.013);
    const change = Math.sin(time * (2 + i * 0.2)) * 4.8;

    ctx.fillStyle = 'rgba(76, 239, 120, 0.9)';
    ctx.font = '13px Arial';
    ctx.fillText(`$${formatNumber(price, symbol === 'BTC' || symbol === 'ETH' ? 2 : 4)}`, x, y + 20);

    ctx.fillStyle = change >= 0 ? 'rgba(76, 239, 120, 0.95)' : 'rgba(239, 76, 76, 0.95)';
    ctx.fillText(`${change >= 0 ? '+' : ''}${formatNumber(change, 2)}%`, x, y + 40);
  });
}

function drawFloatingData(time) {
  const items = getLiveCryptoItems().slice(0, getResponsiveMarketCount());
  if (!items.length) {
    drawFallbackFloatingData(time);
    return;
  }

  const horizontalPadding = canvas.width < 640 ? 24 : 60;
  const slotWidth = (canvas.width - horizontalPadding * 2) / items.length;
  const cardWidth = Math.max(72, slotWidth - 14);
  const cardHeight = canvas.width < 640 ? 62 : 70;
  const baseY = canvas.width < 640 ? 112 : 118;

  items.forEach((item, index) => {
    const x = horizontalPadding + slotWidth * index;
    const y = baseY + Math.sin(time * 1.1 + index) * 12;
    const change = Number(item.change) || 0;
    const price = Number(item.price) || 0;
    const positive = change >= 0;
    const history = marketHistory.get(item.symbol) || [];

    ctx.fillStyle = 'rgba(5, 12, 20, 0.42)';
    ctx.fillRect(x, y - 18, cardWidth, cardHeight);
    ctx.strokeStyle = positive ? 'rgba(76, 239, 120, 0.28)' : 'rgba(239, 76, 76, 0.28)';
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y - 18, cardWidth, cardHeight);

    ctx.fillStyle = 'rgba(255, 255, 255, 0.92)';
    ctx.font = 'bold 14px Arial';
    ctx.fillText(item.symbol, x + 8, y);

    ctx.fillStyle = positive ? 'rgba(76, 239, 120, 0.94)' : 'rgba(239, 76, 76, 0.94)';
    ctx.font = '12px Arial';
    ctx.fillText(`${change >= 0 ? '+' : ''}${formatNumber(change, 2)}%`, x + 8, y + 18);

    ctx.fillStyle = 'rgba(255, 255, 255, 0.82)';
    ctx.fillText(getCanvasPriceLabel(price), x + 8, y + 34);

    drawSparkline(x + 8, y + 42, Math.max(26, cardWidth - 16), 10, history, positive);
  });
}

function drawMode1() {
  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
  gradient.addColorStop(0, 'rgba(10, 18, 26, 0.62)');
  gradient.addColorStop(0.6, 'rgba(0, 0, 0, 0.45)');
  gradient.addColorStop(1, 'rgba(2, 3, 6, 0.92)');

  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const lineY = canvas.height * 0.32;
  const amplitude = 38;
  const period = 2600;

  ctx.beginPath();
  for (let x = 0; x <= canvas.width; x += 4) {
    const sine = Math.sin((x / 72) + Date.now() / period) * amplitude;
    const y = lineY + sine;
    if (x === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.strokeStyle = 'rgba(242, 193, 78, 0.22)';
  ctx.lineWidth = 1.35;
  ctx.stroke();

  particles.forEach((particle) => {
    particle.x += particle.drift * 0.6;
    particle.y -= particle.speed;

    if (particle.y < -10) {
      particle.y = canvas.height + 10;
      particle.x = Math.random() * canvas.width;
    }
    if (particle.x < -10) particle.x = canvas.width + 10;
    if (particle.x > canvas.width + 10) particle.x = -10;

    ctx.beginPath();
    ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(242,193,78, ${particle.alpha})`;
    ctx.fill();
  });
}

function drawMode2() {
  const base = ctx.createLinearGradient(0, 0, 0, canvas.height);
  base.addColorStop(0, 'rgba(5, 10, 13, 0.85)');
  base.addColorStop(1, 'rgba(0, 0, 0, 0.95)');
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  for (let i = 0; i < 120; i++) {
    const x = (i * 45 + Date.now() / 25) % canvas.width;
    const height = ((Math.sin(Date.now() / 180 + i) + 1) / 2) * (canvas.height * 0.35) + 20;
    ctx.fillStyle = `rgba(76, 239, 120, ${0.06 + (Math.sin(Date.now() / 520 + i) + 1) / 30})`;
    ctx.fillRect(x, canvas.height - height, 2.8, height);
  }

  ctx.strokeStyle = 'rgba(242, 193, 78, 0.15)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let x = 0; x <= canvas.width; x += 5) {
    const y = canvas.height * 0.45 + Math.sin((x / 55) + Date.now() / 3300) * 22;
    if (x === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function drawMode3() {
  const gradient = ctx.createRadialGradient(canvas.width * 0.7, canvas.height * 0.2, 20, canvas.width * 0.7, canvas.height * 0.2, canvas.width * 0.9);
  gradient.addColorStop(0, 'rgba(242, 193, 78, 0.16)');
  gradient.addColorStop(1, 'rgba(2, 2, 6, 0.95)');

  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  for (let i = 0; i < 40; i++) {
    const radius = 18 + Math.sin(Date.now() / 900 + i) * 8;
    const x = (canvas.width * (i / 40)) + Math.sin(Date.now() / 1700 + i) * 42;
    const y = canvas.height * 0.4 + Math.cos(Date.now() / 1300 + i) * 42;

    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(242, 193, 78, ${(0.04 + i / 220).toFixed(2)})`;
    ctx.fill();
  }

  ctx.fillStyle = 'rgba(255, 255, 255, 0.08)';
  ctx.fillRect(0, canvas.height - 110, canvas.width, 110);
}


function drawMarketFeedOverlay() {
  // background feed overlay removed for clean polished background; left as placeholder.
}
