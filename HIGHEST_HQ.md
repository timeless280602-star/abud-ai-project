# The Highest HQ — foundation deployment

This is the initial feature branch, not a production deployment. Do not replace a newer VPS checkout with the older main branch. Review and merge/rebase the change against the branch actually running on the VPS. Back up the ABUD data directory before rebuilding.

- Public entrance: https://abud.web.id/highest/
- No ABUD/Discord identity is accepted by HQ.
- New signups are community only. Admin review with rank and position is mandatory for internal access.
- Admin role is distinct from IC rank. An admin can manage membership without becoming an approved IC member.
- Original user-supplied logo must be copied to app/highest_web/logo.png before image build.
- Database: /app/data/highest.db by default, persisted by existing ABUD data volume.
- Set HIGHEST_ORIGIN=https://abud.web.id (or ensure ABUD_BASE_URL matches).
- Set HIGHEST_YOUTUBE_API_KEY and HIGHEST_LIVE_INTERVAL (default 3600 seconds). YouTube search uses 100 quota units per check per channel, so configure interval/quotas for roster size.
- TikTok requires a real HTTPS provider endpoint and bearer token: HIGHEST_TIKTOK_STATUS_URL and HIGHEST_TIKTOK_STATUS_TOKEN. Adapter expects GET username query parameter and JSON live boolean. No provider is included or verified. Failed checks show unavailable.
- After creating an HQ account, VPS operator grants the first HQ admin using:
  docker exec abud-api python -c "from app.highest import bootstrap_admin; bootstrap_admin('your_username')"
- Rebuild only the API after merging, installing the original logo, and configuring environment:
  docker compose up -d --build --no-deps abud-api
- Smoke-test direct HQ login, ABUD homepage button, pending membership 403, approval, revocation, rank ordering and live status. Phase 2 includes rank-scoped treasury, inventory/vault, completed crafting, IC case files and audit. Admin must grant each rank explicit module permission. Treasury uses two different members for submission and review. Inventory and crafting are manual IC ledger records, not synced to the game server. Advanced community, evidence attachments, crafting approvals and remaining planned modules are not implemented.

- Rank All Access uses a wildcard grant for all registered internal operations, including future modules that use the same permission guard. Disable it to restore the existing custom module permissions. It never grants website administration or bypasses membership approval or the no-self-review rule.

- Phase 3 initial community features: moderated moments and POVs, creator verification, creator studio, lore/character/recap wiki, moderated text feed, clip likes/bookmarks, streamer follow and all-time clip leaderboard. Spoiler markers are UI disclosure, not authorization. No external analytics, actual live notifications, comments, uploads or creator channel ownership checks yet. Admin verifies creator identity manually.

- Phase 4 includes versioned organizational RP records, asset registry, activity notes/schedule fields, SOP acknowledgement, case reference text and relationship rows, scoped approval overview, and per-tab Streamer Mode (static safe screen, not an authorization boundary or OBS guarantee). Binary evidence upload, drag-and-drop relationship diagram, calendar view and full approval workflow remain planned.

- Business POS: grant business for order work and business_prices for catalog management. Write creates orders and progresses ordinary status; Approve completes/cancels. Optional stock and treasury settlement requires corresponding write rights at creation and completion. Prices are immutable snapshots on orders. No stock reservation, real payments, tax or actual FIFO costing; margin is estimated from catalog buy price. POS supports either an all-items discount (percentage or one fixed cart amount) or discounts on selected item lines (percentage or fixed amount per unit). Discounts are mutually exclusive, capped at each eligible subtotal, snapshotted on order creation, and reflected in order totals, treasury requests and analytics. Treasury remains pending for independent approval.

- Business workflow simplified to exactly Pending → Ready (Butuh pengantaran) → Completed. Completion timestamp and immutable order-line price snapshots feed the analytics archive. Legacy cancelled orders are hidden from active lists; legacy confirmed/processing records are normalized to Pending.
- Business Intelligence & Analytics has a separate rank permission. Reporting includes completed-order revenue, purchases, estimated gross profit and margin, average order value, group and product performance, date-filtered trend, pending/ready delivery pipeline, inventory input/output by movement type/item, internal transfers separately, stock and low-stock snapshots.
- Inventory movement valuation is captured when a business order completes using the order's locked unit-price snapshot. Other movements without price snapshots remain quantity-only and are flagged. Gross profit is estimated from buy-price snapshots, not FIFO/weighted-average accounting.

