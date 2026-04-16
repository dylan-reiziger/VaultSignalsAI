(function () {
  if (window.VaultBadgeUI) {
    return;
  }

  let lastTrigger = null;

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function sanitizeTone(value) {
    const cleaned = String(value || 'gold').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-');
    return cleaned || 'gold';
  }

  function toTitleCase(value) {
    return String(value || '')
      .replace(/[_-]+/g, ' ')
      .split(/\s+/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
      .join(' ');
  }

  function formatBadgeGroup(value) {
    const normalized = String(value || 'badge').trim().toLowerCase();
    const labels = {
      founder: 'Founder',
      trust: 'Trust',
      loyalty: 'Loyalty',
      membership: 'Membership',
      milestone: 'Milestone',
      support: 'Support',
      preview: 'Preview',
      custom: 'Custom',
      badge: 'Badge',
    };
    return labels[normalized] || toTitleCase(normalized || 'badge');
  }

  function renderShieldBadge(badge, options = {}) {
    const tone = sanitizeTone(badge?.tone || 'gold');
    const label = escapeHtml(badge?.label || badge?.name || 'Badge');
    const shortLabel = escapeHtml(badge?.shortLabel || badge?.icon || badge?.label || badge?.name || 'Badge');
    const achievement = escapeHtml(badge?.achievement || badge?.description || 'Unlocked on this account.');
    const group = escapeHtml(formatBadgeGroup(badge?.group || badge?.badgeGroup || 'badge'));
    const variant = options.variant === 'grid' ? 'grid' : 'compact';
    const interactive = options.interactive !== false;
    const tagName = interactive ? 'button' : 'span';
    const metaLabel = escapeHtml(options.metaLabel || group);

    const attrs = interactive
      ? `type="button" data-badge-button data-badge-label="${label}" data-badge-short="${shortLabel}" data-badge-tone="${escapeHtml(toTitleCase(tone))}" data-badge-group="${group}" data-badge-achievement="${achievement}" aria-label="View badge details for ${label}"`
      : '';

    return `
      <${tagName} class="badge-shield badge-shield--${tone} badge-shield--${variant}${interactive ? ' is-interactive' : ' is-static'}" ${attrs}>
        <span class="badge-shield-emblem">
          <span class="badge-shield-mark">${shortLabel}</span>
        </span>
        <span class="badge-shield-copy">
          <span class="badge-shield-label">${label}</span>
          <span class="badge-shield-meta">${metaLabel}</span>
        </span>
      </${tagName}>
    `;
  }

  function ensureBadgeModal() {
    if (!document.body || document.getElementById('badgeDetailModal')) {
      return;
    }

    const wrapper = document.createElement('div');
    wrapper.id = 'badgeDetailModal';
    wrapper.className = 'badge-detail-modal';
    wrapper.hidden = true;
    wrapper.innerHTML = `
      <div class="badge-detail-backdrop" data-badge-close></div>
      <div class="badge-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="badgeDetailTitle">
        <button class="badge-detail-close" type="button" data-badge-close aria-label="Close badge details">✕</button>
        <div class="badge-detail-head">
          <div id="badgeDetailShield" class="badge-detail-shield"></div>
          <div class="badge-detail-copy">
            <p class="eyebrow">Badge Details</p>
            <h3 id="badgeDetailTitle">Badge</h3>
            <p id="badgeDetailTone" class="badge-detail-tone">Badge</p>
          </div>
        </div>
        <div class="badge-detail-section">
          <span class="badge-detail-label">How you got it</span>
          <p id="badgeDetailAchievement" class="badge-detail-text">Unlocked on your account.</p>
        </div>
        <div class="badge-detail-section badge-detail-section--split">
          <div>
            <span class="badge-detail-label">Badge family</span>
            <p id="badgeDetailGroup" class="badge-detail-text">Badge</p>
          </div>
          <div>
            <span class="badge-detail-label">Style</span>
            <p id="badgeDetailShort" class="badge-detail-text">Core</p>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(wrapper);
  }

  function openBadgeModal(detail) {
    ensureBadgeModal();
    const modal = document.getElementById('badgeDetailModal');
    if (!modal) {
      return;
    }

    const label = detail.label || 'Badge';
    const shortLabel = detail.shortLabel || 'Badge';
    const tone = detail.tone || 'Gold';
    const group = detail.group || 'Badge';
    const achievement = detail.achievement || 'Unlocked on your account.';

    const shield = document.getElementById('badgeDetailShield');
    if (shield) {
      shield.innerHTML = renderShieldBadge(
        {
          label,
          shortLabel,
          tone: sanitizeTone(tone),
          group,
          achievement,
        },
        { interactive: false, variant: 'grid', metaLabel: group }
      );
    }

    const title = document.getElementById('badgeDetailTitle');
    const toneNode = document.getElementById('badgeDetailTone');
    const achievementNode = document.getElementById('badgeDetailAchievement');
    const groupNode = document.getElementById('badgeDetailGroup');
    const shortNode = document.getElementById('badgeDetailShort');
    if (title) title.textContent = label;
    if (toneNode) toneNode.textContent = `${tone} shield badge`;
    if (achievementNode) achievementNode.textContent = achievement;
    if (groupNode) groupNode.textContent = group;
    if (shortNode) shortNode.textContent = shortLabel;

    lastTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    modal.hidden = false;
    modal.classList.add('active');
    document.body.classList.add('badge-modal-open');
    modal.querySelector('.badge-detail-close')?.focus();
  }

  function closeBadgeModal() {
    const modal = document.getElementById('badgeDetailModal');
    if (!modal || modal.hidden) {
      return;
    }
    modal.classList.remove('active');
    modal.hidden = true;
    document.body.classList.remove('badge-modal-open');
    if (lastTrigger && typeof lastTrigger.focus === 'function') {
      lastTrigger.focus();
    }
  }

  function bindBadgeEvents() {
    document.addEventListener('click', (event) => {
      const trigger = event.target.closest('[data-badge-button]');
      if (trigger) {
        event.preventDefault();
        openBadgeModal({
          label: trigger.dataset.badgeLabel,
          shortLabel: trigger.dataset.badgeShort,
          tone: trigger.dataset.badgeTone,
          group: trigger.dataset.badgeGroup,
          achievement: trigger.dataset.badgeAchievement,
        });
        return;
      }

      if (event.target.closest('[data-badge-close]')) {
        event.preventDefault();
        closeBadgeModal();
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closeBadgeModal();
      }
    });
  }

  function init() {
    ensureBadgeModal();
    bindBadgeEvents();
  }

  window.VaultBadgeUI = {
    escapeHtml,
    renderShieldBadge,
    openBadgeModal,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();