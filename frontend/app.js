let currentAnalysis = null;
let selectedClauseIndex = 0;
let currentFilter = 'all';
let selectedFile = null;
let kbClausesCache = [];
let runtimeApiKey = "";
let currentUser = null;
let authToken = localStorage.getItem('clauseclear_token') || null;
let currentAuthTab = 'login';
let userHistoryCache = [];
let demoLoginEnabled = false;

document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) {
    lucide.createIcons();
  }
  setupDropZone();
  loadKnowledgeBase();
  checkApiConfig();
  checkAuthStatus();

  // Close user dropdown when clicking outside
  document.addEventListener('click', (e) => {
    const dropdown = document.getElementById('user-dropdown');
    const menuBtn = document.getElementById('user-menu-btn');
    if (dropdown && !dropdown.classList.contains('hidden')) {
      if (!dropdown.contains(e.target) && !menuBtn?.contains(e.target)) {
        dropdown.classList.add('hidden');
      }
    }
  });
});

let runtimeGroqKey = "";

// Modal toggle
function toggleApiKeyModal() {
  const modal = document.getElementById('api-key-modal');
  if (!modal) return;
  if (modal.classList.contains('hidden')) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    const input = document.getElementById('gemini-key-input');
    if (input && runtimeApiKey) input.value = runtimeApiKey;
    const groqInput = document.getElementById('groq-key-input');
    if (groqInput && runtimeGroqKey) groqInput.value = runtimeGroqKey;
    checkApiConfig();
  } else {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }
}

async function checkApiConfig() {
  try {
    const res = await fetch('/api/config');
    if (res.ok) {
      const data = await res.json();

      const keyControls = document.getElementById('runtime-key-controls');
      const managedKeyNotice = document.getElementById('managed-key-notice');
      if (keyControls) keyControls.classList.toggle('hidden', !data.runtime_api_key_updates_enabled);
      if (managedKeyNotice) managedKeyNotice.classList.toggle('hidden', data.runtime_api_key_updates_enabled);
      demoLoginEnabled = Boolean(data.demo_login_enabled);
      document.getElementById('demo-login-box')?.classList.toggle('hidden', !demoLoginEnabled);
      
      // Update modal badges
      const groqBadge = document.getElementById('groq-status-badge');
      if (groqBadge) {
        if (data.groq_configured) {
          groqBadge.textContent = 'Active & Connected';
          groqBadge.className = 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200';
        } else {
          groqBadge.textContent = 'Not Configured';
          groqBadge.className = 'text-[10px] font-semibold px-2 py-0.5 rounded-full bg-gray-100 text-gray-600';
        }
      }

      const geminiBadge = document.getElementById('gemini-status-badge');
      if (geminiBadge) {
        if (data.gemini_configured) {
          geminiBadge.textContent = 'Active';
          geminiBadge.className = 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 border border-blue-200';
        } else {
          geminiBadge.textContent = 'Not Configured';
          geminiBadge.className = 'text-[10px] font-semibold px-2 py-0.5 rounded-full bg-gray-100 text-gray-600';
        }
      }

      const activeEngineName = document.getElementById('active-engine-name');
      const activeEngineBadge = document.getElementById('active-engine-badge');
      if (activeEngineName) {
        if (data.active_provider === 'groq') {
          activeEngineName.textContent = 'Groq (LLaMA 3.3 70B)';
          if (activeEngineBadge) {
            activeEngineBadge.textContent = 'Ultra Fast LLM';
            activeEngineBadge.className = 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-900 border border-amber-300';
          }
        } else if (data.active_provider === 'gemini') {
          activeEngineName.textContent = 'Google Gemini 1.5 Flash';
          if (activeEngineBadge) {
            activeEngineBadge.textContent = 'Cloud LLM';
            activeEngineBadge.className = 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-100 text-blue-900 border border-blue-300';
          }
        } else {
          activeEngineName.textContent = 'ClauseClear Hybrid Semantic Engine';
          if (activeEngineBadge) {
            activeEngineBadge.textContent = 'Local Rule Fallback';
            activeEngineBadge.className = 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-gray-100 text-gray-800 border border-gray-300';
          }
        }
      }

      const sessionStatus = document.getElementById('sidebar-session-status');
      if (sessionStatus && !selectedFile) {
        sessionStatus.textContent = (data.groq_configured || data.gemini_configured) ? 'Ready to Analyze' : 'Local Engine Ready';
      }
    }
  } catch (err) {}
}

async function saveGroqKey() {
  const input = document.getElementById('groq-key-input');
  const btn = document.getElementById('btn-save-groq');
  const key = input ? input.value.trim() : "";
  if (!key || key.length < 15) {
    alert('Please enter a valid Groq API Key (must start with gsk_...)');
    return;
  }

  const originalText = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="animate-spin mr-1">⏳</span> Verifying...';
  }

  try {
    const res = await fetch('/api/config/groq-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ groq_api_key: key })
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to verify Groq API key');
    runtimeGroqKey = key;
    alert(data.message || 'Groq API Key verified and activated successfully!');
    checkApiConfig();
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }
}

async function saveApiKey() {
  const input = document.getElementById('gemini-key-input');
  const btn = document.getElementById('btn-save-gemini');
  const key = input ? input.value.trim() : "";
  if (!key || key.length < 10) {
    alert('Please enter a valid Gemini API Key (e.g. AIzaSy...)');
    return;
  }

  const originalText = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="animate-spin mr-1">⏳</span> Saving...';
  }

  try {
    const res = await fetch('/api/config/key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gemini_api_key: key })
    });

    if (!res.ok) throw new Error('Failed to update API key');
    runtimeApiKey = key;
    alert('Gemini API Key activated successfully!');
    checkApiConfig();
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }
}

// Sidebar Navigation Tab Switching
function switchTab(tabId) {
  document.querySelectorAll('.tab-content').forEach(tab => tab.classList.add('hidden'));
  document.querySelectorAll('aside nav button').forEach(btn => {
    btn.classList.remove('nav-link-active');
  });

  document.querySelectorAll('.sidebar-rail-link[data-tab]').forEach(btn => {
    const isActive = btn.dataset.tab === tabId;
    btn.classList.toggle('is-active', isActive);
    if (isActive) btn.setAttribute('aria-current', 'page');
    else btn.removeAttribute('aria-current');
  });

  const activeContent = document.getElementById(`tab-${tabId}`);
  const activeBtn = document.getElementById(`nav-btn-${tabId}`);
  if (activeContent) {
    activeContent.classList.remove('hidden');
    activeContent.classList.remove('tab-animate');
    void activeContent.offsetWidth; // force reflow
    activeContent.classList.add('tab-animate');
  }
  if (activeBtn) activeBtn.classList.add('nav-link-active');

  const breadcrumbEl = document.getElementById('breadcrumb-current');
  if (breadcrumbEl) {
    const titles = {
      landing: 'Home & Overview',
      analyzer: 'Contract Analyzer',
      knowledge_base: 'Fair Terms Guide',
      eval: 'Developer View: Accuracy Benchmark',
      architecture: 'Developer View: Architecture'
    };
    breadcrumbEl.textContent = titles[tabId] || 'Overview';
  }

  // Scroll to top
  const main = document.querySelector('main');
  if (main) main.scrollTop = 0;

  if (window.lucide) lucide.createIcons();
}

