# -- coding: utf-8 --

##############################################################################
#                                                                            #
# Part of WebbyCrown Solutions (Website: www.webbycrown.com).                #
# Copyright © 2025 WebbyCrown Solutions. All Rights Reserved.                #
#                                                                            #
##############################################################################

from odoo import api, fields, models
from odoo.exceptions import UserError


class PharmacyPrescription(models.Model):
    """What the doctor prescribed — the sale itself happens in the POS."""
    _name = 'pharmacy.prescription'
    _description = 'Prescription'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(
        required=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('pharmacy.prescription') or '/'
    )
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    pharmacy_id = fields.Many2one(
        'pharmacy.pharmacy',
        required=True,
        string='Branch',
        domain="[('company_id', 'in', [company_id, False])]",
    )
    patient_id = fields.Many2one('res.partner', domain="[('is_patient','=',True)]", required=True)
    doctor_id = fields.Many2one('res.partner', domain="[('is_doctor','=',True)]", required=True)
    date_prescribed = fields.Date(default=fields.Date.context_today)
    state = fields.Selection([
        ('draft', 'New'), ('done', 'Done'), ('cancel', 'Canceled')
    ], default='draft', tracking=True)
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    line_ids = fields.One2many('pharmacy.prescription.line', 'prescription_id')

    # Pivot view count field
    count_field = fields.Integer(string='Count', compute='_compute_count_field', store=True, default=1)

    def _compute_count_field(self):
        for rec in self:
            rec.count_field = 1

    # Search fields
    drug_ids = fields.Many2many(
        'pharmacy.drug', string='Drugs',
        compute='_compute_drug_ids', search='_search_drug_ids', store=False)

    @api.depends('line_ids.drug_id')
    def _compute_drug_ids(self):
        for rec in self:
            rec.drug_ids = rec.line_ids.mapped('drug_id')

    def _search_drug_ids(self, operator, value):
        """Search prescriptions by drug"""
        if isinstance(value, str):
            drug_ids = self.env['pharmacy.drug'].search([('name', 'ilike', value)]).ids
            line_ids = self.env['pharmacy.prescription.line'].search([
                ('drug_id', 'in', drug_ids)
            ]).mapped('prescription_id').ids
        else:
            line_ids = self.env['pharmacy.prescription.line'].search([
                ('drug_id', operator, value)
            ]).mapped('prescription_id').ids
        return [('id', 'in', line_ids)] if line_ids else [('id', '=', False)]

    # -------------------------------------------------------------------------
    # Workflow
    # -------------------------------------------------------------------------

    def action_mark_done(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError("Only new prescriptions can be marked as done.")
            rec.state = 'done'

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError("Cannot cancel a prescription that is already done.")
            rec.state = 'cancel'

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state != 'cancel':
                raise UserError("Only canceled prescriptions can be reset.")
            rec.state = 'draft'

    def action_open_register(self):
        """Jump straight to the branch register to sell the prescription."""
        self.ensure_one()
        return self.pharmacy_id.action_open_register()


class PharmacyPrescriptionLine(models.Model):
    _name = 'pharmacy.prescription.line'
    _description = 'Prescription Line'

    prescription_id = fields.Many2one('pharmacy.prescription', required=True, ondelete='cascade')
    pharmacy_id = fields.Many2one(related='prescription_id.pharmacy_id', store=True)
    company_id = fields.Many2one(
        'res.company',
        related='prescription_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    drug_id = fields.Many2one('pharmacy.drug', required=True)
    dosage = fields.Char()
    qty_prescribed = fields.Float(default=1.0)
    uom_id = fields.Many2one('uom.uom')
