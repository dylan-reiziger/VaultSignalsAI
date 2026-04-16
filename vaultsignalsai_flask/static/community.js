(function () {
  const currencyCode = document.body?.dataset.defaultCurrencyCode || 'GBP';
  const currencySymbol = document.body?.dataset.currencySymbol || '£';
  const chatPollMs = Math.max(3000, Number(document.body?.dataset.communityChatPollMs || '8000'));
  const LEADERBOARD_PAGE_SIZE = 5;

  const communityState = {
    activeView: 'global',
    whisperTarget: '',
    leaderboardScope: 'weekly',
    leaderboardIndex: 0,
    leaderboardAll: [],
    summary: null,
    network: null,
    inboxThreads: [],
    modalSnapshot: null,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function parseUtcDate(rawValue) {
    if (!rawValue) {
      return null;
    }
    const raw = String(rawValue).trim();
    if (!raw) {
      return null;
    }
    const normalized = raw.includes('T') ? raw : raw.replace(' ', 'T');
    const withTimezone = /Z$|[+-]\d\d:\d\d$/i.test(normalized) ? normalized : `${normalized}Z`;
    const parsed = new Date(withTimezone);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function formatDateTime(rawValue) {
    const parsed = parseUtcDate(rawValue);
    if (!parsed) {
      return 'Recently';
    }
    return parsed.toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  }

  function formatRelativeTime(rawValue) {
    const parsed = parseUtcDate(rawValue);
    if (!parsed) {
      return 'just now';
    }
    const diffMs = Date.now() - parsed.getTime();
    const diffMinutes = Math.max(0, Math.round(diffMs / 60000));
    if (diffMinutes < 1) {
      return 'just now';
    }
    if (diffMinutes < 60) {
      return `${diffMinutes}m ago`;
    }
    const diffHours = Math.round(diffMinutes / 60);
    if (diffHours < 24) {
      return `${diffHours}h ago`;
    }
    const diffDays = Math.round(diffHours / 24);
    return `${diffDays}d ago`;
  }

  function toTitleCase(value) {
    return String(value || '')
      .split(/\s+/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
      .join(' ');
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      cache: options.cache ?? 'no-store',
    });

    let result = {};
    try {
      result = await response.json();
    } catch {
      result = {};
    }

    return { response, result };
  }

  function formatMoney(value) {
    const amount = Number(value || 0);
    if (!Number.isFinite(amount)) {
      return `${currencySymbol}0.00`;
    }
    try {
      return new Intl.NumberFormat('en-GB', {
        style: 'currency',
        currency: currencyCode,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(amount);
    } catch {
      return `${currencySymbol}${amount.toFixed(2)}`;
    }
  }

  function setSettingsMessage(message, ok) {
    const node = $('communitySettingsMessage');
    if (!node) {
      return;
    }
    node.textContent = message;
    node.style.borderColor = ok ? 'rgba(76,239,120,0.45)' : 'rgba(255,255,255,0.12)';
    node.style.color = ok ? '#84f5a9' : 'rgba(255,255,255,0.78)';
  }

  function setListPlaceholder(id, message) {
    const node = $(id);
    if (!node) {
      return;
    }
    node.innerHTML = `<p class="chat-empty">${escapeHtml(message)}</p>`;
  }

  function buildBadgeMarkup(badges, emptyMessage = '', variant = 'compact', interactive = true) {
    const items = Array.isArray(badges) ? badges : [];
    if (!items.length) {
      return emptyMessage ? `<p class="chat-empty chat-empty--inline">${escapeHtml(emptyMessage)}</p>` : '';
    }
    if (window.VaultBadgeUI?.renderShieldBadge) {
      return items.map((badge) => window.VaultBadgeUI.renderShieldBadge(badge, { variant, interactive })).join('');
    }
    return items.map((badge) => {
      const tone = escapeHtml(badge.tone || 'gold');
      const label = escapeHtml(badge.label || badge.shortLabel || 'Badge');
      const shortLabel = escapeHtml(badge.shortLabel || badge.icon || badge.label || 'Badge');
      const tooltip = escapeHtml(badge.achievement || badge.label || '');
      return `
        <span class="community-mini-badge community-mini-badge--${tone}" title="${tooltip}">
          <span class="community-mini-badge-mark">${shortLabel}</span>
          <span class="community-mini-badge-text">${label}</span>
        </span>
      `;
    }).join('');
  }

  function updateGlobalMeta() {
    const meta = $('communityChatMeta');
    if (!meta) {
      return;
    }
    const account = communityState.summary?.account || {};
    const summary = communityState.summary?.summary || {};
    const connections = Number(account.connectionCounts?.connections || 0);
    const rank = account.userRank || '-';
    const tierBadge = account.tierBadge || 'No Tier';
    meta.textContent = `Tier: ${tierBadge}. Rank: ${rank}. Weekly P/L: ${formatMoney(summary.weekly?.profit)}. ${connections} accepted connection${connections === 1 ? '' : 's'}. The global room clears when the server restarts.`;
  }

  function updateWhisperMeta() {
    const meta = $('communityWhisperMeta');
    if (!meta) {
      return;
    }
    const target = (communityState.whisperTarget || $('communityWhisperTarget')?.value || '').trim();
    if (!target) {
      meta.textContent = 'Choose a connection, click a member from chat, or enter a username to open a whisper thread.';
      return;
    }
    const thread = communityState.inboxThreads.find((item) => String(item.username || '').toLowerCase() === target.toLowerCase());
    if (!thread) {
      meta.textContent = `Private thread with ${target}.`;
      return;
    }
    const statusText = thread.networkState === 'connected'
      ? 'Connected members can always message each other.'
      : 'This is an open direct thread.';
    const activityText = thread.lastMessageAt ? ` Last activity ${formatRelativeTime(thread.lastMessageAt)}.` : '';
    meta.textContent = `Private thread with ${thread.displayName || thread.username}. ${statusText}${activityText}`;
  }

  function renderAccountSummary(data) {
    communityState.summary = data;
    const account = data.account || {};
    const balance = data.balance || {};
    const summary = data.summary || {};
    const connections = account.connectionCounts || {};
    const privacyMode = account.privacyMode || 'public';
    const loyaltyLevel = toTitleCase(account.loyaltyLevel || 'bronze');
    const renameNote = $('communityRenameNote');

    if ($('communityDisplayName')) $('communityDisplayName').textContent = account.displayName || account.username || 'Member';
    if ($('communityTierBadge')) $('communityTierBadge').textContent = account.tierBadge || 'No Tier';
    if ($('communityRankBadge')) $('communityRankBadge').textContent = `Rank: ${account.userRank || '-'}`;
    if ($('communityAvatar')) $('communityAvatar').src = account.avatarUrl || '/static/vaultsignals-logo.png';
    if ($('communityAvatarInput')) $('communityAvatarInput').value = account.avatarUrl || '';
    if ($('communityBalance')) $('communityBalance').textContent = formatMoney(balance.current);
    if ($('communityInvested')) $('communityInvested').textContent = formatMoney(summary.lifetime?.invested);
    if ($('communityProfit')) $('communityProfit').textContent = formatMoney(summary.lifetime?.profit);
    if ($('communityConnectionsCount')) $('communityConnectionsCount').textContent = String(connections.connections || 0);
    if ($('communityIncomingCount')) $('communityIncomingCount').textContent = String(connections.incoming || 0);
    if ($('communityOutgoingCount')) $('communityOutgoingCount').textContent = String(connections.outgoing || 0);
    if ($('communityLoyaltyLevel')) $('communityLoyaltyLevel').textContent = loyaltyLevel;
    if ($('communityPrivacyState')) $('communityPrivacyState').textContent = privacyMode === 'private' ? 'Private profile' : 'Public profile';
    if ($('communityBio')) $('communityBio').textContent = account.bio || 'Add a short trading bio so people know what kind of setups you focus on.';
    if ($('communityBioInput')) $('communityBioInput').value = account.bio || '';
    if ($('communityPrivacyMode')) $('communityPrivacyMode').value = privacyMode;
    if ($('communityLeaderboardToggle')) $('communityLeaderboardToggle').checked = Boolean(account.showOnLeaderboard);
    if ($('communityIgnoreWhisper')) $('communityIgnoreWhisper').checked = Boolean(account.ignoreWhisper);
    if ($('communityBadgeStrip')) $('communityBadgeStrip').innerHTML = buildBadgeMarkup(data.badges, 'No badges unlocked yet.');

    if (renameNote) {
      const cooldownDays = Number(account.displayNameCooldownDays || 30);
      if (account.displayNameCanChange) {
        renameNote.textContent = `Display name changes live in Settings and are limited to one change every ${cooldownDays} days.`;
      } else {
        renameNote.textContent = `Display name is locked until ${formatDateTime(account.displayNameChangeAvailableAt)}. Change it from Settings, not from the live hub.`;
      }
    }

    updateGlobalMeta();
    updateWhisperMeta();
  }

  async function loadSummary() {
    const { response, result } = await requestJson('/api/community/summary');
    if (!response.ok) {
      setSettingsMessage(result.message || 'Could not load community summary.', false);
      return false;
    }
    renderAccountSummary(result);
    return true;
  }

  function setActiveView(view) {
    communityState.activeView = view;

    $('chatTabGlobal')?.classList.toggle('active', view === 'global');
    $('chatTabWhisper')?.classList.toggle('active', view === 'whisper');
    $('chatTabLeaderboard')?.classList.toggle('active', view === 'leaderboard');
    $('chatTabNetwork')?.classList.toggle('active', view === 'network');

    $('globalContent')?.classList.toggle('active', view === 'global');
    $('whisperContent')?.classList.toggle('active', view === 'whisper');
    $('leaderboardContent')?.classList.toggle('active', view === 'leaderboard');
    $('networkContent')?.classList.toggle('active', view === 'network');

    if (view === 'whisper') {
      updateWhisperMeta();
    } else if (view === 'global') {
      updateGlobalMeta();
    }
  }

  function startWhisper(username) {
    const target = String(username || '').trim();
    if (!target) {
      return;
    }
    communityState.whisperTarget = target;
    if ($('communityWhisperTarget')) {
      $('communityWhisperTarget').value = target;
    }
    setActiveView('whisper');
    Promise.all([loadInbox(), loadWhisperMessages()]).catch((error) => {
      console.error('Whisper bootstrap failed:', error);
    });
  }

  function attachMessageInteractions(listId) {
    const list = $(listId);
    if (!list) {
      return;
    }

    list.querySelectorAll('[data-open-profile]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = button.dataset.openProfile || '';
        if (!username) {
          return;
        }
        showUserProfile(username).catch((error) => console.error('Profile load failed:', error));
      });
    });

    list.querySelectorAll('[data-start-whisper]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = button.dataset.startWhisper || '';
        if (!username) {
          return;
        }
        startWhisper(username);
      });
    });
  }

  function renderMessageList(listId, messages, emptyMessage) {
    const list = $(listId);
    if (!list) {
      return;
    }

    if (!Array.isArray(messages) || !messages.length) {
      setListPlaceholder(listId, emptyMessage);
      return;
    }

    list.innerHTML = messages.map((message) => {
      const username = escapeHtml(message.username || 'member');
      const displayName = escapeHtml(message.displayName || message.username || 'Member');
      const avatarUrl = escapeHtml(message.avatarUrl || '/static/vaultsignals-logo.png');
      const userRank = message.userRank ? `<span class="chat-rank">${escapeHtml(message.userRank)}</span>` : '';
      const tierBadge = message.tierBadge ? `<span class="chat-badge">${escapeHtml(message.tierBadge)}</span>` : '';
      const whisperAction = message.isMine ? '' : `<button class="chat-whisper-btn" type="button" data-start-whisper="${username}">Message</button>`;
      return `
        <article class="chat-message${message.isMine ? ' mine' : ''}">
          <img class="chat-message-avatar" src="${avatarUrl}" alt="${displayName}" />
          <div class="chat-message-body">
            <div class="chat-line-top">
              ${tierBadge}
              <button class="chat-name" type="button" data-open-profile="${username}">${displayName}</button>
              ${userRank}
              <span class="chat-time">${escapeHtml(formatRelativeTime(message.createdAt))}</span>
              ${whisperAction}
            </div>
            <p>${escapeHtml(message.text || '')}</p>
          </div>
        </article>
      `;
    }).join('');

    attachMessageInteractions(listId);
    list.scrollTop = list.scrollHeight;
  }

  async function loadGlobalMessages() {
    const { response, result } = await requestJson('/api/community/chat/global');
    if (!response.ok) {
      setListPlaceholder('communityGlobalList', result.message || 'Could not load global chat.');
      return;
    }
    renderMessageList('communityGlobalList', result.messages || [], 'No messages yet.');
  }

  function renderThreadList(threads) {
    const list = $('communityThreadList');
    if (!list) {
      return;
    }

    if (!Array.isArray(threads) || !threads.length) {
      setListPlaceholder('communityThreadList', 'No private threads yet. Accept a connection or start a whisper from chat.');
      return;
    }

    list.innerHTML = threads.map((thread) => {
      const username = escapeHtml(thread.username || 'member');
      const displayName = escapeHtml(thread.displayName || thread.username || 'Member');
      const avatarUrl = escapeHtml(thread.avatarUrl || '/static/vaultsignals-logo.png');
      const preview = escapeHtml(thread.lastMessagePreview || 'No messages yet.');
      const badges = buildBadgeMarkup(thread.badges || [], '', 'compact', false);
      const active = String(thread.username || '').toLowerCase() === String(communityState.whisperTarget || '').toLowerCase();
      return `
        <button class="community-thread-item${active ? ' active' : ''}" type="button" data-thread-username="${username}">
          <img class="community-thread-avatar" src="${avatarUrl}" alt="${displayName}" />
          <span class="community-thread-copy">
            <span class="community-thread-name-row">
              <span class="community-thread-name">${displayName}</span>
              <span class="community-thread-time">${escapeHtml(thread.lastMessageAt ? formatRelativeTime(thread.lastMessageAt) : 'new')}</span>
            </span>
            <span class="community-thread-preview">${preview}</span>
            <span class="community-thread-badges">${badges}</span>
          </span>
        </button>
      `;
    }).join('');

    list.querySelectorAll('[data-thread-username]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = button.dataset.threadUsername || '';
        if (!username) {
          return;
        }
        communityState.whisperTarget = username;
        if ($('communityWhisperTarget')) {
          $('communityWhisperTarget').value = username;
        }
        loadWhisperMessages().catch((error) => console.error('Whisper load failed:', error));
        renderThreadList(communityState.inboxThreads);
      });
    });
  }

  async function loadInbox() {
    const { response, result } = await requestJson('/api/community/chat/inbox');
    if (!response.ok) {
      setListPlaceholder('communityThreadList', result.message || 'Could not load private inbox.');
      return;
    }

    communityState.inboxThreads = Array.isArray(result.threads) ? result.threads : [];
    if (!communityState.whisperTarget && communityState.inboxThreads.length) {
      communityState.whisperTarget = communityState.inboxThreads[0].username;
      if ($('communityWhisperTarget')) {
        $('communityWhisperTarget').value = communityState.whisperTarget;
      }
    }
    renderThreadList(communityState.inboxThreads);
    updateWhisperMeta();
  }

  async function loadWhisperMessages() {
    const target = (communityState.whisperTarget || $('communityWhisperTarget')?.value || '').trim();
    if (!target) {
      communityState.whisperTarget = '';
      updateWhisperMeta();
      setListPlaceholder('communityWhisperList', 'Enter a username or choose a connection to open a private thread.');
      return;
    }

    communityState.whisperTarget = target;
    if ($('communityWhisperTarget')) {
      $('communityWhisperTarget').value = target;
    }
    updateWhisperMeta();

    const { response, result } = await requestJson(`/api/community/chat/whisper/${encodeURIComponent(target)}`);
    if (!response.ok) {
      setListPlaceholder('communityWhisperList', result.message || 'Could not load whisper messages.');
      return;
    }

    renderMessageList('communityWhisperList', result.messages || [], 'No whisper messages yet.');
  }

  function renderLeaderInteractions() {
    const list = $('communityLeaderboardList');
    if (!list) {
      return;
    }

    list.querySelectorAll('[data-open-profile]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = button.dataset.openProfile || '';
        if (!username) {
          return;
        }
        showUserProfile(username).catch((error) => console.error('Profile load failed:', error));
      });
    });

    list.querySelectorAll('[data-start-whisper]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = button.dataset.startWhisper || '';
        if (!username) {
          return;
        }
        startWhisper(username);
      });
    });
  }

  function updateLeaderboardSlide() {
    const list = $('communityLeaderboardList');
    if (!list) {
      return;
    }

    const all = Array.isArray(communityState.leaderboardAll) ? communityState.leaderboardAll : [];
    const totalPages = all.length ? Math.ceil(all.length / LEADERBOARD_PAGE_SIZE) : 0;

    if (!all.length) {
      list.innerHTML = '<p class="chat-empty">No public leaderboard entries yet.</p>';
      if ($('leaderboardSlideInfo')) $('leaderboardSlideInfo').textContent = 'Page 0 / 0';
      if ($('leaderboardPrev')) $('leaderboardPrev').disabled = true;
      if ($('leaderboardNext')) $('leaderboardNext').disabled = true;
      return;
    }

    const page = Math.max(0, Math.min(communityState.leaderboardIndex, totalPages - 1));
    communityState.leaderboardIndex = page;
    const startIndex = page * LEADERBOARD_PAGE_SIZE;
    const pageEntries = all.slice(startIndex, startIndex + LEADERBOARD_PAGE_SIZE);

    list.innerHTML = pageEntries.map((entry, index) => {
      const rank = Number(entry.rank || (startIndex + index + 1));
      const displayName = escapeHtml(entry.displayName || entry.username || 'Member');
      const username = escapeHtml(entry.username || '');
      const avatarUrl = escapeHtml(entry.avatarUrl || '/static/vaultsignals-logo.png');
      const tierBadge = escapeHtml(entry.tierBadge || 'No Tier');
      const userRank = escapeHtml(entry.userRank || '');
      const score = formatMoney(entry.score || 0);
      const balance = formatMoney(entry.balance || 0);
      return `
        <div class="leader-row">
          <span class="leader-rank">#${rank}</span>
          <div class="leader-info">
            <div class="leader-main">
              <img class="leader-avatar" src="${avatarUrl}" alt="${displayName}" />
              <div class="leader-meta">
                <button class="leader-open-account" data-open-profile="${username}" type="button">${displayName}</button>
                <div class="leader-tags">
                  <span class="chat-badge">${tierBadge}</span>
                  ${userRank ? `<span class="chat-rank">${userRank}</span>` : ''}
                </div>
              </div>
            </div>
            <div class="leader-actions">
              <button class="community-inline-action" type="button" data-open-profile="${username}">View Stats</button>
              <button class="community-inline-action community-inline-action--gold" type="button" data-start-whisper="${username}">Message</button>
            </div>
          </div>
          <span class="leader-score" title="Balance: ${balance}">${score}</span>
        </div>
      `;
    }).join('');

    renderLeaderInteractions();
    if ($('leaderboardSlideInfo')) $('leaderboardSlideInfo').textContent = `Page ${page + 1} / ${totalPages}`;
    if ($('leaderboardPrev')) $('leaderboardPrev').disabled = page <= 0;
    if ($('leaderboardNext')) $('leaderboardNext').disabled = page >= totalPages - 1;
  }

  async function loadLeaderboard(scope = communityState.leaderboardScope) {
    communityState.leaderboardScope = scope;
    $('leaderboardWeekly')?.classList.toggle('active', scope === 'weekly');
    $('leaderboardLifetime')?.classList.toggle('active', scope === 'lifetime');

    const { response, result } = await requestJson(`/api/community/leaderboard?scope=${encodeURIComponent(scope)}`);
    if (!response.ok) {
      communityState.leaderboardAll = [];
      const list = $('communityLeaderboardList');
      if (list) {
        list.innerHTML = `<p class="chat-empty">${escapeHtml(result.message || 'Could not load leaderboard.')}</p>`;
      }
      updateLeaderboardSlide();
      return;
    }

    communityState.leaderboardAll = Array.isArray(result.leaders) ? result.leaders : [];
    communityState.leaderboardIndex = 0;
    updateLeaderboardSlide();
  }

  function attachNetworkInteractions(containerId) {
    const container = $(containerId);
    if (!container) {
      return;
    }

    container.querySelectorAll('[data-open-profile]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = button.dataset.openProfile || '';
        if (!username) {
          return;
        }
        showUserProfile(username).catch((error) => console.error('Profile load failed:', error));
      });
    });

    container.querySelectorAll('[data-start-whisper]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = button.dataset.startWhisper || '';
        if (!username) {
          return;
        }
        startWhisper(username);
      });
    });

    container.querySelectorAll('[data-network-accept]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = button.dataset.networkAccept || '';
        if (!username) {
          return;
        }
        handleConnectionAction(username, 'accept').catch((error) => console.error('Accept connection failed:', error));
      });
    });

    container.querySelectorAll('[data-network-decline]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = button.dataset.networkDecline || '';
        if (!username) {
          return;
        }
        handleConnectionAction(username, 'decline').catch((error) => console.error('Decline connection failed:', error));
      });
    });
  }

  function renderMemberCard(member, kind) {
    const username = escapeHtml(member.username || 'member');
    const displayName = escapeHtml(member.displayName || member.username || 'Member');
    const avatarUrl = escapeHtml(member.avatarUrl || '/static/vaultsignals-logo.png');
    const badges = buildBadgeMarkup(member.badges || []);
    const weeklyMetric = member.weeklyProfit == null ? 'Private' : formatMoney(member.weeklyProfit);
    const balanceMetric = member.balance == null ? 'Private' : formatMoney(member.balance);
    const networkState = escapeHtml(member.networkState || kind);

    let actions = `
      <button class="community-inline-action" type="button" data-open-profile="${username}">Profile</button>
    `;
    if (kind === 'connections') {
      actions += `<button class="community-inline-action community-inline-action--gold" type="button" data-start-whisper="${username}">Message</button>`;
    } else if (kind === 'incoming') {
      actions += `
        <button class="community-inline-action community-inline-action--green" type="button" data-network-accept="${username}">Accept</button>
        <button class="community-inline-action community-inline-action--danger" type="button" data-network-decline="${username}">Decline</button>
      `;
    } else {
      actions += `<button class="community-inline-action" type="button" disabled>Pending</button>`;
    }

    return `
      <article class="community-network-card">
        <div class="community-network-card-head">
          <div class="community-network-profile">
            <img class="community-network-avatar" src="${avatarUrl}" alt="${displayName}" />
            <div class="community-network-copy">
              <button class="leader-open-account" type="button" data-open-profile="${username}">${displayName}</button>
              <div class="leader-tags">
                <span class="chat-badge">${escapeHtml(member.tierBadge || 'No Tier')}</span>
                ${member.userRank ? `<span class="chat-rank">${escapeHtml(member.userRank)}</span>` : ''}
              </div>
            </div>
          </div>
          <span class="community-network-state community-network-state--${networkState}">${networkState}</span>
        </div>
        <p class="community-network-bio">${escapeHtml(member.bio || 'No bio shared yet.')}</p>
        <div class="community-network-metrics">
          <div>
            <span>Connections</span>
            <strong>${escapeHtml(String(member.connectionsCount || 0))}</strong>
          </div>
          <div>
            <span>Weekly</span>
            <strong>${escapeHtml(weeklyMetric)}</strong>
          </div>
          <div>
            <span>Balance</span>
            <strong>${escapeHtml(balanceMetric)}</strong>
          </div>
        </div>
        <div class="community-network-badges">${badges || '<span class="community-network-empty">No badges yet.</span>'}</div>
        <div class="community-network-actions">${actions}</div>
      </article>
    `;
  }

  function renderNetworkSection(containerId, members, kind, emptyMessage) {
    const container = $(containerId);
    if (!container) {
      return;
    }
    if (!Array.isArray(members) || !members.length) {
      container.innerHTML = `<p class="chat-empty">${escapeHtml(emptyMessage)}</p>`;
      return;
    }
    container.innerHTML = members.map((member) => renderMemberCard(member, kind)).join('');
    attachNetworkInteractions(containerId);
  }

  async function loadNetwork() {
    const { response, result } = await requestJson('/api/community/network');
    if (!response.ok) {
      setListPlaceholder('communityConnectionsGrid', result.message || 'Could not load your network.');
      setListPlaceholder('communityIncomingRequests', result.message || 'Could not load requests.');
      setListPlaceholder('communityOutgoingRequests', result.message || 'Could not load requests.');
      return;
    }

    communityState.network = result;
    const counts = result.counts || {};
    if ($('communityConnectionsCount')) $('communityConnectionsCount').textContent = String(counts.connections || 0);
    if ($('communityIncomingCount')) $('communityIncomingCount').textContent = String(counts.incoming || 0);
    if ($('communityOutgoingCount')) $('communityOutgoingCount').textContent = String(counts.outgoing || 0);

    renderNetworkSection('communityConnectionsGrid', result.connections || [], 'connections', 'No accepted connections yet. Open member profiles and send requests to build your network.');
    renderNetworkSection('communityIncomingRequests', result.incomingRequests || [], 'incoming', 'No incoming requests right now.');
    renderNetworkSection('communityOutgoingRequests', result.outgoingRequests || [], 'outgoing', 'No pending outgoing requests.');
  }

  function renderProfileStats(snapshot) {
    const profile = snapshot.profile || {};
    const balance = snapshot.balance || {};
    const performance = snapshot.performance || {};
    const cards = [];

    cards.push(`
      <div class="user-profile-stat-card">
        <span>Connections</span>
        <strong>${escapeHtml(String(profile.connectionsCount || 0))}</strong>
      </div>
    `);

    if (snapshot.visibility === 'public' && snapshot.balance) {
      cards.push(`
        <div class="user-profile-stat-card">
          <span>Balance</span>
          <strong>${escapeHtml(formatMoney(balance.current))}</strong>
        </div>
      `);
      cards.push(`
        <div class="user-profile-stat-card">
          <span>Weekly</span>
          <strong>${escapeHtml(formatMoney(performance.weekly?.profit))}</strong>
        </div>
      `);
      cards.push(`
        <div class="user-profile-stat-card">
          <span>Lifetime</span>
          <strong>${escapeHtml(formatMoney(performance.lifetime?.profit))}</strong>
        </div>
      `);
    } else {
      cards.push(`
        <div class="user-profile-stat-card user-profile-stat-card--private">
          <span>Visibility</span>
          <strong>Private</strong>
        </div>
      `);
      cards.push(`
        <div class="user-profile-stat-card user-profile-stat-card--private">
          <span>Stats</span>
          <strong>Hidden</strong>
        </div>
      `);
      cards.push(`
        <div class="user-profile-stat-card user-profile-stat-card--private">
          <span>Leaderboard</span>
          <strong>${profile.privacyMode === 'private' ? 'Off' : 'Public'}</strong>
        </div>
      `);
    }

    return cards.join('');
  }

  function updateModalActions(snapshot) {
    const connectButton = $('addToNetworkBtn');
    const whisperButton = $('userWhisperBtn');
    const modal = $('userProfileModal');
    if (!connectButton || !whisperButton || !modal) {
      return;
    }

    modal.dataset.targetUsername = snapshot.profile?.username || '';
    modal.dataset.networkState = snapshot.networkState || 'none';
    connectButton.disabled = false;

    switch (snapshot.networkState) {
      case 'self':
        connectButton.innerHTML = '<span>•</span> Your Profile';
        connectButton.disabled = true;
        break;
      case 'connected':
        connectButton.innerHTML = '<span>✓</span> Connected';
        connectButton.disabled = true;
        break;
      case 'incoming':
        connectButton.innerHTML = '<span>+</span> Accept Request';
        break;
      case 'outgoing':
        connectButton.innerHTML = '<span>…</span> Request Sent';
        connectButton.disabled = true;
        break;
      default:
        connectButton.innerHTML = '<span>+</span> Send Request';
        break;
    }

    whisperButton.disabled = !snapshot.canWhisper;
    whisperButton.innerHTML = snapshot.canWhisper ? '<span>Msg</span> Private Chat' : '<span>Msg</span> Connect to Message';
  }

  async function showUserProfile(username) {
    const modal = $('userProfileModal');
    if (!modal || !username) {
      return;
    }

    const { response, result } = await requestJson(`/api/community/account/${encodeURIComponent(username)}`);
    if (!response.ok || !result.ok) {
      console.error('Could not load user profile:', result.message || 'Unknown error');
      return;
    }

    communityState.modalSnapshot = result;
    const profile = result.profile || {};

    if ($('userProfileName')) $('userProfileName').textContent = profile.displayName || username;
    if ($('userProfileHandle')) $('userProfileHandle').textContent = `@${profile.username || username}`;
    if ($('userProfileRank')) $('userProfileRank').textContent = `Rank: ${profile.userRank || '-'}`;
    if ($('userProfileTier')) $('userProfileTier').textContent = `Tier: ${profile.tierBadge || 'No Tier'}`;
    if ($('userProfileAvatar')) $('userProfileAvatar').src = profile.avatarUrl || '/static/vaultsignals-logo.png';
    if ($('userProfileBio')) $('userProfileBio').textContent = profile.bio || (result.visibility === 'private' ? 'This member keeps their detailed profile private.' : 'No bio set.');
    if ($('userProfileStats')) $('userProfileStats').innerHTML = renderProfileStats(result);
    if ($('userProfileBadges')) $('userProfileBadges').innerHTML = buildBadgeMarkup(result.badges || [], 'No badges yet.');
    if ($('userProfileMessage')) {
      $('userProfileMessage').textContent = result.visibility === 'private'
        ? 'Financial stats are hidden by this member\'s privacy mode.'
        : `Updated ${result.balance?.updatedAt ? formatDateTime(result.balance.updatedAt) : 'recently'}.`;
      $('userProfileMessage').style.color = 'rgba(255,255,255,0.76)';
    }

    updateModalActions(result);
    modal.classList.remove('hidden');
    modal.classList.add('active');
  }

  function hideUserProfile() {
    const modal = $('userProfileModal');
    if (!modal) {
      return;
    }
    modal.classList.remove('active');
    window.setTimeout(() => {
      modal.classList.add('hidden');
    }, 250);
  }

  async function refreshHubData() {
    await Promise.all([loadSummary(), loadInbox(), loadNetwork()]);
    if (communityState.activeView === 'leaderboard') {
      await loadLeaderboard(communityState.leaderboardScope);
    }
    if (communityState.activeView === 'global') {
      await loadGlobalMessages();
    }
    if (communityState.activeView === 'whisper') {
      await loadWhisperMessages();
    }
  }

  async function handleConnectionAction(username, action) {
    const endpoint = action === 'accept' || action === 'decline'
      ? '/api/community/network/respond'
      : '/api/community/network/add';
    const payload = action === 'send'
      ? { targetUsername: username }
      : { targetUsername: username, action };

    const { response, result } = await requestJson(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const messageNode = $('userProfileMessage');
    if (messageNode && $('userProfileModal')?.classList.contains('active')) {
      messageNode.textContent = result.message || 'Action completed.';
      messageNode.style.color = response.ok ? '#84f5a9' : '#ffb5b5';
    }

    if (!response.ok) {
      return;
    }

    await refreshHubData();
    if ($('userProfileModal')?.classList.contains('active') && username) {
      await showUserProfile(username);
    }
  }

  async function saveSettings(event) {
    event.preventDefault();
    const account = communityState.summary?.account || {};
    const payload = {
      bio: ($('communityBioInput')?.value || '').trim(),
      avatarUrl: ($('communityAvatarInput')?.value || '').trim() || account.avatarUrl || '',
      privacyMode: $('communityPrivacyMode')?.value || 'public',
      showOnLeaderboard: Boolean($('communityLeaderboardToggle')?.checked),
      ignoreWhisper: Boolean($('communityIgnoreWhisper')?.checked),
      layoutPreset: account.layoutPreset || 'default',
      emailAlerts: account.emailAlerts !== false,
      marketAlerts: account.marketAlerts !== false,
      renewalReminders: account.renewalReminders !== false,
      preferredBillingMethod: account.preferredBillingMethod || 'paypal',
    };

    const { response, result } = await requestJson('/api/community/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      setSettingsMessage(result.message || 'Could not save community controls.', false);
      return;
    }

    setSettingsMessage(result.message || 'Community controls saved.', true);
    await loadSummary();
  }

  function wireAvatarEdit() {
    const avatarButton = $('avatarEditBtn');
    const avatarInput = $('communityAvatarInput');
    const avatarImage = $('communityAvatar');
    avatarButton?.addEventListener('click', () => {
      const nextUrl = window.prompt('Enter a new avatar URL:', avatarImage?.src || '');
      if (!nextUrl || !nextUrl.trim() || !avatarInput) {
        return;
      }
      avatarInput.value = nextUrl.trim();
      $('communitySettingsForm')?.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    });
  }

  async function sendGlobalMessage(event) {
    event.preventDefault();
    const input = $('communityGlobalInput');
    const text = (input?.value || '').trim();
    if (!text) {
      return;
    }

    const { response, result } = await requestJson('/api/community/chat/global', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) {
      setSettingsMessage(result.message || 'Could not send message.', false);
      return;
    }

    if (input) {
      input.value = '';
    }
    await loadGlobalMessages();
  }

  async function sendWhisperMessage(event) {
    event.preventDefault();
    const input = $('communityWhisperInput');
    const text = (input?.value || '').trim();
    const target = (communityState.whisperTarget || $('communityWhisperTarget')?.value || '').trim();
    if (!text || !target) {
      return;
    }

    const { response, result } = await requestJson(`/api/community/chat/whisper/${encodeURIComponent(target)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) {
      setSettingsMessage(result.message || 'Could not send whisper.', false);
      return;
    }

    if (input) {
      input.value = '';
    }
    await Promise.all([loadInbox(), loadWhisperMessages()]);
  }

  function wireTabEvents() {
    $('chatTabGlobal')?.addEventListener('click', () => {
      setActiveView('global');
      loadGlobalMessages().catch((error) => console.error('Global chat load failed:', error));
    });
    $('chatTabWhisper')?.addEventListener('click', () => {
      setActiveView('whisper');
      Promise.all([loadInbox(), loadWhisperMessages()]).catch((error) => console.error('Whisper inbox load failed:', error));
    });
    $('chatTabLeaderboard')?.addEventListener('click', () => {
      setActiveView('leaderboard');
      loadLeaderboard(communityState.leaderboardScope).catch((error) => console.error('Leaderboard load failed:', error));
    });
    $('chatTabNetwork')?.addEventListener('click', () => {
      setActiveView('network');
      loadNetwork().catch((error) => console.error('Network load failed:', error));
    });

    $('leaderboardWeekly')?.addEventListener('click', () => {
      loadLeaderboard('weekly').catch((error) => console.error('Weekly leaderboard failed:', error));
    });
    $('leaderboardLifetime')?.addEventListener('click', () => {
      loadLeaderboard('lifetime').catch((error) => console.error('Lifetime leaderboard failed:', error));
    });
    $('leaderboardPrev')?.addEventListener('click', () => {
      communityState.leaderboardIndex = Math.max(0, communityState.leaderboardIndex - 1);
      updateLeaderboardSlide();
    });
    $('leaderboardNext')?.addEventListener('click', () => {
      communityState.leaderboardIndex += 1;
      updateLeaderboardSlide();
    });

    $('communityWhisperTarget')?.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') {
        return;
      }
      event.preventDefault();
      communityState.whisperTarget = (event.currentTarget.value || '').trim();
      loadWhisperMessages().catch((error) => console.error('Whisper lookup failed:', error));
    });

    $('communityWhisperTarget')?.addEventListener('blur', (event) => {
      communityState.whisperTarget = (event.currentTarget.value || '').trim();
      updateWhisperMeta();
    });
  }

  function wireModalEvents() {
    const modal = $('userProfileModal');
    modal?.querySelector('.modal-close-btn')?.addEventListener('click', hideUserProfile);
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && modal?.classList.contains('active')) {
        hideUserProfile();
      }
    });
    modal?.addEventListener('click', (event) => {
      if (event.target === modal) {
        hideUserProfile();
      }
    });

    $('addToNetworkBtn')?.addEventListener('click', () => {
      const targetUsername = modal?.dataset.targetUsername || '';
      const networkState = modal?.dataset.networkState || 'none';
      if (!targetUsername || networkState === 'self' || networkState === 'connected' || networkState === 'outgoing') {
        return;
      }
      const action = networkState === 'incoming' ? 'accept' : 'send';
      handleConnectionAction(targetUsername, action).catch((error) => console.error('Network action failed:', error));
    });

    $('userCheckAccountBtn')?.addEventListener('click', () => {
      const targetUsername = modal?.dataset.targetUsername || '';
      if (!targetUsername) {
        return;
      }
      window.open(`/community/account/${encodeURIComponent(targetUsername)}`, '_blank', 'noopener,noreferrer');
    });

    $('userWhisperBtn')?.addEventListener('click', () => {
      const targetUsername = modal?.dataset.targetUsername || '';
      if (!targetUsername || $('userWhisperBtn')?.disabled) {
        return;
      }
      hideUserProfile();
      startWhisper(targetUsername);
    });
  }

  async function refreshCurrentView() {
    if (communityState.activeView === 'leaderboard') {
      await loadLeaderboard(communityState.leaderboardScope);
      return;
    }
    if (communityState.activeView === 'network') {
      await loadNetwork();
      return;
    }
    if (communityState.activeView === 'whisper') {
      await Promise.all([loadInbox(), loadWhisperMessages()]);
      return;
    }
    await loadGlobalMessages();
  }

  async function initCommunityHub() {
    if (!$('community-hub-section')) {
      return;
    }

    $('communitySettingsForm')?.addEventListener('submit', saveSettings);
    $('communityGlobalForm')?.addEventListener('submit', sendGlobalMessage);
    $('communityWhisperForm')?.addEventListener('submit', sendWhisperMessage);
    wireAvatarEdit();
    wireTabEvents();
    wireModalEvents();

    try {
      await Promise.all([loadSummary(), loadGlobalMessages(), loadLeaderboard('weekly'), loadInbox(), loadNetwork()]);
      if (communityState.whisperTarget) {
        await loadWhisperMessages();
      } else {
        setListPlaceholder('communityWhisperList', 'Enter a username or choose a connection to open a private thread.');
      }
      setActiveView('global');
    } catch (error) {
      console.error('Community hub bootstrap failed:', error);
      setSettingsMessage('Failed to load community hub. Please refresh.', false);
    }

    window.setInterval(() => {
      refreshCurrentView().catch((error) => console.error('Community refresh failed:', error));
    }, chatPollMs);
  }

  document.addEventListener('DOMContentLoaded', initCommunityHub);
})();