let pendingActionAfterLogin = null;

function executePendingAction() {
  if (!pendingActionAfterLogin) return;
  const action = pendingActionAfterLogin;
  pendingActionAfterLogin = null;

  if (action.type === 'file_picker') {
    setTimeout(() => {
      const fileInput = document.getElementById('file-input');
      if (fileInput) fileInput.click();
    }, 350);
  } else if (action.type === 'dropped_file' && action.file) {
    handleFileSelected(action.file);
    showToast(`Document "${action.file.name}" ready to analyze.`);
  } else if (action.type === 'start_analysis') {
    setTimeout(() => {
      startAnalysis();
    }, 350);
  }
}

// File Upload & Dropzone Handling
function setupDropZone() {
  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');
  if (!dropZone || !fileInput) return;

  dropZone.addEventListener('click', (e) => {
    if (!currentUser && !authToken) {
      e.preventDefault();
      pendingActionAfterLogin = { type: 'file_picker' };
      openAuthModal('login');
      showAuthAlert('Please sign in or create an account to add and analyze documents.', 'info');
      return;
    }
    fileInput.click();
  });

  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      if (!currentUser && !authToken) {
        pendingActionAfterLogin = { type: 'dropped_file', file: e.dataTransfer.files[0] };
        openAuthModal('login');
        showAuthAlert('Please sign in or create an account to analyze this document.', 'info');
        return;
      }
      handleFileSelected(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener('click', (e) => {
    if (!currentUser && !authToken) {
      e.preventDefault();
      pendingActionAfterLogin = { type: 'file_picker' };
      openAuthModal('login');
      showAuthAlert('Please sign in or create an account to add documents.', 'info');
      return;
    }
  });

  fileInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      handleFileSelected(e.target.files[0]);
    }
  });
}

function handleFileSelected(file) {
  selectedFile = file;
  const nameDisplay = document.getElementById('file-selected-name');
  if (nameDisplay) {
    nameDisplay.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    nameDisplay.classList.remove('hidden');
  }

  const breadcrumbFile = document.getElementById('breadcrumb-file');
  if (breadcrumbFile) {
    breadcrumbFile.textContent = file.name;
    breadcrumbFile.classList.remove('hidden');
  }

  const sessionStatus = document.getElementById('sidebar-session-status');
  if (sessionStatus) sessionStatus.textContent = file.name;
}

function clearContractInput() {
  document.getElementById('contract-text-input').value = '';
  selectedFile = null;
  const nameDisplay = document.getElementById('file-selected-name');
  if (nameDisplay) nameDisplay.classList.add('hidden');

  const breadcrumbFile = document.getElementById('breadcrumb-file');
  if (breadcrumbFile) breadcrumbFile.classList.add('hidden');

  const sessionStatus = document.getElementById('sidebar-session-status');
  if (sessionStatus) sessionStatus.textContent = 'Ready to Analyze';
}

// Instant Preset Sample Loader
async function loadSample(sampleId) {
  switchTab('analyzer');
  try {
    const res = await fetch(`/api/samples/${sampleId}`);
    if (!res.ok) throw new Error('Failed to load sample agreement');
    const data = await res.json();

    document.getElementById('contract-text-input').value = data.text;
    selectedFile = null;
    const nameDisplay = document.getElementById('file-selected-name');
    if (nameDisplay) nameDisplay.classList.add('hidden');

    const breadcrumbFile = document.getElementById('breadcrumb-file');
    if (breadcrumbFile) {
      breadcrumbFile.textContent = data.filename;
      breadcrumbFile.classList.remove('hidden');
    }

    const sessionStatus = document.getElementById('sidebar-session-status');
    if (sessionStatus) sessionStatus.textContent = data.filename;

    if (!currentUser && !authToken) {
      pendingActionAfterLogin = { type: 'start_analysis' };
      openAuthModal('login');
      showAuthAlert('Sample loaded! Please sign in or create an account to run the full analysis.', 'info');
      return;
    }

    startAnalysis();
  } catch (err) {
    alert(`Could not load sample: ${err.message}`);
  }
}

// Start Analysis Pipeline
async function startAnalysis() {
  const textInput = (document.getElementById('contract-text-input')?.value || '').trim();
  const rawProvider = document.getElementById('engine-selector')?.value;
  const provider = (rawProvider && rawProvider !== 'auto' && rawProvider !== 'gemini') ? rawProvider : undefined;

  if (!selectedFile && (!textInput || textInput.length < 30)) {
    alert('Please upload a contract file (PDF/Text) or paste agreement clauses (minimum 30 characters).');
    return;
  }

  // Enforce login for analysis
  if (!currentUser && !authToken) {
    pendingActionAfterLogin = { type: 'start_analysis' };
    openAuthModal('login');
    showAuthAlert('Please sign in or create an account to analyze your document.', 'info');
    return;
  }

  const loadingEl = document.getElementById('analysis-loading');
  const resultsEl = document.getElementById('results-dashboard');
  const btnAnalyze = document.getElementById('btn-analyze');

  loadingEl.classList.remove('hidden');
  resultsEl.classList.add('hidden');
  btnAnalyze.disabled = true;

  try {
    let response;
    const authHeaders = authToken ? { 'Authorization': `Bearer ${authToken}` } : {};

    if (selectedFile) {
      const formData = new FormData();
      formData.append('file', selectedFile);
      if (provider) formData.append('provider', provider);
      if (runtimeApiKey) formData.append('api_key', runtimeApiKey);

      response = await fetch('/api/analyze/file', {
        method: 'POST',
        headers: authHeaders,
        body: formData
      });
    } else {
      response = await fetch('/api/analyze/text', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders
        },
        body: JSON.stringify({
          text: textInput,
          document_title: 'Submitted Legal Agreement',
          provider: provider,
          api_key: runtimeApiKey || null
        })
      });
    }

    if (response.status === 401) {
      authToken = null;
      currentUser = null;
      localStorage.removeItem('clauseclear_token');
      updateAuthUI();
      pendingActionAfterLogin = { type: 'start_analysis' };
      openAuthModal('login');
      showAuthAlert('Your session has expired. Please sign in to analyze contracts.', 'error');
      return;
    }

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.detail || 'Analysis request failed');
    }

    const data = await response.json();
    currentAnalysis = data;
    selectedClauseIndex = 0;
    renderAnalysisResults(data);
    updateSaveStatusBanner();

    if (currentUser) {
      loadUserHistory();
    }

  } catch (err) {
    alert(`Analysis Error: ${err.message}`);
  } finally {
    loadingEl.classList.add('hidden');
    btnAnalyze.disabled = false;
  }
}

