# Run Guide — Neotec Txn Transfer v1.1.0

## English

### Before you start
1. Take a full site backup.
2. Make sure the target company exists with its chart of accounts, cost centers, warehouses, tax templates, fiscal years and a company address. Same base currency as the source.
3. Disable ZATCA submission for the target company for the whole run window (or point it at simulation). The tool strips e-invoice fields, but it cannot switch your ZATCA app off.
4. Remote mode only: create an API key on the source site for a user with read access to the transactions, GL Entry, Stock Ledger Entry and Serial and Batch Bundle.
5. Run the transfer in a quiet window. Back-dated stock documents trigger valuation reposting.

### Choosing a mode
- **Same Site**: both companies are on this site.
- **Remote Site (pull)**: install on the target site; it reads from the source site over the API.
- **Push to Remote Target**: install on the source site; it sends to the target site over the API. The target site needs no app; only an API user that can create and submit Sales/Purchase Orders, Delivery Notes, Purchase Receipts, Invoices and Payment Entries, and read Customer, Supplier, Item, Account, Warehouse, Cost Center, Address, GL Entry and Stock Ledger Entry.

In push mode, step 5 is a **Pre-flight Check** instead of a Dry Run: nothing is written to the target, so document-level validations (closed periods, fiscal years, credit limits, negative stock) only run at Run time. Each document still goes in as one request, so a failure leaves nothing behind on the target and the run can be repeated. For a large transfer, push to a staging copy of the target first.

If a document shows **Uncertain** in the ledger, the target may have created it. Search the target for it, then open the ledger row and choose *It was created* (enter its name) or *It was not created*, and press Run again.

### Steps
1. **Install** the app on the site (Frappe Cloud: add the app to the bench group, deploy, then install on the site).
2. Open **Transfer Setup** (`/app/transfer-setup`). Fill source, target, date range and the document types. Save.
3. **Scan.** Reads the source, builds the dependency order, takes a snapshot of totals, GL and stock per document, and fills **Transfer Map**. Nothing is created in the target.
4. **Review mappings.** Open *Unmapped Values*. Accounts, warehouses and cost centers are matched by swapping the company abbreviation; fix anything left. For non-essential links (projects, employees, POS profiles) you can use *Clear Non-Core Unmapped*.
5. **Dry Run.** Creates and submits every pending document inside a transaction that is always rolled back. Check the *Dry Run* column in the Ledger and fix causes (closed periods, credit limits, missing fiscal year, negative stock). Repeat until clean.
6. **Run.** Each document commits on its own. If anything fails, fix it and press Run again; completed documents are never repeated.
7. **Verify.** Compares grand total, outstanding, GL debit and stock quantity per document against the source snapshot. Investigate every *Mismatch*.
8. **Reverse Source** (optional, same-site only). Cancels the source documents in reverse order. Sales invoices already reported to ZATCA are skipped; issue credit notes for those manually.
9. **Download Reconciliation CSV.** This file is your only audit record of source → target names. Store it with the project files.
10. **Finalize and Purge.** Type the target company abbreviation. All transfer data, mappings, stored credentials and related logs are deleted.
11. **Uninstall** the app from the site, then remove it from the bench group and deploy. Remote mode: revoke the API key on the source site.

### Limits in v1.1.0
- Base currency must be identical in both companies.
- A row that consumes several batches in one line is blocked; split it in the source first.
- Same-site serialized stock: if a serial number is still in a source warehouse, the target receipt will collide. The dry run shows this; reverse or transfer that stock first.
- Advances allocated inside invoices are rebuilt from the Payment Entry side; Journal Entry advances are not carried.
- Links to documents outside the transfer (Quotation, Material Request, Journal Entry, Pick List) are cleared.

---

## العربية

### قبل البدء
1. خذ نسخة احتياطية كاملة للموقع.
2. تأكد من وجود الشركة الهدف بدليل الحسابات ومراكز التكلفة والمستودعات وقوالب الضرائب والسنوات المالية وعنوان الشركة، وبنفس العملة الأساسية للمصدر.
3. أوقف الإرسال إلى زاتكا للشركة الهدف طوال فترة النقل. الأداة تستبعد حقول الفاتورة الإلكترونية لكنها لا تستطيع إيقاف تطبيق زاتكا.
4. في النمط الخارجي فقط: أنشئ مفتاح API في موقع المصدر لمستخدم يملك صلاحية قراءة المستندات وقيود الأستاذ العام وحركات المخزون ودفعات الأرقام التسلسلية.
5. نفّذ النقل في وقت هادئ، لأن المستندات المخزنية بتواريخ سابقة تعيد احتساب تقييم المخزون.