- POS discount calculation: percentage discounts are rounded to the nearest whole in-game dollar; all-items fixed discounts are a single amount across the cart and are allocated proportionally across lines. Selected-item fixed discounts are per unit and multiply by quantity. Discounts cannot be stacked between all-items and selected-item modes. Sales analytics use net revenue after discounts; purchase analytics and treasury outflows use net purchase totals.

- Business discounts are rank-governed. Admins configure allowed scope (none/all-items/selected-items/both), direct percentage limit, and direct fixed-discount ceiling per order. All discounted orders require a reason; requests above the direct limit additionally require manager approval. Pending requests block the order from moving to Ready; approval applies the saved discount snapshot, while rejection removes the discount and allows the order to continue at full price. Reviewers cannot approve their own requests.
- Discount approvals use the separate `business_discounts` rank permission module. All Access includes the module but does not bypass the rank's discount policy.

- A pending discount request hides order progression controls in the POS as well as being blocked by the API. Rejection resets the effective order total to full price while preserving the requested discount amount for review history.

- No cashier shifts, opening/closing sessions, or shift reconciliation. Every order is automatically and immutably attributed to the authenticated account that created it (`actor`). Later status changes are separately recorded in order history under the acting account. Business order lists can be filtered by creator, and Business Intelligence includes per-member transaction counts, status breakdown, completed sales/purchase values, discounts, and estimated gross profit. Financial contribution remains attributed to the original order creator, not the person who later updates its status.

- Business documents: every order receives a unique invoice number at creation, tied to the order ID and issue date. Completed orders automatically receive a separate receipt number and completion timestamp; the receipt records the member who completed the order. Legacy orders are backfilled during initialization. Item names and document creator names are snapshotted so later profile or catalog edits do not rewrite historical documents.
- Invoice and receipt documents are available from each order. The printable A4 layout includes customer/supplier group, order reference, creator, transaction lines, quantities, unit prices, discounts, totals, notes, and relevant status. Receipts distinguish order completion from treasury settlement; a pending or rejected treasury entry is never labelled as paid. Browser print supports saving the document as PDF. Documents are internal FiveM roleplay economy records, not real-world invoices or proof of payment.


- Business Profile & Document Branding: admins manage multiple active/inactive business-unit profiles with unique unit codes, organization identity, business description, IC contact, HTTPS logo URL, invoice/receipt prefixes, classic/executive/minimal print templates, accent color and custom footer. The POS selects an active issuing unit for each order. The selected identity is snapshotted at order creation; profile edits never rewrite historical invoice/receipt branding or numbering. One active default profile is required for new orders. Logos are referenced by public HTTPS URL; binary image upload is not included.


- Business Document Center: searchable invoice and receipt archive with business-unit, document-type, creator, issue-period and date-range filters; monthly archive summaries; paginated results; repeatable branded print view; and direct PDF downloads generated by the API. Invoices are listed when issued and receipts when orders reach Completed. PDF files are generated on demand from the saved order and business-branding snapshot, so historical documents retain their original identity.


- Intelligence & Case Evidence Vault: case-scoped PDF and image uploads (PDF, PNG, JPG, WEBP; 15 MB maximum) stored outside the public web root with random server-generated filenames. The API validates file signatures against extensions, snapshots metadata, records SHA-256, and verifies the stored bytes before every preview/download. PDF files are forced to download; supported images can be previewed inline. Each upload, preview, download and integrity failure appends a hash-linked chain-of-custody event and HQ audit entry. There is no delete/replace endpoint. Configure HIGHEST_EVIDENCE_PATH to a persistent writable directory; the default is a highest_evidence directory beside the HQ database.

- Interactive Case Relationship Workspace: each case receives a root node; character, vehicle, organization and evidence nodes are case-scoped. Members with cases:write can create nodes, connect them with labelled relationships and drag nodes to persist their diagram coordinates. Evidence uploads automatically create evidence nodes and can be linked to a character, vehicle or organization. Existing text-only relationship rows are migrated into graph nodes/edges and remain available as legacy notes.


- Visual Operations Calendar: a dedicated, database-backed schedule for internal operations with Month, Week and List views; division, category and status filters; activity title, agenda, responsible person, location, WIB start/end time and configurable reminder lead time. Schedule creation and edits require the existing rank-scoped `operations` write permission; viewing requires `operations` view permission; archiving requires approval permission. Each save creates a revision snapshot and an HQ audit entry. Dates are normalized to Asia/Jakarta (+07:00). Reminder lead times are persisted as schedule metadata; background/push delivery is not enabled by this feature.


