// ScholiumRunner, continued: the message box and the queued messages

Object.assign(ScholiumRunner, {
  // the words in a pane's box, or a saved prompt's (text), go to the paper it shows, in the conversation the chosen
  // agent's messages about it go to; a saved prompt leaves the box as it is
  sendFromPane(pane, invert = false, text = null) {
    const typed = text === null, tab = pane.tab;
    // /compact compacts the conversation shown, on whichever tab; it is no wish for an annotation
    const compact = typed ? /^\/compact(?:\s+([\s\S]*))?$/.exec(String(pane.input.value || "").trim()) : null;
    if (compact && pane.item) {
      const view = this.viewOf(pane, pane.tab);
      this.compactFromPane(pane, (compact[1] || "").trim()).then(ok => {
        if (ok) this.clearInput(pane);
        // nothing the agent could compact yet (no session of it there), while the paper is free: a word under the box says
        // so, the words stay
        else if (!(view.shownKey && this.busy(view.shownKey))) this.sayUnderBox(pane, this.text("nothingToCompact"));
      }).catch(e => this.log("compact failed: " + e));
      return;
    }
    // the annotation tab without a session: the words go with a new annotation
    if (typed && pane.tab === "annotate" && !pane.annot.shownConv && !pane.busy) { this.annotateFromPane(pane); return; }
    const say = String(typed ? pane.input.value || "" : text).trim();
    if (!say || !pane.item || pane.sending === say) return;
    this.clearHeldFromPane(pane);
    if (pane.busy && this.followUpFor(pane, invert) === "steer" && this.steerable(pane)) {
      const quote = pane.tab === "chat" ? pane.quote : null, key = this.unsentKey(pane);
      pane.sending = say;
      this.steerFromPane(pane, say, quote)
        .then(ok => {
          if (!ok) return this.queueFromPane(pane, say, { typed });
          if (typed) this.clearSent(pane, tab, say, key);
          if (quote && pane.quote === quote) { pane.quote = null; this.paintQuote(pane); }
        })
        .catch(e => this.log("steer failed: " + e))
        .finally(() => { if (pane.sending === say) pane.sending = null; });
      return;
    }
    // a new message while the queue of the conversation shown is held asks first whether that queue goes, as Codex asks:
    // Clear queue drops it; Send message sends the new message and resumes the queue after it
    const waiting = this.queue.filter(j => this.shownQueued(pane, j));
    if (waiting.length && this.heldQueues.has(this.queueKey(waiting[0])) && !pane.busy) {
      const words = () => (typed ? String(pane.input.value || "").trim() : say);
      this.askInPlace(pane, this.text("clearQueueAsk", waiting.length), [
        [this.text("clearQueue"), "quiet small", () => {
          this.dropQueued(waiting);
          if (words()) this.queueFromPane(pane, words(), { typed }).catch(e => this.log("message failed: " + e));
        }],
        [this.text("sendMessage"), "small", () => {
          if (!words()) return;
          this.queueFromPane(pane, words(), { before: waiting[0], typed }).then(() => this.releaseQueue(waiting[0])).catch(e => this.log("message failed: " + e));
        }]]);
      return;
    }
    this.queueFromPane(pane, say, { typed }).catch(e => this.log("message failed: " + e));
  },

  // the words to the paper's conversation of the tab: sent, or queued behind the run under way (send); typed words
  // leave the box once they went
  queueFromPane(pane, say, { before = null, typed = true, confirmation = null } = {}) {
    const view = this.viewOf(pane, pane.tab);
    if (!confirmation) this.clearHeldFromPane(pane);
    const att = view.shownKey && this.attOf(pane.item.libraryID, view.shownKey);   // the paper of the tab's conversation
    const quote = !confirmation && pane.tab === "chat" ? pane.quote : null, tab = pane.tab, key = this.unsentKey(pane);
    if (typed) pane.sending = say;
    // a chat's message goes with the other papers above the box
    const papers = pane.tab === "chat" ? (pane.others || []).slice() : undefined;
    return this.send(att || pane.item, say, { kind: pane.tab, conv: view.shownConv, before, quote, papers, confirmation })
      .then(sent => {
        if (!sent) return false;
        if (typed) this.clearSent(pane, tab, say, key);
        if (quote && pane.quote === quote) { pane.quote = null; this.paintQuote(pane); }
        return true;
      })
      .finally(() => { if (pane.sending === say) pane.sending = null; });
  },

  // the box emptied of words that went, unless it holds others now (typed meanwhile, or another tab's); kept as the unsent
  // words of the tab they were sent from when another tab is shown now, they go there
  clearSent(pane, tab, say, key = "") {
    if (pane.tab === tab) { if (String(pane.input.value || "").trim() === say) this.clearInput(pane); }
    else if (key && String(this.unsent.get(key) || "").trim() === say) this.unsent.delete(key);
  },

  // the conversation a tab shows, compacted by the agent chosen (an annotation session by its own agent): Claude Code's
  // /compact in its session; false when it has no session yet or its paper is busy
  async compactFromPane(pane, focus = "") {
    if (!this.compactable(pane)) return false;
    const view = this.viewOf(pane, pane.tab);
    const att = this.attOf(pane.item.libraryID, view.shownKey);
    return !!att && this.send(att, focus, { compact: true, kind: pane.tab, conv: view.shownConv });
  },

  // whether the tab shows a conversation its paper is free to compact (its session is looked up when it is sent)
  compactable(pane) {
    const view = this.viewOf(pane, pane.tab);
    return !!pane.item && !!view.shownKey && !!view.shownConv && !this.busy(view.shownKey);
  },

  // the annotation tab's button: the tab's paper annotated anew, with the words in the box as extra wishes; over its
  // Scholium annotations it first asks in place, and Replace deletes them at once
  annotateFromPane(pane, { extra = String(pane.input.value || "").trim() } = {}) {
    const key = pane.annot.shownKey || pane.keys[0];
    const att = key && pane.item && this.attOf(pane.item.libraryID, key);
    if (!att) return;
    const agent = this.agent();
    const queued = this.annotationQueueSnapshot(key, agent);
    const go = (replace = false) => this.annotate([att], { extra, confirmed: true, replace, agent, queueConsent: { [key]: queued } })
      .then(n => { if (n && String(pane.input.value || "").trim() === extra) this.clearInput(pane); })
      .catch(e => this.log("annotate failed: " + e));
    const own = att.getAnnotations().filter(a => ScholiumToggle.isOwn(a)).length;
    if (!own && !queued.length) { go(); return; }
    const question = [queued.length ? this.text("redoQueued", queued.length) : "",
      own ? this.text("redoInline", own, this.clearedNotes([att]).length, !!this.groupOf(att.libraryID)) : ""].filter(Boolean).join(" ");
    this.askInPlace(pane, question, [[this.text("cancelButton"), "quiet small", () => {}],
      [this.text(own ? "replace" : "redoTitle"), "small danger", () => go(true)]]);
  },

  // a question above the box in place of a dialog: its line and its buttons, each of which closes it first
  askInPlace(pane, line, choices) {
    const doc = pane.doc, row = pane.confirmRow;
    const text = doc.createElement("span");
    text.className = "scholium-confirm-text";
    text.textContent = line;
    row.replaceChildren(text, ...choices.map(([label, cls, fn]) => this.paneButton(doc, label, () => { this.show(row, false); fn(); }, cls)));
    this.show(row, true);
  },

  // A report is approved only by its own pane action. Any new words cancel that pending action; a narrower request
  // may produce a new report, which has its own action. Neither path consumes words still in the message box.
  clearHeldFromPane(pane) {
    const view = this.viewOf(pane, pane.tab);
    if (view.shownKey && view.shownConv) this.heldBack.delete(`${view.shownKey}/${view.shownConv}`);
    this.paintHeld(pane);
  },

  heldConfirmationCurrent(confirmation) {
    if (!confirmation || typeof confirmation !== "object") return false;
    const { pane, key, conv, kind, held, keys } = confirmation;
    if (!pane || this.panes.get(pane.body) !== pane || pane.tab !== kind) return false;
    const view = this.viewOf(pane, kind);
    return view.shownKey === key && view.shownConv === conv && this.heldBack.get(`${key}/${conv}`) === held
      && JSON.stringify(held.keys) === keys;
  },

  paintHeld(pane) {
    const row = pane.heldRow;
    if (!row) return;
    const view = this.viewOf(pane, pane.tab), key = view.shownKey, conv = view.shownConv;
    const held = key && conv && this.heldBack.get(`${key}/${conv}`);
    const claimed = held && held.confirmation;
    if (claimed && !claimed.sending && ![...this.active].some(j => j.confirmation === claimed)
        && !this.queue.some(job => job.confirmation === claimed)) delete held.confirmation;
    if (!held || held.confirmation || this.busy(key)) { pane.heldAction = null; this.show(row, false); return; }
    // Keep the controls while this report stays visible; a claimed or hidden action gets a new token next time.
    if (pane.heldAction && this.heldConfirmationCurrent(pane.heldAction)) { this.show(row, true); return; }
    const confirmation = pane.heldAction = { pane, key, conv, kind: pane.tab, held, keys: JSON.stringify(held.keys) };
    const text = pane.doc.createElement("span");
    text.className = "scholium-confirm-text";
    text.textContent = this.text("heldConfirmLine", new Set(Object.values(held.keys).flat()).size);
    const keep = this.paneButton(pane.doc, this.text("heldKeep"), () => {
      if (!this.heldConfirmationCurrent(confirmation)) return;
      this.heldBack.delete(`${key}/${conv}`);
      this.refresh();
    }, "quiet small");
    const confirm = this.paneButton(pane.doc, this.text("heldConfirm"), () => {
      if (!this.heldConfirmationCurrent(confirmation) || held.confirmation || this.busy(key)) return;
      held.confirmation = confirmation;   // claimed synchronously, including across windows
      confirmation.sending = true;
      this.refresh();
      this.queueFromPane(pane, this.text("heldConfirmMessage"), { typed: false, confirmation })
        .then(sent => { if (!sent && held.confirmation === confirmation) delete held.confirmation; })
        .catch(e => {
          if (held.confirmation === confirmation) delete held.confirmation;
          this.log("confirmation failed: " + e);
        })
        .finally(() => { confirmation.sending = false; this.refresh(); });
    }, "small danger");
    row.replaceChildren(text, keep, confirm);
    this.show(row, true);
  },

  // the words in a message box are kept for the tab and the conversation they are typed to until they are sent, across
  // the section's renders and the agent chosen; an annotation session's for its agent. Of the tab shown unless another view
  // is named
  unsentKey(pane, view = this.viewOf(pane, pane.tab)) {
    if (!pane.item) return "";
    const agent = view.kind === "annotate" ? view.shownAgent || this.agent() : "";
    return `${pane.item.libraryID}/${pane.item.key}/${view.kind}/${agent}/${view.shownConv || ""}`;
  },

  keepUnsent(pane) {
    const key = this.unsentKey(pane);
    if (!key) return;
    if (String(pane.input.value || "").trim()) this.unsent.set(key, pane.input.value);
    else this.unsent.delete(key);
  },

  clearInput(pane) {
    pane.input.value = "";
    this.keepUnsent(pane);
    this.fitInput(pane);
  },

  // the box shows what was typed to the conversation now shown, when that is another one than before
  swapUnsent(pane, before) {
    const after = this.unsentKey(pane);
    if (after === before) return;
    pane.input.value = this.unsent.get(after) || "";
    this.fitInput(pane);
  },

  // a list of the section shown at its end stays at its end while what is below it (the queue, the box) grows
  keepAtEnd(pane, fn) {
    const lists = [pane.list, pane.annot && pane.annot.list].filter(Boolean);
    const ends = lists.map(l => { try { return l.clientHeight > 0 && l.scrollHeight - l.scrollTop - l.clientHeight < 40; } catch (e) { return false; } });
    try { return fn(); }
    finally { lists.forEach((l, i) => { if (ends[i]) { try { l.scrollTop = l.scrollHeight; } catch (e) {} } }); }
  },

  // the message box grows with its text, up to its maximum height; an empty box is as tall as its placeholder
  fitInput(pane) {
    this.keepAtEnd(pane, () => this.fitBox(pane));
  },

  fitBox(pane) {
    try {
      const input = pane.input;
      input.style.height = "auto";
      let height = input.scrollHeight;
      if (!input.value && input.placeholder) {
        input.value = input.placeholder;
        height = input.scrollHeight;
        input.value = "";
      }
      input.style.height = height + "px";
    } catch (e) {}
    this.paintSend(pane);
  },

  // the round button: ↑ sends (while the paper runs it queues or steers, as its tooltip says; a /compact the paper cannot
  // take now stays in the box); ■ stops
  paintSend(pane) {
    const text = String(pane.input.value || "").trim();
    const stop = pane.busy && !text;
    const compactNot = /^\/compact(?:\s|$)/.test(text) && !this.compactable(pane);
    pane.send.className = "scholium-round " + (stop ? "stop" : "send");
    pane.send.textContent = stop ? "■" : "↑";
    pane.send.disabled = !stop && !text;
    // its name is what it does; its tooltip says so too, or why /compact cannot go now
    const does = stop ? "stopTip" : !pane.busy ? "sendTip" : this.followUpFor(pane) === "steer" ? "steerTip" : "queueTip";
    pane.send.title = this.text(compactNot ? "compactNotNow" : does);
    pane.send.setAttribute("aria-label", this.text(does));
  },

  // the messages waiting in the conversation the tab shows, in the box above its text, as Codex shows them: a line while
  // the queue is held, the message being sent, each queued one, and one deleted a moment ago with Undo. Another
  // conversation's are not shown; they wait in their own
  paintQueue(pane) {
    const doc = pane.doc;
    const mine = j => this.shownQueued(pane, j);
    const jobs = this.queue.filter(mine);
    const held = jobs.length > 0 && this.heldQueues.has(this.queueKey(jobs[0]));
    const nodes = [], qids = [];
    if (held) {
      const line = doc.createElement("div");
      line.className = "scholium-queue-held";
      const t = doc.createElement("span");
      t.textContent = this.text("queueHeld");
      line.append(t, this.iconButton(doc, "play", this.text("queueGoOn"), () => this.releaseQueue(jobs[0])));
      nodes.push(line);
    }
    const sendingRun = [...this.runs.values()].find(r => !r.gone && mine(r.source) && !r.delivered);
    const sending = sendingRun ? sendingRun.source : null;
    if (sending) { nodes.push(this.queuedRow(pane, sending, { sending: true })); qids.push("sending " + sending.qid); }
    for (const j of jobs) { nodes.push(this.queuedRow(pane, j, { held })); qids.push(j.qid); }
    for (const [qid, r] of this.removedQueued) {
      if (mine(r.job)) { nodes.push(this.undoStrip(doc, this.text("queuedRemoved"), () => this.undoRemoveQueued(qid))); qids.push("removed " + qid); }
    }
    // drawn again only when what it shows changes (a redraw at each event of the run would take the focus from its buttons)
    const sig = JSON.stringify([qids, nodes.map(n => this.nodeSig(n))]);
    if (pane.queueSig !== sig) {
      pane.queueSig = sig;
      pane.queueBox.replaceChildren(...nodes);
    }
    this.show(pane.queueBox, nodes.length > 0);
  },

  // what a node drawn shows: its tags, classes, words, tooltips and states
  nodeSig(n) {
    if (!n || !n.localName) return n ? String(n.textContent || "") : "";
    return [n.localName, n.className, n.title || "", !!n.disabled, n.getAttribute("aria-label") || "", n.textContent,
            [...(n.children || [])].map(c => this.nodeSig(c))];
  },

  // a queued message: ⠿ to drag it, its words on one line (all of them once clicked), and Steer, ✕ and ⋯; Send instead of
  // Steer while its queue is held, Retry once it could not be sent
  queuedRow(pane, job, { held = false, sending = false } = {}) {
    const doc = pane.doc, row = doc.createElement("div");
    row.className = "scholium-queued" + (job.failed ? " failed" : "") + (sending ? " sending" : "") + (pane.openQid === job.qid ? " full" : "");
    const handle = doc.createElement("span");
    handle.className = "scholium-queued-handle";
    handle.textContent = "⠿";
    // the message being sent is out of the queue: neither dragged nor a place to drop
    if (!sending) {
      handle.setAttribute("draggable", "true");
      handle.addEventListener("dragstart", e => { pane.dragQid = job.qid; try { e.dataTransfer.setData("text/plain", job.qid); } catch (err) {} });
      handle.addEventListener("dragend", () => { pane.dragQid = null; });
      row.addEventListener("dragover", e => { if (pane.dragQid) e.preventDefault(); });
      row.addEventListener("drop", e => { e.preventDefault(); if (pane.dragQid) this.moveQueued(pane.dragQid, job.qid); pane.dragQid = null; });
    }
    const text = doc.createElement("span");
    text.className = "scholium-queued-text";
    if (job.failed) {
      const warn = doc.createElement("span");
      warn.className = "scholium-glyph warn";
      warn.setAttribute("role", "img");
      warn.setAttribute("aria-label", this.text("queuedFailedTip"));
      text.append(warn, doc.createTextNode(job.say));
      text.title = this.text("queuedFailedTip");
    } else text.textContent = job.say;
    text.addEventListener("click", () => { pane.openQid = pane.openQid === job.qid ? null : job.qid; this.paintQueue(pane); });
    row.append(handle, text);
    if (sending) {
      const s = doc.createElement("span");
      s.className = "scholium-queued-state";
      s.textContent = this.text("queuedSending");
      row.append(s);
      return row;
    }
    let first;
    if (job.failed) first = this.iconButton(doc, "retry", this.text("retry"), () => this.retryQueued(job.qid));
    else if (held) first = this.iconButton(doc, "play", this.text("queuedSend"), () => this.sendQueuedNow(job.qid));
    else {
      first = this.iconButton(doc, "steer", this.text("steerButton"), () => { this.steerQueued(pane, job.qid).catch(e => this.log("steer failed: " + e)); });
      const can = this.steerable(pane, job);
      first.disabled = !can;
      first.title = can ? this.text("steerRowTip") : !this.canSteer(job.agent) ? this.text("noSteer", this.agentName(job.agent)) : this.text("steerNotNow");
    }
    const remove = this.iconButton(doc, "trash", this.text("queuedRemove"), () => this.removeQueued(pane, job.qid));
    const more = this.paneButton(doc, "⋯", e => this.queuedMenu(pane, job, more, this.byKeyboard(e)), "quiet");
    more.title = this.text("moreTitle");
    more.setAttribute("aria-label", this.text("moreTitle"));
    more.setAttribute("aria-haspopup", "menu");
    row.append(first, remove, more);
    return row;
  },

  // a queued message's ⋯: back to the box to edit, or no queueing from now on (Steer instead, where the agent takes it)
  queuedMenu(pane, job, anchor, focus = false) {
    this.openPopover(pane, "queued", anchor, node => {
      node.setAttribute("role", "menu");
      this.arrowKeys(pane, node, this.menuItems(node));
      const item = (label, run, disabled = false) => {
        const b = pane.doc.createElement("button");
        b.className = "scholium-menu-item";
        b.setAttribute("role", "menuitem");
        b.textContent = label;
        b.disabled = disabled;
        b.addEventListener("click", () => { this.closePopover(pane); run(); });
        node.append(b);
      };
      item(this.text("queuedEdit"), () => this.editQueued(pane, job.qid));
      item(this.text("queueOff"), () => { Zotero.Prefs.set(this.pref + "followUpMode", "steer", true); this.refresh(); },
           !this.canSteer(job.agent) || this.followUpMode() === "steer");
    }, { focus });
  },
});
