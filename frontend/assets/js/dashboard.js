// frontend/assets/js/dashboard.js
let activeMember = "self";
let scanMode = "report";
let selectedFiles = [];
let familyMembersCache = [];
let currentOpenReportId = null;
let currentOpenReportData = null;

window.addEventListener("DOMContentLoaded", () => {
  requireAuthOrGuest();
  lucide.createIcons();
  loadFamilyMembers();
});

function switchTab(tab) {
  ["scanner", "vault", "chat"].forEach((t) => {
    document.getElementById(`view-${t}`).classList.toggle("hidden", t !== tab);
    const dtBtn = document.getElementById(`dt-tab-${t}`);
    const mbBtn = document.getElementById(`mb-tab-${t}`);
    if (dtBtn) dtBtn.classList.toggle("active", t === tab);
    if (mbBtn) mbBtn.classList.toggle("active", t === tab);
  });
  if (tab === "vault") loadMemberTimeline(activeMember);
  lucide.createIcons();
}

function setScanMode(mode) {
  scanMode = mode;
  document.getElementById("mode-report").classList.toggle("active", mode === "report");
  document.getElementById("mode-rx").classList.toggle("active", mode === "prescription");
}

async function handleLanguageChange() {
  if (!currentOpenReportId) return;
  const newLang = document.getElementById("languageSelect").value;
  const loadingBox = document.getElementById("loadingBox");
  document.getElementById("loadingText").innerText = `Switching to ${newLang}...`;
  loadingBox.classList.remove("hidden");

  try {
    const res = await fetch(`/api/v1/vault/records/${currentOpenReportId}/translate?language=${encodeURIComponent(newLang)}`, {
      method: "POST",
    });
    const data = await res.json();
    if (res.ok) renderAnalysisResult(data, "resultsContainer");
  } finally {
    loadingBox.classList.add("hidden");
  }
}

async function loadFamilyMembers() {
  const res = await fetch("/api/v1/vault/members");
  const data = await res.json();
  familyMembersCache = data.family_members?.length
    ? data.family_members
    : [{ member_id: "self", display_name: "Self", relationship: "Self", total_records_stored: 0 }];
  renderFamilyPills();
}

function renderFamilyPills() {
  const container = document.getElementById("familyPillsContainer");
  let html = "";
  familyMembersCache.forEach((m) => {
    const isActive = m.member_id === activeMember;
    html += `
      <button onclick="selectMember('${m.member_id}')" class="family-pill ${isActive ? "active" : ""}">
        <span>${m.display_name}</span>
        <span class="pill-count">${m.total_records_stored || 0}</span>
      </button>`;
  });
  html += `<button onclick="openMemberModal()" class="family-pill" style="color:var(--primary-dark); background:var(--primary-soft);">+ Member</button>`;
  container.innerHTML = html;
  document.getElementById("activeMemberBadge").innerText = activeMember;
  document.getElementById("chatMemberBadge").innerText = activeMember;
}

function selectMember(memberId) {
  activeMember = memberId;
  renderFamilyPills();
  loadMemberTimeline(activeMember);
}

function handleFileSelect(e) {
  selectedFiles = Array.from(e.target.files).slice(0, 10);
  if (!selectedFiles.length) return;
  document.getElementById("selectedFilesBox").classList.remove("hidden");
  document.getElementById("filePills").innerHTML = selectedFiles
    .map((f, i) => `<span class="badge badge-teal">${i + 1}. ${f.name}</span>`)
    .join("");
}

async function submitAnalysis() {
  if (!selectedFiles.length) return;
  const lang = document.getElementById("languageSelect").value;
  const endpoint = scanMode === "report" ? "/api/v1/analyze-report" : "/api/v1/analyze-prescription";
  const formData = new FormData();
  selectedFiles.forEach((f) => formData.append("files", f));
  formData.append("member_id", activeMember);
  formData.append("language", lang);

  document.getElementById("loadingText").innerText = "Analyzing & saving original document to Vault...";
  document.getElementById("loadingBox").classList.remove("hidden");
  const container = document.getElementById("resultsContainer");
  container.classList.add("hidden");

  try {
    const res = await fetch(endpoint, { method: "POST", body: formData });
    const data = await res.json();

    if (!res.ok) {
      container.classList.remove("hidden");
      container.innerHTML = `
        <div class="card" style="background:var(--danger-soft); border-color:#FECACA;">
          <p style="font-size:0.85rem; font-weight:600; color:var(--danger);">
            ${data.detail || "Please upload a valid medical report or prescription."}
          </p>
        </div>`;
      return;
    }

    renderAnalysisResult(data, "resultsContainer");
    loadFamilyMembers();
  } catch (err) {
    alert("Error: " + err.message);
  } finally {
    document.getElementById("loadingBox").classList.add("hidden");
  }
}