- Full Approval Workflow: generic approval requests can be submitted by members with write permission for the selected module. Administrators configure ordered rank approval steps; every configured rank must already hold that module's approve grant. Reviewers must be different from the requester, must still hold approve permission, and can act only at their assigned current step. Approval advances to the next step; rejection closes the request; the requester may cancel while pending. Each decision, note, actor and delegation is stored in the approval action history and HQ audit log.
- Approval delegation: an approver may delegate a module's review work to another approved member who already has approve permission for that module. Delegations can be activated or revoked and delegated decisions identify both the acting reviewer and delegating approver.
- If no rank route is configured for a module, any approved member with that module's approve permission may complete the request in one step. The generic approval workflow records decisions and references; it does not itself execute or mutate the referenced business, inventory, treasury or case operation. Existing treasury and business discount approvals retain their dedicated transactional review flows.


- Advanced Inventory Costing: every inventory item supports FIFO or moving weighted-average costing. Cost layers are stored per vault and item; issues calculate cost from the selected method, and transfers consume source layers and carry the same cost into the destination. Weighted-average items maintain a moving pooled cost per vault. Completed business purchase orders create valued receipt layers from the locked net purchase snapshot; completed sales consume layers and record actual COGS. Crafting transfers consumed ingredient cost into the output item's production layer.
- Multi-stash / multi-vault inventory: the existing vault model supports any number of independently named storage locations (for example, Brankas 1, Brankas 2, Brankas 3). Transfers are atomic, require distinct valid source and destination stashes and sufficient source stock, and create paired movement records with a shared reference, counterparty stash, actor, timestamp, quantity and preserved cost value.
- Inventory valuation and reconciliation: per-stash/item quantity, carrying value, average unit cost and unvalued opening quantity are available. Stocktake adjustments record the physical counted quantity; positive adjustments require a unit cost and negative adjustments consume existing cost layers. Legacy balances are migrated as explicitly unvalued layers until an administrator records an opening valuation; they are not silently priced using a mutable catalog price.
- Inventory movement deposits require a unit acquisition cost. Withdrawals, crafting consumption, sales and transfers derive their issue value from the active costing layers. Internal transfers are excluded from business input/output totals so they do not inflate operating flows.
- Business analytics now uses actual inventory issue cost for completed sales with costed movements, falling back to the historical catalog buy-price estimate for legacy sales without a costed stock issue. The COGS basis is exposed as actual, mixed, or estimated.


- HQ Notification Center & Live Notifications: each approved member has a private in-app inbox with unread counts, per-item read state and mark-all-read. Inbox access is scoped to the authenticated member; notifications are never exposed across accounts.
- Approval alerts: the current rank-based approval reviewers and eligible active delegates are notified when a request reaches their step. The requester is notified when the workflow is finally approved or rejected. Treasury submitters receive the final posted/rejected decision; eligible treasury reviewers receive new review alerts.
- Operations reminders: calendar reminder preferences are now delivered by a background worker at the configured lead time. The event creator receives the reminder; when the free-text owner exactly matches an approved member's username or display name, that member is included as well. Reminder timestamps are displayed in WIB.
- Delivery is idempotent per event revision and recipient. Editing a schedule creates a new revision and therefore a distinct reminder; retries and repeated worker cycles do not duplicate the same reminder.
- The web inbox polls for unread/new notification changes every 30 seconds while the internal HQ page is open. This is in-app delivery only; no email, Discord DM, mobile push, or browser push provider is configured.
- Notifications are retained in the HQ database and are not automatically deleted when read. Notification history is private to each user.


## Asset & Property Management

- The dedicated Assets module tracks vehicles, property, equipment and other organizational assets using unique asset tags. Records include description, make/model, serial and plate references, location, condition, acquisition date/cost, custodian, and optional links to Inventory items and IC Cases.
- Acquisition and disposal are request/reviewer workflows. A requester cannot approve their own request; reviewers require the module's `approve` permission. Acquisition approval creates the asset and a separate pending Treasury cash-out entry when the acquisition has a non-zero cost. Treasury approval remains independent, so the posted balance is unchanged until the cash-out is approved.
- Asset assignment and return update the custodian, location and available/assigned state. Each lifecycle operation is recorded in the asset history and HQ audit log.
- Maintenance work orders record task, description, provider, estimated cost, actor, timestamps and open/completed state. Opening maintenance changes the asset state to maintenance; completion restores assigned or available state based on its custodian. Retired assets cannot be assigned or sent to maintenance.
- The Assets dashboard provides asset status counts, the asset register, acquisition/disposal approval queue, lifecycle history and maintenance history. Access follows the existing rank-based module grants.


