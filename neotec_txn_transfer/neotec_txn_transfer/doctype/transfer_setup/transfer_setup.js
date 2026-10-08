const NTT = "neotec_txn_transfer.api.";

frappe.ui.form.on("Transfer Setup", {
	onload(frm) {
		frappe.realtime.off("ntt_progress");
		frappe.realtime.on("ntt_progress", (d) => {
			if (d.total) {
				frappe.show_progress(__("Transfer"), d.done, d.total, d.msg);
			}
			if (d.reload) {
				frappe.hide_progress();
				frm.reload_doc();
			}
			if (d.failed) {
				frappe.msgprint({ title: __("Job failed"), message: frappe.utils.escape_html(d.msg), indicator: "red" });
			}
		});
	},

	refresh(frm) {
		render_summary(frm);
		const p = frm.doc.phase || "Setup";
		const busy = frm.doc.job_running;
		const runnable = ["Scanned", "Dry Run Done", "Run Partial"].includes(p);
		const g = __("Transfer");

		if (busy) {
			const at = frm.doc.job_heartbeat ? ` (${frappe.datetime.comment_when(frm.doc.job_heartbeat)})` : "";
			frm.dashboard.set_headline(
				`${__("Job running")}: ${frappe.utils.escape_html(frm.doc.progress || "")}${at}`);
			frm.add_custom_button(__("Refresh Status"), () => check_job(frm, true));
			check_job(frm, false);
			return;
		}
		frm.add_custom_button(__("1. Scan"), () => start(frm, "scan"), g);
		if (runnable) {
			const push = frm.doc.source_mode === "Push to Remote Target";
			frm.add_custom_button(push ? __("2. Pre-flight Check") : __("2. Dry Run"), () => start(frm, "dry_run"), g);
			frm.add_custom_button(__("3. Run"), () =>
				frappe.confirm(__("Create and submit the documents in {0}?", [frm.doc.target_company]), () => start(frm, "run")), g);
		}
		if (["Run Done", "Run Partial", "Verified", "Verify Mismatch"].includes(p)) {
			frm.add_custom_button(__("4. Verify"), () => start(frm, "verify"), g);
		}
		if (p === "Verified" && frm.doc.source_mode !== "Remote Site") {
			frm.add_custom_button(__("Reverse Source (optional)"), () =>
				frappe.confirm(__("Cancel the migrated documents in {0}? ZATCA-reported invoices are skipped.", [frm.doc.source_company]),
					() => start(frm, "reverse")), g);
		}

		const r = __("Review");
		frm.add_custom_button(__("Unmapped Values"), () => frappe.set_route("List", "Transfer Map", { status: "Unmapped" }), r);
		frm.add_custom_button(__("All Mappings"), () => frappe.set_route("List", "Transfer Map"), r);
		frm.add_custom_button(__("Ledger"), () => frappe.set_route("List", "Transfer Ledger"), r);
		frm.add_custom_button(__("Clear Non-Core Unmapped"), () =>
			call("clear_unmapped").then((n) => frappe.show_alert(__("Unmapped remaining: {0}", [n]))), r);

		const f = __("Finish");
		frm.add_custom_button(__("Download Reconciliation CSV"), () => download_csv(frm), f);
		frm.add_custom_button(__("Finalize and Purge"), () => finalize(frm), f);
	},
});

function check_job(frm, verbose) {
	call("job_status").then((st) => {
		if (st.healed) {
			frappe.msgprint(__("The previous job stopped without finishing. The lock was cleared; start the step again."));
			frm.reload_doc();
		} else if (verbose) {
			frm.reload_doc();
		}
	});
}

function call(method, args) {
	return frappe.call({ method: NTT + method, args: args || {} }).then((r) => r.message);
}

function start(frm, action) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the form first"));
		return;
	}
	call("start", { action }).then(() => frm.reload_doc());
}

function download_csv(frm) {
	call("reconciliation_csv").then((csv) => {
		const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
		const a = document.createElement("a");
		a.href = URL.createObjectURL(blob);
		a.download = `transfer-reconciliation-${frappe.datetime.now_date()}.csv`;
		a.click();
		URL.revokeObjectURL(a.href);
	});
}

function finalize(frm) {
	frappe.prompt(
		[{ fieldname: "confirm", fieldtype: "Data", reqd: 1,
			label: __("Type the target company abbreviation to confirm"),
			description: __("Download the reconciliation CSV first. This permanently deletes all transfer data.") }],
		(v) => call("finalize", { confirm: v.confirm }).then((msg) => {
			frappe.msgprint(msg);
			frm.reload_doc();
		}),
		__("Finalize and Purge"),
		__("Purge")
	);
}

function render_summary(frm) {
	const w = frm.get_field("summary_html").$wrapper;
	let s = {};
	try { s = JSON.parse(frm.doc.summary_json || "{}"); } catch (e) { s = {}; }
	if (!s.counts) {
		w.html(`<p class="text-muted">${__("Run Scan to see what will be transferred.")}</p>`);
		return;
	}
	const esc = frappe.utils.escape_html;
	const rows = Object.entries(s.counts).map(([dt, c]) =>
		`<tr><td>${esc(__(dt))}</td><td class="text-right">${c.found}</td><td class="text-right">${c.pending}</td><td class="text-right">${c.excluded}</td></tr>`).join("");
	const blockers = (s.global_blockers || []).map((b) => `<li>${esc(b)}</li>`).join("");
	const blocked = (s.blocked || []).map((b) => `<li>${esc(b)}</li>`).join("");
	w.html(`
		<table class="table table-bordered table-sm" style="max-width:640px">
			<thead><tr><th>${__("Document")}</th><th class="text-right">${__("Found")}</th>
			<th class="text-right">${__("Queued")}</th><th class="text-right">${__("Excluded")}</th></tr></thead>
			<tbody>${rows}</tbody>
		</table>
		<p>${__("Source")}: <b>${esc(s.source || "")}</b> &rarr; ${__("Target")}: <b>${esc(s.target || "")}</b> (${esc(__(s.mode || ""))})</p>
		<p>${__("Unmapped values at scan")}: <b>${s.unmapped}</b> &middot; ${__("Documents with cleared links")}: <b>${s.broken_links}</b></p>
		${blockers ? `<div class="alert alert-danger"><b>${__("Blockers")}</b><ul>${blockers}</ul></div>` : ""}
		${blocked ? `<details><summary>${__("Blocked documents")}</summary><ul>${blocked}</ul></details>` : ""}
	`);
}