// Render Results Dashboard
function renderAnalysisResults(data) {
  const resultsEl = document.getElementById('results-dashboard');
  resultsEl.classList.remove('hidden');

  document.getElementById('doc-title-display').textContent = data.document_title || 'Legal Agreement Analysis';
  document.getElementById('doc-verdict-display').textContent = data.summary.overall_verdict;
  document.getElementById('risk-score-display').textContent = `${data.summary.overall_risk_score} / 100`;
  document.getElementById('processing-time-display').textContent = `${data.processing_time_seconds}s`;

  // Risk Badge Styling
  const overallBadge = document.getElementById('risk-badge-overall');
  const score = data.summary.overall_risk_score;
  if (score >= 65) {
    overallBadge.textContent = 'Predatory / High Risk';
    overallBadge.className = 'px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-[#FEF2F2] text-[#DC2626] border border-[#FECACA] shadow-sm';
  } else if (score >= 35) {
    overallBadge.textContent = 'Unusual Terms (Review Advised)';
    overallBadge.className = 'px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-[#FFFBEB] text-[#D97706] border border-[#FDE68A] shadow-sm';
  } else {
    overallBadge.textContent = 'Fair & Standard Terms';
    overallBadge.className = 'px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-[#ECFDF5] text-[#059669] border border-[#A7F3D0] shadow-sm';
  }

  // Summary Metrics — animated count-up
  animateCountUp('stat-total-clauses', data.summary.total_clauses);
  animateCountUp('stat-high-risk', data.summary.high_risk_count);
  animateCountUp('stat-med-risk', data.summary.medium_risk_count);
  animateCountUp('stat-low-risk', data.summary.low_risk_count);
  animateCountUp('stat-unusual-count', data.summary.unusual_clause_count);

  // Red Flags Box
  const redFlagsContainer = document.getElementById('red-flags-container');
  const redFlagsList = document.getElementById('red-flags-list');
  redFlagsList.innerHTML = '';

  if (data.summary.key_red_flags && data.summary.key_red_flags.length > 0) {
    redFlagsContainer.classList.remove('hidden');
    renderRedFlagsAnimated(data.summary.key_red_flags, redFlagsList);
  } else {
    redFlagsContainer.classList.add('hidden');
  }

  // Render Clause List & Inspector
  renderClausesList();
  selectClause(0);

  // Smooth scroll
  resultsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
  if (window.lucide) lucide.createIcons();
}

// Filter View
function filterClauses(filterType) {
  currentFilter = filterType;
  ['all', 'high', 'medium', 'low'].forEach(f => {
    const btn = document.getElementById(`filter-btn-${f}`);
    if (f === filterType) {
      btn.className = 'px-3.5 py-1.5 rounded-lg font-semibold text-white bg-teal-700 shadow-sm';
    } else {
      btn.className = 'px-3.5 py-1.5 rounded-lg font-semibold text-[#6B7280] hover:text-[#111827]';
    }
  });
  renderClausesList();
}

// Render Left Clause Cards List
function renderClausesList() {
  if (!currentAnalysis || !currentAnalysis.clauses) return;
  const container = document.getElementById('clauses-list-container');
  container.innerHTML = '';

  const clauses = currentAnalysis.clauses;
  let visibleCount = 0;

  clauses.forEach((clause, idx) => {
    if (currentFilter !== 'all' && clause.risk_level !== currentFilter) {
      return;
    }
    visibleCount++;

    const card = document.createElement('div');
    const isSelected = (idx === selectedClauseIndex);
    const riskClass = `risk-${clause.risk_level}`;

    let badgeClass = 'bg-[#ECFDF5] text-[#059669] border border-[#A7F3D0]';
    if (clause.risk_level === 'high') {
      badgeClass = 'bg-[#FEF2F2] text-[#DC2626] border border-[#FECACA]';
    } else if (clause.risk_level === 'medium') {
      badgeClass = 'bg-[#FFFBEB] text-[#D97706] border border-[#FDE68A]';
    }

    card.className = `p-4 sm:p-5 rounded-2xl cursor-pointer transition-all duration-150 border border-[#E5E7EB] bg-white hover:border-[#D1D5DB] clause-card-animate ${riskClass} ${isSelected ? 'clause-card-selected' : ''}`;
    card.style.animationDelay = `${visibleCount * 45}ms`;
    card.onclick = () => selectClause(idx);

    card.innerHTML = `
      <div class="flex items-center justify-between gap-2 mb-1.5">
        <span class="text-xs font-bold text-[#111827] truncate">
          ${escapeHtml(clause.clause_title || `Clause ${idx+1}`)}
        </span>
        <span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${badgeClass}">
          ${clause.risk_level === 'high' ? 'Predatory' : clause.risk_level === 'medium' ? 'Unusual' : 'Standard'}
        </span>
      </div>
      <p class="text-xs text-[#4B5563] line-clamp-2 leading-relaxed">
        ${escapeHtml(clause.clause_text)}
      </p>
      <div class="flex items-center justify-between mt-2.5 pt-2 border-t border-[#F3F4F6] text-[11px] text-[#6B7280]">
        <span class="text-teal-700 font-semibold">${escapeHtml(clause.clause_type.replace(/_/g, ' '))}</span>
        <span class="font-medium text-[#374151]">Risk: <strong>${clause.risk_score}</strong>/100</span>
      </div>
    `;

    container.appendChild(card);
  });

  if (visibleCount === 0) {
    container.innerHTML = `<div class="p-8 text-center text-xs text-[#9CA3AF] border border-[#E5E7EB] rounded-2xl bg-white">No clauses match the selected filter.</div>`;
  }
}