function renderStoredDocumentsGallery(storedFiles) {
  const validFiles = (storedFiles || []).filter((f) => f && f.url);
  if (!validFiles.length) return "";

  return `
    <div style="padding-top:10px; border-top:1px solid var(--border);">
      <p style="font-size:0.74rem; font-weight:600; color:var(--text-muted); margin-bottom:8px;">
        📎 Original Uploaded Document (Click to view full screen for your Doctor):
      </p>
      <div style="display:flex; flex-wrap:wrap; gap:10px;">
        ${validFiles.map((f) =>
          f.is_pdf
            ? `<a href="${f.url}" target="_blank" class="btn btn-outline">📄 Open Original PDF (${f.filename})</a>`
            : `<a href="${f.url}" target="_blank" style="display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border:1px solid var(--border); border-radius:10px; background:#FAFAFA;">
                <img src="${f.url}" alt="${f.filename}" style="width:42px; height:42px; object-fit:cover; border-radius:6px; border:1px solid var(--border);" />
                <span style="font-size:0.76rem; font-weight:600; color:var(--primary-dark);">🖼️ View Original Image (${f.filename})</span>
              </a>`
        ).join("")}
      </div>
    </div>
  `;
}

function renderAnalysisResult(data, targetElementId = "resultsContainer") {
  currentOpenReportId = data.report_id || null;
  currentOpenReportData = data;

  const container = document.getElementById(targetElementId);
  container.classList.remove("hidden");
  const ai = data.ai_explanation || {};
  const isRx = ai.document_category === "prescription" || !!ai.medicines_decoded;

  let html = `
    <div class="card space-y">
      <div style="display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:8px;">
        <div>
          <span class="badge badge-teal">${ai.report_type || "Summary"}</span>
          ${data.date_uploaded ? `<span style="font-size:0.75rem; color:var(--text-muted); margin-left:8px;">📅 ${data.date_uploaded}</span>` : ""}
        </div>
        <div style="display:flex; gap:6px;">
          ${ai.voice_summary_script ? `
            <button onclick="speakOnDemand(this)" data-speech="${encodeURIComponent(ai.voice_summary_script)}" data-title="Summary" class="btn btn-soft">
              🔊 Listen
            </button>
          ` : ""}
          <button onclick="shareSummaryOnWhatsApp()" class="btn btn-outline">Share</button>
        </div>
      </div>
      <p style="font-size:0.98rem; font-weight:600;">${ai.overall_status || ""}</p>
      ${renderStoredDocumentsGallery(data.stored_files)}
    </div>
  `;

  if (!isRx) {
    const att = ai.attention_needed || [];
    if (att.length) {
      html += `
        <p style="font-size:0.76rem; font-weight:700; color:var(--danger); text-transform:uppercase;">Needs Attention (${att.length})</p>
        <div class="grid-2">
          ${att.map((item) => {
            const speech = `${item.item}. Your value: ${item.your_value}. Healthy range: ${item.healthy_normal_range}. ${item.simple_explanation}`;
            return `
              <div class="card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                  <strong style="font-size:0.9rem;">${item.item}</strong>
                  <button onclick="speakOnDemand(this)" data-speech="${encodeURIComponent(speech)}" data-title="${item.item}" class="btn-icon">🔈</button>
                </div>
                <div class="compare-box">
                  <div><span class="compare-label">Yours: </span><span class="compare-val-alert">${item.your_value}</span></div>
                  <div><span class="compare-label">Healthy: </span><span class="compare-val-healthy">${item.healthy_normal_range || "Standard"}</span></div>
                </div>
                <p style="font-size:0.8rem; color:var(--text-muted);">${item.simple_explanation}</p>
              </div>`;
          }).join("")}
        </div>`;
    }

    const norm = ai.jargon_and_normal_tests_decoded || [];
    if (norm.length) {
      html += `
        <p style="font-size:0.76rem; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Normal Results (${norm.length})</p>
        <div class="grid-2">
          ${norm.map((n) => {
            const speech = `${n.term_on_report}. ${n.meaning_in_simple_words}`;
            return `
              <div class="card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                  <strong style="font-size:0.86rem;">${n.term_on_report}</strong>
                  <button onclick="speakOnDemand(this)" data-speech="${encodeURIComponent(speech)}" data-title="${n.term_on_report}" class="btn-icon">🔈</button>
                </div>
                <p style="font-size:0.75rem; color:var(--success); font-weight:600; margin:4px 0;">
                  ${n.your_value || "Normal"} (Healthy: ${n.healthy_normal_range || "Normal"})
                </p>
                <p style="font-size:0.78rem; color:var(--text-muted);">${n.meaning_in_simple_words}</p>
              </div>`;
          }).join("")}
        </div>`;
    }
  } else {
    const meds = ai.medicines_decoded || [];
    html += `
      <div class="grid-2">
        ${meds.map((m) => {
          const speech = `${m.medicine_brand_name}. ${m.purpose_in_simple_words}. ${m.dosage_and_timing_decoded}.`;
          return `
            <div class="card space-y">
              <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div>
                  <strong style="font-size:0.92rem;">${m.medicine_brand_name}</strong>
                  <p style="font-size:0.75rem; color:var(--primary-dark);">${m.generic_salt_composition}</p>
                </div>
                <button onclick="speakOnDemand(this)" data-speech="${encodeURIComponent(speech)}" data-title="${m.medicine_brand_name}" class="btn-icon">🔈</button>
              </div>
              <p style="font-size:0.8rem; font-weight:600; color:var(--primary-dark);">🕒 ${m.dosage_and_timing_decoded}</p>
              <p style="font-size:0.8rem; color:var(--text-muted);">${m.purpose_in_simple_words}</p>
            </div>`;
        }).join("")}
      </div>`;
  }

  const questions = ai.questions_for_doctor || [];
  if (questions.length) {
    html += `
      <div class="card space-y">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <strong style="font-size:0.85rem;">Questions to Ask Your Doctor</strong>
          <button onclick="speakOnDemand(this)" data-speech="${encodeURIComponent(questions.join('. '))}" data-title="Questions" class="btn-icon">🔈</button>
        </div>
        <ul style="padding-left:18px; font-size:0.82rem; color:var(--text-muted);" class="space-y">
          ${questions.map((q) => `<li>${q}</li>`).join("")}
        </ul>
        <p style="font-size:0.72rem; color:var(--text-muted);">${ai.disclaimer || ""}</p>
      </div>`;
  }

  container.innerHTML = html;
}