## Executive Intelligence Dashboard

- Internal HQ includes a read-only Executive Intelligence Dashboard backed by live database aggregates; it does not seed, fabricate, or mutate operational records.
- The dashboard shows organization membership totals and only the operational sections granted to the signed-in member's rank: Treasury, Inventory, Assets, Operations Calendar, Case Files, and approval queues.
- Treasury figures use posted ledger entries; pending transactions are reported separately. Inventory valuation uses the existing cost-layer valuation engine and explicitly reports unvalued units. Asset valuation is the recorded acquisition cost of non-retired assets, not a depreciation-adjusted market valuation.
- Operations metrics are sourced from the persistent calendar event table. Case metrics include Evidence Vault file and custody-event totals when the Evidence Vault schema is available; integrity failures are shown as recorded events, not inferred incidents.
- Organization-wide audit event details and the seven-day flagged-event summary are administrator-only. Other ranks do not receive raw audit records through this endpoint.
- The dashboard is read-only and does not change the underlying Treasury, Inventory, Asset, Calendar, Case, Evidence, or approval records.


## Advanced Financial Reporting

- A separate financial_reports rank permission controls access to consolidated reporting and monthly budgets. view reads reports, write also manages budgets, and approve inherits write access through the permission hierarchy.
- Cash flow, monthly totals, category and division breakdowns use posted Treasury ledger entries only. Pending and rejected transactions are excluded. Internal account transfers (transfer_ref set) are excluded from income and expense totals; they do not represent organizational revenue or spend.
- Opening and closing balances use the consolidated posted ledger balance. Monthly comparisons use the immediately preceding period with the same number of months.
- Division attribution uses the transaction creator's current approved rank because the existing Treasury ledger does not retain a historical rank snapshot. Historical rank attribution is not implied.
- Monthly budgets can be scoped to an organization, division/rank, category, or a division/category combination. Each budget row shows actual posted expenses matching that scope, variance, and utilization. The aggregate budget allocation is displayed separately to avoid double-counting overlapping scopes.
- Completed POS orders are shown in a separate operating-performance section, not added to Treasury cash flow. Sales, purchases and estimated gross profit are based on completed orders; estimated COGS uses the order-line buy price. POS totals are not asserted to be settled cash.
- Exports are available as PDF, XLSX and CSV. Reports cover up to 36 months and use WIB month boundaries.
- The Excel export uses openpyxl; install it from requirements.txt.


## Advanced Intelligence Analytics

- The Case Files workspace includes a read-only, permission-scoped intelligence analytics view for fictional in-character roleplay records.
- Overview metrics summarize case statuses, case-scoped graph entities and links, Evidence Vault files, custody events, recorded integrity failures and assets linked to cases.
- Recurring-entity analysis uses exact normalized entity type and name matches across different cases. These are candidate overlaps for manual review, not identity resolution or proof that two records refer to the same character, vehicle or organization.
- Candidate case overlaps, relationship-label patterns, within-case node degree, most-active case files and a WIB activity timeline are surfaced for analyst review.
- Timeline counts are derived from persisted case creation, case notes, graph node/link creation, evidence upload and custody events. No missing activity or event chronology is inferred.
- The analytics endpoint requires the existing cases view permission and is read-only. It does not create cross-case links, modify evidence, or change case records.
- Analytics are limited to fictional IC roleplay records. Do not enter or infer real-world personal information.


## Community review — current scope and verified behavior

- Community routes are authenticated but remain separate from approved internal HQ access. Community content is stored in its own social tables and does not query case, evidence, treasury, inventory or other internal IC records.
- Public clips, moments, POVs, wiki entries, feed posts and verified creator profiles are returned only after publication/approval. Creator verification remains a manual administrator review of the submitted public profile URL.
- Clip likes and bookmarks are idempotent per member/clip. Streamer follows are stored per member/streamer. The all-time leaderboard counts published clips and website likes only.
- POV attribution distinguishes the member submitting the POV from the member who owns the linked clip. Wiki entries and moderation queues expose the submitting member for accountability.
- Moderators cannot approve or reject their own pending community submissions. Creator verification already prevents self-review.
- CI covers social moderation, creator verification, POV publication prerequisites, clip likes/bookmarks, community permissions, author attribution and self-review boundaries.