// Select & Deep-Dive Clause Inspector
function selectClause(idx) {
  if (!currentAnalysis || !currentAnalysis.clauses || !currentAnalysis.clauses[idx]) return;
  selectedClauseIndex = idx;
  renderClausesList();

  const clause = currentAnalysis.clauses[idx];
  const inspector = document.getElementById('clause-inspector');

  inspector.classList.remove('inspector-animate');
  void inspector.offsetWidth;
  inspector.classList.add('inspector-animate');

  let riskColor = 'text-[#059669]';
  let riskBadge = 'bg-[#ECFDF5] text-[#059669] border border-[#A7F3D0]';
  let riskLabel = 'Fair & Standard';

  if (clause.risk_level === 'high') {
    riskColor = 'text-[#DC2626]';
    riskBadge = 'bg-[#FEF2F2] text-[#DC2626] border border-[#FECACA]';
    riskLabel = 'Predatory Trap';
  } else if (clause.risk_level === 'medium') {
    riskColor = 'text-[#D97706]';
    riskBadge = 'bg-[#FFFBEB] text-[#D97706] border border-[#FDE68A]';
    riskLabel = 'Unusual Term';
  }

  // Deviations list
  let deviationsHtml = '';
  if (clause.deviation_points && clause.deviation_points.length > 0) {
    deviationsHtml = `
      <div class="callout-red-flag p-4 sm:p-5 space-y-2">
        <h5 class="text-xs font-bold text-[#DC2626] uppercase tracking-wider flex items-center space-x-1.5">
          <i data-lucide="alert-triangle" class="w-4 h-4 text-[#EF4444]"></i>
          <span>Non-Standard Terms Detected:</span>
        </h5>
        <ul class="text-xs sm:text-sm text-[#7F1D1D] space-y-1.5 list-disc list-inside">
          ${clause.deviation_points.map(d => `<li>${escapeHtml(d)}</li>`).join('')}
        </ul>
      </div>
    `;
  }

  // Stage 2 Validation Pass Badge
  let validationHtml = '';
  if (clause.validation_audit && clause.validation_audit.is_validated) {
    validationHtml = `
      <div class="flex items-center justify-between p-3.5 bg-[#F9FAFB] border border-[#E5E7EB] rounded-xl text-xs">
        <div class="flex items-center space-x-2">
          <i data-lucide="shield-check" class="w-4 h-4 text-teal-600"></i>
          <span class="text-[#374151] font-semibold">Verification Audit:</span>
        </div>
        <span class="text-[11px] text-[#6B7280] italic">${escapeHtml(clause.validation_audit.validator_notes)}</span>
      </div>
    `;
  }

  inspector.innerHTML = `
    <!-- Header -->
    <div class="flex items-start justify-between gap-4 border-b border-[#F3F4F6] pb-4">
      <div>
        <span class="text-[11px] font-bold uppercase tracking-wider text-teal-700 block">${escapeHtml(clause.clause_type.replace(/_/g, ' '))}</span>
        <h3 class="text-xl font-extrabold text-[#111827] mt-0.5 tracking-tight">${escapeHtml(clause.clause_title || 'Legal Clause')}</h3>
      </div>
      <div class="text-right flex flex-col items-end shrink-0">
        <span class="px-3 py-1 rounded-full text-xs font-bold uppercase ${riskBadge}">
          ${riskLabel}
        </span>
        <span class="text-xs text-[#6B7280] mt-1">Risk Score: <strong class="${riskColor} font-mono">${clause.risk_score}</strong>/100</span>
      </div>
    </div>

    <!-- Original Text Block -->
    <div class="space-y-1.5">
      <div class="flex items-center justify-between">
        <h5 class="text-xs font-bold text-[#6B7280] uppercase tracking-wider flex items-center space-x-1.5">
          <i data-lucide="file-text" class="w-3.5 h-3.5 text-[#9CA3AF]"></i>
          <span>Original Agreement Text:</span>
        </h5>
        <button onclick="copyClauseField(${idx}, 'clause_text')" class="text-xs text-teal-700 hover:text-teal-800 flex items-center space-x-1 font-medium">
          <i data-lucide="copy" class="w-3.5 h-3.5"></i>
          <span>Copy</span>
        </button>
      </div>
      <div class="bg-[#F9FAFB] border border-[#E5E7EB] p-4 rounded-xl text-xs text-[#374151] leading-relaxed max-h-36 overflow-y-auto">
        ${escapeHtml(clause.clause_text)}
      </div>
    </div>

    <!-- Plain English Translation -->
    <div class="callout-plain-english p-4 sm:p-5 space-y-2">
      <h5 class="text-xs font-bold text-teal-800 uppercase tracking-wider flex items-center space-x-1.5">
        <i data-lucide="sparkles" class="w-4 h-4 text-teal-600"></i>
        <span>In Plain English (What this means for you):</span>
      </h5>
      <p class="text-xs sm:text-sm text-[#134E4A] leading-relaxed font-medium">
        ${escapeHtml(clause.plain_language_explanation)}
      </p>
    </div>

    <!-- Deviations (if any) -->
    ${deviationsHtml}

    <!-- Standard Baseline Comparison -->
    <div class="callout-standard-baseline p-4 space-y-1.5">
      <h5 class="text-xs font-bold text-[#374151] uppercase tracking-wider flex items-center space-x-1.5">
        <i data-lucide="scale" class="w-3.5 h-3.5 text-teal-600"></i>
        <span>Compared to Fair Standard Terms:</span>
      </h5>
      <p class="text-xs text-[#4B5563] leading-relaxed">
        ${escapeHtml(clause.standard_baseline_comparison || 'Standard market agreements stipulate reasonable mutual notice, fair wear-and-tear exclusions, and statutory consumer protections.')}
      </p>
    </div>

    <!-- Questions to Ask -->
    <div class="callout-questions p-4 sm:p-5 space-y-2.5">
      <div class="flex items-center justify-between">
        <h5 class="text-xs font-bold text-[#92400E] uppercase tracking-wider flex items-center space-x-1.5">
          <i data-lucide="message-square-quote" class="w-4 h-4 text-[#D97706]"></i>
          <span>Polite Question to Ask Your Landlord / Lender:</span>
        </h5>
        <button onclick="copyClauseField(${idx}, 'suggested_question_to_ask_landlord')" class="bg-white hover:bg-amber-50 text-[#92400E] border border-[#FDE68A] px-2.5 py-1 rounded-lg text-xs font-semibold shadow-sm flex items-center space-x-1">
          <i data-lucide="copy" class="w-3 h-3"></i>
          <span>Copy Question</span>
        </button>
      </div>
      <p class="text-xs sm:text-sm text-[#78350F] font-medium italic leading-relaxed">
        "${escapeHtml(clause.suggested_question_to_ask_landlord)}"
      </p>
    </div>

    <!-- Stage 2 Audit -->
    ${validationHtml}
  `;

  if (window.lucide) lucide.createIcons();
}

function copyClauseField(idx, field) {
  const clause = currentAnalysis?.clauses?.[idx];
  if (clause && typeof clause[field] === 'string') copyText(clause[field]);
}

function copyText(text) {
  navigator.clipboard.writeText(text).then(() => {
    alert('Copied to clipboard!');
  }).catch(err => {
    alert('Could not copy text: ' + err);
  });
}

function copyAllQuestions() {
  if (!currentAnalysis || !currentAnalysis.clauses) return;
  const questions = currentAnalysis.clauses
    .filter(c => c.suggested_question_to_ask_landlord &&
                 !c.suggested_question_to_ask_landlord.startsWith('No modification needed'))
    .map((c, i) => `${i+1}. [${c.clause_title}]\n   "${c.suggested_question_to_ask_landlord}"\n`)
    .join('\n');

  if (!questions) {
    alert('No questions generated for this agreement.');
    return;
  }

  navigator.clipboard.writeText(questions).then(() => {
    alert('All negotiation counter-questions copied to clipboard!');
  });
}

async function loadKnowledgeBase() {
  try {
    const res = await fetch('/api/kb/clauses');
    if (!res.ok) return;
    const data = await res.json();
    kbClausesCache = data.clauses || [];
    renderKBGrid(kbClausesCache);

    const kbCountEl = document.getElementById('sidebar-kb-count');
    if (kbCountEl) kbCountEl.textContent = `${kbClausesCache.length}`;
  } catch (err) {
    console.error('KB Load error:', err);
  }
}