// FAMILY VAULT TIMELINE: Shows Date, Original Images/PDFs, and Opens Full Report Inline!
async function loadMemberTimeline(memberId) {
  const res = await fetch(`/api/v1/vault/members/${memberId}/timeline`);
  const data = await res.json();
  const p = data.member_profile || {};
  document.getElementById("vaultAvatar").innerText = (p.display_name || memberId)[0].toUpperCase();
  document.getElementById("vaultMemberName").innerText = p.display_name || memberId;
  document.getElementById("vaultMemberRelation").innerText = p.relationship || "Family";
  document.getElementById("vaultMemberMeta").innerText = `Age: ${p.age || "--"} • Gender: ${p.gender || "--"} • Blood: ${p.blood_group || "--"}`;
  document.getElementById("vaultMemberConditions").innerText = p.known_conditions || "";

  const list = document.getElementById("vaultTimelineList");
  const items = data.timeline || [];
  if (!items.length) {
    list.innerHTML = `<p style="font-size:0.82rem; color:var(--text-muted); text-align:center; padding:24px;">No health records stored for ${p.display_name || memberId} yet.</p>`;
    return;
  }

  list.innerHTML = items.map((r) => `
    <div class="card space-y" style="background:#FAFAFA;">
      <div style="display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:10px;">
        <div>
          <div style="display:flex; align-items:center; gap:8px;">
            <span class="badge badge-teal">${r.category === "prescription" ? "Prescription" : "Lab Report"}</span>
            <span style="font-size:0.76rem; font-weight:600; color:var(--text-muted);">📅 ${r.date_uploaded}</span>
          </div>
          <h4 style="font-size:0.96rem; font-weight:700; margin-top:6px;">${r.report_type}</h4>
          <p style="font-size:0.82rem; color:var(--text-muted); margin-top:2px;">${r.overall_status}</p>
        </div>
        <div style="display:flex; gap:6px;">
          <button onclick="toggleInlineVaultReport('${r.report_id}')" class="btn btn-primary">View Full Report</button>
          <button onclick="deleteVaultRecord('${r.report_id}')" class="btn btn-outline" style="color:var(--danger);">Delete</button>
        </div>
      </div>

      ${renderStoredDocumentsGallery(r.stored_files)}

      <!-- Inline Full Report Container right inside the Vault! -->
      <div id="vault-detail-${r.report_id}" class="hidden space-y" style="padding-top:12px; border-top:1px solid var(--border);"></div>
    </div>
  `).join("");
}

async function toggleInlineVaultReport(reportId) {
  const detailBox = document.getElementById(`vault-detail-${reportId}`);
  if (!detailBox.classList.contains("hidden")) {
    detailBox.classList.add("hidden");
    return;
  }
  const lang = document.getElementById("languageSelect").value;
  detailBox.classList.remove("hidden");
  detailBox.innerHTML = `<p style="font-size:0.8rem; color:var(--text-muted);">Loading full report...</p>`;

  const res = await fetch(`/api/v1/vault/records/${reportId}?language=${encodeURIComponent(lang)}`);
  const data = await res.json();
  renderAnalysisResult(data, `vault-detail-${reportId}`);
}

