#!/usr/bin/env python3
"""Structural guard for neotec_txn_transfer. Run before every push: python3 verify_tree.py"""

import ast
import json
import pathlib
import py_compile
import re
import sys

ROOT = pathlib.Path(__file__).parent
APP = ROOT / "neotec_txn_transfer"
MODULE = APP / "neotec_txn_transfer"
errors = []


def err(msg):
	errors.append(msg)


# 1. required files
for rel in ["pyproject.toml", "README.md", "RUN_GUIDE.md", "CHANGELOG.md", "license.txt",
	"neotec_txn_transfer/__init__.py", "neotec_txn_transfer/hooks.py", "neotec_txn_transfer/modules.txt",
	"neotec_txn_transfer/patches.txt", "neotec_txn_transfer/api.py", "neotec_txn_transfer/translations/ar.csv"]:
	if not (ROOT / rel).exists():
		err(f"missing {rel}")

# 2. hooks: zero-footprint whitelist
ALLOWED_HOOKS = {"app_name", "app_title", "app_publisher", "app_description", "app_email", "app_license",
	"required_apps", "before_uninstall"}
tree = ast.parse((APP / "hooks.py").read_text())
for node in tree.body:
	if isinstance(node, ast.Assign):
		for t in node.targets:
			if isinstance(t, ast.Name) and t.id not in ALLOWED_HOOKS:
				err(f"hooks.py defines '{t.id}' (not allowed: it would leave a footprint)")

# 3. doctypes
sys.path.insert(0, str(APP / "engine"))
const_src = (APP / "engine" / "constants.py").read_text()
app_doctypes = set(re.search(r"APP_DOCTYPES = \(([^)]*)\)", const_src).group(1).replace('"', "").replace(" ", "").split(","))
app_doctypes = {d for d in app_doctypes if d}
found = set()
for j in (MODULE / "doctype").glob("*/*.json"):
	d = json.loads(j.read_text())
	folder = j.parent.name
	found.add(d["name"].replace(" ", ""))
	if d["name"].lower().replace(" ", "_") != folder:
		err(f"{j}: name/folder mismatch")
	if d.get("module") != "Neotec Txn Transfer":
		err(f"{j}: wrong module")
	for k in ("track_changes", "track_seen", "track_views", "custom"):
		if d.get(k):
			err(f"{j}: {k} must be 0")
	for f in ("__init__.py", f"{folder}.py"):
		if not (j.parent / f).exists():
			err(f"{j.parent}: missing {f}")
	names = [f["fieldname"] for f in d["fields"]]
	if names != d["field_order"] or len(set(names)) != len(names):
		err(f"{j}: field_order mismatch or duplicate fieldnames")
if found != app_doctypes:
	err(f"APP_DOCTYPES {sorted(app_doctypes)} != doctype folders {sorted(found)}")

# 4. code rules
for py in APP.rglob("*.py"):
	try:
		py_compile.compile(str(py), doraise=True)
	except py_compile.PyCompileError as e:
		err(f"compile: {e}")
	src = py.read_text()
	if "log_error" in src:
		err(f"{py}: frappe.log_error would create Error Log rows")
	if py.name != "purge.py" and re.search(r"[\"'](Custom Field|Property Setter|Server Script)[\"']", src):
		err(f"{py}: touches customisation doctypes")

# 5. version consistency
ver = re.search(r'__version__ = "([^"]+)"', (APP / "__init__.py").read_text()).group(1)
if f"## {ver}" not in (ROOT / "CHANGELOG.md").read_text():
	err(f"CHANGELOG.md has no entry for {ver}")

if errors:
	print("verify_tree: FAIL")
	for e in errors:
		print(" -", e)
	sys.exit(1)
print(f"verify_tree: OK (v{ver}, {len(found)} doctypes)")
