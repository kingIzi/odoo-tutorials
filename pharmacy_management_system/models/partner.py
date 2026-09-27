# -- coding: utf-8 --

##############################################################################
#                                                                            #
# Part of WebbyCrown Solutions (Website: www.webbycrown.com).                #
# Copyright © 2025 WebbyCrown Solutions. All Rights Reserved.                #
#                                                                            #
##############################################################################

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Patient / doctor flags used across the pharmacy workflow
    is_patient = fields.Boolean(string='Is a Patient')
    is_doctor = fields.Boolean(string='Is a Prescriber')

    # Patient metadata
    gender = fields.Selection(
        [('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
    )
    dob = fields.Date(string='Date of Birth')
    medical_record_no = fields.Char(
        string='Medical Record No.',
        help='External medical record number assigned by the clinic.',
    )
    blood_type = fields.Selection(
        [
            ('a+', 'A+'), ('a-', 'A-'), ('b+', 'B+'), ('b-', 'B-'),
            ('ab+', 'AB+'), ('ab-', 'AB-'), ('o+', 'O+'), ('o-', 'O-'),
        ],
    )
    allergy_note = fields.Text()
    chronic_conditions = fields.Text()
    preferred_pharmacy_id = fields.Many2one('pharmacy.pharmacy', string='Preferred Branch')
    loyalty_card = fields.Char()

    # Doctor metadata
    license_number = fields.Char()
    specialty = fields.Char()
    default_pharmacy_id = fields.Many2one('pharmacy.pharmacy', string='Default Branch')

    _uniq_doctor_license_company = models.Constraint(
        'unique (license_number, company_id)',
        'The prescriber license number must be unique per company.',
    )
    _uniq_medical_record_company = models.Constraint(
        'unique (medical_record_no, company_id)',
        'The medical record number must be unique per company.',
    )

    @api.constrains('license_number')
    def _check_license_number(self):
        for rec in self:
            if rec.is_doctor and not rec.license_number:
                raise ValidationError('Prescribers must have a license number.')

    # Smart button support ------------------------------------------------

    prescription_count = fields.Integer(string='Prescriptions', compute='_compute_prescription_count')
    rx_count_total = fields.Integer(string='Total RX', compute='_compute_prescription_count')

    def _compute_prescription_count(self):
        Prescription = self.env['pharmacy.prescription']
        for rec in self:
            rec.prescription_count = Prescription.search_count([('patient_id', '=', rec.id)])
            rec.rx_count_total = Prescription.search_count([('doctor_id', '=', rec.id)])

    def action_view_prescriptions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Prescriptions',
            'res_model': 'pharmacy.prescription',
            'domain': [('patient_id', '=', self.id)],
            'view_mode': 'list,form',
            'target': 'current',
        }
