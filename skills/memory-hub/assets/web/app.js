(function () {
  "use strict";

  var routes = {
    overview: {
      title: "Overview",
      eyebrow: "Repository memory",
      description: "The current state, recent context, and work that still needs attention.",
      endpoint: "/api/overview"
    },
    timeline: {
      title: "Timeline",
      eyebrow: "Chronological record",
      description: "Sessions, checkpoints, changes, and decisions in the order they happened.",
      endpoint: "/api/timeline"
    },
    decisions: {
      title: "Decisions",
      eyebrow: "Reasoning ledger",
      description: "Technical choices, their rationale, alternatives, and current standing.",
      endpoint: "/api/decisions"
    },
    capabilities: {
      title: "Capabilities",
      eyebrow: "System map",
      description: "What the repository can do, where it lives, and what remains limited.",
      endpoint: "/api/capabilities"
    },
    directions: {
      title: "Developer directions",
      eyebrow: "Human guidance",
      description: "Explicit instructions and corrections that should guide future work.",
      endpoint: "/api/directions"
    },
    "open-work": {
      title: "Open work",
      eyebrow: "Unclosed loops",
      description: "Incomplete tasks, blockers, questions, and deferred improvements.",
      endpoint: "/api/open-work"
    },
    feedback: {
      title: "Feedback",
      eyebrow: "Human signal",
      description: "Corrections, concerns, suggestions, and positive observations attached to repository memory.",
      endpoint: "/api/feedback"
    }
  };

  var state = {
    route: "overview",
    cache: Object.create(null),
    records: [],
    request: null,
    searchRequest: null,
    detailRequest: null,
    activeRecord: null,
    detailReturnFocus: null,
    feedbackReturnFocus: null,
    sessions: null
  };

  var recordTypes = ["checkpoints", "tasks", "changes", "decisions", "directions", "capabilities", "open_loops", "evidence", "relationships"];
  var typeAliases = {
    checkpoint: "checkpoints", task: "tasks", change: "changes", decision: "decisions",
    direction: "directions", capability: "capabilities", open_loop: "open_loops",
    "open-loop": "open_loops", work: "open_loops", evidence: "evidence", relationship: "relationships",
    feedback: "feedback"
  };
  var editableByType = {
    checkpoints: ["summary", "open_context", "scope", "source", "confidence", "confirmation", "status", "evidence_ids", "supersedes_id"],
    tasks: ["title", "status", "summary", "result", "tests", "file_paths", "scope", "source", "confidence", "confirmation", "evidence_ids", "supersedes_id"],
    changes: ["path", "kind", "summary", "old_path", "task_ids", "scope", "source", "confidence", "confirmation", "status", "evidence_ids", "supersedes_id"],
    decisions: ["title", "status", "scope", "rationale", "alternatives", "tradeoffs", "reconsider_when", "source", "confidence", "confirmation", "evidence_ids", "supersedes_id"],
    directions: ["instruction", "status", "scope", "origin", "importance", "correction_of", "source", "confidence", "confirmation", "evidence_ids", "supersedes_id"],
    capabilities: ["name", "status", "summary", "file_paths", "test_paths", "limitations", "scope", "source", "confidence", "confirmation", "evidence_ids", "supersedes_id"],
    open_loops: ["title", "kind", "status", "summary", "next_step", "owner", "scope", "source", "confidence", "confirmation", "evidence_ids", "supersedes_id"],
    evidence: ["kind", "summary", "reference", "observed_at", "scope", "source", "confidence", "confirmation", "status", "evidence_ids", "supersedes_id"],
    relationships: ["from_id", "type", "to_id", "summary"]
  };
  editableByType.feedback = ["type", "sentiment", "rating", "body"];
  var arrayFields = ["evidence_ids", "tests", "file_paths", "task_ids", "rationale", "alternatives", "tradeoffs", "reconsider_when", "test_paths", "limitations"];

  var content = document.getElementById("view-content");
  var filterBar = document.getElementById("filter-bar");
  var recordFilter = document.getElementById("record-filter");
  var statusFilter = document.getElementById("status-filter");
  var filterCount = document.getElementById("filter-count");
  var searchDialog = document.getElementById("search-dialog");
  var searchResults = document.getElementById("search-results");
  var searchSummary = document.getElementById("search-summary");
  var detailDialog = document.getElementById("detail-dialog");
  var detailContent = document.getElementById("detail-content");
  var detailStatus = document.getElementById("detail-status");
  var deleteDialog = document.getElementById("delete-dialog");
  var deleteError = document.getElementById("delete-error");
  var feedbackDialog = document.getElementById("feedback-dialog");
  var feedbackForm = document.getElementById("feedback-form");
  var feedbackError = document.getElementById("feedback-form-error");
  var feedbackScope = document.getElementById("feedback-scope");
  var feedbackSession = document.getElementById("feedback-session");
  var feedbackRecordId = document.getElementById("feedback-record-id");
  var globalStatus = document.getElementById("global-status");

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function value(record, names, fallback) {
    if (!record || typeof record !== "object") return fallback;
    for (var i = 0; i < names.length; i += 1) {
      var found = record[names[i]];
      if (found !== undefined && found !== null && found !== "") return found;
    }
    return fallback;
  }

  function textValue(input, fallback) {
    if (input === undefined || input === null || input === "") return fallback || "";
    if (Array.isArray(input)) return input.map(function (item) { return textValue(item); }).filter(Boolean).join(", ");
    if (typeof input === "object") return textValue(value(input, ["title", "name", "label", "summary", "value"], ""), fallback);
    return String(input);
  }

  function listValue(input) {
    if (input === undefined || input === null || input === "") return [];
    if (Array.isArray(input)) return input;
    if (typeof input === "string") return input.split(/\n|,\s*/).filter(Boolean);
    return [input];
  }

  function recordsFrom(payload, keys) {
    if (Array.isArray(payload)) return payload;
    if (!payload || typeof payload !== "object") return [];
    var names = (keys || []).concat(["items", "records", "results", "data"]);
    for (var i = 0; i < names.length; i += 1) {
      if (Array.isArray(payload[names[i]])) return payload[names[i]];
    }
    if (payload.data && typeof payload.data === "object") return recordsFrom(payload.data, keys);
    return [];
  }

  function normalizedStatus(record) {
    return textValue(value(record, ["status", "state", "outcome", "confirmation_state"], "unknown"), "unknown").toLowerCase();
  }

  function feedbackSentiment(record) {
    return textValue(value(record, ["sentiment"], "neutral"), "neutral").toLowerCase();
  }

  function statusClass(status) {
    if (/positive|active|complete|implemented|confirmed|closed|observed/.test(status)) return "positive";
    if (/open|partial|progress|proposed|review|planned|pending/.test(status)) return "attention";
    if (/negative|reject|block|deprecated|failed|cancel/.test(status)) return "negative";
    if (/supersed|defer/.test(status)) return "muted";
    return "neutral";
  }

  function statusPill(record, override) {
    var status = override || normalizedStatus(record);
    return el("span", "status " + statusClass(status), status.replace(/[_-]+/g, " "));
  }

  function formatDate(input) {
    if (!input) return "Date not recorded";
    var date = new Date(input);
    if (isNaN(date.getTime())) return textValue(input, "Date not recorded");
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
    }).format(date);
  }

  function recordDate(record) {
    return value(record, ["created_at", "timestamp", "date", "updated_at", "started_at", "closed_at", "time"], null);
  }

  function titleFor(record, fallback) {
    var feedbackShape = record && typeof record === "object" && record.body !== undefined && record.scope !== undefined && record.sentiment !== undefined;
    if (feedbackShape || recordIdentity(record, "").type === "feedback") return feedbackTitle(record);
    return textValue(value(record, ["title", "name", "instruction", "goal", "summary", "event", "message"], fallback), fallback);
  }

  function feedbackTitle(record) {
    var body = textValue(value(record, ["body", "summary", "excerpt"], "Feedback"), "Feedback").replace(/\s+/g, " ").trim();
    return body.length > 72 ? body.slice(0, 69).trimEnd() + "..." : body;
  }

  function appendMeta(parent, entries) {
    var usable = entries.filter(function (entry) { return entry[1] !== undefined && entry[1] !== null && entry[1] !== ""; });
    if (!usable.length) return;
    var meta = el("dl", "record-meta");
    usable.forEach(function (entry) {
      meta.append(el("dt", "", entry[0]), el("dd", "", textValue(entry[1], "Not recorded")));
    });
    parent.append(meta);
  }

  function appendList(parent, heading, items) {
    var values = listValue(items).map(function (item) { return textValue(item); }).filter(Boolean);
    if (!values.length) return;
    var section = el("div", "detail-list");
    section.append(el("h3", "", heading));
    var list = el("ul");
    values.forEach(function (item) { list.append(el("li", "", item)); });
    section.append(list);
    parent.append(section);
  }

  function emptyState(title, detail) {
    var box = el("div", "empty-state");
    box.append(el("span", "empty-mark", "0"), el("h2", "", title), el("p", "", detail));
    return box;
  }

  function renderError(error) {
    content.replaceChildren();
    var box = el("div", "error-state");
    box.append(el("p", "eyebrow", "Endpoint unavailable"), el("h2", "", "This view could not be loaded."));
    box.append(el("p", "", error && error.message ? error.message : "The local server returned an unreadable response."));
    var retry = el("button", "primary-button", "Try again");
    retry.type = "button";
    retry.addEventListener("click", function () { loadRoute(state.route, true); });
    box.append(retry);
    content.append(box);
    content.setAttribute("aria-busy", "false");
  }

  function showLoading() {
    content.setAttribute("aria-busy", "true");
    var loading = el("div", "loading-grid");
    for (var i = 0; i < 4; i += 1) {
      var card = el("div", "loading-card");
      card.append(el("i"), el("i"), el("i"));
      loading.append(card);
    }
    content.replaceChildren(loading);
  }

  async function fetchJSON(url, options) {
    options = options || {};
    var headers = { "Accept": "application/json" };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    var response = await fetch(url, {
      method: options.method || "GET",
      headers: headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
      signal: options.signal || (options.controller && options.controller.signal)
    });
    if (response.status === 204 && response.ok) return null;
    var type = response.headers.get("content-type") || "";
    var payload = type.includes("json") ? await response.json().catch(function () { return null; }) : null;
    if (!response.ok) {
      var errorValue = value(payload, ["message", "error", "detail"], "");
      var message = typeof errorValue === "object" ? textValue(value(errorValue, ["message", "detail", "reason"], "")) : textValue(errorValue);
      var references = listValue(value(payload, ["references", "referenced_by", "dependencies"], [])).map(function (item) { return textValue(item); }).filter(Boolean);
      if (references.length) message += (message ? " " : "") + "References: " + references.join(", ") + ".";
      var error = new Error(message || "The local API returned " + response.status + " " + response.statusText + ".");
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    if (!type.includes("json")) throw new Error("The local API did not return JSON.");
    return payload;
  }

  function canonicalType(input) {
    var type = textValue(input).toLowerCase().replace(/\s+/g, "_");
    if (type === "session" || type === "sessions") return "sessions";
    if (recordTypes.includes(type)) return type;
    return typeAliases[type] || (typeAliases[type.replace(/s$/, "")] || "");
  }

  function recordIdentity(record, fallbackType) {
    var fallback = canonicalType(fallbackType);
    if (fallback === "open_loops" && record.kind === undefined) fallback = "tasks";
    var advertised = value(record, ["result_type", "record_type", "memory_type", "event_type"], "");
    return {
      id: textValue(value(record, ["id", "public_id", "record_id"], "")),
      type: canonicalType(advertised) || fallback || canonicalType(value(record, ["type"], ""))
    };
  }

  function makeTrigger(className, record, type, containerTag) {
    var button = el(containerTag || "button", className);
    var trigger = button;
    if (containerTag) {
      trigger = el("button", "record-open-button");
      trigger.type = "button";
      trigger.setAttribute("aria-label", "Open record: " + titleFor(record, "untitled record"));
      button.append(trigger);
    }
    button.type = "button";
    var identity = recordIdentity(record, type);
    if (!identity.id || !identity.type) {
      trigger.disabled = true;
      trigger.title = "Detail is unavailable for this summary";
    } else {
      trigger.addEventListener("click", function () { openDetail(identity.type, identity.id, trigger); });
    }
    return button;
  }

  function humanLabel(field) {
    return field.replace(/_/g, " ").replace(/^./, function (letter) { return letter.toUpperCase(); });
  }

  function unwrapRecord(payload, type) {
    if (!payload || typeof payload !== "object") return {};
    if (payload.record && typeof payload.record === "object") return payload.record;
    var singular = type.replace(/s$/, "");
    if (payload[singular] && typeof payload[singular] === "object") return payload[singular];
    return payload;
  }

  function visibleEntries(record) {
    return Object.keys(record).filter(function (key) {
      return key !== "editable_fields" && record[key] !== null && record[key] !== "" && key !== "related";
    });
  }

  function appendLedgerValue(parent, key, input) {
    var row = el("div", "ledger-row");
    row.append(el("dt", "", humanLabel(key)));
    var detail = el("dd");
    if (Array.isArray(input)) {
      if (!input.length) detail.textContent = "None recorded";
      else {
        var list = el("ul", "ledger-values");
        input.forEach(function (item) { list.append(el("li", "", textValue(item, JSON.stringify(item)))); });
        detail.append(list);
      }
    } else if (typeof input === "object" && input !== null) {
      detail.append(el("pre", "ledger-json", JSON.stringify(input, null, 2)));
    } else if (/_at$|^(date|timestamp)$/.test(key)) {
      detail.textContent = formatDate(input);
    } else {
      detail.textContent = textValue(input, "Not recorded");
    }
    row.append(detail);
    parent.append(row);
  }

  function renderLedger(record) {
    var ledger = el("dl", "ledger-sheet");
    visibleEntries(record).forEach(function (key) { appendLedgerValue(ledger, key, record[key]); });
    return ledger;
  }

  function detailLoading() {
    detailContent.setAttribute("aria-busy", "true");
    detailContent.replaceChildren(el("div", "detail-loading", "Opening ledger entry..."));
    detailStatus.textContent = "Loading record detail";
  }

  function detailFailure(error) {
    var box = el("div", "error-state");
    box.append(el("h3", "", "Record detail could not be loaded."), el("p", "", error.message));
    detailContent.replaceChildren(box);
    detailContent.setAttribute("aria-busy", "false");
    detailStatus.textContent = "Record detail failed to load";
  }

  async function openDetail(type, id, trigger) {
    type = canonicalType(type);
    if (!id || !type) return;
    if (state.detailRequest) state.detailRequest.abort();
    state.detailRequest = new AbortController();
    if (!detailDialog.open) state.detailReturnFocus = trigger || document.activeElement;
    document.getElementById("detail-eyebrow").textContent = type === "sessions" ? "Session ledger" : humanLabel(type.replace(/s$/, ""));
    document.getElementById("detail-title").textContent = type === "sessions" ? "Session detail" : "Record detail";
    detailLoading();
    if (!detailDialog.open) detailDialog.showModal();
    try {
      var endpoint = type === "sessions" ? "/api/sessions/" : "/api/records/" + encodeURIComponent(type) + "/";
      var payload = await fetchJSON(endpoint + encodeURIComponent(id), { controller: state.detailRequest });
      if (type === "sessions") renderSessionDetail(payload);
      else renderRecordDetail(payload, type);
    } catch (error) {
      if (error.name !== "AbortError") detailFailure(error);
    }
  }

  function sessionGroups(payload) {
    var source = payload.related && typeof payload.related === "object" ? payload.related :
      (payload.related_records && typeof payload.related_records === "object" ? payload.related_records : payload);
    return recordTypes.concat(["feedback"]).map(function (type) {
      var records = recordsFrom(source[type], [type]);
      if (!records.length && Array.isArray(source[type])) records = source[type];
      return [type, records];
    }).filter(function (entry) { return entry[1].length; });
  }

  function renderSessionDetail(payload) {
    var session = unwrapRecord(payload, "sessions");
    if (!payload.session && !payload.record) {
      session = Object.assign({}, session);
      recordTypes.concat(["related_records"]).forEach(function (key) { delete session[key]; });
    }
    document.getElementById("detail-title").textContent = titleFor(session, "Session detail");
    var fragment = document.createDocumentFragment();
    fragment.append(renderLedger(session));
    var sessionActions = el("div", "record-actions");
    var addSessionFeedback = el("button", "secondary-button", "Add feedback for this session");
    addSessionFeedback.type = "button";
    addSessionFeedback.addEventListener("click", function () {
      var returnFocus = state.detailReturnFocus;
      detailDialog.close();
      openFeedbackDialog({ scope: "session", session_id: session.id }, returnFocus);
    });
    sessionActions.append(addSessionFeedback);
    fragment.append(sessionActions);
    var groups = sessionGroups(payload);
    var related = el("section", "related-ledger");
    related.append(el("h3", "", "Related records"));
    if (!groups.length) related.append(el("p", "quiet-empty", "No related records were returned for this session."));
    groups.forEach(function (entry) {
      var section = el("section", "related-group");
      var heading = el("div", "related-heading");
      heading.append(el("h4", "", humanLabel(entry[0])), el("span", "", String(entry[1].length).padStart(2, "0")));
      section.append(heading);
      entry[1].forEach(function (record) { section.append(detailRecordButton(record, entry[0])); });
      related.append(section);
    });
    fragment.append(related);
    detailContent.replaceChildren(fragment);
    detailContent.setAttribute("aria-busy", "false");
    detailStatus.textContent = "Session detail loaded";
  }

  function detailRecordButton(record, type) {
    var button = makeTrigger("related-record", record, type);
    button.append(el("span", "record-kind", humanLabel(type.replace(/s$/, ""))), el("strong", "", titleFor(record, "Untitled record")));
    var summary = textValue(value(record, ["body", "summary", "rationale", "instruction", "reference"], ""));
    if (summary && summary !== titleFor(record, "")) button.append(el("span", "related-summary", summary));
    return button;
  }

  function endpointEditable(payload, record, type) {
    var advertised = value(payload, ["editable_fields"], value(record, ["editable_fields"], null));
    var safe = editableByType[type] || [];
    var fields = Array.isArray(advertised) ? advertised : safe.filter(function (field) { return Object.prototype.hasOwnProperty.call(record, field); });
    var forbidden = /(^id$|^public_id$|^repository_id$|^session_id$|_at$|^git_|^created$|^updated$|^closed$|^timestamp$)/;
    return fields.filter(function (field, index) {
      return typeof field === "string" && safe.includes(field) && !forbidden.test(field) && fields.indexOf(field) === index;
    });
  }

  function renderRecordDetail(payload, type) {
    var record = unwrapRecord(payload, type);
    state.activeRecord = { type: type, id: recordIdentity(record, type).id, record: record, payload: payload };
    document.getElementById("detail-title").textContent = titleFor(record, "Record detail");
    var actions = el("div", "record-actions");
    var edit = el("button", "primary-button", type === "feedback" ? "Edit feedback" : "Edit record");
    edit.type = "button";
    edit.addEventListener("click", function () { renderEditForm(); });
    var remove = el("button", "danger-link", type === "feedback" ? "Delete feedback" : "Delete record");
    remove.type = "button";
    remove.addEventListener("click", openDeleteConfirmation);
    var editable = endpointEditable(payload, record, type);
    if (!editable.length) edit.disabled = true;
    actions.append(edit);
    if (type !== "feedback" && type !== "relationships") {
      var addFeedback = el("button", "secondary-button", "Add feedback");
      addFeedback.type = "button";
      addFeedback.addEventListener("click", function () {
        var returnFocus = state.detailReturnFocus;
        detailDialog.close();
        openFeedbackDialog({ scope: "record", record_id: state.activeRecord.id }, returnFocus);
      });
      actions.append(addFeedback);
    }
    actions.append(remove);
    detailContent.replaceChildren(renderLedger(record), actions);
    detailContent.setAttribute("aria-busy", "false");
    detailStatus.textContent = "Record detail loaded";
  }

  function inputForField(field, current) {
    var wrap = el("label", "field-row");
    wrap.append(el("span", "", humanLabel(field)));
    var input;
    if (state.activeRecord && state.activeRecord.type === "feedback" && (field === "type" || field === "sentiment")) {
      input = el("select");
      var choices = field === "type" ? ["positive", "correction", "concern", "suggestion"] : ["positive", "neutral", "negative"];
      choices.forEach(function (choice) {
        var option = el("option", "", humanLabel(choice));
        option.value = choice;
        option.selected = choice === current;
        input.append(option);
      });
      wrap.append(input);
    } else if (state.activeRecord && state.activeRecord.type === "feedback" && field === "rating") {
      input = el("input");
      input.type = "number";
      input.min = "1";
      input.max = "5";
      input.step = "1";
      input.value = current === null || current === undefined ? "" : String(current);
      wrap.append(input, el("small", "", "Optional; leave blank to remove the rating."));
    } else if (arrayFields.includes(field)) {
      input = el("textarea");
      input.rows = 4;
      input.value = JSON.stringify(Array.isArray(current) ? current : listValue(current), null, 2);
      input.dataset.array = "true";
      wrap.append(input, el("small", "", "JSON array, for example [\"one\", \"two\"]"));
    } else if (/summary|rationale|instruction|context|result|limitations|tradeoffs|next_step|body/.test(field)) {
      input = el("textarea");
      input.rows = 4;
      input.value = current === null || current === undefined ? "" : String(current);
      wrap.append(input);
    } else {
      input = el("input");
      input.type = "text";
      input.value = current === null || current === undefined ? "" : String(current);
      wrap.append(input);
    }
    input.name = field;
    return wrap;
  }

  function renderEditForm() {
    var active = state.activeRecord;
    if (!active) return;
    var fields = endpointEditable(active.payload, active.record, active.type);
    var form = el("form", "edit-form");
    form.noValidate = true;
    form.append(el("p", "form-intro", "Only semantic record fields can be changed. Repository IDs, timestamps, and Git state remain read-only."));
    fields.forEach(function (field) { form.append(inputForField(field, active.record[field])); });
    var error = el("p", "form-error");
    error.setAttribute("role", "alert");
    error.setAttribute("aria-live", "assertive");
    error.hidden = true;
    var actions = el("div", "dialog-actions");
    var cancel = el("button", "secondary-button", "Cancel");
    cancel.type = "button";
    cancel.addEventListener("click", function () { renderRecordDetail(active.payload, active.type); });
    var save = el("button", "primary-button", "Save changes");
    save.type = "submit";
    actions.append(cancel, save);
    form.append(error, actions);
    form.addEventListener("submit", function (event) { submitEdit(event, form, fields, save, error); });
    detailContent.replaceChildren(form);
    form.querySelector("input, select, textarea").focus();
  }

  function sameValue(left, right) {
    return JSON.stringify(left === undefined ? null : left) === JSON.stringify(right === undefined ? null : right);
  }

  async function submitEdit(event, form, fields, button, errorNode) {
    event.preventDefault();
    var active = state.activeRecord;
    var changes = {};
    try {
      fields.forEach(function (field) {
        var input = form.elements[field];
        var next = input.dataset.array === "true" ? JSON.parse(input.value || "[]") : input.value;
        if (active.type === "feedback" && field === "rating") next = input.value === "" ? null : Number(input.value);
        if (input.dataset.array === "true" && !Array.isArray(next)) throw new Error(humanLabel(field) + " must be a JSON array.");
        if (active.type === "feedback" && field === "rating" && next !== null && (!Number.isInteger(next) || next < 1 || next > 5)) throw new Error("Rating must be a whole number from 1 through 5.");
        if (active.type === "feedback" && field === "body" && !next.trim()) throw new Error("Feedback is required.");
        if (!sameValue(next, active.record[field])) changes[field] = next;
      });
    } catch (parseError) {
      errorNode.textContent = parseError.message;
      errorNode.hidden = false;
      return;
    }
    if (!Object.keys(changes).length) {
      errorNode.textContent = "No fields have changed.";
      errorNode.hidden = false;
      return;
    }
    button.disabled = true;
    button.textContent = "Saving...";
    form.setAttribute("aria-busy", "true");
    errorNode.hidden = true;
    try {
      var payload = await fetchJSON("/api/records/" + encodeURIComponent(active.type) + "/" + encodeURIComponent(active.id), { method: "PATCH", body: changes });
      invalidateCaches();
      renderRecordDetail(payload || Object.assign({}, active.record, changes), active.type);
      detailStatus.textContent = "Record changes saved";
      announce(active.type === "feedback" ? "Feedback updated." : "Record updated.");
    } catch (saveError) {
      errorNode.textContent = saveError.message;
      errorNode.hidden = false;
      button.disabled = false;
      button.textContent = "Save changes";
      form.setAttribute("aria-busy", "false");
    }
  }

  function openDeleteConfirmation() {
    deleteError.hidden = true;
    deleteError.textContent = "";
    var noun = state.activeRecord.type === "feedback" ? "feedback" : "record";
    document.getElementById("delete-title").textContent = "Delete this " + noun + "?";
    document.getElementById("delete-description").textContent = "Delete \"" + titleFor(state.activeRecord.record, "this " + noun) + "\"? This cannot be undone.";
    deleteDialog.showModal();
  }

  function invalidateCaches() {
    state.cache = Object.create(null);
  }

  async function submitDelete(event) {
    event.preventDefault();
    var active = state.activeRecord;
    var button = document.getElementById("confirm-delete");
    button.disabled = true;
    button.textContent = "Deleting...";
    deleteError.hidden = true;
    try {
      await fetchJSON("/api/records/" + encodeURIComponent(active.type) + "/" + encodeURIComponent(active.id), { method: "DELETE" });
      invalidateCaches();
      deleteDialog.close();
      detailDialog.close();
      state.activeRecord = null;
      await loadRoute(state.route, true);
      announce(active.type === "feedback" ? "Feedback deleted." : "Record deleted.");
    } catch (error) {
      deleteError.textContent = error.status === 409 ? "This record is still referenced by other memory. Remove those references before deleting it. " + error.message : error.message;
      deleteError.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = "Delete permanently";
    }
  }

  function setHeading(route) {
    var config = routes[route];
    document.title = config.title + " | Memory Hub";
    document.getElementById("view-title").textContent = config.title;
    document.getElementById("view-eyebrow").textContent = config.eyebrow;
    document.getElementById("view-description").textContent = config.description;
    document.getElementById("add-feedback-button").hidden = route !== "feedback";
    document.querySelectorAll("[data-route]").forEach(function (link) {
      var active = link.dataset.route === route;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  async function loadRoute(route, force) {
    route = routes[route] ? route : "overview";
    state.route = route;
    setHeading(route);
    filterBar.hidden = route === "overview";
    recordFilter.value = "";
    resetStatusFilter();

    if (!force && state.cache[route] !== undefined) {
      renderRoute(route, state.cache[route]);
      return;
    }
    if (state.request) state.request.abort();
    state.request = new AbortController();
    showLoading();
    try {
      var payload = await fetchJSON(routes[route].endpoint, { controller: state.request });
      state.cache[route] = payload;
      if (state.route === route) renderRoute(route, payload);
    } catch (error) {
      if (error.name !== "AbortError" && state.route === route) renderError(error);
    }
  }

  function overviewCounts(payload) {
    var counts = value(payload, ["counts", "stats", "summary"], {});
    if (!counts || typeof counts !== "object" || Array.isArray(counts)) counts = {};
    return [
      ["Sessions", value(counts, ["sessions", "session_count"], value(payload, ["session_count"], 0))],
      ["Active decisions", value(counts, ["active_decisions", "decisions"], value(payload, ["active_decisions"], 0))],
      ["Open items", value(counts, ["open_work", "open_items", "open_loops"], value(payload, ["open_count"], 0))],
      ["Capabilities", value(counts, ["capabilities", "capability_count"], value(payload, ["capability_count"], 0))]
    ];
  }

  function renderOverview(payload) {
    payload = payload && typeof payload === "object" ? payload : {};
    var fragment = document.createDocumentFragment();
    var repo = value(payload, ["repository", "repo", "project"], {});
    if (typeof repo === "string") repo = { name: repo };
    var hero = el("section", "repository-card");
    var heroCopy = el("div");
    heroCopy.append(el("p", "eyebrow", "Current repository"));
    heroCopy.append(el("h2", "", textValue(value(repo, ["name", "repository_name"], value(payload, ["repository_name", "name"], "Repository")), "Repository")));
    heroCopy.append(el("p", "repo-state", textValue(value(repo, ["state", "summary", "description"], value(payload, ["current_state", "state"], "No repository summary has been captured yet.")))));
    hero.append(heroCopy);
    appendMeta(hero, [
      ["Branch", value(repo, ["branch", "current_branch"], value(payload, ["branch"], null))],
      ["Last capture", formatDate(value(payload, ["last_capture", "last_captured_at", "updated_at"], value(repo, ["last_capture"], null)))],
      ["Path", value(repo, ["path", "root", "repo_root"], null)]
    ]);
    fragment.append(hero);

    var metrics = el("section", "metric-strip", "");
    metrics.setAttribute("aria-label", "Repository totals");
    overviewCounts(payload).forEach(function (metric) {
      var item = el("div", "metric");
      item.append(el("strong", "", textValue(metric[1], "0")), el("span", "", metric[0]));
      metrics.append(item);
    });
    fragment.append(metrics);

    var sections = [
      ["Recent decisions", ["recent_decisions", "decisions"], "decision", "No decisions recorded", "Decisions and their rationale will appear here."],
      ["Open work", ["open_work", "open_loops", "recent_open_work"], "work", "No open work", "There are no recorded open loops."],
      ["Recent session", ["recent_sessions", "sessions", "recent_session", "last_session"], "session", "No sessions recorded", "The latest captured session will appear here."],
      ["Capability summary", ["capabilities", "capability_summary", "recent_capabilities"], "capability", "No capabilities recorded", "Captured repository capabilities will appear here."]
    ];
    var grid = el("section", "overview-grid");
    sections.forEach(function (definition) {
      var raw = value(payload, definition[1], []);
      var records = Array.isArray(raw) ? raw : (raw && typeof raw === "object" ? recordsFrom(raw, definition[1]) : []);
      if (!records.length && raw && typeof raw === "object" && !Array.isArray(raw)) records = [raw];
      var panel = el("article", "overview-panel");
      var heading = el("div", "panel-heading");
      heading.append(el("h2", "", definition[0]), el("span", "", String(records.length).padStart(2, "0")));
      panel.append(heading);
      if (!records.length) {
        panel.append(el("p", "quiet-empty", definition[4]));
      } else {
        records.slice(0, 4).forEach(function (record) { panel.append(compactRecord(record, definition[2])); });
      }
      grid.append(panel);
    });
    fragment.append(grid);
    content.replaceChildren(fragment);
    content.setAttribute("aria-busy", "false");
  }

  function compactRecord(record, type) {
    if (typeof record !== "object" || record === null) record = { title: textValue(record) };
    var item = makeTrigger("compact-record record-trigger", record, type, "div");
    var copy = el("div");
    copy.append(el("strong", "", titleFor(record, "Untitled " + type)));
    var summary = textValue(value(record, ["summary", "rationale", "description", "outcome"], ""));
    if (summary && summary !== titleFor(record, "")) copy.append(el("p", "", summary));
    item.append(copy, statusPill(record));
    return item;
  }

  function makeRecordCard(record, kind) {
    if (typeof record !== "object" || record === null) record = { title: textValue(record) };
    var card = makeTrigger("record-card record-trigger " + kind + "-card", record, kind, "article");
    var top = el("div", "record-topline");
    top.append(el("span", "record-kind", textValue(value(record, ["type", "event_type", "kind", "category"], kind)).replace(/[_-]+/g, " ")), statusPill(record, kind === "feedback" ? feedbackSentiment(record) : ""));
    card.append(top, el("h2", "", titleFor(record, "Untitled record")));
    var summary = textValue(value(record, ["summary", "description", "detail", "body", "outcome"], ""));
    if (summary && summary !== titleFor(record, "")) card.append(el("p", "record-summary", summary));

    if (kind === "decision") {
      appendList(card, "Rationale", value(record, ["rationale", "reasons"], []));
      appendList(card, "Alternatives considered", value(record, ["alternatives", "rejected_alternatives"], []));
      appendList(card, "Trade-offs", value(record, ["tradeoffs", "trade_offs"], []));
      appendMeta(card, [["Scope", value(record, ["scope"], null)], ["Confidence", value(record, ["confidence", "provenance"], null)], ["Recorded", formatDate(recordDate(record))]]);
    } else if (kind === "capability") {
      appendList(card, "Relevant files", value(record, ["file_paths"], []));
      appendList(card, "Tests", value(record, ["test_paths"], []));
      appendList(card, "Known limitations", value(record, ["limitations", "known_limitations"], []));
      appendMeta(card, [["Area", value(record, ["scope", "area", "parent"], null)], ["Updated", formatDate(recordDate(record))]]);
    } else if (kind === "direction") {
      appendMeta(card, [["Scope", value(record, ["scope"], "repository")], ["Importance", value(record, ["importance", "priority"], null)], ["Origin", value(record, ["origin", "source"], null)], ["Recorded", formatDate(recordDate(record))]]);
    } else if (kind === "work") {
      appendList(card, "Blockers", value(record, ["blockers", "blocked_by"], []));
      appendList(card, "Next step", value(record, ["next_step"], []));
      appendMeta(card, [["Priority", value(record, ["priority", "importance"], null)], ["Owner", value(record, ["owner", "assignee"], null)], ["Due", value(record, ["due_at", "due_date"], null)], ["Recorded", formatDate(recordDate(record))]]);
    } else if (kind === "feedback") {
      appendMeta(card, [["Scope", value(record, ["scope"], null)], ["Rating", value(record, ["rating"], null)], ["Session", value(record, ["session_id"], null)], ["Record", value(record, ["record_id"], null)], ["Recorded", formatDate(recordDate(record))]]);
    }
    return card;
  }

  function renderTimeline(records) {
    if (!records.length) return emptyState("No timeline entries", "Sessions, checkpoints, commits, and memory changes will appear after the first capture.");
    var timeline = el("ol", "timeline-list");
    records.slice().sort(function (a, b) {
      return new Date(recordDate(b) || 0).getTime() - new Date(recordDate(a) || 0).getTime();
    }).forEach(function (record) {
      if (typeof record !== "object" || record === null) record = { title: textValue(record) };
      var item = el("li", "timeline-entry");
      var rail = el("div", "timeline-rail");
      rail.append(el("span", "timeline-dot"));
      var body = makeTrigger("timeline-record record-trigger", record, "", "article");
      var kind = textValue(value(record, ["type", "event_type", "kind"], "event"));
      var head = el("div", "timeline-heading");
      head.append(el("span", "record-kind", kind.replace(/[_-]+/g, " ")), el("time", "", formatDate(recordDate(record))));
      body.append(head, el("h2", "", titleFor(record, "Timeline event")));
      var detail = textValue(value(record, ["body", "summary", "description", "detail", "outcome"], ""));
      if (detail && detail !== titleFor(record, "")) body.append(el("p", "", detail));
      appendMeta(body, [["Agent", value(record, ["agent", "actor"], null)], ["Session", value(record, ["session_id", "session"], null)], ["Commit", value(record, ["git_head"], null)]]);
      item.append(rail, body);
      timeline.append(item);
    });
    return timeline;
  }

  function renderRecords(records, kind) {
    if (!records.length) {
      var labels = {
        decision: ["No decisions recorded", "Captured choices and their rationale will appear here."],
        capability: ["No capabilities recorded", "Implemented, partial, and planned capabilities will appear here."],
        direction: ["No developer directions recorded", "Explicit instructions and corrections will appear here."],
        work: ["No open work", "There are no recorded tasks, blockers, or unanswered questions."],
        feedback: ["No feedback recorded", "Corrections, concerns, suggestions, and positive observations will appear here."]
      };
      return emptyState(labels[kind][0], labels[kind][1]);
    }
    var grid = el("section", "record-grid");
    records.forEach(function (record) { grid.append(makeRecordCard(record, kind)); });
    return grid;
  }

  function routeRecords(route, payload) {
    var keys = {
      timeline: ["timeline", "events", "entries"],
      decisions: ["decisions"],
      capabilities: ["capabilities"],
      directions: ["directions", "developer_directions"],
      "open-work": ["open_work", "open_loops", "tasks"],
      feedback: ["feedback"]
    };
    return recordsFrom(payload, keys[route] || []);
  }

  function renderRoute(route, payload) {
    if (route === "overview") {
      state.records = [];
      renderOverview(payload);
      return;
    }
    state.records = routeRecords(route, payload);
    populateStatuses(state.records, route === "feedback");
    applyFilters();
    content.setAttribute("aria-busy", "false");
  }

  function populateStatuses(records, sentiments) {
    document.getElementById("status-filter-label").textContent = sentiments ? "Sentiment" : "Status";
    var statuses = Array.from(new Set(records.map(sentiments ? feedbackSentiment : normalizedStatus))).sort();
    resetStatusFilter();
    statuses.forEach(function (status) {
      var option = el("option", "", status.replace(/[_-]+/g, " "));
      option.value = status;
      statusFilter.append(option);
    });
  }

  function resetStatusFilter() {
    var option = el("option", "", state.route === "feedback" ? "All sentiments" : "All statuses");
    option.value = "";
    statusFilter.replaceChildren(option);
  }

  function searchableText(record) {
    try { return JSON.stringify(record).toLowerCase(); }
    catch (error) { return textValue(record).toLowerCase(); }
  }

  function applyFilters() {
    var query = recordFilter.value.trim().toLowerCase();
    var status = statusFilter.value;
    var filtered = state.records.filter(function (record) {
      var facet = state.route === "feedback" ? feedbackSentiment(record) : normalizedStatus(record);
      return (!query || searchableText(record).includes(query)) && (!status || facet === status);
    });
    filterCount.value = filtered.length + (filtered.length === 1 ? " record" : " records");
    var result;
    if (state.route === "timeline") result = renderTimeline(filtered);
    else {
      var kind = { decisions: "decision", capabilities: "capability", directions: "direction", "open-work": "work", feedback: "feedback" }[state.route];
      result = renderRecords(filtered, kind);
    }
    content.replaceChildren(result);
  }

  function flattenSearch(payload) {
    var direct = recordsFrom(payload, ["results", "matches"]);
    if (direct.length) return direct;
    if (!payload || typeof payload !== "object") return [];
    var results = [];
    Object.keys(payload).forEach(function (key) {
      if (Array.isArray(payload[key])) {
        payload[key].forEach(function (record) {
          if (record && typeof record === "object") results.push(Object.assign({ result_type: key }, record));
          else results.push({ result_type: key, title: textValue(record) });
        });
      }
    });
    return results;
  }

  async function runSearch(query) {
    if (!query) return;
    if (state.searchRequest) state.searchRequest.abort();
    state.searchRequest = new AbortController();
    if (!searchDialog.open) searchDialog.showModal();
    searchSummary.textContent = "Searching local memory for \"" + query + "\"...";
    searchResults.replaceChildren(el("div", "search-loading", "Reading the local index..."));
    try {
      var payload = await fetchJSON("/api/search?q=" + encodeURIComponent(query) + "&task=", { controller: state.searchRequest });
      var results = flattenSearch(payload);
      searchSummary.textContent = results.length + (results.length === 1 ? " match" : " matches") + " for \"" + query + "\"";
      if (!results.length) {
        searchResults.replaceChildren(emptyState("No matching memory", "Try fewer words or a broader repository term."));
        return;
      }
      var list = el("div", "search-result-list");
      results.forEach(function (record) {
        var type = textValue(value(record, ["result_type", "type", "kind", "memory_type"], "memory"));
        var item = makeTrigger("search-result record-trigger", record, type, "article");
        item.append(el("span", "record-kind", type.replace(/[_-]+/g, " ")), el("h3", "", titleFor(record, "Memory record")));
        var excerpt = textValue(value(record, ["excerpt", "snippet", "body", "summary", "description", "rationale", "instruction"], ""));
        if (excerpt && excerpt !== titleFor(record, "")) item.append(el("p", "", excerpt));
        appendMeta(item, [[canonicalType(type) === "feedback" ? "Sentiment" : "Status", value(record, canonicalType(type) === "feedback" ? ["sentiment"] : ["status", "state"], null)], ["Recorded", formatDate(recordDate(record))]]);
        list.append(item);
      });
      searchResults.replaceChildren(list);
    } catch (error) {
      if (error.name === "AbortError") return;
      searchSummary.textContent = "Search unavailable";
      var failure = el("div", "error-state compact");
      failure.append(el("h3", "", "Search could not be completed."), el("p", "", error.message));
      searchResults.replaceChildren(failure);
    }
  }

  function announce(message) {
    globalStatus.textContent = "";
    window.setTimeout(function () { globalStatus.textContent = message; }, 20);
  }

  function sessionLabel(session) {
    var label = titleFor(session, textValue(value(session, ["id"], "Session"), "Session"));
    var identifier = textValue(value(session, ["id", "public_id"], ""));
    return label === identifier ? identifier : label + " (" + identifier + ")";
  }

  async function loadFeedbackSessions() {
    feedbackSession.disabled = true;
    feedbackSession.replaceChildren(el("option", "", "Loading sessions..."));
    try {
      var payload = await fetchJSON("/api/sessions");
      state.sessions = recordsFrom(payload, ["sessions"]);
      feedbackSession.replaceChildren();
      if (!state.sessions.length) {
        feedbackSession.append(el("option", "", "No sessions available"));
      } else {
        state.sessions.forEach(function (session) {
          var option = el("option", "", sessionLabel(session));
          option.value = textValue(value(session, ["id", "public_id"], ""));
          feedbackSession.append(option);
        });
      }
      feedbackSession.disabled = feedbackScope.value !== "session" || !state.sessions.length;
    } catch (error) {
      feedbackSession.replaceChildren(el("option", "", "Sessions unavailable"));
      feedbackError.textContent = "Sessions could not be loaded. " + error.message;
      feedbackError.hidden = false;
    }
  }

  function updateFeedbackScope() {
    var scope = feedbackScope.value;
    var sessionField = document.getElementById("feedback-session-field");
    var recordField = document.getElementById("feedback-record-field");
    sessionField.hidden = scope !== "session";
    recordField.hidden = scope !== "record";
    feedbackSession.disabled = scope !== "session" || !state.sessions || !state.sessions.length;
    feedbackSession.required = scope === "session";
    feedbackRecordId.disabled = scope !== "record";
    feedbackRecordId.required = scope === "record";
  }

  function openFeedbackDialog(preset, returnFocus) {
    state.feedbackReturnFocus = returnFocus || document.activeElement;
    feedbackForm.reset();
    feedbackError.hidden = true;
    feedbackError.textContent = "";
    state.sessions = null;
    if (preset && preset.scope) feedbackScope.value = preset.scope;
    if (preset && preset.record_id) feedbackRecordId.value = preset.record_id;
    updateFeedbackScope();
    feedbackDialog.showModal();
    feedbackForm.elements.type.focus();
    loadFeedbackSessions().then(function () {
      if (preset && preset.session_id) feedbackSession.value = preset.session_id;
    });
  }

  function closeFeedbackDialog() {
    if (feedbackDialog.open) feedbackDialog.close();
  }

  function feedbackFormMessage() {
    var body = feedbackForm.elements.body.value.trim();
    var rating = feedbackForm.elements.rating.value;
    if (!body) return "Feedback is required.";
    if (feedbackScope.value === "session" && (!state.sessions || !state.sessions.length)) return "Choose an available session. Sessions must load before session feedback can be added.";
    if (feedbackScope.value === "record" && !feedbackRecordId.value.trim()) return "Record ID is required for record feedback.";
    if (rating !== "" && (!/^\d+$/.test(rating) || Number(rating) < 1 || Number(rating) > 5)) return "Rating must be a whole number from 1 through 5.";
    return "";
  }

  async function submitFeedback(event) {
    event.preventDefault();
    if (feedbackForm.getAttribute("aria-busy") === "true") return;
    var message = feedbackFormMessage();
    if (message) {
      feedbackError.textContent = message;
      feedbackError.hidden = false;
      return;
    }
    var submit = document.getElementById("submit-feedback");
    var scope = feedbackScope.value;
    var payload = {
      type: feedbackForm.elements.type.value,
      scope: scope,
      body: feedbackForm.elements.body.value.trim(),
      sentiment: feedbackForm.elements.sentiment.value
    };
    if (feedbackForm.elements.rating.value !== "") payload.rating = Number(feedbackForm.elements.rating.value);
    if (scope === "session") payload.session_id = feedbackSession.value;
    if (scope === "record") payload.record_id = feedbackRecordId.value.trim();
    submit.disabled = true;
    submit.textContent = "Adding...";
    feedbackForm.setAttribute("aria-busy", "true");
    feedbackError.hidden = true;
    try {
      await fetchJSON("/api/feedback", { method: "POST", body: payload });
      invalidateCaches();
      closeFeedbackDialog();
      await loadRoute("feedback", true);
      announce("Feedback added.");
    } catch (error) {
      feedbackError.textContent = error.message;
      feedbackError.hidden = false;
    } finally {
      submit.disabled = false;
      submit.textContent = "Add feedback";
      feedbackForm.setAttribute("aria-busy", "false");
    }
  }

  function currentRoute() {
    return location.hash.replace(/^#\/?/, "").split("?")[0] || "overview";
  }

  window.addEventListener("hashchange", function () { loadRoute(currentRoute(), false); });
  document.getElementById("refresh-button").addEventListener("click", function () { loadRoute(state.route, true); });
  recordFilter.addEventListener("input", applyFilters);
  statusFilter.addEventListener("change", applyFilters);
  document.getElementById("search-form").addEventListener("submit", function (event) {
    event.preventDefault();
    runSearch(document.getElementById("global-search").value.trim());
  });
  document.getElementById("close-search").addEventListener("click", function () { searchDialog.close(); });
  searchDialog.addEventListener("click", function (event) {
    if (event.target === searchDialog) searchDialog.close();
  });
  document.getElementById("close-detail").addEventListener("click", function () { detailDialog.close(); });
  detailDialog.addEventListener("click", function (event) {
    if (event.target === detailDialog) detailDialog.close();
  });
  detailDialog.addEventListener("close", function () {
    if (state.detailRequest) state.detailRequest.abort();
    if (state.detailReturnFocus && state.detailReturnFocus.isConnected) state.detailReturnFocus.focus();
  });
  document.getElementById("cancel-delete").addEventListener("click", function () { deleteDialog.close(); });
  document.getElementById("delete-form").addEventListener("submit", submitDelete);
  deleteDialog.addEventListener("click", function (event) {
    if (event.target === deleteDialog) deleteDialog.close();
  });
  document.getElementById("add-feedback-button").addEventListener("click", function (event) {
    openFeedbackDialog(null, event.currentTarget);
  });
  document.getElementById("close-feedback").addEventListener("click", closeFeedbackDialog);
  document.getElementById("cancel-feedback").addEventListener("click", closeFeedbackDialog);
  feedbackScope.addEventListener("change", updateFeedbackScope);
  feedbackForm.addEventListener("submit", submitFeedback);
  feedbackDialog.addEventListener("click", function (event) {
    if (event.target === feedbackDialog) closeFeedbackDialog();
  });
  feedbackDialog.addEventListener("close", function () {
    if (state.feedbackReturnFocus && state.feedbackReturnFocus.isConnected) state.feedbackReturnFocus.focus();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "/" && !/input|select|textarea/i.test(document.activeElement.tagName)) {
      event.preventDefault();
      document.getElementById("global-search").focus();
    }
  });

  loadRoute(currentRoute(), false);
}());