### اختيار النمط
- **نفس الموقع**: الشركتان على هذا الموقع.
- **موقع خارجي (سحب)**: يُثبَّت التطبيق على موقع الهدف ويقرأ من موقع المصدر عبر API.
- **دفع إلى موقع هدف**: يُثبَّت التطبيق على موقع المصدر ويرسل إلى موقع الهدف عبر API، ولا يحتاج موقع الهدف أي تطبيق؛ فقط مستخدم API يملك صلاحية إنشاء واعتماد المستندات وقراءة البيانات الأساسية والقيود وحركات المخزون.

في نمط الدفع تكون الخطوة 5 **فحصاً مسبقاً** بدلاً من التشغيل التجريبي، ولا يُكتب أي شيء في الهدف. يُرسل كل مستند في طلب واحد، فإذا فشل لا يبقى منه شيء في الهدف.

إذا ظهر مستند بحالة **غير مؤكد** في السجل فقد يكون أُنشئ في الهدف. ابحث عنه في الهدف ثم اختر من سجل النقل *تم إنشاؤه* أو *لم يُنشأ* واضغط تنفيذ مرة أخرى.

### الخطوات
1. **التثبيت**: أضف التطبيق إلى مجموعة البنش في Frappe Cloud ثم انشره وثبّته على الموقع.
2. افتح **إعداد النقل** (`/app/transfer-setup`) وأدخل المصدر والهدف والفترة وأنواع المستندات ثم احفظ.
3. **الفحص**: يقرأ المصدر ويرتب المستندات حسب الاعتماد ويحفظ لقطة للإجماليات والقيود والمخزون ويملأ **مطابقة النقل**. لا يُنشأ أي شيء في الهدف.
4. **مراجعة المطابقات**: افتح *قيم غير مطابقة*. تتم مطابقة الحسابات والمستودعات ومراكز التكلفة باستبدال اختصار الشركة، وأكمل الباقي يدوياً. للروابط غير الأساسية يمكن استخدام *مسح غير المطابق*.
5. **التشغيل التجريبي**: ينشئ ويعتمد كل المستندات داخل معاملة يتم التراجع عنها دائماً. راجع عمود *التشغيل التجريبي* في السجل وعالج الأسباب ثم أعد التشغيل حتى يصبح نظيفاً.
6. **التنفيذ**: كل مستند يُحفظ مستقلاً. عند الفشل عالج السبب واضغط تنفيذ مرة أخرى، ولن تتكرر المستندات المنجزة.
7. **التحقق**: يقارن الإجمالي والرصيد المستحق ومدين القيود وكميات المخزون لكل مستند مع لقطة المصدر. راجع كل حالة *عدم تطابق*.
8. **إلغاء المستندات في المصدر** (اختياري، نفس الموقع فقط): يلغي مستندات المصدر بترتيب عكسي، ويتخطى الفواتير المرسلة إلى زاتكا، ويلزم إصدار إشعارات دائنة لها يدوياً.
9. **تنزيل ملف المطابقة CSV**: هذا الملف هو السجل الوحيد لربط أرقام المصدر بالهدف، فاحفظه مع ملفات المشروع.
10. **إنهاء وحذف كل البيانات**: اكتب اختصار الشركة الهدف. تُحذف كل بيانات النقل والمطابقات وبيانات الاعتماد والسجلات المرتبطة.
11. **إزالة التطبيق** من الموقع ثم من مجموعة البنش وانشر. في النمط الخارجي: ألغِ مفتاح API في موقع المصدر.

### حدود الإصدار 1.1.0
- يجب أن تكون العملة الأساسية واحدة في الشركتين.
- السطر الذي يستهلك أكثر من دفعة (Batch) يُحجب، فقسّمه في المصدر أولاً.
- في نفس الموقع: إذا كان رقم تسلسلي ما زال في مستودع المصدر سيتعارض الاستلام في الهدف، ويظهر ذلك في التشغيل التجريبي.
- السلف المخصصة داخل الفواتير يُعاد بناؤها من جهة سند الدفع، ولا تُنقل سلف قيود اليومية.
- الروابط إلى مستندات خارج النقل (عرض سعر، طلب مواد، قيد يومية، قائمة انتقاء) يتم مسحها.
