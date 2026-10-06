"""Job state, realtime progress and the job wrapper. Never writes Error Log rows."""

import functools
import traceback

import frappe

from .constants import REALTIME_EVENT, SETUP


def set_state(**values):
	frappe.db.set_single_value(SETUP, values)
	frappe.db.commit()


def publish(msg, **extra):
	frappe.publish_realtime(
		REALTIME_EVENT, {"msg": msg, **extra}, user=frappe.flags.get("ntt_user") or frappe.session.user
	)


def job(label):
	def deco(fn):
		@functools.wraps(fn)
		def wrapper(ntt_user=None, **kw):
			frappe.flags.ntt_user = ntt_user
			frappe.flags.mute_emails = True
			try:
				return fn(**kw)
			except Exception as e:
				frappe.db.rollback()
				tb = traceback.format_exc(limit=3)
				set_state(progress=f"{label} failed: {str(e)[:300]}")
				publish(f"{label} failed: {e}", failed=1, reload=1, trace=tb[-1500:])
			finally:
				frappe.flags.mute_emails = False
				frappe.db.rollback()
				set_state(job_running=0)
				publish(f"{label} finished", reload=1)

		return wrapper

	return deco