Known community limitations retained for a future phase:
- No user-facing content reporting, published-content takedown workflow, comments/replies, or direct member-to-member messaging.
- No notifications to authors when content is approved/rejected, and following a streamer does not yet send a live-start notification.
- Creator channel ownership is not automatically verified; administrators perform manual review.
- No native media uploads or external-platform view analytics. Clip engagement metrics are website likes only.
- YouTube live polling uses the Data API search endpoint (100 quota units per channel check); size the interval and roster against the project's API quota. TikTok live status requires an operator-supplied HTTPS provider and bearer token; no provider is bundled.
- The current moderation queue is a pending-submission review queue, not a full trust-and-safety console for already-published content.



## Community Trust & Safety — implementation

- Added authenticated member reports for published clips, Moments, POVs, Wiki entries and Community Feed posts. Reports require a category and accept optional context; members cannot report their own content.
- Added one-open-report-per-member/content enforcement, database uniqueness protection, and per-member rate limiting.
- Added a moderator-only report queue with reporter identity, content author, content preview, category and report context.
- Moderators can dismiss reports or remove content from public views. Removed content is soft-hidden (not deleted) and can be restored by an administrator.
- Report decisions are transactional, audited, and protected against duplicate decisions. Moderators cannot remove or restore their own content.
- Members can view their own report history and resolution notes in Creator Studio.
- Added automated tests for duplicate reports, invalid categories, self-report prevention, queue attribution, takedown, restore, dismissal and closed-report behavior.
- This is an initial moderation workflow, not a full appeal/strike system. It does not yet provide automatic notifications, member appeals, moderator assignment/SLA, or automated content scanning.


Community Engagement & Social Interaction:
- Added comment threads to published clips, Moments, POVs, Wiki entries and Community Feed posts.
- Each content item supports top-level comments and one-level replies; nested replies are rejected to keep discussions readable.
- Members can like/unlike comments. Duplicate likes are prevented by a composite database key.
- Comment authors can soft-delete their own comments. Deleted comments retain thread context for replies but their body is cleared; likes are removed. Administrators can remove comments when necessary.
- Notifications are delivered through the existing private HQ notification store for new comments, replies and comment likes. Community activity endpoints expose only the signed-in member's own social notification records, not internal approval or operations notifications.
- Added a dedicated Community Activity tab with unread counts, individual read state and mark-all-read.
- All comment creation, replies, likes and deletes are authenticated; comment creation is rate-limited. Content must still be published when a comment is read or created.
- No nested reply chains, image/GIF attachments, mentions, emoji reactions, or edit-history feature are included in this iteration.


Content approvals and creator integrations:
- Clip approvals/rejections and Moments, POVs, Wiki and Community Feed approvals/rejections create private HQ inbox notifications for the submitting member.
- Streamer live alerts are sent to members who follow that streamer, only on a transition into live. Repeated polling while a stream remains live does not re-notify.
- YouTube channel ownership is verified automatically by a one-time challenge placed in the public channel description and checked through YouTube Data API.
- TikTok channel ownership uses a configurable profile-verification adapter. It must return JSON with `username` and `bio` (or `description`) for the requested username.
- Native clip media supports JPG/JPEG, PNG, WEBP, GIF, MP4 and WEBM. Image uploads are limited to 10 MB; videos to 50 MB. Uploads are private until approved; stored files use random names and SHA-256 fingerprints.
- YouTube view counts use YouTube Data API videos.list statistics. TikTok view counts use an operator-configured statistics adapter. Missing provider credentials or unsupported links remain unavailable; they are never displayed as zero.
- Native media storage defaults to a `highest_media` directory beside the Highest SQLite database; `HIGHEST_MEDIA_DIR` can override the path.

Environment configuration:
- `HIGHEST_YOUTUBE_API_KEY`: YouTube Data API key for livestream polling, channel challenge verification, and YouTube clip view counts.
- `HIGHEST_TIKTOK_STATUS_URL` + `HIGHEST_TIKTOK_STATUS_TOKEN`: existing operator-configured TikTok live-status provider.
- `HIGHEST_TIKTOK_PROFILE_URL` + `HIGHEST_TIKTOK_PROFILE_TOKEN`: HTTPS profile verification adapter; GET with `username` query and Bearer token must return `{ "username": "...", "bio": "..." }`.
- `HIGHEST_TIKTOK_STATS_URL` + `HIGHEST_TIKTOK_STATS_TOKEN`: HTTPS statistics adapter; GET with `url` query and Bearer token must return `{ "views": 123 }`.
- TikTok adapters are integration contracts, not a claim that TikTok provides these endpoints publicly. Configure only a provider that is authorized to access the relevant account/profile data.
