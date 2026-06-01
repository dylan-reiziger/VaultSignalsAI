(function () {
  const body = document.body;
  if (!body) {
    return;
  }

  const hasAccess = body.dataset.securityAccess === "1";
  const authMode = body.dataset.securityAuthMode || "none";
  const panelEnabled = body.dataset.securityPanelEnabled === "1";

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function toDisplay(value) {
    if (value === null || value === undefined || value === "") {
      return "-";
    }
    return String(value);
  }

  function setMessage(element, message, isError) {
    if (!element) {
      return;
    }
    element.textContent = message;
    element.style.borderColor = isError ? "rgba(239, 76, 76, 0.58)" : "var(--line)";
    element.style.color = isError ? "#ffb5b5" : "var(--text-soft)";
  }

  async function parseJson(response) {
    try {
      return await response.json();
    } catch (_error) {
      return {};
    }
  }

  async function requestJson(url, options) {
    const response = await fetch(url, options || {});
    const payload = await parseJson(response);
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || "Request failed.");
    }
    return payload;
  }

  function renderOverview(summary) {
    const grid = document.getElementById("securityOverviewGrid");
    if (!grid) {
      return;
    }

    const cards = [
      { label: "Total accounts", value: summary.totalAccounts },
      { label: "Admin accounts", value: summary.adminAccounts },
      { label: "Verified accounts", value: summary.verifiedAccounts },
      { label: "Active sessions", value: summary.activeSessions },
      { label: "Events (24h)", value: summary.securityEventsLast24h },
      { label: "Blocked DB attempts (24h)", value: summary.blockedDatabaseAttemptsLast24h },
      { label: "Owner allowlisted", value: summary.ownerAllowlistedAccounts },
    ];

    grid.innerHTML = cards
      .map(
        (card) =>
          `<article class="security-overview-card"><span>${escapeHtml(card.label)}</span><strong>${escapeHtml(
            card.value
          )}</strong></article>`
      )
      .join("");
  }

  function renderAccounts(accounts) {
    const target = document.getElementById("securityAccountsTable");
    if (!target) {
      return;
    }

    if (!Array.isArray(accounts) || accounts.length === 0) {
      target.innerHTML = "<p>No account records found.</p>";
      return;
    }

    const rows = accounts
      .map(
        (account) => `
          <tr>
            <td>${escapeHtml(account.id)}</td>
            <td>${escapeHtml(account.username)}</td>
            <td>${escapeHtml(account.email)}</td>
            <td>${account.isAdmin ? "Yes" : "No"}</td>
            <td>${account.isAllowlistedOwner ? "Yes" : "No"}</td>
            <td>${account.isVerified ? "Yes" : "No"}</td>
            <td>${escapeHtml(account.activeTokens)}</td>
            <td>${escapeHtml(toDisplay(account.lastSecurityEventType))}</td>
            <td>${escapeHtml(toDisplay(account.lastSecurityEventStatus))}</td>
            <td>${escapeHtml(toDisplay(account.lastSecurityEventAt))}</td>
          </tr>
        `
      )
      .join("");

    target.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Username</th>
            <th>Email</th>
            <th>Admin</th>
            <th>Allowlisted</th>
            <th>Verified</th>
            <th>Tokens</th>
            <th>Last Event Type</th>
            <th>Last Event Status</th>
            <th>Last Event At</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function renderSecurityEvents(events) {
    const target = document.getElementById("securityEventsTable");
    if (!target) {
      return;
    }

    if (!Array.isArray(events) || events.length === 0) {
      target.innerHTML = "<p>No security events found.</p>";
      return;
    }

    const rows = events
      .map(
        (eventRow) => `
          <tr>
            <td>${escapeHtml(eventRow.id)}</td>
            <td>${escapeHtml(toDisplay(eventRow.accountId))}</td>
            <td>${escapeHtml(eventRow.username)}</td>
            <td>${escapeHtml(toDisplay(eventRow.email))}</td>
            <td>${escapeHtml(eventRow.eventType)}</td>
            <td>${escapeHtml(eventRow.eventStatus)}</td>
            <td>${escapeHtml(toDisplay(eventRow.ipHash))}</td>
            <td>${escapeHtml(toDisplay(eventRow.createdAt))}</td>
            <td>${escapeHtml(toDisplay(eventRow.userAgent))}</td>
          </tr>
        `
      )
      .join("");

    target.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Account ID</th>
            <th>Username</th>
            <th>Email</th>
            <th>Type</th>
            <th>Status</th>
            <th>IP Hash</th>
            <th>Created At</th>
            <th>User Agent</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function renderDatabaseTables(tableCounts) {
    const target = document.getElementById("securityTablesTable");
    if (!target) {
      return;
    }

    const entries = Object.entries(tableCounts || {});
    if (entries.length === 0) {
      target.innerHTML = "<p>No table metrics returned.</p>";
      return;
    }

    const rows = entries
      .map(([tableName, count]) => `<tr><td>${escapeHtml(tableName)}</td><td>${escapeHtml(count)}</td></tr>`)
      .join("");

    target.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Table</th>
            <th>Rows</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function renderAllowedEmails(summary) {
    const target = document.getElementById("securityAllowedEmails");
    if (!target) {
      return;
    }

    const emails = Array.isArray(summary.allowedOwnerEmails) ? summary.allowedOwnerEmails : [];
    if (emails.length === 0) {
      target.textContent = "Allowed owner emails: none configured.";
      return;
    }
    target.textContent = `Allowed owner emails: ${emails.join(", ")}`;
  }

  async function loadSecurityRecords() {
    const messageNode = document.getElementById("securityConsoleMessage");
    setMessage(messageNode, "Refreshing security records...", false);

    try {
      const payload = await requestJson("/api/admin/security/records");
      renderOverview(payload.summary || {});
      renderAccounts(payload.accounts || []);
      renderSecurityEvents(payload.securityEvents || []);
      renderDatabaseTables(payload.databaseTableCounts || {});
      renderAllowedEmails(payload.summary || {});
      setMessage(messageNode, `Records updated for ${payload.auth?.username || "operator"}.`, false);
    } catch (error) {
      setMessage(messageNode, error.message || "Unable to load security records.", true);
    }
  }

  async function handleSecurityPanelLogin(event) {
    event.preventDefault();
    const messageNode = document.getElementById("securityPanelLoginMessage");
    const usernameInput = document.getElementById("securityPanelUsername");
    const passwordInput = document.getElementById("securityPanelPassword");

    const username = (usernameInput?.value || "").trim();
    const password = passwordInput?.value || "";

    if (!username || !password) {
      setMessage(messageNode, "Enter username and password.", true);
      return;
    }

    try {
      await requestJson("/api/admin/security-panel/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ username, password }),
      });
      setMessage(messageNode, "Login successful. Loading security console...", false);
      window.location.assign("/admin/security");
    } catch (error) {
      setMessage(messageNode, error.message || "Login failed.", true);
      if (passwordInput) {
        passwordInput.value = "";
      }
    }
  }

  async function handleSecurityConsoleLogout() {
    const endpoint = authMode === "security_panel" ? "/api/admin/security-panel/logout" : "/api/logout";
    try {
      await requestJson(endpoint, { method: "POST" });
    } catch (_error) {
      // Continue with reload even when logout endpoint returns an error.
    }
    window.location.assign("/admin/security/login");
  }

  function initLoginView() {
    const form = document.getElementById("securityPanelLoginForm");
    if (form && panelEnabled) {
      form.addEventListener("submit", handleSecurityPanelLogin);
    }
  }

  function initConsoleView() {
    const refreshBtn = document.getElementById("securityRefreshBtn");
    const logoutBtn = document.getElementById("securityLogoutBtn");

    if (refreshBtn) {
      refreshBtn.addEventListener("click", function () {
        loadSecurityRecords();
      });
    }
    if (logoutBtn) {
      logoutBtn.addEventListener("click", function () {
        handleSecurityConsoleLogout();
      });
    }

    loadSecurityRecords();
  }

  if (hasAccess) {
    initConsoleView();
  } else {
    initLoginView();
  }
})();
