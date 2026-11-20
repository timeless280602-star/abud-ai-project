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
