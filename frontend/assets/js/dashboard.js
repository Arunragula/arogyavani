// frontend/assets/js/dashboard.js
let currentSession = null;
let activeMember = "self";
let scanMode = "report";
let selectedFiles = [];
let familyMembersCache = [];
let currentOpenReportId = null;
let currentOpenReportData = null;

window.addEventListener("DOMContentLoaded", () => {
  currentSession = requireAuthOrRedirect();
  if (!currentSession) return;

  // Hide upload card if user has 'viewer' role
  if (currentSession.role === "viewer") {
    document.getElementById("uploadCardBox")?.classList.add("hidden");
    document.getElementById("editMemberBtn")?.classList.add("hidden");
    switchTab("vault");
  }
  if (currentSession.role === "owner") {
    document.getElementById("manageRolesBtn")?.classList.remove("hidden");
  }

  lucide.createIcons();
  loadFamilyMembers();

  // Close modals on Escape key
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeMemberModal();
      closeRolesModal();
      closeDocPreviewModal();
    }
  });
});

function isRtlLanguage(lang) {
  const l = (lang || "").toLowerCase();
  return l.includes("arabic") || l.includes("urdu");
}

function switchTab(tab) {
  ["scanner", "vault", "chat"].forEach((t) => {
    document.getElementById(`view-${t}`).classList.toggle("hidden", t !== tab);
    document.getElementById(`dt-tab-${t}`)?.classList.toggle("active", t === tab);
    document.getElementById(`mb-tab-${t}`)?.classList.toggle("active", t === tab);
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
  document.getElementById("loadingText").textContent = `Translating into ${newLang}...`;
  loadingBox.classList.remove("hidden");

  try {
    const res = await apiFetch(
      `/api/v1/vault/records/${encodeURIComponent(currentOpenReportId)}/translate?language=${encodeURIComponent(newLang)}`,
      { method: "POST" }
    );
    const data = await res.json();
    if (res.ok) renderAnalysisResult(data, "resultsContainer");
  } finally {
    loadingBox.classList.add("hidden");
  }
}

async function loadFamilyMembers() {
  const res = await apiFetch("/api/v1/vault/members");
  if (!res.ok) return;
  const data = await res.json();
  familyMembersCache = data.family_members?.length
    ? data.family_members
    : [{ member_id: "self", display_name: "Self", relationship: "Self", total_records_stored: 0 }];

  if (!familyMembersCache.some((m) => m.member_id === activeMember)) {
    activeMember = familyMembersCache[0].member_id;
  }
  renderFamilyPills();
}

function renderFamilyPills() {
  const container = document.getElementById("familyPillsContainer");
  container.innerHTML = "";

  familyMembersCache.forEach((m) => {
    const btn = document.createElement("button");
    btn.className = `family-pill ${m.member_id === activeMember ? "active" : ""}`;
    btn.innerHTML = `<span>${escapeHtml(m.display_name)}</span><span class="pill-count">${Number(m.total_records_stored || 0)}</span>`;
    btn.addEventListener("click", () => selectMember(m.member_id));
    container.appendChild(btn);
  });

  if (currentSession?.role !== "viewer") {
    const addBtn = document.createElement("button");
    addBtn.className = "family-pill";
    addBtn.style.color = "var(--primary-dark)";
    addBtn.style.background = "var(--primary-soft)";
    addBtn.textContent = "+ Member";
    addBtn.addEventListener("click", openMemberModal);
    container.appendChild(addBtn);
  }

  document.getElementById("activeMemberBadge").textContent = activeMember;
  document.getElementById("chatMemberBadge").textContent = activeMember;
}

function selectMember(memberId) {
  activeMember = memberId;
  renderFamilyPills();
  loadMemberTimeline(activeMember);
}

function handleFileSelect(e) {
  selectedFiles = Array.from(e.target.files).slice(0, 5);
  if (!selectedFiles.length) return;
  document.getElementById("selectedFilesBox").classList.remove("hidden");
  document.getElementById("filePills").innerHTML = selectedFiles
    .map((f, i) => `<span class="badge badge-teal">${i + 1}. ${escapeHtml(f.name)}</span>`)
    .join("");
}

async function submitAnalysis() {
  if (!selectedFiles.length) return;
  const consent = document.getElementById("privacyConsentCheck").checked;
  const saveVault = document.getElementById("saveToVaultCheck").checked;
  const errBox = document.getElementById("scannerErrorBox");
  const errText = document.getElementById("scannerErrorText");

  if (!consent) {
    errText.textContent = "Please check the Privacy & Educational Consent box before decoding.";
    errBox.classList.remove("hidden");
    return;
  }

  errBox.classList.add("hidden");
  const lang = document.getElementById("languageSelect").value;
  const endpoint = scanMode === "report" ? "/api/v1/analyze-report" : "/api/v1/analyze-prescription";
  const formData = new FormData();
  selectedFiles.forEach((f) => formData.append("files", f));
  formData.append("member_id", activeMember);
  formData.append("language", lang);
  formData.append("privacy_consent", consent);
  formData.append("save_to_vault", saveVault);

  const loadingBox = document.getElementById("loadingBox");
  const loadingText = document.getElementById("loadingText");
  loadingBox.classList.remove("hidden");
  document.getElementById("resultsContainer").classList.add("hidden");

  const steps = [
    "1/4 Reading document & tables...",
    "2/4 Reducing personal identifiers locally...",
    "3/4 Analyzing medical values & healthy ranges...",
    "4/4 Compressing & encrypting with your vault key...",
  ];
  let stepIdx = 0;
  loadingText.textContent = steps[0];
  const stepTimer = setInterval(() => {
    stepIdx = Math.min(stepIdx + 1, steps.length - 1);
    loadingText.textContent = steps[stepIdx];
  }, 1600);

  try {
    const res = await apiFetch(endpoint, { method: "POST", body: formData });
    const data = await res.json();

    if (!res.ok) {
      errText.textContent = data.detail || "Could not process this document.";
      errBox.classList.remove("hidden");
      return;
    }

    renderAnalysisResult(data, "resultsContainer");
    loadFamilyMembers();
  } catch (err) {
    errText.textContent = err.message;
    errBox.classList.remove("hidden");
  } finally {
    clearInterval(stepTimer);
    loadingBox.classList.add("hidden");
  }
}

// DECRYPTED ORIGINAL IMAGE / PDF VIEWER
async function viewEncryptedVaultFile(reportId, fileId, filename, isPdf) {
  const modal = document.getElementById("docPreviewModal");
  const title = document.getElementById("docPreviewTitle");
  const body = document.getElementById("docPreviewBody");

  title.textContent = filename || "Original Document";
  body.innerHTML = `<p style="font-size:0.82rem; color:var(--text-muted); padding:20px;">Decrypting document in memory...</p>`;
  modal.classList.remove("hidden");

  try {
    const res = await apiFetch(
      `/api/v1/vault/records/${encodeURIComponent(reportId)}/files/${encodeURIComponent(fileId)}`
    );
    if (!res.ok) throw new Error("Could not decrypt file.");
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);

    if (isPdf) {
      body.innerHTML = `<iframe src="${blobUrl}" style="width:100%; height:70vh; border:none; border-radius:8px;"></iframe>`;
    } else {
      body.innerHTML = `<img src="${blobUrl}" alt="${escapeHtml(filename)}" style="max-width:100%; border-radius:10px; border:1px solid var(--border);" />`;
    }
  } catch (err) {
    body.innerHTML = `<p style="color:var(--danger); font-size:0.82rem;">${escapeHtml(err.message)}</p>`;
  }
}

function closeDocPreviewModal() {
  document.getElementById("docPreviewModal").classList.add("hidden");
  document.getElementById("docPreviewBody").innerHTML = "";
}

function renderEncryptedFilesBar(reportId, storedFiles) {
  const valid = (storedFiles || []).filter((f) => f && f.file_id);
  if (!valid.length || !reportId) return "";

  return `
    <div style="padding-top:10px; border-top:1px solid var(--border); display:flex; flex-wrap:wrap; align-items:center; gap:8px;">
      <span style="font-size:0.74rem; color:var(--text-muted); font-weight:600;">🔒 Original Document (Encrypted):</span>
      ${valid
        .map(
          (f) => `
          <button type="button" class="btn btn-outline js-view-file"
            data-report="${escapeHtml(reportId)}"
            data-file="${escapeHtml(f.file_id)}"
            data-name="${escapeHtml(f.filename)}"
            data-pdf="${f.is_pdf ? '1' : '0'}"
            style="padding:4px 10px; font-size:0.74rem;">
            🖼️ View ${escapeHtml(f.filename)} (${Number(f.size_kb || 0)} KB)
          </button>`
        )
        .join("")}
    </div>
  `;
}

function renderDecodedMedicinesList(meds) {
  if (!meds || !meds.length) return "";
  return `
    <div class="grid-2">
      ${meds
        .map((m) => {
          const speech = `${m.medicine_brand_name}. Active salt: ${m.generic_salt_composition}. Purpose: ${m.purpose_in_simple_words}. Timing: ${m.dosage_and_timing_decoded}.`;
          const lowConf = (m.read_confidence || "").includes("low");
          return `
            <div class="card space-y">
              <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div>
                  <strong style="font-size:0.92rem;">${escapeHtml(m.medicine_brand_name)}</strong>
                  <p style="font-size:0.75rem; color:var(--primary-dark);">${escapeHtml(m.generic_salt_composition)}</p>
                </div>
                <button type="button" class="btn-icon js-speak-btn" aria-label="Listen" data-speech="${encodeURIComponent(speech)}" data-title="${escapeHtml(m.medicine_brand_name)}">🔈</button>
              </div>
              ${lowConf ? `<p style="font-size:0.72rem; color:var(--danger); font-weight:600;">⚠️ Handwriting unclear — verify spelling with a pharmacist.</p>` : ""}
              <p style="font-size:0.8rem; font-weight:600; color:var(--primary-dark);">🕒 ${escapeHtml(m.dosage_and_timing_decoded)}</p>
              <p style="font-size:0.78rem; color:var(--text-muted);">${escapeHtml(m.purpose_in_simple_words)}</p>
              <p style="font-size:0.74rem; color:var(--text-muted);"><strong>Precaution:</strong> ${escapeHtml(m.food_and_safety_precautions)}</p>
            </div>`;
        })
        .join("")}
    </div>
  `;
}

// RENDER FULL REPORT + ATTACHED PRESCRIPTIONS SECTION
function renderAnalysisResult(data, targetElementId = "resultsContainer") {
  currentOpenReportId = data.report_id || null;
  currentOpenReportData = data;

  const container = document.getElementById(targetElementId);
  container.classList.remove("hidden");
  const lang = data.selected_language || document.getElementById("languageSelect").value;
  container.dir = isRtlLanguage(lang) ? "rtl" : "ltr";

  const ai = data.ai_explanation || {};
  const isRx = ai.document_category === "prescription" || !!ai.medicines_decoded;
  const att = ai.attention_needed || [];
  const hasCritical = att.some((x) => (x.severity || "").toLowerCase() === "critical");

  let html = "";

  // Urgent Banner for Critical Findings
  if (hasCritical) {
    html += `
      <div class="card" style="background:var(--danger-soft); border-color:#FECACA;">
        <strong style="font-size:0.85rem; color:var(--danger);">🚨 Critical Finding Detected:</strong>
        <p style="font-size:0.78rem; color:var(--danger); margin-top:2px;">
          One or more results are marked critical. Please consult a qualified doctor promptly.
        </p>
      </div>`;
  }

  // Summary Card
  html += `
    <div class="card space-y">
      <div style="display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:8px;">
        <div>
          <span class="badge badge-teal">${escapeHtml(ai.report_type || "Medical Summary")}</span>
          ${data.date_uploaded ? `<span style="font-size:0.74rem; color:var(--text-muted); margin-left:6px;">📅 ${escapeHtml(data.date_uploaded)}</span>` : ""}
        </div>
        <div style="display:flex; gap:6px;">
          ${ai.voice_summary_script ? `
            <button type="button" class="btn btn-soft js-speak-btn" data-speech="${encodeURIComponent(ai.voice_summary_script)}" data-title="Summary">
              🔊 Listen
            </button>` : ""}
          <button type="button" onclick="shareSummaryOnWhatsApp()" class="btn btn-outline">Share</button>
        </div>
      </div>
      <p style="font-size:0.96rem; font-weight:600;">${escapeHtml(ai.overall_status || "")}</p>
      ${renderEncryptedFilesBar(data.report_id, data.stored_files)}
    </div>
  `;

  if (!isRx) {
    if (att.length) {
      html += `
        <p style="font-size:0.76rem; font-weight:700; color:var(--danger); text-transform:uppercase;">Needs Attention (${att.length})</p>
        <div class="grid-2">
          ${att
            .map((item) => {
              const isCrit = (item.severity || "").toLowerCase() === "critical";
              const speech = `${item.item}. Your value: ${item.your_value}. Healthy range: ${item.healthy_normal_range}. ${item.simple_explanation}`;
              return `
                <div class="card">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                      <span class="badge ${isCrit ? 'badge-danger' : 'badge-teal'}">${isCrit ? '🔴 Critical' : '⚠️ Borderline'}</span>
                      <strong style="font-size:0.9rem; display:block; margin-top:4px;">${escapeHtml(item.item)}</strong>
                    </div>
                    <button type="button" class="btn-icon js-speak-btn" aria-label="Listen" data-speech="${encodeURIComponent(speech)}" data-title="${escapeHtml(item.item)}">🔈</button>
                  </div>
                  <div class="compare-box">
                    <div><span class="compare-label">Yours: </span><span class="compare-val-alert">${escapeHtml(item.your_value)}</span></div>
                    <div><span class="compare-label">Healthy: </span><span class="compare-val-healthy">${escapeHtml(item.healthy_normal_range || "Standard")}</span></div>
                  </div>
                  <p style="font-size:0.78rem; color:var(--text-muted);">${escapeHtml(item.simple_explanation)}</p>
                </div>`;
            })
            .join("")}
        </div>`;
    }

    const norm = ai.jargon_and_normal_tests_decoded || [];
    if (norm.length) {
      html += `
        <p style="font-size:0.76rem; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Normal Results (${norm.length})</p>
        <div class="grid-2">
          ${norm
            .map((n) => {
              const speech = `${n.term_on_report}. ${n.meaning_in_simple_words}`;
              return `
                <div class="card">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong style="font-size:0.86rem;">✓ ${escapeHtml(n.term_on_report)}</strong>
                    <button type="button" class="btn-icon js-speak-btn" aria-label="Listen" data-speech="${encodeURIComponent(speech)}" data-title="${escapeHtml(n.term_on_report)}">🔈</button>
                  </div>
                  <p style="font-size:0.75rem; color:var(--success); font-weight:600; margin:4px 0;">
                    ${escapeHtml(n.your_value || "Normal")} (Healthy: ${escapeHtml(n.healthy_normal_range || "Normal")})
                  </p>
                  <p style="font-size:0.78rem; color:var(--text-muted);">${escapeHtml(n.meaning_in_simple_words)}</p>
                </div>`;
            })
            .join("")}
        </div>`;
    }
  } else {
    html += renderDecodedMedicinesList(ai.medicines_decoded || []);
  }

  // Questions for Doctor
  const questions = ai.questions_for_doctor || [];
  if (questions.length) {
    html += `
      <div class="card space-y">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <strong style="font-size:0.85rem;">🩺 Questions to Ask Your Doctor</strong>
          <button type="button" class="btn-icon js-speak-btn" aria-label="Listen" data-speech="${encodeURIComponent(questions.join('. '))}" data-title="Questions">🔈</button>
        </div>
        <ul style="padding-left:18px; font-size:0.8rem; color:var(--text-muted);" class="space-y">
          ${questions.map((q) => `<li>${escapeHtml(q)}</li>`).join("")}
        </ul>
        <p style="font-size:0.72rem; color:var(--text-muted);">${escapeHtml(ai.disclaimer || "")}</p>
      </div>`;
  }

  // LINKED PRESCRIPTIONS SECTION BELOW LAB REPORT!
  if (!isRx && data.report_id) {
    const attachedList = data.attached_prescriptions || [];
    html += `
      <div class="card space-y" style="background:#F9FAFB; border-style:dashed;">
        <div style="display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:10px;">
          <div>
            <strong style="font-size:0.88rem; color:var(--primary-dark);">💊 Prescribed Medicines for This Report (${attachedList.length})</strong>
            <p style="font-size:0.74rem; color:var(--text-muted);">Upload the prescription or medicine strips given by your doctor for this report so they stay linked together.</p>
          </div>
          ${currentSession?.role !== "viewer" ? `
            <label class="btn btn-soft" style="cursor:pointer;">
              ➕ Attach Prescription / Medicine Strip
              <input type="file" multiple accept="image/*,application/pdf" class="hidden js-attach-rx-input" data-report="${escapeHtml(data.report_id)}" data-target="${escapeHtml(targetElementId)}" />
            </label>
          ` : ""}
        </div>

        ${attachedList
          .map(
            (rx, idx) => `
            <div class="space-y" style="padding-top:12px; border-top:1px solid var(--border);">
              <span class="badge badge-teal">Attached Prescription #${idx + 1}</span>
              <p style="font-size:0.84rem; font-weight:600;">${escapeHtml(rx.prescription_guide?.overall_status || "")}</p>
              ${renderEncryptedFilesBar(data.report_id, rx.stored_files)}
              ${renderDecodedMedicinesList(rx.prescription_guide?.medicines_decoded || [])}
            </div>`
          )
          .join("")}
      </div>
    `;
  }

  container.innerHTML = html;
  bindDynamicCardEvents(container);
}

function bindDynamicCardEvents(rootEl) {
  rootEl.querySelectorAll(".js-speak-btn").forEach((btn) => {
    btn.addEventListener("click", () => speakOnDemand(btn));
  });
  rootEl.querySelectorAll(".js-view-file").forEach((btn) => {
    btn.addEventListener("click", () => {
      viewEncryptedVaultFile(
        btn.getAttribute("data-report"),
        btn.getAttribute("data-file"),
        btn.getAttribute("data-name"),
        btn.getAttribute("data-pdf") === "1"
      );
    });
  });
  rootEl.querySelectorAll(".js-attach-rx-input").forEach((input) => {
    input.addEventListener("change", (e) => {
      attachPrescriptionToReport(
        input.getAttribute("data-report"),
        Array.from(e.target.files).slice(0, 5),
        input.getAttribute("data-target")
      );
    });
  });
}

async function attachPrescriptionToReport(reportId, files, targetElementId) {
  if (!files.length) return;
  const lang = document.getElementById("languageSelect").value;
  const formData = new FormData();
  files.forEach((f) => formData.append("files", f));
  formData.append("language", lang);

  const res = await apiFetch(`/api/v1/vault/records/${encodeURIComponent(reportId)}/attach-prescription`, {
    method: "POST",
    body: formData,
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Could not attach prescription.");
    return;
  }
  // Reload the full unified report with its newly attached prescription
  const updatedRes = await apiFetch(`/api/v1/vault/records/${encodeURIComponent(reportId)}?language=${encodeURIComponent(lang)}`);
  const updatedData = await updatedRes.json();
  renderAnalysisResult(updatedData, targetElementId);
}

// FAMILY VAULT TIMELINE
async function loadMemberTimeline(memberId) {
  const res = await apiFetch(`/api/v1/vault/members/${encodeURIComponent(memberId)}/timeline`);
  if (!res.ok) return;
  const data = await res.json();
  const p = data.member_profile || {};
  document.getElementById("vaultAvatar").textContent = (p.display_name || memberId)[0].toUpperCase();
  document.getElementById("vaultMemberName").textContent = p.display_name || memberId;
  document.getElementById("vaultMemberRelation").textContent = p.relationship || "Family";
  document.getElementById("vaultMemberMeta").textContent = `Age: ${p.age || "--"} • Gender: ${p.gender || "--"} • Blood: ${p.blood_group || "--"}`;
  document.getElementById("vaultMemberConditions").textContent = p.known_conditions || "";

  const list = document.getElementById("vaultTimelineList");
  const items = data.timeline || [];
  if (!items.length) {
    list.innerHTML = `<p style="font-size:0.8rem; color:var(--text-muted); text-align:center; padding:20px;">No encrypted records stored for ${escapeHtml(p.display_name || memberId)} yet.</p>`;
    return;
  }

  list.innerHTML = items
    .map(
      (r) => `
    <div class="card space-y" style="background:#FAFAFA;">
      <div style="display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:10px;">
        <div>
          <div style="display:flex; align-items:center; gap:6px;">
            <span class="badge badge-teal">${r.category === "prescription" ? "Prescription" : "Lab Report"}</span>
            ${r.attached_prescriptions_count > 0 ? `<span class="badge badge-success">💊 +${Number(r.attached_prescriptions_count)} Linked Rx</span>` : ""}
            <span style="font-size:0.74rem; color:var(--text-muted);">📅 ${escapeHtml(r.date_uploaded)}</span>
          </div>
          <h4 style="font-size:0.94rem; font-weight:700; margin-top:4px;">${escapeHtml(r.report_type)}</h4>
          <p style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(r.overall_status)}</p>
        </div>
        <div style="display:flex; gap:6px;">
          <button type="button" class="btn btn-primary js-toggle-vault-report" data-report="${escapeHtml(r.report_id)}">View Full Report</button>
          ${currentSession?.role === "owner" ? `<button type="button" class="btn btn-outline js-delete-vault-report" data-report="${escapeHtml(r.report_id)}" style="color:var(--danger);">Delete</button>` : ""}
        </div>
      </div>
      ${renderEncryptedFilesBar(r.report_id, r.stored_files)}
      <div id="vault-detail-${escapeHtml(r.report_id)}" class="hidden space-y" style="padding-top:12px; border-top:1px solid var(--border);"></div>
    </div>`
    )
    .join("");

  bindDynamicCardEvents(list);
  list.querySelectorAll(".js-toggle-vault-report").forEach((btn) => {
    btn.addEventListener("click", () => toggleInlineVaultReport(btn.getAttribute("data-report")));
  });
  list.querySelectorAll(".js-delete-vault-report").forEach((btn) => {
    btn.addEventListener("click", () => deleteVaultRecord(btn.getAttribute("data-report")));
  });
}

async function toggleInlineVaultReport(reportId) {
  const detailBox = document.getElementById(`vault-detail-${reportId}`);
  if (!detailBox.classList.contains("hidden")) {
    detailBox.classList.add("hidden");
    return;
  }
  const lang = document.getElementById("languageSelect").value;
  detailBox.classList.remove("hidden");
  detailBox.innerHTML = `<p style="font-size:0.8rem; color:var(--text-muted);">Decrypting & loading report...</p>`;

  const res = await apiFetch(`/api/v1/vault/records/${encodeURIComponent(reportId)}?language=${encodeURIComponent(lang)}`);
  const data = await res.json();
  renderAnalysisResult(data, `vault-detail-${reportId}`);
}

async function deleteVaultRecord(reportId) {
  if (!confirm("Permanently delete this encrypted record and its files?")) return;
  await apiFetch(`/api/v1/vault/records/${encodeURIComponent(reportId)}`, { method: "DELETE" });
  loadMemberTimeline(activeMember);
  loadFamilyMembers();
}

// IN-MEMORY VOICE AUDIO STREAM PLAYER
async function speakOnDemand(btnEl) {
  const text = decodeURIComponent(btnEl.getAttribute("data-speech") || "");
  const title = btnEl.getAttribute("data-title") || "Audio";
  const language = document.getElementById("languageSelect").value;
  if (!text) return;
  btnEl.disabled = true;
  try {
    const res = await apiFetch("/api/v1/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language }),
    });
    if (!res.ok) throw new Error("Voice limit reached or unavailable.");
    const audioBlob = await res.blob();
    const audioUrl = URL.createObjectURL(audioBlob);

    const bar = document.getElementById("audioPlayerBar");
    const audio = document.getElementById("globalAudio");
    document.getElementById("audioBarTitle").textContent = `${title} (${language})`;
    audio.src = audioUrl;
    bar.classList.remove("hidden");
    audio.play();
  } catch (e) {
    alert(e.message);
  } finally {
    btnEl.disabled = false;
  }
}

function closeAudioBar() {
  document.getElementById("globalAudio").pause();
  document.getElementById("audioPlayerBar").classList.add("hidden");
}

function shareSummaryOnWhatsApp() {
  if (!currentOpenReportData) return;
  const ai = currentOpenReportData.ai_explanation || {};
  const text = `*${ai.report_type || "Health Summary"}*\n${ai.overall_status || ""}\n\n*Questions for Doctor:*\n${(ai.questions_for_doctor || []).map((q) => "• " + q).join("\n")}`;
  window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank");
}

// FAMILY MEMBER MODAL
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
  await apiFetch("/api/v1/vault/members", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  activeMember = payload.member_id.toLowerCase();
  closeMemberModal();
  loadFamilyMembers();
  loadMemberTimeline(activeMember);
}

// FAMILY VAULT ROLE MANAGEMENT MODAL (OWNER ONLY)
function openRolesModal() {
  document.getElementById("rolesModal").classList.remove("hidden");
  loadHouseholdRoles();
}
function closeRolesModal() {
  document.getElementById("rolesModal").classList.add("hidden");
}

async function loadHouseholdRoles() {
  const box = document.getElementById("rolesListBox");
  const res = await apiFetch("/api/v1/vault/roles");
  if (!res.ok) return;
  const data = await res.json();
  box.innerHTML = (data.roles || [])
    .map(
      (r) => `
      <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 10px; border:1px solid var(--border); border-radius:8px; font-size:0.78rem;">
        <div>
          <strong>${escapeHtml(r.label)}</strong>
          <span class="badge badge-teal" style="margin-left:6px;">${escapeHtml(r.role)} (${escapeHtml(r.allowed_member_id)})</span>
        </div>
        ${r.role !== "owner" ? `<button type="button" class="btn btn-outline js-revoke-role" data-id="${escapeHtml(r.role_id)}" style="padding:3px 8px; font-size:0.72rem; color:var(--danger);">Revoke</button>` : ""}
      </div>`
    )
    .join("");
  box.querySelectorAll(".js-revoke-role").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await apiFetch(`/api/v1/vault/roles/${encodeURIComponent(btn.getAttribute("data-id"))}`, { method: "DELETE" });
      loadHouseholdRoles();
    });
  });
}

