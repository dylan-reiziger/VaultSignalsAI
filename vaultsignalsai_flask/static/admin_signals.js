let adminSignalsCache = [];

function setAdminMessage(message, ok = false) {
  const node = document.getElementById('adminSignalMessage');
  if (!node) return;
  node.textContent = message;
  node.style.borderColor = ok ? 'rgba(76,239,120,0.5)' : 'rgba(255,255,255,0.1)';
  node.style.color = ok ? '#84f5a9' : 'rgba(255,255,255,0.78)';
}

function getAdminSignalPayload() {
  return {
    signalDay: document.getElementById('adminSignalDay')?.value,
    tierNumber: Number(document.getElementById('adminTier')?.value || 0),
    assetSymbol: document.getElementById('adminAsset')?.value.trim(),
    market: document.getElementById('adminMarket')?.value.trim(),
    direction: document.getElementById('adminDirection')?.value,
    status: document.getElementById('adminStatus')?.value,
    entryPrice: Number(document.getElementById('adminEntry')?.value || 0),
    targetPrice: Number(document.getElementById('adminTarget')?.value || 0),
    stopPrice: Number(document.getElementById('adminStop')?.value || 0),
    confidenceLabel: document.getElementById('adminConfidence')?.value.trim(),
    sessionLabel: document.getElementById('adminSession')?.value.trim(),
    signalTimeUtc: document.getElementById('adminSignalTime')?.value || '',
    timerMinutes: Number(document.getElementById('adminTimerMinutes')?.value || 90),
    thesis: document.getElementById('adminThesis')?.value.trim(),
  };
}

function setEditingMode(signalId = null) {
  const editingIdNode = document.getElementById('adminEditingSignalId');
  const submitBtn = document.getElementById('adminSubmitBtn');
  const cancelBtn = document.getElementById('adminCancelEditBtn');
  if (!editingIdNode || !submitBtn || !cancelBtn) return;

  editingIdNode.value = signalId ? String(signalId) : '';
  const isEditing = Boolean(signalId);
  submitBtn.textContent = isEditing ? 'Update Signal' : 'Create Signal';
  cancelBtn.hidden = !isEditing;
}

function resetAdminFormForCreate() {
  const formNode = document.getElementById('adminSignalForm');
  const dayValue = document.getElementById('adminSignalDay')?.value;
  formNode?.reset();
  if (dayValue) {
    const dayNode = document.getElementById('adminSignalDay');
    if (dayNode) dayNode.value = dayValue;
  }
  const timerNode = document.getElementById('adminTimerMinutes');
  if (timerNode) timerNode.value = '90';
  setEditingMode(null);
}

function beginEditSignal(signalId) {
  const signal = adminSignalsCache.find((item) => String(item.id) === String(signalId));
  if (!signal) {
    setAdminMessage('Signal not found for editing.');
    return;
  }

  document.getElementById('adminSignalDay').value = signal.signalDay;
  document.getElementById('adminTier').value = String(signal.tierNumber);
  document.getElementById('adminAsset').value = signal.assetSymbol;
  document.getElementById('adminMarket').value = signal.market;
  document.getElementById('adminDirection').value = signal.direction;
  document.getElementById('adminStatus').value = signal.status;
  document.getElementById('adminEntry').value = signal.entryPrice;
  document.getElementById('adminTarget').value = signal.targetPrice;
  document.getElementById('adminStop').value = signal.stopPrice;
  document.getElementById('adminConfidence').value = signal.confidenceLabel;
  document.getElementById('adminSession').value = signal.sessionLabel;
  document.getElementById('adminSignalTime').value = signal.signalTimeUtc || '';
  document.getElementById('adminTimerMinutes').value = String(signal.timerMinutes || 90);
  document.getElementById('adminThesis').value = signal.thesis;

  setEditingMode(signal.id);
  setAdminMessage(`Editing signal #${signal.id}`);
}

async function deleteSignal(signalId) {
  if (!window.confirm('Delete this signal permanently?')) return;
  try {
    const response = await fetch(`/api/admin/signals/${signalId}`, { method: 'DELETE' });
    const result = await response.json();
    if (!response.ok) {
      setAdminMessage(result.message || 'Could not delete signal.');
      return;
    }
    setAdminMessage(result.message || 'Signal deleted.', true);
    const editingId = document.getElementById('adminEditingSignalId')?.value;
    if (editingId && String(editingId) === String(signalId)) {
      resetAdminFormForCreate();
    }
    await loadAdminSignals();
  } catch {
    setAdminMessage('Could not connect to server.');
  }
}