function renderKBGrid(clauses) {
  const container = document.getElementById('kb-clauses-grid');
  if (!container) return;
  container.innerHTML = '';

  clauses.forEach(c => {
    const card = document.createElement('div');
    card.className = 'surface-card p-6 rounded-2xl border border-[#E5E7EB] bg-white space-y-3.5 shadow-sm';

    const flagsHtml = (c.typical_red_flags || []).map(f => `<span class="px-2.5 py-1 bg-red-50 text-[#DC2626] border border-red-200 rounded-full text-[11px] font-medium">${escapeHtml(f)}</span>`).join(' ');

    card.innerHTML = `
      <div class="flex items-center justify-between">
        <span class="text-[11px] font-bold uppercase tracking-wider text-teal-700">${escapeHtml(c.category.replace(/_/g, ' '))}</span>
        <span class="text-[10px] font-mono text-[#9CA3AF]">${escapeHtml(c.id)}</span>
      </div>
      <h4 class="text-base font-bold text-[#111827]">${escapeHtml(c.title)}</h4>
      <p class="text-xs text-[#4B5563] leading-relaxed bg-[#F9FAFB] p-3.5 rounded-xl border border-[#E5E7EB]">
        ${escapeHtml(c.baseline_text)}
      </p>
      <div class="space-y-1 text-xs">
        <span class="text-[#6B7280] block font-semibold text-[11px]">Acceptable Market Standard:</span>
        <p class="text-[#374151] leading-relaxed">${escapeHtml(c.standard_acceptable_range || '')}</p>
      </div>
      <div class="space-y-1 pt-1">
        <span class="text-[#6B7280] block font-semibold text-[11px]">Unusual Traps to Watch For:</span>
        <div class="flex flex-wrap gap-1.5 pt-0.5">
          ${flagsHtml}
        </div>
      </div>
    `;

    container.appendChild(card);
  });
}

function filterKB() {
  const query = document.getElementById('kb-search-input').value.toLowerCase();
  const filtered = kbClausesCache.filter(c =>
    c.title.toLowerCase().includes(query) ||
    c.category.toLowerCase().includes(query) ||
    c.baseline_text.toLowerCase().includes(query)
  );
  renderKBGrid(filtered);
}

async function triggerEvaluation(isInitial = false) {
  const btn = document.getElementById('btn-run-eval');
  if (btn && !isInitial) {
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Testing Benchmark...</span>`;
    if (window.lucide) lucide.createIcons();
  }

  try {
    const res = await fetch('/api/eval/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: 'local' })
    });

    if (!res.ok) throw new Error('Benchmark run failed');
    const data = await res.json();
    renderEvaluationResults(data);

  } catch (err) {
    console.error('Eval error:', err);
  } finally {
    if (btn && !isInitial) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="play" class="w-3.5 h-3.5"></i><span>Run Live Benchmark</span>`;
      if (window.lucide) lucide.createIcons();
    }
  }
}

function renderEvaluationResults(data) {
  const m = data.metrics.unusual_clause_detection;

  document.getElementById('eval-precision').textContent = `${(m.precision * 100).toFixed(1)}%`;
  document.getElementById('eval-recall').textContent = `${(m.recall * 100).toFixed(1)}%`;
  document.getElementById('eval-f1').textContent = m.f1_score.toFixed(3);
  document.getElementById('eval-accuracy').textContent = `${(m.accuracy * 100).toFixed(1)}%`;
  document.getElementById('eval-risk-match').textContent = `${(data.metrics.risk_level_accuracy * 100).toFixed(1)}%`;
  document.getElementById('eval-samples-count').textContent = data.total_test_samples;

  document.getElementById('matrix-tp').textContent = m.tp;
  document.getElementById('matrix-fp').textContent = m.fp;
  document.getElementById('matrix-fn').textContent = m.fn;
  document.getElementById('matrix-tn').textContent = m.tn;

  document.getElementById('stage2-checks-count').textContent = data.metrics.stage2_validation.high_risk_checks_run;
  document.getElementById('stage2-corrections-count').textContent = data.metrics.stage2_validation.false_positives_corrected;

  const tableBody = document.getElementById('eval-table-body');
  if (tableBody && data.detailed_results) {
    tableBody.innerHTML = '';
    data.detailed_results.forEach(item => {
      const tr = document.createElement('tr');
      const isPass = (item.classification === 'TP' || item.classification === 'TN') && item.risk_match;

      tr.innerHTML = `
        <td class="p-3.5 font-semibold text-[#111827]">${escapeHtml(item.title)}</td>
        <td class="p-3.5 font-mono text-[11px] text-teal-700">${escapeHtml(item.pred_category)}</td>
        <td class="p-3.5">
          <span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold ${item.ground_truth_unusual ? 'bg-[#FEF2F2] text-[#DC2626] border border-[#FECACA]' : 'bg-[#ECFDF5] text-[#059669] border border-[#A7F3D0]'}">
            ${item.ground_truth_unusual ? 'Unusual' : 'Standard'}
          </span>
        </td>
        <td class="p-3.5">
          <span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold ${item.pred_unusual ? 'bg-[#FEF2F2] text-[#DC2626] border border-[#FECACA]' : 'bg-[#ECFDF5] text-[#059669] border border-[#A7F3D0]'}">
            ${item.pred_unusual ? 'Unusual' : 'Standard'}
          </span>
        </td>
        <td class="p-3.5 uppercase text-[10px] font-bold font-mono ${item.risk_match ? 'text-[#374151]' : 'text-amber-600'}">${escapeHtml(item.pred_risk)}</td>
        <td class="p-3.5">
          <span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold ${isPass ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-red-50 text-red-700 border border-red-200'}">
            ${isPass ? 'PASS' : 'FAIL'}
          </span>
        </td>
      `;
      tableBody.appendChild(tr);
    });
  }

  if (window.lucide) lucide.createIcons();
}

// Utility escape helpers
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function escapeQuotes(str) {
  return escapeHtml(str);
}

// Animated count-up
function animateCountUp(elementId, targetValue, suffix = '') {
  const el = document.getElementById(elementId);
  if (!el) return;

  const startValue = 0;
  const duration = 500;
  const startTime = performance.now();

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = Math.round(startValue + (targetValue - startValue) * eased);
    el.textContent = current + suffix;

    if (progress < 1) {
      requestAnimationFrame(update);
    } else {
      el.textContent = targetValue + suffix;
      el.classList.remove('stat-flash');
      void el.offsetWidth;
      el.classList.add('stat-flash');
    }
  }

  requestAnimationFrame(update);
}

// Animated red flags list
function renderRedFlagsAnimated(flags, listEl) {
  listEl.innerHTML = '';
  flags.forEach((flag, i) => {
    const li = document.createElement('li');
    li.textContent = flag;
    li.className = 'flag-animate';
    li.style.animationDelay = `${i * 60}ms`;
    listEl.appendChild(li);
  });
}

