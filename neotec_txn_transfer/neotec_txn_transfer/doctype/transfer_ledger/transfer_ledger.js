frappe.ui.form.on("Transfer Ledger", {
	refresh(frm) {
		if (frm.doc.status !== "Uncertain") return;
		frm.dashboard.set_headline(__("The target did not answer for this document. Check the target, then record what you found."));
		const done = (target_name) =>
			frappe.call({
				method: "neotec_txn_transfer.api.resolve_uncertain",
				args: { ledger: frm.doc.name, target_name: target_name || null },
			}).then(() => frm.reload_doc());
		frm.add_custom_button(__("It was created"), () =>
			frappe.prompt({ fieldname: "target_name", fieldtype: "Data", reqd: 1, label: __("Document name on the target") },
				(v) => done(v.target_name), __("It was created")));
		frm.add_custom_button(__("It was not created"), () => done(null));
	},
});