function renderAdminSignalsTable(signals) {
  const tableNode = document.getElementById('adminSignalsTable');
  if (!tableNode) return;
  if (!signals.length) {
    tableNode.innerHTML = '<p>No signals for this day yet.</p>';
    return;
  }

  tableNode.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Tier</th><th>Asset</th><th>Dir</th><th>Time UTC</th><th>Timer</th><th>Entry</th><th>Target</th><th>Stop</th><th>Status</th><th>Actions</th>
        </tr>
      </thead>
      <tbody>
        ${signals.map((signal) => `
          <tr>
            <td>${signal.id}</td>
            <td>${signal.tierNumber}</td>
            <td>${signal.assetSymbol}</td>
            <td>${signal.direction}</td>
            <td>${signal.signalTimeUtc || '--:--'}</td>
            <td>${signal.timerMinutes || 90}m</td>
            <td>${signal.entryPrice}</td>
            <td>${signal.targetPrice}</td>
            <td>${signal.stopPrice}</td>
            <td>${signal.status}</td>
            <td>
              <div class="admin-table-actions">
                <button class="ghost-btn admin-status-btn" data-id="${signal.id}" data-next="${signal.status === 'published' ? 'draft' : 'published'}">
                  ${signal.status === 'published' ? 'Unpublish' : 'Publish'}
                </button>
                <button class="ghost-btn admin-edit-btn" data-id="${signal.id}">Edit</button>
                <button class="ghost-btn danger-btn admin-delete-btn" data-id="${signal.id}">Delete</button>
              </div>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  document.querySelectorAll('.admin-status-btn').forEach((button) => {
    button.addEventListener('click', async () => {
      const signalId = button.dataset.id;
      const nextStatus = button.dataset.next;
      try {
        const response = await fetch(`/api/admin/signals/${signalId}/status`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: nextStatus }),
        });
        const result = await response.json();
        if (!response.ok) {
          setAdminMessage(result.message || 'Could not update status.');
          return;
        }
        setAdminMessage(result.message || 'Signal status updated.', true);
        await loadAdminSignals();
      } catch {
        setAdminMessage('Could not reach server.');
      }
    });
  });

  document.querySelectorAll('.admin-edit-btn').forEach((button) => {
    button.addEventListener('click', () => {
      beginEditSignal(button.dataset.id);
    });
  });

  document.querySelectorAll('.admin-delete-btn').forEach((button) => {
    button.addEventListener('click', async () => {
      await deleteSignal(button.dataset.id);
    });
  });
}

async function loadAdminSignals() {
  const dayNode = document.getElementById('adminSignalDay');
  const day = dayNode?.value;
  if (!day) return;

  try {
    const response = await fetch(`/api/admin/signals?day=${encodeURIComponent(day)}`);
    const result = await response.json();
    if (!response.ok) {
      setAdminMessage(result.message || 'Could not load signals.');
      return;
    }
    adminSignalsCache = result.signals || [];
    renderAdminSignalsTable(adminSignalsCache);
  } catch {
    setAdminMessage('Could not load signals from server.');
  }
}

async function handleAdminSignalCreate(event) {
  event.preventDefault();
  const payload = getAdminSignalPayload();
  const editingId = document.getElementById('adminEditingSignalId')?.value;
  const isEditing = Boolean(editingId);

  try {
    const response = await fetch(isEditing ? `/api/admin/signals/${editingId}` : '/api/admin/signals', {
      method: isEditing ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      setAdminMessage(result.message || 'Could not create signal.');
      return;
    }
    setAdminMessage(result.message || (isEditing ? 'Signal updated.' : 'Signal created.'), true);
    resetAdminFormForCreate();
    await loadAdminSignals();
  } catch {
    setAdminMessage('Could not connect to server.');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('adminSignalForm')?.addEventListener('submit', handleAdminSignalCreate);
  document.getElementById('adminRefreshBtn')?.addEventListener('click', loadAdminSignals);
  document.getElementById('adminCancelEditBtn')?.addEventListener('click', () => {
    resetAdminFormForCreate();
    setAdminMessage('Edit mode cancelled.');
  });
  document.getElementById('adminSignalDay')?.addEventListener('change', loadAdminSignals);
  setEditingMode(null);
  loadAdminSignals();
});