// ============================================================================
// AUTHENTICATION & USER MANAGEMENT CONTROLLER
// ============================================================================

async function checkAuthStatus() {
  if (!authToken) {
    updateAuthUI();
    return;
  }
  try {
    const res = await fetch('/api/auth/me', {
      headers: { 'Authorization': `Bearer ${authToken}` }
    });
    if (res.ok) {
      currentUser = await res.json();
      updateAuthUI();
      loadUserHistory();
    } else {
      // Invalid/expired token
      authToken = null;
      currentUser = null;
      localStorage.removeItem('clauseclear_token');
      updateAuthUI();
    }
  } catch (err) {
    console.error('Failed to verify authentication:', err);
    updateAuthUI();
  }
}

function updateAuthUI() {
  const guestControls = document.getElementById('header-guest-controls');
  const authControls = document.getElementById('header-auth-controls');
  const sidebarGuestView = document.getElementById('sidebar-guest-view');
  const sidebarAuthView = document.getElementById('sidebar-auth-view');
  const sidebarHistoryCount = document.getElementById('sidebar-history-count');

  if (currentUser) {
    // Header UI
    if (guestControls) guestControls.classList.add('hidden');
    if (authControls) authControls.classList.remove('hidden');

    const initials = getInitials(currentUser.name);
    const headerAvatar = document.getElementById('header-user-avatar');
    if (headerAvatar) headerAvatar.textContent = initials;

    const headerName = document.getElementById('header-user-name');
    if (headerName) headerName.textContent = currentUser.name;

    const dropName = document.getElementById('dropdown-user-name');
    if (dropName) dropName.textContent = currentUser.name;

    const dropEmail = document.getElementById('dropdown-user-email');
    if (dropEmail) dropEmail.textContent = currentUser.email;

    const dropRole = document.getElementById('dropdown-user-role');
    if (dropRole) dropRole.textContent = currentUser.role === 'pro_member' ? 'Pro Member' : 'Member';

    // Sidebar UI
    if (sidebarGuestView) sidebarGuestView.classList.add('hidden');
    if (sidebarAuthView) sidebarAuthView.classList.remove('hidden');

    const sideAvatar = document.getElementById('sidebar-user-avatar');
    if (sideAvatar) sideAvatar.textContent = initials;

    const sideName = document.getElementById('sidebar-user-name');
    if (sideName) sideName.textContent = currentUser.name;

    const sideEmail = document.getElementById('sidebar-user-email');
    if (sideEmail) sideEmail.textContent = currentUser.email;

    if (sidebarHistoryCount) sidebarHistoryCount.classList.remove('hidden');
  } else {
    // Header UI
    if (guestControls) guestControls.classList.remove('hidden');
    if (authControls) authControls.classList.add('hidden');

    // Sidebar UI
    if (sidebarGuestView) sidebarGuestView.classList.remove('hidden');
    if (sidebarAuthView) sidebarAuthView.classList.add('hidden');
    if (sidebarHistoryCount) sidebarHistoryCount.classList.add('hidden');
  }

  const dropzoneAuthHint = document.getElementById('dropzone-auth-hint');
  if (dropzoneAuthHint) {
    if (currentUser) {
      dropzoneAuthHint.classList.add('hidden');
    } else {
      dropzoneAuthHint.classList.remove('hidden');
    }
  }

  updateSaveStatusBanner();
  if (window.lucide) lucide.createIcons();
}