async function deleteVaultRecord(reportId) {
  if (!confirm("Delete this record from your Family Vault?")) return;
  await fetch(`/api/v1/vault/records/${reportId}`, { method: "DELETE" });
  loadMemberTimeline(activeMember);
  loadFamilyMembers();
}

function shareSummaryOnWhatsApp() {
  if (!currentOpenReportData) return;
  const ai = currentOpenReportData.ai_explanation || {};
  const text = `*${ai.report_type || "Health Summary"}*\n${ai.overall_status || ""}\n\n*Questions for Doctor:*\n${(ai.questions_for_doctor || []).map((q) => "• " + q).join("\n")}`;
  window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank");
}

async function speakOnDemand(btnEl) {
  const text = decodeURIComponent(btnEl.getAttribute("data-speech") || "");
  const title = btnEl.getAttribute("data-title") || "Audio";
  const language = document.getElementById("languageSelect").value;
  if (!text) return;
  btnEl.disabled = true;
  try {
    const res = await fetch("/api/v1/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language }),
    });
    const data = await res.json();
    const bar = document.getElementById("audioPlayerBar");
    const audio = document.getElementById("globalAudio");
    document.getElementById("audioBarTitle").innerText = `${title} (${language})`;
    audio.src = data.play_url;
    bar.classList.remove("hidden");
    audio.play();
  } finally {
    btnEl.disabled = false;
  }
}

function closeAudioBar() {
  document.getElementById("globalAudio").pause();
  document.getElementById("audioPlayerBar").classList.add("hidden");
}

function openMemberModal() { document.getElementById("memberModal").classList.remove("hidden"); }
function closeMemberModal() { document.getElementById("memberModal").classList.add("hidden"); }

async function saveFamilyMember() {
  const payload = {
    member_id: document.getElementById("m_id").value.trim() || "self",
    display_name: document.getElementById("m_name").value.trim() || "Self",
    relationship: document.getElementById("m_rel").value.trim() || "Family",
    age: document.getElementById("m_age").value.trim(),
    gender: document.getElementById("m_gender").value.trim(),
    blood_group: document.getElementById("m_bg").value.trim(),
    known_conditions: document.getElementById("m_cond").value.trim(),
  };
  await fetch("/api/v1/vault/members", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  activeMember = payload.member_id.toLowerCase();
  closeMemberModal();
  loadFamilyMembers();
  loadMemberTimeline(activeMember);
}

async function submitQuestion() {
  const q = document.getElementById("chatInput").value.trim();
  if (!q) return;
  const language = document.getElementById("languageSelect").value;
  const use_past_history = document.getElementById("useHistoryToggle").checked;
  const box = document.getElementById("chatResponseContainer");
  box.innerHTML = `<p style="font-size:0.8rem; color:var(--text-muted);">Thinking...</p>`;

  try {
    const res = await fetch("/api/v1/ask-question", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, member_id: activeMember, language, use_past_history }),
    });
    const data = await res.json();

    if (!res.ok) {
      box.innerHTML = `
        <div class="card" style="background:var(--danger-soft); border-color:#FECACA;">
          <p style="font-size:0.85rem; font-weight:600; color:var(--danger);">
            ${data.detail || "Please ask questions related to health, symptoms, or medical reports."}
          </p>
        </div>`;
      return;
    }

    const r = data.response || {};
    const reasons = r.possible_reasons || [];
    const historyNote = r.found_in_past_history
      ? `Connected to past history: ${r.past_history_connection}`
      : `Not in past history • General medical guidance`;

    box.innerHTML = `
      <div class="card space-y">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span class="badge badge-teal">${historyNote}</span>
          ${r.voice_script ? `<button onclick="speakOnDemand(this)" data-speech="${encodeURIComponent(r.voice_script)}" data-title="Answer" class="btn-icon">🔈</button>` : ""}
        </div>

        <p style="font-size:0.92rem; font-weight:600;">${r.direct_answer || ""}</p>

        ${reasons.length ? `
          <ul style="padding-left:18px; font-size:0.82rem; color:var(--text-muted);" class="space-y">
            ${reasons.map((item) => `<li>${item}</li>`).join("")}
          </ul>
        ` : ""}

        <div style="padding-top:10px; border-top:1px solid var(--border); font-size:0.78rem; color:var(--text-muted); display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px;">
          <span><strong>Consult:</strong> ${r.which_doctor_to_consult || "General Physician"}</span>
          <span>${r.disclaimer || "Please consult a doctor."}</span>
        </div>
      </div>`;
  } catch (err) {
    box.innerHTML = `<p style="font-size:0.8rem; color:var(--danger);">Error: ${err.message}</p>`;
  }
}