async function createFamilyRole() {
  const payload = {
    share_code: document.getElementById("r_code").value.trim(),
    label: document.getElementById("r_label").value.trim(),
    role: document.getElementById("r_role").value,
    allowed_member_id: document.getElementById("r_member").value.trim() || "*",
  };
  const res = await apiFetch("/api/v1/vault/roles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Could not create role code.");
    return;
  }
  document.getElementById("r_code").value = "";
  document.getElementById("r_label").value = "";
  loadHouseholdRoles();
}

// ASK HEALTH AI (WITH URGENT EMERGENCY BANNER)
const EMERGENCY_SYMPTOMS_REGEX = /\b(chest\s+pain|shortness\s+of\s+breath|can'?t\s+breathe|unconscious|seizure|stroke|paralysis|severe\s+bleeding|heart\s+attack|suicid)\b/i;

async function submitQuestion() {
  const q = document.getElementById("chatInput").value.trim();
  if (!q) return;
  const language = document.getElementById("languageSelect").value;
  const use_past_history = document.getElementById("useHistoryToggle").checked;
  const box = document.getElementById("chatResponseContainer");
  box.dir = isRtlLanguage(language) ? "rtl" : "ltr";
  box.innerHTML = `<p style="font-size:0.8rem; color:var(--text-muted);">Thinking...</p>`;

  const isEmergency = EMERGENCY_SYMPTOMS_REGEX.test(q);

  try {
    const res = await apiFetch("/api/v1/ask-question", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, member_id: activeMember, language, use_past_history }),
    });
    const data = await res.json();

    if (!res.ok) {
      box.innerHTML = `
        <div class="card" style="background:var(--danger-soft); border-color:#FECACA;">
          <p style="font-size:0.84rem; font-weight:600; color:var(--danger);">
            ${escapeHtml(data.detail || "Please ask questions related to health, symptoms, or medical reports.")}
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
      ${isEmergency ? `
        <div class="card" style="background:var(--danger-soft); border-color:#FECACA;">
          <strong style="font-size:0.85rem; color:var(--danger);">🚨 Urgent Medical Care Warning:</strong>
          <p style="font-size:0.78rem; color:var(--danger);">If you or someone with you is experiencing a medical emergency (such as chest pain or difficulty breathing), please call emergency services or visit the nearest hospital ER immediately.</p>
        </div>` : ""}
      <div class="card space-y">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span class="badge badge-teal">${escapeHtml(historyNote)}</span>
          ${r.voice_script ? `<button type="button" class="btn-icon js-speak-btn" aria-label="Listen" data-speech="${encodeURIComponent(r.voice_script)}" data-title="Answer">🔈</button>` : ""}
        </div>
        <p style="font-size:0.92rem; font-weight:600;">${escapeHtml(r.direct_answer || "")}</p>
        ${reasons.length ? `
          <ul style="padding-left:18px; font-size:0.82rem; color:var(--text-muted);" class="space-y">
            ${reasons.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
          </ul>` : ""}
        <div style="padding-top:10px; border-top:1px solid var(--border); font-size:0.76rem; color:var(--text-muted); display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px;">
          <span><strong>Consult:</strong> ${escapeHtml(r.which_doctor_to_consult || "General Physician")}</span>
          <span>${escapeHtml(r.disclaimer || "Please consult a doctor.")}</span>
        </div>
      </div>`;
    bindDynamicCardEvents(box);
  } catch (err) {
    box.innerHTML = `<p style="font-size:0.8rem; color:var(--danger);">Error: ${escapeHtml(err.message)}</p>`;
  }
}