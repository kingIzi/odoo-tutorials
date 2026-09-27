# -- coding: utf-8 --

##############################################################################
#                                                                            #
# Part of WebbyCrown Solutions (Website: www.webbycrown.com).                #
# Copyright © 2025 WebbyCrown Solutions. All Rights Reserved.                #
#                                                                            #
##############################################################################

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class PharmacyPharmacy(models.Model):
    _name = 'pharmacy.pharmacy'
    _description = 'Pharmacy Branch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(required=True)
    code = fields.Char(
        help='Unique code for this pharmacy branch within the company. Used for identification and reporting.'
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        help='Main warehouse used to source stock for this pharmacy.',
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
        help='Company that owns this pharmacy branch.',
    )
    address_id = fields.Many2one('res.partner', string='Address')
    location_id = fields.Many2one(
        'stock.location',
        help='Primary stock location for this pharmacy. Auto-derived from the warehouse when not set.',
    )
    pricelist_id = fields.Many2one(
        'product.pricelist',
        help='Default pricelist used for sales and pricing at this pharmacy branch.',
    )
    parent_pharmacy_id = fields.Many2one('pharmacy.pharmacy', string='Parent Pharmacy')
    compliance_cert_no = fields.Char(string='License Number')
    active = fields.Boolean(default=True)

    # Point of sale ---------------------------------------------------------
    pos_config_id = fields.Many2one(
        'pos.config',
        string='POS Register',
        readonly=True,
        copy=False,
        help='Point of sale register for this branch. Created automatically.',
    )
    create_register = fields.Boolean(
        string='Create POS Register',
        default=True,
        help='Create a Point of Sale register when this branch is saved.',
    )

    # KPIs / smart button counts
    daily_sales_count = fields.Integer(
        string="Today's Sales",
        compute='_compute_kpis',
        help='Number of POS orders processed today at this branch.',
    )
    rx_count_today = fields.Integer(
        string='Prescriptions Today',
        compute='_compute_kpis',
    )
    shortage_alerts_count = fields.Integer(
        string='Shortage Alerts',
        compute='_compute_kpis',
        help='Number of drugs below minimum stock threshold at this branch.',
    )
    expiring_lots_count = fields.Integer(
        string='Expiring Lots',
        compute='_compute_kpis',
        help='Number of stock lots expiring within the next 30 days at this branch.',
    )

    _code_company_uniq = models.Constraint(
        'unique (code, company_id)',
        'Pharmacy code must be unique per company.',
    )

    # -------------------------------------------------------------------------
    # CRUD: auto-derive location and provision the POS register
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        branches = super().create(vals_list)
        for branch in branches:
            if not branch.location_id and branch.warehouse_id:
                branch.location_id = branch.warehouse_id.lot_stock_id
            if branch.create_register and not branch.pos_config_id:
                branch._create_pos_config()
        return branches

    def write(self, vals):
        res = super().write(vals)
        if 'create_register' in vals or 'warehouse_id' in vals or 'location_id' in vals:
            for branch in self:
                if not branch.location_id and branch.warehouse_id:
                    branch.location_id = branch.warehouse_id.lot_stock_id
                if branch.create_register and not branch.pos_config_id:
                    branch._create_pos_config()
        return res

    def _create_pos_config(self):
        """Provision a POS register for this branch.

        Creates a dedicated outgoing picking type sourcing from the branch
        location so POS sales deduct stock from the right branch, then a
        pos.config wired for automatic receipts and customer invoicing.
        """
        self.ensure_one()
        self = self.sudo()
        if not self.location_id:
            raise UserError(
                "Please set a warehouse or stock location on branch %s before creating a POS register."
                % self.name
            )

        PickingType = self.env['stock.picking.type']
        sequence = self.env['ir.sequence'].sudo().create({
            'name': f'{self.name} POS Delivery',
            'code': 'stock.picking',
            'prefix': f'POS/{(self.code or self.name)[:4].upper()}/',
            'padding': 5,
            'company_id': self.company_id.id,
        })
        picking_type = PickingType.create({
            'name': f'{self.name} POS Deliveries',
            'code': 'outgoing',
            'sequence_code': 'outgoing',
            'sequence_id': sequence.id,
            'warehouse_id': self.warehouse_id.id,
            'default_location_src_id': self.location_id.id,
            'default_location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'company_id': self.company_id.id,
        })

        config_vals = {
            'name': f'{self.name} Register',
            'company_id': self.company_id.id,
            'branch_id': self.id,
            'picking_type_id': picking_type.id,
            'warehouse_id': self.warehouse_id.id,
            'receipt_header': 'Mama Pharmacy',
            'receipt_footer': f'{self.name} - Thank you & get well soon!',
            'iface_print_auto': True,
            'use_pricelist': bool(self.pricelist_id),
        }
        if self.pricelist_id:
            config_vals['pricelist_id'] = self.pricelist_id.id
            config_vals['available_pricelist_ids'] = [(4, self.pricelist_id.id)]

        # Invoice journal: reuse an existing sale journal, or create one
        sale_journal = self.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', self.company_id.id)
        ], limit=1)
        if not sale_journal:
            sale_journal = self.env['account.journal'].create({
                'name': 'POS Invoices',
                'code': 'MPINV',
                'type': 'sale',
                'company_id': self.company_id.id,
            })
        config_vals['journal_id'] = sale_journal.id

        # Cash journal + payment method must be dedicated to this register
        # (Odoo forbids sharing cash payment methods across POS configs).
        Journal = self.env['account.journal']
        journal_code = f"{(self.code or self.name)[:4].upper()}C"
        cash_journal = Journal.search([
            ('code', '=', journal_code), ('company_id', '=', self.company_id.id)
        ], limit=1)
        if not cash_journal:
            cash_journal = Journal.create({
                'name': f'{self.name} Cash',
                'code': journal_code,
                'type': 'cash',
                'company_id': self.company_id.id,
            })
        payment_method = self.env['pos.payment.method'].create({
            'name': f'Cash ({self.name})',
            'type': 'cash',
            'journal_id': cash_journal.id,
            'company_id': self.company_id.id,
        })
        config_vals['payment_method_ids'] = [(4, payment_method.id)]
        # The closing entry is a sale document in this version, so the
        # closing journal must be a dedicated sale journal.
        closing_code = f"{(self.code or 'MP')[:3].upper()}CL"
        closing_journal = Journal.search([
            ('code', '=', closing_code), ('company_id', '=', self.company_id.id)
        ], limit=1)
        if not closing_journal:
            closing_journal = Journal.create({
                'name': f'{self.name} Closing',
                'code': closing_code,
                'type': 'sale',
                'company_id': self.company_id.id,
            })
        config_vals['closing_journal_id'] = closing_journal.id

        # Show only medicines in the register
        medicines_categ = self.env['pos.category'].search([('name', '=', 'Medicines')], limit=1)
        if medicines_categ:
            config_vals['limit_categories'] = True
            config_vals['iface_available_categ_ids'] = [(4, medicines_categ.id)]

        config = self.env['pos.config'].create(config_vals)
        self.pos_config_id = config.id

    # -------------------------------------------------------------------------
    # KPIs
    # -------------------------------------------------------------------------

    @api.depends('company_id')
    def _compute_kpis(self):
        Prescription = self.env['pharmacy.prescription']
        PosOrder = self.env['pos.order']
        Lot = self.env['stock.lot']
        Coverage = self.env['pharmacy.drug.coverage']
        today = fields.Date.today()
        future_date = today + relativedelta(days=30)

        branch_ids = self.ids
        rx_counts = {}
        sales_counts = {}
        if branch_ids:
            rx_data = Prescription.read_group(
                [('pharmacy_id', 'in', branch_ids), ('date_prescribed', '=', today)],
                ['pharmacy_id'], ['__count'],
            )
            rx_counts = {k: v for k, v in rx_data if k}
            Config = self.env['pos.config']
            configs = Config.search([('branch_id', 'in', branch_ids)])
            if configs:
                pos_data = PosOrder.read_group(
                    [
                        ('config_id', 'in', configs.ids),
                        ('date_order', '>=', fields.Datetime.now().replace(hour=0, minute=0, second=0)),
                    ],
                    ['config_id'], ['__count'],
                )
                by_config = {k: v for k, v in pos_data if k}
                for config in configs:
                    if config.branch_id:
                        sales_counts[config.branch_id.id] = (
                            sales_counts.get(config.branch_id.id, 0) + by_config.get(config.id, 0)
                        )

        expiring_counts = {}
        if branch_ids:
            lot_data = Lot.read_group(
                [
                    ('pharmacy_id', 'in', branch_ids),
                    ('expiry_date', '!=', False),
                    ('expiry_date', '>=', today),
                    ('expiry_date', '<=', future_date),
                ],
                ['pharmacy_id'], ['__count'],
            )
            expiring_counts = {k: v for k, v in lot_data if k}

        shortage_counts = {}
        if branch_ids:
            for branch in self:
                shortage_counts[branch.id] = Coverage.search_count([
                    ('pharmacy_id', '=', branch.id),
                    ('shortage_flag', '=', True),
                ])

        for rec in self:
            rec.rx_count_today = rx_counts.get(rec.id, 0)
            rec.daily_sales_count = sales_counts.get(rec.id, 0)
            rec.expiring_lots_count = expiring_counts.get(rec.id, 0)
            rec.shortage_alerts_count = shortage_counts.get(rec.id, 0)

    # -------------------------------------------------------------------------
    # Smart buttons
    # -------------------------------------------------------------------------

    def action_open_register(self):
        """Open (or start a session on) this branch's POS register."""
        self.ensure_one()
        if not self.pos_config_id:
            self.sudo()._create_pos_config()
        return self.pos_config_id.open_session_if_not_opened()

    def action_view_prescriptions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Branch Prescriptions',
            'res_model': 'pharmacy.prescription',
            'view_mode': 'list,form',
            'domain': [('pharmacy_id', '=', self.id)],
            'target': 'current',
        }

    # -------------------------------------------------------------------------
    # Demo data helpers (invoked from data/demo.xml)
    # -------------------------------------------------------------------------

    @api.model
    def purge_demo_data(self):
        """One-time cleanup before the demo pack loads: remove leftover
        records from the previous (hospital-era) install, together with
        their external IDs, so the fresh demo records insert cleanly.

        Guarded by the demo_stock_seeded flag — it runs only before the
        first successful demo load and never wipes data entered afterwards.
        """
        params = self.env['ir.config_parameter'].sudo()
        if params.get_str('pharmacy_management_system.demo_stock_seeded'):
            return True

        # Tables of models removed in this version still hold rows that
        # reference the records we need to purge (RESTRICT foreign keys).
        # Odoo only drops these tables after a fully successful upgrade, so
        # clear them first, children before parents. NOTE: hospital_hospital
        # is cleared later — old coverage rows reference it until the ORM
        # purge below has removed them.
        orphan_tables = [
            'hospital_treatment_prescription_rel',
            'hospital_treatment',
            'hospital_treatment_stage',
            'pharmacy_insurance_claim',
            'pharmacy_return_quarantine',
            'pharmacy_controlled_log',
            'pharmacy_portal_request',
            'hospital_department',
            'hospital_api_config',
            'hospital_patient',
            'portal_message_config',
            'pharmacy_alert_rule',
            'pharmacy_substitution_map',
            'pharmacy_config',
        ]
        cr = self.env.cr
        cr.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        existing = {row[0] for row in cr.fetchall()}
        for table in orphan_tables:
            if table in existing:
                cr.execute(f'DELETE FROM "{table}"')

        # Lots (and quants) from the old install. hospital_id no longer
        # exists as an ORM field on stock.lot, so purge at SQL level.
        cr.execute(
            "DELETE FROM stock_quant WHERE lot_id IN ("
            " SELECT id FROM stock_lot WHERE pharmacy_id IS NOT NULL"
            "  OR hospital_id IS NOT NULL)"
        )
        cr.execute(
            "DELETE FROM stock_lot WHERE pharmacy_id IS NOT NULL"
            " OR hospital_id IS NOT NULL"
        )

        purge_models = [
            'pharmacy.drug.coverage',
            'pharmacy.prescription',
            'pharmacy.drug.ingredient',
            'pharmacy.drug',
            'pharmacy.resource.availability',
            'pharmacy.pharmacy',
        ]
        IrModelData = self.env['ir.model.data']
        for model_name in purge_models:
            self.env[model_name].search([]).unlink()
            # Drop stale external IDs so the demo pack recreates records
            # with the same XML ids from scratch.
            IrModelData.search([
                ('module', '=', 'pharmacy_management_system'),
                ('model', '=', model_name),
            ]).unlink()

        # Old coverage/prescription rows (with their legacy hospital_id
        # columns) are gone now, so hospitals can be cleared safely.
        if 'hospital_hospital' in existing:
            cr.execute('DELETE FROM "hospital_hospital"')
        return True

    @api.model
    def load_demo_stock(self):
        """Seed stock lots and quantities for the demo branches.

        Idempotent: guarded by an ir.config_parameter flag so repeated
        module upgrades do not duplicate the stock.
        """
        import datetime

        params = self.env['ir.config_parameter'].sudo()
        if params.get_str('pharmacy_management_system.demo_stock_seeded'):
            return True

        today = datetime.date.today()
        branches = self.search([])
        if not branches:
            return True

        # (lot_offset_days, qty) per branch code suffix
        plan = [
            ('MP1', [(12, 60), (45, 60)]),   # one lot expiring soon, one healthy
            ('MP2', [(25, 40), (80, 40)]),
            ('MP3', [(120, 50)]),
        ]
        Lot = self.env['stock.lot']
        Quant = self.env['stock.quant']
        for branch in branches:
            lot_plan = next((p for c, p in plan if (branch.code or '').startswith(c)), plan[0])
            if not branch.location_id:
                continue
            for drug in self.env['pharmacy.drug'].search([]):
                product = self.env['product.product'].search(
                    [('product_tmpl_id', '=', drug.product_id.id)], limit=1)
                if not product:
                    continue
                quants = Quant
                for offset_days, qty in lot_plan:
                    lot = Lot.create({
                        'name': f'LOT/{branch.code or "MP"}/{drug.id:03d}/{offset_days}D',
                        'product_id': product.id,
                        'pharmacy_id': branch.id,
                        'expiry_date': today + datetime.timedelta(days=offset_days),
                    })
                    quants |= Quant.create({
                        'product_id': product.id,
                        'location_id': branch.location_id.id,
                        'lot_id': lot.id,
                        'inventory_quantity': qty,
                    })
                if quants:
                    quants.action_apply_inventory()

        params.set_str('pharmacy_management_system.demo_stock_seeded', '1')
        return True

    def action_view_shortages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Shortage Alerts',
            'res_model': 'pharmacy.drug.coverage',
            'view_mode': 'list,form',
            'domain': [('pharmacy_id', '=', self.id), ('shortage_flag', '=', True)],
            'target': 'current',
        }

    def action_view_expiring_lots(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Branch Expiring Lots',
            'res_model': 'stock.lot',
            'view_mode': 'list,form',
            'domain': [
                ('pharmacy_id', '=', self.id),
                ('expiry_date', '!=', False),
            ],
            'target': 'current',
        }


class PosConfigBranch(models.Model):
    _inherit = 'pos.config'

    branch_id = fields.Many2one(
        'pharmacy.pharmacy',
        string='Pharmacy Branch',
        help='Branch this register belongs to.',
    )