function getInitials(name) {
  if (!name) return 'U';
  const parts = name.trim().split(' ');
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

function toggleUserDropdown(force) {
  const dropdown = document.getElementById('user-dropdown');
  if (!dropdown) return;
  if (typeof force === 'boolean') {
    if (force) dropdown.classList.remove('hidden');
    else dropdown.classList.add('hidden');
  } else {
    dropdown.classList.toggle('hidden');
  }
}

function openAuthModal(tab = 'login') {
  const modal = document.getElementById('auth-modal');
  if (!modal) return;
  setAuthTab(tab);
  clearAuthAlert();

  // Clear input fields
  document.getElementById('auth-email').value = '';
  document.getElementById('auth-password').value = '';
  const nameInput = document.getElementById('auth-name');
  if (nameInput) nameInput.value = '';
  const confirmInput = document.getElementById('auth-confirm-password');
  if (confirmInput) confirmInput.value = '';

  modal.classList.remove('hidden');
  modal.classList.add('flex');
  if (window.lucide) lucide.createIcons();
}

function closeAuthModal() {
  const modal = document.getElementById('auth-modal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function setAuthTab(tab) {
  currentAuthTab = tab;
  clearAuthAlert();

  const tabBtnLogin = document.getElementById('auth-tab-btn-login');
  const tabBtnRegister = document.getElementById('auth-tab-btn-register');
  const nameGroup = document.getElementById('auth-name-group');
  const confirmGroup = document.getElementById('auth-confirm-group');
  const submitText = document.getElementById('auth-submit-text');
  const modalTitle = document.getElementById('auth-modal-title');
  const modalSubtitle = document.getElementById('auth-modal-subtitle');
  const footerText = document.getElementById('auth-footer-text');
  const footerToggleBtn = document.getElementById('auth-footer-toggle-btn');
  const demoBox = document.getElementById('demo-login-box');

  if (tab === 'login') {
    tabBtnLogin?.classList.add('active');
    tabBtnRegister?.classList.remove('active');
    nameGroup?.classList.add('hidden');
    confirmGroup?.classList.add('hidden');
    demoBox?.classList.toggle('hidden', !demoLoginEnabled);
    if (submitText) submitText.textContent = 'Sign In to Account';
    if (modalTitle) modalTitle.textContent = 'Welcome Back';
    if (modalSubtitle) modalSubtitle.textContent = 'Sign in to access your saved contracts and history.';
    if (footerText) footerText.textContent = "Don't have an account?";
    if (footerToggleBtn) footerToggleBtn.textContent = 'Create Free Account';
  } else {
    tabBtnLogin?.classList.remove('active');
    tabBtnRegister?.classList.add('active');
    nameGroup?.classList.remove('hidden');
    confirmGroup?.classList.remove('hidden');
    demoBox?.classList.add('hidden');
    if (submitText) submitText.textContent = 'Create Free Account';
    if (modalTitle) modalTitle.textContent = 'Create Your Account';
    if (modalSubtitle) modalSubtitle.textContent = 'Sign up to safely save, track, and review contracts.';
    if (footerText) footerText.textContent = 'Already have an account?';
    if (footerToggleBtn) footerToggleBtn.textContent = 'Sign In';
  }

  if (window.lucide) lucide.createIcons();
}

function toggleAuthTab() {
  setAuthTab(currentAuthTab === 'login' ? 'register' : 'login');
}

function togglePasswordVisibility(inputId, iconId) {
  const input = document.getElementById(inputId);
  const icon = document.getElementById(iconId);
  if (!input) return;

  if (input.type === 'password') {
    input.type = 'text';
    if (icon) icon.setAttribute('data-lucide', 'eye-off');
  } else {
    input.type = 'password';
    if (icon) icon.setAttribute('data-lucide', 'eye');
  }
  if (window.lucide) lucide.createIcons();
}

function showAuthAlert(message, type = 'error') {
  const alert = document.getElementById('auth-alert');
  if (!alert) return;
  alert.textContent = message;
  alert.className = type === 'error'
    ? 'p-3 rounded-xl text-xs font-medium border bg-red-50 text-red-700 border-red-200 block'
    : 'p-3 rounded-xl text-xs font-medium border bg-emerald-50 text-emerald-700 border-emerald-200 block';
}

function clearAuthAlert() {
  const alert = document.getElementById('auth-alert');
  if (alert) {
    alert.className = 'hidden p-3 rounded-xl text-xs font-medium border';
    alert.textContent = '';
  }
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  clearAuthAlert();

  const email = document.getElementById('auth-email').value.trim();
  const password = document.getElementById('auth-password').value;
  const submitBtn = document.getElementById('auth-submit-btn');

  if (currentAuthTab === 'register') {
    const name = document.getElementById('auth-name').value.trim();
    const confirmPass = document.getElementById('auth-confirm-password').value;

    if (!name || name.length < 2) {
      showAuthAlert('Please enter your full name (minimum 2 characters).');
      return;
    }
    if (password.length < 6) {
      showAuthAlert('Password must be at least 6 characters long.');
      return;
    }
    if (password !== confirmPass) {
      showAuthAlert('Passwords do not match. Please verify.');
      return;
    }

    try {
      submitBtn.disabled = true;
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Registration failed');

      authToken = data.token;
      currentUser = data.user;
      localStorage.setItem('clauseclear_token', authToken);
      updateAuthUI();
      closeAuthModal();
      showToast(`Welcome to ClauseClear, ${currentUser.name}!`);
      loadUserHistory();
      executePendingAction();
    } catch (err) {
      showAuthAlert(err.message);
    } finally {
      submitBtn.disabled = false;
    }
  } else {
    // Login flow
    try {
      submitBtn.disabled = true;
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Invalid email or password');

      authToken = data.token;
      currentUser = data.user;
      localStorage.setItem('clauseclear_token', authToken);
      updateAuthUI();
      closeAuthModal();
      showToast(`Welcome back, ${currentUser.name}!`);
      loadUserHistory();
      executePendingAction();
    } catch (err) {
      showAuthAlert(err.message);
    } finally {
      submitBtn.disabled = false;
    }
  }
}

async function handleDemoLogin() {
  clearAuthAlert();
  try {
    const res = await fetch('/api/auth/demo-login', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Demo login failed');

    authToken = data.token;
    currentUser = data.user;
    localStorage.setItem('clauseclear_token', authToken);
    updateAuthUI();
    closeAuthModal();
    showToast('Signed in with Demo Account!');
    loadUserHistory();
    executePendingAction();
  } catch (err) {
    showAuthAlert(err.message);
  }
}

async function handleLogout() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } catch (err) {}

  authToken = null;
  currentUser = null;
  localStorage.removeItem('clauseclear_token');
  toggleUserDropdown(false);
  updateAuthUI();
  showToast('Signed out successfully.');
}

function updateSaveStatusBanner() {
  const banner = document.getElementById('analysis-save-status-banner');
  const iconBox = document.getElementById('save-status-icon-box');
  const text = document.getElementById('save-status-text');
  const subtext = document.getElementById('save-status-subtext');
  const action = document.getElementById('save-status-action');
  if (!banner || !text) return;

  if (currentUser) {
    banner.className = 'rounded-2xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2 border border-teal-100 bg-teal-50/60 shadow-xs transition-all';
    if (iconBox) iconBox.className = 'h-8 w-8 rounded-xl bg-teal-100 text-teal-800 flex items-center justify-center shrink-0 border border-teal-200';
    text.textContent = 'Analysis automatically saved to your personal history.';
    text.className = 'text-xs font-bold text-teal-900';
    if (subtext) subtext.textContent = 'You can review and compare this agreement anytime from My Contract History.';
    if (action) {
      action.innerHTML = `
        <button onclick="openHistoryModal()" class="px-3.5 py-1.5 rounded-xl bg-white hover:bg-teal-50 text-teal-800 text-xs font-bold border border-teal-200 shadow-xs transition-colors flex items-center space-x-1.5">
          <i data-lucide="history" class="w-3.5 h-3.5"></i>
          <span>View History</span>
        </button>
      `;
    }
  } else {
    banner.className = 'rounded-2xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2 border border-amber-200 bg-amber-50/70 shadow-xs transition-all';
    if (iconBox) iconBox.className = 'h-8 w-8 rounded-xl bg-amber-100 text-amber-800 flex items-center justify-center shrink-0 border border-amber-200';
    text.textContent = 'Guest Session: Analysis will be lost when page reloads.';
    text.className = 'text-xs font-bold text-amber-900';
    if (subtext) subtext.textContent = 'Sign in or create a free account to permanently save this contract evaluation.';
    if (action) {
      action.innerHTML = `
        <button onclick="openAuthModal('login')" class="px-3.5 py-1.5 rounded-xl bg-amber-600 hover:bg-amber-700 text-white text-xs font-bold shadow-xs transition-colors flex items-center space-x-1.5">
          <i data-lucide="log-in" class="w-3.5 h-3.5"></i>
          <span>Sign In to Save</span>
        </button>
      `;
    }
  }

  if (window.lucide) lucide.createIcons();
}

// ============================================================================
// CONTRACT HISTORY CONTROLLER
// ============================================================================

async function openHistoryModal() {
  if (!currentUser) {
    openAuthModal('login');
    showAuthAlert('Please sign in to view your saved contract history.', 'info');
    return;
  }

  const modal = document.getElementById('history-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  loadUserHistory();
  if (window.lucide) lucide.createIcons();
}

function closeHistoryModal() {
  const modal = document.getElementById('history-modal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

async function loadUserHistory() {
  if (!currentUser || !authToken) return;

  try {
    const res = await fetch('/api/user/history', {
      headers: { 'Authorization': `Bearer ${authToken}` }
    });
    if (!res.ok) throw new Error('Failed to fetch history');

    const data = await res.json();
    userHistoryCache = data.history || [];

    // Update counts across UI
    const count = userHistoryCache.length;
    const badgeSidebar = document.getElementById('sidebar-history-count');
    const badgeSubcount = document.getElementById('sidebar-history-subcount');
    const badgeDropdown = document.getElementById('dropdown-history-count');
    const badgeModal = document.getElementById('history-modal-badge');

    if (badgeSidebar) {
      badgeSidebar.textContent = count;
      badgeSidebar.classList.toggle('hidden', count === 0);
    }
    if (badgeSubcount) badgeSubcount.textContent = count;
    if (badgeDropdown) badgeDropdown.textContent = count;
    if (badgeModal) badgeModal.textContent = `${count} ${count === 1 ? 'Contract' : 'Contracts'}`;

    renderHistoryList(userHistoryCache);
  } catch (err) {
    console.error('Error loading history:', err);
    const container = document.getElementById('history-list-container');
    if (container) {
      container.innerHTML = `
        <div class="py-12 text-center text-red-600 space-y-2">
          <i data-lucide="alert-circle" class="w-8 h-8 mx-auto text-red-500"></i>
          <p class="text-xs font-semibold">Failed to load contract history.</p>
          <button onclick="loadUserHistory()" class="text-xs text-teal-700 underline font-medium">Try Again</button>
        </div>
      `;
      if (window.lucide) lucide.createIcons();
    }
  }
}

function renderHistoryList(history) {
  const container = document.getElementById('history-list-container');
  if (!container) return;

  if (!history || history.length === 0) {
    container.innerHTML = `
      <div class="py-16 text-center space-y-3">
        <div class="w-14 h-14 rounded-2xl bg-teal-50 text-teal-600 flex items-center justify-center mx-auto border border-teal-100 shadow-xs">
          <i data-lucide="file-text" class="w-7 h-7"></i>
        </div>
        <h4 class="text-sm font-bold text-[#111827]">No saved contracts yet</h4>
        <p class="text-xs text-[#6B7280] max-w-sm mx-auto">Upload or paste a contract in the Document Analyzer. Each completed analysis will automatically be saved to your account.</p>
        <button onclick="closeHistoryModal(); switchTab('analyzer');" class="btn-primary px-5 py-2.5 rounded-xl text-xs font-bold mt-2">
          Analyze a Contract Now
        </button>
      </div>
    `;
    if (window.lucide) lucide.createIcons();
    return;
  }

  let html = '<div class="space-y-3">';
  history.forEach(item => {
    const isHigh = item.overall_risk_score >= 65 || item.high_risk_count >= 2;
    const isMed = item.overall_risk_score >= 35 || item.high_risk_count === 1;

    let riskBadgeClass = 'bg-emerald-50 text-emerald-700 border-emerald-200';
    let riskLabel = 'Fair Terms';
    if (isHigh) {
      riskBadgeClass = 'bg-red-50 text-red-700 border-red-200';
      riskLabel = 'High Risk';
    } else if (isMed) {
      riskBadgeClass = 'bg-amber-50 text-amber-700 border-amber-200';
      riskLabel = 'Unusual Terms';
    }

    const dateStr = item.created_at ? formatTimestamp(item.created_at) : 'Recently analyzed';

    html += `
      <div class="surface-card history-card p-4 rounded-2xl border border-[#E5E7EB] bg-white flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xs">
        <div class="space-y-1.5 flex-1 min-w-0">
          <div class="flex items-center space-x-2.5 flex-wrap gap-y-1">
            <h4 class="text-xs sm:text-sm font-bold text-[#111827] truncate">${escapeQuotes(item.document_title)}</h4>
            <span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${riskBadgeClass}">
              ${item.overall_risk_score}/100 — ${riskLabel}
            </span>
          </div>
          <div class="flex items-center space-x-3 text-[11px] text-[#6B7280]">
            <span class="flex items-center space-x-1">
              <i data-lucide="layers" class="w-3 h-3 text-[#9CA3AF]"></i>
              <span>${item.total_clauses} clauses</span>
            </span>
            <span>•</span>
            <span class="flex items-center space-x-1 ${item.high_risk_count > 0 ? 'text-red-600 font-medium' : ''}">
              <i data-lucide="alert-triangle" class="w-3 h-3"></i>
              <span>${item.high_risk_count} red flags</span>
            </span>
            <span>•</span>
            <span class="text-[#9CA3AF]">${dateStr}</span>
          </div>
          ${item.summary_verdict ? `<p class="text-[11px] text-[#4B5563] line-clamp-1 italic mt-1">"${escapeQuotes(item.summary_verdict)}"</p>` : ''}
        </div>
        <div class="flex items-center space-x-2 shrink-0 pt-2 sm:pt-0 border-t sm:border-t-0 border-gray-100">
          <button onclick="restorePastAnalysis(${item.id})" class="px-3.5 py-1.5 rounded-xl bg-teal-50 hover:bg-teal-100 text-teal-800 text-xs font-bold border border-teal-200 transition-colors flex items-center space-x-1.5 shadow-xs">
            <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
            <span>Load in Analyzer</span>
          </button>
          <button onclick="deletePastAnalysis(${item.id}, event)" title="Delete from history" class="p-1.5 rounded-xl text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors">
            <i data-lucide="trash-2" class="w-4 h-4"></i>
          </button>
        </div>
      </div>
    `;
  });
  html += '</div>';

  container.innerHTML = html;
  if (window.lucide) lucide.createIcons();
}

function formatTimestamp(ts) {
  try {
    const d = new Date(ts);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch (e) {
    return ts;
  }
}

async function restorePastAnalysis(historyId) {
  try {
    const res = await fetch(`/api/user/history/${historyId}`, {
      headers: { 'Authorization': `Bearer ${authToken}` }
    });
    if (!res.ok) throw new Error('Could not retrieve saved analysis.');

    const record = await res.json();
    currentAnalysis = record.analysis;
    selectedClauseIndex = 0;

    closeHistoryModal();
    switchTab('analyzer');
    renderAnalysisResults(record.analysis);

    // Scroll smoothly to results
    const resultsEl = document.getElementById('results-dashboard');
    if (resultsEl) {
      resultsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    showToast(`Loaded: ${record.document_title}`);
  } catch (err) {
    alert(`Error loading analysis: ${err.message}`);
  }
}

async function deletePastAnalysis(historyId, event) {
  if (event) event.stopPropagation();
  if (!confirm('Are you sure you want to remove this contract from your saved history?')) {
    return;
  }

  try {
    const res = await fetch(`/api/user/history/${historyId}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${authToken}` }
    });
    if (!res.ok) throw new Error('Failed to delete history record.');

    showToast('Contract removed from history.');
    loadUserHistory();
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
}

// Modern Toast Notifications
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast-notification pointer-events-auto flex items-center space-x-2.5 px-4 py-3 rounded-2xl bg-[#111827] text-white text-xs font-semibold shadow-2xl border border-gray-700/50 backdrop-blur-md';

  const iconName = type === 'success' ? 'check-circle' : 'info';
  const iconColor = type === 'success' ? 'text-emerald-400' : 'text-teal-400';

  toast.innerHTML = `
    <i data-lucide="${iconName}" class="w-4 h-4 ${iconColor} shrink-0"></i>
    <span>${escapeQuotes(message)}</span>
  `;

  container.appendChild(toast);
  if (window.lucide) lucide.createIcons();

  setTimeout(() => {
    toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px) scale(0.95)';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}
