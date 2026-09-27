# -- coding: utf-8 --

##############################################################################
#                                                                            #
# Part of WebbyCrown Solutions (Website: www.webbycrown.com).                #
# Copyright © 2025 WebbyCrown Solutions. All Rights Reserved.                #
#                                                                            #
##############################################################################

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class PharmacyDrugCategory(models.Model):
    _name = 'pharmacy.drug.category'
    _description = 'Drug Category'

    name = fields.Char(required=True)
    code = fields.Char()
    controlled = fields.Boolean()
    description = fields.Text()


class PharmacyDrug(models.Model):
    _name = 'pharmacy.drug'
    _description = 'Drug'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    sale_price = fields.Float(
        string='Sale Price',
        tracking=True,
        help='Retail price per unit shown in the Point of Sale.',
    )
    product_id = fields.Many2one(
        'product.template',
        readonly=True,
        copy=False,
        help='Product automatically created for the Point of Sale. Managed by the system.',
    )
    drug_category_id = fields.Many2one('pharmacy.drug.category')
    is_prescription_required = fields.Boolean()
    controlled = fields.Boolean()
    storage_temp_min = fields.Float()
    storage_temp_max = fields.Float()
    ingredient_ids = fields.One2many('pharmacy.drug.ingredient', 'drug_id')
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        required=True,
        tracking=True,
    )
    pharmacy_ids = fields.Many2many(
        'pharmacy.pharmacy',
        'pharmacy_drug_pharmacy_rel',
        'drug_id',
        'pharmacy_id',
        string='Branches',
        tracking=True,
    )
    coverage_ids = fields.One2many(
        'pharmacy.drug.coverage',
        'drug_id',
        string='Branch Stock Levels',
    )

    # Smart button counts
    prescription_count = fields.Integer(string='Prescriptions', compute='_compute_prescription_count')
    stock_qty_available = fields.Float(string='Available Stock', compute='_compute_stock_qty')
    expiry_alert_count = fields.Integer(
        string='Expiring Lots',
        compute='_compute_expiry_alerts',
        compute_sudo=True,
    )
    has_expiring_lots = fields.Boolean(
        string='Has Expiring Lots',
        compute='_compute_expiry_alerts',
        search='_search_expiring_lots',
        compute_sudo=True,
    )
    has_shortage = fields.Boolean(
        string='Low Stock',
        compute='_compute_has_shortage',
        search='_search_has_shortage',
        compute_sudo=True,
    )

    # -------------------------------------------------------------------------
    # Product / POS linkage
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        drugs = super().create(vals_list)
        for drug in drugs:
            if not drug.product_id:
                drug._create_pos_product()
        return drugs

    def write(self, vals):
        res = super().write(vals)
        if 'name' in vals or 'sale_price' in vals:
            for drug in self:
                if drug.product_id:
                    product_vals = {}
                    if 'name' in vals:
                        product_vals['name'] = drug.name
                    if 'sale_price' in vals:
                        product_vals['list_price'] = drug.sale_price
                    drug.product_id.sudo().write(product_vals)
        return res

    def _create_pos_product(self):
        """Create the POS-ready product linked to this drug."""
        self.ensure_one()
        PosCategory = self.env['pos.category'].sudo()
        category = PosCategory.search([('name', '=', 'Medicines')], limit=1)
        if not category:
            category = PosCategory.create({'name': 'Medicines'})
        product = self.env['product.template'].sudo().create({
            'name': self.name,
            'list_price': self.sale_price,
            'type': 'consu',
            'is_storable': True,
            'available_in_pos': True,
            'pos_categ_ids': [(4, category.id)],
            'company_id': self.company_id.id,
        })
        self.product_id = product.id

    def action_view_product(self):
        self.ensure_one()
        if not self.product_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': 'Product',
            'res_model': 'product.template',
            'view_mode': 'form',
            'res_id': self.product_id.id,
            'target': 'current',
        }

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------

    @api.depends('product_id')
    def _compute_prescription_count(self):
        for rec in self:
            rec.prescription_count = self.env['pharmacy.prescription.line'].search_count([
                ('drug_id', '=', rec.id)
            ])

    @api.depends('product_id')
    def _compute_stock_qty(self):
        for rec in self:
            if rec.product_id:
                product = self.env['product.product'].search(
                    [('product_tmpl_id', '=', rec.product_id.id)], limit=1)
                rec.stock_qty_available = product.qty_available if product else 0.0
            else:
                rec.stock_qty_available = 0.0

    @api.depends('product_id')
    def _compute_expiry_alerts(self):
        for rec in self:
            rec.expiry_alert_count, rec.has_expiring_lots = rec._get_expiry_alerts()

    def _get_expiry_alerts(self):
        self.ensure_one()
        if not self.product_id:
            return 0, False
        product = self.env['product.product'].search(
            [('product_tmpl_id', '=', self.product_id.id)], limit=1)
        if not product:
            return 0, False
        today = fields.Date.today()
        future_date = today + relativedelta(days=30)
        count = self.env['stock.lot'].search_count([
            ('product_id', '=', product.id),
            ('expiry_date', '!=', False),
            ('expiry_date', '<=', future_date),
            ('expiry_date', '>=', today)
        ])
        return count, count > 0

    def _search_expiring_lots(self, operator, value):
        # Boolean leafs arrive as 'in'/'not in'; support 'in' and let the
        # ORM derive negations.
        if operator != 'in':
            return NotImplemented
        today = fields.Date.today()
        future_date = today + relativedelta(days=30)
        lots = self.env['stock.lot'].search([
            ('expiry_date', '!=', False),
            ('expiry_date', '<=', future_date),
            ('expiry_date', '>=', today)
        ])
        product_ids = lots.mapped('product_id').ids
        drug_ids = []
        if product_ids:
            product_tmpl_ids = self.env['product.product'].browse(product_ids).mapped('product_tmpl_id').ids
            drug_ids = self.env['pharmacy.drug'].search([
                ('product_id', 'in', product_tmpl_ids)
            ]).ids
        if True in value:
            return [('id', 'in', drug_ids)]
        return [('id', 'not in', drug_ids)]

    def _compute_has_shortage(self):
        for rec in self:
            rec.has_shortage = any(rec.coverage_ids.mapped('shortage_flag'))

    def _search_has_shortage(self, operator, value):
        if operator != 'in':
            return NotImplemented
        coverage = self.env['pharmacy.drug.coverage'].search([('shortage_flag', '=', True)])
        drug_ids = coverage.mapped('drug_id').ids
        if True in value:
            return [('id', 'in', drug_ids)]
        return [('id', 'not in', drug_ids)]

    # -------------------------------------------------------------------------
    # Smart buttons
    # -------------------------------------------------------------------------

    def action_view_prescriptions(self):
        self.ensure_one()
        line_ids = self.env['pharmacy.prescription.line'].search(
            [('drug_id', '=', self.id)]).mapped('prescription_id').ids
        return {
            'type': 'ir.actions.act_window',
            'name': 'Prescriptions',
            'res_model': 'pharmacy.prescription',
            'domain': [('id', 'in', line_ids)],
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_view_stock(self):
        self.ensure_one()
        if not self.product_id:
            return False
        product = self.env['product.product'].search(
            [('product_tmpl_id', '=', self.product_id.id)], limit=1)
        if not product:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': 'Stock',
            'res_model': 'stock.quant',
            'domain': [('product_id', '=', product.id)],
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_view_expiring_lots(self):
        self.ensure_one()
        if not self.product_id:
            return False
        product = self.env['product.product'].search(
            [('product_tmpl_id', '=', self.product_id.id)], limit=1)
        if not product:
            return False
        today = fields.Date.today()
        future_date = today + relativedelta(days=30)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Expiring Lots',
            'res_model': 'stock.lot',
            'domain': [
                ('product_id', '=', product.id),
                ('expiry_date', '!=', False),
                ('expiry_date', '<=', future_date),
                ('expiry_date', '>=', today)
            ],
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_view_coverage(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Branch Stock Levels',
            'res_model': 'pharmacy.drug.coverage',
            'domain': [('drug_id', '=', self.id)],
            'view_mode': 'list,form,pivot',
            'target': 'current',
        }


class PharmacyDrugIngredient(models.Model):
    _name = 'pharmacy.drug.ingredient'
    _description = 'Drug Ingredient'

    name = fields.Char(required=True)
    strength = fields.Char()
    unit = fields.Char()
    drug_id = fields.Many2one('pharmacy.drug', required=True, ondelete='cascade')
    substitutable = fields.Boolean(default=True)


class StockProductionLot(models.Model):
    _inherit = 'stock.lot'

    pharmacy_id = fields.Many2one('pharmacy.pharmacy')
    recall_flag = fields.Boolean()
    recall_reason = fields.Text()
    temp_log = fields.Json()
    expiry_date = fields.Date()


class PharmacyDrugCoverage(models.Model):
    """Per-branch stock level configuration with shortage / expiry alerts."""
    _name = 'pharmacy.drug.coverage'
    _description = 'Drug Branch Stock Level'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'display_name'

    drug_id = fields.Many2one('pharmacy.drug', required=True, ondelete='cascade', tracking=True)
    pharmacy_id = fields.Many2one(
        'pharmacy.pharmacy', required=True, tracking=True,
        domain="[('company_id', 'in', [company_id, False])]",
    )
    company_id = fields.Many2one('res.company', related='drug_id.company_id', store=True, readonly=True)
    min_qty = fields.Float(default=0.0, help='Alert threshold: flagged as shortage below this quantity.')
    target_qty = fields.Float(default=0.0)
    max_qty = fields.Float(default=0.0)
    current_qty = fields.Float(compute='_compute_current_qty')
    shortage_flag = fields.Boolean(compute='_compute_shortage_flag', search='_search_shortage_flag')
    has_expiring_lots = fields.Boolean(compute='_compute_has_expiring', search='_search_has_expiring_lots')
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _uniq_drug_pharmacy = models.Constraint(
        'unique (drug_id, pharmacy_id)',
        'Each drug can only have one stock level per branch.',
    )

    @api.depends('drug_id.name', 'pharmacy_id.name')
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.drug_id.name or '', rec.pharmacy_id.name or '']
            rec.display_name = ' - '.join(filter(None, parts))

    @api.depends('drug_id', 'pharmacy_id')
    def _compute_current_qty(self):
        StockQuant = self.env['stock.quant']
        for rec in self:
            qty = 0.0
            if rec.drug_id and rec.drug_id.product_id and rec.pharmacy_id:
                product = self.env['product.product'].search([
                    ('product_tmpl_id', '=', rec.drug_id.product_id.id)
                ], limit=1)
                if product and rec.pharmacy_id.location_id:
                    qty = sum(StockQuant.search([
                        ('product_id', '=', product.id),
                        ('location_id', 'child_of', rec.pharmacy_id.location_id.id)
                    ]).mapped('quantity'))
            rec.current_qty = qty

    @api.depends('current_qty', 'min_qty')
    def _compute_shortage_flag(self):
        for rec in self:
            rec.shortage_flag = rec.current_qty < rec.min_qty if rec.min_qty else False

    def _search_shortage_flag(self, operator, value):
        # Boolean leafs reach search methods normalized to 'in'/'not in';
        # implement 'in' only and let the ORM derive the rest (as core does).
        if operator != 'in':
            return NotImplemented
        all_recs = self.browse(self._search([]))
        short_ids = [c.id for c in all_recs if c.shortage_flag]
        if True in value:
            return [('id', 'in', short_ids)]
        return [('id', 'not in', short_ids)]

    def _search_has_expiring_lots(self, operator, value):
        if operator != 'in':
            return NotImplemented
        all_recs = self.browse(self._search([]))
        expiring_ids = [c.id for c in all_recs if c.has_expiring_lots]
        if True in value:
            return [('id', 'in', expiring_ids)]
        return [('id', 'not in', expiring_ids)]

    @api.depends('drug_id', 'pharmacy_id')
    def _compute_has_expiring(self):
        StockLot = self.env['stock.lot']
        for rec in self:
            has_expiring = False
            if rec.drug_id and rec.drug_id.product_id and rec.pharmacy_id:
                product = self.env['product.product'].search([
                    ('product_tmpl_id', '=', rec.drug_id.product_id.id)
                ], limit=1)
                if product:
                    today = fields.Date.today()
                    future_date = today + relativedelta(days=30)
                    has_expiring = bool(StockLot.search_count([
                        ('product_id', '=', product.id),
                        ('expiry_date', '!=', False),
                        ('expiry_date', '>=', today),
                        ('expiry_date', '<=', future_date),
                        ('pharmacy_id', '=', rec.pharmacy_id.id),
                    ]))
            rec.has_expiring_lots = has_expiring
