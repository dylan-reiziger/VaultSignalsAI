(function () {
  const currencyCode = document.body?.dataset.defaultCurrencyCode || 'GBP';
  const currencySymbol = document.body?.dataset.currencySymbol || '£';
  const chatPollMs = Math.max(3000, Number(document.body?.dataset.communityChatPollMs || '8000'));

  const chatState = {
    activeView: 'global',
    mode: 'global',
    whisperTarget: '',
    leaderboardScope: 'weekly',
    leaderboardIndex: 0,
    leaderboardAll: [],
    globalMeta: 'Tier required to send messages.',
  };

  const LEADERBOARD_PAGE_SIZE = 5;

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
    if (!node) return;
    node.textContent = message;
    node.style.borderColor = ok ? 'rgba(76,239,120,0.45)' : 'rgba(255,255,255,0.12)';
    node.style.color = ok ? '#84f5a9' : 'rgba(255,255,255,0.78)';
  }

  function setChatPlaceholder(message) {
    const list = $('communityChatList');
    if (!list) return;
    list.innerHTML = `<p class="chat-empty">${escapeHtml(message)}</p>`;
  }

  function updateChatMeta() {
    const chatMeta = $('communityChatMeta');
    const input = $('communityChatInput');
    const targetInput = $('communityWhisperTarget');
    if (!chatMeta || !input) return;

    if (chatState.activeView === 'whisper') {
      const target = (targetInput?.value || chatState.whisperTarget || '').trim();
      chatMeta.textContent = target
        ? `Private whisper thread with ${target}.`
        : 'Enter a username to open a whisper thread.';
      input.placeholder = target ? `Message ${target}...` : 'Choose a whisper username first...';
      return;
    }

    chatMeta.textContent = chatState.globalMeta;
    input.placeholder = 'Type your message...';
  }

  function setActiveView(view) {
    chatState.activeView = view;
    if (view !== 'leaderboard') {
      chatState.mode = view;
    }

    $('chatTabGlobal')?.classList.toggle('active', view === 'global');
    $('chatTabWhisper')?.classList.toggle('active', view === 'whisper');
    $('chatTabLeaderboard')?.classList.toggle('active', view === 'leaderboard');
    $('chatContent')?.classList.toggle('active', view !== 'leaderboard');
    $('leaderboardContent')?.classList.toggle('active', view === 'leaderboard');
    $('communityWhisperTarget')?.classList.toggle('hidden', view !== 'whisper');
    updateChatMeta();
  }

  function updateLeaderboardSlide() {
    const list = $('communityLeaderboardList');
    if (!list) return;

    const all = Array.isArray(chatState.leaderboardAll) ? chatState.leaderboardAll : [];
    const totalPages = all.length ? Math.ceil(all.length / LEADERBOARD_PAGE_SIZE) : 0;

    if (!all.length) {
      list.innerHTML = '<p class="chat-empty">No public leaderboard entries yet.</p>';
      if ($('leaderboardSlideInfo')) $('leaderboardSlideInfo').textContent = 'Page 0 / 0';
      if ($('leaderboardPrev')) $('leaderboardPrev').disabled = true;
      if ($('leaderboardNext')) $('leaderboardNext').disabled = true;
      return;
    }

    const page = Math.max(0, Math.min(chatState.leaderboardIndex, totalPages - 1));
    chatState.leaderboardIndex = page;
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
                <button class="leader-open-account" data-open-account="${username}" type="button">${displayName}</button>
                <div class="leader-tags">
                  <span class="chat-badge">${tierBadge}</span>
                  ${userRank ? `<span class="chat-rank">${userRank}</span>` : ''}
                </div>
              </div>
            </div>
          </div>
          <span class="leader-score" title="Balance: ${balance}">${score}</span>
        </div>
      `;
    }).join('');

    list.querySelectorAll('[data-open-account]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = button.dataset.openAccount || '';
        if (!username) return;
        window.open(`/community/account/${encodeURIComponent(username)}`, '_blank', 'noopener,noreferrer');
      });
    });

    if ($('leaderboardSlideInfo')) $('leaderboardSlideInfo').textContent = `Page ${page + 1} / ${totalPages}`;
    if ($('leaderboardPrev')) $('leaderboardPrev').disabled = page <= 0;
    if ($('leaderboardNext')) $('leaderboardNext').disabled = page >= totalPages - 1;
  }

  async function loadSummary() {
    const { response, result } = await requestJson('/api/community/summary');
    if (!response.ok) {
      setSettingsMessage(result.message || 'Could not load community summary.', false);
      return;
    }

    const account = result.account || {};
    const lifetime = result.summary?.lifetime || {};
    const daily = result.summary?.daily || {};
    const weekly = result.summary?.weekly || {};

    if ($('communityDisplayName')) $('communityDisplayName').textContent = account.displayName || account.username || 'Member';
    if ($('communityTierBadge')) $('communityTierBadge').textContent = account.tierBadge || 'No Tier';
    if ($('communityRankBadge')) $('communityRankBadge').textContent = `Rank: ${account.userRank || '-'}`;
    if ($('communityAvatar')) $('communityAvatar').src = account.avatarUrl || '/static/vaultsignals-logo.png';
    if ($('communityBalance')) $('communityBalance').textContent = formatMoney(result.balance?.current);
    if ($('communityInvested')) $('communityInvested').textContent = formatMoney(lifetime.invested);
    if ($('communityProfit')) $('communityProfit').textContent = formatMoney(lifetime.profit);
    if ($('communityDisplayNameInput')) $('communityDisplayNameInput').value = account.displayName || '';
    if ($('communityPrivacyMode')) $('communityPrivacyMode').value = account.privacyMode || 'public';
    if ($('communityLeaderboardToggle')) $('communityLeaderboardToggle').checked = Boolean(account.showOnLeaderboard);
    if ($('communityIgnoreWhisper')) $('communityIgnoreWhisper').checked = Boolean(account.ignoreWhisper);

    chatState.globalMeta = `Tier badge: ${account.tierBadge || 'No Tier'}. Rank: ${account.userRank || '-'}. Daily profit: ${formatMoney(daily.profit)}, Weekly: ${formatMoney(weekly.profit)}.`;
    updateChatMeta();
  }

  async function loadLeaderboard(scope = chatState.leaderboardScope) {
    chatState.leaderboardScope = scope;
    $('leaderboardWeekly')?.classList.toggle('active', scope === 'weekly');
    $('leaderboardLifetime')?.classList.toggle('active', scope === 'lifetime');

    const { response, result } = await requestJson(`/api/community/leaderboard?scope=${encodeURIComponent(scope)}`);
    if (!response.ok) {
      chatState.leaderboardAll = [];
      const list = $('communityLeaderboardList');
      if (list) {
        list.innerHTML = `<p class="chat-empty">${escapeHtml(result.message || 'Could not load leaderboard.')}</p>`;
      }
      updateLeaderboardSlide();
      return;
    }

    chatState.leaderboardAll = Array.isArray(result.leaders) ? result.leaders : [];
    chatState.leaderboardIndex = 0;
    updateLeaderboardSlide();
  }

  function renderChatMessages(messages) {
    const list = $('communityChatList');
    if (!list) return;

    if (!Array.isArray(messages) || !messages.length) {
      setChatPlaceholder(chatState.activeView === 'whisper' ? 'No whisper messages yet.' : 'No messages yet.');
      return;
    }

    list.innerHTML = messages.map((message) => {
      const displayName = escapeHtml(message.displayName || message.username || 'Member');
      const username = escapeHtml(message.username || '');
      const text = escapeHtml(message.text || '');
      const tierBadge = message.tierBadge ? `<span class="chat-badge">${escapeHtml(message.tierBadge)}</span>` : '';
      const userRank = message.userRank ? `<span class="chat-rank">${escapeHtml(message.userRank)}</span>` : '';

      return `
        <article class="chat-message${message.isMine ? ' mine' : ''}">
          <div class="chat-line-top">
            ${tierBadge}
            <button class="chat-name" type="button" data-open-profile="${username}">${displayName}</button>
            ${userRank}
            <button class="chat-whisper-btn" type="button" data-whisper="${username}">Whisper</button>
          </div>
          <p>${text}</p>
        </article>
      `;
    }).join('');

    list.querySelectorAll('[data-open-profile]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = button.dataset.openProfile || '';
        if (!username) return;
        showUserProfile(username).catch((error) => console.error('Profile load failed:', error));
      });
    });

    list.querySelectorAll('[data-whisper]').forEach((button) => {
      button.addEventListener('click', () => {
        const username = button.dataset.whisper || '';
        if (!username) return;
        chatState.whisperTarget = username;
        if ($('communityWhisperTarget')) $('communityWhisperTarget').value = username;
        setActiveView('whisper');
        loadWhisperMessages().catch((error) => console.error('Whisper load failed:', error));
      });
    });

    list.scrollTop = list.scrollHeight;
  }

  async function loadGlobalMessages() {
    const { response, result } = await requestJson('/api/community/chat/global');
    if (!response.ok) {
      setChatPlaceholder(result.message || 'Could not load global chat.');
      return;
    }

    renderChatMessages(result.messages || []);
  }

  async function loadWhisperMessages() {
    const targetInput = $('communityWhisperTarget');
    const target = (targetInput?.value || chatState.whisperTarget || '').trim();
    if (!target) {
      chatState.whisperTarget = '';
      updateChatMeta();
      setChatPlaceholder('Enter a username to load whisper messages.');
      return;
    }

    chatState.whisperTarget = target;
    if (targetInput) targetInput.value = target;
    updateChatMeta();

    const { response, result } = await requestJson(`/api/community/chat/whisper/${encodeURIComponent(target)}`);
    if (!response.ok) {
      setChatPlaceholder(result.message || 'Could not load whisper messages.');
      return;
    }

    renderChatMessages(result.messages || []);
  }

  async function refreshCurrentView() {
    if (chatState.activeView === 'leaderboard') {
      await loadLeaderboard(chatState.leaderboardScope);
      return;
    }

    if (chatState.mode === 'whisper') {
      await loadWhisperMessages();
      return;
    }

    await loadGlobalMessages();
  }

  async function sendCurrentMessage(event) {
    event.preventDefault();
    const input = $('communityChatInput');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;

    let endpoint = '/api/community/chat/global';
    if (chatState.mode === 'whisper') {
      const targetInput = $('communityWhisperTarget');
      const target = (targetInput?.value || chatState.whisperTarget || '').trim();
      if (!target) {
        setSettingsMessage('Choose a whisper target username first.', false);
        targetInput?.focus();
        return;
      }
      chatState.whisperTarget = target;
      endpoint = `/api/community/chat/whisper/${encodeURIComponent(target)}`;
    }

    const { response, result } = await requestJson(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) {
      setSettingsMessage(result.message || 'Could not send message.', false);
      return;
    }

    input.value = '';
    setSettingsMessage(result.message || 'Message sent.', true);
    await refreshCurrentView();
  }

  async function showUserProfile(username) {
    const modal = $('userProfileModal');
    if (!modal || !username) return;

    const { response, result } = await requestJson(`/api/community/account/${encodeURIComponent(username)}`);
    if (!response.ok) {
      console.error('Could not load user profile:', result.message || 'Unknown error');
      return;
    }

    const profile = result.profile || {};
    const badges = Array.isArray(result.badges) ? result.badges : [];
    const tierBadge = badges.find((badge) => String(badge || '').toLowerCase().startsWith('tier')) || 'No Tier';
    const message = $('userProfileMessage');

    if ($('userProfileName')) $('userProfileName').textContent = profile.displayName || username;
    if ($('userProfileRank')) $('userProfileRank').textContent = `Rank: ${profile.userRank || '-'}`;
    if ($('userProfileTier')) $('userProfileTier').textContent = `Tier: ${tierBadge}`;
    if ($('userProfileAvatar')) $('userProfileAvatar').src = profile.avatarUrl || '/static/vaultsignals-logo.png';
    if (message) {
      message.textContent = '';
      message.style.color = 'rgba(255,255,255,0.76)';
    }

    modal.dataset.targetUsername = username;
    modal.classList.remove('hidden');
    modal.classList.add('active');
  }

  function hideUserProfile() {
    const modal = $('userProfileModal');
    const message = $('userProfileMessage');
    if (!modal) return;

    modal.classList.remove('active');
    if (message) {
      message.textContent = '';
      message.style.color = 'rgba(255,255,255,0.76)';
    }

    window.setTimeout(() => {
      modal.classList.add('hidden');
    }, 250);
  }

  function wireAvatarEdit() {
    const avatarBtn = $('avatarEditBtn');
    const avatarInput = $('communityAvatarInput');
    const avatarImg = $('communityAvatar');

    avatarBtn?.addEventListener('click', () => {
      const nextUrl = window.prompt('Enter new avatar URL:', avatarImg?.src || '');
      if (!nextUrl || !nextUrl.trim() || !avatarInput) {
        return;
      }
      avatarInput.value = nextUrl.trim();
      $('communitySettingsForm')?.dispatchEvent(new Event('submit', { cancelable: true }));
    });
  }

  async function saveSettings(event) {
    event.preventDefault();

    const payload = {
      displayName: ($('communityDisplayNameInput')?.value || '').trim(),
      avatarUrl: ($('communityAvatarInput')?.value || '').trim(),
      privacyMode: $('communityPrivacyMode')?.value || 'public',
      showOnLeaderboard: Boolean($('communityLeaderboardToggle')?.checked),
      ignoreWhisper: Boolean($('communityIgnoreWhisper')?.checked),
      layoutPreset: 'default',
    };

    const { response, result } = await requestJson('/api/community/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      setSettingsMessage(result.message || 'Could not save settings.', false);
      return;
    }

    setSettingsMessage(result.message || 'Settings saved.', true);
    await loadSummary();
    await loadLeaderboard(chatState.leaderboardScope);
  }

  function wireChatTabs() {
    $('chatTabGlobal')?.addEventListener('click', () => {
      setActiveView('global');
      loadGlobalMessages().catch((error) => console.error('Global chat load failed:', error));
    });

    $('chatTabWhisper')?.addEventListener('click', () => {
      setActiveView('whisper');
      loadWhisperMessages().catch((error) => console.error('Whisper load failed:', error));
    });

    $('chatTabLeaderboard')?.addEventListener('click', () => {
      setActiveView('leaderboard');
      loadLeaderboard(chatState.leaderboardScope).catch((error) => console.error('Leaderboard load failed:', error));
    });

    $('leaderboardWeekly')?.addEventListener('click', () => {
      loadLeaderboard('weekly').catch((error) => console.error('Weekly leaderboard load failed:', error));
    });

    $('leaderboardLifetime')?.addEventListener('click', () => {
      loadLeaderboard('lifetime').catch((error) => console.error('Lifetime leaderboard load failed:', error));
    });

    $('leaderboardPrev')?.addEventListener('click', () => {
      chatState.leaderboardIndex = Math.max(0, chatState.leaderboardIndex - 1);
      updateLeaderboardSlide();
    });

    $('leaderboardNext')?.addEventListener('click', () => {
      chatState.leaderboardIndex += 1;
      updateLeaderboardSlide();
    });

    $('communityWhisperTarget')?.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      chatState.whisperTarget = (event.currentTarget.value || '').trim();
      loadWhisperMessages().catch((error) => console.error('Whisper target load failed:', error));
    });

    $('communityWhisperTarget')?.addEventListener('blur', (event) => {
      chatState.whisperTarget = (event.currentTarget.value || '').trim();
      updateChatMeta();
    });
  }

  async function initCommunityHub() {
    if (!$('communityChatList')) return;

    if ($('communitySettingsForm')) {
      $('communitySettingsForm').addEventListener('submit', saveSettings);
      wireAvatarEdit();
    }

    $('communityChatForm')?.addEventListener('submit', sendCurrentMessage);
    wireChatTabs();

    const modal = $('userProfileModal');
    document.querySelector('.modal-close-btn')?.addEventListener('click', hideUserProfile);
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && modal?.classList.contains('active')) {
        hideUserProfile();
      }
    });

    $('addToNetworkBtn')?.addEventListener('click', async () => {
      const username = modal?.dataset.targetUsername || '';
      if (!username) return;

      const { response, result } = await requestJson('/api/community/network/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ targetUsername: username }),
      });
      const message = $('userProfileMessage');
      if (!message) return;
      message.textContent = result.message || 'Action completed.';
      message.style.color = response.ok ? '#84f5a9' : '#ffb5b5';
    });

    $('userCheckAccountBtn')?.addEventListener('click', () => {
      const username = modal?.dataset.targetUsername || '';
      if (!username) return;
      window.open(`/community/account/${encodeURIComponent(username)}`, '_blank', 'noopener,noreferrer');
    });

    $('userWhisperBtn')?.addEventListener('click', () => {
      const username = modal?.dataset.targetUsername || '';
      if (!username) return;
      chatState.whisperTarget = username;
      if ($('communityWhisperTarget')) $('communityWhisperTarget').value = username;
      hideUserProfile();
      setActiveView('whisper');
      loadWhisperMessages().catch((error) => console.error('Modal whisper load failed:', error));
    });

    modal?.addEventListener('click', (event) => {
      if (event.target === modal) {
        hideUserProfile();
      }
    });

    try {
      if ($('communitySettingsForm')) {
        await loadSummary();
      }
      if ($('communityLeaderboardList')) {
        await loadLeaderboard('weekly');
      }
      setActiveView('global');
      await loadGlobalMessages();
    } catch (error) {
      console.error('Community hub bootstrap failed:', error);
    }

    window.setInterval(() => {
      refreshCurrentView().catch((error) => console.error('Community refresh failed:', error));
    }, chatPollMs);
  }

  document.addEventListener('DOMContentLoaded', initCommunityHub);
})();
